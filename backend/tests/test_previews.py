from __future__ import annotations

import hashlib
import io
import json
from datetime import UTC, datetime
from pathlib import Path

import changelens.data.previews as previews_module
import numpy as np
import pytest
from astropy.io import fits
from astropy.wcs import WCS
from changelens import data
from changelens.contracts import (
    ChecksumStatus,
    ErrorCode,
    RetrievalMode,
    SourceArtifact,
    TargetRecord,
)
from PIL import Image


def fits_bytes() -> bytes:
    output = io.BytesIO()
    wcs = WCS(naxis=2)
    wcs.wcs.crpix = [16, 16]
    wcs.wcs.cdelt = [-0.01, 0.01]
    wcs.wcs.crval = [133.7951291667, -7.2451472222]
    wcs.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    image = np.arange(31 * 31, dtype=np.float32).reshape((31, 31))
    fits.HDUList(
        [
            fits.PrimaryHDU(),
            fits.ImageHDU(data=image, header=wcs.to_header(), name="IMAGE"),
        ]
    ).writeto(output)
    return output.getvalue()


def write_source_artifact(
    cache_directory: Path,
    manifest_directory: Path,
    payload: bytes,
    *,
    artifact_id: str = "art_source_preview_fixture",
    observation_id: str = "plane-preview-001",
) -> SourceArtifact:
    cache_directory.mkdir(parents=True)
    manifest_directory.mkdir(parents=True)
    source_path = cache_directory / f"{artifact_id}.fits"
    source_path.write_bytes(payload)
    artifact = SourceArtifact(
        artifact_id=artifact_id,
        source_url="https://irsa.ipac.caltech.edu/test.fits",
        observation_id=observation_id,
        release="DR1",
        size_bytes=len(payload),
        retrieved_at=datetime(2026, 11, 14, tzinfo=UTC),
        sha256=hashlib.sha256(payload).hexdigest(),
        checksum_status=ChecksumStatus.NO_REMOTE_CHECKSUM,
        retrieval_mode=RetrievalMode.CUTOUT,
    )
    manifest = {
        "schema_version": "1.0",
        "artifact": artifact.model_dump(mode="json"),
        "local_path": source_path.name,
    }
    (manifest_directory / f"{artifact_id}.json").write_text(json.dumps(manifest), encoding="utf-8")
    return artifact


def target() -> TargetRecord:
    return TargetRecord(
        target_id="wise_0855",
        name="WISE 0855",
        ra_deg=133.7951291667,
        dec_deg=-7.2451472222,
        role="preview fixture target",
    )


def test_generated_preview_preserves_observation_target_and_cropped_wcs_metadata(
    tmp_path: Path,
) -> None:
    source = write_source_artifact(
        tmp_path / "cache",
        tmp_path / "manifests",
        fits_bytes(),
    )
    preview_directory = tmp_path / "previews"
    generate_preview = getattr(data, "generate_preview", None)
    assert callable(generate_preview), "DATA preview generator is missing"

    metadata = generate_preview(
        source,
        target(),
        fov_arcmin=3,
        cache_directory=tmp_path / "cache",
        manifest_directory=tmp_path / "manifests",
        preview_directory=preview_directory,
    )
    cached_source = source.model_copy(update={"retrieval_mode": RetrievalMode.CACHE})
    cached_metadata = generate_preview(
        cached_source,
        target(),
        fov_arcmin=3,
        cache_directory=tmp_path / "cache",
        manifest_directory=tmp_path / "manifests",
        preview_directory=preview_directory,
    )

    assert metadata.source_artifact_id == source.artifact_id
    assert cached_metadata.artifact_id == metadata.artifact_id
    assert metadata.observation_id == "plane-preview-001"
    assert metadata.target_id == "wise_0855"
    assert metadata.validation_status == "FITS_CONTAINER_VALIDATED_ONLY"
    assert metadata.warnings == ["SCIENCE_AND_WCS_VALIDATION_PENDING"]
    assert metadata.width == 5
    assert metadata.height == 5
    assert metadata.target_in_footprint is True
    assert metadata.target_ra_deg == pytest.approx(target().ra_deg)
    assert metadata.target_dec_deg == pytest.approx(target().dec_deg)
    assert metadata.stretch_method == "ASINH_PERCENTILE_1_99"
    assert metadata.stretch_min < metadata.stretch_max
    assert metadata.wcs_header["CRVAL1"] == pytest.approx(133.7951291667)
    assert metadata.wcs_header["CRVAL2"] == pytest.approx(-7.2451472222)
    assert metadata.wcs_header["CTYPE1"] == "RA---TAN"
    assert metadata.wcs_header["CTYPE2"] == "DEC--TAN"
    cropped_wcs = WCS(metadata.wcs_header)
    target_x, target_y = cropped_wcs.all_world2pix([[target().ra_deg, target().dec_deg]], 0)[0]
    assert target_x == pytest.approx(2, abs=0.1)
    assert target_y == pytest.approx(2, abs=0.1)
    assert cropped_wcs.pixel_scale_matrix[0, 0] < 0
    assert cropped_wcs.pixel_scale_matrix[1, 1] > 0
    assert metadata.source_origin_x == 13
    assert metadata.source_origin_y == 13

    with Image.open(preview_directory / f"{metadata.artifact_id}.png") as preview:
        assert preview.format == "PNG"
        assert preview.mode == "L"
        assert preview.size == (5, 5)

    saved_metadata = json.loads(
        (preview_directory / f"{metadata.artifact_id}.json").read_text(encoding="utf-8")
    )
    assert saved_metadata["observation_id"] == "plane-preview-001"
    assert saved_metadata["source_artifact_id"] == source.artifact_id


