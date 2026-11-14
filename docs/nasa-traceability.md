# NASA Space Apps Challenge Traceability Matrix

**Status:** `Pending implementation` & `Pending verification`  
**Reference:** 2026 NASA Space Apps Challenge - SPHEREx Temporal Analysis

---

## 1. Objective Traceability
This matrix tracks the mapping between the NASA Space Apps Challenge guidelines and the SPHEREx Change Lens architectural components.

| NASA Requirement / Goal | Architecture Component | Module / Directory | Current Status |
|---|---|---|---|
| Select 5 named NASA targets or custom RA/Dec | Target Management | `change_lens.targets`, `features/target-selection` | Pending implementation |
| Discover & retrieve SPHEREx observations | Archive Retrieval | `change_lens.archive`, `change_lens.retrieval` | Pending implementation |
| Multi-epoch chronological viewing ("video-like") | Timeline & Viewer | `change_lens.timeline`, `features/timeline`, `features/image-viewer` | Pending implementation |
| Validate FITS, WCS, flags, variance, metadata | FITS & Flag Pipeline | `change_lens.fits`, `change_lens.pipeline.masks` | Pending implementation |
| Measure source movement & brightness variation | Scientific Pipeline | `change_lens.pipeline.motion`, `change_lens.pipeline.brightness` | Pending implementation |
| Compute difference images & uncertainty | Difference Engine | `change_lens.pipeline.difference` | Pending implementation |
| Transparent scientific evidence & provenance | Provenance & Evidence | `change_lens.provenance`, `docs/provenance-policy.md` | Pending implementation |

## 2. NASA Data Product Verification
- Data products must strictly trace to published SPHEREx Level 2 or Level 3 data formats.
- Instrument flags and calibration nuances must adhere to official SPHEREx documentation released via IPAC/IRSA.
- Verification status of live archive endpoints: **Pending verification**.
