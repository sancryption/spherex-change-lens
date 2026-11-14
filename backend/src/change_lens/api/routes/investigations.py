"""Coordinate queries and timelines (BE-002, BE-003)."""

import hashlib
import uuid
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter

from change_lens.api.errors import InvestigationNotFoundError, TargetNotFoundError
from change_lens.api.state import ServicesDep
from change_lens.archive.base import DiscoveredEpoch
from change_lens.contracts import CoordinateQueryRequest, InvestigationMetadata, TimelineResponse
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
