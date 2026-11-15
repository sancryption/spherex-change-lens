"""Reconstruct cutout coordinates from an official parent image and verify pixels.

Alternate CRPIX keywords in locally generated cutouts are not trusted. A mapping
is established only when celestial transforms give integer detector positions
and all four science layers equal the corresponding parent pixels exactly.
"""

from hashlib import sha256
from pathlib import Path

import numpy as np
from astropy.io import fits
from astropy.wcs import WCS
from astropy.wcs.utils import pixel_to_pixel


def verify_parent_cutout(parent_path: Path, cutout_path: Path):
    with (
        fits.open(parent_path, memmap=False) as parent,
        fits.open(cutout_path, memmap=False) as cutout,
    ):
        ph, ch = parent["IMAGE"].header, cutout["IMAGE"].header
        for key in ("OBSID", "DETECTOR", "DATE-OBS", "BUNIT"):
            if ph.get(key) is None or ph.get(key) != ch.get(key):
                raise ValueError("PARENT_CUTOUT_METADATA_MISMATCH:" + key)
        y, x = np.indices(cutout["IMAGE"].data.shape)
        px, py = pixel_to_pixel(WCS(ch).celestial, WCS(ph).celestial, x, y)
        # Numerical WCS round-trip tolerance, not a science acceptance threshold.
        if (
            not np.isfinite(px).all()
            or not np.isfinite(py).all()
            or np.max(abs(px - np.rint(px))) > 1e-5
            or np.max(abs(py - np.rint(py))) > 1e-5
        ):
            raise ValueError("CUTOUT_NOT_EXACT_NATIVE_PIXEL_SUBSET")
        px, py = np.rint(px).astype(int), np.rint(py).astype(int)
        shape = parent["IMAGE"].data.shape
        if np.any(px < 0) or np.any(py < 0) or np.any(px >= shape[1]) or np.any(py >= shape[0]):
            raise ValueError("CUTOUT_OUTSIDE_PARENT")
        for name in ("IMAGE", "VARIANCE", "FLAGS", "ZODI"):
            if not np.array_equal(parent[name].data[py, px], cutout[name].data, equal_nan=True):
                raise ValueError("PARENT_CUTOUT_PIXEL_MISMATCH:" + name)
        return (
            px,
            py,
            {
                "method": "celestial-integer-mapping-and-four-layer-exact-equality-v1",
                "parent_sha256": sha256(Path(parent_path).read_bytes()).hexdigest(),
                "cutout_sha256": sha256(Path(cutout_path).read_bytes()).hexdigest(),
                "observation_id": ph["OBSID"],
                "detector": ph["DETECTOR"],
                "detector_x_range": [int(px.min()), int(px.max())],
                "detector_y_range": [int(py.min()), int(py.max())],
            },
        )
