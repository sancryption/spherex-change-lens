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

---

## 3. Implemented in the backend (BE-001..004, BE-006)

All routes below are live under `/api/v1`. Interactive docs: `http://localhost:8000/docs`.

| Method | Path | Request | Response |
|---|---|---|---|
| GET | `/health` | – | status, archive mode, db |
| GET | `/api/v1/targets` | – | `TargetListResponse` |
| GET | `/api/v1/targets/{target_id}/coverage` | – | `TargetCoverageResponse` |
| POST | `/api/v1/investigations/query` | `CoordinateQueryRequest` (`ra`, `dec`, `radius_arcsec`, optional `target_id`) | `InvestigationMetadata` (201) |
| GET | `/api/v1/investigations/{investigation_id}` | – | `InvestigationMetadata` |
| GET | `/api/v1/investigations/{investigation_id}/timeline` | – | `TimelineResponse` |
| GET | `/api/v1/artifacts/{artifact_id}/preview` | – | PNG bytes. FE gets the URL from `EpochDescriptor.preview_url`. |

### Additions to the scaffold contracts (backward-compatible)
- `CoordinateQueryRequest.target_id` (optional): which preset the query came from.
- `EpochDescriptor.data_origin`: `authentic_live` / `authentic_cached` / `synthetic`. **The UI must always show it.**
- `EpochDescriptor.warnings`: reason codes. Frames that fail are kept in the timeline with `quality_warning=true` and may have `preview_url=null`. FE shows a "no preview" state, not a black box.
- `ErrorResponse` / `ErrorDetail`: every non-2xx response is `{ "error": { code, message, retryable, details }, "request_id" }`. Validation errors use `INVALID_COORDINATES` (ra/dec) or `INVALID_REQUEST`.

### Mock archive mode
With `SPHEREX_ARCHIVE_MOCK_MODE=true` (the default), every query returns 5 **synthetic** epochs (one outside the footprint, one with a PSF warning) and generated PNGs stamped "SYNTHETIC". This lets FE build the player before real data exists. Mock coverage is never reported as `verified`.

### For DATA: plugging in the real archive
Implement the `ArchiveClient` protocol in `backend/src/change_lens/archive/base.py` (a `discover(ra, dec, radius_arcsec) -> DiscoveryResult` method), then return it from `_default_archive()` in `main.py` when mock mode is off. The backend handles sorting, deduplication, storage, artifact IDs and serving.

### Real archive mode (INT-003)
Set `SPHEREX_ARCHIVE_MOCK_MODE=false` to serve real SPHEREx data. `change_lens.archive.irsa.IrsaArchiveClient` wraps the DATA code in `changelens.data` (`discover` → `retrieve` → `generate_preview`) without changing it:

- **One detector + one release per timeline.** The group with the most observations is played. Mixing detectors (wavelengths) or releases would look like change.
- **Up to `SPHEREX_MAX_FRAMES` epochs (default 8)**, sampled evenly in time across all visits.
- **North-up alignment.** SPHEREx cutouts arrive in detector orientation, and visits can be rotated about 180° relative to each other. Every preview is reprojected onto one shared north-up TAN grid (≈6.15″/px) centred on the query position, so stars stay fixed between frames.
- **FOV** = 2 × `radius_arcsec`, clamped to 10–30 arcmin.
- **Rendering:** previews are made from the float FITS cutout. Each one is reprojected north-up, has a smooth background subtracted (large median filter, which removes stray-light gradients), and is stretched in units of its own noise (−2σ → black, +60σ → white, asinh). Brightness is therefore comparable between frames. Cutouts are downloaded about 1.42× wider so that rotated frames still fill the square.
- **Target position / crosshair:** the image centre is exactly the queried RA/Dec in every frame. The frontend should draw the crosshair as an overlay at the centre, not burn it into the PNG, so it can be toggled and never hides the pixels being inspected.
- **Per-frame labels:** `detector` (`D1`–`D6`), `release` (`DR1`, `QR3`, …) and `wavelength_range_um` (nominal detector bandpass) are on every `EpochDescriptor`.
- **Labels:** `data_origin` is `authentic_live` or `authentic_cached`. Every frame carries `SCIENCE_AND_WCS_VALIDATION_PENDING` until SCI validation exists.
- **Speed:** the first query for a position takes minutes (TAP discovery plus cutout downloads). Repeat queries are instant (in-process discovery cache plus on-disk FITS cache). Pre-warm demo targets before presenting.
- **Errors:** IRSA timeout, 5xx or connection failure → `503 ARCHIVE_UNAVAILABLE` (retryable). No coverage → empty timeline, `status="no_coverage"`.
- **High proper motion targets:** registry coordinates are J2000, so Barnard's Star appears about 4.5′ north of centre in 2025–26 data.
