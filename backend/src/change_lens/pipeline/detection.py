"""Astronomical source detection pipeline step.

Status: Pending implementation (SCI workstream).
Source detection using photutils/astropy is not implemented in scaffolding.
"""

from typing import Any


def detect_sources(science_image: Any, variance_image: Any, threshold_sigma: float = 3.0) -> Any:
    """Placeholder for source detection on calibrated images.

    Raises NotImplementedError until scientific pipeline is implemented.
    """
    raise NotImplementedError("Source detection is not implemented in scaffolding.")
