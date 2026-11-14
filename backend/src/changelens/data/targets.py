"""Load the NASA challenge target registry from committed JSON."""

from __future__ import annotations

import json
from pathlib import Path

from changelens.contracts import TargetRecord


REGISTRY_PATH = Path(__file__).resolve().parents[4] / "data" / "targets" / "targets.json"


def load_targets(path: Path | None = None) -> tuple[TargetRecord, ...]:
    """Read and validate the target registry, preserving its declared order."""

    registry_path = path or REGISTRY_PATH
    payload = json.loads(registry_path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("target registry must contain a JSON array")
    return tuple(TargetRecord.model_validate(item) for item in payload)


def get_target(target_id: str, path: Path | None = None) -> TargetRecord:
    """Return a case-insensitive target lookup as an isolated model copy."""

    normalized_id = target_id.strip().casefold()
    for target in load_targets(path):
        if target.target_id.casefold() == normalized_id:
            return target.model_copy(deep=True)
    raise KeyError(f"unknown target: {target_id}")
