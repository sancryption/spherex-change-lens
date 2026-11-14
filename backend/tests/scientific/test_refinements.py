"""Synthetic refinements; defaults and scientific boundaries remain conservative."""

from dataclasses import replace

import pytest
from change_lens.pipeline.association import AssociationPolicy, associate_sources_across_epochs
from change_lens.pipeline.brightness import extract_grouped_photometry, extract_photometry
from change_lens.pipeline.phase3 import possible_movers, run_phase3

from .phase3_helpers import centroid, diagnostics_for, epoch, frames_and_track, full_phase2


@pytest.mark.parametrize(
    "days,rate,matched", [(10, 0.03, False), (100, 0.03, True), (100, 0, False), (100, 0.01, False)]
)
def test_elapsed_motion_allowance(days, rate, matched):
    inputs = [epoch("a", 60000), epoch("b", 60000 + days, centroid(10 + 4 / 3600))]
    result = associate_sources_across_epochs(
        inputs, policy=AssociationPolicy(allowance_arcsec_per_day=rate)
    )
    assert bool(result.tracks) == matched
    assert result == associate_sources_across_epochs(
        list(reversed(inputs)), policy=AssociationPolicy(allowance_arcsec_per_day=rate)
    )
    if matched:
        assert result.tracks[0].matches[0].tolerance_arcsec == pytest.approx(
            2 + 3 * 2**0.5 * 0.02 + days * rate
        )


def test_expanded_search_retains_competition():
    result = associate_sources_across_epochs(
        [
            epoch("a", 60000),
            epoch(
                "b",
                60100,
                centroid(10 + 4 / 3600, source_id="one"),
                centroid(10 + 4.5 / 3600, source_id="two"),
            ),
        ],
        policy=AssociationPolicy(allowance_arcsec_per_day=0.03),
    )
    assert not result.tracks and len(result.ambiguous) == 2


@pytest.mark.parametrize("time", [None, float("nan"), float("inf")])
def test_allowance_cannot_invent_baseline(time):
    result = associate_sources_across_epochs(
        [epoch("a", 60000), epoch("b", time)],
        policy=AssociationPolicy(allowance_arcsec_per_day=0.03),
    )
    assert not result.tracks and len(result.unmatched) == 2


@pytest.mark.parametrize("amplitudes,state", [((80, 160), "BRIGHTER"), ((80, 80), "STABLE")])
def test_same_band_group(prepared, amplitudes, state):
    frames, track = frames_and_track(prepared, amplitudes=amplitudes)
    result = extract_grouped_photometry(track, frames)
    assert len(result.groups) == 1 and not result.unavailable
    assert result.groups[0].result.status == state


def test_multiple_bands_compare_only_within_groups(prepared):
    frames, track = frames_and_track(prepared, amplitudes=(80, 160, 80, 80), backgrounds=(12,) * 4)
    for name in ("c", "d"):
        frames[name].provenance["plane_identity"]["band"] = "other-band"
        frames[name].provenance["plane_identity"]["spectral_plane"] = "other-channel"
    assert extract_photometry(track, frames).status == "UNAVAILABLE"
    result = extract_grouped_photometry(track, frames)
    assert {g.result.status for g in result.groups} == {"BRIGHTER", "STABLE"}
    for group in result.groups:
        assert len(group.result.comparisons) == 1
    assert result == extract_grouped_photometry(
        replace(track, points=tuple(reversed(track.points))), frames
    )


@pytest.mark.parametrize("field", ["band", "spectral_plane", "release"])
def test_missing_band_identity_retained_unavailable(prepared, field):
    frames, track = frames_and_track(prepared)
    frames["b"].provenance["plane_identity"].pop(field)
    result = extract_grouped_photometry(track, frames)
    assert len(result.unavailable) == 1
    assert result.unavailable[0].status == "UNAVAILABLE"
    assert result.groups[0].result.status == "UNAVAILABLE"


@pytest.mark.parametrize("field,value", [("band", "different"), ("spectral_plane", "adjacent")])
def test_cross_band_singletons_unavailable(prepared, field, value):
    frames, track = frames_and_track(prepared)
    frames["b"].provenance["plane_identity"][field] = value
    result = extract_grouped_photometry(track, frames)
    assert len(result.groups) == 2
    assert all(g.result.status == "UNAVAILABLE" and not g.result.comparisons for g in result.groups)


def test_conflicting_header_is_not_trusted(prepared):
    frames, track = frames_and_track(prepared)
    frames["b"].provenance["validation"]["metadata"]["BAND"] = "conflict"
    result = extract_grouped_photometry(track, frames)
    assert "PLANE_IDENTITY_CONFLICTS_WITH_HEADER" in result.unavailable[0].warnings


@pytest.mark.parametrize(
    "scenario,expected",
    [("moving", 1), ("stationary", 0), ("artifact", 0), ("ambiguous", 0), ("registration", 0)],
)
def test_possible_mover_from_final_screening(tmp_path, scenario, expected):
    phase2, _ = full_phase2(tmp_path, scenario)
    policy = (
        AssociationPolicy(radius_arcsec=12, max_radius_arcsec=20)
        if scenario == "ambiguous"
        else None
    )
    result = run_phase3(
        phase2,
        association_policy=policy,
        static_track_ids=("track_0002",),
        diagnostics=diagnostics_for(),
    )
    candidates = possible_movers(result)
    assert len(candidates) == expected
    assert candidates == possible_movers(result)
    if candidates:
        candidate = candidates[0]
        assert candidate.label == "possible_mover" and candidate.control_status == "SUPPORTED"
        assert candidate.displacement_arcsec == pytest.approx(1, abs=0.01)
        assert candidate.baseline_days == 10 and candidate.uncertainty_arcsec > 0
        assert candidate.reason_codes and candidate.limitations


def test_preliminary_mover_missing_controls_is_excluded(tmp_path):
    phase2, _ = full_phase2(tmp_path, "moving")
    result = run_phase3(phase2)
    assert result.tracks[0].preliminary_motion.status == "POSSIBLE_MOVEMENT"
    assert not possible_movers(result)
    phase2.alignment.frames[1].provenance["validation"]["metadata"].pop("MJD-OBS")
    assert not possible_movers(run_phase3(phase2))
