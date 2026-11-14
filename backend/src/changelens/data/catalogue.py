"""Optional, non-blocking Gaia and AllWISE context for sky positions.

Catalogue results are contextual only. They are never treated as SPHEREx
measurements or as evidence that a catalogue source is the target object.
Nothing is queried unless a caller explicitly enables enrichment.
"""

from __future__ import annotations

import csv
import io
import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Generic, Literal, Protocol, TypeVar

import astropy.units as u
import requests
from astropy.coordinates import SkyCoord
from astropy.io.votable import parse_single_table
from requests import Session

GAIA_DR3_TAP_URL = "https://gea.esac.esa.int/tap-server/tap/sync"
ALLWISE_GATOR_URL = "https://irsa.ipac.caltech.edu/cgi-bin/Gator/nph-query"
DEFAULT_TIMEOUT = (3.05, 10.0)
DEFAULT_MAX_ROWS = 25
MAX_ROWS = 100
MAX_RADIUS_ARCSEC = 3600.0

CatalogueValue = str | int | float | None
T = TypeVar("T")


class CatalogueContextStatus(StrEnum):
    DISABLED = "DISABLED"
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True)
class CatalogueCandidate:
    """A raw position and selected attributes returned by one catalogue."""

    catalogue: str
    source_id: str | None
    ra_deg: float
    dec_deg: float
    attributes: Mapping[str, CatalogueValue] = field(default_factory=dict)


@dataclass(frozen=True)
class CatalogueMatch:
    """A cone match with locally measured separation and explicit context label."""

    catalogue: str
    source_id: str | None
    ra_deg: float
    dec_deg: float
    separation_arcsec: float
    attributes: Mapping[str, CatalogueValue] = field(default_factory=dict)
    classification: Literal["CONTEXTUAL"] = "CONTEXTUAL"


@dataclass(frozen=True)
class CatalogueContext:
    status: CatalogueContextStatus
    matches: tuple[CatalogueMatch, ...] = ()
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class CatalogueEnrichment(Generic[T]):
    """Optional context kept separate from the unchanged core result."""

    core_result: T
    context: CatalogueContext


class CatalogueAdapter(Protocol):
    catalogue_name: str

    def search_cone(
        self, position: SkyCoord, radius_arcsec: float
    ) -> Sequence[CatalogueCandidate]: ...


