from dataclasses import replace

import pytest
from change_lens.pipeline.brightness import extract_photometry
from change_lens.pipeline.controls import StaticControl, assess_controls
from change_lens.pipeline.motion import estimate_source_motion

from .conftest import gaussian
from .phase3_helpers import diagnostics_for, frames_and_track


def measurements(prepared):
    frames, track = frames_and_track(prepared)
    for frame in frames.values():
        frame.image += gaussian(center=(30, 30), background=0)
    motion = estimate_source_motion(track)
    brightness = extract_photometry(track, frames)
    control_track = replace(
        track,
        track_id="control",
        points=tuple(
            replace(p, centroid=replace(p.centroid, source_id="independent", x=30, y=30))
            for p in track.points
        ),
    )
    control = StaticControl(
        estimate_source_motion(control_track), extract_photometry(control_track, frames)
    )
    return frames, track, motion, brightness, control


def test_supported_controls_reproducible(prepared):
    frames, track, m, b, control = measurements(prepared)
    a = assess_controls(
        track, m, b, frames, static_controls=(control,), diagnostics=diagnostics_for()
    )
    assert a.motion_status == a.brightness_status == "SUPPORTED"
    assert a == assess_controls(
        track, m, b, frames, static_controls=(control,), diagnostics=diagnostics_for()
    )
    assert all(c.provenance is not None for c in a.checks)


def test_missing_controls_never_supported(prepared):
    frames, track, m, b, _ = measurements(prepared)
    result = assess_controls(track, m, b, frames)
    assert result.motion_status == result.brightness_status == "AMBIGUOUS"
    assert any("VALIDATED_PSF_INFORMATION_UNAVAILABLE" in c.reasons for c in result.checks)


@pytest.mark.parametrize("artifact", ["mask", "edge", "variance", "flag", "footprint", "blend"])
def test_artifact_failed(prepared, artifact):
    frames, track, m, b, control = measurements(prepared)
    if artifact == "mask":
        frames["a"].usable_mask[20, 20] = False
    elif artifact == "edge":
        track = replace(
            track, points=tuple(replace(p, centroid=replace(p.centroid, x=1)) for p in track.points)
        )
    elif artifact == "variance":
        frames["a"].variance[20, 20] = 100
    elif artifact == "flag":
        frames["a"].reason_masks["FLAG_WARNING"][20, 20] = True
    elif artifact == "footprint":
        frames["a"].footprint[20, 20] = 0.5
    else:
        track = replace(
            track,
            points=tuple(
                replace(p, centroid=replace(p.centroid, warnings=("POSSIBLE_BLEND",)))
                for p in track.points
            ),
        )
    result = assess_controls(
        track, m, b, frames, static_controls=(control,), diagnostics=diagnostics_for()
    )
    assert result.motion_status == result.brightness_status == "ARTIFACT_SUSPECT"


def test_ambiguous_identity(prepared):
    frames, track, m, b, control = measurements(prepared)
    result = assess_controls(
        replace(track, ambiguous=True),
        m,
        b,
        frames,
        static_controls=(control,),
        diagnostics=diagnostics_for(),
    )
    assert result.motion_status == result.brightness_status == "AMBIGUOUS"


@pytest.mark.parametrize("kind", ["self", "wrong_epoch", "unreliable", "changed"])
def test_static_control_validation(prepared, kind):
    frames, track, m, b, control = measurements(prepared)
    if kind == "self":
        control = StaticControl(m, b)
    elif kind == "wrong_epoch":
        control = replace(
            control,
            motion=replace(
                control.motion, measured_positions=control.motion.measured_positions[:1]
            ),
        )
    elif kind == "unreliable":
        control = replace(control, motion=replace(control.motion, status="AMBIGUOUS"))
    else:
        control = replace(control, motion=replace(control.motion, status="POSSIBLE_MOVEMENT"))
    result = assess_controls(
        track, m, b, frames, static_controls=(control,), diagnostics=diagnostics_for()
    )
    assert result.motion_status == ("ARTIFACT_SUSPECT" if kind == "changed" else "AMBIGUOUS")


@pytest.mark.parametrize("validated", [True, False])
def test_psf_mismatch_requires_validation(prepared, validated):
    frames, track, m, b, control = measurements(prepared)
    diagnostics = diagnostics_for(widths=(3, 6))
    diagnostics["b"] = replace(diagnostics["b"], validated=validated)
    result = assess_controls(
        track, m, b, frames, static_controls=(control,), diagnostics=diagnostics
    )
    assert result.motion_status == ("ARTIFACT_SUSPECT" if validated else "AMBIGUOUS")


def test_validated_background_gradient(prepared):
    frames, track, m, b, control = measurements(prepared)
    diagnostics = diagnostics_for()
    diagnostics["b"] = replace(diagnostics["b"], background_gradient_per_pixel=5)
    result = assess_controls(
        track, m, b, frames, static_controls=(control,), diagnostics=diagnostics
    )
    assert result.brightness_status == "ARTIFACT_SUSPECT"
    assert result.motion_status == "SUPPORTED"


def test_background_change_uses_existing_measurement(prepared):
    frames, track, m, b, control = measurements(prepared)
    changed = replace(b.measurements[1], background=100)
    b = replace(b, measurements=(b.measurements[0], changed))
    result = assess_controls(
        track, m, b, frames, static_controls=(control,), diagnostics=diagnostics_for()
    )
    assert result.brightness_status == "AMBIGUOUS"
    assert result.motion_status == "SUPPORTED"


def test_measurement_track_mismatch(prepared):
    frames, track, m, b, _ = measurements(prepared)
    with pytest.raises(ValueError, match="TRACK_MISMATCH"):
        assess_controls(track, replace(m, track_id="wrong"), b, frames)


def test_static_control_artifact_is_not_trusted(prepared):
    frames, track, m, b, control = measurements(prepared)
    frames["b"].variance[30, 30] = 1000
    result = assess_controls(
        track, m, b, frames, static_controls=(control,), diagnostics=diagnostics_for()
    )
    assert result.motion_status == result.brightness_status == "AMBIGUOUS"
    assert any("STATIC_CONTROL_UNRELIABLE" in c.reasons for c in result.checks)


def test_relabelled_target_cannot_be_its_own_control(prepared):
    frames, track, m, b, _ = measurements(prepared)
    points = tuple(
        replace(p, centroid=replace(p.centroid, source_id="different_label")) for p in track.points
    )
    disguised = replace(track, track_id="disguised", points=points)
    control = StaticControl(
        estimate_source_motion(disguised), extract_photometry(disguised, frames)
    )
    result = assess_controls(
        track, m, b, frames, static_controls=(control,), diagnostics=diagnostics_for()
    )
    assert result.motion_status == result.brightness_status == "AMBIGUOUS"


def test_unavailable_measurements_have_unavailable_controls(prepared):
    frames, track, m, b, _ = measurements(prepared)
    result = assess_controls(
        track,
        replace(m, status="UNAVAILABLE", displacement=None, pairwise=()),
        replace(b, status="UNAVAILABLE", comparisons=()),
        frames,
    )
    assert result.motion_status == result.brightness_status == "UNAVAILABLE"
