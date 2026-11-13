# SPHEREx Change Lens — Working Agreement (DATA / BE workstream)

This file governs all work done in this repository by the DATA owner and by Claude.
Read it at the start of every session, before touching code.

- **Team:** Cosmic Anomaly — NASA Space Apps Challenge 2026, challenge "Planet X and SPHEREx"
- **Owner of this workstream:** DATA (primary), BE (assist only)
- **Hard deadline:** project submission closes **Sunday 15 Nov 2026, 23:59 local time**
- **Language:** English only — code, comments, docs, commit messages, and chat.
  (NASA requires English on the submission page and in all linked materials.)

---

## 1. Sources of truth

In order of authority:

1. **NASA challenge statement** — defines what is mandatory (section 2).
2. **Team guide:** `SPHEREx Change Lens — Technical Implementation Guide` (the PDF, 44 tasks).
   Task IDs in this file (`DATA-002`, `BE-001`, ...) refer to that guide.
3. **This file** — how we work, tonight's scope, and the notification log.

If two sources disagree, do not pick one silently: raise a notification (section 3).

## 2. Mandated vs optional

**Mandated by NASA** (the challenge objectives — never cut, never redesign):

| # | Requirement |
|---|---|
| M1 | A public-facing web tool that displays SPHEREx images of the sky. |
| M2 | The user enters the coordinates of a patch of sky (Right Ascension and declination). |
| M3 | The tool shows a series of images of that patch "like a little video", so change over time is easy to see. |
| M4 | Tested on Barnard's Star, Epsilon Indi B, WISE 0855 (RA 08h55m10.831s, Dec −7d14m42.53s), RW Aurigae, R Draconis. |

**Rule A — mandated path follows the PDF.** Everything needed to deliver M1–M4 is built
the way the team guide specifies. For this workstream that path is:
`DATA-001 → DATA-002 → DATA-003 → DATA-004 → DATA-005` and `BE-001 → BE-002 → BE-003 → BE-006`.

**Rule B — optional features may be changed or improved, but only after notification.**
Everything else is optional: NASA's "potential considerations" (per-detector sums, spectra,
add/subtract images, Gaia/WISE overlay, coordinates in the URL, flag metadata) and the
team guide's own additions (analysis runs, provenance API, difference products, catalogue
adapters, QA/INFRA extras). These can be adjusted, simplified, or improved — **but the
user is notified first, every time, whether or not the change conflicts with the PDF.**

## 3. Notification protocol

A notification is required **before** doing any of the following:

- changing, adding, removing, or improving an optional feature (Rule B);
- deviating from the PDF anywhere, including on the mandated path;
- changing a shared contract (schema, enum, endpoint, file layout) after others depend on it;
- adding a dependency the PDF does not list.

Format — one entry in the log at the bottom of this file, and the same text in chat:

```
N-0XX | <title>
Type:    DEVIATION-FROM-PDF | OPTIONAL-CHANGE | CONTRACT-CHANGE | NEW-DEPENDENCY | FYI
What:    <the change, one or two sentences>
Why:     <evidence — say whether it is verified or assumed>
Impact:  <task IDs and workstreams affected>
Default: <what is done until the user answers>
Status:  PROPOSED | APPROVED | REJECTED | NOTED
```

`FYI` records a choice the PDF already permits, so the user sees it; it needs no decision
and its status is `NOTED`. Every other type needs a decision.

Rules:

1. **Nothing in a `PROPOSED` entry is implemented.** Work continues on the `Default`,
   which must be the PDF-specified behaviour whenever that behaviour is possible.
2. If the user is unavailable (unattended run), log the entry, keep working on the
   default, and list all open entries at the top of the handoff note.
3. If the PDF-specified behaviour is impossible against the real archive, implement the
   smallest working path for the mandated requirement only, and mark the entry
   `DEVIATION-FROM-PDF` so it is reviewed first thing.
4. Only the user changes a status to `APPROVED` or `REJECTED`.

