from __future__ import annotations

import hashlib
import io
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

import changelens.data.retrieval as retrieval_module
import numpy as np
import pytest
from astropy.io import fits
from astropy.wcs import WCS
from changelens.contracts import (
    ChecksumStatus,
    ErrorCode,
    ObservationRecord,
    RetrievalMode,
    SourceArtifact,
)
from changelens.data.retrieval import RetrievalError, retrieve
from requests.exceptions import Timeout


class FakeResponse:
    def __init__(
        self,
        status_code: int,
        body: bytes = b"",
        headers: dict[str, str] | None = None,
        stream_error: Exception | None = None,
    ) -> None:
        self.status_code = status_code
        self.body = body
        self.headers = headers or {"Content-Length": str(len(body))}
        self.stream_error = stream_error

    def iter_content(self, chunk_size: int):
        if self.body:
            yield self.body[: max(1, min(chunk_size, len(self.body) // 2 or 1))]
            remainder = self.body[max(1, min(chunk_size, len(self.body) // 2 or 1)) :]
            if remainder:
                yield remainder
        if self.stream_error:
            raise self.stream_error

    def close(self) -> None:
        return None


class FakeSession:
    def __init__(self, responses: list[FakeResponse | Exception]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, object]] = []

    def get(self, url: str, *, stream: bool, timeout: tuple[float, float]):
        self.calls.append({"url": url, "stream": stream, "timeout": timeout})
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def valid_fits_bytes() -> bytes:
    output = io.BytesIO()
    fits.PrimaryHDU(data=np.zeros((4, 4), dtype=np.int16)).writeto(output)
    return output.getvalue()


def full_file_fits_bytes() -> bytes:
    output = io.BytesIO()
    wcs = WCS(naxis=2)
    wcs.wcs.crpix = [51, 51]
    wcs.wcs.cdelt = [-0.001, 0.001]
    wcs.wcs.crval = [133.0, -7.0]
    wcs.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    header = wcs.to_header()
    image = np.arange(101 * 101, dtype=np.float32).reshape((101, 101))
    flags = np.zeros((101, 101), dtype=np.uint8)
    variance = np.ones((101, 101), dtype=np.float32)
    epsf = np.arange(16, dtype=np.float32)
    fits.HDUList(
        [
            fits.PrimaryHDU(),
            fits.ImageHDU(data=image, header=header, name="IMAGE"),
            fits.ImageHDU(data=flags, header=header, name="FLAGS"),
            fits.ImageHDU(data=variance, header=header, name="VARIANCE"),
            fits.ImageHDU(data=epsf, name="EPSF"),
        ]
    ).writeto(output)
    return output.getvalue()


def observation(
    remote_checksum: str | None = None,
    access_url: str | None = None,
) -> ObservationRecord:
    return ObservationRecord.model_validate(
        {
            "observation_id": "plane-001",
            "access_url": access_url or "https://irsa.ipac.caltech.edu/ibe/data/spherex/dr1/level2/test.fits?center=133.0,-7.0d&size=0.1",
            "release": "DR1",
            "remote_checksum": remote_checksum,
        }
    )


def no_wait(_: float) -> None:
    return None


def retrieve_with(
    session: FakeSession,
    tmp_path: Path,
    remote_checksum: str | None = None,
    access_url: str | None = None,
):
    return retrieve(
        observation(remote_checksum, access_url),
        cache_directory=tmp_path / "cache",
        manifest_directory=tmp_path / "manifests",
        session=session,
        now=lambda: datetime(2026, 11, 14, tzinfo=UTC),
        sleep=no_wait,
    )


def test_valid_fits_without_remote_checksum_is_cached_and_manifested(tmp_path: Path) -> None:
    payload = valid_fits_bytes()
    artifact = retrieve_with(FakeSession([FakeResponse(200, payload)]), tmp_path)

    cache_file = tmp_path / "cache" / f"{artifact.artifact_id}.fits"
    manifest_file = tmp_path / "manifests" / f"{artifact.artifact_id}.json"
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))

    assert cache_file.read_bytes() == payload
    assert artifact.sha256 == hashlib.sha256(payload).hexdigest()
    assert artifact.checksum_status.value == "NO_REMOTE_CHECKSUM"
    assert artifact.retrieval_mode is RetrievalMode.CUTOUT
    assert manifest["artifact"]["sha256"] == artifact.sha256
    assert manifest["local_path"] == cache_file.name
    assert manifest["remote_checksum"] is None


def test_matching_remote_checksum_is_verified(tmp_path: Path) -> None:
    payload = valid_fits_bytes()
    checksum = f"md5:{hashlib.md5(payload, usedforsecurity=False).hexdigest()}"
    artifact = retrieve_with(
        FakeSession([FakeResponse(200, payload)]),
        tmp_path,
        checksum,
        "https://irsa.ipac.caltech.edu/ibe/data/spherex/dr1/level2/test.fits",
    )

    assert artifact.checksum_status.value == "MATCHED"


def test_cutout_does_not_compare_full_file_checksum(tmp_path: Path) -> None:
    payload = valid_fits_bytes()
    checksum_for_full_file = "md5:" + "0" * 32

    artifact = retrieve_with(
        FakeSession([FakeResponse(200, payload)]), tmp_path, checksum_for_full_file
    )

    assert artifact.checksum_status.value == "NO_REMOTE_CHECKSUM"


def test_invalid_explicit_checksum_is_rejected_before_network_access(tmp_path: Path) -> None:
    session = FakeSession([FakeResponse(200, valid_fits_bytes())])

    with pytest.raises(RetrievalError) as raised:
        retrieve_with(session, tmp_path, "md5:not-a-digest")

    assert raised.value.code is ErrorCode.RETRIEVAL_FAILED
    assert raised.value.details["reason"] == "INVALID_REMOTE_CHECKSUM"
    assert session.calls == []


def test_checksum_mismatch_never_promotes_file_or_manifest(tmp_path: Path) -> None:
    wrong_checksum = "md5:" + "0" * 32
    session = FakeSession([FakeResponse(200, valid_fits_bytes())])

    with pytest.raises(RetrievalError) as raised:
        retrieve_with(
            session,
            tmp_path,
            wrong_checksum,
            "https://irsa.ipac.caltech.edu/ibe/data/spherex/dr1/level2/test.fits",
        )

    assert raised.value.details["reason"] == "CHECKSUM_MISMATCH"
    assert list((tmp_path / "cache").glob("*.fits")) == []
    assert list((tmp_path / "manifests").glob("*.json")) == []


def test_partial_download_never_enters_cache(tmp_path: Path) -> None:
    payload = valid_fits_bytes()
    response = FakeResponse(
        200,
        payload,
        headers={"Content-Length": str(len(payload) + 1)},
    )

    with pytest.raises(RetrievalError) as raised:
        retrieve_with(FakeSession([response] * 3), tmp_path)

    assert raised.value.code is ErrorCode.RETRIEVAL_FAILED
    assert raised.value.details["reason"] == "PARTIAL_DOWNLOAD"
    assert list((tmp_path / "cache").glob("*.fits")) == []
    assert list((tmp_path / "manifests").glob("*.json")) == []
    assert list((tmp_path / "cache").glob("*.part")) == []


def test_invalid_fits_never_enters_cache(tmp_path: Path) -> None:
    with pytest.raises(RetrievalError) as raised:
        retrieve_with(
            FakeSession([FakeResponse(200, b"not a FITS file") for _ in range(3)]),
            tmp_path,
        )

    assert raised.value.code is ErrorCode.INVALID_FITS
    assert list((tmp_path / "cache").glob("*.fits")) == []
    assert list((tmp_path / "manifests").glob("*.json")) == []


def test_transient_invalid_archive_body_retries_before_accepting_fits(tmp_path: Path) -> None:
    payload = valid_fits_bytes()
    session = FakeSession([FakeResponse(200, b"invalid body"), FakeResponse(200, payload)])

    artifact = retrieve_with(session, tmp_path)

    assert len(session.calls) == 2
    assert (tmp_path / "cache" / f"{artifact.artifact_id}.fits").read_bytes() == payload


def test_truncated_fits_is_rejected_even_when_length_matches(tmp_path: Path) -> None:
    payload = valid_fits_bytes()[:-5]

    with pytest.raises(RetrievalError) as raised:
        retrieve_with(FakeSession([FakeResponse(200, payload) for _ in range(3)]), tmp_path)

    assert raised.value.code is ErrorCode.INVALID_FITS
    assert list((tmp_path / "cache").glob("*.fits")) == []


def test_cutout_503_falls_back_to_full_file(tmp_path: Path) -> None:
    payload = full_file_fits_bytes()
    remote_checksum = "md5:" + hashlib.md5(payload, usedforsecurity=False).hexdigest()
    cutout_url = "https://irsa.ipac.caltech.edu/ibe/data/spherex/dr1/level2/test.fits?center=133.0,-7.0d&size=0.01"
    session = FakeSession([FakeResponse(503), FakeResponse(200, payload)])

    artifact = retrieve_with(session, tmp_path, remote_checksum, cutout_url)

    assert len(session.calls) == 2
    assert session.calls[0]["url"] == cutout_url
    assert session.calls[1]["url"] == "https://irsa.ipac.caltech.edu/ibe/data/spherex/dr1/level2/test.fits"
    assert artifact.retrieval_mode is RetrievalMode.CUTOUT
    assert artifact.checksum_status.value == "NO_REMOTE_CHECKSUM"
    cache_path = tmp_path / "cache" / f"{artifact.artifact_id}.fits"
    assert cache_path.stat().st_size < len(payload)
    with fits.open(cache_path, mode="readonly") as hdus:
        assert hdus["IMAGE"].data.shape == (10, 10)
        assert hdus["FLAGS"].data.shape == (10, 10)
        assert hdus["VARIANCE"].data.shape == (10, 10)
        assert hdus["EPSF"].data.shape == (16,)
        assert np.array_equal(hdus["EPSF"].data, np.arange(16, dtype=np.float32))
        x, y = WCS(hdus["IMAGE"].header).all_world2pix([[133.0, -7.0]], 0)[0]
        assert 4 <= x <= 5
        assert 4 <= y <= 5
    manifest = json.loads(
        (tmp_path / "manifests" / f"{artifact.artifact_id}.json").read_text(encoding="utf-8")
    )
    assert manifest["fallback_source"]["checksum_status"] == "MATCHED"
    assert manifest["fallback_source"]["sha256"] == hashlib.sha256(payload).hexdigest()
    assert manifest["local_crop"]["cropped_hdu_names"] == ["IMAGE", "FLAGS", "VARIANCE"]
    assert artifact.sha256 == hashlib.sha256(cache_path.read_bytes()).hexdigest()

    cache_hit = retrieve_with(FakeSession([]), tmp_path, remote_checksum, cutout_url)
    assert cache_hit.artifact_id == artifact.artifact_id
    assert cache_hit.retrieval_mode is RetrievalMode.CACHE


def test_uncropped_legacy_full_file_cache_is_refetched_for_cutout(tmp_path: Path) -> None:
    full_file = full_file_fits_bytes()
    checksum = "md5:" + hashlib.md5(full_file, usedforsecurity=False).hexdigest()
    cutout_url = "https://irsa.ipac.caltech.edu/ibe/data/spherex/dr1/level2/test.fits?center=133.0,-7.0d&size=0.01"
    requested_observation = observation(checksum, cutout_url)
    artifact_id = "art_source_" + retrieval_module._request_key(requested_observation)[:24]
    cache_path = tmp_path / "cache" / f"{artifact_id}.fits"
    cache_path.parent.mkdir(parents=True)
    cache_path.write_bytes(full_file)
    legacy_artifact = SourceArtifact(
        artifact_id=artifact_id,
        source_url="https://irsa.ipac.caltech.edu/ibe/data/spherex/dr1/level2/test.fits",
        observation_id="plane-001",
        release="DR1",
        size_bytes=len(full_file),
        retrieved_at=datetime(2026, 11, 14, tzinfo=UTC),
        sha256=hashlib.sha256(full_file).hexdigest(),
        checksum_status=ChecksumStatus.MATCHED,
        retrieval_mode=RetrievalMode.FULL_FILE,
    )
    manifest_path = tmp_path / "manifests" / f"{artifact_id}.json"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "artifact": legacy_artifact.model_dump(mode="json"),
                "requested_url": cutout_url,
                "remote_checksum": checksum,
                "local_path": cache_path.name,
            }
        ),
        encoding="utf-8",
    )
    session = FakeSession([FakeResponse(200, valid_fits_bytes())])

    artifact = retrieve(
        requested_observation,
        cache_directory=tmp_path / "cache",
        manifest_directory=tmp_path / "manifests",
        session=session,
        sleep=no_wait,
    )

    assert len(session.calls) == 1
    assert artifact.retrieval_mode is RetrievalMode.CUTOUT


