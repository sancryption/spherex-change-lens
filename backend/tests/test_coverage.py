from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from changelens.contracts import (
    ChecksumStatus,
    DiscoveryResult,
    DiscoveryStatus,
    ObservationRecord,
    RetrievalMode,
    SourceArtifact,
    TargetRecord,
    TimelineModel,
)
from changelens.data.coverage import (
    build_coverage_report,
    build_target_coverage,
    render_coverage_report,
)


def test_coverage_counts_frames_detectors_and_visit_groups_without_claiming_usability() -> None:
    target = TargetRecord(
        target_id="wise_0855",
        name="WISE 0855",
        ra_deg=133.7951291667,
        dec_deg=-7.2451472222,
        role="NASA challenge test target",
    )
    first = datetime(2025, 1, 1, tzinfo=UTC)
    observations = [
        ObservationRecord(observation_id="p1", observed_at=first, mjd=60676, band="SPHEREx-D1", release="DR1"),
        ObservationRecord(
            observation_id="p2",
            observed_at=first + timedelta(days=2),
            mjd=60678,
            band="SPHEREx-D2",
            release="DR1",
        ),
        ObservationRecord(
            observation_id="p3",
            observed_at=first + timedelta(days=40),
            mjd=60716,
            band="SPHEREx-D1",
            release="QR3",
        ),
    ]

    report = build_target_coverage(
        target,
        DiscoveryResult(status=DiscoveryStatus.COMPLETE, observations=observations),
        file_validated_observation_ids={"p1"},
    )
    markdown = render_coverage_report([report])

    assert report["frame_count"] == 3
    assert report["date_range"] == {"start": "2025-01-01", "end": "2025-02-10"}
    assert report["detector_counts"] == {"SPHEREx-D1": 2, "SPHEREx-D2": 1}
    assert report["visit_group_count"] == 2
    assert report["release_counts"] == {"DR1": 2, "QR3": 1}
    assert report["metadata_only_count"] == 2
    assert report["file_validated_count"] == 1
    assert report["file_validated_observation_ids"] == ["p1"]
    assert report["target_status"] == "UNVERIFIED"
    assert report["usable"] is False
    assert "usable coverage is not claimed" in markdown.lower()
    assert "full per-series and per-frame manifests are returned by `build_coverage_report()`" in markdown.lower()


def test_empty_and_partial_discovery_states_remain_explicit() -> None:
    target = TargetRecord(
        target_id="r_draconis",
        name="R Draconis",
        ra_deg=248.167610833,
        dec_deg=66.7549794172,
        role="NASA challenge test target",
    )

    empty = build_target_coverage(
        target, DiscoveryResult(status=DiscoveryStatus.NO_RESULTS)
    )
    partial = build_target_coverage(
        target,
        DiscoveryResult(
            status=DiscoveryStatus.PARTIAL,
            observations=[ObservationRecord(observation_id="p1")],
            warnings=["ARCHIVE_RESULT_OVERFLOW"],
        ),
    )

    assert empty["frame_count"] == 0
    assert empty["date_range"] is None
    assert partial["discovery_status"] == "PARTIAL"
    assert partial["warnings"] == ["ARCHIVE_RESULT_OVERFLOW"]
    assert partial["target_status"] == "UNVERIFIED"


def test_duplicate_observation_times_remain_in_the_same_visit_group() -> None:
    target = TargetRecord(
        target_id="barnards_star",
        name="Barnard's Star",
        ra_deg=269.4520769586,
        dec_deg=4.6933649666,
        role="NASA challenge test target",
    )
    timestamp = datetime(2025, 1, 1, tzinfo=UTC)
    result = DiscoveryResult(
        status=DiscoveryStatus.COMPLETE,
        observations=[
            ObservationRecord(observation_id="p1", observed_at=timestamp),
            ObservationRecord(observation_id="p2", observed_at=timestamp),
        ],
    )

    report = build_target_coverage(target, result)

    assert report["frame_count"] == 2
    assert report["visit_group_count"] == 1


