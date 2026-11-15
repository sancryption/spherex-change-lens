"""Analytic linear-operator tests, not real-data approval evidence."""

from types import SimpleNamespace

import numpy as np
import pytest
from change_lens.pipeline.alignment import reproject_frame
from change_lens.pipeline.propagation import (
    build_alignment_operator,
    compare_spectral_mixtures,
    difference_covariance,
    propagate_noise,
    propagate_spectral_map,
)

from .conftest import make_wcs


def test_operator_matches_existing_alignment(prepared):
    image = np.arange(81, dtype=float).reshape(9, 9)
    observation = prepared(image=image, variance=np.full((9, 9), 2))
    target = make_wcs(shift=(0.4, 0.2), shape=image.shape)
    aligned = reproject_frame(observation.validated, observation.masks, target, image.shape)
    op = build_alignment_operator(
        observation.validated.wcs, image.shape, target, image.shape, observation.masks.usable_mask
    )
    np.testing.assert_array_equal(op.usable_mask, aligned.usable_mask)
    np.testing.assert_allclose(op.apply(image), aligned.image, atol=1e-12)
    noise = propagate_noise(op, observation.validated.variance)
    np.testing.assert_allclose(noise.diagonal(), aligned.variance, atol=1e-12)
    cov = noise.covariance(np.array([40, 41]))
    assert cov[0, 1] > 0  # Shared interpolation inputs create covariance.
    assert np.linalg.eigvalsh(cov).min() >= 0


def test_background_covariance_includes_data_mean_correlation():
    shape = (2, 2)
    wcs = make_wcs(shape=shape)
    op = build_alignment_operator(wcs, shape, wcs, shape, np.ones(shape, bool))
    b = np.full(shape, 0.25)
    noise = propagate_noise(op, np.ones(shape), background_weights=b)
    expected = np.eye(4) - np.ones((4, 4)) / 4
    np.testing.assert_allclose(noise.covariance(np.arange(4)), expected, atol=1e-12)
    np.testing.assert_allclose(noise.diagonal(), 0.75)


def test_shared_calibration_mode_cancels_in_difference():
    shape = (3, 3)
    wcs = make_wcs(shape=shape)
    op = build_alignment_operator(wcs, shape, wcs, shape, np.ones(shape, bool))
    mode = np.full(shape, 2.0)
    a = propagate_noise(op, np.ones(shape), nuisance_modes={"shared-gain": mode})
    b = propagate_noise(op, np.ones(shape), nuisance_modes={"shared-gain": mode})
    indexes = np.array([0, 4, 8])
    np.testing.assert_allclose(
        difference_covariance(a, b, indexes, shared_modes=("shared-gain",)), np.eye(3) * 2
    )
    np.testing.assert_allclose(
        difference_covariance(a, b, indexes, shared_modes=()), np.eye(3) * 2 + 8
    )
    with pytest.raises(ValueError, match="SHARED_UNCERTAINTY"):
        difference_covariance(a, b, indexes, shared_modes=("missing",))


def test_spectral_mixture_retains_contributors_and_rejects_masked_region():
    shape = (5, 5)
    wcs = make_wcs(shape=shape)
    shifted = make_wcs(shift=(0.5, 0.5), shape=shape)
    op = build_alignment_operator(wcs, shape, shifted, shape, np.ones(shape, bool))
    wave = np.ones(shape)
    wave[2, 2] = 1.1
    m = SimpleNamespace(
        wavelength_um=wave,
        bandwidth_um=np.full(shape, 0.1),
        calibration=SimpleNamespace(sha256="synthetic"),
    )
    mixture = propagate_spectral_map(m, op)
    assert len(mixture.contributors(12)["weights"]) == 4
    region = np.zeros(shape, bool)
    region[2, 2] = True
    evidence, reasons = compare_spectral_mixtures(mixture, mixture, region)
    assert evidence["max_contributor_delta_um"] == pytest.approx(0.1)
    assert evidence["max_weighted_mean_delta_um"] == 0
    assert "SPECTRAL_POLICY_UNREVIEWED" in reasons
    region[:] = True
    assert compare_spectral_mixtures(mixture, mixture, region)[1] == (
        "SPECTRAL_REGION_UNSUPPORTED",
    )


def test_masked_contributor_is_not_renormalized():
    shape = (5, 5)
    good = np.ones(shape, bool)
    good[2, 2] = False
    op = build_alignment_operator(
        make_wcs(shape=shape), shape, make_wcs(shift=(0.5, 0.5), shape=shape), shape, good
    )
    assert not op.usable_mask[2, 2]
    assert op.matrix.getrow(12).nnz == 0


def test_disjoint_intervals_reject_without_an_invented_threshold():
    from change_lens.pipeline.propagation import propagate_interval_arrays

    shape = (3, 3)
    wcs = make_wcs(shape=shape)
    region = np.ones(shape, bool)
    op = build_alignment_operator(wcs, shape, wcs, shape, region)
    a = propagate_interval_arrays(np.full(shape, 0.83), np.full(shape, 0.02), op, "candidate")
    b = propagate_interval_arrays(np.full(shape, 1.05), np.full(shape, 0.025), op, "candidate")
    evidence, reasons = compare_spectral_mixtures(a, b, region)
    assert evidence["disjoint_interval_pixels"] == 9
    assert "SPECTRAL_BANDWIDTH_INTERVALS_DISJOINT" in reasons
    assert "SPECTRAL_CALIBRATION_UNVERIFIED" in reasons
    assert "SPECTRAL_POLICY_UNREVIEWED" in reasons
