"""IRSA TAP discovery adapter for the SPHEREx archive."""

from __future__ import annotations

import hashlib
import io
import json
import logging
import re
import time
import xml.etree.ElementTree as ET
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from datetime import time as datetime_time
from pathlib import Path
from typing import Any

import requests
from astropy.io.votable import parse_single_table
from pydantic import ValidationError
from requests import Session
from requests.exceptions import ConnectionError, Timeout

from changelens.contracts import (
    DiscoveryResult,
    DiscoveryStatus,
    InvestigationRequest,
    ObservationRecord,
)
from changelens.data.network import ARCHIVE_REQUEST_GATE

TAP_URL = "https://irsa.ipac.caltech.edu/TAP/sync"
MAX_RECORDS = 50000
MAX_ATTEMPTS = 3
TIMEOUT = (10.0, 60.0)
BACKOFF_SECONDS = 0.5
DEFAULT_ARTIFACT_DIRECTORY = Path(__file__).resolve().parents[4] / "data" / "target_queries"
LOGGER = logging.getLogger(__name__)


def _quote_adql(value: str) -> str:
    return value.replace("'", "''")


def _mjd_from_date(value: datetime) -> float:
    epoch = datetime(1858, 11, 17, tzinfo=UTC)
    normalized = datetime.combine(value.date(), datetime_time.min, tzinfo=UTC)
    return (normalized - epoch).total_seconds() / 86400.0


def _build_query(request: InvestigationRequest) -> str:
    ra = format(request.ra_deg, ".15g")
    dec = format(request.dec_deg, ".15g")
    size_deg = format(request.fov_arcmin / 60.0, ".12g")
    cutout_url = (
        "'https://irsa.ipac.caltech.edu/' || a.uri || "
        f"'?center={ra},{dec}d&size={size_deg}'"
    )
    predicates = [
        f"1=CONTAINS(POINT('{_quote_adql(request.frame)}', {ra}, {dec}), p.poly)",
        "a.producttype = 'science'",
        "a.contenttype = 'image/fits'",
    ]
    if request.collection:
        collection = request.collection.strip().casefold()
        if collection.startswith("spherex_"):
            collection = collection.removeprefix("spherex_")
        collection = _quote_adql(collection)
        predicates.append(f"a.uri LIKE '%/spherex/{collection}/%'")
    if request.band_policy != "SAME_SUPPORTED_BAND":
        band = _quote_adql(request.band_policy.strip())
        predicates.append(f"p.energy_bandpassname = '{band}'")
    if request.start_date:
        start = datetime.combine(request.start_date, datetime_time.min, tzinfo=UTC)
        predicates.append(f"p.time_bounds_lower >= {_mjd_from_date(start):.12g}")
    if request.end_date:
        end_exclusive = datetime.combine(
            request.end_date + timedelta(days=1), datetime_time.min, tzinfo=UTC
        )
        predicates.append(f"p.time_bounds_lower < {_mjd_from_date(end_exclusive):.12g}")

    where = "\n  AND ".join(predicates)
    return (
        "SELECT\n"
        f"  {cutout_url} AS access_url,\n"
        "  p.planeid AS planeid,\n"
        "  a.uri AS artifact_path,\n"
        "  p.time_bounds_lower AS time_mjd,\n"
        "  p.energy_bandpassname AS band,\n"
        "  p.dataproducttype AS product,\n"
        "  p.position_dimension_naxis1 AS width,\n"
        "  p.position_dimension_naxis2 AS height,\n"
        "  p.poly AS footprint,\n"
        "  a.contentchecksum AS remote_checksum\n"
        "FROM spherex.artifact AS a\n"
        "JOIN spherex.plane AS p ON a.planeid = p.planeid\n"
        f"WHERE {where}\n"
        "ORDER BY p.time_bounds_lower"
    )


def _query_status(payload: bytes) -> tuple[str, ...] | None:
    try:
        root = ET.fromstring(payload)
    except ET.ParseError:
        return None
    statuses = tuple(
        element.attrib.get("value", "").upper()
        for element in root.iter()
        if element.tag.rsplit("}", 1)[-1] == "INFO"
        and element.attrib.get("name") == "QUERY_STATUS"
    )
    return statuses or None


