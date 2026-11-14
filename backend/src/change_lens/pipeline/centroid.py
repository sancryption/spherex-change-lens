"""SCI-005: variance-weighted local Gaussian fits with honest quality states.

An axis-aligned elliptical Gaussian plus constant background is fitted at pixel
centers. This is a simple sampled-PSF model, not calibrated astrometry. The
Jacobian covariance is a diagonal-noise proxy, inflated for excess residuals;
resampling covariance, WCS systematics and PSF mismatch remain unmodeled.
"""

from dataclasses import dataclass

import numpy as np
from astropy.wcs import WCS
from scipy.optimize import least_squares

from change_lens.pipeline.alignment import AlignedFrame, celestial_grid
from change_lens.pipeline.detection import Quality, SourceRegion, valid_pixels


@dataclass(frozen=True)
class CentroidMeasurement:
    x: float | None
    y: float | None
    ra_deg: float | None
    dec_deg: float | None
    uncertainty_x: float | None
    uncertainty_y: float | None
    uncertainty_arcsec: float | None
    snr: float | None
    background: float | None
    valid_fraction: float
    quality: Quality
    warnings: tuple[str, ...]
    source_id: str | None = None
    method: str = "variance-weighted-gaussian-constant-background-v1"
    coordinate_frame: str = "ICRS"


