"""Coordinate queries and timelines (BE-002, BE-003)."""

import hashlib
import uuid
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter

from change_lens.api.errors import InvestigationNotFoundError, TargetNotFoundError
from change_lens.api.state import ServicesDep
from change_lens.archive.base import DiscoveredEpoch
from change_lens.contracts import (
    CoordinateQueryRequest,
    EvidenceResponse,
    InvestigationMetadata,
    MoversResponse,
    TimelineResponse,
)
from change_lens.investigations.evidence import build_evidence
from change_lens.investigations.movers import screen_movers
from change_lens.targets import NASA_PRESET_TARGETS
from change_lens.timeline.builder import build_timeline

router = APIRouter(prefix="/investigations", tags=["Investigations"])


def _artifact_id(path: Path) -> str:
    """Opaque, stable id for a preview file (never exposes the path)."""
    return "art_" + hashlib.sha256(str(path).encode()).hexdigest()[:16]


@router.post("/query", response_model=InvestigationMetadata, status_code=201)
def create_query(
    req: CoordinateQueryRequest, services: ServicesDep
) -> InvestigationMetadata:
    target_name = None
    if req.target_id is not None:
        target = next((t for t in NASA_PRESET_TARGETS if t.target_id == req.target_id), None)
        if target is None:
            raise TargetNotFoundError(f"Unknown target '{req.target_id}'.", {"target_id": req.target_id})
        target_name = target.name

    result = services.archive.discover(req.ra, req.dec, req.radius_arcsec, detector=req.detector)
    inv_id = f"inv_{uuid.uuid4().hex[:12]}"
    prefix = services.settings.api_prefix

    def preview_url(e: DiscoveredEpoch) -> str | None:
        if e.preview_path is None or not e.preview_path.is_file():
            return None
        art_id = _artifact_id(e.preview_path.resolve())
        services.repo.save_artifact(art_id, e.preview_path, "image/png")
        return f"{prefix}/artifacts/{art_id}/preview"

    timeline = build_timeline(inv_id, result.epochs, preview_url)
    inv = InvestigationMetadata(
        investigation_id=inv_id,
        target_name=target_name,
        ra=req.ra,
        dec=req.dec,
        created_at_utc=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        status="timeline_ready" if timeline.total_epochs else "no_coverage",
    )
    services.repo.save_investigation(inv)
    services.repo.save_timeline(timeline)
    for e in result.epochs:
        if e.source_fits_path is not None:
            services.repo.save_epoch_source(
                inv_id, e.epoch_id, e.mjd, e.source_fits_path, e.detector, e.release
            )
    return inv


@router.get("/{investigation_id}", response_model=InvestigationMetadata)
def get_investigation(
    investigation_id: str, services: ServicesDep
) -> InvestigationMetadata:
    inv = services.repo.get_investigation(investigation_id)
    if inv is None:
        raise InvestigationNotFoundError(f"Investigation '{investigation_id}' not found.")
    return inv


@router.get("/{investigation_id}/timeline", response_model=TimelineResponse)
def get_timeline(
    investigation_id: str, services: ServicesDep
) -> TimelineResponse:
    timeline = services.repo.get_timeline(investigation_id)
    if timeline is None:
        raise InvestigationNotFoundError(f"No timeline for investigation '{investigation_id}'.")
    return timeline


@router.get("/{investigation_id}/movers", response_model=MoversResponse)
def get_movers(investigation_id: str, services: ServicesDep) -> MoversResponse:
    """Run (once, then cached) SCI possible-mover screening on this timeline's frames.

    Can take up to about a minute the first time on real data. Synthetic/mock
    investigations return status UNAVAILABLE.
    """
    if services.repo.get_investigation(investigation_id) is None:
        raise InvestigationNotFoundError(f"Investigation '{investigation_id}' not found.")
    cached = services.repo.get_movers(investigation_id)
    if cached is not None:
        return cached
    from change_lens.config import resolve_data_path

    result = screen_movers(
        investigation_id,
        services.repo.get_epoch_sources(investigation_id),
        cache_dir=resolve_data_path(services.settings.data_dir) / "mover_cache",
    )
    if result.status != "FAILED":
        services.repo.save_movers(result)
    return result


@router.get("/{investigation_id}/evidence", response_model=EvidenceResponse)
def get_evidence(investigation_id: str, services: ServicesDep) -> EvidenceResponse:
    """Run (once, then cached) SCI phase 4 evidence synthesis on this timeline's frames.

    Per-track motion/brightness statuses (SCI-012) plus a first-vs-last frame
    difference image (SCI-011). Shares the SCI run with /movers. Synthetic/mock
    investigations return status UNAVAILABLE.
    """
    if services.repo.get_investigation(investigation_id) is None:
        raise InvestigationNotFoundError(f"Investigation '{investigation_id}' not found.")
    cached = services.repo.get_evidence(investigation_id)
    if cached is not None:
        return cached
    from change_lens.config import resolve_data_path

    result, png = build_evidence(
        investigation_id,
        services.repo.get_epoch_sources(investigation_id),
        derived_dir=resolve_data_path(services.settings.derived_dir),
        cache_dir=resolve_data_path(services.settings.data_dir) / "evidence_cache",
    )
    if result.difference is not None and png is not None:
        art_id = _artifact_id(png.resolve())
        services.repo.save_artifact(art_id, png, "image/png")
        url = f"{services.settings.api_prefix}/artifacts/{art_id}/preview"
        result = result.model_copy(
            update={"difference": result.difference.model_copy(update={"image_url": url})}
        )
    if result.status != "FAILED":
        services.repo.save_evidence(result)
    return result
