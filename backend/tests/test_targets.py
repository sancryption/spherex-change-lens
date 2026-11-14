from __future__ import annotations

import json
from pathlib import Path

import pytest
from changelens.data.targets import get_target, load_targets
from pydantic import ValidationError

EXPECTED_TARGET_IDS = {
    "barnards_star",
    "epsilon_indi_b",
    "wise_0855",
    "rw_aurigae",
    "r_draconis",
}


def test_target_registry_contains_all_five_nasa_targets() -> None:
    targets = load_targets()

    assert {target.target_id for target in targets} == EXPECTED_TARGET_IDS
    assert len(targets) == 5


def test_all_registry_targets_start_unverified() -> None:
    targets = load_targets()

    assert all(target.coverage_status.value == "UNVERIFIED" for target in targets)
    assert all(target.verification_level.value == "UNVERIFIED" for target in targets)


def test_wise_0855_coordinates_match_the_challenge_exactly() -> None:
    target = get_target("wise_0855")

    assert target.ra_deg == 133.7951291667
    assert target.dec_deg == -7.2451472222


def test_target_lookup_is_case_insensitive_and_returns_a_copy() -> None:
    first = get_target("BARNARDS_STAR")
    original_notes = first.notes.copy()
    first.notes.append("local mutation")
    second = get_target("barnards_star")

    assert second.notes == original_notes


def test_invalid_registry_entries_fail_validation(tmp_path: Path) -> None:
    registry_path = tmp_path / "targets.json"
    registry_path.write_text(json.dumps([{"target_id": "broken"}]), encoding="utf-8")

    with pytest.raises(ValidationError):
        load_targets(registry_path)
