from dataclasses import replace

import numpy as np
import pytest
from change_lens.pipeline.brightness import (
    BrightnessPolicy,
    aperture_weights,
    extract_photometry,
    measure_aperture,
)
from change_lens.pipeline.detection import Quality

from .phase3_helpers import frames_and_track


@pytest.mark.parametrize(
    "amps,state", [((80, 80), "STABLE"), ((80, 160), "BRIGHTER"), ((160, 80), "FAINTER")]
)
def test_brightness_direction(prepared, amps, state):
    frames, track = frames_and_track(prepared, amplitudes=amps)
    result = extract_photometry(track, frames)
    assert result.status == state
    assert result.measurements[0].unit == "MJy/sr"
    assert result.measurements[0].method == "subpixel-aperture-mean-annulus-mean-v1"
    assert "CALIBRATION_UNCERTAINTY_OMITTED" in result.warnings


def test_background_change_is_subtracted(prepared):
    frames, track = frames_and_track(prepared, backgrounds=(12, 50))
    result = extract_photometry(track, frames)
    assert result.status == "STABLE"
    assert result.measurements[1].background - result.measurements[0].background == pytest.approx(
        38
    )
    assert result.comparisons[0].difference == pytest.approx(0, abs=1e-10)


def test_wrong_epoch_frame_cannot_be_reused(prepared):
    frames, track = frames_and_track(prepared)
    result = measure_aperture(frames["a"], track.points[1])
    assert result.quality == Quality.UNAVAILABLE
    assert "FRAME_OBSERVATION_ID_MISMATCH" in result.warnings


def test_background_scatter_inflates_uncertainty(prepared):
    frames, track = frames_and_track(prepared)
    frame = frames["a"]
    before = measure_aperture(frame, track.points[0])
    _, annulus, _, _ = aperture_weights(frame.image.shape, 20, 20, BrightnessPolicy())
    y, x = np.indices(frame.image.shape)
    frame.image[annulus > 0] += (10 * (-1.0) ** (x + y))[annulus > 0]
    after = measure_aperture(frame, track.points[0])
    assert after.background_uncertainty > before.background_uncertainty
    assert after.uncertainty > before.uncertainty


def test_squared_weights_and_background_variance(prepared):
    frames, track = frames_and_track(prepared)
    frame = frames["a"]
    frame.image[:] = 12
    policy = BrightnessPolicy()
    a, b, area, bg_area = aperture_weights(frame.image.shape, 20, 20, policy)
    frame.image[a > 0] = 22
    result = measure_aperture(frame, track.points[0], policy=policy)
    expected_variance = np.sum((a / area) ** 2) + np.sum((b / bg_area) ** 2)
    assert result.value == pytest.approx(10)
    assert result.uncertainty**2 == pytest.approx(expected_variance)
    assert result.background_uncertainty**2 == pytest.approx(np.sum((b / bg_area) ** 2))


@pytest.mark.parametrize("bad", [0, -1, float("nan"), float("inf")])
def test_invalid_source_variance_unavailable(prepared, bad):
    frames, track = frames_and_track(prepared)
    frames["b"].variance[20, 20] = bad
    result = extract_photometry(track, frames)
    assert result.status == "UNAVAILABLE"
    assert "INCOMPLETE_OR_INVALID_APERTURE" in result.measurements[1].warnings


@pytest.mark.parametrize("layer", ["mask", "footprint", "image"])
def test_incomplete_aperture_not_renormalized(prepared, layer):
    frames, track = frames_and_track(prepared)
    if layer == "mask":
        frames["b"].usable_mask[20, 20] = False
    elif layer == "footprint":
        frames["b"].footprint[20, 20] = 0.5
    else:
        frames["b"].image[20, 20] = np.nan
    result = extract_photometry(track, frames)
    assert result.status == "UNAVAILABLE"
    assert result.measurements[1].value is None
    assert result.measurements[1].valid_fraction < 1


