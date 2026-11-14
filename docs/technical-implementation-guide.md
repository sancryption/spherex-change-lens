# Technical Implementation Guide

**Status:** `Pending implementation`  
**Target Workstreams:** BE, FE, SCI, DATA

---

## 1. Scope & Purpose
This guide outlines the technical implementation steps required to transition SPHEREx Change Lens from the scaffold foundation to functional modules, without skipping scientific rigor or architectural boundaries.

## 2. Workstream Implementation Steps

### 2.1 DATA Workstream (SPHEREx Archive & Ingestion)
- **Step 1:** Implement IRSA/SPHEREx API client in `change_lens.archive`.
- **Step 2:** Formulate cone-search queries for target positions.
- **Step 3:** Handle retrieval with download throttling, backoff, and integrity verification.
- **Step 4:** Implement MEF (Multi-Extension FITS) parser: extract Science (`SCI`), Variance (`VAR`), and Flag/Mask (`MASK`) arrays.

### 2.2 SCI Workstream (Scientific Pipeline)
- **Step 1:** Implement WCS parsing and spatial alignment via `astropy.wcs` and `reproject.reproject_interp`.
- **Step 2:** Apply mask propagation according to the flag policy (`docs/flag-policy.md`).
- **Step 3:** Implement background modeling and difference image generation (`pipeline/difference.py`).
- **Step 4:** Configure source detection using `photutils` and centroid estimation (`pipeline/detection.py`, `pipeline/centroid.py`).
- **Step 5:** Compute motion trajectories and light curves with error propagation.

### 2.3 BE Workstream (Backend Services)
- **Step 1:** Implement route handlers in `change_lens.api.routes` corresponding to Pydantic contracts.
- **Step 2:** Wire SQLite database models in `change_lens.storage` for caching metadata and tracking async investigation jobs.
- **Step 3:** Connect pipeline executions to the job scheduler in `change_lens.jobs`.

### 2.4 FE Workstream (Frontend Application)
- **Step 1:** Implement target search and NASA preset target selector (`features/target-selection`).
- **Step 2:** Build timeline scrubber with epoch controls (`features/timeline`).
- **Step 3:** Build multi-epoch image viewer with color scale stretching (Linear, Log, Asinh) and flag overlay toggles.
- **Step 4:** Implement difference viewing mode and scientific evidence drawer.

## 3. Integration & Testing Gates
- Verification of contract consistency across Python Pydantic models and TypeScript types.
- Scientific regression test execution against synthetic FITS inputs in `data/synthetic/`.
