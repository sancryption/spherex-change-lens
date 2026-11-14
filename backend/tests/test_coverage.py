from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from changelens.contracts import (
    DiscoveryResult,
    DiscoveryStatus,
    ObservationRecord,
    TargetRecord,
    TimelineModel,
)
from changelens.data.coverage import build_target_coverage, render_coverage_report


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
