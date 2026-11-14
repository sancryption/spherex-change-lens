from dataclasses import replace

import pytest
from astropy import units as u
from astropy.coordinates import SkyCoord
from change_lens.pipeline.association import SourceTrack
from change_lens.pipeline.motion import MotionPolicy, estimate_source_motion

from .phase3_helpers import track


def test_stationary_has_no_direction_and_valid_uncertainty():
    result = estimate_source_motion(track(0))
    assert result.status == "STABLE"
    assert result.displacement.angular_arcsec == 0
    assert result.displacement.position_angle_deg is None
    assert result.displacement.uncertainty_arcsec == pytest.approx(2**0.5 * 0.02)
    assert result.displacement.baseline_days == 10
    assert result.max_residual_arcsec is None


@pytest.mark.parametrize(
    "ra,dec,angle", [(359.9999, 0, 90), (10, 89.999, 0), (10, -70, 270), (10, 0, 180)]
)
def test_displacement_direction_spherical(ra, dec, angle):
    t = track()
    a = replace(t.points[0], centroid=replace(t.points[0].centroid, ra_deg=ra, dec_deg=dec))
    end = SkyCoord(ra * u.deg, dec * u.deg).directional_offset_by(angle * u.deg, 1.5 * u.arcsec)
    b = replace(
        t.points[1], centroid=replace(t.points[1].centroid, ra_deg=end.ra.deg, dec_deg=end.dec.deg)
    )
    result = estimate_source_motion(SourceTrack("t", (b, a)))
    assert result.status == "POSSIBLE_MOVEMENT"
    assert result.measured_positions == (b, a)
    assert result.displacement.angular_arcsec == pytest.approx(1.5, abs=2e-6)
    assert result.displacement.position_angle_deg == pytest.approx(angle, abs=1e-6)


@pytest.mark.parametrize(
    "change",
    [{"ra_deg": None}, {"dec_deg": 100}, {"uncertainty_arcsec": None}, {"uncertainty_arcsec": -1}],
)
def test_invalid_epoch_prevents_measurement(change):
    t = track()
    b = replace(t.points[1], centroid=replace(t.points[1].centroid, **change))
    assert estimate_source_motion(replace(t, points=(t.points[0], b))).status == "UNAVAILABLE"


@pytest.mark.parametrize("count", [0, 1])
def test_insufficient_epochs(count):
    t = track()
    assert estimate_source_motion(replace(t, points=t.points[:count])).status == "UNAVAILABLE"


def test_same_time_unavailable():
    t = track()
    assert (
        estimate_source_motion(
            replace(t, points=(t.points[0], replace(t.points[1], mjd_utc=60000)))
        ).status
        == "UNAVAILABLE"
    )


def test_noise_limited_not_stable():
    t = track(0, uncertainty_arcsec=2)
    assert estimate_source_motion(t).status == "AMBIGUOUS"


def test_ambiguous_identity_retains_displacement():
    result = estimate_source_motion(replace(track(), ambiguous=True))
    assert result.status == "AMBIGUOUS" and result.displacement is not None


@pytest.mark.parametrize("middle_shift,expected", [(0.5, "POSSIBLE_MOVEMENT"), (3, "AMBIGUOUS")])
def test_three_epoch_consistency(middle_shift, expected):
    t = track()
    middle = replace(
        t.points[0],
        observation_id="middle",
        mjd_utc=60005,
        centroid=replace(t.points[0].centroid, ra_deg=10 + middle_shift / 3600),
    )
    result = estimate_source_motion(replace(t, points=(t.points[0], middle, t.points[1])))
    assert len(result.pairwise) == 3
    assert result.status == expected
    assert result.max_residual_arcsec == pytest.approx(abs(middle_shift - 0.5), abs=1e-7)


@pytest.mark.parametrize("value", [0, -1, float("nan")])
def test_invalid_motion_policy(value):
    with pytest.raises(ValueError):
        MotionPolicy(displacement_floor_arcsec=value)
