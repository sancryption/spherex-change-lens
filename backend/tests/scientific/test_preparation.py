"""Synthetic mechanism tests; tolerances below are NOT real-data policies."""

from dataclasses import replace
from io import BytesIO

import numpy as np
import pytest
from astropy.io import fits
from change_lens.pipeline.calibration import (
    CalibrationReference,
    _verify_bytes,
    calibration_reasons,
    fetch_calibration,
    history_calibrations,
    require_irsa_url,
)
from change_lens.pipeline.difference import compute_difference
from change_lens.pipeline.preparation import (
    ScientificPolicy,
    apply_psf_kernel,
    assess_effective_psfs,
    compare_spectra,
    load_native_epsf_samples,
    load_spectral_map,
    prepare_background,
    record_pair_preparation,
)

from .phase3_helpers import frames_and_track

UUID = "019f4f98-edf0-744b-9600-424841d46dc0"
URL = "https://irsa.ipac.caltech.edu/ibe/data/spherex/dr1/spectral_wcs/test/1/spectral_wcs_D1_test.fits"
REF = CalibrationReference("spectral_wcs", UUID)
POLICY = ScientificPolicy("synthetic-unit-test-only", 0.001, 0.9, 0.01)


def product_bytes(uuid=UUID):
    stream = BytesIO()
    fits.HDUList(
        [
            fits.PrimaryHDU(header=fits.Header({"UUID": uuid, "DETECTOR": 1})),
            fits.ImageHDU(np.ones((4, 4)), name="CWAVE", header=fits.Header({"BUNIT": "um"})),
            fits.ImageHDU(np.full((4, 4), 0.1), name="CBAND", header=fits.Header({"BUNIT": "um"})),
        ]
    ).writeto(stream)
    return stream.getvalue()


@pytest.fixture
def spectral(tmp_path):
    content = product_bytes()
    path = tmp_path / "cal.fits"
    path.write_bytes(content)
    product = _verify_bytes(REF, URL, content)
    y, x = np.indices((4, 4))
    return load_spectral_map(product, path, 1, x, y, "synthetic native grid"), path


def test_history_deduplicates_but_does_not_verify():
    history = [f"[CALIB] spectral_wcs {UUID}"] * 2
    assert history_calibrations(history) == (REF,)
    assert calibration_reasons(history, ()) == (f"CALIBRATION_UNVERIFIED:spectral_wcs:{UUID}",)
    with pytest.raises(ValueError, match="MALFORMED"):
        history_calibrations(["[CALIB] spectral_wcs not-a-uuid"])


@pytest.mark.parametrize(
    "url",
    [
        URL.replace("https:", "http:"),
        URL.replace("irsa.ipac.caltech.edu", "example.org"),
        URL + "?x=y",
        URL.replace("/dr1/", "/qr2/"),
    ],
)
def test_reject_non_authoritative_urls(url):
    with pytest.raises(ValueError):
        require_irsa_url(url)


def test_download_verified_and_unavailable(monkeypatch, tmp_path):
    class Response:
        status_code = 200
        content = product_bytes()

    monkeypatch.setattr(
        "change_lens.pipeline.calibration.requests.get", lambda *a, **kw: Response()
    )
    path = tmp_path / "official.fits"
    verified = fetch_calibration(REF, URL, path)
    assert verified.sha256 and verified.identity_evidence
    assert path.read_bytes() == Response.content
    Response.status_code = 404
    with pytest.raises(ValueError, match="UNAVAILABLE"):
        fetch_calibration(REF, URL, tmp_path / "missing.fits")
    assert not (tmp_path / "missing.fits").exists()


def test_uuid_is_product_identity_not_dependency():
    with pytest.raises(ValueError, match="UUID_NOT_VERIFIED"):
        _verify_bytes(REF, URL, product_bytes("019f4f98-edf0-744b-9600-424841d46dc1"))


