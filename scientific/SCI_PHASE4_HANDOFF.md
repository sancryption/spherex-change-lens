# SCI Phase 4 backend handoff

Implemented in `change_lens.pipeline.difference` and `change_lens.pipeline.evidence`.
No shared contracts or routes are changed. These are Python SCI-local dataclasses,
not JSON response schemas. The legacy untyped scaffold entry points remain disabled;
the backend should use the typed interfaces below.

## Imports and signatures

```python
from change_lens.pipeline.alignment import AlignedFrame
from change_lens.pipeline.difference import DifferenceResult, compute_difference
from change_lens.pipeline.evidence import EvidenceResult, synthesize_evidence
from change_lens.pipeline.phase3 import Phase3Result

def compute_difference(earlier: AlignedFrame, later: AlignedFrame) -> DifferenceResult: ...

def synthesize_evidence(
    phase3: Phase3Result, *, differences: tuple[DifferenceResult, ...] = ()
) -> EvidenceResult: ...
```

## Required inputs and minimal usage

Supply the existing SCI-003 `AlignedFrame` objects from a successful Phase 2 run,
and the final `run_phase3` result. Frames must have matching certified
`plane_identity` (band, product, spectral_plane, release), exact unit scale,
known identical `validation.metadata.CALVER`, passed validation, distinct
observation IDs, valid chronological MJD-OBS/DATE-OBS, and identical validated
WCS grids. `target_wcs` and `shape_out` provenance must agree with actual arrays.
The caller selects earlier/later explicitly; the function does not sort or align.

```python
from change_lens.pipeline.difference import compute_difference
from change_lens.pipeline.evidence import synthesize_evidence

def summarize(phase2, phase3, earlier_id, later_id):
    frames = {
        f.provenance["validation"]["observation_id"]: f
        for f in phase2.alignment.frames
    }
    difference = compute_difference(frames[earlier_id], frames[later_id])
    # Rejected products are retained as unavailable evidence, with reasons.
    return synthesize_evidence(phase3, differences=(difference,))

def summarize_without_difference(phase3):
    return synthesize_evidence(phase3)
```

## Output fields and handling

`DifferenceResult` contains:

- `status`: AVAILABLE, REJECTED (incompatible inputs), or UNAVAILABLE (no usable pixels).
- `earlier_observation_id`, `later_observation_id`, `earlier_mjd_utc`,
  `later_mjd_utc`, and `subtraction_order` (`later_epoch - earlier_epoch`).
- `plane_identity`, `unit`, `grid` (serialized WCS header, shape, comparison rule).
- `image`, `variance`, `variance_status` (AVAILABLE/PARTIAL/UNAVAILABLE),
  `usable_mask`, categorical union `flags`, `reason_masks`, and minimum `footprint`.
- `reason_codes`, `warnings`, and copied input `provenance`.
- Derived properties `absolute_image` and `normalized_image` (D/sqrt(Var(D))).

Rejected products have no image/variance/mask arrays. Unavailable compatible
products preserve masks and an all-NaN image; variance is None. Partial products
use NaN at excluded pixels. Missing uncertainty never becomes zero. Warning-only
flag pixels remain usable under the existing mask policy, with flags/reasons
retained; AVAILABLE is not a clean scientific finding. Arrays own their data and
do not depend on open FITS handles. Variance units are the square of `unit`;
normalized values are dimensionless inspection statistics.

`EvidenceResult` contains `tracks`, original `association`, `differences`,
`reason_codes`, `limitations`, and `provenance` including evidence labels.

- Each `TrackEvidence` has `track_id`, original `association` (`SourceTrack`),
  original `screened` (`ScreenedTrack`), conservative `statuses`, `reason_codes`,
  and `limitations`. Inspect `screened.preliminary_motion` for positions,
  displacement/pairwise measurements and uncertainties; inspect
  `screened.preliminary_brightness` for epoch values, uncertainties and comparisons.
  Original domain statuses and all control checks remain in `screened`.
- `statuses` is a deduplicated motion-then-brightness summary using existing Phase 3
  labels. Both domains remain inspectable. A brightness change with static position
  is not contradictory. An artifact in either domain remains visible alongside
  evidence in the other. Inconsistent positive/stable labels are downgraded to
  AMBIGUOUS; artifact controls veto support in their domain.
- Each `DifferenceEvidence` retains its `product`, `availability`,
  `valid_pixel_count`, frame-wide `minimum`/`maximum`, and `reason_codes`.
  Unknown epochs or conflicting upstream provenance make it unavailable to this
  summary. Extrema are not source-specific measurements or significant detections.
- Unmatched, rejected and ambiguous associations remain available in `association`,
  including source IDs, epoch times, reasons and provenance. An empty track list is
  insufficient evidence, never proof of no change. Missing/rejected differences
  never downgrade supported Phase 3 changes or prove stability.