def test_image_is_cropped_before_float64_display_conversion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = write_source_artifact(
        tmp_path / "cache",
        tmp_path / "manifests",
        fits_bytes(),
    )
    original_cutout = previews_module.Cutout2D

    def preserve_source_dtype(image_data: np.ndarray, **kwargs: object):
        assert image_data.dtype.kind == "f"
        assert image_data.dtype.itemsize == 4
        return original_cutout(image_data, **kwargs)

    monkeypatch.setattr(previews_module, "Cutout2D", preserve_source_dtype)

    data.generate_preview(
        source,
        target(),
        fov_arcmin=3,
        cache_directory=tmp_path / "cache",
        manifest_directory=tmp_path / "manifests",
        preview_directory=tmp_path / "previews",
    )


def test_invalid_fits_source_fails_explicitly_without_partial_preview(
    tmp_path: Path,
) -> None:
    source = write_source_artifact(
        tmp_path / "cache",
        tmp_path / "manifests",
        b"not a FITS file",
    )
    preview_directory = tmp_path / "previews"
    error_type = getattr(data, "PreviewError", None)
    generate_preview = getattr(data, "generate_preview", None)
    assert isinstance(error_type, type), "typed preview error is missing"
    assert callable(generate_preview), "DATA preview generator is missing"

    with pytest.raises(error_type) as raised:
        generate_preview(
            source,
            target(),
            fov_arcmin=3,
            cache_directory=tmp_path / "cache",
            manifest_directory=tmp_path / "manifests",
            preview_directory=preview_directory,
        )

    assert raised.value.code is ErrorCode.INVALID_FITS
    assert list(preview_directory.glob("*")) == []


def test_fits_without_image_extension_fails_explicitly(tmp_path: Path) -> None:
    output = io.BytesIO()
    fits.PrimaryHDU(data=np.ones((8, 8), dtype=np.float32)).writeto(output)
    source = write_source_artifact(
        tmp_path / "cache",
        tmp_path / "manifests",
        output.getvalue(),
    )
    error_type = getattr(data, "PreviewError", None)
    assert isinstance(error_type, type), "typed preview error is missing"

    with pytest.raises(error_type) as raised:
        data.generate_preview(
            source,
            target(),
            fov_arcmin=3,
            cache_directory=tmp_path / "cache",
            manifest_directory=tmp_path / "manifests",
            preview_directory=tmp_path / "previews",
        )

    assert raised.value.code is ErrorCode.INVALID_FITS
    assert raised.value.details["reason"] == "IMAGE_EXTENSION_UNAVAILABLE"
    assert list((tmp_path / "previews").glob("*")) == []


def test_image_without_celestial_wcs_fails_explicitly(tmp_path: Path) -> None:
    output = io.BytesIO()
    fits.HDUList(
        [
            fits.PrimaryHDU(),
            fits.ImageHDU(data=np.ones((8, 8), dtype=np.float32), name="IMAGE"),
        ]
    ).writeto(output)
    source = write_source_artifact(
        tmp_path / "cache",
        tmp_path / "manifests",
        output.getvalue(),
    )

    with pytest.raises(data.PreviewError) as raised:
        data.generate_preview(
            source,
            target(),
            fov_arcmin=3,
            cache_directory=tmp_path / "cache",
            manifest_directory=tmp_path / "manifests",
            preview_directory=tmp_path / "previews",
        )

    assert raised.value.code is ErrorCode.WCS_FAILURE
    assert raised.value.details["reason"] == "CELESTIAL_WCS_UNAVAILABLE"
    assert list((tmp_path / "previews").glob("*")) == []


def test_source_hash_mismatch_is_rejected_without_preview(tmp_path: Path) -> None:
    source = write_source_artifact(
        tmp_path / "cache",
        tmp_path / "manifests",
        fits_bytes(),
    )
    (tmp_path / "cache" / f"{source.artifact_id}.fits").write_bytes(b"tampered")
    preview_directory = tmp_path / "previews"
    error_type = getattr(data, "PreviewError", None)
    generate_preview = getattr(data, "generate_preview", None)
    assert isinstance(error_type, type), "typed preview error is missing"
    assert callable(generate_preview), "DATA preview generator is missing"

    with pytest.raises(error_type) as raised:
        generate_preview(
            source,
            target(),
            fov_arcmin=3,
            cache_directory=tmp_path / "cache",
            manifest_directory=tmp_path / "manifests",
            preview_directory=preview_directory,
        )

    assert raised.value.code is ErrorCode.INVALID_FITS
    assert list(preview_directory.glob("*")) == []


