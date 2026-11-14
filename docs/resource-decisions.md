# Resource Decisions and Technical Boundaries

**Status:** `Decision required` & `Active Policy`  
**Governing Workstreams:** INFRA / BE / SCI

---

## 1. Architectural Guardrails (Standard Baseline)
To keep the application accessible, reproducible, and compliant with the challenge constraints, the following technologies are chosen:

- **Web Frontend**: React, TypeScript, Vite, minimal maintainable CSS.
- **Backend**: Python 3.11+, FastAPI, Pydantic v2.
- **Scientific Foundation**: Astropy, NumPy, SciPy, reproject, photutils, Matplotlib, Pillow.
- **Persistence**: SQLite (standard file-based DB, zero-config, portable).
- **Tooling & Quality**: Ruff, Pytest, ESLint, TypeScript Strict, Vitest, Playwright.
- **Containerization**: Docker, Docker Compose.

## 2. Prohibited Premature Infrastructure
Unless explicitly approved and justified by team consensus, the following components are **strictly excluded**:
- **No Redis / Celery**: Complex distributed task brokers are prohibited during initial phases; use native asyncio or lightweight SQLite-backed background job queues.
- **No Heavy RDBMS (PostgreSQL/MySQL)**: SQLite is sufficient for single-node metadata and job state during the competition.
- **No Cloud Object Stores (S3/GCS)**: Local filesystem paths under `data/` will be used for caching and previews.
- **No External Authentication Services**: The application is designed as a public, open scientific lens; user auth is out of initial scope.
- **No Black-box ML / DL Frameworks**: Scientific measurements (photometry, astrometry, difference imaging) must rely on transparent analytical methods.

## 3. Pending Resource Decisions
- Max disk allocation limit for `data/cached_mefs/` (Recommendation: 10 GB limit with LRU eviction).
- Thread worker pool limits for CPU-intensive reproject and difference computations.
