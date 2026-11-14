"""Standardized error responses and exceptions for SPHEREx Change Lens."""

from typing import Any


class ChangeLensError(Exception):
    """Base exception for all domain-specific errors."""

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class TargetNotFoundError(ChangeLensError):
    """Raised when a requested target or coordinate search returns no results."""


class ArchiveUnavailableError(ChangeLensError):
    """Raised when upstream NASA/IPAC archives are unreachable or timeout."""


class PipelineProcessingError(ChangeLensError):
    """Raised when alignment, difference, or photometric steps fail."""


class InvestigationNotFoundError(ChangeLensError):
    """Raised when an investigation_id is unknown."""


class ArtifactNotFoundError(ChangeLensError):
    """Raised when an artifact_id is unknown or its file is not servable."""


# --- HTTP mapping: every non-2xx response is an ErrorResponse envelope ---

_STATUS_AND_CODE: dict[type[ChangeLensError], tuple[int, str, bool]] = {
    TargetNotFoundError: (404, "TARGET_NOT_FOUND", False),
    InvestigationNotFoundError: (404, "NOT_FOUND", False),
    ArtifactNotFoundError: (404, "ARTIFACT_NOT_FOUND", False),
    ArchiveUnavailableError: (503, "ARCHIVE_UNAVAILABLE", True),
    PipelineProcessingError: (500, "ANALYSIS_FAILED", False),
}


def install_error_handlers(app: Any) -> None:
    """Register handlers that turn exceptions into ErrorResponse JSON."""
    from fastapi import Request
    from fastapi.exceptions import RequestValidationError
    from fastapi.responses import JSONResponse
    from starlette.exceptions import HTTPException as StarletteHTTPException

    from change_lens.contracts import ErrorDetail, ErrorResponse

    def respond(request: Request, status: int, detail: ErrorDetail) -> JSONResponse:
        rid = getattr(request.state, "request_id", "unknown")
        body = ErrorResponse(error=detail, request_id=rid).model_dump(mode="json")
        return JSONResponse(status_code=status, content=body, headers={"X-Request-ID": rid})

    @app.exception_handler(ChangeLensError)
    async def _domain(request: Request, exc: ChangeLensError) -> JSONResponse:
        status, code, retryable = next(
            (v for k, v in _STATUS_AND_CODE.items() if isinstance(exc, k)),
            (500, "INTERNAL_ERROR", False),
        )
        return respond(
            request,
            status,
            ErrorDetail(code=code, message=exc.message, retryable=retryable, details=exc.details),
        )

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        errors = exc.errors()
        fields = [".".join(str(p) for p in e.get("loc", ()) if p != "body") for e in errors]
        is_coord = any(f.split(".")[-1] in ("ra", "dec") for f in fields)
        message = f"{fields[0]}: {errors[0].get('msg')}" if errors else "Invalid request."
        return respond(
            request,
            422,
            ErrorDetail(
                code="INVALID_COORDINATES" if is_coord else "INVALID_REQUEST",
                message=message,
                details={"fields": fields},
            ),
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = "NOT_FOUND" if exc.status_code == 404 else "INVALID_REQUEST"
        return respond(request, exc.status_code, ErrorDetail(code=code, message=str(exc.detail)))
