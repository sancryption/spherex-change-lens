"""SCI-008 fixed-radius aperture mean in native surface-brightness units.

Subpixel area weights follow measured centroids on the common aligned grid.
The result is a background-subtracted region mean, NOT integrated source flux.
No aperture correction, PSF matching, covariance or calibration error is invented.
All source pixels must be usable; masked apertures are never renormalized.
"""

from dataclasses import asdict, dataclass
from itertools import combinations
from typing import Literal

import numpy as np
from astropy import units as u

from change_lens.pipeline.alignment import AlignedFrame
from change_lens.pipeline.association import SourceTrack, TrackPoint, finite, position_valid
from change_lens.pipeline.detection import Quality, valid_pixels


@dataclass(frozen=True)
class BrightnessPolicy:
    """Radii in aligned pixels; absolute floor in native surface-brightness units.

    Defaults are locked synthetic screening choices, not SPHEREx calibration.
    Fractional floor uses the larger absolute epoch value, including negatives.
    """

    aperture_radius: float = 3.0
    annulus_inner: float = 5.0
    annulus_outer: float = 8.0
    min_background_fraction: float = 0.8
    absolute_change_floor: float = 0.5
    fractional_change_floor: float = 0.05
    uncertainty_multiplier: float = 3.0
    subpixels: int = 4

    def __post_init__(self):
        if not all(np.isfinite(v) and v > 0 for v in asdict(self).values()):
            raise ValueError("INVALID_BRIGHTNESS_POLICY")
        if (
            not self.aperture_radius < self.annulus_inner < self.annulus_outer
            or self.min_background_fraction > 1
        ):
            raise ValueError("INVALID_APERTURE_OR_ANNULUS")
        if (
            isinstance(self.subpixels, bool)
            or not isinstance(self.subpixels, int)
            or self.subpixels > 32
        ):
            raise ValueError("INVALID_SUBPIXELS")


@dataclass(frozen=True)
class BrightnessMeasurement:
    point: TrackPoint
    value: float | None
    uncertainty: float | None
    background: float | None
    background_uncertainty: float | None
    background_spread: float | None
    valid_fraction: float
    background_valid_fraction: float
    unit: str | None
    quality: Quality
    warnings: tuple[str, ...]
    provenance: dict
    method: str = "subpixel-aperture-mean-annulus-mean-v1"


@dataclass(frozen=True)
class BrightnessComparison:
    first_observation_id: str
    last_observation_id: str
    difference: float
    uncertainty: float
    threshold: float
    status: Literal["BRIGHTER", "FAINTER", "STABLE", "AMBIGUOUS"]


@dataclass(frozen=True)
class BrightnessResult:
    track_id: str
    measurements: tuple[BrightnessMeasurement, ...]
    comparisons: tuple[BrightnessComparison, ...]
    status: Literal["BRIGHTER", "FAINTER", "STABLE", "AMBIGUOUS", "UNAVAILABLE"]
    warnings: tuple[str, ...]
    provenance: dict


def aperture_weights(shape: tuple[int, int], x: float, y: float, policy: BrightnessPolicy):
    """Return in-image source/annulus weights and full geometric areas.

    Construct outside-image support explicitly to detect truncation, including
    subpixel edge coverage. A bounded local box avoids full-frame subpixel arrays.
    """
    r = int(np.ceil(policy.annulus_outer + 1))
    cx, cy = int(np.floor(x)), int(np.floor(y))
    yy, xx = np.mgrid[cy - r : cy + r + 1, cx - r : cx + r + 1]
    source, background = np.zeros(xx.shape), np.zeros(xx.shape)
    for dy in (np.arange(policy.subpixels) + 0.5) / policy.subpixels - 0.5:
        for dx in (np.arange(policy.subpixels) + 0.5) / policy.subpixels - 0.5:
            d2 = (xx + dx - x) ** 2 + (yy + dy - y) ** 2
            source += d2 <= policy.aperture_radius**2
            background += (d2 >= policy.annulus_inner**2) & (d2 <= policy.annulus_outer**2)
    source /= policy.subpixels**2
    background /= policy.subpixels**2
    inside = (xx >= 0) & (yy >= 0) & (xx < shape[1]) & (yy < shape[0])
    a, b = np.zeros(shape), np.zeros(shape)
    a[yy[inside], xx[inside]] = source[inside]
    b[yy[inside], xx[inside]] = background[inside]
    return a, b, float(source.sum()), float(background.sum())


