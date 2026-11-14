"""Quality flags and bad-pixel masking step.

Status: Pending implementation (SCI workstream).
Mask propagation is not implemented in scaffolding.
"""

from typing import Any


def apply_flag_masks(data_array: Any, mask_array: Any, bitmask_threshold: int = 0) -> Any:
    """Placeholder for data quality flag application and bad-pixel masking.

    Raises NotImplementedError until scientific pipeline is implemented.
    """
    raise NotImplementedError("Flag masking is not implemented in scaffolding.")
