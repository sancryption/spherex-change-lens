"""Safe streaming retrieval, FITS checks, hashing, and disk cache manifests."""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import re
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from urllib.parse import parse_qs, urlsplit, urlunsplit

import requests
from astropy import units as u
from astropy.coordinates import SkyCoord
from astropy.io import fits
from astropy.nddata import Cutout2D
from astropy.wcs import WCS
from pydantic import ValidationError
from requests import Session
from requests.exceptions import ConnectionError, RequestException, Timeout

from changelens.contracts import (
    ChecksumStatus,
    ErrorCode,
    ObservationRecord,
    RetrievalMode,
    SourceArtifact,
)
from changelens.data.network import ARCHIVE_REQUEST_GATE


LOGGER = logging.getLogger(__name__)
DEFAULT_CACHE_DIRECTORY = Path(__file__).resolve().parents[4] / "data" / "cached_mefs"
DEFAULT_MANIFEST_DIRECTORY = Path(__file__).resolve().parents[4] / "data" / "manifests"
DEFAULT_TIMEOUT = (10.0, 90.0)
MAX_ATTEMPTS = 3
BACKOFF_SECONDS = 0.5
DEFAULT_CACHE_BUDGET_BYTES = 5 * 1024**3
CHUNK_SIZE = 1024 * 1024
_CACHE_BUDGET_LOCKS_GUARD = threading.Lock()
_CACHE_BUDGET_LOCKS: dict[str, threading.Lock] = {}


