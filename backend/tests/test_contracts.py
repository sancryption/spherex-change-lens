from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from changelens import contracts


def contract(name: str):
    value = getattr(contracts, name, None)
    assert value is not None, f"Draft contract {name} has not been defined"
    return value


def test_documented_observation_availability_values_are_preserved() -> None:
    status = contract("ObservationAvailability")

    assert {item.value for item in status} == {
        "VALIDATED",
        "VALIDATED_WITH_WARNINGS",
        "INVALID",
        "UNAVAILABLE",
        "SYNTHETIC",
    }


def test_documented_run_status_values_are_preserved() -> None:
    status = contract("RunStatus")

    assert {item.value for item in status} == {
        "QUEUED",
        "RUNNING",
        "SUCCEEDED",
        "SUCCEEDED_WITH_WARNINGS",
        "FAILED",
        "CANCELLED",
    }


def test_documented_evidence_status_values_are_preserved() -> None:
    status = contract("EvidenceStatus")

    assert {item.value for item in status} == {
        "NO_RELIABLE_CHANGE",
        "POSSIBLE_POSITIONAL_MOVEMENT",
        "POSSIBLE_BRIGHTNESS_VARIATION",
        "ARTIFACT_RISK",
        "AMBIGUOUS",
        "INSUFFICIENT_EVIDENCE",
    }


def test_investigation_request_accepts_the_pdf_example() -> None:
    model = contract("InvestigationRequest")
    request = model.model_validate(
        {
            "target_name": "WISE_0855",
            "ra_deg": 133.7951291667,
            "dec_deg": -7.2451472222,
            "frame": "ICRS",
            "fov_arcmin": 10,
            "collection": "spherex_qr3",
            "band_policy": "SAME_SUPPORTED_BAND",
        }
    )

    assert request.ra_deg == 133.7951291667
    assert request.dec_deg == -7.2451472222
    assert request.model_dump(mode="json")["frame"] == "ICRS"


@pytest.mark.parametrize("collection", ["%", "dr1%", "dr_1", "spherex_qr3%"])
def test_investigation_request_rejects_collection_like_wildcards(collection: str) -> None:
    model = contract("InvestigationRequest")

    with pytest.raises(ValidationError):
        model.model_validate(
            {
                "ra_deg": 133.7951291667,
                "dec_deg": -7.2451472222,
                "frame": "ICRS",
                "fov_arcmin": 10,
                "collection": collection,
                "band_policy": "SAME_SUPPORTED_BAND",
            }
        )


@pytest.mark.parametrize(
    "coordinates",
    [
        {"ra_deg": 360, "dec_deg": 0},
        {"ra_deg": 0, "dec_deg": 90.001},
        {"ra_deg": 0, "dec_deg": -90.001},
    ],
)
def test_investigation_request_rejects_coordinates_outside_sky_bounds(
    coordinates: dict[str, float],
) -> None:
    model = contract("InvestigationRequest")
    payload = {
        "ra_deg": 133.0,
        "dec_deg": 10.0,
        "frame": "ICRS",
        "fov_arcmin": 10,
        "collection": "spherex_qr3",
        "band_policy": "SAME_SUPPORTED_BAND",
    }
    payload.update(coordinates)

    with pytest.raises(ValidationError):
        model.model_validate(payload)


def test_investigation_request_requires_positive_field_of_view() -> None:
    model = contract("InvestigationRequest")

    with pytest.raises(ValidationError):
        model.model_validate(
            {
                "ra_deg": 133.0,
                "dec_deg": 10.0,
                "frame": "ICRS",
                "fov_arcmin": 0,
                "band_policy": "SAME_SUPPORTED_BAND",
            }
        )


@pytest.mark.parametrize("fov_arcmin", [0.01665, 300.0001])
def test_investigation_request_rejects_unsupported_field_of_view(
    fov_arcmin: float,
) -> None:
    model = contract("InvestigationRequest")

    with pytest.raises(ValidationError):
        model.model_validate(
            {
                "ra_deg": 133.0,
                "dec_deg": 10.0,
                "frame": "ICRS",
                "fov_arcmin": fov_arcmin,
                "band_policy": "SAME_SUPPORTED_BAND",
            }
        )


def test_investigation_request_rejects_end_date_before_start_date() -> None:
    model = contract("InvestigationRequest")

    with pytest.raises(ValidationError):
        model.model_validate(
            {
                "ra_deg": 133.0,
                "dec_deg": 10.0,
                "frame": "ICRS",
                "fov_arcmin": 10,
                "band_policy": "SAME_SUPPORTED_BAND",
                "start_date": "2026-01-11",
                "end_date": "2026-01-10",
            }
        )


def test_target_defaults_to_unverified_and_usable_requires_a_report() -> None:
    model = contract("TargetRecord")
    target = model.model_validate(
        {
            "target_id": "WISE_0855",
            "name": "WISE 0855",
            "ra_deg": 133.7951291667,
            "dec_deg": -7.2451472222,
            "role": "NASA challenge target",
        }
    )

    assert target.coverage_status.value == "UNVERIFIED"
    assert target.verification_level.value == "UNVERIFIED"

    validated_target = model.model_validate(
        {
            "target_id": "WISE_0855",
            "name": "WISE 0855",
            "ra_deg": 133.7951291667,
            "dec_deg": -7.2451472222,
            "role": "NASA challenge target",
            "coverage_status": "USABLE",
            "validation_report_id": "coverage_wise_0855_v1",
        }
    )
    assert validated_target.validation_report_id == "coverage_wise_0855_v1"

    with pytest.raises(ValidationError):
        model.model_validate(
            {
                "target_id": "WISE_0855",
                "name": "WISE 0855",
                "ra_deg": 133.7951291667,
                "dec_deg": -7.2451472222,
                "role": "NASA challenge target",
                "coverage_status": "USABLE",
            }
        )


