from pathlib import Path

import numpy as np
import pytest
from astropy.io import fits
from change_lens.pipeline.calibration_mapping import verify_parent_cutout

from .conftest import make_wcs


def make_pair(tmp_path: Path):
    wcs = make_wcs(shape=(7, 7))
    parent, cutout = [], []
    metadata = {"OBSID": "test", "DETECTOR": 1, "DATE-OBS": "2025-09-30", "BUNIT": "MJy/sr"}
    for name in ("IMAGE", "VARIANCE", "FLAGS", "ZODI"):
        array = np.arange(49).reshape(7, 7)
        header = wcs.to_header()
        header.update(metadata)
        parent.append(fits.ImageHDU(array, header=header, name=name))
        header = wcs.slice((slice(2, 5), slice(3, 6))).to_header()
        header.update(metadata)
        cutout.append(fits.ImageHDU(array[2:5, 3:6], header=header, name=name))
    p, c = tmp_path / "parent.fits", tmp_path / "cutout.fits"
    fits.HDUList([fits.PrimaryHDU(), *parent]).writeto(p)
    fits.HDUList([fits.PrimaryHDU(), *cutout]).writeto(c)
    return p, c


def test_exact_four_layer_subset_and_tampering(tmp_path):
    p, c = make_pair(tmp_path)
    x, y, evidence = verify_parent_cutout(p, c)
    assert evidence["detector_x_range"] == [3, 5]
    assert evidence["detector_y_range"] == [2, 4]
    assert x.shape == y.shape == (3, 3)
    with fits.open(c, mode="update") as h:
        h["ZODI"].data[0, 0] += 1
    with pytest.raises(ValueError, match="PIXEL_MISMATCH:ZODI"):
        verify_parent_cutout(p, c)