## 4. Tonight's scope — finish and hand off

Goal: by morning, every other workstream can start without waiting for DATA.
Priority order is fixed; if time runs out, stop at the last finished item — never leave
one half-done. DATA comes before BE.

| # | Deliverable | Task | Done when |
|---|---|---|---|
| T0 | Repo skeleton, pinned environment, run instructions | — | Clean clone → install → `pytest` passes, on Python 3.10. |
| T1 | Draft contracts (Pydantic): target, observation record, discovery result, source artifact, timeline frame/model, error envelope, status enums | INT-001 (draft) | Models match the PDF's representative JSON; marked `DRAFT` until the team freezes them. |
| T2 | NASA target registry | DATA-001 | All five targets present; WISE 0855 coordinates exact; every target starts `unverified`. |
| T3 | IRSA discovery adapter | DATA-002 | Recorded-response tests pass; one live smoke query passes; raw query and raw response are kept; zero rows, 4xx, 5xx, timeout, and partial results each produce a typed outcome. |
| T4 | Retrieval, hashing, cache | DATA-003 | Simulated timeout, 503, partial download, and cache hit are tested; an invalid or partial file can never become a cache entry; SHA-256 and manifest are written. |
| T5 | Live coverage report for the five targets, plus one authentic timeline fixture and a small authentic cutout cache | DATA-002/003 output | Report states frames, date range, detectors, and visit groups per target; nothing is labelled usable without evidence. |
| T6 | Thin API skeleton and `GET /v1/targets` | BE-001 | `/health/live` works without storage; `/health/ready` reports storage state; errors use the envelope; request IDs appear in responses and logs; OpenAPI builds; CORS allows the local frontend. |
| T7 | Handoff note | — | `docs/HANDOFF.md` written (section 7). |

**Not tonight:** DATA-004, DATA-005, DATA-006, BE-002 through BE-007, anything in SCI/FE/QA/INFRA.
BE work beyond T6 is the BE owner's; this workstream only assists when asked.

## 5. What each workstream receives

| Consumer | Receives | Unblocks |
|---|---|---|
| FE | `GET /v1/targets`, OpenAPI JSON, error-envelope shape, an authentic timeline fixture | FE-002, FE-003, FE-004 |
| BE | Draft contracts, the DATA Python interface, fixtures that stand in for live data, the API skeleton | BE-002, BE-003, BE-006 |
| SCI | Authentic cached cutouts with manifest (path, SHA-256, source URL) and the observed FITS structure | SCI-001, SCI-002, SCI-003 |
| QA | Recorded archive responses, pytest layout, the `live` test marker | QA-001, QA-002 |
| INFRA | Directory layout, environment variables, install/run commands | INFRA-001, INFRA-002 |
| INT | Draft contracts, the notification log, the coverage report (basis for choosing the demo target) | INT-001, INT-002 |

DATA exposes plain Python functions; BE wraps them in HTTP. Neither side blocks the other:

```python
discover(request) -> DiscoveryResult      # DATA-002
retrieve(observation) -> SourceArtifact   # DATA-003
```

## 6. Engineering standards

**Scope and design**
- Build the thinnest slice that works end to end before adding breadth.
- Contract first: the Pydantic models are the interface. After the team freeze, changes are additive or go through a notification.
- No new dependency, framework, or service unless a listed task needs it (the PDF rules out Redis/Celery, large viz frameworks, and ML for the core).
- Scientific calculations stay out of route handlers.

**Correctness and honesty**
- Use authentic SPHEREx data wherever it exists. Label cached data as cached and synthetic data as synthetic — the labels are never blurred, and data is never fabricated.
- A metadata record is not an image; a downloaded file is not automatically valid. Record each state separately.
- Never drop a failed record silently: keep it with a reason.
- In docs and notes, mark every claim as **verified** (with how) or **unverified**.
- No discovery, Planet X, object-identity, or precision-photometry claims anywhere.