def test_authentic_timeline_fixture_is_contract_valid_and_cautious() -> None:
    fixture_path = Path(__file__).parent / "fixtures" / "authentic_timeline_barnards_star.json"

    timeline = TimelineModel.model_validate_json(fixture_path.read_text(encoding="utf-8"))

    assert timeline.series_status.value == "PARTIALLY_VALIDATED"
    assert len(timeline.frames) == 1
    assert timeline.frames[0].availability.value == "VALIDATED_WITH_WARNINGS"
    assert "FITS_CONTAINER_VALIDATED_ONLY" in timeline.frames[0].warnings


def test_observation_record_retains_product_family_and_spectral_plane() -> None:
    record = ObservationRecord(
        observation_id="plane-001",
        product_family="LEVEL2",
        spectral_plane="CH2",
    )

    assert record.product_family == "LEVEL2"
    assert record.spectral_plane == "CH2"


def _timeline_builder():
    from changelens.data import coverage

    builder = getattr(coverage, "build_timeline_manifest", None)
    assert callable(builder), "coverage must expose a timeline manifest builder"
    return builder


def _target() -> TargetRecord:
    return TargetRecord(
        target_id="wise_0855",
        name="WISE 0855",
        ra_deg=133.7951291667,
        dec_deg=-7.2451472222,
        role="NASA challenge test target",
    )


def _frame(observation_id: str, day: int) -> ObservationRecord:
    return ObservationRecord(
        observation_id=observation_id,
        observed_at=datetime(2025, 1, 1, tzinfo=UTC) + timedelta(days=day),
        band="SPHEREx-D2",
        release="DR1",
        product="image",
        product_family="LEVEL2",
        spectral_plane="CH2",
    )


def _complete_validation(observation_id: str) -> dict[str, object]:
    return {
        "observation_id": observation_id,
        "band": "SPHEREx-D2",
        "release": "DR1",
        "product_family": "LEVEL2",
        "spectral_plane": "CH2",
        "retrieval_status": "DOWNLOADED",
        "fits_status": "PASSED",
        "wcs_status": "PASSED",
        "compatibility_status": "PASSED",
        "science_status": "PASSED",
    }


def test_timeline_manifest_sorts_and_collapses_exact_duplicate_observations() -> None:
    build_timeline_manifest = _timeline_builder()
    discovery = DiscoveryResult(
        status=DiscoveryStatus.COMPLETE,
        observations=[_frame("p2", 10), _frame("p1", 0), _frame("p1", 0)],
    )

    manifest = build_timeline_manifest(_target(), discovery)

    assert manifest.status.value == "PARTIALLY_VALIDATED"
    assert len(manifest.series) == 1
    series = manifest.series[0]
    assert (series.band, series.product_family, series.spectral_plane, series.release) == (
        "SPHEREx-D2",
        "LEVEL2",
        "CH2",
        "DR1",
    )
    assert [frame.observation_id for frame in series.frames] == ["p1", "p2"]
    assert [frame.duplicate_count for frame in series.frames] == [2, 1]
    assert series.time_baseline_days == 10
    assert manifest.record_count == 3
    assert manifest.duplicate_record_count == 1
    assert series.evidence_counts.model_dump() == {
        "data_found": 2,
        "downloaded": 0,
        "parsed": 0,
        "compatible": 0,
        "scientifically_measured": 0,
    }


def test_timeline_manifest_keeps_one_frame_and_partial_discovery_reasons() -> None:
    build_timeline_manifest = _timeline_builder()
    manifest = build_timeline_manifest(
        _target(),
        DiscoveryResult(
            status=DiscoveryStatus.PARTIAL,
            observations=[_frame("p1", 0)],
            warnings=["ARCHIVE_RESULT_OVERFLOW"],
        ),
        validation_reports=[_complete_validation("p1")],
    )

    assert manifest.status.value == "ONE_FRAME"
    assert manifest.series[0].status.value == "ONE_FRAME"
    assert "ARCHIVE_RESULT_OVERFLOW" in manifest.series[0].reasons
    assert manifest.series[0].frames[0].fits_status.value == "PASSED"
    assert manifest.evidence_counts.scientifically_measured == 1


