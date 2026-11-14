import hashlib

import numpy as np
import pytest
from astropy.io import fits
from change_lens.pipeline.detection import Quality
from change_lens.pipeline.phase2 import run_phase2

from .conftest import IDENTITY, POLICY, gaussian, make_wcs


def write_product(path, wcs, center):
    header = wcs.to_header()
    header["BUNIT"] = "MJy/sr"
    header["SYNTHET"] = True
    header["OBSID"] = path.stem
    header["BAND"] = IDENTITY.band
    header["PRODTYPE"] = IDENTITY.product
    header["RELEASE"] = IDENTITY.release
    header["HISTORY"] = "Deterministic synthetic Phase 2 acceptance fixture"
    fits.HDUList(
        [
            fits.PrimaryHDU(),
            fits.ImageHDU(gaussian(center=center), header=header, name="IMAGE"),
            fits.ImageHDU(
                np.ones((41, 41)), header=fits.Header({"BUNIT": "MJy2/sr2"}), name="VARIANCE"
            ),
            fits.ImageHDU(np.zeros((41, 41), np.uint16), name="FLAGS"),
        ]
    ).writeto(path)


def test_synthetic_end_to_end_rotated_observations(tmp_path):
    reference = make_wcs()
    center = (20.3, 19.7)
    sky = reference.pixel_to_world(*center)
    paths = []
    for i, angle in enumerate([0, 90, 180, 33]):
        wcs = make_wcs(angle=angle)
        path = tmp_path / f"synthetic_{i}.fits"
        write_product(path, wcs, wcs.world_to_pixel(sky))
        paths.append(path)
    hashes = [hashlib.sha256(path.read_bytes()).hexdigest() for path in paths]
    a = run_phase2(paths, [IDENTITY] * 4, POLICY)
    b = run_phase2(paths, [IDENTITY] * 4, POLICY)
    assert a.alignment.status == "ALIGNED"
    assert a.alignment.overlap_fraction > 0.75
    for index, (detection, measurements) in enumerate(zip(a.detections, a.centroids, strict=True)):
        assert len(detection.sources) == len(measurements) == 1
        measurement = measurements[0]
        assert measurement.quality == Quality.VALID
        assert (measurement.x, measurement.y) == pytest.approx(center, abs=0.04)
        assert measurement.ra_deg == pytest.approx(sky.icrs.ra.deg, abs=0.04 / 3600)
        assert measurement.dec_deg == pytest.approx(sky.icrs.dec.deg, abs=0.04 / 3600)
        assert measurement.uncertainty_arcsec > 0
        frame = a.alignment.frames[index]
        provenance = frame.provenance
        assert provenance["validation"]["metadata"]["SYNTHET"] == "True"
        assert provenance["validation"]["observation_id"] == f"synthetic_{index}"
        assert provenance["mask_policy"] == POLICY.version
        assert provenance["plane_identity"]["spectral_plane"] == IDENTITY.spectral_plane
        assert "RESAMPLING_COVARIANCE_NOT_MODELED" in measurement.warnings
        np.testing.assert_array_equal(frame.image, b.alignment.frames[index].image)
    assert a.centroids == b.centroids and a.detections == b.detections
    assert hashes == [hashlib.sha256(path.read_bytes()).hexdigest() for path in paths]


def test_no_overlap_stops_measurement(tmp_path):
    paths = [tmp_path / "a.fits", tmp_path / "b.fits"]
    write_product(paths[0], make_wcs(), (20, 20))
    write_product(paths[1], make_wcs(shift=(100, 0)), (20, 20))
    result = run_phase2(paths, [IDENTITY] * 2, POLICY)
    assert result.alignment.status == "INSUFFICIENT_EVIDENCE"
    assert result.detections == () and result.centroids == ()
