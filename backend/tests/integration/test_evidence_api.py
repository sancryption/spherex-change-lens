"""Evidence endpoint: BE wiring of SCI phase 4 (SCI-011/012), pipeline faked, offline."""

from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import change_lens.pipeline.difference as difference
import change_lens.pipeline.evidence as sci_evidence
import change_lens.pipeline.phase2 as phase2
import change_lens.pipeline.phase3 as phase3
import numpy as np
import pytest
from astropy.wcs import WCS
from change_lens.archive.mock import MockArchiveClient
from change_lens.config import Settings
from change_lens.contracts import EvidenceResponse
from change_lens.investigations.evidence import build_evidence
from change_lens.investigations.movers import clear_sci_memo, screen_movers
from change_lens.main import create_app
from change_lens.storage.sqlite import Repository
from fastapi.testclient import TestClient
from PIL import Image


@pytest.fixture(autouse=True)
def _fresh_memo():
    clear_sci_memo()
    yield
    clear_sci_memo()


def _wcs(n: int = 20) -> WCS:
    w = WCS(naxis=2)
    w.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    w.wcs.crval = [269.45, 4.69]
    w.wcs.crpix = [(n + 1) / 2, (n + 1) / 2]
    w.wcs.cdelt = [-6.15 / 3600, 6.15 / 3600]
    return w


def _sources(tmp_path: Path, n: int = 3):
    out = []
    for i in range(n):
        f = tmp_path / f"frame{i}.fits"
        f.write_bytes(b"FITS")
        out.append((f"plane_{i}", 60800.0 + i * 100, f, "D2", "DR1"))
    return out


@dataclass
class FakeTrackEvidence:
    track_id: str
    statuses: tuple
    motion: str = "NO_RELIABLE_CHANGE"
    brightness: str = "NO_RELIABLE_CHANGE"
    reason_codes: tuple = ("CONTROL_MOTION:SUPPORTED",)
    limitations: tuple = ()

    @property
    def screened(self):
        return SimpleNamespace(motion_status=self.motion, brightness_status=self.brightness)


def _fake_product(status: str = "AVAILABLE", n: int = 20):
    norm = np.zeros((n, n))
    norm[5, 5], norm[15, 15] = 10.0, -10.0
    return SimpleNamespace(
        status=status,
        earlier_mjd_utc=60800.0,
        later_mjd_utc=61000.0,
        subtraction_order="later_epoch - earlier_epoch",
        unit="MJy/sr",
        variance_status="AVAILABLE",
        warnings=(),
        reason_codes=() if status == "AVAILABLE" else ("CALIBRATION_VERSION_MISMATCH",),
        normalized_image=norm if status == "AVAILABLE" else None,
    )


@pytest.fixture
def fake_sci(monkeypatch):
    calls = {"phase2": 0, "diff_pairs": []}
    frames = [SimpleNamespace(name=f"f{i}", wcs=_wcs()) for i in range(3)]

    def fake_phase2(*a, **kw):
        calls["phase2"] += 1
        return SimpleNamespace(alignment=SimpleNamespace(frames=frames, warnings=()))

    def fake_diff(earlier, later):
        calls["diff_pairs"].append((earlier.name, later.name))
        return calls.get("product") or _fake_product()

    def fake_synth(p3, *, differences=()):
        tracks = (
            FakeTrackEvidence("trk_a", ("NO_RELIABLE_CHANGE",)),
            FakeTrackEvidence(
                "trk_b",
                ("POSSIBLE_POSITIONAL_MOVEMENT", "NO_RELIABLE_CHANGE"),
                motion="POSSIBLE_POSITIONAL_MOVEMENT",
            ),
            FakeTrackEvidence("trk_c", ("ARTIFACT_RISK",), motion="ARTIFACT_RISK"),
        )
        diffs = tuple(
            SimpleNamespace(
                product=d,
                valid_pixel_count=400 if d.status == "AVAILABLE" else 0,
                minimum=-1.5 if d.status == "AVAILABLE" else None,
                maximum=2.5 if d.status == "AVAILABLE" else float("nan"),
                reason_codes=(),
            )
            for d in differences
        )
        return SimpleNamespace(
            tracks=tracks,
            differences=diffs,
            reason_codes=("UTC_TIME_SCALE_ASSUMED",),
            limitations=("CORRELATED_EVIDENCE_NOT_COMBINED",),
        )

    monkeypatch.setattr(phase2, "run_phase2", fake_phase2)
    monkeypatch.setattr(
        phase3,
        "run_phase3",
        lambda p2: SimpleNamespace(tracks=(), warnings=("UTC_TIME_SCALE_ASSUMED",)),
    )
    monkeypatch.setattr(phase3, "possible_movers", lambda p3: ())
    monkeypatch.setattr(difference, "compute_difference", fake_diff)
    monkeypatch.setattr(sci_evidence, "synthesize_evidence", fake_synth)
    return calls


