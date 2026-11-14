# DATA-001–006 security recheck test log

**Assessment:** Test suites passed for the stated candidates. The standalone DATA scope remains **NOT READY** because security findings and owner/runtime gates remain open.

## Scope and candidate identity

- The owner selected standalone DATA and selected optional Gaia/AllWISE catalogue support as enabled. This records intended scope, not runtime activation or release approval.
- DATA-001–005 tests and probes are bound to pinned candidate `2600f2b89701d6d3fbab70ccfcf181fdba1fa2f2`.
- DATA-006 was checked separately at `f0779d91710727672db5a74f1192c8c31c8c5ad8`; PR #8 merged it to `main` at `0311ad63c9693ecd18d3bc7b0b478d61dc048d06`.
- The audited upstream candidates require Python `>=3.11` and the test receipts used Python 3.11.14. The separate staged local worktree specifies Python 3.10; it is a different candidate and these receipts do not cover it (N-006).
- A separate local parent-recovery DATA/BE candidate is recorded at frozen identity `sha256:cbf2ddf1044ff9069e31ffbd7072128c0ab5ee350aa07902db3ef098c9a92a8c`, based on `d45aa956fac7ecb81ba712b06995c27bbb08020a` and tested as clean-clone commit `39b75500182db489fe03a0e349943d0c0fea28d8`. It passed its locked Python 3.10.11 clean-clone and README offline suite separately; this candidate-bound result does not transfer to the upstream snapshots or establish the optional DATA-006 adapter integration.
- GitHub reported `main` at `f568d39a5df23bf9839449b8b9056a320101e3e0` at 18:45 UTC on 14 November 2026. Open PRs #15 (INT demo pre-warm/persistent caches) and #16 (SCI Phase 4) are unrelated to this standalone DATA audit.

## Test results

| Candidate / task | Command or test group | Result |
|---|---|---|
| `2600f2b` DATA-001 | `test_targets.py`, `test_data_contracts.py` | 27 passed |
| `2600f2b` DATA-002 | `test_discovery.py`, `test_network.py` | 12 passed |
| `2600f2b` DATA-003 | `test_retrieval.py` | 15 passed |
| `2600f2b` DATA-004 | `test_previews.py`, `test_preview_api.py` | 11 passed |
| `2600f2b` DATA-005 | `test_coverage.py`, `test_data_contracts.py` | 42 passed |
| `2600f2b` offline backend suite | `python -m pytest -c backend/pyproject.toml backend/tests -m "not live" -q -p no:cacheprovider` | 112 passed, 1 live test deselected |
| `f0779d9` DATA-006 | `test_catalogue.py`, `test_data_exports.py` | 12 passed |
| `f0779d9` offline backend suite | Same offline-suite command | 107 passed, 1 live test deselected |
| Local parent-recovery candidate at `39b7550` | `uv run --project backend --locked python -m pytest -c backend/pyproject.toml` in a fresh clone with Python 3.10.11 | 65 passed, 1 live test deselected; one expected warning from the deliberately truncated FITS fixture |
| Current `main` at `f568d39` offline backend suite | `python -m pytest -c backend/pyproject.toml backend/tests -m "not live" -q -p no:cacheprovider` | 380 passed, 1 live test deselected, 4 warnings; exit code 0 |
| Current `main` preview regression | Exact `test_preview_api.py` and matching preview source blobs | 1 passed; focused test only |

DATA-001–005 task checks ran on 14 November 2026 from 14:25:07 to 14:25:23 UTC. The offline candidate reruns completed at 17:11 UTC. The focused current-main preview test passed at 17:31:42 UTC. The full current-main backend suite was run from a detached worktree at exact SHA `f568d39a5df23bf9839449b8b9056a320101e3e0` using Python 3.11.14; the result capture at 19:07:57 UTC recorded 380 passed, 1 live test deselected, 4 warnings, and exit code 0. An initial attempt used an invalid pytest temporary directory and stopped before collection; the successful run used a separate unique system-temp directory. No assertion failures occurred in successful runs.

The separate local parent-recovery candidate completed its clean-clone check at `2026-11-14 06:20:40 SGT`: frozen identity `sha256:cbf2ddf1044ff9069e31ffbd7072128c0ab5ee350aa07902db3ef098c9a92a8c`, commit `39b75500182db489fe03a0e349943d0c0fea28d8`, Python 3.10.11 locked install and lock check passed, and the README offline suite reported 65 passed with 1 live test deselected. Parent recovery recorded T0–T7 acceptance met, known implementation blockers none, independent attestation not obtained within the fixed review budget, and final-strict not achieved. This verifies that exact candidate's handoff acceptance, not the pinned upstream security findings or integration with the separate DATA-006 adapter. The test receipt predates later audit-document edits to the local workspace.

## Recheck status and limitations

The standalone DATA assessment remains **NOT READY**. Open or unverified in-scope findings include R-001–R-005, R-007–R-009, and R-012–R-022. In particular, the enabled DATA-006 scope still has R-008 (redirect/response-size controls) and R-009 (warnings for zero or multiple matches) open. R-015/R-016 depend on the deployed worker topology and storage policy. Cross-workstream agreement, runtime activation/limits, and PM outcome are pending. R-006/R-010/R-011 and the main-app delivery portion of R-005 are integration handoff items outside this standalone decision.

The bounded upstream IRSA request returned HTTP 200 with `QUERY_STATUS=OVERFLOW` and is partial evidence; the later parent-recovery live attempt timed out after three bounded tries with no HTTP status or response body. Compose configuration passed, but the full Compose run/build stalled during Docker Hub image resolution before containers started; it is not green. The full current-main offline backend suite passed, but live and Compose checks remain incomplete. The owner's installed-package inventory was not shared with an external service, and no public advisory scan was run.

## Repository status at review

At `2026-11-14 18:45:24 UTC` (`15 November 2026 02:45:24 SGT`), the review checkout was on `data/night-1` at `d45aa956fac7ecb81ba712b06995c27bbb08020a` with 104 porcelain status entries. It was not clean; staged snapshot files and local audit artifacts were present. The separate DATA-006 checkout was clean on `codex/data-006-optional-catalogue-adapters` at `f0779d91710727672db5a74f1192c8c31c8c5ad8`.

This log records candidate-specific test outcomes and the captured repository state. Passing tests do not clear the open security findings or establish deployment readiness.
