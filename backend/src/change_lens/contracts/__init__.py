"""Canonical Pydantic v2 API contracts for SPHEREx Change Lens.

Single source of truth for API schemas across backend, frontend, and docs.
"""

from typing import Any

from pydantic import BaseModel, Field

# --- Target Contracts ---

class TargetItem(BaseModel):
    """Metadata representation for an astronomical target."""

    target_id: str = Field(..., description="Unique slug or identifier for target")
    name: str = Field(..., description="Display name of target")
    ra: float = Field(..., description="Right Ascension in decimal degrees (J2000)")
    dec: float = Field(..., description="Declination in decimal degrees (J2000)")
    category: str = Field(..., description="Classification category (e.g. standard_star, brown_dwarf, yso)")
    description: str | None = Field(None, description="Brief scientific description")
    known_proper_motion: dict[str, float] | None = Field(
        None, description="Known proper motion components if established"
    )


class TargetListResponse(BaseModel):
    """Response payload listing reference targets."""

    targets: list[TargetItem]
    total_count: int


class TargetCoverageResponse(BaseModel):
    """Response payload indicating archival coverage for a target."""

    target_id: str
    ra: float
    dec: float
    available_epochs_count: int = Field(0, description="Number of discovered observation epochs")
    spectral_bands: list[str] = Field(default_factory=list, description="SPHEREx band identifiers")
    verification_status: str = Field(
        "pending_verification",
        description="Status of archive verification ('pending_verification', 'verified', 'no_coverage')",
    )


# --- Query & Investigation Contracts ---

class CoordinateQueryRequest(BaseModel):
    """Request payload for custom celestial coordinates cone query."""

    ra: float = Field(..., ge=0.0, lt=360.0, description="Right Ascension in decimal degrees")
    dec: float = Field(..., ge=-90.0, le=90.0, description="Declination in decimal degrees")
    radius_arcsec: float = Field(30.0, gt=0.0, le=3600.0, description="Search cone radius in arcseconds")


class InvestigationMetadata(BaseModel):
    """Summary descriptor for an active or queried investigation."""

    investigation_id: str = Field(..., description="Unique identifier for investigation session")
    target_name: str | None = None
    ra: float
    dec: float
    created_at_utc: str
    status: str = Field("initialized", description="Current status of investigation")


# --- Timeline & Epoch Contracts ---

class EpochDescriptor(BaseModel):
    """Descriptor for a single temporal observation epoch."""

    epoch_id: str
    observation_time_utc: str
    mjd: float = Field(..., description="Modified Julian Date")
    band_id: str
    preview_url: str | None = None
    variance_url: str | None = None
    flags_summary: dict[str, int] = Field(default_factory=dict)
    quality_warning: bool = False


class TimelineResponse(BaseModel):
    """Chronological sequence of observation epochs."""

    investigation_id: str
    epochs: list[EpochDescriptor]
    total_epochs: int


# --- Difference Analysis Contracts ---

class DifferenceRequest(BaseModel):
    """Parameters required to compute or retrieve a difference image."""

    reference_epoch_id: str
    target_epoch_id: str
    subtraction_method: str = Field("standard_median", description="Subtraction and background matching method")


class DifferenceResult(BaseModel):
    """Result of difference image computation."""

    difference_id: str
    reference_epoch_id: str
    target_epoch_id: str
    difference_preview_url: str | None = None
    difference_fits_url: str | None = None
    residual_flux_mean: float = 0.0
    residual_flux_std: float = 0.0
    detected_sources_count: int = 0
    warnings: list[str] = Field(default_factory=list)


# --- Scientific Evidence & Provenance Contracts ---

class EvidencePackage(BaseModel):
    """Comprehensive scientific evidence and provenance package."""

    investigation_id: str
    target_ra: float
    target_dec: float
    computed_at_utc: str
    software_versions: dict[str, str] = Field(default_factory=dict)
    provenance_chain: list[dict[str, Any]] = Field(default_factory=list)
    light_curve_points: list[dict[str, Any]] = Field(default_factory=list)
    motion_vectors: list[dict[str, Any]] = Field(default_factory=list)
    quality_notices: list[str] = Field(default_factory=list)
