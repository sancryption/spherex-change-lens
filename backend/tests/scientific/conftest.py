"""Synthetic-only fixtures for SCI Phase 2; never use authentic archive data."""

import numpy as np
import pytest
from astropy.wcs import WCS
from change_lens.fits.validator import FitsValidationReport, ValidationResult
from change_lens.pipeline.masks import FlagAction, FlagPolicy, build_quality_masks
from change_lens.pipeline.phase2 import PlaneIdentity, PreparedObservation

POLICY = FlagPolicy(
    "synthetic-v1",
    "SYNTHETIC_TEST_ONLY",
    {1: FlagAction.EXCLUDE_UNUSABLE, 2: FlagAction.RETAIN_WITH_WARNING},
)
IDENTITY = PlaneIdentity("test-band", "test-product", "synthetic-plane", "synthetic-release")


def make_wcs(angle=0, scale=1, shift=(0, 0), shape=(41, 41)):
    wcs = WCS(naxis=2)
    wcs.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    wcs.wcs.crval = [359.999, 30]
    wcs.wcs.crpix = [(shape[1] + 1) / 2 + shift[0], (shape[0] + 1) / 2 + shift[1]]
    theta = np.deg2rad(angle)
    wcs.wcs.cd = (
        np.array([[-np.cos(theta), np.sin(theta)], [np.sin(theta), np.cos(theta)]]) * scale / 3600
    )
    return wcs


def gaussian(shape=(41, 41), center=(20.3, 19.7), amplitude=80, sigma=1.5, background=12):
    y, x = np.indices(shape)
    return background + amplitude * np.exp(
        -((x - center[0]) ** 2 + (y - center[1]) ** 2) / (2 * sigma**2)
    )


@pytest.fixture
def prepared():
    def make(image=None, variance=None, flags=None, wcs=None, footprint=None):
        image = gaussian() if image is None else image
        variance = np.ones(image.shape) if variance is None else variance
        flags = np.zeros(image.shape, np.uint16) if flags is None else flags
        wcs = make_wcs(shape=image.shape) if wcs is None else wcs
        report = FitsValidationReport(
            passed=True,
            policy_version="synthetic",
            image_unit="MJy/sr",
            observation_id="synthetic",
            metadata={"SYNTHET": "True"},
        )
        validated = ValidationResult(report, image, variance, flags, wcs)
        return PreparedObservation(
            validated, build_quality_masks(validated, POLICY, footprint=footprint), IDENTITY
        )

    return make