def test_authoritative_maps_and_interval_comparison(spectral):
    m, _ = spectral
    region = np.ones((4, 4), bool)
    evidence, reasons = compare_spectra(m, m, region, POLICY)
    assert not reasons
    assert evidence["min_interval_overlap"] == pytest.approx(1)
    assert evidence["max_delta_um"] == 0
    assert compare_spectra(m, m, region, None)[1] == ("SPECTRAL_POLICY_UNREVIEWED",)
    shifted = replace(m, wavelength_um=m.wavelength_um + 0.1)
    assert "SPECTRAL_INCOMPATIBLE" in compare_spectra(m, shifted, region, POLICY)[1]
    bad = replace(m, bandwidth_um=np.full((4, 4), np.nan))
    assert "INVALID_SPECTRAL_PIXELS" in compare_spectra(m, bad, region, POLICY)[1]


def test_corruption_and_fractional_mapping_rejected(spectral):
    m, path = spectral
    y, x = np.indices((4, 4))
    with pytest.raises(ValueError, match="EXACT_NATIVE"):
        load_spectral_map(m.calibration, path, 1, x + 0.5, y, "test")
    with pytest.raises(ValueError, match="DETECTOR"):
        load_spectral_map(m.calibration, path, 2, x, y, "test")
    with fits.open(path, mode="update") as hdus:
        hdus["CWAVE"].data[:] = 2
    with pytest.raises(ValueError, match="CONTENT_MISMATCH"):
        load_spectral_map(m.calibration, path, 1, x, y, "test")


def test_background_subtraction_masks_and_covariance():
    image, variance, zodi = np.full((4, 4), 7.0), np.ones((4, 4)), np.full((4, 4), 2.0)
    flags = np.zeros((4, 4), np.uint16)
    flags[0, 0] = 1
    source_free = np.zeros((4, 4), bool)
    source_free[:2] = True
    image[3, 3] += 10
    result = prepare_background(
        image,
        variance,
        zodi,
        flags,
        np.ones((4, 4), bool),
        source_free,
        source_free_reference="synthetic known sky",
        zodi_variance=np.full((4, 4), 0.5),
        uncertainty_reference="synthetic independent noise constant sky",
    )
    assert not result.reasons
    assert result.offset == 5
    assert result.offset_variance == pytest.approx(1.5 / 7)
    assert result.image[3, 3] == 10
    assert np.isnan(result.image[0, 0])
    assert result.variance[3, 3] == 1.5  # rank-one offset term is separate
    assert image[3, 3] == 17  # input unmodified
    missing = prepare_background(
        image, variance, zodi, flags, np.ones((4, 4), bool), source_free, source_free_reference=""
    )
    assert "ZODI_UNCERTAINTY_UNKNOWN" in missing.reasons
    assert "SOURCE_FREE_REGION_UNVERIFIED" in missing.reasons


def test_psf_spatial_assessment_and_matching():
    stamps = np.ones((2, 3, 3))
    kwargs = {
        "alignment_reference": "synthetic identity",
        "coverage_reference": "two test zones",
        "policy": POLICY,
    }
    assert not assess_effective_psfs(stamps, stamps, [[0, 0], [1, 1]], **kwargs)[1]
    other = stamps.copy()
    other[1, 1, 1] = 20
    assert assess_effective_psfs(stamps, other, [[0, 0], [1, 1]], **kwargs)[1] == (
        "PSF_MATCHING_REQUIRED",
    )
    image = np.ones((7, 7))
    values, var, good, evidence = apply_psf_kernel(
        image,
        image,
        image.astype(bool),
        np.ones((3, 3)) / 9,
        kernel_reference="synthetic boxcar",
        kernel_uncertainty_reference="test exact kernel",
    )
    assert values[3, 3] == pytest.approx(1)
    assert var[3, 3] == pytest.approx(1 / 9)
    assert not good[0, 0]
    assert evidence["covariance_operator"] == "K diag(input_variance) K.T"


