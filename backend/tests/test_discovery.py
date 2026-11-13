from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from requests.exceptions import Timeout

from changelens.contracts import DiscoveryStatus, InvestigationRequest
from changelens.data.discovery import TAP_URL, discover


FIXTURES = Path(__file__).parent / "fixtures"


class FakeResponse:
    def __init__(self, status_code: int, content: bytes, headers: dict[str, str] | None = None):
        self.status_code = status_code
        self.content = content
        self.headers = headers or {"content-type": "application/x-votable+xml"}


class FakeSession:
    def __init__(self, responses: list[FakeResponse | Exception]):
        self.responses = list(responses)
        self.calls: list[dict[str, object]] = []

    def post(self, url: str, *, data: dict[str, object], timeout: tuple[float, float]):
        self.calls.append({"url": url, "data": data, "timeout": timeout})
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def make_request() -> InvestigationRequest:
    return InvestigationRequest(
        target_name="WISE 0855",
        ra_deg=133.7951291667,
        dec_deg=-7.2451472222,
        frame="ICRS",
        fov_arcmin=10,
        band_policy="SAME_SUPPORTED_BAND",
    )


def response(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def no_wait(_: float) -> None:
    return None


def test_recorded_discovery_response_is_normalized_and_saved(tmp_path: Path) -> None:
    raw = response("discovery_one_row.votable")
    session = FakeSession([FakeResponse(200, raw)])

    result = discover(
        make_request(),
        session=session,
        artifact_directory=tmp_path,
        sleep=no_wait,
    )

    assert result.status is DiscoveryStatus.COMPLETE
    assert len(result.observations) == 1
    observation = result.observations[0]
    assert observation.observation_id == "plane-001"
    assert observation.mjd == 40587
    assert observation.observed_at.isoformat() == "1970-01-01T00:00:00+00:00"
    assert observation.band == "SPHEREx-D2"
    assert observation.release == "DR1"
    assert observation.width == 2040 and observation.height == 2040
    assert observation.remote_checksum == "md5:ba0cb5d912601e6ccb45b96245be6234"
    assert observation.access_url is not None and "center=133.7951291667" in str(observation.access_url)

    request = session.calls[0]
    assert request["url"] == TAP_URL
    assert request["timeout"] == (10.0, 60.0)
    payload = request["data"]
    assert payload["FORMAT"] == "votable"
    assert "CONTAINS(POINT('ICRS', 133.7951291667, -7.2451472222), p.poly)" in payload["QUERY"]
    assert result.raw_response_artifact_id is not None
    query_id = f"art_query_{hashlib.sha256(payload['QUERY'].encode('utf-8')).hexdigest()[:16]}"
    assert (tmp_path / f"{query_id}.adql").read_text(encoding="utf-8") == payload["QUERY"]
    assert (tmp_path / f"{result.raw_response_artifact_id}.votable").read_bytes() == raw


def test_discovery_preserves_exact_request_parameters_and_artifact(tmp_path: Path) -> None:
    session = FakeSession([FakeResponse(200, response("discovery_empty.votable"))])

    result = discover(
        make_request(), session=session, artifact_directory=tmp_path, sleep=no_wait
    )

    query_files = list(tmp_path.glob("art_query_*.adql"))
    assert len(query_files) == 1
    query = query_files[0].read_text(encoding="utf-8")
    expected = {
        "endpoint": TAP_URL,
        "REQUEST": "doQuery",
        "LANG": "ADQL",
        "FORMAT": "votable",
        "MAXREC": "50000",
        "QUERY": query,
    }
    assert result.raw_query_parameters == expected

    request_files = list(tmp_path.glob("art_request_*.json"))
    assert len(request_files) == 1
    assert json.loads(request_files[0].read_text(encoding="utf-8")) == expected


def test_repeated_query_responses_keep_distinct_raw_artifacts(tmp_path: Path) -> None:
    first_payload = response("discovery_one_row.votable")
    second_payload = response("discovery_empty.votable")

    first = discover(
        make_request(),
        session=FakeSession([FakeResponse(200, first_payload)]),
        artifact_directory=tmp_path,
        sleep=no_wait,
    )
    second = discover(
        make_request(),
        session=FakeSession([FakeResponse(200, second_payload)]),
        artifact_directory=tmp_path,
        sleep=no_wait,
    )

    assert first.raw_response_artifact_id != second.raw_response_artifact_id
    assert (tmp_path / f"{first.raw_response_artifact_id}.votable").read_bytes() == first_payload
    assert (tmp_path / f"{second.raw_response_artifact_id}.votable").read_bytes() == second_payload


def test_empty_discovery_response_has_a_distinct_outcome(tmp_path: Path) -> None:
    result = discover(
        make_request(),
        session=FakeSession([FakeResponse(200, response("discovery_empty.votable"))]),
        artifact_directory=tmp_path,
        sleep=no_wait,
    )

    assert result.status is DiscoveryStatus.NO_RESULTS
    assert result.observations == []


@pytest.mark.parametrize(
    ("status_code", "expected"),
    [(429, DiscoveryStatus.HTTP_4XX), (503, DiscoveryStatus.HTTP_5XX)],
)
def test_http_failures_are_typed_and_keep_the_raw_response(
    status_code: int, expected: DiscoveryStatus, tmp_path: Path
) -> None:
    raw = b"archive error fixture"
    result = discover(
        make_request(),
        session=FakeSession([FakeResponse(status_code, raw)] * 3),
        artifact_directory=tmp_path,
        sleep=no_wait,
    )

    assert result.status is expected
    assert len(result.observations) == 0
    assert result.raw_response_artifact_id is not None
    assert (tmp_path / f"{result.raw_response_artifact_id}.votable").read_bytes() == raw


def test_timeout_is_bounded_and_typed(tmp_path: Path) -> None:
    session = FakeSession([Timeout("fixture timeout") for _ in range(3)])

    result = discover(
        make_request(), session=session, artifact_directory=tmp_path, sleep=no_wait
    )

    assert result.status is DiscoveryStatus.TIMEOUT
    assert len(session.calls) == 3


def test_votable_overflow_keeps_rows_and_marks_result_partial(tmp_path: Path) -> None:
    result = discover(
        make_request(),
        session=FakeSession([FakeResponse(200, response("discovery_overflow.votable"))]),
        artifact_directory=tmp_path,
        sleep=no_wait,
    )

    assert result.status is DiscoveryStatus.PARTIAL
    assert result.warnings == ["ARCHIVE_RESULT_OVERFLOW"]


def test_retry_is_bounded_and_recovers_from_transient_server_error(tmp_path: Path) -> None:
    session = FakeSession(
        [
            FakeResponse(503, b"temporary outage"),
            FakeResponse(200, response("discovery_empty.votable")),
        ]
    )

    result = discover(
        make_request(), session=session, artifact_directory=tmp_path, sleep=no_wait
    )

    assert result.status is DiscoveryStatus.NO_RESULTS
    assert len(session.calls) == 2


@pytest.mark.parametrize(
    ("collection", "expected_path_release"),
    [("spherex_qr3", "qr3"), ("DR1", "dr1")],
)
def test_collection_filter_maps_archive_release_names(
    collection: str, expected_path_release: str, tmp_path: Path
) -> None:
    request = make_request().model_copy(update={"collection": collection})
    session = FakeSession([FakeResponse(200, response("discovery_empty.votable"))])

    discover(request, session=session, artifact_directory=tmp_path, sleep=no_wait)

    query = session.calls[0]["data"]["QUERY"]
    assert f"a.uri LIKE '%/spherex/{expected_path_release}/%'" in query
