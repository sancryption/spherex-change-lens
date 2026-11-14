# Scientific Provenance & Auditability Policy

**Status:** `Pending implementation`  
**Workstream:** SCI / BE / DATA

---

## 1. Core Principle
Every calculated metric, difference image, and light curve shown in SPHEREx Change Lens must be fully traceable back to raw archive products, library versions, algorithm parameters, and mathematical transformations.

## 2. Provenance Record Structure
Every investigation record stored in the backend and delivered to the frontend Evidence Drawer must contain:
1. **Input Identifiers:** Exact SPHEREx MEF file URLs, observation IDs, band designations, and SHA-256 hashes.
2. **Execution Metadata:** Timestamp (UTC), software version, Python/Astropy/Photutils dependency versions.
3. **Algorithm Parameters:** Aperture radius, background annulus size, reproject interpolation mode, threshold sigmas.
4. **Processing Log:** Chronological record of steps applied (Alignment -> Masking -> Subtraction -> Extraction).
5. **Quality Warnings:** Any flagged anomalies, saturated pixels in aperture, or WCS astrometric uncertainties.

## 3. Evidence Drawer Export
Users must be able to export the complete scientific provenance package as a JSON manifest alongside exported FITS and PNG difference products.
