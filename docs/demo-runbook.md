# Demonstration Runbook & Presentation Script

**Status:** `Pending implementation`  
**Purpose:** Standard operating procedure for testing, running, and presenting the SPHEREx Change Lens prototype.

---

## 1. Demo Flow Outline

### Stage 1: Target Selection & Discovery
- Open the application landing page.
- Select NASA Preset Target 1: **Barnard's Star** (High proper motion demonstration).
- Observe observation discovery: list of detected epochs returned from archive/mock cache.

### Stage 2: Observation & Timeline Playback
- Load multi-epoch timeline.
- Scrub through epochs or press "Play" to view changes in astronomical field.
- Toggle between raw science flux (`SCI`), variance map (`VAR`), and data quality flags (`MASK`).

### Stage 3: Difference Imaging & Source Analysis
- Select reference epoch (Epoch 0) and compare with subsequent epoch (Epoch $N$).
- Inspect difference image: observe positive/negative residual signature characteristic of moving point sources.
- Highlight centroid shift vector and calculated motion.

### Stage 4: Scientific Provenance Inspection
- Open Evidence Drawer.
- Review mathematical parameters: aperture radii, background subtraction mode, WCS alignment errors.
- Export scientific metadata manifest.

---

## 2. Dry-Run Verification Checklist
- [ ] Backend API healthy at `http://localhost:8000/docs`.
- [ ] Synthetic observation datasets available in `data/synthetic/`.
- [ ] Frontend loading without console errors or missing asset 404s.
- [ ] Graceful fallback displayed if live NASA archive connection is unavailable.
