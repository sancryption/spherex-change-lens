"""Build chronological series manifests from discovery and validation evidence."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta

from changelens.contracts import (
    DiscoveryResult,
    DiscoveryStatus,
    ObservationRecord,
    ObservationValidationReport,
    RetrievalStatus,
    SourceArtifact,
    TargetRecord,
    TimelineEvidenceCounts,
    TimelineManifest,
    TimelineManifestFrame,
    TimelineManifestSeries,
    TimelineStatus,
    ValidationStatus,
)

_VALIDATION_FIELDS = (
    "fits_status",
    "wcs_status",
    "compatibility_status",
    "science_status",
)


def _observation_time(observation: ObservationRecord) -> datetime | None:
    if observation.observed_at is not None:
        value = observation.observed_at
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if observation.mjd is not None:
        epoch = datetime(1858, 11, 17, tzinfo=UTC)
        return epoch + timedelta(days=observation.mjd)
    return None


def _normalize(value: str | None) -> str | None:
    normalized = value.strip().casefold() if value else ""
    return normalized or None


def _display(value: str | None) -> str | None:
    normalized = value.strip() if value else ""
    return normalized or None


def _group_values(observation: ObservationRecord) -> tuple[str | None, ...]:
    return (
        _normalize(observation.band),
        _normalize(observation.product_family),
        _normalize(observation.spectral_plane or observation.observation_id),
        _normalize(observation.release),
    )


def _record_fingerprint(observation: ObservationRecord) -> str:
    observed_at = _observation_time(observation)
    normalized_time = observed_at.astimezone(UTC).isoformat() if observed_at else None
    canonical = {
        "observation_id": observation.observation_id,
        "observed_at": normalized_time,
        "mjd": observation.mjd,
        "band": _normalize(observation.band),
        "product_family": _normalize(observation.product_family),
        "spectral_plane": _normalize(observation.spectral_plane or observation.observation_id),
        "release": _normalize(observation.release),
        "product": _normalize(observation.product),
        "width": observation.width,
        "height": observation.height,
        "remote_checksum": observation.remote_checksum,
        "access_url": str(observation.access_url) if observation.access_url else None,
        "footprint": observation.footprint,
    }
    return json.dumps(canonical, sort_keys=True, separators=(",", ":"), default=str)


def _report_specificity(report: ObservationValidationReport) -> int:
    return sum(
        getattr(report, field) is not None
        for field in ("band", "product_family", "spectral_plane", "release")
    )


def _report_matches(report: ObservationValidationReport, observation: ObservationRecord) -> bool:
    if report.observation_id != observation.observation_id:
        return False
    actual = {
        "band": _normalize(observation.band),
        "product_family": _normalize(observation.product_family),
        "spectral_plane": _normalize(observation.spectral_plane or observation.observation_id),
        "release": _normalize(observation.release),
    }
    return all(
        getattr(report, field) is None or _normalize(getattr(report, field)) == actual[field]
        for field in actual
    )


def _artifact_matches(artifact: SourceArtifact, observation: ObservationRecord) -> bool:
    return artifact.observation_id == observation.observation_id and (
        _normalize(observation.release) is None
        or _normalize(artifact.release) == _normalize(observation.release)
    )


def _matching_reports(
    observation: ObservationRecord,
    reports: list[ObservationValidationReport],
) -> tuple[list[ObservationValidationReport], list[str]]:
    matching = [report for report in reports if _report_matches(report, observation)]
    if not matching:
        return [], []
    specificity = max(_report_specificity(report) for report in matching)
    selected = [report for report in matching if _report_specificity(report) == specificity]
    signatures = {
        (
            report.retrieval_status.value,
            *(getattr(report, field).value for field in _VALIDATION_FIELDS),
            tuple(report.reasons),
        )
        for report in selected
    }
    reasons = ["CONFLICTING_VALIDATION_REPORTS"] if len(signatures) > 1 else []
    return selected, reasons


def _merge_validation_status(
    reports: list[ObservationValidationReport], field: str
) -> ValidationStatus:
    statuses = {getattr(report, field) for report in reports}
    for status in (
        ValidationStatus.FAILED,
        ValidationStatus.PARTIAL,
        ValidationStatus.PASSED,
    ):
        if status in statuses:
            return status
    return ValidationStatus.NOT_RUN


def _merge_retrieval_status(
    reports: list[ObservationValidationReport],
) -> RetrievalStatus:
    statuses = {report.retrieval_status for report in reports}
    if RetrievalStatus.DOWNLOADED in statuses:
        return RetrievalStatus.DOWNLOADED
    if RetrievalStatus.FAILED in statuses:
        return RetrievalStatus.FAILED
    return RetrievalStatus.NOT_ATTEMPTED


def _status_reasons(
    retrieval: RetrievalStatus,
    validation: dict[str, ValidationStatus],
) -> list[str]:
    reasons: list[str] = []
    if retrieval is RetrievalStatus.NOT_ATTEMPTED:
        reasons.append("RETRIEVAL_NOT_ATTEMPTED")
    elif retrieval is RetrievalStatus.FAILED:
        reasons.append("RETRIEVAL_FAILED")
    labels = {
        "fits_status": "FITS_VALIDATION",
        "wcs_status": "WCS_VALIDATION",
        "compatibility_status": "COMPATIBILITY_VALIDATION",
        "science_status": "SCIENCE_VALIDATION",
    }
    for field, label in labels.items():
        status = validation[field]
        if status is not ValidationStatus.PASSED:
            reasons.append(f"{label}_{status.value}")
    return reasons


def _counts(frames: list[TimelineManifestFrame]) -> TimelineEvidenceCounts:
    return TimelineEvidenceCounts(
        data_found=len(frames),
        downloaded=sum(frame.retrieval_status is RetrievalStatus.DOWNLOADED for frame in frames),
        parsed=sum(frame.fits_status is ValidationStatus.PASSED for frame in frames),
        compatible=sum(frame.compatibility_status is ValidationStatus.PASSED for frame in frames),
        scientifically_measured=sum(
            frame.science_status is ValidationStatus.PASSED for frame in frames
        ),
    )


def _group_display_value(frames: list[TimelineManifestFrame], field: str) -> str | None:
    values = {value for frame in frames if (value := _display(getattr(frame, field))) is not None}
    return min(values, key=lambda value: (value.casefold(), value)) if values else None


def _baseline_days(frames: list[TimelineManifestFrame]) -> float:
    times = [frame.observed_at.astimezone(UTC) for frame in frames if frame.observed_at is not None]
    if len(times) < 2:
        return 0.0
    return (max(times) - min(times)).total_seconds() / 86400.0


def _series_status(
    frames: list[TimelineManifestFrame], discovery: DiscoveryResult
) -> tuple[TimelineStatus, list[str]]:
    reasons = list(discovery.warnings)
    if discovery.status is not DiscoveryStatus.COMPLETE:
        reasons.append(f"DISCOVERY_{discovery.status.value}")
    if any(frame.compatibility_status is ValidationStatus.FAILED for frame in frames):
        return TimelineStatus.INCOMPATIBLE, reasons
    if len(frames) == 1:
        return TimelineStatus.ONE_FRAME, reasons
    dated = {frame.observed_at.astimezone(UTC) for frame in frames if frame.observed_at is not None}
    if len(dated) < 2:
        reasons.append("INSUFFICIENT_DATED_EPOCHS")
        return TimelineStatus.PARTIALLY_VALIDATED, reasons
    if discovery.status is not DiscoveryStatus.COMPLETE:
        return TimelineStatus.PARTIALLY_VALIDATED, reasons
    all_evidence_complete = all(
        frame.retrieval_status is RetrievalStatus.DOWNLOADED
        and all(getattr(frame, field) is ValidationStatus.PASSED for field in _VALIDATION_FIELDS)
        for frame in frames
    )
    if all_evidence_complete:
        return TimelineStatus.USABLE, reasons
    return TimelineStatus.PARTIALLY_VALIDATED, reasons


def _manifest_status(
    discovery: DiscoveryResult,
    series: list[TimelineManifestSeries],
) -> TimelineStatus:
    if not series:
        return (
            TimelineStatus.EMPTY
            if discovery.status is DiscoveryStatus.NO_RESULTS
            else TimelineStatus.UNAVAILABLE
        )
    statuses = [item.status for item in series]
    if all(status is TimelineStatus.USABLE for status in statuses):
        return TimelineStatus.USABLE
    if len(statuses) == 1:
        return statuses[0]
    if all(status is TimelineStatus.INCOMPATIBLE for status in statuses):
        return TimelineStatus.INCOMPATIBLE
    return TimelineStatus.PARTIALLY_VALIDATED


def build_timeline_manifest(
    target: TargetRecord,
    discovery: DiscoveryResult,
    *,
    validation_reports: Iterable[ObservationValidationReport | dict[str, object]] = (),
    source_artifacts: Iterable[SourceArtifact | dict[str, object]] = (),
    file_validated_observation_ids: set[str] | None = None,
) -> TimelineManifest:
    """Group observations by band, product family, plane, and release.

    Duplicate archive rows with the same complete product identity are collapsed,
    while conflicting records and every validation failure remain in the manifest.
    A series is usable only after download, FITS, WCS, compatibility, and science
    evidence all pass for at least two distinct dated frames.
    """

    reports = [
        report
        if isinstance(report, ObservationValidationReport)
        else ObservationValidationReport.model_validate(report)
        for report in validation_reports
    ]
    for observation_id in file_validated_observation_ids or set():
        reports.append(
            ObservationValidationReport(
                observation_id=observation_id,
                fits_status=ValidationStatus.PASSED,
            )
        )
    artifacts = [
        artifact
        if isinstance(artifact, SourceArtifact)
        else SourceArtifact.model_validate(artifact)
        for artifact in source_artifacts
    ]

    duplicate_records: dict[str, tuple[ObservationRecord, int, set[str]]] = {}
    for observation in discovery.observations:
        fingerprint = _record_fingerprint(observation)
        previous = duplicate_records.get(fingerprint)
        if previous:
            duplicate_records[fingerprint] = (
                previous[0],
                previous[1] + 1,
                previous[2] | set(observation.warnings),
            )
        else:
            duplicate_records[fingerprint] = (
                observation,
                1,
                set(observation.warnings),
            )
    records = list(duplicate_records.values())
    id_record_counts: dict[str, int] = defaultdict(int)
    for observation, _, _ in records:
        id_record_counts[observation.observation_id] += 1

    grouped: dict[
        tuple[str | None, ...],
        list[tuple[ObservationRecord, int, set[str]]],
    ] = defaultdict(list)
    for observation, copies, duplicate_warnings in records:
        grouped[_group_values(observation)].append((observation, copies, duplicate_warnings))

    series_models: list[TimelineManifestSeries] = []
    for group_key in sorted(grouped, key=lambda key: tuple(value or "" for value in key)):
        observations = grouped[group_key]
        ordered_frames: list[tuple[TimelineManifestFrame, str]] = []
        for observation, copies, duplicate_warnings in observations:
            matched_reports, report_reasons = _matching_reports(observation, reports)
            validation = {
                field: _merge_validation_status(matched_reports, field)
                for field in _VALIDATION_FIELDS
            }
            retrieval = _merge_retrieval_status(matched_reports)
            has_artifact = any(_artifact_matches(artifact, observation) for artifact in artifacts)
            if has_artifact:
                if retrieval is RetrievalStatus.FAILED:
                    report_reasons.append("RETRIEVAL_REPORT_CONFLICT")
                retrieval = RetrievalStatus.DOWNLOADED

            reasons = sorted(duplicate_warnings) + report_reasons
            for report in matched_reports:
                reasons.extend(report.reasons)
            reasons.extend(_status_reasons(retrieval, validation))
            if _display(observation.band) is None:
                reasons.append("BAND_UNKNOWN")
            if _display(observation.product_family) is None:
                reasons.append("PRODUCT_FAMILY_UNKNOWN")
            if _display(observation.spectral_plane or observation.observation_id) is None:
                reasons.append("SPECTRAL_PLANE_UNKNOWN")
            if _display(observation.release) is None:
                reasons.append("RELEASE_UNKNOWN")
            if _observation_time(observation) is None:
                reasons.append("OBSERVATION_TIME_MISSING")
            if id_record_counts[observation.observation_id] > 1:
                reasons.append("DUPLICATE_OBSERVATION_CONFLICT")

            frame = TimelineManifestFrame(
                observation_id=observation.observation_id,
                observed_at=_observation_time(observation),
                band=_display(observation.band),
                product_family=_display(observation.product_family),
                spectral_plane=_display(observation.spectral_plane or observation.observation_id),
                release=_display(observation.release),
                duplicate_count=copies,
                retrieval_status=retrieval,
                **validation,
                reasons=list(dict.fromkeys(reasons)),
            )
            ordered_frames.append((frame, _record_fingerprint(observation)))
        ordered_frames.sort(
            key=lambda item: (
                item[0].observed_at is None,
                item[0].observed_at.astimezone(UTC)
                if item[0].observed_at is not None
                else datetime.max.replace(tzinfo=UTC),
                item[0].observation_id,
                item[1],
            )
        )
        frames = [frame for frame, _ in ordered_frames]
        status, reasons = _series_status(frames, discovery)
        grouping = {
            "band": group_key[0],
            "product_family": group_key[1],
            "spectral_plane": group_key[2],
            "release": group_key[3],
        }
        series_id = (
            "series_"
            + hashlib.sha256(
                json.dumps(grouping, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest()[:24]
        )
        series_models.append(
            TimelineManifestSeries(
                series_id=series_id,
                band=_group_display_value(frames, "band"),
                product_family=_group_display_value(frames, "product_family"),
                spectral_plane=_group_display_value(frames, "spectral_plane"),
                release=_group_display_value(frames, "release"),
                status=status,
                frames=frames,
                time_baseline_days=_baseline_days(frames),
                evidence_counts=_counts(frames),
                reasons=list(dict.fromkeys(reasons)),
            )
        )

    all_frames = [frame for series in series_models for frame in series.frames]
    distinct_times = sorted(
        {frame.observed_at.astimezone(UTC) for frame in all_frames if frame.observed_at is not None}
    )
    unmatched_reports = [
        report
        for report in reports
        if not any(_report_matches(report, observation) for observation in discovery.observations)
    ]
    unmatched_artifacts = [
        artifact
        for artifact in artifacts
        if not any(
            _artifact_matches(artifact, observation)
            for observation in discovery.observations
        )
    ]
    manifest_warnings = list(discovery.warnings)
    manifest_warnings.extend(
        f"UNMATCHED_VALIDATION_REPORT:{report.observation_id}" for report in unmatched_reports
    )
    manifest_warnings.extend(
        f"UNMATCHED_SOURCE_ARTIFACT:{artifact.artifact_id}" for artifact in unmatched_artifacts
    )
    manifest_baseline = (
        (distinct_times[-1] - distinct_times[0]).total_seconds() / 86400.0
        if len(distinct_times) > 1
        else 0.0
    )
    return TimelineManifest(
        target_id=target.target_id,
        target_name=target.name,
        discovery_status=discovery.status,
        status=_manifest_status(discovery, series_models),
        record_count=len(discovery.observations),
        distinct_frame_count=len(all_frames),
        duplicate_record_count=len(discovery.observations) - len(all_frames),
        time_baseline_days=manifest_baseline,
        evidence_counts=_counts(all_frames),
        series=series_models,
        unmatched_validation_reports=unmatched_reports,
        unmatched_source_artifacts=unmatched_artifacts,
        warnings=list(dict.fromkeys(manifest_warnings)),
        provenance_id=discovery.raw_response_artifact_id,
    )


__all__ = ["build_timeline_manifest"]