**Reliability**
- Every network call has connect and read timeouts.
- Retry only idempotent requests, with bounded backoff; never retry a malformed request.
- Check every download is a FITS file before it enters the cache (the PDF: invalid or partial files never become cache entries); write to a temporary file and promote atomically. Structural validation of the extensions is SCI-001's job.
- Be a polite archive client: bounded concurrency, a generic User-Agent, a disk budget for the cache.

**Tests**
- Each module ships with tests in the same commit.
- Tests run offline by default using recorded fixtures; tests that touch the network carry the `live` marker and are opt-in.
- Fixed inputs give fixed outputs — no test depends on wall-clock time or archive state.

**Code**
- Python 3.10, type hints throughout, Pydantic models at boundaries, `pathlib` for paths, standard `logging` (no `print` in library code).
- Errors are typed and map to the PDF's error envelope.
- Dependencies are pinned in `pyproject.toml`.

**Security and privacy**
- No secrets, tokens, names, or email addresses in code, logs, fixtures, or outbound requests.
- Artifact access goes through opaque IDs — never a caller-supplied filesystem path.
- Large binaries (FITS cache, previews) are git-ignored; only manifests and small fixtures are committed.

**Git**
- Small commits, one concern each, Conventional Commits style (`feat(data): ...`, `test(api): ...`).
- Work on a branch (`data/night-1`), never directly on `main`; tests pass before each commit.
- Local commits are allowed as checkpoints. **Nothing is pushed, published, or shared without the user's explicit instruction.**

**Submission compliance** (required by the NASA guides)
- `docs/REFERENCES.md` lists every external resource used — code, text, images, data, tutorials — including open-source ones.
- `docs/AI_USAGE.md` records how AI tools were used; the submission must describe this.

## 7. Handoff note

Every working session ends by updating `docs/HANDOFF.md`:

1. Open notifications awaiting a decision (first, always).
2. What is finished, with the command that proves it.
3. What is not finished or not verified — stated plainly.
4. What each workstream can now start, and with which file.
5. Known problems and the next three actions.

## 8. Layout

```
backend/
  pyproject.toml
  src/changelens/
    contracts/     Pydantic models and status enums        (T1)
    data/          target registry, discovery, retrieval   (T2–T4)
    api/           FastAPI app                             (T6)
  tests/
    fixtures/      recorded archive responses
data/
  targets/         target registry file                    (committed)
  manifests/       source manifests                        (committed)
  target_queries/  raw queries and responses               (committed)
  cached_mefs/     authentic FITS cutouts                  (git-ignored)
  previews/  derived/  synthetic/                          (later tasks)
docs/
  HANDOFF.md  COVERAGE_REPORT.md  REFERENCES.md  AI_USAGE.md
```

Directory names under `data/` follow INFRA-002 in the team guide.

## 9. Archive facts (live-tested 14 Nov 2026)

Verified from this machine against IRSA:

