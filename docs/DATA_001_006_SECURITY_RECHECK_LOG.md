# DATA-001–006 security recheck test log

**Assessment:** Test suites passed for the stated candidates. The standalone DATA scope remains **NOT READY** because security findings and owner/runtime gates remain open.

## Scope and candidate identity

- The owner selected standalone DATA and selected optional Gaia/AllWISE catalogue support as enabled. This records intended scope, not runtime activation or release approval.
- DATA-001–005 tests and probes are bound to pinned candidate `2600f2b89701d6d3fbab70ccfcf181fdba1fa2f2`.
- DATA-006 was checked separately at `f0779d91710727672db5a74f1192c8c31c8c5ad8`; PR #8 merged it to `main` at `0311ad63c9693ecd18d3bc7b0b478d61dc048d06`.
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
| Current `main` preview regression | Exact `test_preview_api.py` and matching preview source blobs | 1 passed; focused test only |

DATA-001–005 task checks ran on 14 November 2026 from 14:25:07 to 14:25:23 UTC. The offline candidate reruns completed at 17:11 UTC. The focused test from current `main` passed at 17:31:42 UTC. Live tests were deselected in offline suites. A first pytest attempt failed during temporary-directory setup on Windows; workspace-scoped temporary directories were used for the successful reruns. No assertion failures occurred in those successful runs.

## Recheck status and limitations

The standalone DATA assessment remains **NOT READY**. Open or unverified in-scope findings include R-001–R-005, R-007–R-009, and R-012–R-022. In particular, the enabled DATA-006 scope still has R-008 (redirect/response-size controls) and R-009 (warnings for zero or multiple matches) open. R-015/R-016 depend on the deployed worker topology and storage policy. Cross-workstream agreement, runtime activation/limits, and PM outcome are pending. R-006/R-010/R-011 and the main-app delivery portion of R-005 are integration handoff items outside this standalone decision.

The bounded IRSA request returned HTTP 200 with `QUERY_STATUS=OVERFLOW` and is partial evidence. Compose configuration passed, but the full Compose run/build stalled during Docker Hub image resolution before containers started; it is not green. The full current `main` suite was not rerun. The owner's installed-package inventory was not shared with an external service, and no public advisory scan was run.

## Repository status at review

At `2026-11-14 18:45:24 UTC` (`15 November 2026 02:45:24 SGT`), the review checkout was on `data/night-1` at `d45aa956fac7ecb81ba712b06995c27bbb08020a` with 104 porcelain status entries. It was not clean; staged snapshot files and local audit artifacts were present. The separate DATA-006 checkout was clean on `codex/data-006-optional-catalogue-adapters` at `f0779d91710727672db5a74f1192c8c31c8c5ad8`.

This log records candidate-specific test outcomes and the captured repository state. Passing tests do not clear the open security findings or establish deployment readiness.
