"""Safe preview delivery (BE-006). Only opaque IDs are accepted, never paths."""

from fastapi import APIRouter
from fastapi.responses import FileResponse

from change_lens.api.errors import ArtifactNotFoundError
from change_lens.api.state import ServicesDep

router = APIRouter(prefix="/artifacts", tags=["Artifacts"])

MAX_BYTES = 50 * 1024 * 1024


@router.get("/{artifact_id}/preview")
def artifact_preview(artifact_id: str, services: ServicesDep) -> FileResponse:
    found = services.repo.get_artifact(artifact_id)
    if found is None:
        raise ArtifactNotFoundError(f"Artifact '{artifact_id}' not found.")
    path, media_type = found
    path = path.resolve()
    if not any(path.is_relative_to(root) for root in services.artifact_roots):
        raise ArtifactNotFoundError(f"Artifact '{artifact_id}' not found.")
    if not path.is_file() or path.stat().st_size > MAX_BYTES or not media_type.startswith("image/"):
        raise ArtifactNotFoundError(f"Artifact '{artifact_id}' is not available.")
    return FileResponse(path, media_type=media_type)
