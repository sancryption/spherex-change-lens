import ast
import hashlib
from dataclasses import replace
from pathlib import Path

import pytest
from change_lens.pipeline import brightness, controls, motion
from change_lens.pipeline.association import AssociationPolicy
from change_lens.pipeline.phase3 import observation_time, run_phase3

from .phase3_helpers import diagnostics_for, full_phase2


@pytest.mark.parametrize(
    "scenario,motion_state,brightness_state",
    [
        ("stationary", "NO_RELIABLE_CHANGE", "NO_RELIABLE_CHANGE"),
        ("moving", "POSSIBLE_POSITIONAL_MOVEMENT", "NO_RELIABLE_CHANGE"),
        ("variable", "NO_RELIABLE_CHANGE", "POSSIBLE_BRIGHTNESS_VARIATION"),
        ("artifact", "ARTIFACT_RISK", "ARTIFACT_RISK"),
    ],
)
def test_synthetic_fits_end_to_end(tmp_path, scenario, motion_state, brightness_state):
    phase2, paths = full_phase2(tmp_path, scenario)
    before = [hashlib.sha256(p.read_bytes()).hexdigest() for p in paths]
    result = run_phase3(phase2, static_track_ids=("track_0002",), diagnostics=diagnostics_for())
    assert len(result.tracks) == 2
    target = result.tracks[0]
    assert target.motion_status == motion_state
    assert target.brightness_status == brightness_state
    assert target.preliminary_motion.displacement is not None
    assert target.preliminary_brightness.measurements
    assert result == run_phase3(
        phase2, static_track_ids=("track_0002",), diagnostics=diagnostics_for()
    )
    assert [hashlib.sha256(p.read_bytes()).hexdigest() for p in paths] == before


def test_ambiguous_association_end_to_end(tmp_path):
    phase2, _ = full_phase2(tmp_path)
    source = phase2.centroids[1][0]
    competitor = replace(source, source_id="competitor", ra_deg=source.ra_deg + 0.2 / 3600)
    phase2 = replace(phase2, centroids=(phase2.centroids[0], (*phase2.centroids[1], competitor)))
    result = run_phase3(phase2)
    assert len(result.association.ambiguous) == 2
    assert len(result.tracks) == 1
    assert result.tracks[0].track_id == "track_0002"
    assert "AMBIGUOUS_ASSOCIATIONS_RETAINED" in result.warnings


def test_ambiguous_sources_from_fits(tmp_path):
    phase2, _ = full_phase2(tmp_path, "ambiguous")
    result = run_phase3(
        phase2, association_policy=AssociationPolicy(radius_arcsec=12, max_radius_arcsec=20)
    )
    assert result.association.ambiguous
    assert not any(t.track_id == "track_0001" for t in result.tracks)
    assert "AMBIGUOUS_ASSOCIATIONS_RETAINED" in result.warnings


def test_missing_controls_downgrade_keeps_preliminary(tmp_path):
    phase2, _ = full_phase2(tmp_path, "moving")
    result = run_phase3(phase2)
    target = result.tracks[0]
    assert target.preliminary_motion.status == "POSSIBLE_MOVEMENT"
    assert target.motion_status == "AMBIGUOUS"


def test_shared_registration_shift_is_downgraded(tmp_path):
    phase2, _ = full_phase2(tmp_path, "registration")
    result = run_phase3(phase2, static_track_ids=("track_0002",), diagnostics=diagnostics_for())
    target = result.tracks[0]
    assert target.preliminary_motion.status == "POSSIBLE_MOVEMENT"
    assert target.motion_status == "ARTIFACT_RISK"
    assert any("STATIC_CONTROL_CHANGED" in check.reasons for check in target.controls.checks)


def test_bad_alignment_stops_phase3(tmp_path):
    phase2, _ = full_phase2(tmp_path)
    phase2.alignment.status = "INCOMPATIBLE_PRODUCT"
    result = run_phase3(phase2)
    assert not result.tracks
    assert "ALIGNMENT_NOT_USABLE" in result.warnings


def test_missing_time_preserves_unmatched(tmp_path):
    phase2, _ = full_phase2(tmp_path)
    phase2.alignment.frames[1].provenance["validation"]["metadata"].pop("MJD-OBS")
    result = run_phase3(phase2)
    assert not result.tracks
    assert len(result.association.unmatched) == 4
    assert "b:MISSING_OBSERVATION_TIME" in result.warnings


def test_duplicate_observation_id_rejected(tmp_path):
    phase2, _ = full_phase2(tmp_path)
    phase2.alignment.frames[1].provenance["validation"]["observation_id"] = "a"
    with pytest.raises(ValueError, match="UNIQUE_OBSERVATION_IDS"):
        run_phase3(phase2)


@pytest.mark.parametrize(
    "metadata,reason",
    [
        ({}, "MISSING_OBSERVATION_TIME"),
        ({"MJD-OBS": "nan"}, "INVALID_OBSERVATION_TIME"),
        ({"DATE-OBS": "bad"}, "INVALID_OBSERVATION_TIME"),
        ({"MJD-OBS": "60000", "DATE-OBS": "2023-02-26T00:00:00"}, "CONFLICTING_OBSERVATION_TIMES"),
    ],
)
def test_invalid_times(metadata, reason):
    assert observation_time(metadata) == (None, (reason,))


def test_both_timestamp_formats():
    assert observation_time({"MJD-OBS": "60000", "DATE-OBS": "2023-02-25T00:00:00"}) == (60000, ())


def test_two_stage_import_boundary_and_no_measurement_recalculation():
    for module in (motion, brightness):
        tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8-sig"))
        imports = [node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
        assert not any(
            name and (name.endswith("controls") or name.endswith("phase3")) for name in imports
        )
    tree = ast.parse(Path(controls.__file__).read_text(encoding="utf-8-sig"))
    calls = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert not calls.intersection(
        {"estimate_source_motion", "extract_photometry", "measure_aperture", "run_phase3"}
    )
