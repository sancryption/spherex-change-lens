# API Contracts and Schema Specification

**Status:** `Scaffold Defined` - Schema Source of Truth  
**Authority:** `backend/src/change_lens/contracts` (Pydantic v2 Models)

---

## 1. Single Source of Truth
- **Backend Canonical Models:** `backend/src/change_lens/contracts/`
- **Frontend Synchronized Types:** `frontend/src/contracts/`
- **Documentation Reference:** This file (`docs/api-contracts.md`)

Frontend types are strictly generated or maintained in alignment with backend Pydantic definitions. Divergent custom frontend types are prohibited.

---

## 2. Core Endpoint Specifications

### 2.1 Target Inquiries
- `GET /api/v1/targets`
  - Returns the list of standard NASA reference targets and their known metadata.
  - Response: `TargetListResponse`
- `GET /api/v1/targets/{target_id}/coverage`
  - Returns observed epochs, bands, and retrieval status.
  - Response: `TargetCoverageResponse`

### 2.2 Coordinate Query
- `POST /api/v1/investigations/query`
  - Submits a custom RA/Dec coordinate cone query.
  - Request: `CoordinateQueryRequest` (`ra: float`, `dec: float`, `radius_arcsec: float`)
  - Response: `InvestigationMetadata`

### 2.3 Timeline & Observations
- `GET /api/v1/investigations/{investigation_id}/timeline`
  - Returns chronological epochs with preview thumbnail URLs, timestamps, and quality flags.
  - Response: `TimelineResponse`

### 2.4 Difference & Analysis
- `POST /api/v1/investigations/{investigation_id}/difference`
  - Triggers or retrieves difference computation between two epochs.
  - Request: `DifferenceRequest` (`reference_epoch_id: str`, `target_epoch_id: str`)
  - Response: `DifferenceResult`

### 2.5 Scientific Evidence
- `GET /api/v1/investigations/{investigation_id}/evidence`
  - Retrieves complete provenance, light curve data, motion vectors, and calibration details.
  - Response: `EvidencePackage`