def measure_aperture(
    frame: AlignedFrame, point: TrackPoint, *, policy: BrightnessPolicy | None = None
) -> BrightnessMeasurement:
    policy = policy or BrightnessPolicy()
    unit = frame.provenance.get("validation", {}).get("image_unit")
    warnings = [
        *frame.warnings,
        *point.centroid.warnings,
        "REGION_MEAN_NOT_INTEGRATED_FLUX",
        "PIXEL_AND_EPOCH_COVARIANCE_OMITTED",
        "CALIBRATION_UNCERTAINTY_OMITTED",
        "APERTURE_AND_PSF_CORRECTIONS_OMITTED",
    ]
    provenance = {
        "frame": frame.provenance,
        "policy": asdict(policy),
        "variance_method": "sum_squared_normalized_source_weights_plus_background_mean_variance",
        "background_method": "area-weighted-annulus-mean-with-empirical-scatter-floor",
    }

    def unavailable(reason, fraction=0.0, bg_fraction=0.0):
        return BrightnessMeasurement(
            point,
            None,
            None,
            None,
            None,
            None,
            fraction,
            bg_fraction,
            unit,
            Quality.UNAVAILABLE,
            tuple(dict.fromkeys([*warnings, reason])),
            provenance,
        )

    c = point.centroid
    if frame.provenance.get("validation", {}).get("observation_id") != point.observation_id:
        return unavailable("FRAME_OBSERVATION_ID_MISMATCH")
    if not position_valid(point) or not finite(c.x) or not finite(c.y):
        return unavailable("INVALID_APERTURE_POSITION_OR_TIME")
    if not (0 <= c.x < frame.image.shape[1] and 0 <= c.y < frame.image.shape[0]):
        return unavailable("APERTURE_OUTSIDE_IMAGE")
    try:
        if unit is None or not u.Unit(unit).is_equivalent(u.MJy / u.sr):
            return unavailable("SURFACE_BRIGHTNESS_UNITS_REQUIRED")
    except ValueError:
        return unavailable("INVALID_UNITS")
    valid = valid_pixels(frame.image, frame.variance, frame.usable_mask, frame.footprint)
    a, b, area, bg_area = aperture_weights(frame.image.shape, c.x, c.y, policy)
    fraction = float(a[valid].sum() / area)
    bg_fraction = float(b[valid].sum() / bg_area)
    if fraction < 1 - 1e-10:
        return unavailable("INCOMPLETE_OR_INVALID_APERTURE", fraction, bg_fraction)
    if bg_fraction < policy.min_background_fraction or np.count_nonzero((b > 0) & valid) < 8:
        return unavailable("INSUFFICIENT_LOCAL_BACKGROUND", fraction, bg_fraction)
    selected, annulus = (a > 0) & valid, (b > 0) & valid
    weights = a[selected] / area
    bg_weights = b[annulus] / b[annulus].sum()
    bg_values = frame.image[annulus]
    background = float(np.sum(bg_weights * bg_values))
    spread2 = float(
        np.sum(bg_weights * (bg_values - background) ** 2) / (1 - np.sum(bg_weights**2))
    )
    bg_variance = float(
        max(np.sum(bg_weights**2 * frame.variance[annulus]), spread2 * np.sum(bg_weights**2))
    )
    value = float(np.sum(weights * (frame.image[selected] - background)))
    variance = float(np.sum(weights**2 * frame.variance[selected]) + bg_variance)
    if not np.isfinite([background, spread2, value, variance]).all() or variance <= 0:
        return unavailable("NONFINITE_APERTURE_MEASUREMENT", fraction, bg_fraction)
    problems = []
    if c.quality != Quality.VALID:
        problems.append("CENTROID_QUALITY")
    if bg_fraction < 1 - 1e-10:
        problems.append("PARTIAL_BACKGROUND_REGION")
    for name, mask in frame.reason_masks.items():
        if mask.shape != frame.image.shape:
            raise ValueError("INVALID_REASON_MASK_SHAPE")
        if np.any(mask & ((a > 0) | (b > 0))):
            problems.append(f"REGION_QUALITY:{name}")
    return BrightnessMeasurement(
        point,
        value,
        float(np.sqrt(variance)),
        background,
        float(np.sqrt(bg_variance)),
        float(np.sqrt(spread2)),
        fraction,
        bg_fraction,
        unit,
        Quality.AMBIGUOUS if problems else Quality.VALID,
        tuple(dict.fromkeys([*warnings, *problems])),
        provenance,
    )


