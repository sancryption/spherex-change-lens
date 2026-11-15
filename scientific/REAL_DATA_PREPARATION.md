# Real-data SCI preparation: current result

The September 30–October 1, 2025 Barnard's Star pair remains **REJECTED**.
Official product retrieval works. UUID identity verification remains incomplete.
Corrected detector-coordinate diagnostics contradict the earlier wavelength
compatibility claim.

## Official retrieval

SIA supplied the working publisher IDs:
- `ivo://irsa.ipac/spherex_dr1?2025W40_1A_0441_1/D1`
- `ivo://irsa.ipac/spherex_dr1?2025W40_1A_0500_1/D1`

These work at `https://irsa.ipac.caltech.edu/datalink/links/spherex` using the ID
parameter. Substituting cached plane UUIDs into publisher IDs was incorrect.
The service sometimes returned transient 502s; correct IDs subsequently worked.
The parser uses FIELD names (including lowercase `id`), not the `col_*` FIELD IDs.

Both responses list the same 15 calibration products with exact S3 keys in
`nasa-irsa-spherex` (us-east-1). All 15 products and both parent science images
were downloaded, checked against DataLink byte lengths, and SHA-256 hashed.
See `calibration_retrieval.json`. Downloads and raw responses remain Git-ignored
in `data/derived/calibration_candidates/`. A small DataLink XML fixture is tested.

Retrieval is not UUID certification. None of the calibration FITS headers or
YAML/ECSV files contains a UUID. DataLink rows identify the observation and
product name, not the calibration UUID. Exact artifact/identity TAP and calibration
SIA queries timed out or returned 502. No UUID was inferred from a filename.
`initial_distortion_table` and `sband_mnemonics` are absent from the returned links.

## Corrected mapping and spectral diagnostics

Each cutout exactly equals its official parent in IMAGE, VARIANCE, FLAGS and ZODI
at native coordinates recovered through celestial WCS. Zero-based detector ranges:

| Observation | x | y |
| --- | --- | --- |
| September 30 | 1469–1606 | 1359–1496 |
| October 1 | 551–688 | 246–383 |

The observation-linked `spectral_wcs_D1_spx_cal-swcs-v5-2026-191.fits` gives:

| Observation | Central wavelength range (µm) | Whole-cutout bandwidth interval envelope (µm) |
| --- | --- | --- |
| September 30 | 0.822605–0.847616 | 0.812220–0.858438 |
| October 1 | 1.031557–1.062247 | 1.017694–1.076636 |

Parent spectral WCS independently gives central wavelengths 0.823009–0.847891
and 1.032056–1.062120 µm using core spectral transforms without celestial SIP.

The 50-pixel conservative aligned zero-FLAGS region has 50 disjoint interval
pixels, minimum overlap 0, maximum contributor wavelength difference 0.215991 µm,
and maximum weighted-mean difference 0.215884 µm. These remain candidate
diagnostics because calibration UUID identity is unresolved.

The earlier 0.000184 µm screening result must not approve this pair. The cutouts
retain full-detector spectral lookup coordinates and unshifted alternate
coordinate keywords; local cutout coordinates do not locate the target on that
detector grid. Other previously screened pairs have not been re-audited here.

## Implementation

- `calibration.py`: official S3 URL support, paginated anonymous listing, correct
  DataLink schema, observation-scoped discovery, hashes and strict UUID checks.
  Exact calibration-ID associations are supported but were not returned by IRSA.
- `calibration_mapping.py`: verified integer celestial mapping and exact
  four-layer parent/subset equality, with file hashes.
- `propagation.py`: sparse operators matching SCI-003, individual spectral
  contributors retained through alignment, all-contributor interval checks and
  disjoint-interval rejection without an invented numerical acceptance threshold.
- Statistical covariance follows the same operators. Background subtraction uses
  L = A - (A 1) b^T, retaining correlations between fitted background and science
  pixels. Named nuisance modes accept supplied calibration/ZODI/PSF perturbations.
  Explicit shared modes retain cross-epoch covariance in the difference.
- The audit passes spectral rejection evidence into pair preparation and records
  statistical-only covariance diagnostics. It never treats missing uncertainties
  as measured zero or promotes raw subtraction to a scientific result.

## Exact remaining blockers and implementation boundary

1. Corrected-coordinate diagnostics show disjoint spectral intervals for this
   selected pair. Background subtraction or PSF matching cannot fix that.
2. HISTORY UUID-to-product identities remain unverified; two dependencies lack
   DataLink products. Identical UUIDs between observations are insufficient.
3. Measurement/source-free regions, background adequacy and mask policy need
   scientific review. The 50-pixel audit region is not an approved science aperture.
4. ZODI scaling supplies ZodiScale_err but no complete model-error covariance or
   cross-wavelength/epoch correlations. Calibration and effective-PSF uncertainty
   inputs and post-alignment PSF evidence remain missing.
5. Propagation mathematics is implemented and tested, but a complete certified
   covariance/response product is not wired into final real-data acceptance.
   PairPreparation still enforces its capability blockers. No successful real-pair
   certification path is claimed; editing serialized reasons cannot enable one.

CALVER was not fabricated. No acceptance tolerance was chosen to force success.
Both protected untracked directories and unrelated frontend files were untouched.

## Reproduction and validation

From C:\NASA:

```powershell
.venv/Scripts/python.exe scripts/retrieve_barnard_calibrations.py
.venv/Scripts/python.exe scripts/audit_barnard_preparation.py --output scientific/barnard_preparation_audit.json
.venv/Scripts/python.exe -m pytest backend/tests/scientific -q
.venv/Scripts/python.exe -m pytest backend/tests/integration/test_evidence_api.py -q
```

331 scientific tests and 7 evidence API tests passed. Coverage includes the real
DataLink schema, unresolved UUIDs, mirror tampering, pagination, cutout mapping,
alignment/variance parity, off-diagonal covariance, background correlations,
shared-mode cancellation and disjoint intervals. Existing invalid-WCS/truncated
FITS fixtures retain expected warnings. API tests ran outside the sandbox to
avoid the previously diagnosed Windows local socket-pair stall.

Official references:
- [IRSA cloud access](https://irsa.ipac.caltech.edu/cloud_access/)
- [IRSA DataLink calibration access](https://irsa.ipac.caltech.edu/onlinehelp/spherex/spherex/visualization.html)
- [IRSA calibration product definitions](https://caltech-ipac.github.io/spherex-archive-documentation/spherex-data-products/)
