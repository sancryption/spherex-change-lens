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
