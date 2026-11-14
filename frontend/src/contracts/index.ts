/**
 * Synchronized TypeScript contracts for SPHEREx Change Lens.
 *
 * Source of truth: backend/src/change_lens/contracts/__init__.py
 * Documentation: docs/api-contracts.md
 */

// --- Target Contracts ---

export interface TargetItem {
  target_id: string;
  name: string;
  ra: number;
  dec: number;
  category: string;
  description?: string;
  known_proper_motion?: Record<string, number>;
}

export interface TargetListResponse {
  targets: TargetItem[];
  total_count: number;
}

export interface TargetCoverageResponse {
  target_id: string;
  ra: number;
  dec: number;
  available_epochs_count: number;
  spectral_bands: string[];
  verification_status: "pending_verification" | "verified" | "no_coverage" | string;
}

// --- Query & Investigation Contracts ---

export interface CoordinateQueryRequest {
  ra: number;
  dec: number;
  radius_arcsec: number;
  /** Optional preset target_id from /targets */
  target_id?: string;
  /** Optional detector to play, "D1".."D6". Brown dwarfs: D5/D6. */
  detector?: string;
}

export interface InvestigationMetadata {
  investigation_id: string;
  target_name?: string;
  ra: number;
  dec: number;
  created_at_utc: string;
  status: string;
}

// --- Timeline & Epoch Contracts ---

export interface EpochDescriptor {
  epoch_id: string;
  observation_time_utc: string;
  mjd: number;
  band_id: string;
  preview_url?: string;
  variance_url?: string;
  flags_summary: Record<string, number>;
  quality_warning: boolean;
  /** Where the pixels came from. Always show it in the UI. */
  data_origin: "authentic_live" | "authentic_cached" | "synthetic" | string;
  /** Reason codes, e.g. "OUTSIDE_FOOTPRINT", "PSF_METADATA_INCOMPLETE" */
  warnings: string[];
  /** SPHEREx detector, "D1".."D6" */
  detector?: string | null;
  /** Archive release, e.g. "DR1", "QR3" */
  release?: string | null;
  /** Nominal [min, max] wavelength of the detector in microns */
  wavelength_range_um?: [number, number] | null;
}

export interface TimelineResponse {
  investigation_id: string;
  epochs: EpochDescriptor[];
  total_epochs: number;
}

// --- Difference Analysis Contracts ---

export interface DifferenceRequest {
  reference_epoch_id: string;
  target_epoch_id: string;
  subtraction_method: string;
}

export interface DifferenceResult {
  difference_id: string;
  reference_epoch_id: string;
  target_epoch_id: string;
  difference_preview_url?: string;
  difference_fits_url?: string;
  residual_flux_mean: number;
  residual_flux_std: number;
  detected_sources_count: number;
  warnings: string[];
}

// --- Scientific Evidence & Provenance Contracts ---

export interface EvidencePackage {
  investigation_id: string;
  target_ra: number;
  target_dec: number;
  computed_at_utc: string;
  software_versions: Record<string, string>;
  provenance_chain: Array<Record<string, unknown>>;
  light_curve_points: Array<Record<string, unknown>>;
  motion_vectors: Array<Record<string, unknown>>;
  quality_notices: string[];
}

// --- Error Contracts ---

export interface ErrorDetail {
  code: string; // e.g. INVALID_COORDINATES, NOT_FOUND, ARCHIVE_UNAVAILABLE
  message: string; // safe to show in the UI
  retryable: boolean;
  details: Record<string, unknown>;
}

/** Body of every non-2xx API response */
export interface ErrorResponse {
  error: ErrorDetail;
  request_id: string;
}

// --- Possible-mover screening: GET /api/v1/investigations/{id}/movers ---

export interface MoverCandidate {
  track_id: string;
  label: "possible_mover" | string;
  displacement_arcsec: number;
  baseline_days: number;
  uncertainty_arcsec: number;
  control_status: string;
  reason_codes: string[];
  limitations: string[];
}

export interface MoversResponse {
  investigation_id: string;
  /** COMPLETED | UNAVAILABLE (synthetic data, <2 frames) | FAILED */
  status: "COMPLETED" | "UNAVAILABLE" | "FAILED" | string;
  detector: string | null;
  frames_used: number;
  tracks_screened: number;
  /** motion_status -> count, e.g. { AMBIGUOUS: 7, ARTIFACT_RISK: 1 } */
  track_status_counts: Record<string, number>;
  /** Empty = no qualifying possible movers. Never call these discoveries. */
  candidates: MoverCandidate[];
  warnings: string[];
  limitations: string[];
  method: Record<string, unknown>;
}

/** SCI-011 difference (later - earlier frame). GET /investigations/{id}/evidence */
export interface DifferenceSummary {
  /** AVAILABLE | REJECTED (incompatible frames) | UNAVAILABLE */
  status: "AVAILABLE" | "REJECTED" | "UNAVAILABLE" | string;
  earlier_epoch_id: string | null;
  later_epoch_id: string | null;
  earlier_mjd: number | null;
  later_mjd: number | null;
  subtraction_order: string;
  unit: string | null;
  variance_status: string | null;
  valid_pixel_count: number;
  /** Frame-wide extremes, not source measurements */
  minimum: number | null;
  maximum: number | null;
  /** North-up PNG of D/sqrt(Var): white = brighter, black = fainter, grey = no change/masked */
  image_url: string | null;
  reason_codes: string[];
  warnings: string[];
}

/** SCI-012 evidence for one track; motion and brightness stay separate */
export interface TrackEvidenceSummary {
  track_id: string;
  statuses: string[];
  motion_status: string;
  brightness_status: string;
  reason_codes: string[];
  limitations: string[];
}

export interface EvidenceResponse {
  investigation_id: string;
  /** COMPLETED | UNAVAILABLE (synthetic data, <2 frames) | FAILED */
  status: "COMPLETED" | "UNAVAILABLE" | "FAILED" | string;
  detector: string | null;
  frames_used: number;
  tracks_total: number;
  /** summary status -> number of tracks carrying it */
  status_counts: Record<string, number>;
  /** tracks with any status other than NO_RELIABLE_CHANGE (max 50) */
  notable_tracks: TrackEvidenceSummary[];
  difference: DifferenceSummary | null;
  warnings: string[];
  limitations: string[];
  method: Record<string, unknown>;
}
