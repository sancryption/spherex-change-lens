"""API integration tests in mock-archive mode (synthetic data only)."""

from pathlib import Path

import pytest
from change_lens.archive.mock import MockArchiveClient
from change_lens.contracts import ErrorResponse, InvestigationMetadata, TimelineResponse
from change_lens.main import create_app
from change_lens.storage.sqlite import Repository
from fastapi.testclient import TestClient

WISE = {"ra": 133.79513, "dec": -7.24514, "target_id": "wise-0855"}


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    from change_lens.config import Settings

    settings = Settings(data_dir=tmp_path)
    archive = MockArchiveClient(tmp_path / "synthetic")
    return TestClient(create_app(settings=settings, repo=Repository(":memory:"), archive=archive))


def query(client: TestClient, body: dict = WISE) -> InvestigationMetadata:
    r = client.post("/api/v1/investigations/query", json=body)
    assert r.status_code == 201, r.text
    return InvestigationMetadata.model_validate(r.json())


def test_health(client: TestClient) -> None:
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["archive"] == "mock"


def test_request_id_echoed(client: TestClient) -> None:
    r = client.get("/health", headers={"X-Request-ID": "req_test"})
    assert r.headers["X-Request-ID"] == "req_test"


def test_targets(client: TestClient) -> None:
    body = client.get("/api/v1/targets").json()
    assert body["total_count"] == 5


def test_target_coverage_is_never_verified_in_mock_mode(client: TestClient) -> None:
    body = client.get("/api/v1/targets/wise-0855/coverage").json()
    assert body["available_epochs_count"] == 5
    assert body["verification_status"] == "pending_verification"


def test_unknown_target_coverage_404(client: TestClient) -> None:
    r = client.get("/api/v1/targets/planet-x/coverage")
    assert r.status_code == 404
    assert ErrorResponse.model_validate(r.json()).error.code == "TARGET_NOT_FOUND"


def test_query_and_get_investigation(client: TestClient) -> None:
    inv = query(client)
    assert inv.target_name == "WISE 0855"
    assert inv.status == "timeline_ready"
    again = client.get(f"/api/v1/investigations/{inv.investigation_id}")
    assert again.json()["investigation_id"] == inv.investigation_id


def test_free_coordinates(client: TestClient) -> None:
    inv = query(client, {"ra": 10.5, "dec": 41.2})
    assert inv.target_name is None


def test_timeline_sorted_labelled_and_keeps_bad_frames(client: TestClient) -> None:
    inv = query(client)
    tl = TimelineResponse.model_validate(
        client.get(f"/api/v1/investigations/{inv.investigation_id}/timeline").json()
    )
    assert tl.total_epochs == 5
    mjds = [e.mjd for e in tl.epochs]
    assert mjds == sorted(mjds)
    assert all(e.data_origin == "synthetic" for e in tl.epochs)
    no_preview = [e for e in tl.epochs if e.preview_url is None]
    assert len(no_preview) == 1  # outside-footprint frame kept, flagged, no image
    assert no_preview[0].quality_warning
    assert "OUTSIDE_FOOTPRINT" in no_preview[0].warnings


def test_preview_png_served(client: TestClient) -> None:
    inv = query(client)
    tl = client.get(f"/api/v1/investigations/{inv.investigation_id}/timeline").json()
    url = next(e["preview_url"] for e in tl["epochs"] if e["preview_url"])
    r = client.get(url)
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"
    assert r.content[:8] == b"\x89PNG\r\n\x1a\n"


@pytest.mark.parametrize(
    "body,code",
    [
        ({"ra": 10, "dec": 95}, "INVALID_COORDINATES"),
        ({"ra": 360, "dec": 0}, "INVALID_COORDINATES"),
        ({"ra": 10, "dec": 0, "radius_arcsec": 0}, "INVALID_REQUEST"),
    ],
)
def test_invalid_query_returns_envelope(client: TestClient, body: dict, code: str) -> None:
    r = client.post("/api/v1/investigations/query", json=body)
    assert r.status_code == 422
    env = ErrorResponse.model_validate(r.json())
    assert env.error.code == code
    assert env.request_id == r.headers["X-Request-ID"]


def test_unknown_target_in_query(client: TestClient) -> None:
    r = client.post("/api/v1/investigations/query", json={"ra": 1, "dec": 1, "target_id": "planet-x"})
    assert r.status_code == 404


def test_unknown_investigation_404(client: TestClient) -> None:
    r = client.get("/api/v1/investigations/inv_nope/timeline")
    assert r.status_code == 404
    assert ErrorResponse.model_validate(r.json()).error.code == "NOT_FOUND"


def test_unknown_artifact_404(client: TestClient) -> None:
    r = client.get("/api/v1/artifacts/art_nope/preview")
    assert r.status_code == 404
    assert ErrorResponse.model_validate(r.json()).error.code == "ARTIFACT_NOT_FOUND"


def test_artifact_outside_allowed_roots_refused(tmp_path: Path) -> None:
    from change_lens.config import Settings

    repo = Repository(":memory:")
    secret = tmp_path / "outside" / "secret.png"
    secret.parent.mkdir()
    secret.write_bytes(b"\x89PNG\r\n\x1a\nsecret")
    repo.save_artifact("art_evil", secret, "image/png")
    app = create_app(
        settings=Settings(data_dir=tmp_path / "data"),
        repo=repo,
        archive=MockArchiveClient(tmp_path / "data" / "synthetic"),
    )
    assert TestClient(app).get("/api/v1/artifacts/art_evil/preview").status_code == 404
