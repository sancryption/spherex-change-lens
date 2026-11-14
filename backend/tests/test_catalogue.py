from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import pytest
import requests
from astropy import units as u
from astropy.coordinates import SkyCoord
from changelens.data.catalogue import (
    AllWISEAdapter,
    CatalogueCandidate,
    CatalogueContextStatus,
    GaiaDR3Adapter,
    add_catalogue_context,
)


@dataclass
class _FakeAdapter:
    catalogue_name: str
    candidates: Sequence[CatalogueCandidate] = ()
    error: Exception | None = None
    calls: int = 0

    def search_cone(
        self, position: SkyCoord, radius_arcsec: float
    ) -> Sequence[CatalogueCandidate]:
        self.calls += 1
        if self.error:
            raise self.error
        return self.candidates


@dataclass
class _FakeResponse:
    content: bytes
    text: str

    def raise_for_status(self) -> None:
        return None


class _FakeSession:
    def __init__(self, response: _FakeResponse):
        self.response = response
        self.post_call: dict[str, object] | None = None
        self.get_call: dict[str, object] | None = None

    def post(self, url: str, *, data: dict[str, str], timeout: tuple[float, float]):
        self.post_call = {"url": url, "data": data, "timeout": timeout}
        return self.response

    def get(self, url: str, *, params: dict[str, str], timeout: tuple[float, float]):
        self.get_call = {"url": url, "params": params, "timeout": timeout}
        return self.response


def _center() -> SkyCoord:
    return SkyCoord(ra=10.0 * u.deg, dec=0.0 * u.deg, frame="icrs")


def _candidate(
    *, catalogue: str = "Fixture", source_id: str = "source-1", ra_deg: float = 10.0002
) -> CatalogueCandidate:
    return CatalogueCandidate(
        catalogue=catalogue,
        source_id=source_id,
        ra_deg=ra_deg,
        dec_deg=0.0,
        attributes={"magnitude": 15.2},
    )


def test_catalogue_context_is_disabled_by_default_and_preserves_core_result() -> None:
    core_result = object()
    adapter = _FakeAdapter("fixture", [_candidate()])

    result = add_catalogue_context(core_result, _center(), 2.0, adapters=[adapter])

    assert result.core_result is core_result
    assert result.context.status is CatalogueContextStatus.DISABLED
    assert result.context.matches == ()
    assert adapter.calls == 0


def test_successful_cone_match_is_labeled_contextual_with_computed_separation() -> None:
    core_result = {"timeline": "unchanged"}
    adapter = _FakeAdapter("fixture", [_candidate()])

    result = add_catalogue_context(
        core_result, _center(), 2.0, enabled=True, adapters=[adapter]
    )

    assert result.core_result is core_result
    assert result.context.status is CatalogueContextStatus.COMPLETE
    assert len(result.context.matches) == 1
    match = result.context.matches[0]
    assert match.source_id == "source-1"
    assert match.classification == "CONTEXTUAL"
    assert match.separation_arcsec == pytest.approx(0.72, abs=0.01)


def test_provider_timeout_becomes_warning_without_changing_core_result() -> None:
    core_result = {"analysis": [1, 2, 3]}
    adapter = _FakeAdapter("Gaia DR3", error=requests.Timeout())

    result = add_catalogue_context(
        core_result, _center(), 2.0, enabled=True, adapters=[adapter]
    )

    assert result.core_result is core_result
    assert result.core_result == {"analysis": [1, 2, 3]}
    assert result.context.status is CatalogueContextStatus.UNAVAILABLE
    assert result.context.matches == ()
    assert result.context.warnings == ("CATALOGUE_QUERY_FAILED:Gaia DR3:Timeout",)


def test_one_failed_provider_keeps_successful_contextual_matches() -> None:
    successful = _FakeAdapter("Gaia DR3", [_candidate(catalogue="Gaia DR3")])
    failed = _FakeAdapter("AllWISE", error=OSError("service unavailable"))

    result = add_catalogue_context(
        {"timeline": "present"},
        _center(),
        2.0,
        enabled=True,
        adapters=[successful, failed],
    )

    assert result.context.status is CatalogueContextStatus.PARTIAL
    assert [match.catalogue for match in result.context.matches] == ["Gaia DR3"]
    assert result.context.matches[0].classification == "CONTEXTUAL"
    assert result.context.warnings == ("CATALOGUE_QUERY_FAILED:AllWISE:OSError",)


