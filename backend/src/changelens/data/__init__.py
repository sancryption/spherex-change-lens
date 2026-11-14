"""Archive discovery, retrieval, and local-preview helpers."""

from changelens.data.catalogue import (
    AllWISEAdapter,
    CatalogueAdapter,
    CatalogueCandidate,
    CatalogueContext,
    CatalogueContextStatus,
    CatalogueEnrichment,
    CatalogueMatch,
    GaiaDR3Adapter,
    add_catalogue_context,
)
from changelens.data.coverage import build_coverage_report, build_timeline_manifest
from changelens.data.discovery import discover
from changelens.data.previews import (
    PreviewError,
    generate_preview,
    load_source_artifact_from_manifest,
)
from changelens.data.retrieval import retrieve

__all__ = [
    "AllWISEAdapter",
    "CatalogueAdapter",
    "CatalogueCandidate",
    "CatalogueContext",
    "CatalogueContextStatus",
    "CatalogueEnrichment",
    "CatalogueMatch",
    "GaiaDR3Adapter",
    "PreviewError",
    "add_catalogue_context",
    "build_coverage_report",
    "build_timeline_manifest",
    "discover",
    "generate_preview",
    "load_source_artifact_from_manifest",
    "retrieve",
]
