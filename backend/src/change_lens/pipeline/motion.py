"""SCI-007 preliminary apparent displacement; no orbit or proper-motion claim.

Scalar radial centroid errors are combined in quadrature as uncertainty proxies.
WCS systematics, resampling covariance and epoch correlation remain omitted.
Thresholds are screening policy, not calibrated statistical significance.
"""

from dataclasses import asdict, dataclass
from itertools import combinations
from typing import Literal

import numpy as np
from astropy import units as u

from change_lens.pipeline.association import SourceTrack, TrackPoint, position_reasons, sky


@dataclass(frozen=True)
class MotionPolicy:
    """Synthetic screening floor and error multiplier, with no confidence claim."""

    displacement_floor_arcsec: float = 0.3
    uncertainty_multiplier: float = 3.0

    def __post_init__(self):
        if not all(np.isfinite(v) and v > 0 for v in asdict(self).values()):
            raise ValueError("INVALID_MOTION_POLICY")


@dataclass(frozen=True)
class Displacement:
    first_observation_id: str
    last_observation_id: str
    angular_arcsec: float
    position_angle_deg: float | None
    baseline_days: float
    uncertainty_arcsec: float
    threshold_arcsec: float


@dataclass(frozen=True)
class MotionResult:
    track_id: str
    measured_positions: tuple[TrackPoint, ...]
    displacement: Displacement | None
    pairwise: tuple[Displacement, ...]
    max_residual_arcsec: float | None
    status: Literal["POSSIBLE_MOVEMENT", "STABLE", "AMBIGUOUS", "UNAVAILABLE"]
    warnings: tuple[str, ...]
    provenance: dict


def estimate_source_motion(
    track: SourceTrack, *, policy: MotionPolicy | None = None
) -> MotionResult:
    """Measure all valid pairs and endpoint-geodesic consistency, without screening.

    With >=3 epochs, residuals test constant-speed travel on the endpoint great
    circle, not an astrometric fit. UTC MJD differences are civil-day baselines
    (leap-second timing precision omitted). All input positions are retained.
    Position angle is east of north and unavailable at zero displacement.
    """
    policy = policy or MotionPolicy()
    warnings = [
        "PRELIMINARY_MEASUREMENT",
        "DIAGONAL_POSITION_UNCERTAINTY_PROXY",
        "WCS_AND_RESAMPLING_SYSTEMATICS_NOT_MODELED",
        "UTC_DAY_BASELINE",
    ]
    points = sorted(
        (p for p in track.points if not position_reasons(p)), key=lambda p: (p.mjd_utc, p.key)
    )
    provenance = {
        "method": "spherical-pairwise-displacement-v1",
        "policy": asdict(policy),
        "association": track.matches,
    }
    if len(points) != len(track.points):
        warnings.append("EXCLUDED_INVALID_OR_UNCERTAIN_EPOCHS")
    pairs = []
    for a, b in combinations(points, 2):
        if a.mjd_utc == b.mjd_utc:
            warnings.append("DUPLICATE_EPOCH_TIME")
            continue
        distance = float(sky(a).separation(sky(b)).arcsec)
        error = float(np.hypot(a.centroid.uncertainty_arcsec, b.centroid.uncertainty_arcsec))
        pairs.append(
            Displacement(
                a.observation_id,
                b.observation_id,
                distance,
                float(sky(a).position_angle(sky(b)).deg) if distance > 1e-9 else None,
                b.mjd_utc - a.mjd_utc,
                error,
                max(policy.displacement_floor_arcsec, policy.uncertainty_multiplier * error),
            )
        )
    if not pairs:
        return MotionResult(
            track.track_id,
            track.points,
            None,
            (),
            None,
            "UNAVAILABLE",
            (*warnings, "TWO_VALID_DISTINCT_EPOCHS_REQUIRED"),
            provenance,
        )
    endpoint = next(
        p
        for p in pairs
        if p.first_observation_id == points[0].observation_id
        and p.last_observation_id == points[-1].observation_id
    )
    residual = None
    if len(points) >= 3:
        origin = sky(points[0])
        angle = origin.position_angle(sky(points[-1]))
        residual = float(
            max(
                origin.directional_offset_by(
                    angle,
                    endpoint.angular_arcsec
                    * (p.mjd_utc - points[0].mjd_utc)
                    / endpoint.baseline_days
                    * u.arcsec,
                )
                .separation(sky(p))
                .arcsec
                for p in points
            )
        )
    if track.ambiguous or len(points) != len(track.points) or "DUPLICATE_EPOCH_TIME" in warnings:
        status = "AMBIGUOUS"
    elif residual is not None and residual > max(p.threshold_arcsec for p in pairs):
        status = "AMBIGUOUS"
        warnings.append("INCONSISTENT_DISPLACEMENT_TREND")
    elif any(p.angular_arcsec > p.threshold_arcsec for p in pairs):
        status = "POSSIBLE_MOVEMENT"
    elif all(
        p.angular_arcsec + policy.uncertainty_multiplier * p.uncertainty_arcsec
        <= policy.displacement_floor_arcsec
        for p in pairs
    ):
        status = "STABLE"
    else:
        status = "AMBIGUOUS"
        warnings.append("NOISE_LIMITED_DISPLACEMENT")
    if track.ambiguous:
        warnings.append("AMBIGUOUS_ASSOCIATION")
    return MotionResult(
        track.track_id,
        track.points,
        endpoint,
        tuple(pairs),
        residual,
        status,
        tuple(dict.fromkeys(warnings)),
        provenance,
    )
