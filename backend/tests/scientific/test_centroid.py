import numpy as np
import pytest
from change_lens.pipeline.centroid import measure_centroid
from change_lens.pipeline.detection import Quality, detect_sources

from .conftest import gaussian, make_wcs


@pytest.mark.parametrize("center", [(20.3, 19.7), (20.5, 20.5), (18.12, 22.87)])
def test_subpixel_and_sky_conversion(center):
    image = gaussian(center=center)
    original = image.copy()
    wcs = make_wcs(angle=180)
    seed = tuple(np.rint(center))
    result = measure_centroid(image, seed, np.ones(image.shape), wcs=wcs)
    assert result.quality == Quality.VALID
    assert (result.x, result.y) == pytest.approx(center, abs=1e-5)
    expected = wcs.pixel_to_world(*center).icrs
    assert result.ra_deg == pytest.approx(expected.ra.deg, abs=1e-8)
    assert result.dec_deg == pytest.approx(expected.dec.deg, abs=1e-8)
    assert result.uncertainty_arcsec > 0
    assert result.background == pytest.approx(12, abs=1e-5)
    np.testing.assert_array_equal(image, original)
    assert result == measure_centroid(image, seed, np.ones(image.shape), wcs=wcs)


def test_noisy_masked_source():
    image = gaussian() + np.random.default_rng(29).normal(0, 1, (41, 41))
    usable = np.ones(image.shape, bool)
    usable[20, 20] = False
    image[20, 20] = 1e8
    result = measure_centroid(
        image, (20, 20), np.ones(image.shape), wcs=make_wcs(), usable_mask=usable
    )
    assert (result.x, result.y) == pytest.approx((20.3, 19.7), abs=0.08)
    assert result.quality == Quality.AMBIGUOUS
    assert "MASKED_FIT_REGION" in result.warnings


def test_uncertainty_scales_with_noise_and_signal():
    image = gaussian()
    a = measure_centroid(image, (20, 20), np.ones(image.shape), wcs=make_wcs())
    b = measure_centroid(image, (20, 20), np.full(image.shape, 4.0), wcs=make_wcs())
    c = measure_centroid(gaussian(amplitude=160), (20, 20), np.ones(image.shape), wcs=make_wcs())
    assert b.uncertainty_x == pytest.approx(a.uncertainty_x * 2, rel=0.01)
    assert c.uncertainty_x == pytest.approx(a.uncertainty_x / 2, rel=0.01)
    assert b.snr == pytest.approx(a.snr / 2, rel=0.01)


@pytest.mark.parametrize("center", [(0.8, 20), (39.4, 20), (20, 0.8), (20, 39.4)])
def test_edge_truncation(center):
    image = gaussian(center=center)
    result = measure_centroid(image, center, np.ones(image.shape), wcs=make_wcs())
    assert result.quality != Quality.VALID
    if result.x is not None:
        assert (result.x, result.y) == pytest.approx(center, abs=0.02)
        assert "EDGE_TRUNCATED" in result.warnings


def test_low_snr_and_invalid_cases():
    image = gaussian(amplitude=1)
    result = measure_centroid(image, (20, 20), np.ones(image.shape), wcs=make_wcs())
    assert result.quality == Quality.AMBIGUOUS and "LOW_SNR" in result.warnings
    for position in [(np.nan, 10), (-1, 10), (100, 100)]:
        result = measure_centroid(image, position, np.ones(image.shape))
        assert result.quality == Quality.UNAVAILABLE and result.x is None
    result = measure_centroid(image, (20, 20), np.full(image.shape, np.nan))
    assert result.quality == Quality.UNAVAILABLE and result.uncertainty_x is None
    result = measure_centroid(np.ones((41, 41)), (20, 20), np.ones((41, 41)))
    assert result.quality == Quality.UNAVAILABLE


def test_blend_and_saturation():
    image = gaussian(center=(17, 20), sigma=2) + gaussian(center=(23, 20), sigma=2, background=0)
    source = detect_sources(image, np.ones(image.shape), threshold_sigma=3).sources[0]
    result = measure_centroid(image, source, np.ones(image.shape), wcs=make_wcs(), radius=9)
    assert result.quality != Quality.VALID and "POSSIBLE_BLEND" in result.warnings
    image = gaussian()
    result = measure_centroid(
        image, (20, 20), np.ones(image.shape), wcs=make_wcs(), saturation_level=50
    )
    assert result.quality == Quality.AMBIGUOUS and "SATURATED" in result.warnings


def test_invalid_wcs_and_heavy_mask():
    image = gaussian()
    wcs = make_wcs()
    wcs.wcs.cd = np.zeros((2, 2))
    result = measure_centroid(image, (20, 20), np.ones(image.shape), wcs=wcs)
    assert result.quality == Quality.UNAVAILABLE and result.ra_deg is None
    usable = np.zeros(image.shape, bool)
    usable[20, 20] = True
    result = measure_centroid(image, (20, 20), np.ones(image.shape), usable_mask=usable)
    assert result.quality == Quality.UNAVAILABLE