def compatibility_reasons(frames: list[AlignedFrame]) -> tuple[str, ...]:
    """Require caller-certified product/plane, identical grid and exact unit scale.

    Missing calibration/release identity blocks a clean comparison; differing
    calibrations are not assumed interchangeable. No implicit unit conversion.
    """
    if not frames:
        return ("NO_FRAMES",)
    reasons = []
    signatures = []
    for frame in frames:
        p = frame.provenance
        identity = p.get("plane_identity", {})
        metadata = p.get("validation", {}).get("metadata", {})
        unit = p.get("validation", {}).get("image_unit")
        if not all(identity.get(k) for k in ("band", "product", "spectral_plane", "release")):
            reasons.append("MISSING_PLANE_IDENTITY")
        for header, key in (("BAND", "band"), ("PRODTYPE", "product"), ("RELEASE", "release")):
            if header in metadata and metadata[header] != identity.get(key):
                reasons.append("PLANE_IDENTITY_CONFLICTS_WITH_HEADER")
        calibration = metadata.get("CALVER")
        if not calibration:
            reasons.append("CALIBRATION_UNKNOWN")
        try:
            unit = u.Unit(unit) if unit else None
        except ValueError:
            unit = None
        if unit is None:
            reasons.append("INVALID_UNITS")
        signatures.append(
            (
                identity.get("band"),
                identity.get("product"),
                identity.get("spectral_plane"),
                identity.get("release"),
                calibration,
                unit,
            )
        )
        if frame.image.shape != frames[0].image.shape or frame.wcs.to_header(relax=True) != frames[
            0
        ].wcs.to_header(relax=True):
            reasons.append("INCOMPATIBLE_ALIGNED_GRID")
    if any(s != signatures[0] for s in signatures[1:]):
        reasons.append("INCOMPATIBLE_PRODUCT_BAND_PLANE_RELEASE_CALIBRATION_OR_UNIT")
    return tuple(dict.fromkeys(reasons))


def extract_photometry(
    track: SourceTrack, frames: dict[str, AlignedFrame], *, policy: BrightnessPolicy | None = None
) -> BrightnessResult:
    """Independent preliminary measurements, with all chronological pairs retained.

    A changed pair must exceed absolute/fractional floors and the configured
    uncertainty multiple. Stability requires the uncertainty interval to fit
    inside the floor. High-noise non-detections are therefore ambiguous.
    Mixed directions across >2 epochs remain ambiguous, with pairwise history.
    """
    policy = policy or BrightnessPolicy()
    provenance = {"method": "aperture-mean-pairwise-screening-v1", "policy": asdict(policy)}
    points = sorted(
        track.points, key=lambda p: (p.mjd_utc if finite(p.mjd_utc) else float("inf"), p.key)
    )
    measurements = tuple(
        measure_aperture(frames[p.observation_id], p, policy=policy)
        for p in points
        if p.observation_id in frames
    )
    warnings = list(
        compatibility_reasons(
            [frames[p.observation_id] for p in points if p.observation_id in frames]
        )
    )
    if len(measurements) != len(points):
        warnings.append("MISSING_EPOCH_FRAME")
    fatal = [w for w in warnings if w != "CALIBRATION_UNKNOWN"]
    if (
        fatal
        or len(measurements) < 2
        or any(m.quality == Quality.UNAVAILABLE for m in measurements)
    ):
        return BrightnessResult(
            track.track_id,
            measurements,
            (),
            "UNAVAILABLE",
            (*warnings, "TWO_USABLE_COMPATIBLE_EPOCHS_REQUIRED"),
            provenance,
        )
    comparisons = []
    for a, b in combinations(measurements, 2):
        if a.point.mjd_utc == b.point.mjd_utc:
            warnings.append("DUPLICATE_EPOCH_TIME")
            continue
        difference = b.value - a.value
        uncertainty = float(np.hypot(a.uncertainty, b.uncertainty))
        floor = max(
            policy.absolute_change_floor,
            policy.fractional_change_floor * max(abs(a.value), abs(b.value)),
        )
        threshold = max(floor, policy.uncertainty_multiplier * uncertainty)
        if abs(difference) > threshold:
            status = "BRIGHTER" if difference > 0 else "FAINTER"
        elif abs(difference) + policy.uncertainty_multiplier * uncertainty <= floor:
            status = "STABLE"
        else:
            status = "AMBIGUOUS"
        comparisons.append(
            BrightnessComparison(
                a.point.observation_id,
                b.point.observation_id,
                difference,
                uncertainty,
                threshold,
                status,
            )
        )
    states = {c.status for c in comparisons}
    if not comparisons:
        status = "UNAVAILABLE"
    elif warnings or track.ambiguous or any(m.quality != Quality.VALID for m in measurements):
        status = "AMBIGUOUS"
    elif states == {"STABLE"}:
        status = "STABLE"
    elif states <= {"STABLE", "BRIGHTER"}:
        status = "BRIGHTER"
    elif states <= {"STABLE", "FAINTER"}:
        status = "FAINTER"
    else:
        status = "AMBIGUOUS"
    if track.ambiguous:
        warnings.append("AMBIGUOUS_ASSOCIATION")
    return BrightnessResult(
        track.track_id,
        measurements,
        tuple(comparisons),
        status,
        tuple(
            dict.fromkeys(
                [
                    *warnings,
                    "PRELIMINARY_SCREENING_ONLY",
                    "PIXEL_AND_EPOCH_COVARIANCE_OMITTED",
                    "CALIBRATION_UNCERTAINTY_OMITTED",
                ]
            )
        ),
        provenance,
    )


