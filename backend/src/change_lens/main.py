"""Application entrypoint and factory for SPHEREx Change Lens.

Run from the repo root:  uvicorn change_lens.main:app --reload --port 8000
Docs: http://localhost:8000/docs
"""

import uuid
from typing import Any

from change_lens.config import Settings, get_settings, resolve_data_path


def _default_archive(settings: Settings) -> Any:
    if settings.spherex_archive_mock_mode:
        from change_lens.archive.mock import MockArchiveClient

        return MockArchiveClient(resolve_data_path(settings.data_dir) / "synthetic")
    from change_lens.archive.irsa import IrsaArchiveClient

    return IrsaArchiveClient(
        data_dir=resolve_data_path(settings.data_dir),
        previews_dir=resolve_data_path(settings.previews_dir),
        cache_dir=resolve_data_path(settings.cached_mefs_dir),
        max_frames=settings.spherex_max_frames,
    )


def create_app(settings: Settings | None = None, repo: Any = None, archive: Any = None) -> Any:
    """Create and configure the FastAPI application instance."""
    try:
        from fastapi import FastAPI, Request
        from fastapi.middleware.cors import CORSMiddleware
    except ImportError:
        # Fallback placeholder when FastAPI is not yet installed in host environment
        class ScaffoldAppPlaceholder:
            """Scaffold placeholder when runtime dependencies are pending."""

            def __init__(self) -> None:
                self.title = "SPHEREx Change Lens (Pending Dependencies)"

            def __call__(self, *args: Any, **kwargs: Any) -> None:
                raise RuntimeError(
                    "FastAPI runtime dependencies not installed. "
                    "Run 'pip install -e backend/' to install requirements."
                )

        return ScaffoldAppPlaceholder()

    from change_lens.api.errors import install_error_handlers
    from change_lens.api.routes import artifacts, investigations, targets
    from change_lens.api.state import Services
    from change_lens.storage.sqlite import Repository

    settings = settings or get_settings()
    data_dir = resolve_data_path(settings.data_dir)
    services = Services(
        settings=settings,
        repo=repo or Repository(resolve_data_path(settings.sqlite_db_path)),
        archive=archive or _default_archive(settings),
        artifact_roots=[
            (data_dir / "synthetic").resolve(),
            resolve_data_path(settings.previews_dir),
            resolve_data_path(settings.derived_dir),
        ],
    )

    app = FastAPI(
        title="SPHEREx Change Lens API",
        description="API backend for the SPHEREx Change Lens application (2026 NASA Space Apps Challenge).",
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
    )
    app.state.services = services

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID"],
    )

    @app.middleware("http")
    async def request_id(request: Request, call_next: Any) -> Any:
        rid = request.headers.get("X-Request-ID") or f"req_{uuid.uuid4().hex[:12]}"
        request.state.request_id = rid
        response = await call_next(request)
        response.headers["X-Request-ID"] = rid
        return response

    install_error_handlers(app)

    @app.get("/health", tags=["Health"])
    async def health_check() -> dict:
        """Basic healthcheck endpoint for infrastructure monitoring."""
        try:
            services.repo.ping()
            db = "ok"
        except Exception:
            db = "error"
        return {
            "status": "ok" if db == "ok" else "degraded",
            "service": "spherex-change-lens-api",
            "environment": settings.environment,
            "archive": services.archive.name,
            "db": db,
        }

    for router in (targets.router, investigations.router, artifacts.router):
        app.include_router(router, prefix=settings.api_prefix)

    return app


app = create_app()
