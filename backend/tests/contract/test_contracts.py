"""Contract verification tests for Pydantic models."""

from change_lens.contracts import CoordinateQueryRequest, TargetListResponse
from change_lens.targets import NASA_PRESET_TARGETS


def test_target_list_contract():
    """Verify TargetListResponse contract serializes expected preset targets."""
    response = TargetListResponse(
        targets=NASA_PRESET_TARGETS,
        total_count=len(NASA_PRESET_TARGETS),
    )
    assert response.total_count == 5
    assert len(response.targets) == 5
    assert response.targets[0].target_id == "barnards-star"


def test_coordinate_query_validation():
    """Verify coordinate bounds validation in contract."""
    query = CoordinateQueryRequest(ra=180.0, dec=-45.0, radius_arcsec=15.0)
    assert query.ra == 180.0
    assert query.dec == -45.0
    assert query.radius_arcsec == 15.0
