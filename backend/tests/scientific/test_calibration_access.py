"""Official DataLink schema fixture and isolated acquisition rejection tests."""

from pathlib import Path

import pytest
from change_lens.pipeline.calibration import (
    CalibrationReference,
    list_s3_candidates,
    observation_calibration_links,
    parse_datalink_calibration,
    require_irsa_url,
)

FIXTURE = Path(__file__).parents[1] / "fixtures/barnard_datalink.xml"
PUBLISHER = "ivo://irsa.ipac/spherex_dr1?2025W40_1A_0441_1/D1"


def test_real_datalink_schema_names_and_cloud_mirrors():
    content = FIXTURE.read_bytes()
    links = observation_calibration_links(content, PUBLISHER)
    assert len(links) == 15
    assert all(not p["uuid_verified"] for p in links)
    spectral = next(p for p in links if "/spectral_wcs/" in p["url"])
    assert spectral["size_bytes"] == 33312960
    assert spectral["url"].endswith("spectral_wcs_D1_spx_cal-swcs-v5-2026-191.fits")
    assert observation_calibration_links(content, "wrong-publisher") == []
    assert len(observation_calibration_links(content, PUBLISHER, semantics="#this")) == 1


def test_observation_link_does_not_prove_calibration_uuid():
    ref = CalibrationReference("spectral_wcs", "019f4f98-edf0-744b-9600-424841d46dc0")
    with pytest.raises(ValueError, match="ID_UNVERIFIED"):
        parse_datalink_calibration(FIXTURE.read_bytes(), ref)


def test_malicious_mirror_and_query_error_rejected():
    content = FIXTURE.read_bytes().replace(b"nasa-irsa-spherex", b"untrusted-bucket")
    with pytest.raises(ValueError, match="BUCKET"):
        observation_calibration_links(content, PUBLISHER)
    ref = CalibrationReference("spectral_wcs", "019f4f98-edf0-744b-9600-424841d46dc0")
    xml = b'<VOTABLE><RESOURCE><INFO name="QUERY_STATUS" value="ERROR">Invalid ID</INFO></RESOURCE></VOTABLE>'
    with pytest.raises(ValueError, match="DATALINK_QUERY_ERROR"):
        parse_datalink_calibration(xml, ref)


def test_official_s3_url_allowed_but_similar_host_rejected():
    url = "https://nasa-irsa-spherex.s3.amazonaws.com/dr1/spectral_wcs/test.fits"
    require_irsa_url(url)
    with pytest.raises(ValueError):
        require_irsa_url(url.replace("s3.amazonaws.com", "s3.amazonaws.com.example.org"))
    with pytest.raises(ValueError):
        require_irsa_url(url.replace("/dr1/", "/qr2/"))


def test_s3_pagination_and_no_uuid_inference(monkeypatch):
    calls = []

    def get(url, **kwargs):
        calls.append(dict(kwargs["params"]))
        page = len(calls)
        content = f"""<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">
        <Name>nasa-irsa-spherex</Name><IsTruncated>{"true" if page == 1 else "false"}</IsTruncated>
        <Contents><Key>dr1/spectral_wcs/v{page}/1/spectral_wcs_D1_test.fits</Key><Size>100</Size><ETag>etag</ETag></Contents>
        <NextContinuationToken>page2</NextContinuationToken></ListBucketResult>""".encode()
        return type("Response", (), {"status_code": 200, "content": content})()

    monkeypatch.setattr("change_lens.pipeline.calibration.requests.get", get)
    found = list_s3_candidates("spectral_wcs", 1)
    assert len(found) == 2
    assert calls[1]["continuation-token"] == "page2"
    assert all(not item["uuid_verified"] for item in found)
