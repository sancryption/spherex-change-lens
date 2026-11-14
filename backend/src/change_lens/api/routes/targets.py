"""GET /targets and GET /targets/{target_id}/coverage."""

from fastapi import APIRouter

from change_lens.api.errors import TargetNotFoundError
from change_lens.api.state import ServicesDep
from change_lens.contracts import TargetCoverageResponse, TargetListResponse
from change_lens.targets import NASA_PRESET_TARGETS

router = APIRouter(prefix="/targets", tags=["Targets"])


@router.get("", response_model=TargetListResponse)
def list_targets() -> TargetListResponse:
    return TargetListResponse(targets=NASA_PRESET_TARGETS, total_count=len(NASA_PRESET_TARGETS))


@router.get("/{target_id}/coverage", response_model=TargetCoverageResponse)
def target_coverage(target_id: str, services: ServicesDep) -> TargetCoverageResponse:
    target = next((t for t in NASA_PRESET_TARGETS if t.target_id == target_id), None)
    if target is None:
        raise TargetNotFoundError(f"Unknown target '{target_id}'.", {"target_id": target_id})
    result = services.archive.discover(target.ra, target.dec, radius_arcsec=30.0)
    authentic = [e for e in result.epochs if e.data_origin != "synthetic"]
    # Mock/synthetic coverage never counts as verified.
    if not result.epochs:
        status = "no_coverage"
    elif authentic and all(not e.warnings for e in authentic):
        status = "verified"
    else:
        status = "pending_verification"
    return TargetCoverageResponse(
        target_id=target.target_id,
        ra=target.ra,
        dec=target.dec,
        available_epochs_count=len(result.epochs),
        spectral_bands=sorted({e.band_id for e in result.epochs}),
        verification_status=status,
    )
