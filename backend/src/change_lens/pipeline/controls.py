"""SCI-009 assesses existing measurements; never recomputes motion/brightness.

Controls provide screening evidence only. Explicit static-control tracks must
cover the same epochs and be distinct from the target. Validated optional product
diagnostics are caller supplied with provenance; extension presence alone is not
validation. No PSF correction or matching is performed.
"""

from dataclasses import asdict, dataclass
from typing import Literal

import numpy as np

from change_lens.pipeline.alignment import AlignedFrame
from change_lens.pipeline.association import SourceTrack, TrackPoint, finite, position_reasons
from change_lens.pipeline.brightness import BrightnessResult
from change_lens.pipeline.motion import MotionResult


@dataclass
class PipelineExecutionControls:
    """Existing scaffold configuration retained for compatibility."""

    max_cutout_size_pixels: int = 1024
    interpolation_order: str = "bilinear"
    mask_cosmic_rays: bool = True
    mask_saturation: bool = True
    difference_threshold_sigma: float = 3.0
    aperture_radius_pixels: float = 3.0


@dataclass(frozen=True)
class ControlPolicy:
    """Synthetic screening defaults; background limits use native image units.

    The variance ratio compares source pixels with the usable-frame median.
    It detects local excess; uniform high noise is handled by the preliminary
    uncertainty rules. Background spread is scatter, not a gradient fit.
    """

    edge_margin_pixels: float = 8.0
    high_variance_ratio: float = 10.0
    background_change_limit: float = 10.0
    background_spread_limit: float = 5.0
    psf_fractional_change_limit: float = 0.15
    background_gradient_limit: float = 1.0

    def __post_init__(self):
        if not all(np.isfinite(v) and v > 0 for v in asdict(self).values()):
            raise ValueError("INVALID_CONTROL_POLICY")


@dataclass(frozen=True)
class ProductDiagnostics:
    """Caller-validated summaries of actual products, not inferred PSF models.

    Provenance identifies the product and validation procedure. Gradient is in
    native image units/pixel; PSF FWHM is in aligned-grid pixels. A caller must
    validate units, projection and applicability before setting validated=True.
    """

    observation_id: str
    validated: bool = False
    psf_fwhm_pixels: float | None = None
    background_gradient_per_pixel: float | None = None
    provenance: str = ""


@dataclass(frozen=True)
class StaticControl:
    motion: MotionResult
    brightness: BrightnessResult


@dataclass(frozen=True)
class ControlCheck:
    name: str
    domain: Literal["MOTION", "BRIGHTNESS", "BOTH"]
    outcome: Literal["PASSED", "FAILED", "AMBIGUOUS", "UNAVAILABLE"]
    reasons: tuple[str, ...]
    provenance: dict


@dataclass(frozen=True)
class ControlAssessment:
    checks: tuple[ControlCheck, ...]
    motion_status: Literal["SUPPORTED", "AMBIGUOUS", "ARTIFACT_SUSPECT", "UNAVAILABLE"]
    brightness_status: Literal["SUPPORTED", "AMBIGUOUS", "ARTIFACT_SUSPECT", "UNAVAILABLE"]
    provenance: dict


def _aggregate(checks, domain):
    selected = [c for c in checks if c.domain in (domain, "BOTH")]
    if any(c.outcome == "FAILED" for c in selected):
        return "ARTIFACT_SUSPECT"
    if any(c.name.startswith("preliminary_") and c.outcome == "UNAVAILABLE" for c in selected):
        return "UNAVAILABLE"
    if not selected or all(c.outcome == "UNAVAILABLE" for c in selected):
        return "UNAVAILABLE"
    if any(c.outcome != "PASSED" for c in selected):
        return "AMBIGUOUS"
    return "SUPPORTED"


def _pixel_reasons(
    frame: AlignedFrame, point: TrackPoint, radius: float, policy: ControlPolicy
) -> tuple[str, ...]:
    """Quality-only inspection, shared by targets and static control regions."""
    x, y = point.centroid.x, point.centroid.y
    if not finite(x) or not finite(y):
        return ("MISSING_PIXEL_POSITION",)
    yy, xx = np.indices(frame.image.shape)
    region = (xx - x) ** 2 + (yy - y) ** 2 <= (radius + 1) ** 2
    reasons = []
    if min(x, y, frame.image.shape[1] - 1 - x, frame.image.shape[0] - 1 - y) < max(
        policy.edge_margin_pixels, radius + 1
    ):
        reasons.append("EDGE_PROXIMITY")
    if not region.any():
        reasons.append("NO_SOURCE_COVERAGE")
    elif (
        not frame.usable_mask[region].all()
        or not np.isfinite(frame.image[region]).all()
        or not np.isfinite(frame.footprint[region]).all()
        or np.any(frame.footprint[region] < 1 - 1e-10)
    ):
        reasons.append("MASK_OR_COVERAGE_ARTIFACT")
    for name, mask in frame.reason_masks.items():
        if mask.shape != frame.image.shape:
            raise ValueError("INVALID_REASON_MASK_SHAPE")
        if np.any(mask & region):
            reasons.append(f"QUALITY_MASK:{name}")
    local = frame.variance[region]
    global_good = frame.variance[
        np.isfinite(frame.variance) & (frame.variance > 0) & frame.usable_mask
    ]
    if not local.size or not np.isfinite(local).all() or np.any(local <= 0) or not global_good.size:
        reasons.append("INVALID_VARIANCE")
    elif np.max(local) > policy.high_variance_ratio * np.median(global_good):
        reasons.append("HIGH_VARIANCE")
    for warning in point.centroid.warnings:
        if any(term in warning for term in ("BLEND", "SATURAT", "POOR_MODEL", "MASK", "EDGE")):
            reasons.append(warning)
    return tuple(dict.fromkeys(reasons))


