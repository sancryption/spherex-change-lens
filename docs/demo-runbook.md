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

---

## Pre-warm before presenting (real SPHEREx mode)

The first query for a position takes **minutes** (IRSA discovery, cutout downloads, previews, SCI screening). Do it ahead of time **on the machine that will run the backend during the demo**:

```bash
pip install -e "backend/[dev]"
python scripts/prewarm_demo.py        # or: make prewarm   (~30-50 min for all 5 targets)
```

- It fetches real frames and runs mover screening plus evidence synthesis (difference image) for all 5 NASA targets, using the frontend's default parameters (`radius_arcsec=60`, default detector).
- Everything is stored on disk (`data/cached_mefs`, `data/previews`, `data/discovery_cache`, `data/mover_cache`, `data/evidence_cache`, `data/derived/differences`). After that, preset targets load **instantly**, even after a server restart.
- Re-running is safe: warm targets are skipped in seconds. One target failing (e.g. an IRSA timeout) does not stop the others; just re-run.
- Optional extra: `python scripts/prewarm_demo.py --detector D6 --targets wise-0855` (D6 ≈ 4.4–5.0 µm, where cold brown dwarfs are brightest).

Then start the API in real mode:

```bash
SPHEREX_ARCHIVE_MOCK_MODE=false uvicorn change_lens.main:app --port 8000
```

**Demo order suggestion:** lead with **Barnard's Star**. It is bright and sits about 4.5′ north of its J2000 position because of its proper motion, which is visible in the aligned frames. Show **WISE 0855** as the honest case: SPHEREx coverage exists, but the object is not detectable and the SCI screening reports no candidates.
