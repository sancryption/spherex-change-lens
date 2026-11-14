"""Deterministic synthetic SCI-011 tests; no authentic verification data."""

from copy import deepcopy

import numpy as np
import pytest
from change_lens.pipeline.difference import compute_difference

from .conftest import make_wcs
from .phase3_helpers import frames_and_track, full_phase2


@pytest.fixture
def pair(prepared):
    frames, _ = frames_and_track(prepared)
    return frames["a"], frames["b"]


def test_identity_direction_variance_and_owned_output(pair):
    a, b = pair
    zero = compute_difference(a, b)
    assert zero.status == "AVAILABLE"
    np.testing.assert_array_equal(zero.image, 0)
    b.image[10, 10] += 5
    b.image[11, 11] -= 3
    a.variance[:] = 2
    b.variance[:] = 7
    result = compute_difference(a, b)
    assert result.image[10, 10] == 5
    assert result.image[11, 11] == -3
    np.testing.assert_array_equal(result.variance, 9)
    assert result.absolute_image[11, 11] == 3
    assert result.normalized_image[10, 10] == pytest.approx(5 / 3)
    assert result.subtraction_order == "later_epoch - earlier_epoch"
    assert (result.earlier_observation_id, result.later_observation_id) == ("a", "b")
    assert (result.earlier_mjd_utc, result.later_mjd_utc) == (60000, 60010)
    repeated = compute_difference(a, b)
    for field in ("image", "variance", "usable_mask", "flags", "footprint"):
        np.testing.assert_array_equal(getattr(result, field), getattr(repeated, field))
        assert not np.shares_memory(getattr(result, field), getattr(a, field))
        assert not np.shares_memory(getattr(result, field), getattr(b, field))
    assert result.provenance == repeated.provenance
    assert result.reason_codes == repeated.reason_codes
    b.image[:] = 0
    b.provenance["validation"]["metadata"]["CALVER"] = "changed"
    assert result.image[10, 10] == 5
    assert result.provenance["later"]["validation"]["metadata"]["CALVER"] == "synthetic-v1"


def test_masks_categorical_flags_and_nonfinite(pair):
    a, b = pair
    a.usable_mask[0, 0] = False
    a.flags[0, 0] = 1
    b.flags[0, 0] = 2
    a.reason_masks["UNKNOWN_FLAG"][0, 0] = True
    b.reason_masks["FLAG_WARNING"][1, 1] = True
    b.flags[1, 1] = 2
    b.image[2, 2] = np.inf
    a.image[3, 3] = np.nan
    b.footprint[4, 4] = 0.5
    result = compute_difference(a, b)
    assert result.flags[0, 0] == 3
    assert result.flags[1, 1] == 2
    assert result.usable_mask[1, 1]  # Retain-with-warning stays usable, not clean.
    for i in (0, 2, 3, 4):
        assert not result.usable_mask[i, i]
        assert np.isnan(result.image[i, i])
        assert np.isnan(result.variance[i, i])
    assert result.reason_masks["FLAG_WARNING"][1, 1]
    assert "UNKNOWN_FLAG" in result.reason_codes
    assert result.variance_status == "PARTIAL"


@pytest.mark.parametrize("value", [0, -1, np.nan, np.inf])
def test_invalid_variance_never_zero_filled(pair, value):
    a, b = pair
    b.variance[4, 5] = value
    result = compute_difference(a, b)
    assert not result.usable_mask[4, 5]
    assert np.isnan(result.variance[4, 5])
    assert result.reason_masks["INVALID_VARIANCE"][4, 5]


@pytest.mark.parametrize("missing", [True, False])
def test_no_uncertainty_is_explicitly_unavailable(pair, missing):
    a, b = pair
    b.variance = None if missing else np.full(b.image.shape, np.nan)
    result = compute_difference(a, b)
    assert result.status == "UNAVAILABLE"
    assert result.variance_status == "UNAVAILABLE"
    assert result.variance is None and result.normalized_image is None
    assert not result.usable_mask.any()
    assert np.isnan(result.image).all()


@pytest.mark.parametrize(
    "field,value",
    [
        ("band", "other"),
        ("spectral_plane", "other"),
        ("release", "other"),
        ("product", "other"),
        ("band", ""),
    ],
)
def test_incompatible_plane(pair, field, value):
    a, b = pair
    b.provenance["plane_identity"][field] = value
    result = compute_difference(a, b)
    assert result.status == "REJECTED"
    assert result.image is None


@pytest.mark.parametrize("unit", [None, "bad-unit", "Jy/sr", "Jy", ""])
def test_units_require_exact_scale(pair, unit):
    a, b = pair
    b.provenance["validation"]["image_unit"] = unit
    assert compute_difference(a, b).status == "REJECTED"


@pytest.mark.parametrize("calibration", [None, "", "other"])
def test_unknown_or_mismatched_calibration_rejected(pair, calibration):
    a, b = pair
    b.provenance["validation"]["metadata"]["CALVER"] = calibration
    assert compute_difference(a, b).status == "REJECTED"


