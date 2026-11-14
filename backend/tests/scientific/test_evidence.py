"""SCI-012 tests built on actual synthetic Phase 1-3 outputs."""

from dataclasses import replace

import pytest
from change_lens.pipeline.difference import compute_difference
from change_lens.pipeline.evidence import synthesize_evidence
from change_lens.pipeline.phase3 import run_phase3

from .phase3_helpers import diagnostics_for, full_phase2


def pipeline(tmp_path, scenario="stationary"):
    phase2, _ = full_phase2(tmp_path, scenario)
    phase3 = run_phase3(phase2, static_track_ids=("track_0002",), diagnostics=diagnostics_for())
    return phase2, phase3


@pytest.mark.parametrize(
    "scenario,status",
    [
        ("moving", "POSSIBLE_POSITIONAL_MOVEMENT"),
        ("variable", "POSSIBLE_BRIGHTNESS_VARIATION"),
        ("stationary", "NO_RELIABLE_CHANGE"),
        ("artifact", "ARTIFACT_RISK"),
        ("registration", "ARTIFACT_RISK"),
    ],
)
def test_final_screened_scenarios_without_difference(tmp_path, scenario, status):
    _, phase3 = pipeline(tmp_path, scenario)
    result = synthesize_evidence(phase3)
    target = result.tracks[0]
    assert status in target.statuses
    assert target.screened is phase3.tracks[0]
    assert target.association is phase3.association.tracks[0]
    assert target.screened.preliminary_motion.displacement.uncertainty_arcsec > 0
    assert target.screened.preliminary_brightness.measurements[0].uncertainty > 0
    assert "DIFFERENCE_UNAVAILABLE" in result.reason_codes
    assert result == synthesize_evidence(phase3)
    assert target.reason_codes == synthesize_evidence(phase3).tracks[0].reason_codes
    assert target.association.points[0].observation_id == "a"
    assert target.association.points[0].provenance["validation"]["metadata"]["SYNTHET"]


def test_missing_controls_not_upgraded_by_difference(tmp_path):
    phase2, _ = full_phase2(tmp_path, "moving")
    phase3 = run_phase3(phase2)
    product = compute_difference(*phase2.alignment.frames)
    result = synthesize_evidence(phase3, differences=(product,))
    assert result.tracks[0].statuses == ("AMBIGUOUS",)
    assert result.differences[0].availability == "AVAILABLE"
    assert "NONZERO_RESIDUAL_PIXELS" in result.differences[0].reason_codes


def test_artifact_cannot_be_overridden_by_preliminary_or_difference(tmp_path):
    phase2, phase3 = pipeline(tmp_path, "artifact")
    target = replace(phase3.tracks[0], motion_status="POSSIBLE_POSITIONAL_MOVEMENT")
    phase3 = replace(phase3, tracks=(target,))
    result = synthesize_evidence(
        phase3, differences=(compute_difference(*phase2.alignment.frames),)
    )
    assert result.tracks[0].statuses == ("ARTIFACT_RISK",)
    assert result.tracks[0].screened.controls.motion_status == "ARTIFACT_SUSPECT"


def test_ambiguous_associations_and_unmatched_preserved(tmp_path):
    phase2, _ = full_phase2(tmp_path)
    source = phase2.centroids[1][0]
    competitor = replace(source, source_id="competitor", ra_deg=source.ra_deg + 0.2 / 3600)
    phase2 = replace(phase2, centroids=(phase2.centroids[0], (*phase2.centroids[1], competitor)))
    phase3 = run_phase3(phase2)
    result = synthesize_evidence(phase3)
    assert result.association is phase3.association
    assert result.association.ambiguous and result.association.unmatched
    assert "AMBIGUOUS_ASSOCIATIONS_RETAINED" in result.reason_codes
    assert not any(t.track_id == "track_0001" for t in result.tracks)