def test_timeline_manifest_retains_incompatible_observations_with_reasons() -> None:
    build_timeline_manifest = _timeline_builder()
    report = _complete_validation("p1") | {
        "compatibility_status": "FAILED",
        "reasons": ["PRODUCT_FAMILY_MISMATCH"],
    }

    manifest = build_timeline_manifest(
        _target(),
        DiscoveryResult(
            status=DiscoveryStatus.COMPLETE,
            observations=[_frame("p1", 0), _frame("p2", 10)],
        ),
        validation_reports=[report],
    )

    assert manifest.status.value == "INCOMPATIBLE"
    assert manifest.series[0].status.value == "INCOMPATIBLE"
    assert [frame.observation_id for frame in manifest.series[0].frames] == ["p1", "p2"]
    assert manifest.series[0].evidence_counts.compatible == 0
    assert "PRODUCT_FAMILY_MISMATCH" in manifest.series[0].frames[0].reasons


def test_timeline_manifest_marks_series_usable_only_with_complete_evidence() -> None:
    build_timeline_manifest = _timeline_builder()
    manifest = build_timeline_manifest(
        _target(),
        DiscoveryResult(
            status=DiscoveryStatus.COMPLETE,
            observations=[_frame("p1", 0), _frame("p2", 10)],
        ),
        validation_reports=[_complete_validation("p1"), _complete_validation("p2")],
    )

    assert manifest.status.value == "USABLE"
    assert manifest.series[0].status.value == "USABLE"
    assert manifest.series[0].time_baseline_days == 10
    assert manifest.series[0].evidence_counts.model_dump() == {
        "data_found": 2,
        "downloaded": 2,
        "parsed": 2,
        "compatible": 2,
        "scientifically_measured": 2,
    }


def test_timeline_manifest_separates_each_grouping_dimension() -> None:
    build_timeline_manifest = _timeline_builder()
    observations = [
        _frame("p1", 0),
        _frame("p2", 1).model_copy(update={"band": "SPHEREx-D3"}),
        _frame("p3", 2).model_copy(update={"product_family": "LEVEL3"}),
        _frame("p4", 3).model_copy(update={"spectral_plane": "CH3"}),
        _frame("p5", 4).model_copy(update={"release": "QR3"}),
    ]

    manifest = build_timeline_manifest(
        _target(),
        DiscoveryResult(status=DiscoveryStatus.COMPLETE, observations=observations),
    )

    assert len(manifest.series) == 5
    assert {
        (series.band, series.product_family, series.spectral_plane, series.release)
        for series in manifest.series
    } == {
        ("SPHEREx-D2", "LEVEL2", "CH2", "DR1"),
        ("SPHEREx-D3", "LEVEL2", "CH2", "DR1"),
        ("SPHEREx-D2", "LEVEL3", "CH2", "DR1"),
        ("SPHEREx-D2", "LEVEL2", "CH3", "DR1"),
        ("SPHEREx-D2", "LEVEL2", "CH2", "QR3"),
    }


def test_timeline_manifest_uses_source_artifacts_as_download_evidence() -> None:
    build_timeline_manifest = _timeline_builder()
    artifact = SourceArtifact(
        artifact_id="art_source_p1",
        source_url="https://irsa.ipac.caltech.edu/data/p1.fits",
        observation_id="p1",
        release="DR1",
        size_bytes=1,
        retrieved_at=datetime(2025, 1, 2, tzinfo=UTC),
        sha256="a" * 64,
        checksum_status=ChecksumStatus.COMPUTED,
        retrieval_mode=RetrievalMode.FULL_FILE,
    )

    manifest = build_timeline_manifest(
        _target(),
        DiscoveryResult(
            status=DiscoveryStatus.COMPLETE,
            observations=[_frame("p1", 0)],
        ),
        source_artifacts=[artifact],
    )

    assert manifest.evidence_counts.downloaded == 1
    assert manifest.series[0].frames[0].retrieval_status.value == "DOWNLOADED"