@pytest.mark.parametrize(
    "metadata,reason",
    [
        ({}, "MISSING_OBSERVATION_TIME"),
        ({"MJD-OBS": "nan"}, "INVALID_OBSERVATION_TIME"),
        ({"DATE-OBS": "bad"}, "INVALID_OBSERVATION_TIME"),
        ({"MJD-OBS": 60000}, "INVALID_OBSERVATION_ORDER"),
        ({"MJD-OBS": 59000}, "INVALID_OBSERVATION_ORDER"),
        ({"MJD-OBS": 60010, "DATE-OBS": "2023-02-25T00:00:00"}, "CONFLICTING_OBSERVATION_TIMES"),
        ({"MJD-OBS": 60010, "TIMESYS": "TAI"}, "UNSUPPORTED_TIME_SCALE"),
    ],
)
def test_invalid_times(pair, metadata, reason):
    a, b = pair
    b.provenance["validation"]["metadata"] = {"CALVER": "synthetic-v1", **metadata}
    result = compute_difference(a, b)
    assert result.status == "REJECTED"
    assert reason in result.reason_codes


def test_date_obs_and_reverse_order(pair):
    a, b = pair
    b.provenance["validation"]["metadata"].pop("MJD-OBS")
    b.provenance["validation"]["metadata"]["DATE-OBS"] = "2023-03-07T00:00:00"
    assert compute_difference(a, b).later_mjd_utc == 60010
    assert "INVALID_OBSERVATION_ORDER" in compute_difference(b, a).reason_codes


@pytest.mark.parametrize("obs_id", [None, "", "a"])
def test_missing_or_duplicate_id(pair, obs_id):
    a, b = pair
    b.provenance["validation"]["observation_id"] = obs_id
    assert "UNIQUE_OBSERVATION_IDS_REQUIRED" in compute_difference(a, b).reason_codes


@pytest.mark.parametrize(
    "change",
    [
        "shape",
        "mask",
        "variance",
        "wcs",
        "rotation",
        "grid_metadata",
        "missing_grid",
        "invalid_wcs",
    ],
)
def test_grid_shape_and_alignment_provenance(pair, change):
    a, b = pair
    if change == "shape":
        b.image = b.image[:-1]
    elif change == "mask":
        b.usable_mask = b.usable_mask[:-1]
    elif change == "variance":
        b.variance = b.variance[:-1]
    elif change in ("wcs", "rotation"):
        b.wcs = make_wcs(shift=(1, 0)) if change == "wcs" else make_wcs(angle=90)
        b.provenance["target_wcs"] = b.wcs.to_header(relax=True).tostring()
    elif change == "grid_metadata":
        b.provenance["shape_out"] = [1, 1]
    elif change == "missing_grid":
        b.provenance.pop("target_wcs")
    else:
        b.wcs = None
    result = compute_difference(a, b)
    assert result.status == "REJECTED"
    assert result.image is None


def test_no_overlap_and_overflow(pair):
    a, b = pair
    b.footprint[:] = 0
    assert compute_difference(a, b).status == "UNAVAILABLE"
    b.footprint[:] = 1
    b.image[0, 0], a.image[0, 0] = 1e308, -1e308
    b.variance[1, 1], a.variance[1, 1] = 1e308, 1e308
    result = compute_difference(a, b)
    assert not result.usable_mask[0, 0] and not result.usable_mask[1, 1]


def test_fits_closed_and_inputs_unchanged(tmp_path):
    phase2, paths = full_phase2(tmp_path, "variable")
    a, b = phase2.alignment.frames
    before = [p.read_bytes() for p in paths]
    image, provenance = a.image.copy(), deepcopy(a.provenance)
    result = compute_difference(a, b)
    assert result.status == "AVAILABLE"
    assert result.image[25, 25] == pytest.approx(80)
    np.testing.assert_array_equal(a.image, image)
    assert a.provenance == provenance
    assert [p.read_bytes() for p in paths] == before


@pytest.mark.parametrize(
    "kind,reason",
    [
        ("failed", "INPUT_VALIDATION_NOT_PASSED"),
        ("id_conflict", "OBSERVATION_ID_CONFLICTS_WITH_HEADER"),
        ("blank_calibration", "CALIBRATION_UNKNOWN"),
        ("header_conflict", "PLANE_IDENTITY_CONFLICTS_WITH_HEADER"),
        ("bad_flags", "INVALID_FLAGS"),
        ("bad_mask", "INVALID_MASK_TYPE"),
    ],
)
def test_invalid_provenance_and_quality_types(pair, kind, reason):
    a, b = pair
    validation = b.provenance["validation"]
    if kind == "failed":
        validation["passed"] = False
    elif kind == "id_conflict":
        validation["metadata"]["OBSID"] = "wrong"
    elif kind == "blank_calibration":
        validation["metadata"]["CALVER"] = " "
    elif kind == "header_conflict":
        validation["metadata"]["BAND"] = "wrong"
    elif kind == "bad_flags":
        b.flags = np.full(b.image.shape, -1)
    else:
        b.usable_mask = b.usable_mask.astype(float)
    result = compute_difference(a, b)
    assert result.status == "REJECTED"
    assert reason in result.reason_codes