def test_candidates_outside_requested_radius_are_not_returned() -> None:
    adapter = _FakeAdapter(
        "fixture",
        [
            _candidate(source_id="inside", ra_deg=10.0002),
            _candidate(source_id="outside", ra_deg=10.002),
        ],
    )

    result = add_catalogue_context(
        None, _center(), 1.0, enabled=True, adapters=[adapter]
    )

    assert [match.source_id for match in result.context.matches] == ["inside"]
    assert result.context.matches[0].separation_arcsec <= 1.0


def test_enabled_lookup_without_adapters_returns_warning_not_exception() -> None:
    result = add_catalogue_context(None, _center(), 2.0, enabled=True)

    assert result.context.status is CatalogueContextStatus.UNAVAILABLE
    assert result.context.warnings == ("NO_CATALOGUE_ADAPTERS_CONFIGURED",)


def test_invalid_region_is_rejected_before_querying_adapters() -> None:
    adapter = _FakeAdapter("fixture", [_candidate()])

    with pytest.raises(ValueError, match="radius_arcsec"):
        add_catalogue_context(
            None, _center(), 0.0, enabled=True, adapters=[adapter]
        )

    assert adapter.calls == 0


def test_provider_row_limit_requires_a_bounded_integer() -> None:
    with pytest.raises(ValueError, match="max_rows"):
        GaiaDR3Adapter(max_rows=1.5)  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="max_rows"):
        AllWISEAdapter(max_rows=101)


def test_gaia_dr3_adapter_uses_timed_tap_query_and_parses_csv() -> None:
    response = _FakeResponse(
        content=b"source_id,ra,dec,phot_g_mean_mag\n123456789,10.0002,0,15.2\n",
        text="source_id,ra,dec,phot_g_mean_mag\n123456789,10.0002,0,15.2\n",
    )
    session = _FakeSession(response)
    adapter = GaiaDR3Adapter(session=session, timeout=(1.0, 2.0))

    candidates = adapter.search_cone(_center(), 2.0)

    assert len(candidates) == 1
    assert candidates[0].catalogue == "Gaia DR3"
    assert candidates[0].source_id == "123456789"
    assert candidates[0].attributes["phot_g_mean_mag"] == pytest.approx(15.2)
    assert session.post_call is not None
    assert session.post_call["timeout"] == (1.0, 2.0)
    assert "tap-server/tap/sync" in str(session.post_call["url"])
    form = session.post_call["data"]
    assert form["REQUEST"] == "doQuery"
    assert form["LANG"] == "ADQL"
    assert form["FORMAT"] == "csv"
    assert "gaiadr3.gaia_source" in form["QUERY"]


def test_allwise_adapter_uses_bounded_gator_cone_query_and_parses_votable() -> None:
    votable = b"""<?xml version="1.0"?>
<VOTABLE version="1.3" xmlns="http://www.ivoa.net/xml/VOTable/v1.3">
  <RESOURCE><TABLE>
    <FIELD name="designation" datatype="char" arraysize="*"/>
    <FIELD name="ra" datatype="double" unit="deg"/>
    <FIELD name="dec" datatype="double" unit="deg"/>
    <FIELD name="w1mpro" datatype="float" unit="mag"/>
    <FIELD name="w2mpro" datatype="float" unit="mag"/>
    <FIELD name="w3mpro" datatype="float" unit="mag"/>
    <FIELD name="w4mpro" datatype="float" unit="mag"/>
    <DATA><TABLEDATA><TR>
      <TD>J004000.00+0000000</TD><TD>10.0002</TD><TD>0</TD>
      <TD>12.1</TD><TD>11.7</TD><TD>8.2</TD><TD>6.0</TD>
    </TR></TABLEDATA></DATA>
  </TABLE></RESOURCE>
</VOTABLE>"""
    session = _FakeSession(_FakeResponse(content=votable, text=votable.decode()))
    adapter = AllWISEAdapter(session=session, timeout=(1.0, 2.0), max_rows=7)

    candidates = adapter.search_cone(_center(), 2.0)

    assert len(candidates) == 1
    assert candidates[0].catalogue == "AllWISE"
    assert candidates[0].source_id == "J004000.00+0000000"
    assert candidates[0].attributes["w1mpro"] == pytest.approx(12.1)
    assert session.get_call is not None
    assert session.get_call["timeout"] == (1.0, 2.0)
    params = session.get_call["params"]
    assert params["catalog"] == "allwise_p3as_psd"
    assert params["spatial"] == "cone"
    assert params["radunits"] == "arcsec"
    assert params["outfmt"] == "3"
    assert params["outrows"] == "7"