def test_build_evidence_maps_sci_output(tmp_path: Path, fake_sci) -> None:
    result, png = build_evidence("inv_1", _sources(tmp_path), derived_dir=tmp_path / "derived")
    assert result.status == "COMPLETED"
    assert result.frames_used == 3 and result.detector == "D2"
    assert result.tracks_total == 3
    assert result.status_counts == {
        "NO_RELIABLE_CHANGE": 2,
        "POSSIBLE_POSITIONAL_MOVEMENT": 1,
        "ARTIFACT_RISK": 1,
    }
    assert [t.track_id for t in result.notable_tracks] == ["trk_b", "trk_c"]
    # longest baseline: first vs last aligned frame
    assert fake_sci["diff_pairs"] == [("f0", "f2")]
    d = result.difference
    assert d.status == "AVAILABLE"
    assert (d.earlier_epoch_id, d.later_epoch_id) == ("plane_0", "plane_2")
    assert d.minimum == -1.5 and d.maximum == 2.5 and d.valid_pixel_count == 400
    assert "SCREENING_ONLY_NOT_A_DISCOVERY" in result.limitations
    assert "CORRELATED_EVIDENCE_NOT_COMBINED" in result.limitations
    # PNG: mid-grey background, white = brighter, black = fainter
    assert png is not None and png.is_file()
    pix = np.asarray(Image.open(png))
    assert pix.min() < 40 and pix.max() > 215
    assert int(np.median(pix)) in (127, 128)


def test_rejected_difference_is_reported_not_hidden(tmp_path: Path, fake_sci) -> None:
    fake_sci["product"] = _fake_product("REJECTED")
    result, png = build_evidence("inv_1", _sources(tmp_path), derived_dir=tmp_path / "derived")
    assert result.status == "COMPLETED"
    assert result.difference.status == "REJECTED"
    assert result.difference.maximum is None  # NaN -> JSON null
    assert "CALIBRATION_VERSION_MISMATCH" in result.difference.reason_codes
    assert png is None
    assert result.notable_tracks  # track evidence still returned


def test_evidence_failure_is_reported(tmp_path: Path, monkeypatch) -> None:
    def boom(*a, **kw):
        raise ValueError("bad fits")

    monkeypatch.setattr(phase2, "run_phase2", boom)
    result, png = build_evidence("inv_1", _sources(tmp_path), derived_dir=tmp_path)
    assert result.status == "FAILED" and png is None
    assert result.warnings == ["SCI_PIPELINE_ERROR:ValueError"]


def test_movers_and_evidence_share_one_sci_run(tmp_path: Path, fake_sci) -> None:
    sources = _sources(tmp_path)
    screen_movers("inv_1", sources)
    build_evidence("inv_1", sources, derived_dir=tmp_path / "derived")
    assert fake_sci["phase2"] == 1


def test_evidence_disk_cache_survives_restart(tmp_path: Path, fake_sci) -> None:
    sources = _sources(tmp_path)
    kw = {"derived_dir": tmp_path / "derived", "cache_dir": tmp_path / "ec"}
    build_evidence("inv_a", sources, **kw)
    clear_sci_memo()  # simulate a fresh process
    b, png = build_evidence("inv_b", sources, **kw)
    assert fake_sci["phase2"] == 1
    assert b.investigation_id == "inv_b" and png is not None


def test_evidence_unavailable_for_synthetic_data(tmp_path: Path) -> None:
    app = create_app(
        settings=Settings(data_dir=tmp_path),
        repo=Repository(":memory:"),
        archive=MockArchiveClient(tmp_path / "synthetic"),
    )
    client = TestClient(app)
    inv = client.post("/api/v1/investigations/query", json={"ra": 10, "dec": 10}).json()
    r = client.get(f"/api/v1/investigations/{inv['investigation_id']}/evidence")
    assert r.status_code == 200
    body = EvidenceResponse.model_validate(r.json())
    assert body.status == "UNAVAILABLE" and body.difference is None
    assert client.get("/api/v1/investigations/inv_nope/evidence").status_code == 404


def test_evidence_endpoint_serves_difference_png(tmp_path: Path, fake_sci) -> None:
    repo = Repository(":memory:")
    settings = Settings(data_dir=tmp_path, derived_dir=tmp_path / "derived")
    client = TestClient(
        create_app(settings=settings, repo=repo, archive=MockArchiveClient(tmp_path / "synthetic"))
    )
    inv = client.post("/api/v1/investigations/query", json={"ra": 10, "dec": 10}).json()
    inv_id = inv["investigation_id"]
    for s in _sources(tmp_path):
        repo.save_epoch_source(inv_id, *s)
    body = client.get(f"/api/v1/investigations/{inv_id}/evidence").json()
    url = body["difference"]["image_url"]
    assert url and url.startswith("/api/v1/artifacts/")
    img = client.get(url)
    assert img.status_code == 200 and img.headers["content-type"] == "image/png"
    # second call comes from SQLite
    assert client.get(f"/api/v1/investigations/{inv_id}/evidence").json() == body
