"""Possible-mover endpoint and BE wiring of SCI phase 2/3 (pipeline faked, offline)."""

from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace

import change_lens.pipeline.phase2 as phase2
import change_lens.pipeline.phase3 as phase3
import pytest
from change_lens.archive.mock import MockArchiveClient
from change_lens.config import Settings
from change_lens.contracts import MoversResponse
from change_lens.investigations.movers import screen_movers
from change_lens.main import create_app
from change_lens.storage.sqlite import Repository
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    app = create_app(
        settings=Settings(data_dir=tmp_path),
        repo=Repository(":memory:"),
        archive=MockArchiveClient(tmp_path / "synthetic"),
    )
    return TestClient(app)


def test_movers_unavailable_for_synthetic_data(client: TestClient) -> None:
    inv = client.post("/api/v1/investigations/query", json={"ra": 10, "dec": 10}).json()
    r = client.get(f"/api/v1/investigations/{inv['investigation_id']}/movers")
    assert r.status_code == 200
    body = MoversResponse.model_validate(r.json())
    assert body.status == "UNAVAILABLE"
    assert body.candidates == []
    assert "NO_FITS_FOR_SYNTHETIC_OR_MISSING_FRAMES" in body.warnings


def test_movers_unknown_investigation_404(client: TestClient) -> None:
    r = client.get("/api/v1/investigations/inv_nope/movers")
    assert r.status_code == 404


def _sources(tmp_path: Path, n: int = 3, detector: str = "D2"):
    out = []
    for i in range(n):
        f = tmp_path / f"frame{i}.fits"
        f.write_bytes(b"FITS")
        out.append((f"plane_{i}", 60800.0 + i * 100, f, detector, "DR1"))
    return out


@dataclass
class FakeCandidate:
    track_id: str = "trk_1"
    label: str = "possible_mover"
    displacement_arcsec: float = 6.1
    baseline_days: float = 200.0
    uncertainty_arcsec: float = 1.2
    control_status: str = "SUPPORTED"
    reason_codes: tuple = ("FINAL_SCREENED_POSITIONAL_MOVEMENT",)
    limitations: tuple = ("PARALLAX_NOT_SEPARATELY_MODELED",)


@dataclass
class FakeTrack:
    motion_status: str


@dataclass
class FakePhase3:
    tracks: tuple = (FakeTrack("POSSIBLE_POSITIONAL_MOVEMENT"), FakeTrack("AMBIGUOUS"), FakeTrack("AMBIGUOUS"))
    warnings: tuple = ("UTC_TIME_SCALE_ASSUMED",)
    association: object = None
    provenance: dict = field(default_factory=dict)


def test_screen_movers_maps_sci_output(tmp_path: Path, monkeypatch) -> None:
    seen = {}

    def fake_phase2(paths, identities, policy, **kw):
        seen.update(paths=paths, identities=identities, policy=policy, kw=kw)
        return SimpleNamespace(alignment=SimpleNamespace(warnings=()))

    monkeypatch.setattr(phase2, "run_phase2", fake_phase2)
    monkeypatch.setattr(phase3, "run_phase3", lambda p2: FakePhase3())
    monkeypatch.setattr(phase3, "possible_movers", lambda p3: (FakeCandidate(),))

    result = screen_movers("inv_1", _sources(tmp_path))
    assert result.status == "COMPLETED"
    assert result.frames_used == 3 and result.detector == "D2"
    assert result.tracks_screened == 3
    assert result.track_status_counts == {"POSSIBLE_POSITIONAL_MOVEMENT": 1, "AMBIGUOUS": 2}
    assert result.candidates[0].displacement_arcsec == 6.1
    assert "SCREENING_ONLY_NOT_A_DISCOVERY" in result.limitations
    # BE defaults handed to SCI
    assert seen["kw"]["centroid_radius"] == 3
    assert (1 << 21) in seen["policy"].bits
    assert {i.band for i in seen["identities"]} == {"D2"}


def test_screen_movers_reports_pipeline_failure(tmp_path: Path, monkeypatch) -> None:
    def boom(*a, **kw):
        raise ValueError("bad fits")

    monkeypatch.setattr(phase2, "run_phase2", boom)
    result = screen_movers("inv_1", _sources(tmp_path))
    assert result.status == "FAILED"
    assert result.warnings == ["SCI_PIPELINE_ERROR:ValueError"]


def test_screen_movers_needs_two_frames_and_one_detector(tmp_path: Path) -> None:
    assert screen_movers("i", _sources(tmp_path, n=1)).status == "UNAVAILABLE"
    mixed = _sources(tmp_path, n=2) + [(
        "plane_x", 61000.0, tmp_path / "frame0.fits", "D6", "DR1"
    )]
    result = screen_movers("i", mixed)
    assert result.status == "UNAVAILABLE" and "MIXED_DETECTORS" in result.warnings


def test_mover_cache_reused_across_investigations(tmp_path: Path, monkeypatch) -> None:
    calls = []

    def fake_phase2(*a, **kw):
        calls.append(1)
        return SimpleNamespace(alignment=SimpleNamespace(warnings=()))

    monkeypatch.setattr(phase2, "run_phase2", fake_phase2)
    monkeypatch.setattr(phase3, "run_phase3", lambda p2: FakePhase3())
    monkeypatch.setattr(phase3, "possible_movers", lambda p3: (FakeCandidate(),))
    sources = _sources(tmp_path)
    a = screen_movers("inv_a", sources, cache_dir=tmp_path / "mc")
    b = screen_movers("inv_b", sources, cache_dir=tmp_path / "mc")
    assert len(calls) == 1
    assert b.investigation_id == "inv_b" and b.candidates == a.candidates
