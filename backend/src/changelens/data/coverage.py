"""Metadata-only archive coverage summaries for the NASA target set."""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta

from changelens.contracts import (
    DiscoveryResult,
    DiscoveryStatus,
    ObservationRecord,
    ObservationValidationReport,
    SourceArtifact,
    TargetRecord,
)
from changelens.data.timeline import build_timeline_manifest


def _observation_time(observation: ObservationRecord) -> datetime | None:
    if observation.observed_at is not None:
        value = observation.observed_at
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if observation.mjd is not None:
        epoch = datetime(1858, 11, 17, tzinfo=UTC)
        return epoch + timedelta(days=observation.mjd)
    return None


def _visit_groups(
    observations: Iterable[ObservationRecord], gap_days: float
) -> list[dict[str, object]]:
    dated = sorted(
        (
            (when, observation)
            for observation in observations
            if (when := _observation_time(observation)) is not None
        ),
        key=lambda item: item[0],
    )
    if not dated:
        return []
    groups: list[list[tuple[datetime, ObservationRecord]]] = [[dated[0]]]
    for item in dated[1:]:
        gap = item[0] - groups[-1][-1][0]
        if gap.total_seconds() > gap_days * 86400:
            groups.append([item])
        else:
            groups[-1].append(item)
    return [
        {
            "start": group[0][0].date().isoformat(),
            "end": group[-1][0].date().isoformat(),
            "frame_count": len(group),
        }
        for group in groups
    ]


def build_target_coverage(
    target: TargetRecord,
    discovery: DiscoveryResult,
    *,
    visit_gap_days: float = 30.0,
    file_validated_observation_ids: set[str] | None = None,
    validation_reports: Iterable[ObservationValidationReport | dict[str, object]] = (),
    source_artifacts: Iterable[SourceArtifact | dict[str, object]] = (),
) -> dict[str, object]:
    """Summarize metadata coverage while keeping target verification conservative."""

    observations = discovery.observations
    dates = [when for item in observations if (when := _observation_time(item)) is not None]
    dates.sort()
    detector_counts: dict[str, int] = {}
    release_counts: dict[str, int] = {}
    for observation in observations:
        detector = observation.band or "UNKNOWN"
        release = observation.release or "UNKNOWN"
        detector_counts[detector] = detector_counts.get(detector, 0) + 1
        release_counts[release] = release_counts.get(release, 0) + 1
    visit_groups = _visit_groups(observations, visit_gap_days)
    known_observation_ids = {item.observation_id for item in observations}
    timeline_manifest = build_timeline_manifest(
        target,
        discovery,
        validation_reports=validation_reports,
        source_artifacts=source_artifacts,
        file_validated_observation_ids=(file_validated_observation_ids or set())
        & known_observation_ids,
    )
    validated_ids = sorted(
        (
            {
                frame.observation_id
                for series in timeline_manifest.series
                for frame in series.frames
                if frame.fits_status.value == "PASSED"
            }
        )
        & known_observation_ids
    )
    if observations:
        data_state = "DATA_FOUND"
    elif discovery.status.value == "NO_RESULTS":
        data_state = "NO_RESULTS"
    else:
        data_state = "UNAVAILABLE_OR_PARTIAL"
    missing_date_count = len(observations) - len(dates)

    return {
        "target_id": target.target_id,
        "name": target.name,
        "coordinates": {
            "ra_deg": target.ra_deg,
            "dec_deg": target.dec_deg,
            "frame": target.frame,
        },
        "discovery_status": discovery.status.value,
        "data_state": data_state,
        "frame_count": len(observations),
        "date_range": (
            {"start": dates[0].date().isoformat(), "end": dates[-1].date().isoformat()}
            if dates
            else None
        ),
        "detector_counts": dict(sorted(detector_counts.items())),
        "release_counts": dict(sorted(release_counts.items())),
        "visit_gap_days": visit_gap_days,
        "visit_group_count": len(visit_groups),
        "visit_groups": visit_groups,
        "metadata_only_count": len(observations) - len(validated_ids),
        "file_validated_count": len(validated_ids),
        "file_validated_observation_ids": validated_ids,
        "science_validated_count": timeline_manifest.evidence_counts.scientifically_measured,
        "timeline_status": timeline_manifest.status.value,
        "validation_counts": timeline_manifest.evidence_counts.model_dump(),
        "timeline_manifest": timeline_manifest.model_dump(mode="json"),
        "missing_date_count": missing_date_count,
        "target_status": "UNVERIFIED",
        "usable": False,
        "warnings": list(discovery.warnings),
        "error_code": discovery.error_code,
        "http_status": discovery.http_status,
    }


