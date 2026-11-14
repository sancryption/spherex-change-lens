# Team Workstream Ownership & Responsibilities

**Status:** `Decision required` - Allocation Pending  
**Context:** 6 Team Members covering 7 Technical Workstreams

---

## 1. Technical Workstreams Overview
The SPHEREx Change Lens project divides its technical scope into 7 workstreams:

1. **FE (Frontend Engineering)**: React, UI design, viewer canvas, time-series player, accessibility.
2. **BE (Backend Engineering)**: FastAPI routes, business logic, asynchronous task dispatch, SQLite storage.
3. **DATA (Archive & Ingestion)**: NASA/IPAC IRSA API, FITS downloading, validation, disk caching, MEF handling.
4. **SCI (Scientific Processing)**: WCS reprojection, background modeling, difference imaging, motion, photometry.
5. **QA (Quality Assurance)**: Automated tests, scientific benchmark verification, end-to-end user workflows.
6. **INFRA (Infrastructure & DevOps)**: Docker, CI/CD, local scripting, environment reproducibility.
7. **INT (Cross-Module Integration)**: API contracts synchronization, end-to-end data flow, presentation alignment.

---

## 2. Workstream Assignment Matrix

> [!NOTE]
> Per architectural guidelines, specific individual names are intentionally omitted at this scaffolding stage.
> Allocation of primary and secondary leads across the six team members will be finalized during the kickoff meeting.

| Workstream | Code | Primary Role Focus | Secondary Focus |
|---|---|---|---|
| Frontend Engineering | `FE` | User Interface, Canvas Viewer, Timeline | Integration with API |
| Backend Engineering | `BE` | FastAPI, Job Queue, Storage Models | Pipeline Orchestration |
| SPHEREx Archive Data | `DATA` | IRSA Client, MEF Extraction, Ingestion | Cache Management |
| Scientific Analysis | `SCI` | WCS Alignment, Differencing, Astrometry | Scientific Validation |
| Quality Assurance | `QA` | Unit/Contract/E2E Test Suites | Benchmark Comparisons |
| Infrastructure | `INFRA`| Docker, CI/CD, Makefiles, Scripts | Performance Monitoring |
| System Integration | `INT` | API Contracts, Type Sync, Demo Prep | Scientific Communication |