def test_timeline_manifest_does_not_call_unknown_release_artifact_unmatched() -> None:
    build_timeline_manifest = _timeline_builder()
    artifact = SourceArtifact(
        artifact_id="art_source_unknown_release",
        source_url="https://irsa.ipac.caltech.edu/data/p1.fits",
        observation_id="p1",
        release="DR1",
        size_bytes=1,
        retrieved_at=datetime(2025, 1, 2, tzinfo=UTC),
        sha256="c" * 64,
        checksum_status=ChecksumStatus.COMPUTED,
        retrieval_mode=RetrievalMode.FULL_FILE,
    )

    manifest = build_timeline_manifest(
        _target(),
        DiscoveryResult(
            status=DiscoveryStatus.COMPLETE,
            observations=[_frame("p1", 0).model_copy(update={"release": None})],
        ),
        source_artifacts=[artifact],
    )

    assert manifest.evidence_counts.downloaded == 1
    assert manifest.unmatched_source_artifacts == []
    assert "UNMATCHED_SOURCE_ARTIFACT:art_source_unknown_release" not in manifest.warnings


def test_timeline_manifest_preserves_conflicting_duplicate_ids_with_reasons() -> None:
    build_timeline_manifest = _timeline_builder()
    observations = [
        _frame("p1", 0),
        _frame("p1", 1),
    ]

    manifest = build_timeline_manifest(
        _target(),
        DiscoveryResult(status=DiscoveryStatus.COMPLETE, observations=observations),
    )

    assert manifest.record_count == 2
    assert manifest.distinct_frame_count == 2
    assert manifest.duplicate_record_count == 0
    assert len(manifest.series[0].frames) == 2
    assert all(
        "DUPLICATE_OBSERVATION_CONFLICT" in frame.reasons
        for frame in manifest.series[0].frames
    )


def test_timeline_manifest_does_not_collapse_records_with_conflicting_mjd() -> None:
    build_timeline_manifest = _timeline_builder()
    same_time = _frame("p1", 0)
    observations = [
        same_time.model_copy(update={"mjd": 60676}),
        same_time.model_copy(update={"mjd": 60677}),
    ]

    manifest = build_timeline_manifest(
        _target(),
        DiscoveryResult(status=DiscoveryStatus.COMPLETE, observations=observations),
    )

    assert manifest.record_count == 2
    assert manifest.distinct_frame_count == 2
    assert manifest.duplicate_record_count == 0
    assert all(
        "DUPLICATE_OBSERVATION_CONFLICT" in frame.reasons
        for frame in manifest.series[0].frames
    )


def test_timeline_manifest_merges_reasons_from_collapsed_duplicate_rows() -> None:
    build_timeline_manifest = _timeline_builder()
    first = _frame("p1", 0).model_copy(update={"warnings": ["ARCHIVE_WARNING_A"]})
    second = _frame("p1", 0).model_copy(update={"warnings": ["ARCHIVE_WARNING_B"]})

    manifest = build_timeline_manifest(
        _target(),
        DiscoveryResult(status=DiscoveryStatus.COMPLETE, observations=[first, second]),
    )

    assert manifest.duplicate_record_count == 1
    assert manifest.series[0].frames[0].duplicate_count == 2
    assert {"ARCHIVE_WARNING_A", "ARCHIVE_WARNING_B"} <= set(
        manifest.series[0].frames[0].reasons
    )