def test_real_gate_and_stale_record(prepared):
    frames, _ = frames_and_track(prepared)
    a, b = frames.values()
    # Existing synthetic functionality remains available.
    assert compute_difference(a, b).status == "AVAILABLE"
    for f in (a, b):
        f.provenance["validation"]["metadata"].pop("SYNTHET")
        f.provenance["validation"]["metadata"]["HISTORY"] = [f"[CALIB] spectral_wcs {UUID}"]
    # Even CALVER cannot bypass the new gate.
    assert "PAIR_PREPARATION_REQUIRED" in compute_difference(a, b).reason_codes
    region = np.ones(a.image.shape, bool)
    record = record_pair_preparation(a, b, region)
    rejected = compute_difference(a, b, preparation=record)
    assert rejected.status == "REJECTED" and rejected.image is None
    assert "SPECTRAL_EVIDENCE_MISSING" in rejected.reason_codes
    assert "BACKGROUND_EVIDENCE_MISSING" in rejected.reason_codes
    assert "PSF_EVIDENCE_MISSING" in rejected.reason_codes
    assert "PAIR_COVARIANCE_MODEL_UNAVAILABLE" in rejected.reason_codes
    b.image[0, 0] += 1
    assert (
        "PAIR_PREPARATION_INPUT_MISMATCH"
        in compute_difference(a, b, preparation=record).reason_codes
    )
    # Removing rejection codes from a serialized record does not certify it.
    edited = replace(record, reasons=())
    assert compute_difference(a, b, preparation=edited).status == "REJECTED"


def test_independent_provenance_does_not_fabricate_calver(prepared, spectral):
    m, path = spectral
    frames, _ = frames_and_track(prepared)
    a, b = frames.values()
    for frame in (a, b):
        metadata = frame.provenance["validation"]["metadata"]
        metadata.pop("SYNTHET")
        metadata.pop("CALVER")
        metadata["HISTORY"] = [f"[CALIB] spectral_wcs {UUID}"]
    kwargs = {"products": (m.calibration,), "product_paths": {m.calibration.sha256: path}}
    record = record_pair_preparation(a, b, np.ones(a.image.shape, bool), **kwargs)
    result = compute_difference(a, b, preparation=record)
    assert "CALIBRATION_UNKNOWN" not in result.reason_codes
    assert not any(r.startswith("CALIBRATION_UNVERIFIED") for r in result.reason_codes)
    assert result.status == "REJECTED"  # Missing other mandatory preparation evidence.
    assert "CALVER" not in a.provenance["validation"]["metadata"]
    assert "CALVER" not in b.provenance["validation"]["metadata"]
    unverified = record_pair_preparation(
        a, b, np.ones(a.image.shape, bool), products=(m.calibration,)
    )
    assert "CALIBRATION_CACHE_UNVERIFIED" in unverified.reasons
    assert "CALIBRATION_UNKNOWN" in compute_difference(a, b, preparation=unverified).reason_codes


def test_native_epsf_zone_selection(tmp_path):
    path = tmp_path / "epsf.fits"
    columns = [
        fits.Column(name=name, format="E", array=values)
        for name, values in (
            ("XCENTER", [1.0, 3.0]),
            ("YCENTER", [1.0, 1.0]),
            ("XWIDTH", [2.0, 2.0]),
            ("YWIDTH", [2.0, 2.0]),
        )
    ]
    columns.append(
        fits.Column(
            name="EPSF",
            format="9D",
            dim="(3,3)",
            array=np.stack([np.ones((3, 3)), np.full((3, 3), 2)]),
        )
    )
    fits.HDUList([fits.PrimaryHDU(), fits.BinTableHDU.from_columns(columns, name="EPSF")]).writeto(
        path
    )
    stamps, evidence = load_native_epsf_samples(path, np.array([[1, 1], [2, 1]]))
    assert evidence["native_zone_indexes"] == [0, 1]
    assert not evidence["post_alignment_verified"]
    assert stamps[1, 0, 0] == 2
    with pytest.raises(ValueError, match="ZONE_MISSING"):
        load_native_epsf_samples(path, np.array([[10, 10]]))
