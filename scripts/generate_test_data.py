#!/usr/bin/env python3
"""SPHEREx Change Lens - Deterministic Synthetic Test Data Generator.

This script creates small, deterministic test fixtures in data/synthetic/
strictly for automated unit testing and pipeline configuration tests.
No real NASA data is downloaded and no fake production observations are generated.
"""

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SYNTHETIC_DIR = REPO_ROOT / "data" / "synthetic"


def generate_synthetic_manifest() -> Path:
    """Generate a minimal deterministic test manifest fixture."""
    SYNTHETIC_DIR.mkdir(parents=True, exist_ok=True)
    manifest_path = SYNTHETIC_DIR / "sample_synthetic_manifest.json"

    data = {
        "dataset_type": "synthetic_scaffold_fixture",
        "description": "Deterministic fixture for pipeline configuration testing only",
        "simulated_epochs": [
            {
                "epoch_index": 0,
                "timestamp_utc": "2026-01-01T00:00:00Z",
                "dimensions": [64, 64],
                "band": "SPHEREx_Band_1",
                "notes": "Placeholder dimension for test suite; actual FITS generation pending SCI workstream",
            },
            {
                "epoch_index": 1,
                "timestamp_utc": "2026-06-01T00:00:00Z",
                "dimensions": [64, 64],
                "band": "SPHEREx_Band_1",
                "notes": "Simulated displacement vector fixture pending pipeline implementation",
            }
        ]
    }

    manifest_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"Generated synthetic test fixture manifest: {manifest_path}")
    return manifest_path


def main() -> None:
    print("Generating deterministic test fixtures for scaffold testing...")
    generate_synthetic_manifest()
    print("Generation complete.")


if __name__ == "__main__":
    main()
