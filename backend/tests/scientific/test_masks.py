import numpy as np
import pytest
from change_lens.fits.validator import FitsValidationReport, ValidationResult
from change_lens.pipeline.masks import FlagAction, FlagPolicy, build_quality_masks

POLICY = FlagPolicy(
    "synthetic-v1",
    "SYNTHETIC_TEST_ONLY",
    {
        1: FlagAction.EXCLUDE_UNUSABLE,
        2: FlagAction.RETAIN_WITH_WARNING,
        4: FlagAction.RETAIN,
        8: FlagAction.UNKNOWN_POLICY,
    },
)


def arrays():
    return ValidationResult(
        FitsValidationReport(passed=True, policy_version="synthetic"),
        np.ones((5, 5)),
        np.ones((5, 5)),
        np.zeros((5, 5), dtype=np.uint16),
    )


def test_valid():
    out = build_quality_masks(arrays(), POLICY)
    assert out.valid_count == 25 and out.invalid_count == 0
    assert out.valid_fraction == 1
    assert out.policy_version == "synthetic-v1"


@pytest.mark.parametrize(
    "plane,value,reason",
    [("image", np.nan, "BAD_PIXEL"), ("image", np.inf, "BAD_PIXEL")]
    + [("variance", x, "INVALID_VARIANCE") for x in [0, -1, np.nan, np.inf]]
    + [("flags", 1, "BAD_PIXEL"), ("flags", 8, "UNKNOWN_FLAG"), ("flags", 16, "UNKNOWN_FLAG")],
)
def test_excluded(plane, value, reason):
    data = arrays()
    getattr(data, plane)[2, 2] = value
    out = build_quality_masks(data, POLICY)
    assert not out.usable_mask[2, 2]
    assert out.reason_counts[reason] == 1
    assert out.invalid_count == 1


def test_warning_and_retained():
    data = arrays()
    data.flags[2, 2] = 2
    data.flags[1, 1] = 4
    out = build_quality_masks(data, POLICY)
    assert out.valid_count == 25
    assert not out.clean_mask[2, 2]
    assert out.clean_mask[1, 1]


def test_union_and_determinism():
    data = arrays()
    data.image[2, 2] = np.nan
    data.variance[2, 2] = -1
    data.flags[2, 2] = 1 | 2 | 16
    original = data.flags.copy()
    data.variance[1, 1] = 10
    footprint = np.ones((5, 5), dtype=bool)
    footprint[2, 2] = False
    a = build_quality_masks(data, POLICY, footprint=footprint, edge_width=1, high_variance=5)
    b = build_quality_masks(data, POLICY, footprint=footprint, edge_width=1, high_variance=5)
    assert a.invalid_count == 18
    assert a.reason_counts["EDGE"] == 16
    assert a.reason_counts["BAD_PIXEL"] == 1
    assert a.reason_counts["INVALID_VARIANCE"] == 1
    assert a.reason_counts["OUTSIDE_FOOTPRINT"] == 1
    assert a.reason_counts["HIGH_VARIANCE"] == 1
    assert sum(a.reason_counts.values()) > a.invalid_count
    assert a.unknown_bits[2, 2] == 16
    assert not a.usable_mask[2, 2]
    np.testing.assert_array_equal(a.usable_mask, b.usable_mask)
    np.testing.assert_array_equal(data.flags, original)
    np.testing.assert_array_equal(a.flags, original)
    for reason in a.reason_masks:
        np.testing.assert_array_equal(a.reason_masks[reason], b.reason_masks[reason])


def test_invalid_product():
    data = arrays()
    data.report.passed = False
    with pytest.raises(ValueError, match="INVALID_PRODUCT"):
        build_quality_masks(data, POLICY)
