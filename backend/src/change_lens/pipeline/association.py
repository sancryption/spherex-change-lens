"""SCI-006 conservative spherical association without nearest-neighbour forcing.

Explicit UTC MJD epochs; equal-time observations form one candidate group and
cannot match one another. Contested endpoints are retired permanently. Missing
detections may be bridged; elapsed-time allowance is a search policy, not a
physical motion model. No official flag meanings are inferred.
"""

from dataclasses import asdict, dataclass, field

import numpy as np
from astropy import units as u
from astropy.coordinates import SkyCoord

from change_lens.pipeline.centroid import CentroidMeasurement
from change_lens.pipeline.detection import Quality


@dataclass(frozen=True)
class EpochDetections:
    observation_id: str
    mjd_utc: float | None
    centroids: tuple[CentroidMeasurement, ...]
    provenance: dict = field(default_factory=dict)


@dataclass(frozen=True)
class TrackPoint:
    observation_id: str
    mjd_utc: float | None
    centroid: CentroidMeasurement
    provenance: dict = field(default_factory=dict)

    @property
    def key(self) -> tuple[str, str]:
        return self.observation_id, self.centroid.source_id or ""


@dataclass(frozen=True)
class AssociationPolicy:
    """Search bounds in arcseconds; defaults are synthetic screening choices.

    Set allowance_arcsec_per_day=0.03 for an illustrative moving-source search.
    Zero preserves the original default. This is not a universal source speed
    limit: proper motion alone may not describe parallax-driven displacement.
    The allowance expands candidates only; quality and uniqueness still apply.
    """

    radius_arcsec: float = 2.0
    uncertainty_multiplier: float = 3.0
    max_radius_arcsec: float = 10.0
    allowance_arcsec_per_day: float = 0.0
    min_valid_fraction: float = 0.9

    def __post_init__(self):
        if not all(np.isfinite(v) and v >= 0 for v in asdict(self).values()):
            raise ValueError("INVALID_ASSOCIATION_POLICY")
        if (
            not 0 < self.radius_arcsec <= self.max_radius_arcsec
            or not 0 < self.min_valid_fraction <= 1
        ):
            raise ValueError("INVALID_ASSOCIATION_POLICY")


@dataclass(frozen=True)
class AssociationEdge:
    previous: TrackPoint
    current: TrackPoint
    separation_arcsec: float
    tolerance_arcsec: float
    reasons: tuple[str, ...] = ()
    method: str = "spherical-unique-candidate-v1"


@dataclass(frozen=True)
class SourceTrack:
    track_id: str
    points: tuple[TrackPoint, ...]
    matches: tuple[AssociationEdge, ...] = ()
    ambiguous: bool = False


@dataclass(frozen=True)
class UnmatchedDetection:
    point: TrackPoint
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class AssociationResult:
    tracks: tuple[SourceTrack, ...]
    unmatched: tuple[UnmatchedDetection, ...]
    ambiguous: tuple[AssociationEdge, ...]
    rejected: tuple[AssociationEdge, ...]
    provenance: dict


def finite(value: float | None) -> bool:
    return value is not None and bool(np.isfinite(value))


def position_valid(point: TrackPoint) -> bool:
    c = point.centroid
    return (
        finite(point.mjd_utc)
        and finite(c.ra_deg)
        and finite(c.dec_deg)
        and 0 <= c.ra_deg < 360
        and -90 <= c.dec_deg <= 90
        and c.coordinate_frame == "ICRS"
        and c.quality != Quality.UNAVAILABLE
    )


def sky(point: TrackPoint) -> SkyCoord:
    return SkyCoord(point.centroid.ra_deg * u.deg, point.centroid.dec_deg * u.deg, frame="icrs")


def position_reasons(point: TrackPoint, min_fraction: float = 0.9) -> tuple[str, ...]:
    c = point.centroid
    reasons = []
    if not position_valid(point):
        reasons.append("INVALID_POSITION_OR_TIME")
    if c.quality != Quality.VALID:
        reasons.append("CENTROID_QUALITY")
    if not finite(c.valid_fraction) or c.valid_fraction < min_fraction:
        reasons.append("LOW_VALID_FRACTION")
    if not finite(c.uncertainty_arcsec) or c.uncertainty_arcsec <= 0:
        reasons.append("POSITION_UNCERTAINTY_UNAVAILABLE")
    for warning in c.warnings:
        if any(
            term in warning
            for term in ("BLEND", "MASK", "EDGE", "SATURAT", "LOW_SNR", "FLAG_WARNING")
        ):
            reasons.append(warning)
    return tuple(dict.fromkeys(reasons))


