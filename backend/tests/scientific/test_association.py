from dataclasses import replace

import pytest
from astropy import units as u
from astropy.coordinates import SkyCoord
from change_lens.pipeline.association import (
    AssociationPolicy,
    EpochDetections,
    associate_sources_across_epochs,
)
from change_lens.pipeline.detection import Quality

from .phase3_helpers import centroid, epoch


def test_stationary_and_deterministic_order():
    inputs = [epoch("c", 60020), epoch("a", 60000), epoch("b", 60010)]
    a = associate_sources_across_epochs(inputs)
    b = associate_sources_across_epochs(list(reversed(inputs)))
    assert a == b
    assert [p.observation_id for p in a.tracks[0].points] == ["a", "b", "c"]
    assert not a.unmatched and not a.ambiguous
    assert a.tracks[0].matches[0].separation_arcsec == 0
    assert a.tracks[0].matches[0].tolerance_arcsec > 2


@pytest.mark.parametrize("ra,dec,angle", [(359.9999, 0, 90), (10, 89.999, 40), (10, -89.999, 220)])
def test_known_shift_wrap_and_poles(ra, dec, angle):
    shifted = SkyCoord(ra * u.deg, dec * u.deg).directional_offset_by(angle * u.deg, 1 * u.arcsec)
    result = associate_sources_across_epochs(
        [epoch("a", 1, centroid(ra, dec)), epoch("b", 2, centroid(shifted.ra.deg, shifted.dec.deg))]
    )
    # Astropy's near-pole synthetic offset roundtrip is accurate to microarcseconds.
    assert result.tracks[0].matches[0].separation_arcsec == pytest.approx(1, abs=2e-6)


@pytest.mark.parametrize("reverse", [False, True])
def test_competing_sources_never_force_nearest(reverse):
    a = (centroid(source_id="left"), centroid(10 + 1 / 3600, source_id="right"))
    b = (centroid(10 + 0.1 / 3600),)
    if reverse:
        a, b = b, a
    result = associate_sources_across_epochs([epoch("a", 1, *a), epoch("b", 2, *b)])
    assert not result.tracks
    assert len(result.ambiguous) == 2
    assert len(result.unmatched) == 3
    assert all("COMPETING_ASSOCIATIONS" in edge.reasons for edge in result.ambiguous)


@pytest.mark.parametrize(
    "change",
    [
        {"quality": Quality.AMBIGUOUS},
        {"valid_fraction": 0.5},
        {"uncertainty_arcsec": None},
        {"uncertainty_arcsec": 100},
        {"warnings": ("POSSIBLE_BLEND",)},
        {"warnings": ("MASK_NEAR_SOURCE",)},
    ],
)
def test_uncertain_position_is_visible_ambiguity(change):
    result = associate_sources_across_epochs([epoch("a", 1), epoch("b", 2, centroid(**change))])
    assert not result.tracks and len(result.ambiguous) == 1
    assert result.ambiguous[0].reasons


@pytest.mark.parametrize(
    "change",
    [
        {"ra_deg": None},
        {"ra_deg": float("nan")},
        {"dec_deg": 91},
        {"ra_deg": 360},
        {"quality": Quality.UNAVAILABLE},
        {"coordinate_frame": "galactic"},
    ],
)
def test_invalid_measurement_unmatched(change):
    result = associate_sources_across_epochs(
        [epoch("a", 1), epoch("b", 2, replace(centroid(), **change))]
    )
    assert not result.tracks and len(result.unmatched) == 2
    assert any("INVALID_POSITION_OR_TIME" in item.reasons for item in result.unmatched)


@pytest.mark.parametrize("time", [None, float("nan"), float("inf")])
def test_invalid_timestamp(time):
    result = associate_sources_across_epochs([epoch("a", 1), epoch("b", time)])
    assert not result.tracks
    assert len(result.unmatched) == 2


def test_unmatched_distance_rejection_and_time_allowance():
    epochs = [epoch("a", 1), epoch("b", 11, centroid(10 + 5 / 3600))]
    result = associate_sources_across_epochs(epochs)
    assert len(result.unmatched) == 2
    assert result.rejected[0].reasons == ("OUTSIDE_TOLERANCE",)
    assert (
        len(
            associate_sources_across_epochs(
                epochs, policy=AssociationPolicy(allowance_arcsec_per_day=0.5)
            ).tracks
        )
        == 1
    )


def test_equal_times_do_not_form_track():
    assert not associate_sources_across_epochs([epoch("a", 1), epoch("b", 1)]).tracks


def test_later_ambiguity_is_not_erased():
    result = associate_sources_across_epochs(
        [
            epoch("a", 1),
            epoch("b", 2),
            epoch("c", 3, centroid(source_id="one"), centroid(10 + 0.1 / 3600, source_id="two")),
            epoch("d", 4),
        ]
    )
    assert len(result.tracks) == 1
    assert result.tracks[0].ambiguous
    assert len(result.tracks[0].points) == 2


def test_missing_epoch_can_be_bridged():
    result = associate_sources_across_epochs(
        [epoch("a", 1), EpochDetections("empty", 2, ()), epoch("b", 3)]
    )
    assert len(result.tracks) == 1


@pytest.mark.parametrize(
    "inputs",
    [
        [epoch("a", 1), epoch("a", 2)],
        [epoch("a", 1, centroid(), centroid())],
        [epoch("a", 1, centroid(source_id=None))],
    ],
)
def test_duplicate_or_missing_identity_rejected(inputs):
    with pytest.raises(ValueError):
        associate_sources_across_epochs(inputs)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"radius_arcsec": 0},
        {"max_radius_arcsec": 1},
        {"uncertainty_multiplier": -1},
        {"min_valid_fraction": 2},
        {"radius_arcsec": float("nan")},
    ],
)
def test_invalid_policy(kwargs):
    with pytest.raises(ValueError):
        AssociationPolicy(**kwargs)