- **Discovery works through IRSA TAP** (`https://irsa.ipac.caltech.edu/TAP`), using the query from IRSA's own SPHEREx cutout tutorial: join `spherex.artifact` to `spherex.plane` on `planeid`, filter with `CONTAINS(POINT('ICRS', ra, dec), p.poly)`, order by `p.time_bounds_lower`.
- At RA 269.452, Dec 4.6934 (near Barnard's Star): **363 frames in 14 s**; 59–62 frames per detector (`SPHEREx-D1` … `D6`); MJD 60902.86 – 61305.63; two gaps longer than 30 days (161 d, 104 d), so three visit groups.
- **Cutouts** are requested by appending `?center=<ra>,<dec>d&size=<deg>` to the artifact URL. A 0.05° cutout is 29 × 29 pixels, pixel scale about 6.2 arcsec.
- Cutout HDUs: `PRIMARY`, `IMAGE`, `FLAGS`, `VARIANCE`, `ZODI`, `EPSF`, `WCS-WAVE`. Headers carry `MJD-AVG`, `DATE-AVG`, `DETECTOR`, `BUNIT = MJy / sr`; the primary header carries `VERSION`.
- One cutout response was 3,962,880 bytes and took about 10 s.
- Artifact paths returned for this position sit under `ibe/data/spherex/dr1/level2/`.
- On this Windows machine `urllib` fails TLS verification; `requests` works.

Observed but not yet explained:

- 2 of 4 cutout requests returned a body Astropy could not open ("No SIMPLE card found"); a retry succeeded. Status code and content type of the failures were not captured. DATA-003 treats such a body as an invalid download and logs status, content type, and first bytes.

Not verified:

- SIA2 discovery. Two guessed collection names (`spherex_qr`, `spherex_qr2`) returned zero rows; the correct collection name was never tried, so SIA2 is neither confirmed nor ruled out.
- Coverage of the other four targets.
- Full-file size, and whether cutouts ever return HTTP 503.

## 10. Notification log

Append-only. Newest last.

```
N-001 | Discovery uses IRSA TAP
Type:    FYI
What:    DATA-002 queries the TAP tables spherex.plane / spherex.artifact.
Why:     Verified working (section 9). The PDF allows "IRSA/SIA2 or documented
         programmatic service"; TAP is the method in IRSA's own tutorial. SIA2 unverified.
Impact:  DATA-002 only. The adapter interface does not expose which service is used.
Default: Use TAP.
Status:  NOTED

N-002 | Release and collection names come from the archive
Type:    FYI
What:    Each frame reports the release the archive gives for it. "spherex_qr3" in the
         PDF's request example is treated as an example, not a confirmed value.
Why:     The artifact paths observed are under dr1 (verified). Which collection values
         exist, and which releases cover each target, is unverified. The PDF already
         requires per-frame release and that QR2/QR3/DR1 are never silently mixed.
Impact:  DATA-002, DATA-005; the allowed values of `collection` in BE-002 / FE-002.
Default: Keep the PDF's `collection` field; list its real values in the coverage report.
Status:  NOTED

N-003 | Full-file fallback off by default
Type:    DEVIATION-FROM-PDF
What:    DATA-003 says to fall back to full-file retrieval when a cutout returns 503.
         Proposal: retry the cutout with backoff first; keep the full-file fallback
         behind a setting that is off by default, with a size limit.
Why:     Full files hold complete detector images and are assumed to be far larger
         than cutouts (size unverified); 363 frames per target would be costly.
Impact:  DATA-003, cache disk budget.
Default: Implement as the PDF says (fallback on 503).
Status:  PROPOSED

N-004 | Record the wavelength at the target position for every frame
Type:    OPTIONAL-CHANGE (additive field)
What:    Add `central_wavelength_um` to each observation/timeline frame, computed from
         the WCS-WAVE extension as IRSA's tutorial does.
Why:     SPHEREx detectors use linear variable filters, so two frames from the same
         detector can see the target at different wavelengths. The PDF's
         `SAME_SUPPORTED_BAND` policy cannot be applied without this value. (Instrument
         behaviour: from mission documentation, not verified here.)
Impact:  Contracts (additive), DATA-005, SCI-003, FE frame labels.
Default: Not added.
Status:  PROPOSED

N-005 | Store proper motion and epoch for the named targets
Type:    OPTIONAL-CHANGE (additive fields)
What:    Add proper motion and reference epoch to the target registry, and query at
         the position for the observation period rather than the catalogue position.
Why:     Barnard's Star moves about 10 arcsec per year, so its J2000 catalogue position
         is several arcminutes from where SPHEREx sees it — comparable to the PDF's
         example 10-arcmin field. (Catalogue values not yet fetched: unverified.)
         WISE 0855 keeps NASA's exact coordinates regardless.
Impact:  DATA-001 schema (additive), GET /v1/targets, FE-002 presets.
Default: Registry holds only the PDF's fields; positions as catalogued.
Status:  PROPOSED
```