- Duplicate track IDs, inconsistent measurement track IDs and duplicate difference
  pairs raise reason-coded `ValueError` rather than silently merging evidence.

Use the summary labels with original domain details. Do not promote preliminary
measurements when controls say ARTIFACT_SUSPECT, AMBIGUOUS or UNAVAILABLE. Do not
combine difference residuals and brightness/motion as independent votes. Translate
NumPy arrays/NaNs into backend-owned artifacts and explicit JSON nulls as appropriate;
this task does not implement serialization, persistence, previews or routes.

## Scientific assumptions and boundaries

- Independent epochs: Var(D) = Var(later) + Var(earlier). No inter-epoch covariance,
  resampling covariance, calibration-error model, PSF matching, or background matching.
- Positive finite variances are required, following SCI-002/003. Missing/invalid
  uncertainty masks pixels conservatively, including the raw difference image.
- UTC is inherited from Phase 3; supplied non-UTC TIMESYS is rejected. SCI-001 does
  not currently preserve TIMESYS, so upstream UTC metadata certification remains
  an assumption. No earlier-phase interface is changed.
- Exact grid-header equality is deliberately conservative; mathematically equivalent
  but differently encoded grids can be rejected. SIP is covered by header equality;
  external distortion tables are explicitly rejected, since header equality alone
  cannot establish their equivalence.
- Exact band/plane/release/calibration identity is required. No implicit unit
  conversion, recalibration, cross-band subtraction or new resampling is performed.
- Difference products are supporting image evidence. No confidence scores, calibrated
  significance, or discoveries are inferred. No SCI-010 or direction-change detector.
- Synthetic tests establish algorithm behavior, not authentic SPHEREx acceptance.
  `data/sci_verification/` is untouched.

## Architecture reconciliation

The v3 task register and scientific sections govern this implementation. Its earlier
traceability table uses SCI-009 for wavelength metadata, whereas the task register
and existing implementation use SCI-009 for controls; controls are preserved.
Architecture previews, FITS/PNG export, persistence and API examples describe the
broader product. The user's narrower scope leaves these for backend integration.
Existing dataclasses and screened labels are retained rather than introducing new
shared Pydantic/API contracts. Difference generation is optional for synthesis.

## Validation

Commands are run from `C:\NASA` with the existing Windows virtual environment.
Final results:

| Check | Passed | Failed | Deselected | Notes |
| --- | ---: | ---: | ---: | --- |
| Focused SCI-011/012 | 66 | 0 | 0 | 48 difference and 18 evidence cases |
| Existing Phase 1-3 regression | 239 | 0 | 0 | New test files excluded with `--ignore`; 2 expected malformed-FITS warnings |
| Full scientific suite | 305 | 0 | 0 | 2 expected malformed-FITS warnings |
| Full offline backend | 441 | 0 | 1 | Live IRSA test deselected; 3 expected malformed-FITS warnings |
| Ruff lint | pass | 0 | n/a | All four changed Python files |
| Ruff formatting check | pass | 0 | n/a | All four files already formatted |
| `git diff --check` | pass | 0 | n/a | Git reports only Windows LF/CRLF normalization notices |

The first sandboxed backend run stalled after two contract tests, before the first
API health assertion. Diagnostic command
`.\.venv\Scripts\python.exe -m pytest backend/tests/integration/test_api.py::test_health -vv -o faulthandler_timeout=20`
located the stall in Windows asyncio's local socket-pair creation (`socket.accept`).
Both stalled runs were stopped. The identical full offline command then passed
outside the sandbox; no environment, dependency or backend code was changed.
No unresolved implementation blockers remain. Authentic-data acceptance and backend
integration remain separate work, as scoped above.

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests/scientific/test_difference.py backend/tests/scientific/test_evidence.py
.\.venv\Scripts\python.exe -m pytest backend/tests/scientific --ignore=backend/tests/scientific/test_difference.py --ignore=backend/tests/scientific/test_evidence.py
.\.venv\Scripts\python.exe -m pytest backend/tests/scientific
.\.venv\Scripts\python.exe -m pytest backend/tests -m "not live"
.\.venv\Scripts\python.exe -m ruff check backend/src/change_lens/pipeline/difference.py backend/src/change_lens/pipeline/evidence.py backend/tests/scientific/test_difference.py backend/tests/scientific/test_evidence.py
.\.venv\Scripts\python.exe -m ruff format --check backend/src/change_lens/pipeline/difference.py backend/src/change_lens/pipeline/evidence.py backend/tests/scientific/test_difference.py backend/tests/scientific/test_evidence.py
git diff --check
```
