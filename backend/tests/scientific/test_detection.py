import numpy as np
import pytest
from change_lens.pipeline.alignment import reproject_frame
from change_lens.pipeline.detection import Quality, detect_sources

from .conftest import gaussian


def test_isolated_and_multiple_sources_deterministic():
    image = gaussian(center=(10.2, 10.3)) + gaussian(center=(30.1, 28.7), background=0)
    variance = np.ones(image.shape)
    original = image.copy()
    result = detect_sources(image, variance)
    assert len(result.sources) == 2
    assert result == detect_sources(image, variance)
    np.testing.assert_allclose(
        [(s.x, s.y) for s in result.sources], [(10.2, 10.3), (30.1, 28.7)], atol=0.1
    )
    assert all(s.quality == Quality.VALID and s.peak_sigma > 60 for s in result.sources)
    assert all(s.valid_fraction == 1 for s in result.sources)
    np.testing.assert_array_equal(image, original)


@pytest.mark.parametrize("seed", [7, 13, 42])
def test_noise_only(seed):
    image = np.random.default_rng(seed).normal(12, 2, (101, 101))
    result = detect_sources(image, np.full(image.shape, 4.0))
    assert not result.sources
    assert result.background == pytest.approx(12, abs=0.1)
    assert result.noise == pytest.approx(2, abs=0.1)


def test_masked_artifact_and_missing_coverage():
    image = gaussian(center=(10, 10)) + gaussian(center=(30, 30), amplitude=10000, background=0)
    usable = np.ones(image.shape, bool)
    usable[23:38, 23:38] = False
    result = detect_sources(image, np.ones(image.shape), usable_mask=usable)
    assert len(result.sources) == 1 and result.sources[0].x == pytest.approx(10, abs=0.1)
    result = detect_sources(image, np.ones(image.shape), footprint=usable.astype(float))
    assert len(result.sources) == 1


def test_edge_and_saturation_are_not_clean():
    image = gaussian(center=(0.5, 20))
    source = detect_sources(image, np.ones(image.shape)).sources[0]
    assert source.quality == Quality.AMBIGUOUS and "EDGE_TRUNCATED" in source.warnings
    image = gaussian()
    source = detect_sources(image, np.ones(image.shape), saturation_level=50).sources[0]
    assert source.quality == Quality.AMBIGUOUS and "SATURATED" in source.warnings


def test_threshold_variance_and_minimum_size():
    image = gaussian(amplitude=8)
    variance = np.ones(image.shape)
    assert len(detect_sources(image, variance, threshold_sigma=3).sources) == 1
    assert not detect_sources(image, variance, threshold_sigma=10).sources
    assert not detect_sources(image, variance * 100).sources
    image = np.zeros((15, 15))
    image[7, 7] = 1000
    assert not detect_sources(image, np.ones(image.shape)).sources


def test_blend_warning():
    image = gaussian(center=(17, 20), sigma=2) + gaussian(center=(23, 20), sigma=2, background=0)
    sources = detect_sources(image, np.ones(image.shape), threshold_sigma=3).sources
    assert len(sources) == 1
    assert "POSSIBLE_BLEND" in sources[0].warnings


def test_aligned_warning_sky_bounds_and_empty(prepared):
    flags = np.zeros((41, 41), np.uint16)
    flags[20, 20] = 2
    item = prepared(flags=flags)
    frame = reproject_frame(item.validated, item.masks, item.validated.wcs, (41, 41))
    result = detect_sources(frame)
    source = result.sources[0]
    assert source.flags == 2 and "FLAG_WARNING" in source.warnings
    assert len(source.sky_bounds) == 4
    frame.usable_mask[:] = False
    result = detect_sources(frame)
    assert not result.sources and result.background is None
    assert "NO_USABLE_PIXELS" in result.warnings


@pytest.mark.parametrize("threshold", [0, -1, np.nan, np.inf])
def test_invalid_threshold(threshold):
    with pytest.raises(ValueError):
        detect_sources(np.ones((5, 5)), np.ones((5, 5)), threshold)
