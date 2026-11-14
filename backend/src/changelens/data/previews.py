"""Local FITS crop and display-preview generation with provenance sidecars."""

from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
from pathlib import Path
from typing import Any

import numpy as np
from astropy import units as u
from astropy.coordinates import SkyCoord
from astropy.io import fits
from astropy.nddata import Cutout2D
from astropy.nddata.utils import NoOverlapError
from astropy.wcs import WCS
from PIL import Image
from pydantic import ValidationError

from changelens.contracts import (
    ErrorCode,
    PreviewMetadata,
    RetrievalMode,
    SourceArtifact,
    TargetRecord,
)
from changelens.data.retrieval import (
    DEFAULT_CACHE_DIRECTORY,
    DEFAULT_MANIFEST_DIRECTORY,
    _validate_fits,
)

DEFAULT_PREVIEW_DIRECTORY = Path(__file__).resolve().parents[4] / "data" / "previews"
STRETCH_PERCENTILES = (1.0, 99.0)
STRETCH_METHOD = "ASINH_PERCENTILE_1_99"
VALIDATION_STATUS = "FITS_CONTAINER_VALIDATED_ONLY"
VALIDATION_WARNINGS = ["SCIENCE_AND_WCS_VALIDATION_PENDING"]
CHUNK_SIZE = 1024 * 1024


