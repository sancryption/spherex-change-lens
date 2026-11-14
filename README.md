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
> **Scaffold Status Notice**  
> Application features, scientific algorithms, and API endpoints are **NOT implemented yet**.  
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
- **Contract Driven**: Backend Pydantic models in `backend/src/change_lens/contracts` are the single source of truth for all API interactions.
- **Strict Data Exclusion**: Large FITS files (`*.fits`, `*.fit`, `*.fts`), cache directories, and generated previews are ignored by Git.
- **Minimal Dependencies**: We avoid heavy premature dependencies (e.g., Celery, Redis, PostgreSQL) in favor of SQLite and modular Python pipelines.

---

## 6. License
License terms are pending confirmation by the project team. See [LICENSE](file:///c:/NASA/LICENSE).