def measure_centroid(
    image: np.ndarray | AlignedFrame,
    initial_position: tuple[float, float] | SourceRegion,
    variance: np.ndarray | None = None,
    *,
    wcs: WCS | None = None,
    usable_mask: np.ndarray | None = None,
    footprint: np.ndarray | None = None,
    radius: int = 6,
    min_snr: float = 5.0,
    saturation_level: float | None = None,
) -> CentroidMeasurement:
    """Fit a local source; ambiguous positions must not support clean claims.

    Radius is a fixed square half-width in pixels; at least 50% of the full
    requested box and >7 valid samples are required. Masked/edge/blended or
    saturated sources remain AMBIGUOUS even if the fit numerically succeeds.
    Unavailable uncertainty is represented by None, never zero.
    """
    if isinstance(radius, bool) or not isinstance(radius, int) or radius < 2:
        raise ValueError("INVALID_RADIUS")
    if not np.isfinite(min_snr) or min_snr <= 0:
        raise ValueError("INVALID_SNR_THRESHOLD")
    if saturation_level is not None and not np.isfinite(saturation_level):
        raise ValueError("INVALID_SATURATION_LEVEL")
    frame = image if isinstance(image, AlignedFrame) else None
    if frame is not None:
        if any(value is not None for value in (variance, wcs, usable_mask, footprint)):
            raise ValueError("ALIGNED_FRAME_ALREADY_CONTAINS_QUALITY")
        image, variance, wcs = frame.image, frame.variance, frame.wcs
        usable_mask, footprint = frame.usable_mask, frame.footprint
    if variance is None:
        raise ValueError("VARIANCE_REQUIRED")
    valid = valid_pixels(image, variance, usable_mask, footprint)
    region = initial_position if isinstance(initial_position, SourceRegion) else None
    position = (region.x, region.y) if region else initial_position
    warnings = list(region.warnings) if region else []
    warnings += ["DIAGONAL_COVARIANCE_PROXY", "PSF_AND_WCS_SYSTEMATICS_NOT_MODELED"]
    if frame:
        warnings.extend(frame.warnings)
    source_id = region.source_id if region else None

    def unavailable(reason: str, fraction: float = 0) -> CentroidMeasurement:
        return CentroidMeasurement(
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            fraction,
            Quality.UNAVAILABLE,
            tuple(dict.fromkeys([*warnings, reason])),
            source_id,
        )

    if len(position) != 2 or not np.isfinite(position).all():
        return unavailable("INVALID_INITIAL_POSITION")
    px, py = position
    if not (0 <= px < image.shape[1] and 0 <= py < image.shape[0]):
        return unavailable("INITIAL_POSITION_OUTSIDE_IMAGE")
    ix, iy = int(np.floor(px + 0.5)), int(np.floor(py + 0.5))
    x0, x1 = max(0, ix - radius), min(image.shape[1], ix + radius + 1)
    y0, y1 = max(0, iy - radius), min(image.shape[0], iy + radius + 1)
    box = np.s_[y0:y1, x0:x1]
    good = valid[box]
    fraction = float(good.sum() / (2 * radius + 1) ** 2)
    if good.sum() <= 7 or fraction < 0.5:
        return unavailable("INSUFFICIENT_VALID_PIXELS", fraction)
    problems = list(region.warnings) if region else []
    if x1 - x0 < 2 * radius + 1 or y1 - y0 < 2 * radius + 1:
        problems.append("EDGE_TRUNCATED")
    if not good.all():
        problems.append("MASKED_FIT_REGION")
    if frame and frame.reason_masks.get("FLAG_WARNING", np.zeros(valid.shape, bool))[box].any():
        problems.append("FLAG_WARNING")
    if saturation_level is not None and np.any(image[box][good] >= saturation_level):
        problems.append("SATURATED")
    yy, xx = np.mgrid[y0:y1, x0:x1]
    x, y, data, sigma = xx[good], yy[good], image[box][good], np.sqrt(variance[box][good])
    background = float(np.median(data))
    amplitude = float(data.max() - background)
    if amplitude <= 0:
        return unavailable("NO_POSITIVE_SOURCE", fraction)

    def residual(params):
        amp, cx, cy, sx, sy, bg = params
        model = bg + amp * np.exp(-0.5 * (((x - cx) / sx) ** 2 + ((y - cy) / sy) ** 2))
        return (model - data) / sigma

    lower = [0, x0 - 0.5, y0 - 0.5, 0.4, 0.4, -np.inf]
    upper = [np.inf, x1 - 0.5, y1 - 0.5, radius, radius, np.inf]
    try:
        fit = least_squares(
            residual,
            [amplitude, px, py, 1.5, 1.5, background],
            bounds=(lower, upper),
            max_nfev=500,
            x_scale="jac",
        )
    except (ValueError, FloatingPointError):
        return unavailable("FIT_FAILED", fraction)
    if not fit.success or not np.isfinite(fit.x).all():
        return unavailable("FIT_FAILED", fraction)
    if np.linalg.matrix_rank(fit.jac) < 6 or np.any(fit.active_mask):
        return unavailable("DEGENERATE_OR_BOUNDARY_FIT", fraction)
    reduced_chi2 = float(np.sum(fit.fun**2) / (len(data) - 6))
    try:
        covariance = np.linalg.inv(fit.jac.T @ fit.jac) * max(1, reduced_chi2)
    except np.linalg.LinAlgError:
        return unavailable("UNCERTAINTY_UNAVAILABLE", fraction)
    if not np.isfinite(covariance).all() or np.any(np.diag(covariance) <= 0):
        return unavailable("UNCERTAINTY_UNAVAILABLE", fraction)
    amp, cx, cy, sx, sy, bg = fit.x
    snr = float(amp / np.sqrt(covariance[0, 0]))
    if snr < min_snr:
        problems.append("LOW_SNR")
    if reduced_chi2 > 3:
        problems.append("POOR_MODEL_FIT_OR_BLEND")
    if np.hypot(cx - px, cy - py) > radius / 2:
        problems.append("CENTROID_FAR_FROM_SEED")
    ra = dec = sky_uncertainty = None
    if wcs is not None:
        try:
            grid = celestial_grid(wcs, image.shape)
            sky = grid.pixel_to_world(cx, cy).icrs
            ra, dec = float(sky.ra.deg), float(sky.dec.deg)
            # Numerical sky Jacobian in local east/north coordinates handles RA wrap.
            jacobian = np.empty((2, 2))
            for axis, offset in enumerate(((1e-3, 0), (0, 1e-3))):
                shifted = grid.pixel_to_world(cx + offset[0], cy + offset[1]).icrs
                east, north = sky.spherical_offsets_to(shifted)
                jacobian[:, axis] = [east.arcsec / 1e-3, north.arcsec / 1e-3]
            sky_uncertainty = float(np.sqrt(np.trace(jacobian @ covariance[1:3, 1:3] @ jacobian.T)))
            if not np.isfinite([ra, dec, sky_uncertainty]).all():
                return unavailable("INVALID_WCS", fraction)
        except Exception:
            return unavailable("INVALID_WCS", fraction)
    else:
        problems.append("SKY_COORDINATES_UNAVAILABLE")
    warnings.extend(problems)
    return CentroidMeasurement(
        float(cx),
        float(cy),
        ra,
        dec,
        float(np.sqrt(covariance[1, 1])),
        float(np.sqrt(covariance[2, 2])),
        sky_uncertainty,
        snr,
        float(bg),
        fraction,
        Quality.AMBIGUOUS if problems else Quality.VALID,
        tuple(dict.fromkeys(warnings)),
        source_id,
    )


def calculate_source_centroid(
    cutout_data: np.ndarray,
    initial_position: tuple[float, float],
    *,
    variance: np.ndarray | None = None,
) -> tuple[float, float]:
    """Legacy tuple API now requires explicit variance; typed API is preferred."""
    result = measure_centroid(cutout_data, initial_position, variance)
    if result.x is None or result.y is None:
        raise ValueError("CENTROID_UNAVAILABLE: " + ",".join(result.warnings))
    return result.x, result.y
