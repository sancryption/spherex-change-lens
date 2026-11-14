"""SCI-012 final screened evidence synthesis; legacy scaffold API retained."""

from dataclasses import dataclass
from typing import Any, Literal

import numpy as np

from change_lens.pipeline.association import AssociationResult, SourceTrack
from change_lens.pipeline.difference import DifferenceResult
from change_lens.pipeline.phase3 import Phase3Result, ScreenedStatus, ScreenedTrack


@dataclass(frozen=True)
class DifferenceEvidence:
    """Frame-wide descriptive extrema, never attributed to a particular source.

    Nonzero residuals are not a detection. Zero residuals do not establish source
    stability. Original products preserve masks, units, lineage and uncertainty.
    """

    product: DifferenceResult
    availability: Literal["AVAILABLE", "UNAVAILABLE"]
    valid_pixel_count: int
    minimum: float | None
    maximum: float | None
    reason_codes: tuple[str, ...]


@dataclass(frozen=True)
class TrackEvidence:
    track_id: str
    association: SourceTrack
    screened: ScreenedTrack
    statuses: tuple[ScreenedStatus, ...]
    reason_codes: tuple[str, ...]
    limitations: tuple[str, ...]


@dataclass(frozen=True)
class EvidenceResult:
    """SCI-local audit view, not an API serialization contract.

    Tracks retain measurements, uncertainties, per-domain final labels, controls,
    source IDs, epoch times and provenance without rerunning any measurement.
    Unmatched/ambiguous/rejected associations remain visible in association.
    """

    tracks: tuple[TrackEvidence, ...]
    association: AssociationResult
    differences: tuple[DifferenceEvidence, ...]
    reason_codes: tuple[str, ...]
    limitations: tuple[str, ...]
    provenance: dict