def test_edge_aperture_unavailable(prepared):
    frames, track = frames_and_track(prepared)
    p = replace(track.points[0], centroid=replace(track.points[0].centroid, x=1))
    result = measure_aperture(frames["a"], p)
    assert result.quality == Quality.UNAVAILABLE
    assert result.valid_fraction < 1


def test_insufficient_background(prepared):
    frames, track = frames_and_track(prepared)
    a, b, _, _ = aperture_weights((41, 41), 20, 20, BrightnessPolicy())
    frames["a"].usable_mask[b > 0] = False
    result = measure_aperture(frames["a"], track.points[0])
    assert result.quality == Quality.UNAVAILABLE
    assert result.warnings[-1] == "INSUFFICIENT_LOCAL_BACKGROUND"
    assert frames["a"].usable_mask[a > 0].all()


@pytest.mark.parametrize("key", ["band", "product", "spectral_plane", "release"])
def test_incompatible_plane(prepared, key):
    frames, track = frames_and_track(prepared)
    frames["b"].provenance["plane_identity"][key] = "different"
    result = extract_photometry(track, frames)
    assert result.status == "UNAVAILABLE"
    assert not result.comparisons


@pytest.mark.parametrize("change", ["calibration", "unit", "grid"])
def test_incompatible_calibration_units_grid(prepared, change):
    frames, track = frames_and_track(prepared)
    if change == "calibration":
        frames["b"].provenance["validation"]["metadata"]["CALVER"] = "other"
    elif change == "unit":
        frames["b"].provenance["validation"]["image_unit"] = "Jy/sr"
    else:
        frames["b"].wcs.wcs.crpix += 1
    assert extract_photometry(track, frames).status == "UNAVAILABLE"


def test_missing_calibration_is_ambiguous(prepared):
    frames, track = frames_and_track(prepared)
    for f in frames.values():
        f.provenance["validation"]["metadata"].pop("CALVER")
    assert extract_photometry(track, frames).status == "AMBIGUOUS"


def test_noise_limited_is_ambiguous(prepared):
    frames, track = frames_and_track(prepared, variance=10000)
    assert extract_photometry(track, frames).status == "AMBIGUOUS"


def test_configurable_change_threshold(prepared):
    frames, track = frames_and_track(prepared, amplitudes=(80, 90))
    assert extract_photometry(track, frames).status == "BRIGHTER"
    assert (
        extract_photometry(track, frames, policy=BrightnessPolicy(absolute_change_floor=100)).status
        == "STABLE"
    )


def test_three_epoch_reversal_is_visible(prepared):
    frames, track = frames_and_track(prepared, amplitudes=(80, 160, 80), backgrounds=(12, 12, 12))
    result = extract_photometry(track, frames)
    assert result.status == "AMBIGUOUS"
    assert len(result.comparisons) == 3
    assert {c.status for c in result.comparisons} == {"BRIGHTER", "FAINTER", "STABLE"}


def test_missing_frame_and_insufficient_epochs(prepared):
    frames, track = frames_and_track(prepared)
    assert extract_photometry(track, {"a": frames["a"]}).status == "UNAVAILABLE"
    assert (
        extract_photometry(replace(track, points=track.points[:1]), frames).status == "UNAVAILABLE"
    )


def test_no_mutation_and_determinism(prepared):
    frames, track = frames_and_track(prepared)
    arrays = {
        k: (v.image.copy(), v.variance.copy(), v.usable_mask.copy()) for k, v in frames.items()
    }
    a = extract_photometry(track, frames)
    b = extract_photometry(replace(track, points=tuple(reversed(track.points))), frames)
    assert a == b
    for k, f in frames.items():
        for before, after in zip(arrays[k], (f.image, f.variance, f.usable_mask), strict=True):
            np.testing.assert_array_equal(before, after)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"aperture_radius": 0},
        {"annulus_inner": 2},
        {"min_background_fraction": 2},
        {"subpixels": 1.5},
        {"subpixels": True},
        {"subpixels": 33},
        {"uncertainty_multiplier": float("nan")},
    ],
)
def test_invalid_policy(kwargs):
    with pytest.raises(ValueError):
        BrightnessPolicy(**kwargs)