def test_observation_record_keeps_archive_identity_and_metadata() -> None:
    model = contract("ObservationRecord")
    observation = model.model_validate(
        {
            "observation_id": "obs_001",
            "access_url": "https://irsa.ipac.caltech.edu/ibe/data/spherex/dr1/level2/example.fits",
            "observed_at": "2026-01-10T00:00:00Z",
            "mjd": 61000.0,
            "band": "D2",
            "release": "DR1",
            "product": "MEF",
            "width": 29,
            "height": 29,
        }
    )

    assert observation.observation_id == "obs_001"
    assert observation.observed_at == datetime(2026, 1, 10, tzinfo=timezone.utc)
    assert observation.width == 29


def test_observation_record_can_carry_an_archive_checksum_for_retrieval() -> None:
    model = contract("ObservationRecord")
    observation = model.model_validate(
        {
            "observation_id": "obs_001",
            "remote_checksum": "md5:ba0cb5d912601e6ccb45b96245be6234",
        }
    )

    assert observation.remote_checksum == "md5:ba0cb5d912601e6ccb45b96245be6234"


def test_discovery_result_preserves_query_raw_response_and_partial_records() -> None:
    model = contract("DiscoveryResult")
    result = model.model_validate(
        {
            "status": "PARTIAL",
            "raw_query_parameters": {"ra": 269.452, "dec": 4.6934, "radius": 0.05},
            "raw_response_artifact_id": "art_query_001",
            "observations": [
                {
                    "observation_id": "obs_001",
                    "access_url": "https://irsa.ipac.caltech.edu/ibe/data/spherex/dr1/level2/one.fits",
                    "band": "D2",
                    "release": "DR1",
                    "product": "MEF",
                }
            ],
            "warnings": ["ARCHIVE_RETURNED_PARTIAL_RESULTS"],
        }
    )

    assert result.status.value == "PARTIAL"
    assert result.raw_query_parameters["ra"] == 269.452
    assert [item.observation_id for item in result.observations] == ["obs_001"]
    assert result.warnings == ["ARCHIVE_RETURNED_PARTIAL_RESULTS"]


def test_source_artifact_requires_a_sha256_digest_and_opaque_id() -> None:
    model = contract("SourceArtifact")
    artifact = model.model_validate(
        {
            "artifact_id": "art_source_001",
            "source_url": "https://irsa.ipac.caltech.edu/ibe/data/spherex/dr1/level2/one.fits",
            "observation_id": "obs_001",
            "release": "DR1",
            "size_bytes": 1024,
            "retrieved_at": "2026-11-14T00:00:00Z",
            "sha256": "a" * 64,
            "checksum_status": "COMPUTED",
            "retrieval_mode": "FULL_FILE",
        }
    )

    assert artifact.artifact_id == "art_source_001"
    assert artifact.sha256 == "a" * 64

    with pytest.raises(ValidationError):
        model.model_validate(
            {
                "artifact_id": "art_source_002",
                "source_url": "https://irsa.ipac.caltech.edu/ibe/data/spherex/dr1/level2/two.fits",
                "observation_id": "obs_002",
                "release": "DR1",
                "size_bytes": 1024,
                "retrieved_at": "2026-11-14T00:00:00Z",
                "sha256": "not-a-digest",
                "checksum_status": "COMPUTED",
                "retrieval_mode": "FULL_FILE",
            }
        )

    with pytest.raises(ValidationError):
        model.model_validate(
            {
                "artifact_id": "..\\private\\file.fits",
                "source_url": "https://irsa.ipac.caltech.edu/ibe/data/spherex/dr1/level2/three.fits",
                "observation_id": "obs_003",
                "release": "DR1",
                "size_bytes": 1024,
                "retrieved_at": "2026-11-14T00:00:00Z",
                "sha256": "b" * 64,
                "checksum_status": "COMPUTED",
                "retrieval_mode": "FULL_FILE",
            }
        )


def test_timeline_model_accepts_the_pdf_representative_response() -> None:
    model = contract("TimelineModel")
    timeline = model.model_validate(
        {
            "timeline_id": "timeline_001",
            "investigation_id": "inv_001",
            "series_status": "PARTIALLY_VALIDATED",
            "frames": [
                {
                    "observation_id": "obs_001",
                    "observed_at": "2026-01-10T00:00:00Z",
                    "band": "D2",
                    "release": "QR3",
                    "availability": "VALIDATED_WITH_WARNINGS",
                    "preview_artifact_id": "art_preview_001",
                    "warnings": ["PSF_METADATA_INCOMPLETE"],
                }
            ],
            "provenance_id": "prov_timeline_001",
        }
    )

    dumped = timeline.model_dump(mode="json")
    assert dumped["series_status"] == "PARTIALLY_VALIDATED"
    assert dumped["frames"][0]["warnings"] == ["PSF_METADATA_INCOMPLETE"]
    assert dumped["frames"][0]["preview_artifact_id"] == "art_preview_001"


def test_error_response_accepts_the_pdf_representative_envelope() -> None:
    model = contract("ErrorResponse")
    error = model.model_validate(
        {
            "error": {
                "code": "INSUFFICIENT_EPOCHS",
                "message": "Fewer than two validated compatible epochs are available for motion analysis.",
                "retryable": False,
                "details": {"validated_epochs": 1, "required_epochs": 2},
            },
            "request_id": "req_001",
            "schema_version": "3.0",
        }
    )

    assert error.error.code.value == "INSUFFICIENT_EPOCHS"
    assert error.error.details == {"validated_epochs": 1, "required_epochs": 2}