def synthesize_evidence(
    phase3: Phase3Result, *, differences: tuple[DifferenceResult, ...] = ()
) -> EvidenceResult:
    """Summarize final Phase 3 evidence, with optional supporting differences.

    Motion and brightness are different observables: a static position with
    variable brightness (or movement at stable brightness) is not a conflict.
    Inconsistent final/preliminary/control labels are explicitly ambiguous;
    artifact controls always veto a supported summary in their domain.
    Differences never add votes, change a status, or claim independent evidence.
    """
    limitations = (
        "SCREENING_ONLY_REQUIRES_INVESTIGATION",
        "CORRELATED_EVIDENCE_NOT_COMBINED",
        "DIFFERENCE_EXTREMA_ARE_FRAME_WIDE_NOT_SOURCE_MEASUREMENTS",
        "NO_ORBIT_OR_DISCOVERY_INFERENCE",
    )
    reasons = list(phase3.warnings)
    association = {t.track_id: t for t in phase3.association.tracks}
    if len(association) != len(phase3.association.tracks) or len(
        {t.track_id for t in phase3.tracks}
    ) != len(phase3.tracks):
        raise ValueError("DUPLICATE_TRACK_ID")
    tracks = []
    for screened in sorted(phase3.tracks, key=lambda t: t.track_id):
        track = association.get(screened.track_id)
        if track is None or any(
            r.track_id != screened.track_id
            for r in (screened.preliminary_motion, screened.preliminary_brightness)
        ):
            raise ValueError("EVIDENCE_TRACK_ID_MISMATCH")
        track_reasons = [r for c in screened.controls.checks for r in c.reasons]
        track_reasons.extend(screened.preliminary_motion.warnings)
        track_reasons.extend(screened.preliminary_brightness.warnings)
        states = []
        for domain, final, preliminary, control, changed, accepted in (
            (
                "MOTION",
                screened.motion_status,
                screened.preliminary_motion.status,
                screened.controls.motion_status,
                "POSSIBLE_POSITIONAL_MOVEMENT",
                {"POSSIBLE_MOVEMENT"},
            ),
            (
                "BRIGHTNESS",
                screened.brightness_status,
                screened.preliminary_brightness.status,
                screened.controls.brightness_status,
                "POSSIBLE_BRIGHTNESS_VARIATION",
                {"BRIGHTER", "FAINTER"},
            ),
        ):
            track_reasons.append(f"FINAL_{domain}:{final}")
            track_reasons.append(f"CONTROL_{domain}:{control}")
            if control == "ARTIFACT_SUSPECT" or final == "ARTIFACT_RISK":
                state = "ARTIFACT_RISK"
            elif track.ambiguous:
                state = "AMBIGUOUS"
                track_reasons.append("AMBIGUOUS_ASSOCIATION")
            elif final in (changed, "NO_RELIABLE_CHANGE"):
                expected = preliminary in accepted if final == changed else preliminary == "STABLE"
                if control != "SUPPORTED" or not expected:
                    state = "AMBIGUOUS"
                    track_reasons.append(f"INCONSISTENT_{domain}_EVIDENCE")
                else:
                    state = final
            else:
                state = final
            states.append(state)
        tracks.append(
            TrackEvidence(
                track.track_id,
                track,
                screened,
                tuple(dict.fromkeys(states)),
                tuple(dict.fromkeys(track_reasons)),
                tuple(
                    dict.fromkeys(
                        (
                            *limitations,
                            *screened.preliminary_motion.warnings,
                            *screened.preliminary_brightness.warnings,
                            *(
                                w
                                for m in screened.preliminary_brightness.measurements
                                for w in m.warnings
                            ),
                            *screened.controls.provenance.get("limitations", ()),
                        )
                    )
                ),
            )
        )
    if set(association) - {t.track_id for t in tracks}:
        reasons.append("UNSCREENED_ASSOCIATION_TRACKS")
    if not tracks:
        reasons.append("INSUFFICIENT_EVIDENCE")
    if phase3.association.ambiguous:
        reasons.append("AMBIGUOUS_ASSOCIATIONS_RETAINED")
    if phase3.association.unmatched:
        reasons.append("UNMATCHED_DETECTIONS_RETAINED")
    # Include unmatched epochs for provenance verification, without fabricating tracks.
    points = [p for t in phase3.association.tracks for p in t.points]
    points += [d.point for d in phase3.association.unmatched]
    points += [p for e in phase3.association.ambiguous for p in (e.previous, e.current)]
    known_epochs = {(p.observation_id, p.mjd_utc) for p in points}
    summaries = []
    seen = set()
    for product in sorted(
        differences, key=lambda d: (d.earlier_observation_id or "", d.later_observation_id or "")
    ):
        key = (product.earlier_observation_id, product.later_observation_id)
        if key in seen:
            raise ValueError("DUPLICATE_DIFFERENCE_PAIR")
        seen.add(key)
        issues = list(product.reason_codes)
        related = all(
            pair in known_epochs
            for pair in (
                (product.earlier_observation_id, product.earlier_mjd_utc),
                (product.later_observation_id, product.later_mjd_utc),
            )
        )
        if not related:
            issues.append("DIFFERENCE_EPOCHS_NOT_IN_ASSOCIATION")
        for role, obs_id in (("earlier", key[0]), ("later", key[1])):
            source = product.provenance.get(role, {})
            for point in points:
                if point.observation_id != obs_id:
                    continue
                for field in ("plane_identity", "target_wcs", "shape_out", "validation"):
                    if field in point.provenance and point.provenance[field] != source.get(field):
                        related = False
                        issues.append("DIFFERENCE_PROVENANCE_MISMATCH")
        available = product.status == "AVAILABLE" and related
        values = np.array([], dtype=float)
        if available and product.image is not None and product.usable_mask is not None:
            values = product.image[product.usable_mask & np.isfinite(product.image)]
        available = available and bool(values.size)
        issues.append("DIFFERENCE_AVAILABLE" if available else "DIFFERENCE_UNAVAILABLE")
        if available:
            issues.append(
                "NONZERO_RESIDUAL_PIXELS" if np.any(values != 0) else "ZERO_RESIDUAL_PIXELS"
            )
        summaries.append(
            DifferenceEvidence(
                product,
                "AVAILABLE" if available else "UNAVAILABLE",
                int(values.size),
                float(values.min()) if available else None,
                float(values.max()) if available else None,
                tuple(dict.fromkeys(issues)),
            )
        )
    reasons.append(
        "DIFFERENCE_AVAILABLE"
        if any(d.availability == "AVAILABLE" for d in summaries)
        else "DIFFERENCE_UNAVAILABLE"
    )
    return EvidenceResult(
        tuple(tracks),
        phase3.association,
        tuple(summaries),
        tuple(dict.fromkeys(reasons)),
        tuple(
            dict.fromkeys(
                (*limitations, *phase3.warnings, *(w for d in differences for w in d.warnings))
            )
        ),
        {
            "method": "final-screened-evidence-v1",
            "phase3": phase3.provenance,
            "difference_scope": "frame-wide supporting evidence only; no independent votes",
            "evidence_labels": {
                "measured": "screened preliminary positions and brightness measurements",
                "derived": "displacement, brightness comparisons and difference products",
                "assumed": "input policies and warnings; independent-epoch difference variance",
                "unavailable": "INSUFFICIENT_EVIDENCE; DIFFERENCE_UNAVAILABLE; unmatched detections",
            },
        },
    )


def compile_scientific_evidence(investigation_data: dict[str, Any]) -> dict[str, Any]:
    """Legacy BE dictionary scaffold; use synthesize_evidence with Phase3Result.

    Dictionary/API translation belongs to the backend integration workstream.
    """
    raise NotImplementedError("Use SCI-local synthesize_evidence(phase3, differences=()).")
