"""SCI-004 deterministic candidate regions, not a discovery classifier.

Positive per-pixel residual thresholds and 8-connected components are used.
A sigma-clipped global median/MAD is a constant-background approximation;
structured backgrounds and unresolved blends require subsequent review.
Significances assume diagonal noise and are screening statistics.
"""

from dataclasses import dataclass
from enum import StrEnum

import numpy as np
from astropy.stats import sigma_clip
from scipy import ndimage

from change_lens.pipeline.alignment import AlignedFrame


class Quality(StrEnum):
    VALID = "VALID"
    AMBIGUOUS = "AMBIGUOUS"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True)
class SourceRegion:
    source_id: str
    x: float
    y: float
    bounds: tuple[int, int, int, int]  # x0, y0, x1, y1; exclusive upper bounds
    area: int
    peak_sigma: float
    aggregate_sigma: float
    valid_fraction: float  # padded bounding box, including off-image pixels
    flags: int
    quality: Quality
    warnings: tuple[str, ...]
    sky_bounds: tuple[tuple[float, float], ...] | None = None  # ICRS corners


@dataclass(frozen=True)
class DetectionResult:
    sources: tuple[SourceRegion, ...]
    background: float | None
    noise: float | None
    threshold_sigma: float
    warnings: tuple[str, ...]
    method: str = "clipped-median-mad-components-v1"


def valid_pixels(
    image: np.ndarray,
    variance: np.ndarray,
    usable_mask: np.ndarray | None,
    footprint: np.ndarray | None,
) -> np.ndarray:
    if image.ndim != 2 or not image.size or image.shape != variance.shape:
        raise ValueError("INVALID_ARRAY_SHAPE")
    valid = np.isfinite(image) & np.isfinite(variance) & (variance > 0)
    if usable_mask is not None:
        if usable_mask.shape != image.shape or usable_mask.dtype != np.bool_:
            raise ValueError("INVALID_USABLE_MASK")
        valid &= usable_mask
    if footprint is not None:
        if footprint.shape != image.shape:
            raise ValueError("INVALID_FOOTPRINT_SHAPE")
        valid &= np.isfinite(footprint) & (footprint >= 1 - 1e-10)
    return valid


def detect_sources(
    science_image: np.ndarray | AlignedFrame,
    variance_image: np.ndarray | None = None,
    threshold_sigma: float = 5.0,
    *,
    usable_mask: np.ndarray | None = None,
    footprint: np.ndarray | None = None,
    min_pixels: int = 3,
    quality_padding: int = 2,
    saturation_level: float | None = None,
) -> DetectionResult:
    """Detect positive components in fixed raster order; no implicit deblending.

    Variance is required. The larger of supplied variance and empirical MAD^2
    supplies a conservative noise floor. Saturation is caller-specified in native
    image units; no official flag meanings or detector thresholds are assumed.
    """
    if not np.isfinite(threshold_sigma) or threshold_sigma <= 0:
        raise ValueError("INVALID_THRESHOLD")
    for n, minimum in ((min_pixels, 1), (quality_padding, 1)):
        if isinstance(n, bool) or not isinstance(n, int) or n < minimum:
            raise ValueError("INVALID_COMPONENT_CONFIGURATION")
    if saturation_level is not None and not np.isfinite(saturation_level):
        raise ValueError("INVALID_SATURATION_LEVEL")
    frame = science_image if isinstance(science_image, AlignedFrame) else None
    if frame is not None:
        if variance_image is not None or usable_mask is not None or footprint is not None:
            raise ValueError("ALIGNED_FRAME_ALREADY_CONTAINS_QUALITY")
        science_image, variance_image = frame.image, frame.variance
        usable_mask, footprint = frame.usable_mask, frame.footprint
    if variance_image is None:
        raise ValueError("VARIANCE_REQUIRED")
    valid = valid_pixels(science_image, variance_image, usable_mask, footprint)
    warnings = ["DIAGONAL_NOISE_SCREENING_STATISTIC", "CONSTANT_BACKGROUND_APPROXIMATION"]
    if frame:
        warnings.extend(frame.warnings)
    if not valid.any():
        return DetectionResult(
            (), None, None, threshold_sigma, tuple(warnings + ["NO_USABLE_PIXELS"])
        )
    sample = sigma_clip(science_image[valid], sigma=3, maxiters=5).compressed()
    background = float(np.median(sample))
    noise = float(1.4826 * np.median(abs(sample - background)))
    effective_var = np.maximum(variance_image, noise**2)
    residual = science_image - background
    significance = np.full(science_image.shape, -np.inf)
    significance[valid] = residual[valid] / np.sqrt(effective_var[valid])
    selected = valid & (significance >= threshold_sigma)
    labels, count = ndimage.label(selected, structure=np.ones((3, 3)))
    maxima = selected & (significance == ndimage.maximum_filter(significance, size=3))
    sources = []
    for label in range(1, count + 1):
        component = labels == label
        y, x = np.nonzero(component)
        if len(x) < min_pixels:
            continue
        weights = residual[component]
        cx, cy = float(np.average(x, weights=weights)), float(np.average(y, weights=weights))
        x0, y0, x1, y1 = int(x.min()), int(y.min()), int(x.max() + 1), int(y.max() + 1)
        p = quality_padding
        bx0, by0, bx1, by1 = x0 - p, y0 - p, x1 + p, y1 + p
        box = np.s_[max(0, by0) : min(valid.shape[0], by1), max(0, bx0) : min(valid.shape[1], bx1)]
        fraction = float(valid[box].sum() / ((bx1 - bx0) * (by1 - by0)))
        reasons = []
        if bx0 < 0 or by0 < 0 or bx1 > valid.shape[1] or by1 > valid.shape[0]:
            reasons.append("EDGE_TRUNCATED")
        if not valid[box].all():
            reasons.append("MASK_NEAR_SOURCE")
        _, peaks = ndimage.label(maxima & component, structure=np.ones((3, 3)))
        if peaks > 1:
            reasons.append("POSSIBLE_BLEND")
        if saturation_level is not None and np.any(science_image[component] >= saturation_level):
            reasons.append("SATURATED")
        flags = 0
        sky_bounds = None
        if frame:
            flags = int(np.bitwise_or.reduce(frame.flags[box].ravel()))
            if frame.reason_masks.get("FLAG_WARNING", np.zeros(valid.shape, bool))[box].any():
                reasons.append("FLAG_WARNING")
            sky = frame.wcs.pixel_to_world([x0, x1 - 1, x1 - 1, x0], [y0, y0, y1 - 1, y1 - 1]).icrs
            sky_bounds = tuple(zip(sky.ra.deg.tolist(), sky.dec.deg.tolist(), strict=True))
        sources.append(
            SourceRegion(
                f"source_{len(sources) + 1:04d}",
                cx,
                cy,
                (x0, y0, x1, y1),
                len(x),
                float(significance[component].max()),
                float(weights.sum() / np.sqrt(effective_var[component].sum())),
                fraction,
                flags,
                Quality.AMBIGUOUS if reasons else Quality.VALID,
                tuple(reasons),
                sky_bounds,
            )
        )
    return DetectionResult(
        tuple(sources), background, noise, threshold_sigma, tuple(dict.fromkeys(warnings))
    )