def build_coverage_report(
    targets: Iterable[TargetRecord],
    discoveries: dict[str, DiscoveryResult],
    *,
    visit_gap_days: float = 30.0,
    file_validated_observation_ids: dict[str, set[str]] | None = None,
    validation_reports: dict[
        str, Iterable[ObservationValidationReport | dict[str, object]]
    ] | None = None,
    source_artifacts: dict[str, Iterable[SourceArtifact | dict[str, object]]] | None = None,
) -> dict[str, object]:
    target_reports = [
        build_target_coverage(
            target,
            discoveries.get(
                target.target_id,
                DiscoveryResult(
                    status=DiscoveryStatus.PARTIAL,
                    warnings=["DISCOVERY_NOT_RUN"],
                    error_code="DISCOVERY_NOT_RUN",
                ),
            ),
            visit_gap_days=visit_gap_days,
            file_validated_observation_ids=(file_validated_observation_ids or {}).get(
                target.target_id, set()
            ),
            validation_reports=(validation_reports or {}).get(target.target_id, ()),
            source_artifacts=(source_artifacts or {}).get(target.target_id, ()),
        )
        for target in targets
    ]
    has_file_validation = any(item["file_validated_count"] for item in target_reports)
    return {
        "schema_version": "1.0",
        "evidence_level": (
            "ARCHIVE_METADATA_WITH_FILE_VALIDATION"
            if has_file_validation
            else "ARCHIVE_METADATA_ONLY"
        ),
        "usable_coverage_claimed": False,
        "visit_gap_days": visit_gap_days,
        "targets": target_reports,
    }


def render_coverage_report(reports: list[dict[str, object]]) -> str:
    lines = [
        "# SPHEREx target coverage",
        "",
        "This report summarizes IRSA archive metadata and recorded FITS-container checks. Science validation has not been performed. Usable coverage is not claimed; every target remains `UNVERIFIED` until the required validation evidence is recorded.",
        "",
        "Timelines group observations by band, product family, spectral plane, and release. Exact duplicate records are counted once; conflicting or unusable observations remain with reasons. Full per-series and per-frame manifests are returned by `build_coverage_report()`; the checked-in JSON stores compact target summaries.",
        "",
        "Visit groups split when adjacent observation times differ by more than 30 days.",
        "",
        "| Target | Discovery | Frames | Date range | Detectors | Visit groups | Releases |",
        "|---|---|---:|---|---|---:|---|",
    ]
    for report in reports:
        date_range = report["date_range"]
        date_text = (
            f"{date_range['start']} – {date_range['end']}" if date_range else "—"
        )
        lines.append(
            "| {name} | {status} | {frames} | {dates} | {detectors} | {visits} | {releases} |".format(
                name=report["name"],
                status=report["discovery_status"],
                frames=report["frame_count"],
                dates=date_text,
                detectors=json.dumps(report["detector_counts"], sort_keys=True),
                visits=report["visit_group_count"],
                releases=json.dumps(report["release_counts"], sort_keys=True),
            )
        )
    lines.extend(["", "## Evidence limits", ""])
    for report in reports:
        lines.append(
            f"- **{report['name']}:** {report['metadata_only_count']} metadata records; "
            f"{report['file_validated_count']} file-validated; "
            f"{report['science_validated_count']} science-validated; "
            f"target status `{report['target_status']}`; usable `{str(report['usable']).lower()}`."
        )
        levels = report.get("validation_counts")
        if levels:
            lines.append(
                "  - Timeline evidence: "
                f"{levels['data_found']} found, {levels['downloaded']} downloaded, "
                f"{levels['parsed']} parsed, {levels['compatible']} compatible, "
                f"{levels['scientifically_measured']} scientifically measured; "
                f"series status `{report['timeline_status']}`."
            )
        for warning in report["warnings"]:
            lines.append(f"  - Warning: `{warning}`.")
    return "\n".join(lines) + "\n"


__all__ = [
    "build_coverage_report",
    "build_target_coverage",
    "build_timeline_manifest",
    "render_coverage_report",
]
