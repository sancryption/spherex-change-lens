"""SCI-local categorical masks. No official SPHEREx bit meanings are assumed."""

from dataclasses import dataclass
from enum import StrEnum

import numpy as np

from change_lens.fits.validator import ValidationResult


class FlagAction(StrEnum):
    EXCLUDE_UNUSABLE = "EXCLUDE_UNUSABLE"
    RETAIN_WITH_WARNING = "RETAIN_WITH_WARNING"
    RETAIN = "RETAIN"
    UNKNOWN_POLICY = "UNKNOWN_POLICY"


@dataclass(frozen=True)
class FlagPolicy:
    """Explicit single-bit actions for a specified release/product or synthetic fixture.

    Undeclared bits are UNKNOWN_POLICY. A zero flag has no asserted flag conditions.
    This does not certify an unreviewed policy for authentic science.
    """

    version: str
    product: str
    bits: dict[int, FlagAction]

    def __post_init__(self):
        if not self.version or not self.product:
            raise ValueError("Policy version and product are required")
        for bit, action in self.bits.items():
            if not isinstance(bit, int) or bit <= 0 or bit > 2**63 or bit & (bit - 1):
                raise ValueError("Policy keys must be individual uint64 bits")
            FlagAction(action)


@dataclass
class MaskResult:
    """Owned output masks; invalid_count is the excluded union, never reason sum.

    Reason layers may overlap. FLAG_WARNING retains otherwise usable pixels;
    unknown flags exclude pixels. clean_mask additionally removes warning pixels.
    """

    usable_mask: np.ndarray
    reason_masks: dict[str, np.ndarray]
    reason_counts: dict[str, int]
    valid_count: int
    invalid_count: int
    valid_fraction: float
    policy_version: str
    flags: np.ndarray
    unknown_bits: np.ndarray
    warnings: list[str]
    policy_product: str

    @property
    def clean_mask(self) -> np.ndarray:
        return self.usable_mask & ~self.reason_masks["FLAG_WARNING"]


def build_quality_masks(
    validated: ValidationResult,
    policy: FlagPolicy,
    *,
    footprint: np.ndarray | None = None,
    edge_width: int = 0,
    high_variance: float | None = None,
    contamination: np.ndarray | None = None,
) -> MaskResult:
    """Consume SCI-001 arrays without mutation; thresholds are caller-selected.

    Footprint must be boolean (True means covered); contamination True excludes.
    High variance uses native variance units; no implicit threshold is applied.
    """
    validated.require_valid()
    image, variance, flags = validated.image, validated.variance, validated.flags
    if image is None or variance is None or flags is None:
        raise ValueError("MISSING_VALIDATED_ARRAYS")
    if (
        image.ndim != 2
        or not image.size
        or variance.shape != image.shape
        or flags.shape != image.shape
    ):
        raise ValueError("INVALID_ARRAY_SHAPE")
    if flags.dtype.kind not in "iu" or np.any(flags < 0):
        raise ValueError("INVALID_FLAGS")
    if isinstance(edge_width, bool) or not isinstance(edge_width, int) or edge_width < 0:
        raise ValueError("Invalid edge width")
    if high_variance is not None and (not np.isfinite(high_variance) or high_variance <= 0):
        raise ValueError("Invalid variance threshold")
    for layer in (footprint, contamination):
        if layer is not None and (layer.shape != image.shape or layer.dtype != np.bool_):
            raise ValueError("Quality layers must be boolean and match image shape")
    names = [
        "BAD_PIXEL",
        "INVALID_VARIANCE",
        "HIGH_VARIANCE",
        "EDGE",
        "OUTSIDE_FOOTPRINT",
        "UNKNOWN_FLAG",
        "FLAG_WARNING",
        "CONTAMINATION",
    ]
    reasons = {name: np.zeros(image.shape, dtype=bool) for name in names}
    reasons["BAD_PIXEL"] |= ~np.isfinite(image)
    reasons["INVALID_VARIANCE"] |= ~np.isfinite(variance) | (variance <= 0)
    if high_variance is not None:
        reasons["HIGH_VARIANCE"] |= variance > high_variance
    if footprint is not None:
        reasons["OUTSIDE_FOOTPRINT"] |= ~footprint
    if contamination is not None:
        reasons["CONTAMINATION"] |= contamination
    if edge_width:
        reasons["EDGE"][:edge_width, :] = True
        reasons["EDGE"][-edge_width:, :] = True
        reasons["EDGE"][:, :edge_width] = True
        reasons["EDGE"][:, -edge_width:] = True
    unsigned = flags.astype(np.uint64)
    known = 0
    unknown = unsigned.copy()
    for bit, action in policy.bits.items():
        action = FlagAction(action)
        selected = (unsigned & np.uint64(bit)) != 0
        if action != FlagAction.UNKNOWN_POLICY:
            known |= bit
        if action == FlagAction.EXCLUDE_UNUSABLE:
            reasons["BAD_PIXEL"] |= selected
        elif action == FlagAction.RETAIN_WITH_WARNING:
            reasons["FLAG_WARNING"] |= selected
    unknown &= np.uint64((2**64 - 1) ^ known)
    reasons["UNKNOWN_FLAG"] |= unknown != 0
    excluded = np.zeros(image.shape, dtype=bool)
    for name, mask in reasons.items():
        if name != "FLAG_WARNING":
            excluded |= mask
    usable = ~excluded
    counts = {name: int(mask.sum()) for name, mask in reasons.items()}
    warnings = list(validated.report.warnings)
    warnings.extend(name for name in ("UNKNOWN_FLAG", "FLAG_WARNING") if counts[name])
    return MaskResult(
        usable,
        reasons,
        counts,
        int(usable.sum()),
        int(excluded.sum()),
        float(usable.mean()),
        policy.version,
        flags.copy(),
        unknown,
        warnings,
        policy.product,
    )


def apply_flag_masks(
    data_array: np.ndarray, mask_array: np.ndarray, bitmask_threshold: int = 0
) -> np.ndarray:
    """Legacy conservative helper: exclude all nonzero flags and nonfinite data.

    Numeric flag thresholds never had implemented semantics. Nonzero thresholds
    are rejected; new SCI consumers should use build_quality_masks.
    """
    if bitmask_threshold != 0:
        raise ValueError("Use a versioned FlagPolicy instead of numeric thresholds")
    if data_array.shape != mask_array.shape or mask_array.dtype.kind not in "iu":
        raise ValueError("Invalid flag array")
    return np.where((mask_array == 0) & np.isfinite(data_array), data_array, np.nan)