def test_conflicting_domain_evidence_remains_visible(tmp_path):
    _, phase3 = pipeline(tmp_path, "moving")
    target = phase3.tracks[0]
    # A motion change and brightness ambiguity are not collapsed into a clean claim.
    target = replace(target, brightness_status="AMBIGUOUS")
    result = synthesize_evidence(replace(phase3, tracks=(target,)))
    assert result.tracks[0].statuses == ("POSSIBLE_POSITIONAL_MOVEMENT", "AMBIGUOUS")
    # A final label contradicting the underlying measurement is not supported.
    target = replace(target, preliminary_motion=replace(target.preliminary_motion, status="STABLE"))
    result = synthesize_evidence(replace(phase3, tracks=(target,)))
    assert result.tracks[0].statuses == ("AMBIGUOUS",)
    assert "INCONSISTENT_MOTION_EVIDENCE" in result.tracks[0].reason_codes


@pytest.mark.parametrize("kind", ["rejected", "unavailable", "unrelated", "wrong_provenance"])
def test_unusable_difference_never_means_no_change(tmp_path, kind):
    phase2, phase3 = pipeline(tmp_path, "variable")
    a, b = phase2.alignment.frames
    if kind == "rejected":
        b.provenance["plane_identity"]["band"] = "wrong"
    elif kind == "unavailable":
        b.variance[:] = 0
    product = compute_difference(a, b)
    if kind == "unrelated":
        product = replace(product, later_mjd_utc=61000)
    if kind == "wrong_provenance":
        product.provenance["later"]["plane_identity"]["band"] = "wrong"
    result = synthesize_evidence(phase3, differences=(product,))
    assert result.differences[0].availability == "UNAVAILABLE"
    assert result.differences[0].minimum is None
    assert "POSSIBLE_BRIGHTNESS_VARIATION" in result.tracks[0].statuses


def test_zero_difference_not_a_source_stability_vote(tmp_path):
    phase2, phase3 = pipeline(tmp_path, "moving")
    a, b = phase2.alignment.frames
    b.image[:] = a.image
    product = compute_difference(a, b)
    result = synthesize_evidence(phase3, differences=(product,))
    assert "POSSIBLE_POSITIONAL_MOVEMENT" in result.tracks[0].statuses
    assert result.differences[0].minimum == result.differences[0].maximum == 0
    assert "ZERO_RESIDUAL_PIXELS" in result.differences[0].reason_codes
    assert result == synthesize_evidence(phase3, differences=(product,))


def test_empty_result_preserves_insufficiency(tmp_path):
    phase2, _ = full_phase2(tmp_path)
    phase2.alignment.frames[1].provenance["validation"]["metadata"].pop("MJD-OBS")
    result = synthesize_evidence(run_phase3(phase2))
    assert not result.tracks
    assert "INSUFFICIENT_EVIDENCE" in result.reason_codes
    assert result.association.unmatched


def test_duplicate_difference_not_double_counted(tmp_path):
    phase2, phase3 = pipeline(tmp_path)
    product = compute_difference(*phase2.alignment.frames)
    with pytest.raises(ValueError, match="DUPLICATE_DIFFERENCE_PAIR"):
        synthesize_evidence(phase3, differences=(product, product))


def test_mismatched_and_duplicate_track_ids_rejected(tmp_path):
    _, phase3 = pipeline(tmp_path)
    target = phase3.tracks[0]
    with pytest.raises(ValueError, match="EVIDENCE_TRACK_ID_MISMATCH"):
        synthesize_evidence(replace(phase3, tracks=(replace(target, track_id="unknown"),)))
    with pytest.raises(ValueError, match="DUPLICATE_TRACK_ID"):
        synthesize_evidence(replace(phase3, tracks=(target, target)))


def test_track_order_is_deterministic(tmp_path):
    _, phase3 = pipeline(tmp_path)
    assert synthesize_evidence(phase3) == synthesize_evidence(
        replace(phase3, tracks=phase3.tracks[::-1])
    )