def associate_sources_across_epochs(
    source_lists: list[EpochDetections], *, policy: AssociationPolicy | None = None
) -> AssociationResult:
    """Accept only isolated, quality-usable edges in the whole bipartite graph.

    Tolerance = base + multiplier*hypot(errors) + elapsed-time allowance, capped
    at max_radius. Missing/excessive uncertainty produces ambiguity. All tested
    rejected edges retain reasons. Explicit unique IDs ensure stable ordering.
    """
    policy = policy or AssociationPolicy()
    if len({e.observation_id for e in source_lists}) != len(source_lists):
        raise ValueError("DUPLICATE_OBSERVATION_ID")
    points = []
    for epoch in source_lists:
        ids = [c.source_id for c in epoch.centroids]
        if not epoch.observation_id or any(not x for x in ids) or len(set(ids)) != len(ids):
            raise ValueError("UNIQUE_OBSERVATION_AND_SOURCE_IDS_REQUIRED")
        points.extend(
            TrackPoint(epoch.observation_id, epoch.mjd_utc, c, epoch.provenance)
            for c in epoch.centroids
        )
    points.sort(key=lambda p: (p.mjd_utc if finite(p.mjd_utc) else float("inf"), p.key))
    unmatched = [
        UnmatchedDetection(p, position_reasons(p)) for p in points if not position_valid(p)
    ]
    usable = [p for p in points if position_valid(p)]
    tracks: list[SourceTrack] = []
    retired: set[int] = set()
    ambiguous, rejected = [], []
    for time in sorted({p.mjd_utc for p in usable}):
        group = [p for p in usable if p.mjd_utc == time]
        candidates = []
        for index, track in enumerate(tracks):
            if index in retired:
                continue
            previous = track.points[-1]
            for point in group:
                errors = (previous.centroid.uncertainty_arcsec, point.centroid.uncertainty_arcsec)
                known = all(finite(e) and e > 0 for e in errors)
                requested = (
                    (
                        policy.radius_arcsec
                        + policy.uncertainty_multiplier * np.hypot(*errors)
                        + policy.allowance_arcsec_per_day * (time - previous.mjd_utc)
                    )
                    if known
                    else policy.max_radius_arcsec
                )
                tolerance = float(min(policy.max_radius_arcsec, requested))
                distance = float(sky(previous).separation(sky(point)).arcsec)
                reasons = [
                    *position_reasons(previous, policy.min_valid_fraction),
                    *position_reasons(point, policy.min_valid_fraction),
                ]
                if requested > policy.max_radius_arcsec:
                    reasons.append("REQUESTED_TOLERANCE_EXCEEDS_SEARCH_CAP")
                edge = AssociationEdge(
                    previous, point, distance, tolerance, tuple(dict.fromkeys(reasons))
                )
                if distance <= tolerance:
                    candidates.append((index, edge))
                else:
                    rejected.append(
                        AssociationEdge(
                            previous,
                            point,
                            distance,
                            tolerance,
                            (*edge.reasons, "OUTSIDE_TOLERANCE"),
                        )
                    )
        used, contested = set(), set()
        for index, edge in candidates:
            multiple = (
                sum(i == index for i, _ in candidates) > 1
                or sum(e.current.key == edge.current.key for _, e in candidates) > 1
            )
            if multiple or edge.reasons:
                reasons = (*edge.reasons, "COMPETING_ASSOCIATIONS") if multiple else edge.reasons
                ambiguous.append(
                    AssociationEdge(
                        edge.previous,
                        edge.current,
                        edge.separation_arcsec,
                        edge.tolerance_arcsec,
                        reasons,
                    )
                )
                contested.add(edge.current.key)
                retired.add(index)
                old = tracks[index]
                tracks[index] = SourceTrack(old.track_id, old.points, old.matches, True)
            else:
                old = tracks[index]
                tracks[index] = SourceTrack(
                    old.track_id, (*old.points, edge.current), (*old.matches, edge)
                )
                used.add(edge.current.key)
        for point in group:
            if point.key in contested:
                unmatched.append(UnmatchedDetection(point, ("AMBIGUOUS_ASSOCIATION",)))
            elif point.key not in used:
                tracks.append(SourceTrack(f"track_{len(tracks) + 1:04d}", (point,)))
    for track in tracks:
        if len(track.points) == 1:
            unmatched.append(
                UnmatchedDetection(
                    track.points[0], ("AMBIGUOUS_ASSOCIATION" if track.ambiguous else "NO_MATCH",)
                )
            )
    return AssociationResult(
        tuple(t for t in tracks if len(t.points) >= 2),
        tuple(unmatched),
        tuple(ambiguous),
        tuple(rejected),
        {
            "method": "spherical-unique-candidate-v1",
            "policy": asdict(policy),
            "time_scale": "UTC_MJD",
            "epochs": tuple(
                e.observation_id
                for e in sorted(
                    source_lists,
                    key=lambda e: (
                        e.mjd_utc if finite(e.mjd_utc) else float("inf"),
                        e.observation_id,
                    ),
                )
            ),
        },
    )
