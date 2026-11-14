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
    target_id: str | None = Field(
        None, description="Optional preset target_id (from /targets) this query was started from"
    )
    detector: str | None = Field(
        None,
        pattern=r"^D[1-6]$",
        description="Optional SPHEREx detector to play ('D1'..'D6'). Default: the one with most data. "
        "Cold brown dwarfs are brightest in D5/D6 (~4-5 um).",
    )


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
    data_origin: str = Field(
        "synthetic",
        description="Where the pixels came from: 'authentic_live', 'authentic_cached' or 'synthetic'. "
        "Always shown in the UI.",
    )
    warnings: list[str] = Field(default_factory=list, description="Reason codes for quality issues")
    detector: str | None = Field(None, description="SPHEREx detector, 'D1'..'D6'")
    release: str | None = Field(None, description="Archive release, e.g. 'DR1', 'QR3'")
    wavelength_range_um: list[float] | None = Field(
        None, description="Nominal [min, max] wavelength of the detector in microns"
    )


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


# --- Error Contracts ---

class ErrorDetail(BaseModel):
    """Machine-readable error body."""

    code: str = Field(..., description="Stable error code, e.g. INVALID_COORDINATES, NOT_FOUND")
    message: str = Field(..., description="Human-readable message, safe to show in the UI")
    retryable: bool = False
    details: dict[str, Any] = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    """Envelope returned for every non-2xx API response."""

    error: ErrorDetail
    request_id: str


# --- Possible-mover screening (SCI phase 3 exposed by BE) ---

class MoverCandidate(BaseModel):
    """A track that passed SCI motion screening and controls. Screening only, not a discovery."""

    track_id: str
    label: str = Field("possible_mover", description="Always 'possible_mover'")
    displacement_arcsec: float
    baseline_days: float
    uncertainty_arcsec: float
    control_status: str
    reason_codes: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class MoversResponse(BaseModel):
    """Result of running the SCI pipeline on an investigation's timeline frames."""

    investigation_id: str
    status: str = Field(
        ..., description="'COMPLETED', 'UNAVAILABLE' (e.g. synthetic data, <2 frames) or 'FAILED'"
    )
    detector: str | None = None
    frames_used: int = 0
    tracks_screened: int = 0
    track_status_counts: dict[str, int] = Field(
        default_factory=dict, description="motion_status -> count, e.g. AMBIGUOUS, ARTIFACT_RISK"
    )
    candidates: list[MoverCandidate] = Field(
        default_factory=list, description="Empty list = no qualifying possible movers"
    )
    warnings: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    method: dict[str, Any] = Field(default_factory=dict, description="Policies and parameters used")


class DifferenceSummary(BaseModel):
    """SCI-011 difference product (later - earlier frame), summarized for the UI."""

    status: str = Field(..., description="'AVAILABLE', 'REJECTED' (incompatible frames) or 'UNAVAILABLE'")
    earlier_epoch_id: str | None = None
    later_epoch_id: str | None = None
    earlier_mjd: float | None = None
    later_mjd: float | None = None
    subtraction_order: str = "later_epoch - earlier_epoch"
    unit: str | None = None
    variance_status: str | None = None
    valid_pixel_count: int = 0
    minimum: float | None = Field(None, description="Frame-wide extreme, not a source measurement")
    maximum: float | None = Field(None, description="Frame-wide extreme, not a source measurement")
    image_url: str | None = Field(
        None,
        description="PNG of D/sqrt(Var(D)) clipped to +/-5: black = fainter, white = brighter, "
        "mid-grey = no change or masked",
    )
    reason_codes: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class TrackEvidenceSummary(BaseModel):
    """SCI-012 evidence for one source track (motion and brightness kept separate)."""

    track_id: str
    statuses: list[str] = Field(..., description="Summary labels, motion first then brightness")
    motion_status: str
    brightness_status: str
    reason_codes: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class EvidenceResponse(BaseModel):
    """SCI phase 4 evidence synthesis for an investigation's timeline frames."""

    investigation_id: str
    status: str = Field(
        ..., description="'COMPLETED', 'UNAVAILABLE' (e.g. synthetic data, <2 frames) or 'FAILED'"
    )
    detector: str | None = None
    frames_used: int = 0
    tracks_total: int = 0
    status_counts: dict[str, int] = Field(
        default_factory=dict, description="summary status -> number of tracks carrying it"
    )
    notable_tracks: list[TrackEvidenceSummary] = Field(
        default_factory=list,
        description="Tracks with any status other than NO_RELIABLE_CHANGE (capped, see warnings)",
    )
    difference: DifferenceSummary | None = None
    warnings: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    method: dict[str, Any] = Field(default_factory=dict)
