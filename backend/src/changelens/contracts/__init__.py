"""Draft shared data contracts; INT-001 must freeze them before cross-team use."""

from __future__ import annotations

import re
from datetime import date, datetime
from enum import Enum
from typing import Annotated, Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    StringConstraints,
    field_validator,
    model_validator,
)


class ContractModel(BaseModel):
    """Base for strict JSON boundary models shared across workstreams."""

    model_config = ConfigDict(extra="forbid")


class ObservationAvailability(str, Enum):
    VALIDATED = "VALIDATED"
    VALIDATED_WITH_WARNINGS = "VALIDATED_WITH_WARNINGS"
    INVALID = "INVALID"
    UNAVAILABLE = "UNAVAILABLE"
    SYNTHETIC = "SYNTHETIC"


class RunStatus(str, Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    SUCCEEDED_WITH_WARNINGS = "SUCCEEDED_WITH_WARNINGS"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class EvidenceStatus(str, Enum):
    NO_RELIABLE_CHANGE = "NO_RELIABLE_CHANGE"
    POSSIBLE_POSITIONAL_MOVEMENT = "POSSIBLE_POSITIONAL_MOVEMENT"
    POSSIBLE_BRIGHTNESS_VARIATION = "POSSIBLE_BRIGHTNESS_VARIATION"
    ARTIFACT_RISK = "ARTIFACT_RISK"
    AMBIGUOUS = "AMBIGUOUS"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class AnalysisMode(str, Enum):
    MOTION = "MOTION"
    BRIGHTNESS = "BRIGHTNESS"


class TargetCoverageStatus(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    NO_COVERAGE = "NO_COVERAGE"
    DATA_FOUND = "DATA_FOUND"
    VALIDATED = "VALIDATED"
    USABLE = "USABLE"


class VerificationLevel(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    METADATA_ONLY = "METADATA_ONLY"
    FILE_VALIDATED = "FILE_VALIDATED"
    SCIENCE_VALIDATED = "SCIENCE_VALIDATED"


class DiscoveryStatus(str, Enum):
    COMPLETE = "COMPLETE"
    NO_RESULTS = "NO_RESULTS"
    PARTIAL = "PARTIAL"
    HTTP_4XX = "HTTP_4XX"
    HTTP_5XX = "HTTP_5XX"
    TIMEOUT = "TIMEOUT"


class ChecksumStatus(str, Enum):
    COMPUTED = "COMPUTED"
    MATCHED = "MATCHED"
    MISMATCH = "MISMATCH"
    NO_REMOTE_CHECKSUM = "NO_REMOTE_CHECKSUM"


class RetrievalMode(str, Enum):
    CUTOUT = "CUTOUT"
    FULL_FILE = "FULL_FILE"
    CACHE = "CACHE"


class SeriesStatus(str, Enum):
    EMPTY = "EMPTY"
    PARTIALLY_VALIDATED = "PARTIALLY_VALIDATED"
    VALIDATED = "VALIDATED"
    UNAVAILABLE = "UNAVAILABLE"


class ErrorCode(str, Enum):
    INVALID_COORDINATES = "INVALID_COORDINATES"
    NO_OBSERVATIONS = "NO_OBSERVATIONS"
    ARCHIVE_UNAVAILABLE = "ARCHIVE_UNAVAILABLE"
    RETRIEVAL_FAILED = "RETRIEVAL_FAILED"
    INVALID_FITS = "INVALID_FITS"
    INCOMPATIBLE_PRODUCT = "INCOMPATIBLE_PRODUCT"
    WCS_FAILURE = "WCS_FAILURE"
    NO_OVERLAP = "NO_OVERLAP"
    SOURCE_NOT_DETECTED = "SOURCE_NOT_DETECTED"
    SOURCE_NOT_MATCHED = "SOURCE_NOT_MATCHED"
    INSUFFICIENT_EPOCHS = "INSUFFICIENT_EPOCHS"
    ARTIFACT_NOT_FOUND = "ARTIFACT_NOT_FOUND"
    ANALYSIS_FAILED = "ANALYSIS_FAILED"


ArtifactId = Annotated[
    str,
    StringConstraints(
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$",
        min_length=1,
        max_length=128,
    ),
]
Sha256Digest = Annotated[str, StringConstraints(pattern=r"^[a-fA-F0-9]{64}$")]
RightAscensionDegrees = Annotated[float, Field(ge=0, lt=360)]
DeclinationDegrees = Annotated[float, Field(ge=-90, le=90)]


class TargetRecord(ContractModel):
    target_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    ra_deg: RightAscensionDegrees
    dec_deg: DeclinationDegrees
    frame: str = Field(default="ICRS", min_length=1)
    nasa_source_url: HttpUrl | None = None
    role: str = Field(min_length=1)
    expected_mode: AnalysisMode | None = None
    coverage_status: TargetCoverageStatus = TargetCoverageStatus.UNVERIFIED
    verification_level: VerificationLevel = VerificationLevel.UNVERIFIED
    validation_report_id: str | None = None
    notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def usable_requires_validation_report(self) -> TargetRecord:
        if (
            self.coverage_status is TargetCoverageStatus.USABLE
            and not self.validation_report_id
        ):
            raise ValueError("usable targets require a validation report ID")
        return self


class InvestigationRequest(ContractModel):
    target_name: str | None = None
    ra_deg: RightAscensionDegrees
    dec_deg: DeclinationDegrees
    frame: str = Field(default="ICRS", min_length=1)
    fov_arcmin: float = Field(ge=0.01666, le=300)
    collection: str | None = None
    band_policy: str = Field(default="SAME_SUPPORTED_BAND", min_length=1)
    start_date: date | None = None
    end_date: date | None = None

    @field_validator("collection")
    @classmethod
    def collection_is_literal_release_segment(cls, value: str | None) -> str | None:
        if value is None:
            return None
        collection = value.strip()
        normalized = collection.casefold()
        release = normalized.removeprefix("spherex_")
        if not release or not re.fullmatch(r"[a-z0-9-]+", release):
            raise ValueError("collection must be a literal SPHEREx release label")
        return collection

    @model_validator(mode="after")
    def date_range_is_ordered(self) -> InvestigationRequest:
        if self.start_date and self.end_date and self.start_date > self.end_date:
            raise ValueError("start_date must be on or before end_date")
        return self


class ObservationRecord(ContractModel):
    observation_id: str = Field(min_length=1)
    access_url: HttpUrl | None = None
    remote_checksum: str | None = None
    observed_at: datetime | None = None
    mjd: float | None = Field(default=None, ge=0)
    band: str | None = None
    release: str | None = None
    product: str | None = None
    width: int | None = Field(default=None, gt=0)
    height: int | None = Field(default=None, gt=0)
    footprint: dict[str, Any] | None = None
    availability: ObservationAvailability | None = None
    warnings: list[str] = Field(default_factory=list)


class DiscoveryResult(ContractModel):
    status: DiscoveryStatus
    raw_query_parameters: dict[str, Any] = Field(default_factory=dict)
    raw_response_artifact_id: ArtifactId | None = None
    observations: list[ObservationRecord] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    http_status: int | None = Field(default=None, ge=100, le=599)
    error_code: str | None = None


class SourceArtifact(ContractModel):
    artifact_id: ArtifactId
    source_url: HttpUrl
    observation_id: str = Field(min_length=1)
    release: str = Field(min_length=1)
    size_bytes: int = Field(gt=0)
    retrieved_at: datetime
    sha256: Sha256Digest
    checksum_status: ChecksumStatus
    retrieval_mode: RetrievalMode


class TimelineFrame(ContractModel):
    observation_id: str = Field(min_length=1)
    observed_at: datetime
    band: str = Field(min_length=1)
    release: str = Field(min_length=1)
    availability: ObservationAvailability
    preview_artifact_id: ArtifactId | None = None
    warnings: list[str] = Field(default_factory=list)


class TimelineModel(ContractModel):
    timeline_id: str = Field(min_length=1)
    investigation_id: str = Field(min_length=1)
    series_status: SeriesStatus
    frames: list[TimelineFrame] = Field(default_factory=list)
    provenance_id: str = Field(min_length=1)


class ErrorDetail(ContractModel):
    code: ErrorCode
    message: str = Field(min_length=1)
    retryable: bool
    details: dict[str, Any] = Field(default_factory=dict)


class ErrorResponse(ContractModel):
    error: ErrorDetail
    request_id: str = Field(min_length=1)
    schema_version: str = "3.0"


__all__ = [
    "AnalysisMode",
    "ArtifactId",
    "ChecksumStatus",
    "DeclinationDegrees",
    "DiscoveryResult",
    "DiscoveryStatus",
    "ErrorCode",
    "ErrorDetail",
    "ErrorResponse",
    "EvidenceStatus",
    "InvestigationRequest",
    "ObservationAvailability",
    "ObservationRecord",
    "RetrievalMode",
    "RightAscensionDegrees",
    "RunStatus",
    "SeriesStatus",
    "Sha256Digest",
    "SourceArtifact",
    "TargetCoverageStatus",
    "TargetRecord",
    "TimelineFrame",
    "TimelineModel",
    "VerificationLevel",
]