class PreviewError(RuntimeError):
    """Typed local-preview failure suitable for mapping to the shared envelope."""

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        *,
        details: dict[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = False
        self.details = details or {}


def _error(
    reason: str,
    message: str,
    *,
    code: ErrorCode,
    **details: object,
) -> PreviewError:
    return PreviewError(code, message, details={"reason": reason, **details})


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_source_artifact_from_manifest(
    artifact_id: str,
    *,
    manifest_directory: Path | None = None,
) -> SourceArtifact:
    """Load a source artifact record for an already-cached local FITS product."""

    if (
        not artifact_id
        or len(artifact_id) > 128
        or not artifact_id[0].isascii()
        or not artifact_id[0].isalnum()
        or not all(
            character.isascii() and (character.isalnum() or character in "_-")
            for character in artifact_id
        )
    ):
        raise _error(
            "INVALID_SOURCE_ARTIFACT_ID",
            "The requested source artifact ID is invalid.",
            code=ErrorCode.ARTIFACT_NOT_FOUND,
        )
    manifest_path = (manifest_directory or DEFAULT_MANIFEST_DIRECTORY) / f"{artifact_id}.json"
    if not manifest_path.is_file():
        raise _error(
            "SOURCE_ARTIFACT_NOT_FOUND",
            "The requested source artifact manifest is not available locally.",
            code=ErrorCode.ARTIFACT_NOT_FOUND,
            artifact_id=artifact_id,
        )
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        source_artifact = SourceArtifact.model_validate(manifest["artifact"])
    except (OSError, ValueError, KeyError, TypeError, ValidationError) as exc:
        raise _error(
            "INVALID_SOURCE_MANIFEST",
            "The source artifact manifest is missing or invalid.",
            code=ErrorCode.INVALID_FITS,
            artifact_id=artifact_id,
        ) from exc
    if source_artifact.artifact_id != artifact_id:
        raise _error(
            "SOURCE_MANIFEST_ID_MISMATCH",
            "The source artifact manifest does not match the requested ID.",
            code=ErrorCode.INVALID_FITS,
            artifact_id=artifact_id,
        )
    return source_artifact


def _load_source_manifest(
    source_artifact: SourceArtifact,
    *,
    cache_directory: Path,
    manifest_directory: Path,
) -> Path:
    source_path = cache_directory / f"{source_artifact.artifact_id}.fits"
    manifest_path = manifest_directory / f"{source_artifact.artifact_id}.json"
    if not source_path.is_file() or not manifest_path.is_file():
        raise _error(
            "SOURCE_ARTIFACT_NOT_FOUND",
            "The requested source FITS artifact or its manifest is not available locally.",
            code=ErrorCode.ARTIFACT_NOT_FOUND,
            artifact_id=source_artifact.artifact_id,
        )

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest_artifact = SourceArtifact.model_validate(manifest["artifact"])
    except (OSError, ValueError, KeyError, TypeError, ValidationError) as exc:
        raise _error(
            "INVALID_SOURCE_MANIFEST",
            "The source artifact manifest is missing or invalid.",
            code=ErrorCode.INVALID_FITS,
            artifact_id=source_artifact.artifact_id,
        ) from exc

    if manifest.get("local_path") != source_path.name:
        raise _error(
            "SOURCE_MANIFEST_PATH_MISMATCH",
            "The source manifest does not identify the expected local FITS file.",
            code=ErrorCode.INVALID_FITS,
            artifact_id=source_artifact.artifact_id,
        )

    stable_fields = (
        "artifact_id",
        "source_url",
        "observation_id",
        "release",
        "size_bytes",
        "retrieved_at",
        "sha256",
        "checksum_status",
    )
    if any(
        getattr(manifest_artifact, field) != getattr(source_artifact, field)
        for field in stable_fields
    ):
        raise _error(
            "SOURCE_MANIFEST_IDENTITY_MISMATCH",
            "The supplied source artifact does not match its persisted manifest.",
            code=ErrorCode.INVALID_FITS,
            artifact_id=source_artifact.artifact_id,
        )
    if (
        source_artifact.retrieval_mode is not RetrievalMode.CACHE
        and manifest_artifact.retrieval_mode != source_artifact.retrieval_mode
    ):
        raise _error(
            "SOURCE_RETRIEVAL_MODE_MISMATCH",
            "The supplied source artifact retrieval mode does not match its manifest.",
            code=ErrorCode.INVALID_FITS,
            artifact_id=source_artifact.artifact_id,
        )

    if source_path.stat().st_size != manifest_artifact.size_bytes:
        raise _error(
            "SOURCE_SIZE_MISMATCH",
            "The local FITS file size does not match its recorded source artifact.",
            code=ErrorCode.INVALID_FITS,
            artifact_id=source_artifact.artifact_id,
        )
    if _sha256_file(source_path) != manifest_artifact.sha256:
        raise _error(
            "SOURCE_SHA256_MISMATCH",
            "The local FITS file hash does not match its recorded source artifact.",
            code=ErrorCode.INVALID_FITS,
            artifact_id=source_artifact.artifact_id,
        )
    return source_path


def _load_image_cutout(
    source_path: Path,
    observation_id: str,
    target: TargetRecord,
    *,
    fov_arcmin: float,
) -> tuple[np.ndarray, WCS, tuple[int, int], bool]:
    try:
        _validate_fits(source_path)
        with fits.open(
            source_path,
            mode="readonly",
            memmap=True,
            lazy_load_hdus=False,
            ignore_missing_simple=False,
        ) as hdus:
            try:
                image_hdu = hdus["IMAGE"]
            except (KeyError, IndexError) as exc:
                raise _error(
                    "IMAGE_EXTENSION_UNAVAILABLE",
                    "The source FITS file has no IMAGE extension for preview generation.",
                    code=ErrorCode.INVALID_FITS,
                ) from exc

            data = image_hdu.data
            if data is None or getattr(data, "ndim", 0) != 2:
                raise _error(
                    "IMAGE_EXTENSION_NOT_TWO_DIMENSIONAL",
                    "The source IMAGE extension must contain a two-dimensional image.",
                    code=ErrorCode.INVALID_FITS,
                )
            if data.dtype.kind not in "biuf":
                raise _error(
                    "IMAGE_EXTENSION_NOT_REAL_NUMERIC",
                    "The source IMAGE extension must contain real numeric pixels.",
                    code=ErrorCode.INVALID_FITS,
                )

            try:
                wcs = WCS(image_hdu.header, relax=True).celestial
            except Exception as exc:
                raise _error(
                    "INVALID_IMAGE_WCS",
                    "The source IMAGE extension has an unreadable celestial WCS.",
                    code=ErrorCode.WCS_FAILURE,
                ) from exc
            if not wcs.has_celestial or wcs.pixel_n_dim != 2:
                raise _error(
                    "CELESTIAL_WCS_UNAVAILABLE",
                    "The source IMAGE extension has no two-dimensional celestial WCS.",
                    code=ErrorCode.WCS_FAILURE,
                )

            try:
                position = SkyCoord(
                    ra=target.ra_deg * u.deg,
                    dec=target.dec_deg * u.deg,
                    frame=target.frame.lower(),
                )
                fill_value = float("nan") if data.dtype.kind == "f" else 0
                cutout = Cutout2D(
                    data,
                    position=position,
                    size=(fov_arcmin * u.arcmin, fov_arcmin * u.arcmin),
                    wcs=wcs,
                    mode="partial",
                    fill_value=fill_value,
                )
            except NoOverlapError as exc:
                raise _error(
                    "TARGET_OUTSIDE_SOURCE_FOOTPRINT",
                    "The requested target field does not overlap the source FITS image.",
                    code=ErrorCode.NO_OVERLAP,
                    target_id=target.target_id,
                    observation_id=observation_id,
                ) from exc
            except Exception as exc:
                raise _error(
                    "CUTOUT_WCS_FAILURE",
                    "The source WCS could not produce the requested local crop.",
                    code=ErrorCode.WCS_FAILURE,
                    target_id=target.target_id,
                ) from exc

            target_x, target_y = cutout.wcs.world_to_pixel(position)
            target_in_footprint = bool(
                0 <= target_x < cutout.data.shape[1] and 0 <= target_y < cutout.data.shape[0]
            )
            origin = (int(cutout.origin_original[0]), int(cutout.origin_original[1]))
            return (
                np.asarray(cutout.data, dtype=np.float64),
                cutout.wcs,
                origin,
                target_in_footprint,
            )
    except PreviewError:
        raise
    except (OSError, ValueError, fits.verify.VerifyError) as exc:
        raise _error(
            "INVALID_SOURCE_FITS",
            "The source artifact is not a complete, readable FITS container.",
            code=ErrorCode.INVALID_FITS,
        ) from exc


def _display_pixels(data: np.ndarray) -> tuple[np.ndarray, float, float]:
    finite = np.isfinite(data)
    if not np.any(finite):
        raise _error(
            "NO_FINITE_IMAGE_PIXELS",
            "The requested preview crop has no finite image pixels to display.",
            code=ErrorCode.INVALID_FITS,
        )

    low, high = (float(value) for value in np.percentile(data[finite], STRETCH_PERCENTILES))
    if not math.isfinite(low) or not math.isfinite(high):
        raise _error(
            "INVALID_DISPLAY_STRETCH",
            "A finite display stretch could not be computed for this source image.",
            code=ErrorCode.INVALID_FITS,
        )
    if high <= low:
        high = low + 1.0

    scaled = np.clip((np.where(finite, data, low) - low) / (high - low), 0.0, 1.0)
    stretched = np.arcsinh(10.0 * scaled) / np.arcsinh(10.0)
    pixels = np.rint(stretched * 255).astype(np.uint8)
    pixels[~finite] = 0
    return pixels, low, high


def _json_wcs_header(wcs: WCS) -> dict[str, Any]:
    header = wcs.to_header(relax=True)
    return {
        card.keyword: card.value
        for card in header.cards
        if card.keyword not in {"COMMENT", "HISTORY", ""}
    }


def _atomic_write_preview(
    metadata: PreviewMetadata,
    pixels: np.ndarray,
    *,
    preview_directory: Path,
) -> None:
    preview_directory.mkdir(parents=True, exist_ok=True)
    png_path = preview_directory / metadata.preview_filename
    metadata_path = preview_directory / f"{metadata.artifact_id}.json"
    temporary_png: Path | None = None
    temporary_metadata: Path | None = None
    backups: dict[Path, Path] = {}
    published: set[Path] = set()
    committed = False
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            suffix=".png",
            prefix=f".{metadata.artifact_id}-",
            dir=preview_directory,
            delete=False,
        ) as handle:
            temporary_png = Path(handle.name)
        Image.fromarray(pixels, mode="L").save(temporary_png, format="PNG")

        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            suffix=".json",
            prefix=f".{metadata.artifact_id}-",
            dir=preview_directory,
            delete=False,
        ) as handle:
            temporary_metadata = Path(handle.name)
            json.dump(
                metadata.model_dump(mode="json"),
                handle,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            handle.write("\n")

        for final_path in (png_path, metadata_path):
            if final_path.exists():
                descriptor, backup_name = tempfile.mkstemp(
                    suffix=final_path.suffix,
                    prefix=f".{metadata.artifact_id}-backup-",
                    dir=preview_directory,
                )
                os.close(descriptor)
                backup_path = Path(backup_name)
                backup_path.unlink()
                os.replace(final_path, backup_path)
                backups[final_path] = backup_path

        os.replace(temporary_png, png_path)
        temporary_png = None
        published.add(png_path)
        os.replace(temporary_metadata, metadata_path)
        temporary_metadata = None
        published.add(metadata_path)
        committed = True
    except (OSError, TypeError, ValueError) as exc:
        for final_path in published - backups.keys():
            try:
                final_path.unlink(missing_ok=True)
            except OSError:
                pass
        rollback_failures: list[str] = []
        for final_path, backup_path in reversed(list(backups.items())):
            if backup_path.exists():
                try:
                    os.replace(backup_path, final_path)
                except OSError:
                    rollback_failures.append(str(backup_path))
        raise _error(
            "PREVIEW_STORAGE_FAILED",
            "The generated preview could not be written to local storage.",
            code=ErrorCode.ANALYSIS_FAILED,
            artifact_id=metadata.artifact_id,
            rollback_incomplete=bool(rollback_failures),
            rollback_recovery_artifact_count=len(rollback_failures),
        ) from exc
    finally:
        if temporary_png:
            temporary_png.unlink(missing_ok=True)
        if temporary_metadata:
            temporary_metadata.unlink(missing_ok=True)
        if committed:
            for backup_path in backups.values():
                try:
                    backup_path.unlink(missing_ok=True)
                except OSError:
                    pass


def generate_preview(
    source_artifact: SourceArtifact,
    target: TargetRecord,
    *,
    fov_arcmin: float,
    cache_directory: Path | None = None,
    manifest_directory: Path | None = None,
    preview_directory: Path | None = None,
) -> PreviewMetadata:
    """Generate a local PNG and WCS/provenance sidecar without archive access."""

    if not math.isfinite(fov_arcmin) or not 0 < fov_arcmin <= 300:
        raise _error(
            "INVALID_PREVIEW_FIELD_OF_VIEW",
            "The preview field of view must be finite and between 0 and 300 arcminutes.",
            code=ErrorCode.INVALID_COORDINATES,
            fov_arcmin=fov_arcmin,
        )

    source_path = _load_source_manifest(
        source_artifact,
        cache_directory=cache_directory or DEFAULT_CACHE_DIRECTORY,
        manifest_directory=manifest_directory or DEFAULT_MANIFEST_DIRECTORY,
    )
    cutout, cutout_wcs, origin, target_in_footprint = _load_image_cutout(
        source_path,
        source_artifact.observation_id,
        target,
        fov_arcmin=fov_arcmin,
    )
    pixels, stretch_min, stretch_max = _display_pixels(cutout)

    identity = "\0".join(
        (
            source_artifact.artifact_id,
            source_artifact.sha256,
            source_artifact.observation_id,
            target.target_id,
            target.name,
            f"{target.ra_deg:.12f}",
            f"{target.dec_deg:.12f}",
            target.frame.upper(),
            f"{fov_arcmin:.17g}",
            STRETCH_METHOD,
        )
    )
    preview_id = f"art_preview_{hashlib.sha256(identity.encode('utf-8')).hexdigest()[:24]}"
    metadata = PreviewMetadata(
        artifact_id=preview_id,
        preview_filename=f"{preview_id}.png",
        preview_url=f"/v1/previews/{preview_id}.png",
        source_artifact_id=source_artifact.artifact_id,
        source_sha256=source_artifact.sha256,
        observation_id=source_artifact.observation_id,
        target_id=target.target_id,
        target_name=target.name,
        target_ra_deg=target.ra_deg,
        target_dec_deg=target.dec_deg,
        target_frame=target.frame,
        fov_arcmin=fov_arcmin,
        width=int(cutout.shape[1]),
        height=int(cutout.shape[0]),
        source_origin_x=origin[0],
        source_origin_y=origin[1],
        target_in_footprint=target_in_footprint,
        wcs_header=_json_wcs_header(cutout_wcs),
        stretch_method=STRETCH_METHOD,
        stretch_percentiles=STRETCH_PERCENTILES,
        stretch_min=stretch_min,
        stretch_max=stretch_max,
        validation_status=VALIDATION_STATUS,
        warnings=list(VALIDATION_WARNINGS),
    )
    _atomic_write_preview(
        metadata,
        pixels,
        preview_directory=preview_directory or DEFAULT_PREVIEW_DIRECTORY,
    )
    return metadata


__all__ = [
    "DEFAULT_PREVIEW_DIRECTORY",
    "PreviewError",
    "generate_preview",
    "load_source_artifact_from_manifest",
]
