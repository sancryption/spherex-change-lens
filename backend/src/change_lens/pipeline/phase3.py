"""SCI-local two-stage Phase 3 integration. Shared contracts/API remain untouched.

Association -> independent preliminary measurements -> artifact controls -> final
screened statuses. Controls never call measurement functions. SCI-012 general
finding synthesis, difference products and archive access remain out of scope.
"""

from dataclasses import dataclass
from typing import Literal

import numpy as np
from astropy.time import Time

from change_lens.pipeline.association import (
    AssociationPolicy,
    AssociationResult,
    EpochDetections,
    associate_sources_across_epochs,
)
from change_lens.pipeline.brightness import BrightnessPolicy, BrightnessResult, extract_photometry
from change_lens.pipeline.controls import (
    ControlAssessment,
    ControlPolicy,
    ProductDiagnostics,
    StaticControl,
    assess_controls,
)
from change_lens.pipeline.motion import MotionPolicy, MotionResult, estimate_source_motion
from change_lens.pipeline.phase2 import Phase2Result

ScreenedStatus = Literal[
    "POSSIBLE_POSITIONAL_MOVEMENT",
    "POSSIBLE_BRIGHTNESS_VARIATION",
    "NO_RELIABLE_CHANGE",
    "AMBIGUOUS",
    "ARTIFACT_RISK",
    "INSUFFICIENT_EVIDENCE",
]


@dataclass(frozen=True)
class ScreenedTrack:
    track_id: str
    preliminary_motion: MotionResult
    preliminary_brightness: BrightnessResult
    controls: ControlAssessment
    motion_status: ScreenedStatus
    brightness_status: ScreenedStatus


@dataclass(frozen=True)
class Phase3Result:
    association: AssociationResult
    tracks: tuple[ScreenedTrack, ...]
    warnings: tuple[str, ...]
    provenance: dict


def observation_time(metadata: dict) -> tuple[float | None, tuple[str, ...]]:
    """Read explicit MJD-OBS/DATE-OBS as UTC, reject conflicts >1 second.

    SCI-001 currently preserves these standard metadata fields but not TIMESYS;
    UTC is an explicit Phase 3 assumption, retained in provenance. A missing or
    invalid supplied timestamp is never replaced with input-list order.
    """
    times = []
    try:
        if "MJD-OBS" in metadata:
            value = float(metadata["MJD-OBS"])
            if not np.isfinite(value):
                raise ValueError("nonfinite")
            times.append(value)
        if "DATE-OBS" in metadata:
            times.append(float(Time(metadata["DATE-OBS"], format="isot", scale="utc").mjd))
    except (ValueError, TypeError, OverflowError):
        return None, ("INVALID_OBSERVATION_TIME",)
    if not times:
        return None, ("MISSING_OBSERVATION_TIME",)
    if len(times) == 2 and abs(times[0] - times[1]) * 86400 > 1:
        return None, ("CONFLICTING_OBSERVATION_TIMES",)
    return times[0], ()


def _screen(preliminary: str, controls: str, changed: str) -> ScreenedStatus:
    if controls == "ARTIFACT_SUSPECT":
        return "ARTIFACT_RISK"
    if preliminary == "UNAVAILABLE" or controls == "UNAVAILABLE":
        return "INSUFFICIENT_EVIDENCE"
    if preliminary == "AMBIGUOUS" or controls == "AMBIGUOUS":
        return "AMBIGUOUS"
    return "NO_RELIABLE_CHANGE" if preliminary == "STABLE" else changed