class RetrievalError(RuntimeError):
    """Typed retrieval failure suitable for mapping to the shared error envelope."""

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        *,
        retryable: bool = False,
        details: dict[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable
        self.details = details or {}


def _error(
    reason: str,
    message: str,
    *,
    code: ErrorCode = ErrorCode.RETRIEVAL_FAILED,
    retryable: bool = False,
    **details: object,
) -> RetrievalError:
    return RetrievalError(
        code,
        message,
        retryable=retryable,
        details={"reason": reason, **details},
    )


def _parse_remote_checksum(value: str | None) -> tuple[str, str] | None:
    if value is None or not value.strip():
        return None
    match = re.fullmatch(r"(md5|sha256):([A-Fa-f0-9]+)", value.strip(), flags=re.IGNORECASE)
    if not match:
        raise _error(
            "INVALID_REMOTE_CHECKSUM",
            "The archive supplied a checksum with an unsupported format.",
        )
    algorithm, digest = match.group(1).lower(), match.group(2).lower()
    expected_length = 32 if algorithm == "md5" else 64
    if len(digest) != expected_length:
        raise _error(
            "INVALID_REMOTE_CHECKSUM",
            "The archive supplied a checksum with an invalid digest length.",
        )
    return algorithm, digest


def _request_key(observation: ObservationRecord) -> str:
    key = "\0".join(
        [observation.observation_id, str(observation.access_url), observation.remote_checksum or ""]
    )
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def _full_file_url(access_url: str) -> str | None:
    parsed = urlsplit(access_url)
    query = parse_qs(parsed.query)
    if "center" not in query or "size" not in query:
        return None
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def _cutout_parameters(access_url: str) -> tuple[SkyCoord, float, float, float]:
    query = parse_qs(urlsplit(access_url).query)
    centers = query.get("center", [])
    sizes = query.get("size", [])
    try:
        center_text = centers[0].rstrip("dD")
        ra_text, dec_text = center_text.split(",", 1)
        ra_deg = float(ra_text)
        dec_deg = float(dec_text)
        size_deg = float(sizes[0])
    except (IndexError, TypeError, ValueError) as exc:
        raise _error(
            "INVALID_CUTOUT_PARAMETERS",
            "The requested cutout URL has invalid center or size parameters.",
            code=ErrorCode.INVALID_FITS,
        ) from exc
    if (
        not math.isfinite(ra_deg)
        or not math.isfinite(dec_deg)
        or not math.isfinite(size_deg)
        or not 0 <= ra_deg < 360
        or not -90 <= dec_deg <= 90
        or size_deg <= 0
    ):
        raise _error(
            "INVALID_CUTOUT_PARAMETERS",
            "The requested cutout URL has invalid center or size parameters.",
            code=ErrorCode.INVALID_FITS,
        )
    return SkyCoord(ra=ra_deg * u.deg, dec=dec_deg * u.deg, frame="icrs"), ra_deg, dec_deg, size_deg


def _crop_full_file(
    source_path: Path,
    *,
    requested_url: str,
    cache_directory: Path,
    artifact_id: str,
) -> tuple[Path, dict[str, object]]:
    position, ra_deg, dec_deg, size_deg = _cutout_parameters(requested_url)
    cache_directory.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{artifact_id}-crop-", suffix=".part", dir=cache_directory
    )
    os.close(descriptor)
    crop_path = Path(temporary_name)
    cropped_hdu_names: list[str] = []
    image_cropped = False
    try:
        with fits.open(
            source_path,
            mode="readonly",
            memmap=True,
            lazy_load_hdus=False,
            ignore_missing_simple=False,
        ) as hdus:
            for hdu in hdus:
                data = hdu.data
                if data is None or getattr(data, "ndim", 0) != 2:
                    continue
                try:
                    wcs = WCS(hdu.header).celestial
                except Exception:
                    continue
                if not wcs.has_celestial:
                    continue
                fill_value = float("nan") if data.dtype.kind in "fc" else 0
                cutout = Cutout2D(
                    data,
                    position=position,
                    size=(size_deg * u.deg, size_deg * u.deg),
                    wcs=wcs,
                    mode="partial",
                    fill_value=fill_value,
                )
                updated_header = hdu.header.copy()
                updated_header.update(cutout.wcs.to_header(relax=True))
                hdu.data = cutout.data
                hdu.header = updated_header
                cropped_hdu_names.append(hdu.name)
                if hdu.name.upper() == "IMAGE":
                    image_cropped = True
            if not image_cropped:
                raise _error(
                    "LOCAL_CROP_IMAGE_UNAVAILABLE",
                    "The full FITS source has no celestial IMAGE extension to crop.",
                    code=ErrorCode.INVALID_FITS,
                )
            hdus.writeto(crop_path, overwrite=True, output_verify="exception")
        _validate_fits(crop_path)
        return crop_path, {
            "center_ra_deg": ra_deg,
            "center_dec_deg": dec_deg,
            "size_deg": size_deg,
            "cropped_hdu_names": cropped_hdu_names,
        }
    except RetrievalError:
        crop_path.unlink(missing_ok=True)
        raise
    except Exception as exc:
        crop_path.unlink(missing_ok=True)
        raise _error(
            "LOCAL_CROP_FAILED",
            "The downloaded full FITS source could not be cropped to the requested cutout.",
            code=ErrorCode.INVALID_FITS,
        ) from exc


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _apply_local_cutout_fallback(
    source_path: Path,
    *,
    source_url: str,
    source_size_bytes: int,
    source_sha256: str,
    source_checksum_status: ChecksumStatus,
    requested_url: str,
    cache_directory: Path,
    artifact_id: str,
) -> tuple[Path, int, str, dict[str, object], dict[str, object]]:
    crop_path, crop_metadata = _crop_full_file(
        source_path,
        requested_url=requested_url,
        cache_directory=cache_directory,
        artifact_id=artifact_id,
    )
    try:
        crop_size = crop_path.stat().st_size
        crop_sha256 = _sha256_file(crop_path)
        source_path.unlink()
    except OSError:
        crop_path.unlink(missing_ok=True)
        raise
    fallback_source = {
        "source_url": source_url,
        "size_bytes": source_size_bytes,
        "sha256": source_sha256,
        "checksum_status": source_checksum_status.value,
    }
    return crop_path, crop_size, crop_sha256, fallback_source, crop_metadata


def _validate_fits(path: Path) -> None:
    size = path.stat().st_size
    if size == 0:
        raise OSError("empty file")
    with fits.open(
        path,
        mode="readonly",
        memmap=True,
        lazy_load_hdus=False,
        ignore_missing_simple=False,
    ) as hdus:
        if not hdus:
            raise OSError("FITS file has no HDUs")
        hdus.verify("exception")
        for hdu in hdus:
            info = hdu.fileinfo()
            if info and info.get("datLoc") is not None and info.get("datSpan") is not None:
                if int(info["datLoc"]) + int(info["datSpan"]) > size:
                    raise OSError("FITS data extends beyond end of file")