def _cell(row: Any, name: str, default: Any = None) -> Any:
    if name not in row.colnames:
        return default
    value = row[name]
    if getattr(value, "mask", False):
        return default
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if hasattr(value, "item"):
        value = value.item()
    return value


def _release_from_artifact_path(path: str) -> str | None:
    match = re.search(r"/spherex/([^/]+)/", path, flags=re.IGNORECASE)
    return match.group(1).upper() if match else None


def _product_family_from_artifact_path(path: str) -> str | None:
    match = re.search(r"/spherex/[^/]+/([^/]+)/", path, flags=re.IGNORECASE)
    return match.group(1).upper() if match else None


def _observation(row: Any) -> ObservationRecord:
    plane_id = str(_cell(row, "planeid", "")).strip()
    if not plane_id:
        raise ValueError("VOTable row has no planeid")
    artifact_path = str(_cell(row, "artifact_path", ""))
    mjd_value = _cell(row, "time_mjd")
    mjd = float(mjd_value) if mjd_value is not None else None
    observed_at = None
    if mjd is not None:
        epoch = datetime(1858, 11, 17, tzinfo=UTC)
        observed_at = epoch + timedelta(days=mjd)
    warnings: list[str] = []
    release = _release_from_artifact_path(artifact_path)
    if release is None:
        warnings.append("ARCHIVE_RELEASE_NOT_RECOGNIZED")
    footprint_value = _cell(row, "footprint")
    footprint = {"archive_value": str(footprint_value)} if footprint_value is not None else None
    return ObservationRecord(
        observation_id=plane_id,
        access_url=_cell(row, "access_url"),
        remote_checksum=_cell(row, "remote_checksum"),
        observed_at=observed_at,
        mjd=mjd,
        band=_cell(row, "band"),
        release=release,
        product=_cell(row, "product"),
        product_family=_product_family_from_artifact_path(artifact_path),
        spectral_plane=plane_id,
        width=int(_cell(row, "width")) if _cell(row, "width") is not None else None,
        height=int(_cell(row, "height")) if _cell(row, "height") is not None else None,
        footprint=footprint,
        warnings=warnings,
    )


def _save_query_artifacts(directory: Path, query: str, payload: bytes | None) -> str:
    query_id = f"art_query_{hashlib.sha256(query.encode('utf-8')).hexdigest()[:16]}"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{query_id}.adql").write_text(query, encoding="utf-8")
    if payload is None:
        return query_id
    response_key = hashlib.sha256(query.encode("utf-8") + b"\0" + payload).hexdigest()
    response_id = f"art_response_{response_key[:24]}"
    (directory / f"{response_id}.votable").write_bytes(payload)
    return response_id