def test_valid_cache_hit_does_not_call_archive_again(tmp_path: Path) -> None:
    payload = valid_fits_bytes()
    first = retrieve_with(FakeSession([FakeResponse(200, payload)]), tmp_path)
    unused_network = FakeSession([])

    second = retrieve_with(unused_network, tmp_path)

    assert second.artifact_id == first.artifact_id
    assert second.sha256 == first.sha256
    assert second.retrieval_mode is RetrievalMode.CACHE
    assert unused_network.calls == []


def test_timeouts_retry_a_bounded_number_of_times(tmp_path: Path) -> None:
    session = FakeSession([Timeout("fixture timeout") for _ in range(3)])

    with pytest.raises(RetrievalError) as raised:
        retrieve_with(session, tmp_path)

    assert raised.value.details["reason"] == "TIMEOUT"
    assert len(session.calls) == 3
    assert list((tmp_path / "cache").glob("*.fits")) == []


def test_concurrent_retrievals_share_the_cache_budget(tmp_path: Path) -> None:
    payload = valid_fits_bytes()
    first_entered = threading.Event()
    release_first = threading.Event()
    second_entered = threading.Event()

    class CoordinatedSession(FakeSession):
        def __init__(self, *, first: bool) -> None:
            super().__init__([FakeResponse(200, payload)])
            self.first = first

        def get(self, url: str, *, stream: bool, timeout: tuple[float, float]):
            if self.first:
                first_entered.set()
                assert release_first.wait(timeout=5)
            else:
                second_entered.set()
            return super().get(url, stream=stream, timeout=timeout)

    cache_directory = tmp_path / "cache"
    manifest_directory = tmp_path / "manifests"

    def run(item: ObservationRecord, session: CoordinatedSession):
        try:
            result = retrieve(
                item,
                cache_directory=cache_directory,
                manifest_directory=manifest_directory,
                session=session,
                cache_budget_bytes=len(payload),
                max_attempts=1,
                sleep=no_wait,
            )
            return result
        except RetrievalError as exc:
            return exc

    first_observation = observation().model_copy(
        update={"observation_id": "first", "access_url": "https://example.test/first.fits"}
    )
    second_observation = observation().model_copy(
        update={"observation_id": "second", "access_url": "https://example.test/second.fits"}
    )

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(run, first_observation, CoordinatedSession(first=True))
        assert first_entered.wait(timeout=5)
        second = pool.submit(run, second_observation, CoordinatedSession(first=False))
        # Without budget coordination, the second fetch enters while the first
        # response is still pending, so both calls observe the same free space.
        second_entered.wait(timeout=0.25)
        release_first.set()
        results = [first.result(timeout=5), second.result(timeout=5)]

    successes = [item for item in results if not isinstance(item, RetrievalError)]
    cached_files = list(cache_directory.glob("*.fits"))
    assert len(successes) == 1
    assert len(cached_files) == 1
    assert sum(path.stat().st_size for path in cached_files) <= len(payload)


def test_manifest_write_failure_removes_promoted_fits_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail_manifest_write(path: Path, value: dict[str, object]) -> None:
        raise OSError("fixture manifest write failure")

    monkeypatch.setattr(retrieval_module, "_atomic_json", fail_manifest_write)

    with pytest.raises(RetrievalError) as raised:
        retrieve_with(FakeSession([FakeResponse(200, valid_fits_bytes())]), tmp_path)

    assert raised.value.details["reason"] == "STORAGE_WRITE_FAILED"
    assert list((tmp_path / "cache").glob("*.fits")) == []
    assert list((tmp_path / "manifests").glob("*.json")) == []