@dataclass(frozen=True)
class BrightnessGroup:
    """Exact caller-certified band/plane and calibration identity; no channel guessing."""

    band: str
    product: str
    spectral_plane: str
    release: str
    calibration: str
    unit: str
    result: BrightnessResult


@dataclass(frozen=True)
class GroupedBrightnessResult:
    track_id: str
    groups: tuple[BrightnessGroup, ...]
    unavailable: tuple[BrightnessResult, ...]


def extract_grouped_photometry(
    track: SourceTrack, frames: dict[str, AlignedFrame], *, policy: BrightnessPolicy | None = None
) -> GroupedBrightnessResult:
    """Compare epochs only within exact certified band/plane/calibration groups.

    Input frames must already be aligned by SCI-003. Phase 2 rejects mixed-band
    series, so callers with multiple bands prepare compatible series separately
    and provide their aligned frames here. Grid compatibility is still checked
    within each group. One common measurement policy applies to every group;
    no premeasured values with differing apertures are combined. Unknown identity
    or calibration is retained as unavailable, never assigned to a guessed band.
    A single-epoch group is unavailable. No overall cross-band change is inferred.
    """
    policy = policy or BrightnessPolicy()
    grouped = {}
    unavailable = []
    for point in sorted(track.points, key=lambda p: p.key):
        frame = frames.get(point.observation_id)
        identity = frame.provenance.get("plane_identity", {}) if frame else {}
        validation = frame.provenance.get("validation", {}) if frame else {}
        values = tuple(identity.get(k) for k in ("band", "product", "spectral_plane", "release"))
        calibration = validation.get("metadata", {}).get("CALVER")
        unit = validation.get("image_unit")
        issues = compatibility_reasons([frame]) if frame else ("MISSING_EPOCH_FRAME",)
        if issues or not all(
            isinstance(v, str) and v.strip() for v in (*values, calibration, unit)
        ):
            subset = SourceTrack(track.track_id, (point,), ambiguous=track.ambiguous)
            result = extract_photometry(subset, frames, policy=policy)
            unavailable.append(result)
            continue
        key = (*values, calibration, str(u.Unit(unit)))
        grouped.setdefault(key, []).append(point)
    groups = []
    for key, points in sorted(grouped.items()):
        subset = SourceTrack(track.track_id, tuple(points), ambiguous=track.ambiguous)
        result = extract_photometry(subset, frames, policy=policy)
        groups.append(BrightnessGroup(*key, result))
    return GroupedBrightnessResult(track.track_id, tuple(groups), tuple(unavailable))