def _save_request_artifact(directory: Path, form: dict[str, str]) -> None:
    """Persist the exact endpoint and form fields as a content-addressed record."""

    request_record = {"endpoint": TAP_URL, **form}
    canonical = json.dumps(request_record, sort_keys=True, separators=(",", ":"))
    request_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:24]
    request_id = f"art_request_{request_hash}"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{request_id}.json").write_text(
        json.dumps(request_record, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def discover(
    request: InvestigationRequest,
    *,
    session: Session | None = None,
    artifact_directory: Path | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> DiscoveryResult:
    """Query IRSA TAP and preserve exact request parameters, ADQL, and raw response bytes."""

    query = _build_query(request)
    artifact_dir = artifact_directory or DEFAULT_ARTIFACT_DIRECTORY
    artifact_id = _save_query_artifacts(artifact_dir, query, None)
    client = session or requests
    payload: bytes | None = None
    http_status: int | None = None
    timeout_seen = False
    connection_error: str | None = None

    form = {
        "REQUEST": "doQuery",
        "LANG": "ADQL",
        "FORMAT": "votable",
        "MAXREC": str(MAX_RECORDS),
        "QUERY": query,
    }
    _save_request_artifact(artifact_dir, form)
    response = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            with ARCHIVE_REQUEST_GATE:
                response = client.post(TAP_URL, data=form, timeout=TIMEOUT)
            payload = response.content
            http_status = int(response.status_code)
            if http_status >= 500 and attempt < MAX_ATTEMPTS:
                sleep(BACKOFF_SECONDS * (2 ** (attempt - 1)))
                continue
            break
        except Timeout:
            timeout_seen = True
            if attempt < MAX_ATTEMPTS:
                sleep(BACKOFF_SECONDS * (2 ** (attempt - 1)))
        except ConnectionError as exc:
            connection_error = type(exc).__name__
            if attempt < MAX_ATTEMPTS:
                sleep(BACKOFF_SECONDS * (2 ** (attempt - 1)))

    artifact_id = _save_query_artifacts(artifact_dir, query, payload)
    common = {
        "raw_query_parameters": {
            "endpoint": TAP_URL,
            **form,
        },
        "raw_response_artifact_id": artifact_id if payload is not None else None,
        "http_status": http_status,
    }
    if timeout_seen and payload is None and connection_error is None:
        return DiscoveryResult(
            status=DiscoveryStatus.TIMEOUT,
            error_code="ARCHIVE_TIMEOUT",
            warnings=["IRSA_TAP_REQUEST_TIMED_OUT"],
            **common,
        )
    if connection_error and payload is None:
        LOGGER.warning("IRSA TAP connection failed (%s)", connection_error)
        return DiscoveryResult(
            status=DiscoveryStatus.PARTIAL,
            error_code="ARCHIVE_CONNECTION_ERROR",
            warnings=["IRSA_TAP_CONNECTION_FAILED"],
            **common,
        )
    if http_status is None:
        return DiscoveryResult(
            status=DiscoveryStatus.PARTIAL,
            error_code="ARCHIVE_REQUEST_FAILED",
            warnings=["IRSA_TAP_REQUEST_FAILED"],
            **common,
        )
    if 400 <= http_status < 500:
        return DiscoveryResult(
            status=DiscoveryStatus.HTTP_4XX,
            error_code="ARCHIVE_HTTP_4XX",
            warnings=["IRSA_TAP_REJECTED_REQUEST"],
            **common,
        )
    if http_status >= 500:
        return DiscoveryResult(
            status=DiscoveryStatus.HTTP_5XX,
            error_code="ARCHIVE_HTTP_5XX",
            warnings=["IRSA_TAP_SERVER_ERROR"],
            **common,
        )
    if http_status == 206:
        status_warning = ["ARCHIVE_HTTP_PARTIAL_CONTENT"]
    else:
        status_warning = []

    try:
        table = parse_single_table(io.BytesIO(payload or b""), verify="ignore").to_table(
            use_names_over_ids=True
        )
        observations: list[ObservationRecord] = []
        row_failures = 0
        for row in table:
            try:
                observations.append(_observation(row))
            except (TypeError, ValueError, ValidationError):
                row_failures += 1
        query_statuses = _query_status(payload or b"") or ()
    except Exception as exc:
        LOGGER.warning("IRSA TAP returned an unreadable VOTable (%s)", type(exc).__name__)
        return DiscoveryResult(
            status=DiscoveryStatus.PARTIAL,
            error_code="INVALID_ARCHIVE_RESPONSE",
            warnings=status_warning + ["ARCHIVE_RESPONSE_COULD_NOT_BE_PARSED"],
            **common,
        )

    warnings = list(status_warning)
    if "OVERFLOW" in query_statuses:
        warnings.append("ARCHIVE_RESULT_OVERFLOW")
    if "ERROR" in query_statuses:
        warnings.append("ARCHIVE_REPORTED_QUERY_ERROR")
    if row_failures:
        warnings.append("ARCHIVE_ROWS_COULD_NOT_BE_NORMALIZED")

    partial = bool(warnings) or row_failures > 0
    if partial:
        status = DiscoveryStatus.PARTIAL
    elif observations:
        status = DiscoveryStatus.COMPLETE
    else:
        status = DiscoveryStatus.NO_RESULTS
    return DiscoveryResult(
        status=status,
        observations=observations,
        warnings=warnings,
        error_code="PARTIAL_ARCHIVE_RESPONSE" if partial else None,
        **common,
    )


__all__ = ["MAX_ATTEMPTS", "TAP_URL", "discover"]
