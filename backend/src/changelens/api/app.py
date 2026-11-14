"""FastAPI application exposing health, target, and local-preview endpoints."""

from __future__ import annotations

import logging
import os
import re
import tempfile
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from changelens.contracts import (
    ErrorCode,
    ErrorDetail,
    ErrorResponse,
    PreviewMetadata,
    PreviewRequest,
    TargetRecord,
)
from changelens.data.previews import (
    DEFAULT_PREVIEW_DIRECTORY,
    PreviewError,
    generate_preview,
    load_source_artifact_from_manifest,
)
from changelens.data.retrieval import DEFAULT_CACHE_DIRECTORY, DEFAULT_MANIFEST_DIRECTORY
from changelens.data.targets import get_target, load_targets

LOGGER = logging.getLogger("uvicorn.error")
REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
PREVIEW_ID_PATTERN = re.compile(r"^art_preview_[a-f0-9]{24}$")
LOCAL_FRONTEND_ORIGINS = (
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
)


def _request_id(request: Request) -> str:
    value = request.headers.get("X-Request-ID", "")
    if REQUEST_ID_PATTERN.fullmatch(value):
        return value
    return uuid4().hex


def _error_response(
    request: Request,
    *,
    code: ErrorCode,
    message: str,
    retryable: bool,
    status_code: int,
    details: dict[str, object] | None = None,
) -> JSONResponse:
    request_id = getattr(request.state, "request_id", uuid4().hex)
    model = ErrorResponse(
        error=ErrorDetail(
            code=code,
            message=message,
            retryable=retryable,
            details=details or {},
        ),
        request_id=request_id,
    )
    response = JSONResponse(status_code=status_code, content=model.model_dump(mode="json"))
    response.headers["X-Request-ID"] = request_id
    return response


def _storage_is_writable(directory: Path) -> bool:
    if not directory.is_dir():
        return False
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", prefix=".readiness-", dir=directory, delete=True
        ):
            pass
    except OSError:
        return False
    return True


def create_app(
    *,
    cache_directory: Path | None = None,
    manifest_directory: Path | None = None,
    preview_directory: Path | None = None,
) -> FastAPI:
    configured_cache = cache_directory
    if configured_cache is None:
        environment_value = os.environ.get("CHANGELENS_CACHE_DIR")
        configured_cache = Path(environment_value) if environment_value else DEFAULT_CACHE_DIRECTORY

    api = FastAPI(
        title="SPHEREx Change Lens API",
        description="Draft data and health endpoints for the SPHEREx Change Lens prototype.",
        version="0.1.0",
    )
    api.state.cache_directory = configured_cache
    api.state.manifest_directory = manifest_directory or DEFAULT_MANIFEST_DIRECTORY
    api.state.preview_directory = preview_directory or DEFAULT_PREVIEW_DIRECTORY

    api.add_middleware(
        CORSMiddleware,
        allow_origins=list(LOCAL_FRONTEND_ORIGINS),
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "X-Request-ID"],
        expose_headers=["X-Request-ID"],
    )

    @api.middleware("http")
    async def request_id_middleware(request: Request, call_next):
        request_id = _request_id(request)
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        LOGGER.info(
            "request_complete request_id=%s method=%s path=%s status_code=%d",
            request_id,
            request.method,
            request.url.path,
            response.status_code,
        )
        return response

    @api.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError):
        issues = [
            {
                "location": [str(part) for part in item.get("loc", ())],
                "message": item.get("msg", "Invalid value"),
                "type": item.get("type", "validation_error"),
            }
            for item in exc.errors()
        ]
        return _error_response(
            request,
            code=ErrorCode.INVALID_COORDINATES,
            message="The request did not match the expected input schema.",
            retryable=False,
            status_code=422,
            details={"issues": issues},
        )

    @api.exception_handler(StarletteHTTPException)
    async def http_error_handler(request: Request, exc: StarletteHTTPException):
        if exc.status_code == 404:
            code = ErrorCode.ARTIFACT_NOT_FOUND
        elif exc.status_code >= 500:
            code = ErrorCode.ARCHIVE_UNAVAILABLE
        else:
            code = ErrorCode.ANALYSIS_FAILED
        message = (
            exc.detail if isinstance(exc.detail, str) else "The request could not be completed."
        )
        return _error_response(
            request,
            code=code,
            message=message,
            retryable=exc.status_code >= 500,
            status_code=exc.status_code,
        )

    @api.exception_handler(PreviewError)
    async def preview_error_handler(request: Request, exc: PreviewError):
        if exc.code is ErrorCode.ARTIFACT_NOT_FOUND:
            status_code = 404
        elif exc.code is ErrorCode.ANALYSIS_FAILED:
            status_code = 500
        else:
            status_code = 422
        return _error_response(
            request,
            code=exc.code,
            message=str(exc),
            retryable=exc.retryable,
            status_code=status_code,
            details=exc.details,
        )

    @api.exception_handler(Exception)
    async def unexpected_error_handler(request: Request, exc: Exception):
        LOGGER.error(
            "request_failed request_id=%s exception_type=%s",
            getattr(request.state, "request_id", "unknown"),
            type(exc).__name__,
        )
        return _error_response(
            request,
            code=ErrorCode.ANALYSIS_FAILED,
            message="An unexpected server error occurred.",
            retryable=False,
            status_code=500,
        )

    @api.get("/health/live", tags=["health"])
    def health_live() -> dict[str, str]:
        return {"status": "live"}

    @api.get("/health/ready", tags=["health"])
    def health_ready() -> JSONResponse:
        storage_available = _storage_is_writable(api.state.cache_directory)
        body = {
            "status": "ready" if storage_available else "not_ready",
            "storage": "available" if storage_available else "unavailable",
        }
        return JSONResponse(status_code=200 if storage_available else 503, content=body)

    @api.get("/v1/targets", response_model=list[TargetRecord], tags=["targets"])
    def targets() -> list[TargetRecord]:
        return list(load_targets())

    @api.post("/v1/previews", response_model=PreviewMetadata, tags=["previews"])
    def create_preview(payload: PreviewRequest) -> PreviewMetadata:
        source_artifact = load_source_artifact_from_manifest(
            payload.source_artifact_id,
            manifest_directory=api.state.manifest_directory,
        )
        try:
            target = get_target(payload.target_id)
        except KeyError as exc:
            raise StarletteHTTPException(
                status_code=404,
                detail="The requested target is not present in the local registry.",
            ) from exc
        return generate_preview(
            source_artifact,
            target,
            fov_arcmin=payload.fov_arcmin,
            cache_directory=api.state.cache_directory,
            manifest_directory=api.state.manifest_directory,
            preview_directory=api.state.preview_directory,
        )

    @api.get(
        "/v1/previews/{artifact_id}.png",
        response_class=FileResponse,
        tags=["previews"],
    )
    def read_preview(artifact_id: str) -> FileResponse:
        if not PREVIEW_ID_PATTERN.fullmatch(artifact_id):
            raise StarletteHTTPException(status_code=404, detail="Preview artifact not found.")
        preview_path = api.state.preview_directory / f"{artifact_id}.png"
        if not preview_path.is_file():
            raise StarletteHTTPException(status_code=404, detail="Preview artifact not found.")
        return FileResponse(
            preview_path,
            media_type="image/png",
            headers={"Cache-Control": "no-store"},
        )

    return api


app = create_app()


__all__ = ["app", "create_app"]