def _cache_size(cache_directory: Path, excluded: Path) -> int:
    total = 0
    if not cache_directory.exists():
        return 0
    for path in cache_directory.glob("*.fits"):
        if path != excluded and path.is_file():
            total += path.stat().st_size
    return total


def _atomic_json(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.stem}-",
            suffix=".part",
            delete=False,
        ) as handle:
            temporary_name = handle.name
            json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(temporary_name, path)
    except OSError:
        if temporary_name:
            Path(temporary_name).unlink(missing_ok=True)
        raise


def _cached_artifact(
    *,
    artifact_id: str,
    cache_path: Path,
    manifest_path: Path,
    remote_checksum: tuple[str, str] | None,
    requested_cutout: bool,
) -> SourceArtifact | None:
    if not cache_path.is_file() or not manifest_path.is_file():
        return None
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        artifact = SourceArtifact.model_validate(manifest["artifact"])
        if artifact.artifact_id != artifact_id or cache_path.stat().st_size != artifact.size_bytes:
            return None
        if (
            requested_cutout
            and artifact.retrieval_mode is RetrievalMode.FULL_FILE
            and not manifest.get("local_crop")
        ):
            return None
        cached_checksum = (
            remote_checksum
            if artifact.retrieval_mode is RetrievalMode.FULL_FILE
            else None
        )
        sha = hashlib.sha256()
        remote_hash = None
        if cached_checksum and cached_checksum[0] == "md5":
            remote_hash = hashlib.md5(usedforsecurity=False)
        elif cached_checksum:
            remote_hash = hashlib.sha256()
        with cache_path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(CHUNK_SIZE), b""):
                sha.update(chunk)
                if remote_hash:
                    remote_hash.update(chunk)
        if sha.hexdigest() != artifact.sha256:
            return None
        if cached_checksum and remote_hash and remote_hash.hexdigest() != cached_checksum[1]:
            return None
        _validate_fits(cache_path)
        return artifact.model_copy(update={"retrieval_mode": RetrievalMode.CACHE})
    except (OSError, ValueError, KeyError, ValidationError, TypeError):
        return None


def _download_once(
    *,
    client: Session,
    url: str,
    cache_path: Path,
    artifact_id: str,
    expected_checksum: tuple[str, str] | None,
    budget_remaining: int,
    timeout: tuple[float, float],
) -> tuple[Path, int, str, ChecksumStatus]:
    ARCHIVE_REQUEST_GATE.acquire()
    response = None
    try:
        response = client.get(url, stream=True, timeout=timeout)
        status_code = int(response.status_code)
        if status_code == 503:
            raise _error("HTTP_503", "The archive returned HTTP 503.", http_status=503, retryable=True)
        if 400 <= status_code < 500:
            raise _error("HTTP_4XX", "The archive rejected the retrieval request.", http_status=status_code)
        if status_code >= 500:
            raise _error("HTTP_5XX", "The archive returned a server error.", http_status=status_code, retryable=True)
        if status_code != 200:
            raise _error("UNEXPECTED_HTTP_STATUS", "The archive returned an unexpected status.", http_status=status_code)

        content_length_value = response.headers.get("Content-Length") or response.headers.get("content-length")
        if content_length_value is not None:
            try:
                expected_size = int(content_length_value)
            except (TypeError, ValueError) as exc:
                raise _error("INVALID_CONTENT_LENGTH", "The archive returned an invalid Content-Length.") from exc
            if expected_size < 1:
                raise _error("INVALID_CONTENT_LENGTH", "The archive returned an empty Content-Length.")
            if expected_size > budget_remaining:
                raise _error("CACHE_BUDGET_EXCEEDED", "The download exceeds the configured cache budget.")
        else:
            expected_size = None

        cache_path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{artifact_id}-", suffix=".part", dir=cache_path.parent
        )
        os.close(descriptor)
        temporary_path = Path(temporary_name)
        sha = hashlib.sha256()
        remote_hash = None
        if expected_checksum and expected_checksum[0] == "md5":
            remote_hash = hashlib.md5(usedforsecurity=False)
        elif expected_checksum:
            remote_hash = hashlib.sha256()
        downloaded = 0
        try:
            with temporary_path.open("wb") as output:
                for chunk in response.iter_content(chunk_size=CHUNK_SIZE):
                    if not chunk:
                        continue
                    downloaded += len(chunk)
                    if downloaded > budget_remaining:
                        raise _error(
                            "CACHE_BUDGET_EXCEEDED",
                            "The download exceeds the configured cache budget.",
                        )
                    sha.update(chunk)
                    if remote_hash:
                        remote_hash.update(chunk)
                    output.write(chunk)
            if expected_size is not None and downloaded != expected_size:
                raise _error(
                    "PARTIAL_DOWNLOAD",
                    "The downloaded byte count does not match Content-Length.",
                    expected_bytes=expected_size,
                    received_bytes=downloaded,
                    retryable=True,
                )
            if downloaded == 0:
                raise _error("EMPTY_DOWNLOAD", "The archive returned an empty file.", retryable=True)
            if expected_checksum and remote_hash and remote_hash.hexdigest() != expected_checksum[1]:
                raise _error("CHECKSUM_MISMATCH", "The archive checksum does not match the downloaded file.")
            try:
                _validate_fits(temporary_path)
            except (OSError, ValueError, fits.verify.VerifyError) as exc:
                raise _error(
                    "INVALID_FITS",
                    "The archive response is not a complete, readable FITS file.",
                    code=ErrorCode.INVALID_FITS,
                    retryable=True,
                ) from exc
            checksum_status = (
                ChecksumStatus.MATCHED if expected_checksum else ChecksumStatus.NO_REMOTE_CHECKSUM
            )
            return temporary_path, downloaded, sha.hexdigest(), checksum_status
        except Exception:
            temporary_path.unlink(missing_ok=True)
            raise
    finally:
        try:
            close = getattr(response, "close", None)
            if callable(close):
                close()
        finally:
            ARCHIVE_REQUEST_GATE.release()


