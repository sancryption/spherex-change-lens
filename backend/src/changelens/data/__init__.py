"""Archive discovery, retrieval, and local-preview helpers."""

from changelens.data.coverage import build_coverage_report, build_timeline_manifest
from changelens.data.discovery import discover
from changelens.data.previews import (
    PreviewError,
    generate_preview,
    load_source_artifact_from_manifest,
)
from changelens.data.retrieval import retrieve

__all__ = [
    "PreviewError",
    "build_coverage_report",
    "build_timeline_manifest",
    "discover",
    "generate_preview",
    "load_source_artifact_from_manifest",
    "retrieve",
]
