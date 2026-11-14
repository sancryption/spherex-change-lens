import numpy as np
import pytest
from astropy.wcs import WCS
from change_lens.pipeline.alignment import align_observation_wcs, reproject_frame
from change_lens.pipeline.phase2 import PlaneIdentity, align_series
from reproject import reproject_interp

from .conftest import make_wcs


def align(observation, target=None, shape=None):
    return reproject_frame(
        observation.validated,
        observation.masks,
        target or observation.validated.wcs,
        shape or observation.validated.image.shape,
    )


def test_identity_and_owned_outputs(prepared):
    image = np.arange(63.0).reshape(7, 9)
    variance = image + 1
    observation = prepared(image=image, variance=variance)
    out = align(observation)
    np.testing.assert_array_equal(out.image, image)
    np.testing.assert_array_equal(out.variance, variance)
    assert out.usable_mask.all() and np.all(out.footprint == 1)
    out.image[0, 0] = -1
    out.wcs.wcs.crval[0] = 3
    out.provenance["validation"]["metadata"]["SYNTHET"] = "changed"
    assert image[0, 0] == 0
    assert observation.validated.wcs.wcs.crval[0] == 359.999
    assert observation.validated.report.metadata["SYNTHET"] == "True"


@pytest.mark.parametrize("angle", [0, 90, 180, 270, 33])
@pytest.mark.parametrize("scale", [0.6, 1, 1.8])
def test_rotation_scale_and_surface_brightness(prepared, angle, scale):
    reference = make_wcs()
    source = make_wcs(angle=angle, scale=scale)
    # A celestial tangent-plane affine field has an exact bilinear solution.
    y, x = np.indices((41, 41))
    rx, ry = reference.world_to_pixel(source.pixel_to_world(x, y))
    observation = prepared(image=4 + 2 * rx + 3 * ry, wcs=source)
    out = align(observation, reference)
    assert out.usable_mask.any()
    np.testing.assert_allclose(
        out.image[out.usable_mask], (4 + 2 * x + 3 * y)[out.usable_mask], atol=2e-6
    )
    expected, _ = reproject_interp(
        (observation.validated.image, source), reference, shape_out=(41, 41)
    )
    np.testing.assert_allclose(out.image[out.usable_mask], expected[out.usable_mask], atol=2e-6)
    assert out.provenance["pixel_scale_ratio"] == pytest.approx(scale)


def test_half_pixel_weights_variance_and_categorical_flags(prepared):
    image = np.arange(25.0).reshape(5, 5)
    variance = np.arange(1.0, 26).reshape(5, 5)
    flags = np.zeros((5, 5), np.uint16)
    flags[2, 2] = 2
    observation = prepared(
        image=image, variance=variance, flags=flags, wcs=make_wcs(shift=(0.5, 0.5), shape=(5, 5))
    )
    out = align(observation, make_wcs(shape=(5, 5)))
    assert out.image[1, 1] == pytest.approx(image[1:3, 1:3].mean(), abs=1e-6)
    assert out.variance[1, 1] == pytest.approx(variance[1:3, 1:3].sum() / 16, abs=1e-6)
    assert out.flags[1, 1] == 2
    assert out.reason_masks["FLAG_WARNING"][1, 1]
    assert out.usable_mask[1, 1]
    assert not out.usable_mask[-1, -1]
    assert out.footprint[-1, -1] == pytest.approx(0.25, abs=1e-6)


@pytest.mark.parametrize("kind", ["flag", "nan", "variance", "footprint"])
def test_invalid_contributor_excludes_whole_stencil(prepared, kind):
    image = np.ones((7, 7))
    variance = image.copy()
    flags = np.zeros((7, 7), np.uint16)
    footprint = np.ones((7, 7), bool)
    if kind == "flag":
        flags[3, 3] = 1
    elif kind == "nan":
        image[3, 3] = np.nan
    elif kind == "variance":
        variance[3, 3] = -1
    else:
        footprint[3, 3] = False
    observation = prepared(
        image=image,
        variance=variance,
        flags=flags,
        footprint=footprint,
        wcs=make_wcs(shape=(7, 7), shift=(0.5, 0.5)),
    )
    out = align(observation, make_wcs(shape=(7, 7)))
    assert not out.usable_mask[2:4, 2:4].any()
    assert np.isnan(out.image[2:4, 2:4]).all()
    assert np.isnan(out.variance[2:4, 2:4]).all()
    assert out.usable_mask[0, 0]
    if kind != "footprint":
        assert out.footprint[2, 2] == pytest.approx(1)


def test_series_overlap_and_reference(prepared):
    a = prepared()
    b = prepared(wcs=make_wcs(shift=(5, 0)))
    result = align_series([a, b], reference_index=1)
    assert result.status == "ALIGNED"
    assert result.overlap_fraction == pytest.approx(36 / 41)
    np.testing.assert_array_equal(result.frames[1].image, b.validated.image)
    assert result.frames[0].provenance["reference_index"] == 1
    c = prepared(wcs=make_wcs(shift=(100, 100)))
    result = align_series([a, c])
    assert result.status == "INSUFFICIENT_EVIDENCE"
    assert result.overlap_fraction == 0
    assert not result.frames[1].footprint.any()
    assert np.isnan(result.frames[1].image).all()


@pytest.mark.parametrize("field", ["band", "product", "spectral_plane"])
def test_incompatible_plane(prepared, field):
    a, b = prepared(), prepared()
    identity = {
        "band": "test-band",
        "product": "test-product",
        "spectral_plane": "synthetic-plane",
        "release": "synthetic-release",
    }
    identity[field] = "different"
    b.identity = PlaneIdentity(**identity)
    result = align_series([a, b])
    assert result.status == "INCOMPATIBLE_PRODUCT" and not result.frames


def test_unit_scale_and_metadata_conflict(prepared):
    a, b = prepared(), prepared()
    b.validated.report.image_unit = "Jy/sr"
    assert align_series([a, b]).status == "INCOMPATIBLE_PRODUCT"
    b.validated.report.image_unit = "MJy/sr"
    b.validated.report.metadata["BAND"] = "different"
    assert "PLANE_IDENTITY_CONFLICTS_WITH_HEADER" in align_series([a, b]).warnings


@pytest.mark.parametrize("mode", ["noncelestial", "singular", "nan"])
def test_invalid_wcs(prepared, mode):
    observation = prepared()
    wcs = make_wcs()
    if mode == "noncelestial":
        wcs = WCS(naxis=2)
    elif mode == "singular":
        wcs.wcs.cd = np.zeros((2, 2))
    else:
        wcs.wcs.crval = [np.nan, 30]
    with pytest.raises(ValueError, match="INVALID_WCS"):
        align(observation, wcs)


def test_legacy_intensity_helper(prepared):
    observation = prepared()
    header = observation.validated.wcs.to_header()
    header["NAXIS1"] = header["NAXIS2"] = 41
    result = align_observation_wcs(header, header, observation.validated.image)
    np.testing.assert_allclose(result, observation.validated.image, atol=1e-7)