def test_timeline_manifest_retains_validation_evidence_without_discovery_records() -> None:
    build_timeline_manifest = _timeline_builder()
    artifact = SourceArtifact(
        artifact_id="art_source_orphan",
        source_url="https://irsa.ipac.caltech.edu/data/orphan.fits",
        observation_id="orphan",
        release="DR1",
        size_bytes=1,
        retrieved_at=datetime(2025, 1, 2, tzinfo=UTC),
        sha256="b" * 64,
        checksum_status=ChecksumStatus.COMPUTED,
        retrieval_mode=RetrievalMode.FULL_FILE,
    )

    manifest = build_timeline_manifest(
        _target(),
        DiscoveryResult(status=DiscoveryStatus.NO_RESULTS),
        validation_reports=[_complete_validation("orphan")],
        source_artifacts=[artifact],
    )

    assert manifest.status.value == "EMPTY"
    unmatched_reports = getattr(manifest, "unmatched_validation_reports", [])
    unmatched_artifacts = getattr(manifest, "unmatched_source_artifacts", [])
    assert unmatched_reports and unmatched_reports[0].observation_id == "orphan"
    assert unmatched_artifacts and unmatched_artifacts[0].artifact_id == "art_source_orphan"
    assert "UNMATCHED_VALIDATION_REPORT:orphan" in manifest.warnings
    assert "UNMATCHED_SOURCE_ARTIFACT:art_source_orphan" in manifest.warnings


def test_timeline_manifest_retains_undated_unknown_observations_with_reasons() -> None:
    build_timeline_manifest = _timeline_builder()
    manifest = build_timeline_manifest(
        _target(),
        DiscoveryResult(
            status=DiscoveryStatus.COMPLETE,
            observations=[ObservationRecord(observation_id="unknown-plane")],
        ),
    )
    frame = manifest.series[0].frames[0]

    assert manifest.distinct_frame_count == 1
    assert manifest.status.value == "ONE_FRAME"
    assert "BAND_UNKNOWN" in frame.reasons
    assert "PRODUCT_FAMILY_UNKNOWN" in frame.reasons
    assert "RELEASE_UNKNOWN" in frame.reasons
    assert "OBSERVATION_TIME_MISSING" in frame.reasons


def test_target_coverage_exposes_every_timeline_validation_level() -> None:
    report = build_target_coverage(
        _target(),
        DiscoveryResult(
            status=DiscoveryStatus.COMPLETE,
            observations=[_frame("p1", 0), _frame("p2", 10)],
        ),
        validation_reports=[_complete_validation("p1")],
    )
    markdown = render_coverage_report([report])

    assert report["validation_counts"] == {
        "data_found": 2,
        "downloaded": 1,
        "parsed": 1,
        "compatible": 1,
        "scientifically_measured": 1,
    }
    assert report["timeline_status"] == "PARTIALLY_VALIDATED"
    assert report["timeline_manifest"]["series"][0]["frames"][0]["fits_status"] == "PASSED"
    assert report["file_validated_count"] == 1
    assert report["file_validated_observation_ids"] == ["p1"]
    assert report["science_validated_count"] == 1
    assert "2 found, 1 downloaded, 1 parsed, 1 compatible, 1 scientifically measured" in markdown


def test_specific_failed_fits_report_overrides_legacy_validated_id() -> None:
    report = build_target_coverage(
        _target(),
        DiscoveryResult(
            status=DiscoveryStatus.COMPLETE,
            observations=[_frame("p1", 0)],
        ),
        file_validated_observation_ids={"p1"},
        validation_reports=[
            _complete_validation("p1") | {"fits_status": "FAILED"}
        ],
    )

    assert report["timeline_manifest"]["series"][0]["frames"][0]["fits_status"] == "FAILED"
    assert report["file_validated_count"] == 0
    assert report["file_validated_observation_ids"] == []


def test_coverage_report_passes_validation_evidence_into_timeline_manifests() -> None:
    target = _target()
    report = build_coverage_report(
        [target],
        {
            target.target_id: DiscoveryResult(
                status=DiscoveryStatus.COMPLETE,
                observations=[_frame("p1", 0), _frame("p2", 10)],
            )
        },
        validation_reports={target.target_id: [_complete_validation("p1")]},
    )

    target_report = report["targets"][0]
    assert target_report["timeline_manifest"]["evidence_counts"] == {
        "data_found": 2,
        "downloaded": 1,
        "parsed": 1,
        "compatible": 1,
        "scientifically_measured": 1,
    }