def _validate_max_rows(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= MAX_ROWS:
        raise ValueError(f"max_rows must be between 1 and {MAX_ROWS}")
    return value


def _validate_timeout(value: tuple[float, float]) -> tuple[float, float]:
    if (
        len(value) != 2
        or any(not math.isfinite(seconds) or seconds <= 0 for seconds in value)
    ):
        raise ValueError("timeout must contain positive finite connect and read seconds")
    return value


def _validate_region(position: SkyCoord, radius_arcsec: float) -> tuple[SkyCoord, float]:
    if not isinstance(position, SkyCoord) or not position.isscalar:
        raise ValueError("position must be a scalar Astropy SkyCoord")
    center = position.icrs
    if not math.isfinite(center.ra.deg) or not math.isfinite(center.dec.deg):
        raise ValueError("position coordinates must be finite")
    if (
        isinstance(radius_arcsec, bool)
        or not math.isfinite(radius_arcsec)
        or not 0 < radius_arcsec <= MAX_RADIUS_ARCSEC
    ):
        raise ValueError(f"radius_arcsec must be greater than 0 and at most {MAX_RADIUS_ARCSEC}")
    return center, float(radius_arcsec)


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _match_candidate(
    position: SkyCoord, radius_arcsec: float, candidate: CatalogueCandidate
) -> CatalogueMatch | None:
    ra = _optional_float(candidate.ra_deg)
    dec = _optional_float(candidate.dec_deg)
    if ra is None or dec is None or not 0 <= ra < 360 or not -90 <= dec <= 90:
        raise ValueError("catalogue returned invalid sky coordinates")
    source_position = SkyCoord(ra=ra * u.deg, dec=dec * u.deg, frame="icrs")
    separation = float(position.separation(source_position).to_value(u.arcsec))
    if separation > radius_arcsec:
        return None
    return CatalogueMatch(
        catalogue=candidate.catalogue,
        source_id=candidate.source_id,
        ra_deg=ra,
        dec_deg=dec,
        separation_arcsec=separation,
        attributes=dict(candidate.attributes),
    )


def add_catalogue_context(
    core_result: T,
    position: SkyCoord,
    radius_arcsec: float,
    *,
    enabled: bool = False,
    adapters: Iterable[CatalogueAdapter] = (),
) -> CatalogueEnrichment[T]:
    """Return optional catalogue context while preserving ``core_result``.

    The default is fully disabled and performs no I/O. When enabled, each
    provider failure is converted into a warning; successful providers still
    contribute contextual matches and the core result is returned by identity.
    """

    if not enabled:
        return CatalogueEnrichment(
            core_result=core_result,
            context=CatalogueContext(status=CatalogueContextStatus.DISABLED),
        )
    center, radius = _validate_region(position, radius_arcsec)
    adapter_list = tuple(adapters)
    if not adapter_list:
        return CatalogueEnrichment(
            core_result=core_result,
            context=CatalogueContext(
                status=CatalogueContextStatus.UNAVAILABLE,
                warnings=("NO_CATALOGUE_ADAPTERS_CONFIGURED",),
            ),
        )

    successful_providers = 0
    matches: list[CatalogueMatch] = []
    warnings: list[str] = []
    for adapter in adapter_list:
        try:
            candidates = adapter.search_cone(center, radius)
            provider_matches = [
                match
                for candidate in candidates
                if (match := _match_candidate(center, radius, candidate)) is not None
            ]
            successful_providers += 1
            matches.extend(provider_matches)
        except Exception as exc:  # optional context must not fail the core task
            provider_name = getattr(adapter, "catalogue_name", type(adapter).__name__)
            warnings.append(f"CATALOGUE_QUERY_FAILED:{provider_name}:{type(exc).__name__}")

    matches.sort(
        key=lambda match: (
            match.catalogue.casefold(),
            match.separation_arcsec,
            match.source_id or "",
            match.ra_deg,
            match.dec_deg,
        )
    )
    if successful_providers == 0:
        status = CatalogueContextStatus.UNAVAILABLE
    elif warnings:
        status = CatalogueContextStatus.PARTIAL
    else:
        status = CatalogueContextStatus.COMPLETE
    return CatalogueEnrichment(
        core_result=core_result,
        context=CatalogueContext(
            status=status,
            matches=tuple(matches),
            warnings=tuple(warnings),
        ),
    )


class GaiaDR3Adapter:
    """Small, bounded Gaia DR3 cone query through the public TAP sync service."""

    catalogue_name = "Gaia DR3"

    def __init__(
        self,
        *,
        session: Session | None = None,
        timeout: tuple[float, float] = DEFAULT_TIMEOUT,
        max_rows: int = DEFAULT_MAX_ROWS,
    ) -> None:
        self.session = session if session is not None else requests.Session()
        self.timeout = _validate_timeout(timeout)
        self.max_rows = _validate_max_rows(max_rows)

    def search_cone(
        self, position: SkyCoord, radius_arcsec: float
    ) -> Sequence[CatalogueCandidate]:
        center, radius = _validate_region(position, radius_arcsec)
        ra = center.ra.deg
        dec = center.dec.deg
        radius_deg = radius / 3600.0
        point = "POINT('ICRS', ra, dec)"
        center_point = f"POINT('ICRS', {ra:.12g}, {dec:.12g})"
        query = (
            f"SELECT TOP {self.max_rows} source_id, ra, dec, phot_g_mean_mag "
            "FROM gaiadr3.gaia_source "
            f"WHERE 1 = CONTAINS({point}, "
            f"CIRCLE('ICRS', {ra:.12g}, {dec:.12g}, {radius_deg:.12g})) "
            f"ORDER BY DISTANCE({point}, {center_point})"
        )
        response = self.session.post(
            GAIA_DR3_TAP_URL,
            data={"REQUEST": "doQuery", "LANG": "ADQL", "FORMAT": "csv", "QUERY": query},
            timeout=self.timeout,
        )
        response.raise_for_status()
        reader = csv.DictReader(io.StringIO(response.text))
        required = {"source_id", "ra", "dec", "phot_g_mean_mag"}
        if reader.fieldnames is None or not required <= {
            field.strip().casefold() for field in reader.fieldnames
        }:
            raise ValueError("Gaia TAP response is missing required columns")
        column_names = {field.strip().casefold(): field for field in reader.fieldnames}
        candidates: list[CatalogueCandidate] = []
        for row in reader:
            ra_value = _optional_float(row.get(column_names["ra"]))
            dec_value = _optional_float(row.get(column_names["dec"]))
            if ra_value is None or dec_value is None:
                raise ValueError("Gaia TAP response contains invalid coordinates")
            source_id = row.get(column_names["source_id"], "").strip() or None
            candidates.append(
                CatalogueCandidate(
                    catalogue=self.catalogue_name,
                    source_id=source_id,
                    ra_deg=ra_value,
                    dec_deg=dec_value,
                    attributes={
                        "phot_g_mean_mag": _optional_float(
                            row.get(column_names["phot_g_mean_mag"])
                        )
                    },
                )
            )
            if len(candidates) >= self.max_rows:
                break
        return candidates


class AllWISEAdapter:
    """Bounded AllWISE source-catalog cone query through IRSA Gator."""

    catalogue_name = "AllWISE"

    def __init__(
        self,
        *,
        session: Session | None = None,
        timeout: tuple[float, float] = DEFAULT_TIMEOUT,
        max_rows: int = DEFAULT_MAX_ROWS,
    ) -> None:
        self.session = session if session is not None else requests.Session()
        self.timeout = _validate_timeout(timeout)
        self.max_rows = _validate_max_rows(max_rows)

    def search_cone(
        self, position: SkyCoord, radius_arcsec: float
    ) -> Sequence[CatalogueCandidate]:
        center, radius = _validate_region(position, radius_arcsec)
        response = self.session.get(
            ALLWISE_GATOR_URL,
            params={
                "catalog": "allwise_p3as_psd",
                "spatial": "cone",
                "radius": f"{radius:.12g}",
                "radunits": "arcsec",
                "objstr": f"{center.ra.deg:.12g} {center.dec.deg:.12g}",
                "outfmt": "3",
                "selcols": "designation,ra,dec,w1mpro,w2mpro,w3mpro,w4mpro",
                "outrows": str(self.max_rows),
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        table = parse_single_table(io.BytesIO(response.content)).to_table(
            use_names_over_ids=True
        )
        columns = {str(name).casefold(): name for name in table.colnames}
        required = {"designation", "ra", "dec"}
        if not required <= columns.keys():
            raise ValueError("AllWISE response is missing required columns")
        candidates: list[CatalogueCandidate] = []
        for row in table:
            ra_value = _optional_float(_table_value(row, columns["ra"]))
            dec_value = _optional_float(_table_value(row, columns["dec"]))
            if ra_value is None or dec_value is None:
                raise ValueError("AllWISE response contains invalid coordinates")
            designation = _table_value(row, columns["designation"])
            source_id = str(designation).strip() if designation is not None else None
            attributes = {
                name: _optional_float(_table_value(row, columns[name]))
                if name in columns
                else None
                for name in ("w1mpro", "w2mpro", "w3mpro", "w4mpro")
            }
            candidates.append(
                CatalogueCandidate(
                    catalogue=self.catalogue_name,
                    source_id=source_id or None,
                    ra_deg=ra_value,
                    dec_deg=dec_value,
                    attributes=attributes,
                )
            )
            if len(candidates) >= self.max_rows:
                break
        return candidates


def _table_value(row: object, column: str) -> object | None:
    value = row[column]  # type: ignore[index]
    if getattr(value, "mask", False):
        return None
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if hasattr(value, "item"):
        value = value.item()
    return value


__all__ = [
    "AllWISEAdapter",
    "CatalogueAdapter",
    "CatalogueCandidate",
    "CatalogueContext",
    "CatalogueContextStatus",
    "CatalogueEnrichment",
    "CatalogueMatch",
    "GaiaDR3Adapter",
    "add_catalogue_context",
]
