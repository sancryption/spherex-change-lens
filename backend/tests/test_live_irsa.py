from __future__ import annotations

import pytest

from changelens.contracts import DiscoveryStatus, InvestigationRequest
from changelens.data.discovery import discover
from changelens.data.targets import get_target


@pytest.mark.live
def test_live_irsa_barnards_star_smoke() -> None:
    target = get_target("barnards_star")
    request = InvestigationRequest(
        target_name=target.name,
        ra_deg=target.ra_deg,
        dec_deg=target.dec_deg,
        frame=target.frame,
        fov_arcmin=10,
        band_policy="SAME_SUPPORTED_BAND",
    )

    result = discover(request)

    assert result.http_status == 200
    assert result.status in {DiscoveryStatus.COMPLETE, DiscoveryStatus.PARTIAL}
    assert result.observations
    assert result.raw_response_artifact_id