def test_manifest_observation_identity_mismatch_is_rejected(tmp_path: Path) -> None:
    source = write_source_artifact(
        tmp_path / "cache",
        tmp_path / "manifests",
        fits_bytes(),
    ).model_copy(update={"observation_id": "different-observation"})
    error_type = getattr(data, "PreviewError", None)
    generate_preview = getattr(data, "generate_preview", None)
    assert isinstance(error_type, type), "typed preview error is missing"
    assert callable(generate_preview), "DATA preview generator is missing"

    with pytest.raises(error_type) as raised:
        generate_preview(
            source,
            target(),
            fov_arcmin=3,
            cache_directory=tmp_path / "cache",
            manifest_directory=tmp_path / "manifests",
            preview_directory=tmp_path / "previews",
        )

    assert raised.value.code is ErrorCode.INVALID_FITS
    assert raised.value.details["reason"] == "SOURCE_MANIFEST_IDENTITY_MISMATCH"
    assert list((tmp_path / "previews").glob("*")) == []


def test_target_without_image_overlap_has_explicit_error(tmp_path: Path) -> None:
    source = write_source_artifact(
        tmp_path / "cache",
        tmp_path / "manifests",
        fits_bytes(),
    )
    outside_target = target().model_copy(update={"target_id": "outside", "ra_deg": 134.0})
    error_type = getattr(data, "PreviewError", None)
    generate_preview = getattr(data, "generate_preview", None)
    assert isinstance(error_type, type), "typed preview error is missing"
    assert callable(generate_preview), "DATA preview generator is missing"

    with pytest.raises(error_type) as raised:
        generate_preview(
            source,
            outside_target,
            fov_arcmin=3,
            cache_directory=tmp_path / "cache",
            manifest_directory=tmp_path / "manifests",
            preview_directory=tmp_path / "previews",
        )

    assert raised.value.code is ErrorCode.NO_OVERLAP
    assert raised.value.details["observation_id"] == source.observation_id
    assert list((tmp_path / "previews").glob("*")) == []


def test_identical_fits_from_distinct_observations_keep_distinct_preview_identity(
    tmp_path: Path,
) -> None:
    payload = fits_bytes()
    first_source = write_source_artifact(
        tmp_path / "cache-one",
        tmp_path / "manifests-one",
        payload,
        artifact_id="art_source_preview_one",
        observation_id="plane-one",
    )
    second_source = write_source_artifact(
        tmp_path / "cache-two",
        tmp_path / "manifests-two",
        payload,
        artifact_id="art_source_preview_two",
        observation_id="plane-two",
    )
    generate_preview = getattr(data, "generate_preview", None)
    assert callable(generate_preview), "DATA preview generator is missing"

    first_preview = generate_preview(
        first_source,
        target(),
        fov_arcmin=3,
        cache_directory=tmp_path / "cache-one",
        manifest_directory=tmp_path / "manifests-one",
        preview_directory=tmp_path / "previews",
    )
    second_preview = generate_preview(
        second_source,
        target(),
        fov_arcmin=3,
        cache_directory=tmp_path / "cache-two",
        manifest_directory=tmp_path / "manifests-two",
        preview_directory=tmp_path / "previews",
    )

    assert first_source.sha256 == second_source.sha256
    assert first_preview.artifact_id != second_preview.artifact_id
    assert first_preview.observation_id == "plane-one"
    assert second_preview.observation_id == "plane-two"


def test_failed_sidecar_replace_preserves_existing_preview_pair(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = write_source_artifact(
        tmp_path / "cache",
        tmp_path / "manifests",
        fits_bytes(),
    )
    preview_directory = tmp_path / "previews"
    metadata = data.generate_preview(
        source,
        target(),
        fov_arcmin=3,
        cache_directory=tmp_path / "cache",
        manifest_directory=tmp_path / "manifests",
        preview_directory=preview_directory,
    )
    png_path = preview_directory / metadata.preview_filename
    json_path = preview_directory / f"{metadata.artifact_id}.json"
    original_png = png_path.read_bytes()
    original_json = json_path.read_bytes()
    real_replace = previews_module.os.replace
    calls = 0

    def fail_sidecar_publish(source_path: Path, destination_path: Path) -> None:
        nonlocal calls
        calls += 1
        if calls == 4:
            raise OSError("fixture sidecar promotion failure")
        real_replace(source_path, destination_path)

    monkeypatch.setattr(previews_module.os, "replace", fail_sidecar_publish)

    with pytest.raises(data.PreviewError):
        data.generate_preview(
            source,
            target(),
            fov_arcmin=3,
            cache_directory=tmp_path / "cache",
            manifest_directory=tmp_path / "manifests",
            preview_directory=preview_directory,
        )

    assert calls >= 6
    assert png_path.read_bytes() == original_png
    assert json_path.read_bytes() == original_json