def assess_controls(
    track: SourceTrack,
    motion: MotionResult,
    brightness: BrightnessResult,
    frames: dict[str, AlignedFrame],
    *,
    static_controls: tuple[StaticControl, ...] = (),
    diagnostics: dict[str, ProductDiagnostics] | None = None,
    policy: ControlPolicy | None = None,
) -> ControlAssessment:
    policy = policy or ControlPolicy()
    diagnostics = diagnostics or {}
    if motion.track_id != track.track_id or brightness.track_id != track.track_id:
        raise ValueError("CONTROL_MEASUREMENT_TRACK_MISMATCH")
    checks = []

    def add(name, domain, outcome, reasons=(), **provenance):
        checks.append(ControlCheck(name, domain, outcome, tuple(reasons), provenance))

    identity_reasons = [r for p in track.points for r in position_reasons(p)]
    if track.ambiguous:
        identity_reasons.append("AMBIGUOUS_ASSOCIATION")
    add(
        "identity",
        "BOTH",
        "AMBIGUOUS" if identity_reasons else "PASSED",
        tuple(dict.fromkeys(identity_reasons)),
        matches=track.matches,
    )
    add(
        "preliminary_motion",
        "MOTION",
        "UNAVAILABLE"
        if motion.status == "UNAVAILABLE"
        else "AMBIGUOUS"
        if motion.status == "AMBIGUOUS"
        else "PASSED",
        motion.warnings,
        status=motion.status,
    )
    add(
        "preliminary_brightness",
        "BRIGHTNESS",
        "UNAVAILABLE"
        if brightness.status == "UNAVAILABLE"
        else "AMBIGUOUS"
        if brightness.status == "AMBIGUOUS"
        else "PASSED",
        brightness.warnings,
        status=brightness.status,
    )
    radius = brightness.provenance.get("policy", {}).get("aperture_radius", 3.0)
    for point in track.points:
        frame = frames.get(point.observation_id)
        if frame is None or not finite(point.centroid.x) or not finite(point.centroid.y):
            add(
                "pixel_quality",
                "BOTH",
                "UNAVAILABLE",
                ("MISSING_FRAME_OR_PIXEL_POSITION",),
                observation_id=point.observation_id,
            )
            continue
        reasons = _pixel_reasons(frame, point, radius, policy)
        add(
            "pixel_quality",
            "BOTH",
            "FAILED" if reasons else "PASSED",
            tuple(dict.fromkeys(reasons)),
            observation_id=point.observation_id,
            frame=frame.provenance,
        )

    target_epochs = {(p.observation_id, p.mjd_utc) for p in track.points}
    target_keys = {p.key for p in track.points}
    target_positions = {p.observation_id: p.centroid for p in track.points}
    for domain in ("MOTION", "BRIGHTNESS"):
        usable_controls = []
        rejected_controls = []
        for control in static_controls:
            positions = control.motion.measured_positions
            same_scope = {(p.observation_id, p.mjd_utc) for p in positions} == target_epochs
            independent = not target_keys.intersection(p.key for p in positions)
            control_radius = control.brightness.provenance.get("policy", {}).get(
                "aperture_radius", 3.0
            )
            for point in positions:
                target = target_positions.get(point.observation_id)
                if target is not None:
                    coords = (point.centroid.x, point.centroid.y, target.x, target.y)
                    if (
                        not all(finite(v) for v in coords)
                        or np.hypot(point.centroid.x - target.x, point.centroid.y - target.y)
                        <= radius + control_radius + 2
                    ):
                        independent = False
            consistent = control.motion.track_id == control.brightness.track_id and {
                (m.point.key, m.point.mjd_utc) for m in control.brightness.measurements
            } == {(p.key, p.mjd_utc) for p in positions}
            clean = all(
                p.observation_id in frames
                and not position_reasons(p)
                and not _pixel_reasons(frames[p.observation_id], p, control_radius, policy)
                for p in positions
            )
            if domain == "BRIGHTNESS":
                clean &= bool(control.brightness.measurements) and all(
                    finite(m.background_spread)
                    and m.background_spread <= policy.background_spread_limit
                    for m in control.brightness.measurements
                )
            state = control.motion.status if domain == "MOTION" else control.brightness.status
            if not same_scope or not independent or not consistent:
                rejected_controls.append(control.motion.track_id)
            else:
                usable_controls.append((control.motion.track_id, state if clean else "AMBIGUOUS"))
        if not usable_controls:
            add(
                "static_controls",
                domain,
                "UNAVAILABLE",
                ("NO_INDEPENDENT_SAME_EPOCH_STATIC_CONTROL",),
                rejected=rejected_controls,
            )
        elif any(s in ("POSSIBLE_MOVEMENT", "BRIGHTER", "FAINTER") for _, s in usable_controls):
            add(
                "static_controls",
                domain,
                "FAILED",
                ("STATIC_CONTROL_CHANGED",),
                controls=usable_controls,
                rejected=rejected_controls,
            )
        elif any(s != "STABLE" for _, s in usable_controls) or rejected_controls:
            add(
                "static_controls",
                domain,
                "AMBIGUOUS",
                ("STATIC_CONTROL_UNRELIABLE",),
                controls=usable_controls,
                rejected=rejected_controls,
            )
        else:
            add("static_controls", domain, "PASSED", controls=usable_controls)

    backgrounds = brightness.measurements
    if not backgrounds or any(
        not finite(m.background) or not finite(m.background_spread) for m in backgrounds
    ):
        add("local_background", "BRIGHTNESS", "UNAVAILABLE", ("BACKGROUND_UNAVAILABLE",))
    else:
        bg_range = max(m.background for m in backgrounds) - min(m.background for m in backgrounds)
        spread = max(m.background_spread for m in backgrounds)
        if spread > policy.background_spread_limit:
            add(
                "local_background",
                "BRIGHTNESS",
                "FAILED",
                ("STRUCTURED_OR_CONTAMINATED_BACKGROUND",),
                spread=spread,
                background_range=bg_range,
            )
        elif bg_range > policy.background_change_limit:
            add(
                "local_background",
                "BRIGHTNESS",
                "AMBIGUOUS",
                ("LARGE_BACKGROUND_CHANGE",),
                spread=spread,
                background_range=bg_range,
            )
        else:
            add(
                "local_background", "BRIGHTNESS", "PASSED", spread=spread, background_range=bg_range
            )
    valid_diagnostics = []
    for point in track.points:
        diagnostic = diagnostics.get(point.observation_id)
        if (
            diagnostic is None
            or not diagnostic.validated
            or not diagnostic.provenance
            or diagnostic.observation_id != point.observation_id
        ):
            continue
        valid_diagnostics.append(diagnostic)
    psfs = [
        d.psf_fwhm_pixels
        for d in valid_diagnostics
        if finite(d.psf_fwhm_pixels) and d.psf_fwhm_pixels > 0
    ]
    if len(psfs) != len(track.points) or not psfs:
        add(
            "psf",
            "BOTH",
            "UNAVAILABLE",
            ("VALIDATED_PSF_INFORMATION_UNAVAILABLE",),
            diagnostics=tuple(valid_diagnostics),
        )
    elif max(psfs) / min(psfs) - 1 > policy.psf_fractional_change_limit:
        add(
            "psf",
            "BOTH",
            "FAILED",
            ("PSF_MISMATCH", "NO_PSF_MATCHING_PERFORMED"),
            diagnostics=tuple(valid_diagnostics),
        )
    else:
        add(
            "psf",
            "BOTH",
            "PASSED",
            ("PSF_WIDTH_CHECK_ONLY", "NO_PSF_MATCHING_PERFORMED"),
            diagnostics=tuple(valid_diagnostics),
        )
    for diagnostic in valid_diagnostics:
        gradient = diagnostic.background_gradient_per_pixel
        if gradient is not None:
            outcome = (
                "UNAVAILABLE"
                if not finite(gradient) or gradient < 0
                else "FAILED"
                if gradient > policy.background_gradient_limit
                else "PASSED"
            )
            add(
                "product_background",
                "BRIGHTNESS",
                outcome,
                ("BACKGROUND_GRADIENT",) if outcome == "FAILED" else (),
                diagnostic=diagnostic,
            )
    return ControlAssessment(
        tuple(checks),
        _aggregate(checks, "MOTION"),
        _aggregate(checks, "BRIGHTNESS"),
        {
            "method": "reason-coded-artifact-screening-v1",
            "policy": asdict(policy),
            "static_measurements": static_controls,
            "limitations": (
                "SCREENING_ONLY",
                "PSF_WIDTH_DOES_NOT_VALIDATE_FULL_MODEL",
                "NO_COVARIANCE_OR_CALIBRATION_VALIDATION",
            ),
        },
    )
