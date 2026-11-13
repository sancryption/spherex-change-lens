# SPHEREx Change Lens

> **NASA Space Apps Challenge 2026**  
> *Repository Scaffolding & Initial Foundation*

---

## 1. Project Purpose

SPHEREx Change Lens is planned as a public web application enabling researchers and the public to:
- Select one of NASA's five named targets or input arbitrary RA/Dec coordinates.
- Discover and retrieve SPHEREx observations.
- View observations chronologically like a small video.
- Validate FITS products, WCS, flags, variance, and metadata.
- Investigate source movement and brightness variation.
- Review difference images, uncertainty, quality warnings, and scientific provenance.

### Target Reference Set (NASA Named Targets)
1. **Barnard's Star** (High proper motion reference)
2. **Epsilon Indi B** (Nearby brown dwarf candidate)
3. **WISE 0855** (Ultra-cool sub-stellar object)
4. **RW Aurigae** (Variable Young Stellar Object / binary)
5. **R Draconis** (Mira-type pulsating variable)

> [!WARNING]
> **Implementation Status Notice**
> The DATA backend prototype and its thin API are implemented on this branch. Frontend integration and scientific image analysis remain pending.
> The target coverage, archival availability, and scientific usability for the five targets listed above are **pending verification** and must not be assumed complete until data retrieval and pipeline validation workstreams are executed.

---

## 2. Repository Structure

This repository is organized into distinct package boundaries and workstreams:
- `backend/`: FastAPI application, Pydantic contracts, scientific pipeline scaffolds, archive connectors, storage, and observability.
- `frontend/`: React + TypeScript + Vite web interface scaffold and synchronized client contracts.
- `docs/`: Technical specifications, NASA traceability, policies, and operational runbooks.
- `infra/`: Container definitions, Docker Compose, and reverse proxy configuration.
- `scientific/`: Scientific configuration definitions, validation specs, and reference output baselines.
- `data/`: Manifests, query logs, cache structures, and synthetic test fixtures (strictly excluded from Git tracking for large data).
- `scripts/`: Environment setup, validation, and deterministic test data generation utilities.

---

## 3. Workstream Architecture

The project is structured around seven technical workstreams:
- **FE**: Frontend Engineering (UI, timeline, viewer, responsive interaction)
- **BE**: Backend Engineering (API routes, job handling, SQLite storage, contracts)
- **DATA**: SPHEREx Archive & Data Engineering (retrieval, caching, manifests)
- **SCI**: Scientific Processing & Analysis (alignment, difference imaging, motion, photometry)
- **QA**: Quality Assurance (unit, integration, contract, and synthetic end-to-end tests)
- **INFRA**: Infrastructure & Deployment (Docker, CI/CD, local runtime environments)
- **INT**: Cross-Module Integration (API-frontend synchronization, contract tests)

*Team ownership across the six team members will be allocated and confirmed separately (see [docs/team-ownership.md](file:///c:/NASA/docs/team-ownership.md)).*

---

## 4. Getting Started (Scaffold Baseline)

### Prerequisites
- Python 3.11+
- Node.js 20+ & npm / pnpm
- Docker & Docker Compose (optional for containerized runs)

### Environment Setup
1. Copy the example environment configuration:
   ```bash
   cp .env.example .env
   ```
2. Set up the backend virtual environment:
   ```bash
   cd backend
   python -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   pip install -e ".[dev]"
   ```
3. Set up the frontend dependencies:
   ```bash
   cd frontend
   npm install
   ```

### Scaffolding Verification
Run the root verification script to confirm environment and repository boundaries:
```bash
python scripts/validate_environment.py
```

---

## 5. Development Principles & Guardrails
- **No Mock Production Claims**: Do not present synthetic or placeholder data as verified NASA archival observations.
- **Contract Driven**: The scaffold models in `backend/src/change_lens/contracts` remain canonical for shared frontend integration. The DATA-specific models in `backend/src/changelens/contracts` are drafts pending INT-001.
- **Strict Data Exclusion**: Large FITS files (`*.fits`, `*.fit`, `*.fts`), cache directories, and generated previews are ignored by Git.
- **Minimal Dependencies**: We avoid heavy premature dependencies (e.g., Celery, Redis, PostgreSQL) in favor of SQLite and modular Python pipelines.

---

## 6. DATA Workstream Prototype

This branch adds an initial DATA backend alongside the team scaffold. The data package lives in `backend/src/changelens`; its draft contracts are not yet reconciled with the shared `change_lens` contracts, so cross-workstream API integration remains pending INT-001.

### Backend setup

Use Python 3.11 and `uv`. From the repository root in PowerShell:

```powershell
uv sync --project backend --locked --extra dev
New-Item -ItemType Directory -Force data/cached_mefs | Out-Null
uv run --project backend --locked --extra dev python -m pytest -c backend/pyproject.toml
```

Offline tests are the default. The live IRSA smoke test is opt-in:

```powershell
uv run --project backend --locked --extra dev python -m pytest -c backend/pyproject.toml -o "addopts=" -m live backend/tests/test_live_irsa.py
```

### Run the DATA API

```powershell
uv run --project backend --locked --extra dev uvicorn changelens.api.app:app --app-dir backend/src --reload
```

The API exposes `/health/live`, `/health/ready`, `/v1/targets`, and `/openapi.json` on `http://127.0.0.1:8000`. Readiness returns `503` if the configured cache directory is missing or not writable. Set `CHANGELENS_CACHE_DIR` to use another directory.

### Archive data and evidence

- The five target definitions are in `data/targets/targets.json`; every target remains `UNVERIFIED`.
- Submitted ADQL, TAP request parameters, and raw IRSA VOTable responses are retained in `data/target_queries/`.
- Coverage counts and visit summaries are in `docs/COVERAGE_REPORT.md` and `data/manifests/coverage_report.json`.
- FITS cache files live in `data/cached_mefs/` and are ignored by Git.
- The authentic one-frame timeline fixture is marked partial: the FITS container was checked, while science and WCS validation remain pending.
## 7. License
License terms are pending confirmation by the project team. See [LICENSE](file:///c:/NASA/LICENSE).
