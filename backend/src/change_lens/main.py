"""Application entrypoint and factory placeholder for SPHEREx Change Lens."""

from typing import Any

from change_lens.config import get_settings


def create_app() -> Any:
    """Create and configure the FastAPI application instance.

    Scaffold placeholder: Does not implement feature routes or scientific endpoints.
    """
    try:
        from fastapi import FastAPI
        from fastapi.middleware.cors import CORSMiddleware

        settings = get_settings()
        app = FastAPI(
            title="SPHEREx Change Lens API",
            description="API backend for the SPHEREx Change Lens application (2026 NASA Space Apps Challenge).",
            version="0.1.0",
            docs_url="/docs",
            redoc_url="/redoc",
        )

        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

        @app.get("/health", tags=["Health"])
        async def health_check() -> dict:
            """Basic healthcheck endpoint for infrastructure monitoring."""
            return {
                "status": "ok",
                "service": "spherex-change-lens-api",
                "environment": settings.environment,
                "scaffold_mode": True,
            }

        return app

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


app = create_app()
