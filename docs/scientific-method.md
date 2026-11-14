# Scientific Methodology & Analysis Procedures

**Status:** `Pending implementation`  
**Workstream:** SCI (Scientific Processing & Analysis)

---

## 1. Scientific Pipeline Overview
The scientific engine in SPHEREx Change Lens processes time-series spectral imaging through an explicit, reproducible analytical pipeline:

```
[Raw Multi-Extension FITS]
         │
         ▼
[WCS Reprojection & Coordinate Alignment]
         │
         ▼
[Masking & Quality Filtering (Flags/Variance)]
         │
         ├───────────────────────────────┐
         ▼                               ▼
[Difference Imaging (Epoch - Ref)]   [Photometric Extraction (Aperture / PSF)]
         │                               │
         ▼                               ▼
[Residual / Motion Detection]        [Temporal Light Curve & Variability Test]
         │                               │
         └───────────────┬───────────────┘
                         ▼
             [Evidence Synthesis & Provenance]
```

## 2. Methodology Outlines

### 2.1 Spatial Alignment & Reprojection
- Use `astropy.wcs` and `reproject` to align subsequent epochs onto a common celestial grid (WCS) centered on the target coordinates.
- Interpolation method: Bi-linear or Lanczos interpolation (`reproject_interp`), with explicit tracking of pixel area distortion.

### 2.2 Variance Propagation
- Propagate error arrays (SPHEREx `VAR` extension) through every mathematical transformation:
  $$\sigma_{\text{diff}}^2 = \sigma_{\text{epoch}}^2 + \sigma_{\text{ref}}^2$$

### 2.3 Difference Imaging
- Reference epoch selection: Earliest unflagged epoch or median composite image across unflagged epochs.
- Background matching and flux scaling before subtraction to prevent false dipole residuals.

### 2.4 Photometry & Brightness Change
- Target flux extracted using `photutils.aperture.CircularAperture` or PSF modeling with local background subtraction.
- Compute normalized variability index:
  $$\Delta m = -2.5 \log_{10}(F_{t} / F_{\text{ref}})$$

### 2.5 Motion & Astrometry
- Measure source centroid per epoch using 2D Gaussian fitting or intensity moments.
- Compute apparent angular velocity vector ($\mu_{\alpha} \cos \delta, \mu_{\delta}$) and compare with catalogue proper motions.
