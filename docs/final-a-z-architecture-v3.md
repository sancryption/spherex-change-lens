# Architecture Blueprint: SPHEREx Change Lens (A-Z Architecture v3)

**Status:** `Decision required` & `Pending implementation`  
**Document Owner:** Architecture Working Group (INT / BE / FE / INFRA)

---

## 1. System Vision & Objective
SPHEREx Change Lens is an interactive scientific web application designed to allow researchers and citizen scientists to explore temporal changes in SPHEREx spectral survey observations across the sky and specifically targeting candidate astronomical objects.

## 2. High-Level Architectural Diagram
```
+-------------------------------------------------------------+
|                        Frontend UI                          |
|  (React, TypeScript, Vite, WebGL/Canvas Video Viewer, CSS)  |
+------------------------------+------------------------------+
                               | HTTPS / JSON (OpenAPI)
+------------------------------v------------------------------+
|                     FastAPI Backend                         |
|   - API Routing & Dependency Injection                      |
|   - Contract Enforcement (Pydantic v2)                      |
|   - Asynchronous Job Coordinator (SQLite State)             |
+---------------+------------------------------+--------------+
                |                              |
+---------------v---------------+   +----------v--------------+
|     DATA / Archive Engine     |   |  SCI Processing Engine  |
| - SPHEREx Archive / IRSA API  |   | - WCS Alignment (reproj)|
| - FITS Download & Validation  |   | - Bad-pixel Masking     |
| - MEF Splitting & Caching     |   | - Source Det (photutils)|
+---------------+---------------+   | - Centroid & Motion     |
                |                   | - Difference Imaging    |
+---------------v---------------+   +----------+--------------+
|      Local File System        |              |
|  - data/cached_mefs/          |<-------------+
|  - data/previews/             |
|  - data/derived/              |
+-------------------------------+
```

## 3. Core Component Outlines
- **Frontend (FE)**: Target selection, interactive multi-epoch timeline playback, image viewer with variance/flag overlays, difference viewer, and evidence drawer.
- **Backend (BE)**: REST endpoints matching contracts, SQLite database for job tracking and metadata storage, structured logging and error handling.
- **Data Layer (DATA)**: Interface to NASA/IPAC IRSA SPHEREx archives, cone searches, cutouts, Multi-Extension FITS (MEF) unpacking, and disk caching.
- **Scientific Pipeline (SCI)**: Coordinate transformation, reproject-based spatial alignment, flagging bad pixels, difference image computation, photometric variation analysis, and motion vector estimation.
- **Infrastructure (INFRA)**: Docker containerization, development compose configurations, and CI pipelines.

## 4. Pending Architectural Decisions
- Strategy for caching Multi-Extension FITS slices on disk vs in-memory.
- Maximum bounding box / cutout dimension allowed for dynamic interactive alignment.
- Precision threshold for difference imaging background matching.
