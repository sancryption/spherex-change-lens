import numpy as np
import pytest
from astropy.io import fits
from astropy.wcs import WCS
from change_lens.fits.validator import validate_fits


@pytest.fixture
def product(tmp_path):
    def make(drop=None, kind=None, wcs_mode="pc", unit="MJy/sr", nan=False):
        w = WCS(naxis=2)
        w.wcs.crpix = [3, 3]
        w.wcs.crval = [20, 30]
        w.wcs.ctype = ["RA---TAN", "DEC--TAN"]
        w.wcs.cdelt = [-0.001, 0.001]
        h = w.to_header()
        if wcs_mode == "missing":
            h = fits.Header()
        elif wcs_mode == "bad":
            h["CDELT1"] = 0
        elif wcs_mode == "cd":
            del h["CDELT1"]
            del h["CDELT2"]
            h["CD1_1"], h["CD2_2"] = -0.001, 0.001
        elif wcs_mode == "pc":
            h["PC1_1"], h["PC2_2"] = 1.0, 1.0
        h["SYNTHET"] = True
        h["OBSID"] = "synthetic-test"
        if unit is not None:
            h["BUNIT"] = unit
        image = np.ones((5, 5))
        if nan:
            image[0, :2] = [np.nan, np.inf]
        if kind == "image":
            image = image.astype(complex)
        # FITS image HDUs cannot encode complex/string/object arrays: use a table.
        im = (
            fits.BinTableHDU.from_columns(
                [fits.Column(name="x", format="5A", array=["abc"])], name="IMAGE"
            )
            if kind == "image"
            else fits.ImageHDU(image, header=h, name="IMAGE")
        )
        variance = np.ones((3, 3) if kind == "shape" else (5, 5))
        vh = fits.Header({"BUNIT": "MJy2/sr2"})
        flags = np.zeros((5, 5), dtype=float if kind == "flags" else np.uint16)
        hdus = [
            fits.PrimaryHDU(),
            im,
            fits.ImageHDU(variance, header=vh, name="VARIANCE"),
            fits.ImageHDU(flags, name="FLAGS"),
        ]
        path = tmp_path / "synthetic.fits"
        fits.HDUList([x for x in hdus if x.name != drop]).writeto(path, overwrite=True)
        return path

    return make


@pytest.mark.parametrize("mode", ["pc", "cd"])
def test_valid(product, mode):
    path = product(wcs_mode=mode, nan=True)
    result = validate_fits(path).require_valid()
    path.unlink()
    assert result.image.shape == (5, 5)
    assert result.report.observation_id == "synthetic-test"
    assert result.report.finite_fraction == 23 / 25
    assert result.report.extensions["IMAGE"]["normalized_dtype"] == "float64"
    assert result.report.has_flags and result.report.has_variance
    assert all(
        f"MISSING_OPTIONAL:{n}" in result.report.warnings for n in ["PSF", "ZODI", "WCS-WAVE"]
    )
    assert result.variance.sum() == 25


@pytest.mark.parametrize(
    "kwargs",
    [{"drop": x} for x in ["IMAGE", "VARIANCE", "FLAGS"]]
    + [{"kind": x} for x in ["shape", "image", "flags"]]
    + [{"wcs_mode": x} for x in ["missing", "bad"]]
    + [{"unit": x} for x in [None, "s"]],
)
def test_invalid(product, kwargs):
    result = validate_fits(product(**kwargs))
    assert not result.report.passed
    assert result.report.errors
    assert result.image is None
    with pytest.raises(ValueError, match="INVALID_PRODUCT"):
        result.require_valid()


def test_corrupt_and_missing(tmp_path):
    path = tmp_path / "broken.fits"
    assert validate_fits(path).report.errors == ["FILE_NOT_FOUND"]
    path.write_bytes(b"not FITS")
    assert "MALFORMED_FITS" in validate_fits(path).report.errors


def test_validation_to_masks(product):
    from change_lens.pipeline.masks import FlagPolicy, build_quality_masks

    result = validate_fits(product(nan=True))
    out = build_quality_masks(result, FlagPolicy("synthetic-zero-v1", "SYNTHETIC_TEST_ONLY", {}))
    assert out.valid_count == 23
    assert out.invalid_count == 2
    assert out.reason_counts["BAD_PIXEL"] == 2
    invalid = validate_fits(product(drop="IMAGE"))
    with pytest.raises(ValueError, match="INVALID_PRODUCT"):
        build_quality_masks(invalid, FlagPolicy("synthetic-v1", "SYNTHETIC_TEST_ONLY", {}))


@pytest.mark.parametrize("shape", [(0, 5), (2, 3, 4)])
def test_invalid_dimensions(product, shape):
    path = product()
    with fits.open(path, mode="update") as hdus:
        hdus["IMAGE"].data = np.ones(shape)
    assert "INVALID_ARRAY_SHAPE:IMAGE" in validate_fits(path).report.errors


def test_integer_image_and_truncation(product):
    path = product()
    with fits.open(path, mode="update") as hdus:
        hdus["IMAGE"].data = np.ones((5, 5), dtype=np.int16)
    result = validate_fits(path).require_valid()
    assert result.image.dtype == np.float64
    path.write_bytes(path.read_bytes()[:-2880])
    assert not validate_fits(path).report.passed


def test_variance_units(product):
    path = product()
    with fits.open(path, mode="update") as hdus:
        hdus["VARIANCE"].header["BUNIT"] = "Jy2/sr2"
    assert "INVALID_REQUIRED_UNITS:VARIANCE" in validate_fits(path).report.errors


def test_optional_header_commentary_serializes(product):
    import json

    path = product()
    header = fits.Header()
    header.add_history("First calibration step")
    header.add_history("Second calibration step")
    header.add_comment("Instrument context")
    header.add_comment("Additional context")
    header["GAIN"] = 2.5
    header["PHASE"] = complex(1, -2)
    header["UNDEF"] = None
    with fits.open(path, mode="update") as hdus:
        hdus["IMAGE"].header.add_history("Image provenance")
        hdus.append(fits.ImageHDU(np.ones((2, 2)), header=header, name="PSF"))
    report = validate_fits(path).require_valid().report
    payload = json.loads(report.model_dump_json())
    optional = payload["extensions"]["PSF"]["header"]
    assert optional["HISTORY"] == ["First calibration step", "Second calibration step"]
    assert optional["COMMENT"] == ["Instrument context", "Additional context"]
    assert optional["GAIN"] == 2.5
    assert optional["PHASE"] == {"type": "complex", "real": 1.0, "imag": -2.0}
    assert optional["UNDEF"] is None
    assert payload["metadata"]["HISTORY"] == ["Image provenance"]
    assert payload["passed"] is True


def test_header_values_do_not_stringify_arbitrary_objects():
    from change_lens.fits.validator import _header_metadata, _header_value

    with pytest.raises(TypeError, match="Unsupported FITS header value"):
        _header_value(np.arange(3))
    assert _header_value(np.int32(7)) == 7
    assert _header_value(float("inf")) == {"type": "nonfinite_float", "value": "inf"}

    class UnsupportedCard:
        keyword = "UNSUPPORTED"
        value = object()

    class HeaderWithUnsupportedValue:
        cards = [UnsupportedCard()]

    warnings = []
    assert _header_metadata(HeaderWithUnsupportedValue(), warnings, "PSF") == {}
    assert warnings == ["UNSUPPORTED_HEADER_VALUE:PSF:UNSUPPORTED"]
