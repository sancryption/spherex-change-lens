"""Pipeline execution controls, validation barriers, and configuration parameters."""

from dataclasses import dataclass


@dataclass
class PipelineExecutionControls:
    """Control parameters for scientific pipeline execution."""

    max_cutout_size_pixels: int = 1024
    interpolation_order: str = "bilinear"
    mask_cosmic_rays: bool = True
    mask_saturation: bool = True
    difference_threshold_sigma: float = 3.0
    aperture_radius_pixels: float = 3.0
