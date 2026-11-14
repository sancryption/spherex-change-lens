"""Deterministic Phase 3 synthetic helpers; never authentic acceptance evidence."""

from dataclasses import replace

import numpy as np
from astropy.io import fits
from change_lens.pipeline.association import EpochDetections, SourceTrack, TrackPoint
from change_lens.pipeline.centroid import CentroidMeasurement
from change_lens.pipeline.controls import ProductDiagnostics
from change_lens.pipeline.detection import Quality
from change_lens.pipeline.phase2 import align_series, run_phase2

from .conftest import IDENTITY, POLICY, gaussian, make_wcs


def centroid(ra=10.0, dec=0.0, source_id="s", **changes):
    base = CentroidMeasurement(
        20.0, 20.0, ra, dec, 0.01, 0.01, 0.02, 100.0, 12.0, 1.0, Quality.VALID, (), source_id
    )
    return replace(base, **changes)


def epoch(name="a", time=60000.0, *centroids):
    return EpochDetections(name, time, centroids or (centroid(),), {"synthetic": True})


def track(shift=1.0, **changes):
    a = TrackPoint("a", 60000.0, centroid(), {"synthetic": True})
    b = TrackPoint("b", 60010.0, centroid(ra=10 + shift / 3600, **changes), {"synthetic": True})
    return SourceTrack("target", (a, b))


def frames_and_track(prepared, amplitudes=(80, 80), backgrounds=(12, 12), variance=1.0):
    observations = []
    for i, (amp, bg) in enumerate(zip(amplitudes, backgrounds, strict=True)):
        p = prepared(
            image=gaussian(center=(20, 20), amplitude=amp, background=bg),
            variance=np.full((41, 41), variance),
        )
        p.validated.report.observation_id = chr(97 + i)
        p.validated.report.metadata.update(
            {"CALVER": "synthetic-v1", "MJD-OBS": str(60000 + 10 * i)}
        )
        observations.append(p)
    aligned = align_series(observations)
    points = tuple(
        TrackPoint(chr(97 + i), 60000 + 10 * i, centroid()) for i in range(len(observations))
    )
    return dict(zip((p.observation_id for p in points), aligned.frames, strict=True)), SourceTrack(
        "target", points
    )


def diagnostics_for(names=("a", "b"), widths=(3.5322, 3.5322)):
    return {
        name: ProductDiagnostics(
            name, True, width, 0.0, "synthetic Gaussian fixture: known injected PSF width"
        )
        for name, width in zip(names, widths, strict=True)
    }


def full_phase2(tmp_path, scenario="stationary"):
    """Two FITS epochs with a separate static control and certified test plane."""
    paths = []
    shape = (81, 81)
    for i in range(2):
        shift = i if scenario in ("moving", "registration") else 0
        amplitude = 160 if scenario == "variable" and i else 80
        target = gaussian(shape, (25 + shift, 25), amplitude=amplitude)
        control = gaussian(
            shape, (55 + (i if scenario == "registration" else 0), 55), amplitude=100, background=0
        )
        image = target + control
        if scenario == "ambiguous" and i:
            image += gaussian(shape, (35, 25), amplitude=80, background=0)
        variance = np.ones(shape)
        if scenario == "artifact" and i:
            variance[25, 25] = 1000
        header = make_wcs(shape=shape).to_header()
        name = chr(97 + i)
        header.update(
            {
                "BUNIT": "MJy/sr",
                "SYNTHET": True,
                "OBSID": name,
                "BAND": IDENTITY.band,
                "PRODTYPE": IDENTITY.product,
                "RELEASE": IDENTITY.release,
                "CALVER": "synthetic-v1",
                "MJD-OBS": 60000 + 10 * i,
            }
        )
        path = tmp_path / f"{scenario}_{name}.fits"
        fits.HDUList(
            [
                fits.PrimaryHDU(),
                fits.ImageHDU(image, header=header, name="IMAGE"),
                fits.ImageHDU(variance, header=fits.Header({"BUNIT": "MJy2/sr2"}), name="VARIANCE"),
                fits.ImageHDU(np.zeros(shape, np.uint16), name="FLAGS"),
                fits.ImageHDU(
                    np.array([[3.5322]]),
                    header=fits.Header({"BUNIT": "pixel", "SYNTHET": True}),
                    name="PSF",
                ),
            ]
        ).writeto(path)
        paths.append(path)
    return run_phase2(paths, [IDENTITY] * 2, POLICY), paths
