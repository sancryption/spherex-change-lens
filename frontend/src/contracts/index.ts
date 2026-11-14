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
