"""SCI-003: surface-brightness reprojection with explicit bilinear stencils.

Zero-based (x, y) coordinates throughout. No flux-per-pixel area scaling is
appropriate for SCI-001 surface brightness. Variance assumes independent input
pixels; output covariance is NOT represented. All nonzero stencil contributors
must be usable: holes are never filled or renormalized.
"""

from dataclasses import dataclass

import numpy as np
from astropy.io.fits import Header
from astropy.wcs import WCS
from astropy.wcs.utils import pixel_to_pixel

from change_lens.fits.validator import ValidationResult
from change_lens.pipeline.masks import MaskResult


@dataclass
class AlignedFrame:
    image: np.ndarray
    variance: np.ndarray
    usable_mask: np.ndarray
    footprint: np.ndarray  # interpolation support coverage, not spherical area
    flags: np.ndarray  # bitwise union, never interpolation
    reason_masks: dict[str, np.ndarray]
    wcs: WCS
    provenance: dict
    warnings: tuple[str, ...]

    @property
    def valid_fraction(self) -> float:
        return float(self.usable_mask.mean())


def celestial_grid(wcs: WCS, shape: tuple[int, int]) -> WCS:
    """Validate and copy a two-dimensional celestial grid, including roundtrip."""
    try:
        if len(shape) != 2 or any(int(n) != n or n <= 0 for n in shape):
            raise ValueError("shape")
        if wcs.pixel_n_dim != 2 or not wcs.has_celestial:
            raise ValueError("celestial axes")
        grid = wcs.celestial.deepcopy()
        matrix = grid.pixel_scale_matrix
        if not np.isfinite(matrix).all() or abs(np.linalg.det(matrix)) == 0:
            raise ValueError("singular matrix")
        y, x = np.meshgrid(
            [0, (shape[0] - 1) / 2, shape[0] - 1], [0, (shape[1] - 1) / 2, shape[1] - 1]
        )
        sky = grid.pixel_to_world(x, y)
        xx, yy = grid.world_to_pixel(sky)
        if not (np.allclose(xx, x, atol=1e-5, rtol=0) and np.allclose(yy, y, atol=1e-5, rtol=0)):
            raise ValueError("roundtrip")
        return grid
    except Exception as exc:
        raise ValueError("INVALID_WCS_OR_GRID") from exc