def run_phase3(
    phase2: Phase2Result,
    *,
    association_policy: AssociationPolicy | None = None,
    motion_policy: MotionPolicy | None = None,
    brightness_policy: BrightnessPolicy | None = None,
    control_policy: ControlPolicy | None = None,
    static_track_ids: tuple[str, ...] = (),
    diagnostics: dict[str, ProductDiagnostics] | None = None,
) -> Phase3Result:
    """Consume existing SCI-001..005 outputs without reprocessing or mutation.

    Static IDs are explicit caller designations, never inferred from a target's
    measured lack of change. Track IDs are deterministic for the same input set.
    Optional PSF/background diagnostics must come from validated actual products.
    """
    warnings = [*phase2.alignment.warnings, "UTC_TIME_SCALE_ASSUMED"]
    epochs, frames = [], {}
    provenance = {
        "method": "phase3-two-stage-v1",
        "time_assumption": "UTC",
        "static_track_ids": static_track_ids,
    }
    if phase2.alignment.status != "ALIGNED":
        return Phase3Result(
            associate_sources_across_epochs([], policy=association_policy),
            (),
            (*warnings, "ALIGNMENT_NOT_USABLE"),
            provenance,
        )
    if not len(phase2.alignment.frames) == len(phase2.centroids) == len(phase2.detections):
        raise ValueError("PHASE2_EPOCH_COUNTS_DIFFER")
    for frame, centroids in zip(phase2.alignment.frames, phase2.centroids, strict=True):
        validation = frame.provenance.get("validation", {})
        obs_id = validation.get("observation_id")
        if not obs_id or obs_id in frames:
            raise ValueError("UNIQUE_OBSERVATION_IDS_REQUIRED")
        time, issues = observation_time(validation.get("metadata", {}))
        warnings.extend(f"{obs_id}:{issue}" for issue in issues)
        frames[obs_id] = frame
        epochs.append(EpochDetections(obs_id, time, centroids, frame.provenance))
    association = associate_sources_across_epochs(epochs, policy=association_policy)
    preliminary = {
        track.track_id: (
            estimate_source_motion(track, policy=motion_policy),
            extract_photometry(track, frames, policy=brightness_policy),
        )
        for track in association.tracks
    }
    unknown = set(static_track_ids) - preliminary.keys()
    if unknown:
        warnings.append("STATIC_CONTROL_TRACKS_UNAVAILABLE:" + ",".join(sorted(unknown)))
    screened = []
    for track in association.tracks:
        motion, brightness = preliminary[track.track_id]
        controls = tuple(
            StaticControl(*preliminary[control_id])
            for control_id in sorted(set(static_track_ids))
            if control_id in preliminary and control_id != track.track_id
        )
        assessment = assess_controls(
            track,
            motion,
            brightness,
            frames,
            static_controls=controls,
            diagnostics=diagnostics,
            policy=control_policy,
        )
        screened.append(
            ScreenedTrack(
                track.track_id,
                motion,
                brightness,
                assessment,
                _screen(motion.status, assessment.motion_status, "POSSIBLE_POSITIONAL_MOVEMENT"),
                _screen(
                    brightness.status, assessment.brightness_status, "POSSIBLE_BRIGHTNESS_VARIATION"
                ),
            )
        )
    if association.ambiguous:
        warnings.append("AMBIGUOUS_ASSOCIATIONS_RETAINED")
    if not association.tracks:
        warnings.append("NO_MATCHED_TRACKS")
    return Phase3Result(association, tuple(screened), tuple(dict.fromkeys(warnings)), provenance)


@dataclass(frozen=True)
class PossibleMover:
    """Small BE-facing SCI screening view; track_id references Phase3Result.tracks.

    Values remain approximate apparent displacement, requiring scientific review.
    No orbit, physical proper motion or discovery inference is supplied.
    """

    track_id: str
    label: Literal["possible_mover"]
    displacement_arcsec: float
    baseline_days: float
    uncertainty_arcsec: float
    control_status: Literal["SUPPORTED"]
    reason_codes: tuple[str, ...]
    limitations: tuple[str, ...]


def possible_movers(result: Phase3Result) -> tuple[PossibleMover, ...]:
    """Extract qualifying final screened motion only, in deterministic track order.

    BE imports this function from change_lens.pipeline.phase3 and supplies the
    completed run_phase3 result. Empty output means no qualifying candidate;
    consult result.tracks[*].motion_status, .controls.checks, and
    result.association for stationary, ambiguous, artifact-risk, unavailable and
    unmatched evidence. This adapter never runs measurements or controls again.
    """
    candidates = []
    for track in sorted(result.tracks, key=lambda t: t.track_id):
        motion = track.preliminary_motion
        displacement = motion.displacement
        if (
            track.motion_status != "POSSIBLE_POSITIONAL_MOVEMENT"
            or track.controls.motion_status != "SUPPORTED"
            or motion.status != "POSSIBLE_MOVEMENT"
            or displacement is None
            or any(p.centroid.quality != "VALID" for p in motion.measured_positions)
            or len({p.mjd_utc for p in motion.measured_positions}) < 2
            or "AMBIGUOUS_ASSOCIATION" in motion.warnings
        ):
            continue
        values = (
            displacement.angular_arcsec,
            displacement.baseline_days,
            displacement.uncertainty_arcsec,
        )
        if not all(np.isfinite(v) and v > 0 for v in values):
            continue
        reasons = tuple(
            dict.fromkeys(
                [
                    "FINAL_SCREENED_POSITIONAL_MOVEMENT",
                    *(
                        reason
                        for check in track.controls.checks
                        if check.domain in ("MOTION", "BOTH")
                        for reason in check.reasons
                    ),
                ]
            )
        )
        limitations = tuple(
            dict.fromkeys(
                [
                    *motion.warnings,
                    *track.controls.provenance.get("limitations", ()),
                    "APPARENT_DISPLACEMENT_SCREENING_ONLY",
                    "PARALLAX_NOT_SEPARATELY_MODELED",
                ]
            )
        )
        candidates.append(
            PossibleMover(
                track.track_id, "possible_mover", *values, "SUPPORTED", reasons, limitations
            )
        )
    return tuple(candidates)
