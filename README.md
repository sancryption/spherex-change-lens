# SPHEREx Change Lens

SPHEREx Change Lens is a coordinate-driven viewer prototype for authentic SPHEREx observations. This repository contains draft shared contracts, target and archive data services, a thin API, and a coverage handoff. It makes no Planet X, object-identity, or precision-photometry claims.

## Backend setup

Use Python 3.10 and `uv`. From the repository root in PowerShell:

```powershell
uv sync --project backend --locked
New-Item -ItemType Directory -Force data/cached_mefs | Out-Null
uv run --project backend --locked python -m pytest -c backend/pyproject.toml
```

Offline tests are the default. The live IRSA smoke test is opt-in:

```powershell
uv run --project backend --locked python -m pytest -c backend/pyproject.toml -o "addopts=" -m live backend/tests/test_live_irsa.py
```

## Run the API

From the repository root:

```powershell
uv run --project backend --locked uvicorn changelens.api.app:app --app-dir backend/src --reload
```

The API serves `/health/live`, `/health/ready`, `/v1/targets`, and `/openapi.json` on `http://127.0.0.1:8000`. `/health/ready` returns `503` when the configured cache directory is missing or not writable. Set `CHANGELENS_CACHE_DIR` to use another directory. Local frontend CORS origins include ports `5173` and `3000` on `localhost` and `127.0.0.1`.

## Archive data and evidence

- The five target definitions are in `data/targets/targets.json`; every target remains `UNVERIFIED`.
- Exact ADQL, the submitted TAP form parameters, and raw IRSA VOTable responses are retained in `data/target_queries/` as `.adql`, content-addressed `art_request_*.json`, and `.votable` files.
- Coverage counts, date ranges, detectors, releases, and visit groups are in [`docs/COVERAGE_REPORT.md`](docs/COVERAGE_REPORT.md) and `data/manifests/coverage_report.json`.
- Source manifests are committed under `data/manifests/`. FITS cache files live under `data/cached_mefs/` and are git-ignored.
- The authentic one-frame timeline fixture is [`backend/tests/fixtures/authentic_timeline_barnards_star.json`](backend/tests/fixtures/authentic_timeline_barnards_star.json). It is marked partial because the FITS container was checked but science and WCS validation remain pending.

The shared contracts are drafts pending INT-001. Open notices N-003, N-004, and N-005 are listed in [`docs/HANDOFF.md`](docs/HANDOFF.md) and the notification log in [`CLAUDE.md`](CLAUDE.md).