def reproject_frame(
    validated: ValidationResult,
    masks: MaskResult,
    reference_wcs: WCS,
    shape_out: tuple[int, int],
) -> AlignedFrame:
    """Map a validated frame to an explicit reference grid without mutation.

    Astropy full celestial transforms include frame conversion and distortion.
    Explicit bilinear weights apply to IMAGE and their squares to VARIANCE.
    Coordinates within 1e-7 pixel of integers snap to remove WCS edge roundoff.
    Footprints measure interpolation support, not spherical pixel-area overlap.
    """
    validated.require_valid()
    image, variance = validated.image, validated.variance
    if image is None or variance is None or validated.wcs is None:
        raise ValueError("MISSING_VALIDATED_ARRAYS_OR_WCS")
    if image.ndim != 2 or not image.size or variance.shape != image.shape:
        raise ValueError("INVALID_ARRAY_SHAPE")
    layers = [masks.usable_mask, masks.flags, *masks.reason_masks.values()]
    if any(layer.shape != image.shape for layer in layers):
        raise ValueError("INVALID_MASK_SHAPE")
    source = celestial_grid(validated.wcs, image.shape)
    target = celestial_grid(reference_wcs, shape_out)
    yy, xx = np.indices(shape_out, dtype=float)
    try:
        x, y = pixel_to_pixel(target, source, xx, yy)
    except Exception as exc:
        raise ValueError("WCS_TRANSFORM_FAILED") from exc
    finite = np.isfinite(x) & np.isfinite(y)
    finite &= (x >= -1) & (x <= image.shape[1]) & (y >= -1) & (y <= image.shape[0])
    x, y = np.where(finite, x, -2), np.where(finite, y, -2)
    x = np.where(abs(x - np.rint(x)) < 1e-7, np.rint(x), x)
    y = np.where(abs(y - np.rint(y)) < 1e-7, np.rint(y), y)
    x0, y0 = np.floor(x).astype(int), np.floor(y).astype(int)
    dx, dy = x - x0, y - y0
    values = np.zeros(shape_out)
    variances = np.zeros(shape_out)
    footprint = np.zeros(shape_out)
    usable = finite.copy()
    flags = np.zeros(shape_out, dtype=np.uint64)
    reasons = {name: np.zeros(shape_out, bool) for name in masks.reason_masks}
    for name in ("BAD_PIXEL", "INVALID_VARIANCE", "OUTSIDE_FOOTPRINT"):
        reasons.setdefault(name, np.zeros(shape_out, bool))
    input_covered = ~masks.reason_masks.get("OUTSIDE_FOOTPRINT", np.zeros(image.shape, bool))
    for ox, oy, weight in (
        (0, 0, (1 - dx) * (1 - dy)),
        (1, 0, dx * (1 - dy)),
        (0, 1, (1 - dx) * dy),
        (1, 1, dx * dy),
    ):
        xi, yi = x0 + ox, y0 + oy
        active = weight > 0
        inside = finite & (xi >= 0) & (yi >= 0) & (xi < image.shape[1]) & (yi < image.shape[0])
        xi, yi = np.clip(xi, 0, image.shape[1] - 1), np.clip(yi, 0, image.shape[0] - 1)
        contributes = active & inside
        covered = inside & input_covered[yi, xi]
        footprint += np.where(covered, weight, 0)
        good_image = np.isfinite(image[yi, xi])
        good_var = np.isfinite(variance[yi, xi]) & (variance[yi, xi] > 0)
        good = covered & masks.usable_mask[yi, xi] & good_image & good_var
        usable &= ~active | good
        values += weight * np.where(good, image[yi, xi], 0)
        variances += weight**2 * np.where(good, variance[yi, xi], 0)
        flags |= np.where(contributes, masks.flags[yi, xi], 0).astype(np.uint64)
        for name, layer in masks.reason_masks.items():
            reasons[name] |= contributes & layer[yi, xi]
        reasons["BAD_PIXEL"] |= contributes & ~good_image
        reasons["INVALID_VARIANCE"] |= contributes & ~good_var
        reasons["OUTSIDE_FOOTPRINT"] |= active & ~covered
    reasons["OUTSIDE_FOOTPRINT"] |= ~finite
    values[~usable] = np.nan
    variances[~usable] = np.nan
    warnings = tuple(dict.fromkeys([*masks.warnings, "RESAMPLING_COVARIANCE_NOT_MODELED"]))
    return AlignedFrame(
        values,
        variances,
        usable,
        footprint,
        flags,
        reasons,
        target,
        {
            "validation": validated.report.model_dump(mode="json"),
            "mask_policy": masks.policy_version,
            "mask_product": masks.policy_product,
            "method": "bilinear-strict-v1",
            "variance_method": "sum_squared_weights",
            "source_wcs": source.to_header(relax=True).tostring(),
            "target_wcs": target.to_header(relax=True).tostring(),
            "shape_out": list(shape_out),
            "pixel_scale_ratio": float(
                np.sqrt(
                    abs(
                        np.linalg.det(source.pixel_scale_matrix)
                        / np.linalg.det(target.pixel_scale_matrix)
                    )
                )
            ),
        },
        warnings,
    )


def align_observation_wcs(
    reference_header: Header, target_header: Header, target_data: np.ndarray
) -> np.ndarray:
    """Legacy intensity-only helper; use reproject_frame for measurements.

    Reference NAXIS1/2 is required. This API makes no variance or quality claims.
    """
    from reproject import reproject_interp

    shape = (reference_header["NAXIS2"], reference_header["NAXIS1"])
    target = celestial_grid(WCS(target_header), target_data.shape)
    reference = celestial_grid(WCS(reference_header), shape)
    image, _ = reproject_interp((target_data, target), reference, shape_out=shape)
    return image
