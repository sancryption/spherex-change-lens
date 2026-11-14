from __future__ import annotations

import asyncio
import hashlib
import io
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import changelens.api.app as api_module
import numpy as np
from astropy.io import fits
from astropy.wcs import WCS
from changelens.contracts import ChecksumStatus, RetrievalMode, SourceArtifact


def fits_bytes() -> bytes:
    output = io.BytesIO()
    wcs = WCS(naxis=2)
    wcs.wcs.crpix = [16, 16]
    wcs.wcs.cdelt = [-0.01, 0.01]
    wcs.wcs.crval = [133.7951291667, -7.2451472222]
    wcs.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    image = np.arange(31 * 31, dtype=np.float32).reshape((31, 31))
    fits.HDUList(
        [
            fits.PrimaryHDU(),
            fits.ImageHDU(data=image, header=wcs.to_header(), name="IMAGE"),
        ]
    ).writeto(output)
    return output.getvalue()


def write_source_artifact(
    cache_directory: Path,
    manifest_directory: Path,
) -> SourceArtifact:
    artifact_id = "art_source_preview_api_fixture"
    cache_directory.mkdir(parents=True)
    manifest_directory.mkdir(parents=True)
    payload = fits_bytes()
    source_path = cache_directory / f"{artifact_id}.fits"
    source_path.write_bytes(payload)
    artifact = SourceArtifact(
        artifact_id=artifact_id,
        source_url="https://irsa.ipac.caltech.edu/test.fits",
        observation_id="plane-preview-api-001",
        release="DR1",
        size_bytes=len(payload),
        retrieved_at=datetime(2026, 11, 14, tzinfo=UTC),
        sha256=hashlib.sha256(payload).hexdigest(),
        checksum_status=ChecksumStatus.NO_REMOTE_CHECKSUM,
        retrieval_mode=RetrievalMode.CUTOUT,
    )
    manifest = {
        "schema_version": "1.0",
        "artifact": artifact.model_dump(mode="json"),
        "local_path": source_path.name,
    }
    (manifest_directory / f"{artifact_id}.json").write_text(json.dumps(manifest), encoding="utf-8")
    return artifact


def request_asgi(
    app: Any,
    *,
    method: str,
    path: str,
    body: dict[str, object] | None = None,
) -> tuple[int, dict[str, str], bytes]:
    payload = json.dumps(body).encode("utf-8") if body is not None else b""
    request_headers = [(b"content-length", str(len(payload)).encode("ascii"))]
    if body is not None:
        request_headers.append((b"content-type", b"application/json"))
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode("ascii"),
        "query_string": b"",
        "headers": request_headers,
        "client": ("127.0.0.1", 51000),
        "server": ("127.0.0.1", 8000),
    }
    messages: list[dict[str, Any]] = []
    delivered = False

    async def receive():
        nonlocal delivered
        if delivered:
            # A real client stays connected until the response is sent. Returning
            # http.disconnect here makes Starlette's FileResponse abort the body.
            await asyncio.Event().wait()
        delivered = True
        return {"type": "http.request", "body": payload, "more_body": False}

    async def send(message):
        messages.append(message)

    asyncio.run(app(scope, receive, send))
    start = next(item for item in messages if item["type"] == "http.response.start")
    response_body = b"".join(
        item.get("body", b"") for item in messages if item["type"] == "http.response.body"
    )
    response_headers = {
        key.decode("latin-1").lower(): value.decode("latin-1")
        for key, value in start.get("headers", [])
    }
    return start["status"], response_headers, response_body


def test_browser_can_request_preview_and_receive_local_png_without_fits_download(
    tmp_path: Path,
    monkeypatch,
) -> None:
    cache_directory = tmp_path / "cache"
    manifest_directory = tmp_path / "manifests"
    preview_directory = tmp_path / "previews"
    source = write_source_artifact(cache_directory, manifest_directory)
    monkeypatch.setattr(api_module, "DEFAULT_MANIFEST_DIRECTORY", manifest_directory, raising=False)
    monkeypatch.setattr(api_module, "DEFAULT_PREVIEW_DIRECTORY", preview_directory, raising=False)
    app = api_module.create_app(cache_directory=cache_directory)

    status, _, response_body = request_asgi(
        app,
        method="POST",
        path="/v1/previews",
        body={
            "source_artifact_id": source.artifact_id,
            "target_id": "wise_0855",
            "fov_arcmin": 3,
        },
    )

    assert status == 200, response_body
    metadata = json.loads(response_body)
    assert metadata["observation_id"] == source.observation_id
    assert metadata["source_artifact_id"] == source.artifact_id
    assert metadata["preview_url"] == f"/v1/previews/{metadata['artifact_id']}.png"
    assert metadata["validation_status"] == "FITS_CONTAINER_VALIDATED_ONLY"
    assert metadata["warnings"] == ["SCIENCE_AND_WCS_VALIDATION_PENDING"]

    preview_status, headers, png = request_asgi(
        app,
        method="GET",
        path=f"/v1/previews/{metadata['artifact_id']}.png",
    )
    assert preview_status == 200
    assert headers["content-type"] == "image/png"
    assert png.startswith(b"\x89PNG\r\n\x1a\n")

    fits_status, _, _ = request_asgi(
        app,
        method="GET",
        path=f"/v1/previews/{source.artifact_id}.fits",
    )
    assert fits_status == 404

    (cache_directory / f"{source.artifact_id}.fits").write_bytes(b"tampered")
    invalid_status, _, invalid_body = request_asgi(
        app,
        method="POST",
        path="/v1/previews",
        body={
            "source_artifact_id": source.artifact_id,
            "target_id": "wise_0855",
            "fov_arcmin": 3,
        },
    )
    error = json.loads(invalid_body)
    assert invalid_status == 422
    assert error["error"]["code"] == "INVALID_FITS"