def _retrieve(
    observation: ObservationRecord,
    *,
    cache_directory: Path | None = None,
    manifest_directory: Path | None = None,
    session: Session | None = None,
    timeout: tuple[float, float] = DEFAULT_TIMEOUT,
    max_attempts: int = MAX_ATTEMPTS,
    cache_budget_bytes: int = DEFAULT_CACHE_BUDGET_BYTES,
    now: Callable[[], datetime] | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> SourceArtifact:
    """Fetch an archive FITS product and atomically cache it after validation."""

    if observation.access_url is None:
        raise _error("MISSING_ACCESS_URL", "The observation has no archive access URL.")
    if max_attempts < 1 or cache_budget_bytes < 1:
        raise ValueError("max_attempts and cache_budget_bytes must be positive")
    expected_checksum = _parse_remote_checksum(observation.remote_checksum)
    cache_dir = cache_directory or DEFAULT_CACHE_DIRECTORY
    manifest_dir = manifest_directory or DEFAULT_MANIFEST_DIRECTORY
    request_key = _request_key(observation)
    artifact_id = f"art_source_{request_key[:24]}"
    cache_path = cache_dir / f"{artifact_id}.fits"
    manifest_path = manifest_dir / f"{artifact_id}.json"
    requested_url = str(observation.access_url)
    requested_cutout = _full_file_url(requested_url) is not None
    cached = _cached_artifact(
        artifact_id=artifact_id,
        cache_path=cache_path,
        manifest_path=manifest_path,
        remote_checksum=expected_checksum,
        requested_cutout=requested_cutout,
    )
    if cached:
        return cached

    current_url = requested_url
    mode = RetrievalMode.CUTOUT if requested_cutout else RetrievalMode.FULL_FILE
    checksum_for_url = expected_checksum if mode is RetrievalMode.FULL_FILE else None
    full_url = _full_file_url(requested_url)
    full_file_fallback = False
    fallback_source: dict[str, object] | None = None
    local_crop: dict[str, object] | None = None
    attempts_for_url = 0
    payload_path: Path | None = None
    download_size = 0
    sha256 = ""
    checksum_status = ChecksumStatus.NO_REMOTE_CHECKSUM
    used_session = session or requests.Session()
    owns_session = session is None
    promoted_path: Path | None = None
    try:
        while True:
            attempts_for_url += 1
            budget_remaining = cache_budget_bytes - _cache_size(cache_dir, cache_path)
            if budget_remaining <= 0:
                raise _error("CACHE_BUDGET_EXCEEDED", "The configured cache budget is full.")
            try:
                payload_path, download_size, sha256, checksum_status = _download_once(
                    client=used_session,
                    url=current_url,
                    cache_path=cache_path,
                    artifact_id=artifact_id,
                    expected_checksum=checksum_for_url,
                    budget_remaining=budget_remaining,
                    timeout=timeout,
                )
                break
            except RetrievalError as exc:
                if (
                    exc.details.get("reason") == "HTTP_503"
                    and mode is RetrievalMode.CUTOUT
                    and full_url
                    and not full_file_fallback
                ):
                    current_url = full_url
                    full_file_fallback = True
                    checksum_for_url = expected_checksum
                    attempts_for_url = 0
                    continue
                if exc.retryable and attempts_for_url < max_attempts:
                    sleep(BACKOFF_SECONDS * (2 ** (attempts_for_url - 1)))
                    continue
                raise
            except (Timeout, ConnectionError, RequestException) as exc:
                if attempts_for_url < max_attempts:
                    sleep(BACKOFF_SECONDS * (2 ** (attempts_for_url - 1)))
                    continue
                reason = "TIMEOUT" if isinstance(exc, Timeout) else "NETWORK_ERROR"
                raise _error(reason, "The archive retrieval failed after bounded retries.", retryable=True) from exc

        if full_file_fallback:
            payload_path, download_size, sha256, fallback_source, local_crop = (
                _apply_local_cutout_fallback(
                    payload_path,
                    source_url=current_url,
                    source_size_bytes=download_size,
                    source_sha256=sha256,
                    source_checksum_status=checksum_status,
                    requested_url=requested_url,
                    cache_directory=cache_dir,
                    artifact_id=artifact_id,
                )
            )
            checksum_status = ChecksumStatus.NO_REMOTE_CHECKSUM

        os.replace(payload_path, cache_path)
        promoted_path = cache_path
        timestamp = now() if now is not None else datetime.now(timezone.utc)
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        artifact = SourceArtifact(
            artifact_id=artifact_id,
            source_url=current_url,
            observation_id=observation.observation_id,
            release=observation.release or "UNKNOWN",
            size_bytes=download_size,
            retrieved_at=timestamp,
            sha256=sha256,
            checksum_status=checksum_status,
            retrieval_mode=mode,
        )
        _atomic_json(
            manifest_path,
            {
                "schema_version": "1.0",
                "artifact": artifact.model_dump(mode="json"),
                "requested_url": requested_url,
                "remote_checksum": observation.remote_checksum,
                "local_path": cache_path.name,
                "fallback_source": fallback_source,
                "local_crop": local_crop,
            },
        )
        return artifact
    except RetrievalError:
        if payload_path:
            payload_path.unlink(missing_ok=True)
        if promoted_path:
            promoted_path.unlink(missing_ok=True)
        raise
    except OSError as exc:
        if payload_path:
            payload_path.unlink(missing_ok=True)
        if promoted_path:
            promoted_path.unlink(missing_ok=True)
        raise _error("STORAGE_WRITE_FAILED", "The cache file or manifest could not be written.") from exc
    finally:
        if owns_session:
            used_session.close()


def retrieve(
    observation: ObservationRecord,
    *,
    cache_directory: Path | None = None,
    manifest_directory: Path | None = None,
    session: Session | None = None,
    timeout: tuple[float, float] = DEFAULT_TIMEOUT,
    max_attempts: int = MAX_ATTEMPTS,
    cache_budget_bytes: int = DEFAULT_CACHE_BUDGET_BYTES,
    now: Callable[[], datetime] | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> SourceArtifact:
    """Fetch an archive FITS product under the cache's shared byte budget."""

    cache_dir = cache_directory or DEFAULT_CACHE_DIRECTORY
    cache_key = str(cache_dir.resolve())
    with _CACHE_BUDGET_LOCKS_GUARD:
        cache_lock = _CACHE_BUDGET_LOCKS.setdefault(cache_key, threading.Lock())
    with cache_lock:
        return _retrieve(
            observation,
            cache_directory=cache_dir,
            manifest_directory=manifest_directory,
            session=session,
            timeout=timeout,
            max_attempts=max_attempts,
            cache_budget_bytes=cache_budget_bytes,
            now=now,
            sleep=sleep,
        )


__all__ = ["DEFAULT_CACHE_BUDGET_BYTES", "RetrievalError", "retrieve"]
