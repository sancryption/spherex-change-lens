"""Offline tests for the IRSA adapter: DATA functions are faked, no network."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import change_lens.archive.irsa as irsa
import pytest
from change_lens.api.errors import ArchiveUnavailableError
from change_lens.archive.irsa import IrsaArchiveClient, select_frames
from changelens.contracts import (
    DiscoveryResult,
    DiscoveryStatus,
    ErrorCode,
    ObservationRecord,
    RetrievalMode,
)
from changelens.data import PreviewError

MJD0 = datetime(1858, 11, 17, tzinfo=UTC)


def obs(i: int, mjd: float, band: str = "SPHEREx-D2", release: str = "DR1") -> ObservationRecord:
    return ObservationRecord(
        observation_id=f"plane_{i}",
        access_url=f"https://irsa.ipac.caltech.edu/x/{i}.fits",
        observed_at=MJD0 + timedelta(days=mjd),
        mjd=mjd,
        band=band,
        release=release,
    )


def test_select_frames_keeps_one_group_and_samples_evenly() -> None:
    observations = [obs(i, 60800 + i * 10) for i in range(20)]
    observations += [obs(100 + i, 60805 + i, band="SPHEREx-D5") for i in range(3)]
    chosen, notes = select_frames(observations, max_frames=5)
    assert len(chosen) == 5
    assert {o.band for o in chosen} == {"SPHEREx-D2"}
    mjds = [o.mjd for o in chosen]
    assert mjds == sorted(mjds)
    assert mjds[0] == 60800 and mjds[-1] == 60990  # first and last visit included
    assert "OTHER_DETECTORS_OR_RELEASES_NOT_MIXED" in notes


def test_select_frames_dedupes_and_skips_unusable() -> None:
    a = obs(1, 60800)
    no_url = ObservationRecord(observation_id="plane_x", mjd=60900, band="SPHEREx-D2", release="DR1")
    chosen, _ = select_frames([a, a, no_url], max_frames=8)
    assert [o.observation_id for o in chosen] == ["plane_1"]


@pytest.fixture
def client(tmp_path: Path) -> IrsaArchiveClient:
    return IrsaArchiveClient(
        data_dir=tmp_path, previews_dir=tmp_path / "previews", cache_dir=tmp_path / "cache", max_frames=3
    )


def fake_discovery(status=DiscoveryStatus.COMPLETE, observations=None, **kw) -> DiscoveryResult:
    return DiscoveryResult(status=status, observations=observations or [], **kw)


class FakeSource:
    def __init__(self, mode: RetrievalMode):
        self.retrieval_mode = mode


class FakePreview:
    def __init__(self, filename: str, in_footprint: bool = True):
        self.preview_filename = filename
        self.target_in_footprint = in_footprint
        self.warnings = ["SCIENCE_AND_WCS_VALIDATION_PENDING"]
        self.wcs_header = {}


def test_discover_maps_frames_previews_and_origin(client, monkeypatch, tmp_path) -> None:
    observations = [obs(i, 60800 + i * 30) for i in range(6)]
    monkeypatch.setattr(irsa, "discover", lambda req, **kw: fake_discovery(observations=observations))
    modes = iter([RetrievalMode.CUTOUT, RetrievalMode.CACHE, RetrievalMode.CUTOUT])
    monkeypatch.setattr(irsa, "retrieve", lambda o, **kw: FakeSource(next(modes)))

    def preview(source, target, **kw):
        if source.retrieval_mode == RetrievalMode.CACHE:
            raise PreviewError(ErrorCode.INVALID_FITS, "bad cutout")
        name = f"art_preview_{id(source)}.png"
        (tmp_path / "previews").mkdir(exist_ok=True)
        (tmp_path / "previews" / name).write_bytes(b"\x89PNG")
        return FakePreview(name)

    monkeypatch.setattr(irsa, "generate_preview", preview)
    import numpy as np

    monkeypatch.setattr(irsa, "_load_source_manifest", lambda src, **kw: tmp_path / "x.fits")
    monkeypatch.setattr(irsa, "_load_image_cutout", lambda *a, **kw: (np.ones((5, 5)), None, (0, 0), True))
    monkeypatch.setattr(irsa, "reproject_north_up", lambda data, *a: data)
    monkeypatch.setattr(irsa, "render_display", lambda arr: np.zeros((5, 5), dtype=np.uint8))

    result = client.discover(269.452, 4.693, radius_arcsec=60)
    assert len(result.epochs) == 3
    first, second, third = result.epochs
    assert first.data_origin == "authentic_live" and first.preview_path is not None
    assert first.band_id == "D2"
    assert first.detector == "D2" and first.release == "DR1"
    assert first.wavelength_range_um == [1.10, 1.62]
    assert first.observation_time_utc.endswith("Z")
    assert second.data_origin == "authentic_cached"
    assert second.preview_path is None and "PREVIEW_FAILED" in second.warnings  # kept, flagged
    assert "SCIENCE_AND_WCS_VALIDATION_PENDING" in third.warnings
    assert any(w.startswith("PLAYING_D2_DR1_3_OF_6") for w in result.warnings)


def test_discover_no_results_is_empty_not_error(client, monkeypatch) -> None:
    monkeypatch.setattr(irsa, "discover", lambda req, **kw: fake_discovery(DiscoveryStatus.NO_RESULTS))
    assert client.discover(10.0, 10.0, 30).epochs == []


@pytest.mark.parametrize(
    "status,code",
    [
        (DiscoveryStatus.TIMEOUT, "ARCHIVE_TIMEOUT"),
        (DiscoveryStatus.HTTP_5XX, "ARCHIVE_HTTP_5XX"),
        (DiscoveryStatus.PARTIAL, "ARCHIVE_CONNECTION_ERROR"),
    ],
)
def test_archive_down_raises_unavailable(client, monkeypatch, status, code) -> None:
    monkeypatch.setattr(irsa, "discover", lambda req, **kw: fake_discovery(status, error_code=code))
    with pytest.raises(ArchiveUnavailableError):
        client.discover(10.0, 10.0, 30)


def test_fov_is_clamped(client, monkeypatch) -> None:
    seen = {}

    def capture(req, **kw):
        seen["fov"] = req.fov_arcmin
        return fake_discovery(DiscoveryStatus.NO_RESULTS)

    monkeypatch.setattr(irsa, "discover", capture)
    client.discover(10.0, 10.0, radius_arcsec=5)
    assert seen["fov"] == pytest.approx(10.0 * 1.42)
    client.discover(10.0, 10.0, radius_arcsec=3600)
    assert seen["fov"] == pytest.approx(30.0 * 1.42)


def test_repeat_query_uses_cache(client, monkeypatch) -> None:
    calls = []

    def counting(req, **kw):
        calls.append(req)
        return fake_discovery(DiscoveryStatus.NO_RESULTS)

    monkeypatch.setattr(irsa, "discover", counting)
    client.discover(10.0, 10.0, 300)
    client.discover(10.0, 10.0, 300)
    assert len(calls) == 1


def _sky_frame(rotated: bool, gradient: bool = False):
    """41x41 float image (FITS order) with one star 60 arcsec north of centre."""
    import numpy as np
    from astropy.wcs import WCS

    ra, dec, scale = 150.0, 20.0, 6.15 / 3600
    w = WCS(naxis=2)
    w.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    w.wcs.crval = [ra, dec]
    w.wcs.crpix = [21, 21]
    w.wcs.cdelt = [-scale, scale]
    if rotated:  # detector flipped by 180 degrees
        w.wcs.pc = [[-1, 0], [0, -1]]
    rng = np.random.default_rng(0)
    img = 100 + rng.normal(0, 1, (41, 41))
    if gradient:  # stray-light ramp, like the bright Mar 2026 frame
        img += np.linspace(0, 80, 41)[:, None]
    x, y = w.world_to_pixel_values(ra, dec + 60 / 3600)
    img[round(float(y)) - 1 : round(float(y)) + 2, round(float(x)) - 1 : round(float(x)) + 2] += 500
    return img, w, ra, dec


def test_rotated_frames_align_to_same_pixel() -> None:
    import numpy as np
    from change_lens.archive.irsa import render_display, reproject_north_up

    peaks = []
    for rotated in (False, True):
        img, w, ra, dec = _sky_frame(rotated)
        arr = render_display(reproject_north_up(img, w, ra, dec, 4.0))
        peaks.append(np.unravel_index(np.argmax(arr), arr.shape))
    assert peaks[0] == peaks[1]  # same pixel after alignment
    assert peaks[0][0] < arr.shape[0] // 2  # north of centre -> upper half in display order


def test_background_gradient_is_removed() -> None:
    import numpy as np
    from change_lens.archive.irsa import render_display, reproject_north_up

    flat_img, w, ra, dec = _sky_frame(False)
    ramp_img, _, _, _ = _sky_frame(False, gradient=True)
    flat = render_display(reproject_north_up(flat_img, w, ra, dec, 4.0)).astype(float)
    ramp = render_display(reproject_north_up(ramp_img, w, ra, dec, 4.0)).astype(float)
    inner = (slice(8, -8), slice(8, -8))
    # Without background subtraction the ramp frame would be far brighter; now they match.
    assert abs(np.median(ramp[inner]) - np.median(flat[inner])) < 10
    top, bottom = np.median(ramp[8:15, 8:-8]), np.median(ramp[-15:-8, 8:-8])
    assert abs(top - bottom) < 10  # no residual gradient


def test_select_frames_honours_requested_detector() -> None:
    observations = [obs(i, 60800 + i * 10) for i in range(10)]  # D2, the biggest group
    observations += [obs(100 + i, 60805 + i * 20, band="SPHEREx-D6") for i in range(4)]
    chosen, _ = select_frames(observations, max_frames=8, detector="D6")
    assert {o.band for o in chosen} == {"SPHEREx-D6"} and len(chosen) == 4
    none, notes = select_frames(observations, max_frames=8, detector="D3")
    assert none == [] and notes == ["NO_OBSERVATIONS_FOR_D3"]


def test_discovery_cache_survives_restart(tmp_path, monkeypatch) -> None:
    """A new client (e.g. after a server restart) reuses the on-disk discovery cache."""
    import numpy as np

    observations = [obs(i, 60800 + i * 30) for i in range(3)]
    calls = []

    def counting(req, **kw):
        calls.append(req)
        return fake_discovery(observations=observations)

    monkeypatch.setattr(irsa, "discover", counting)
    monkeypatch.setattr(irsa, "retrieve", lambda o, **kw: FakeSource(RetrievalMode.CUTOUT))
    (tmp_path / "previews").mkdir()

    def preview(source, target, **kw):
        name = f"p{len(list((tmp_path / 'previews').iterdir()))}.png"
        (tmp_path / "previews" / name).write_bytes(b"x")
        return FakePreview(name)

    monkeypatch.setattr(irsa, "generate_preview", preview)
    monkeypatch.setattr(irsa, "_load_source_manifest", lambda src, **kw: tmp_path / "x.fits")
    monkeypatch.setattr(irsa, "_load_image_cutout", lambda *a, **kw: (np.ones((5, 5)), None, (0, 0), True))
    monkeypatch.setattr(irsa, "reproject_north_up", lambda data, *a: data)
    monkeypatch.setattr(irsa, "render_display", lambda arr: np.zeros((5, 5), dtype=np.uint8))
    (tmp_path / "x.fits").write_bytes(b"FITS")

    def new_client():
        return IrsaArchiveClient(
            data_dir=tmp_path, previews_dir=tmp_path / "previews", cache_dir=tmp_path / "cache", max_frames=3
        )

    first = new_client().discover(10.0, 10.0, 60)
    second = new_client().discover(10.0, 10.0, 60)  # fresh process, same disk
    assert len(calls) == 1
    assert [e.epoch_id for e in second.epochs] == [e.epoch_id for e in first.epochs]
    assert second.epochs[0].preview_path == first.epochs[0].preview_path

    # A deleted preview makes the cache stale -> rediscover
    first.epochs[0].preview_path.unlink()
    new_client().discover(10.0, 10.0, 60)
    assert len(calls) == 2


def test_discovery_cache_portable_to_another_machine(tmp_path) -> None:
    """A data/ folder copied from another machine (absolute Windows paths) still hits the cache."""
    import json

    from change_lens.archive.irsa import IrsaArchiveClient, _relocate

    data = tmp_path / "data"
    (data / "previews" / "aligned").mkdir(parents=True)
    (data / "cached_mefs").mkdir()
    (data / "previews" / "aligned" / "p.png").write_bytes(b"x")
    (data / "cached_mefs" / "s.fits").write_bytes(b"FITS")
    client = IrsaArchiveClient(data, data / "previews", data / "cached_mefs")
    key = (10.0, 10.0, 10.0, None)
    epoch = {
        "epoch_id": "e1", "observation_time_utc": "2025-04-24T21:06:38Z", "mjd": 60789.9,
        "band_id": "D1", "data_origin": "authentic_live",
        "preview_path": r"C:\Users\someone\repo\data\previews\aligned\p.png",
        "flags_summary": {}, "warnings": [], "detector": "D1", "release": "DR1",
        "wavelength_range_um": [0.75, 1.09],
        "source_fits_path": r"C:\Users\someone\repo\data\cached_mefs\s.fits",
    }
    client.discovery_cache_dir.mkdir(parents=True)
    client._cache_file(key).write_text(json.dumps({"epochs": [epoch], "warnings": []}), "utf-8")

    hit = client._load_cached(key)
    assert hit is not None
    assert hit.epochs[0].preview_path == data / "previews" / "aligned" / "p.png"
    assert hit.epochs[0].source_fits_path == data / "cached_mefs" / "s.fits"

    # new entries are stored relative to data/
    client._store_cached(key, hit)
    stored = json.loads(client._cache_file(key).read_text("utf-8"))["epochs"][0]
    assert stored["preview_path"] == "previews/aligned/p.png"
    assert _relocate(stored["source_fits_path"], data) == data / "cached_mefs" / "s.fits"
