from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

import pytest

from changelens.api.app import create_app


def request_asgi(app: Any, *, method: str = "GET", path: str, headers: dict[str, str] | None = None):
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode("ascii"),
        "query_string": b"",
        "headers": [
            (key.lower().encode("latin-1"), value.encode("latin-1"))
            for key, value in (headers or {}).items()
        ],
        "client": ("127.0.0.1", 51000),
        "server": ("127.0.0.1", 8000),
    }
    messages: list[dict[str, Any]] = []
    delivered = False

    async def receive():
        nonlocal delivered
        if delivered:
            return {"type": "http.disconnect"}
        delivered = True
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        messages.append(message)

    asyncio.run(app(scope, receive, send))
    start = next(item for item in messages if item["type"] == "http.response.start")
    body = b"".join(
        item.get("body", b"") for item in messages if item["type"] == "http.response.body"
    )
    response_headers = {
        key.decode("latin-1").lower(): value.decode("latin-1")
        for key, value in start.get("headers", [])
    }
    try:
        decoded = json.loads(body) if body else None
    except json.JSONDecodeError:
        decoded = body.decode("utf-8", errors="replace")
    return start["status"], response_headers, decoded


def test_live_health_does_not_require_storage(tmp_path: Path) -> None:
    app = create_app(cache_directory=tmp_path / "missing")

    status, headers, body = request_asgi(app, path="/health/live")

    assert status == 200
    assert body["status"] == "live"
    assert headers["x-request-id"]


def test_ready_health_reports_storage_state(tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache"
    app = create_app(cache_directory=cache_dir)

    status_before, _, body_before = request_asgi(app, path="/health/ready")
    cache_dir.mkdir()
    status_after, _, body_after = request_asgi(app, path="/health/ready")

    assert status_before == 503
    assert body_before["status"] == "not_ready"
    assert status_after == 200
    assert body_after["storage"] == "available"


def test_targets_endpoint_returns_registry_records(tmp_path: Path) -> None:
    app = create_app(cache_directory=tmp_path / "cache")

    status, _, body = request_asgi(app, path="/v1/targets")

    assert status == 200
    assert {target["target_id"] for target in body} == {
        "barnards_star",
        "epsilon_indi_b",
        "wise_0855",
        "rw_aurigae",
        "r_draconis",
    }
    assert all(target["coverage_status"] == "UNVERIFIED" for target in body)


def test_request_id_is_returned_logged_and_used_in_error_envelope(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    app = create_app(cache_directory=tmp_path / "cache")
    caplog.set_level(logging.INFO, logger="uvicorn.error")

    status, headers, body = request_asgi(
        app,
        path="/not-a-route",
        headers={"X-Request-ID": "req-test-001"},
    )

    assert status == 404
    assert headers["x-request-id"] == "req-test-001"
    assert body["request_id"] == "req-test-001"
    assert body["error"]["code"] == "ARTIFACT_NOT_FOUND"
    assert "req-test-001" in caplog.text


def test_openapi_contains_required_skeleton_routes(tmp_path: Path) -> None:
    app = create_app(cache_directory=tmp_path / "cache")

    schema = app.openapi()

    assert {"/health/live", "/health/ready", "/v1/targets"}.issubset(schema["paths"])


def test_cors_allows_the_local_frontend_origin(tmp_path: Path) -> None:
    app = create_app(cache_directory=tmp_path / "cache")

    status, headers, _ = request_asgi(
        app,
        method="OPTIONS",
        path="/v1/targets",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert status == 200
    assert headers["access-control-allow-origin"] == "http://localhost:5173"
