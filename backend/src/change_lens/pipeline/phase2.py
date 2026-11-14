"""SCI-local SCI-001 -> 005 orchestration; no shared/API contracts or association.

Callers explicitly certify a supported spectral plane and product family. A
2-D detector image or matching BAND alone does not establish wavelength
compatibility. This module never infers an authentic SPHEREx plane selection.
"""

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

import numpy as np
from astropy import units as u

from change_lens.fits.validator import ProductPolicy, ValidationResult, validate_fits
from change_lens.pipeline.alignment import AlignedFrame, reproject_frame
from change_lens.pipeline.centroid import CentroidMeasurement, measure_centroid
from change_lens.pipeline.detection import DetectionResult, detect_sources
from change_lens.pipeline.masks import FlagPolicy, MaskResult, build_quality_masks


@dataclass(frozen=True)
class PlaneIdentity:
    """Caller-verified plane identity, not an assertion inferred from FITS shape."""

    band: str
    product: str
    spectral_plane: str
    release: str

    def __post_init__(self):
        if not all(isinstance(x, str) and x.strip() for x in asdict(self).values()):
            raise ValueError("EXPLICIT_PLANE_IDENTITY_REQUIRED")


@dataclass
class PreparedObservation:
    validated: ValidationResult
    masks: MaskResult
    identity: PlaneIdentity


@dataclass
class AlignedSeries:
    frames: tuple[AlignedFrame, ...]
    reference_index: int
    common_usable_mask: np.ndarray | None
    overlap_fraction: float
    status: Literal["ALIGNED", "INSUFFICIENT_EVIDENCE", "INCOMPATIBLE_PRODUCT"]
    warnings: tuple[str, ...]


@dataclass
class Phase2Result:
    alignment: AlignedSeries
    detections: tuple[DetectionResult, ...]
    centroids: tuple[tuple[CentroidMeasurement, ...], ...]


def align_series(
    observations: list[PreparedObservation], *, reference_index: int = 0
) -> AlignedSeries:
    """Use the explicitly indexed input grid (default first); never silently sort.

    Strict equality of caller-certified band/product/plane and unit scale is
    required. Release/calibration differences are retained as warnings. No
    overlap means no common usable pixels, including quality exclusions.
    """
    if (
        not observations
        or isinstance(reference_index, bool)
        or not isinstance(reference_index, int)
        or not 0 <= reference_index < len(observations)
    ):
        raise ValueError("INVALID_REFERENCE_INDEX_OR_EMPTY_SERIES")
    reference = observations[reference_index]
    warnings = []
    for observation in observations:
        observation.validated.require_valid()
        a, b = observation.identity, reference.identity
        if (a.band, a.product, a.spectral_plane) != (b.band, b.product, b.spectral_plane):
            warnings.append("INCOMPATIBLE_BAND_PRODUCT_OR_PLANE")
        report = observation.validated.report
        for key, expected in (("BAND", a.band), ("PRODTYPE", a.product), ("RELEASE", a.release)):
            if key in report.metadata and report.metadata[key] != expected:
                warnings.append("PLANE_IDENTITY_CONFLICTS_WITH_HEADER")
        try:
            if report.image_unit is None or reference.validated.report.image_unit is None:
                raise ValueError("missing units")
            if u.Unit(report.image_unit) != u.Unit(reference.validated.report.image_unit):
                warnings.append("INCOMPATIBLE_UNIT_SCALE")
        except ValueError:
            warnings.append("MISSING_OR_INVALID_UNITS")
    if warnings:
        return AlignedSeries(
            (), reference_index, None, 0, "INCOMPATIBLE_PRODUCT", tuple(dict.fromkeys(warnings))
        )
    if len({item.identity.release for item in observations}) > 1:
        warnings.append("MIXED_RELEASES")
    if len({item.validated.report.metadata.get("CALVER") for item in observations}) > 1:
        warnings.append("MIXED_CALIBRATIONS")
    frames = tuple(
        reproject_frame(
            item.validated, item.masks, reference.validated.wcs, reference.validated.image.shape
        )
        for item in observations
    )
    for item, frame in zip(observations, frames, strict=True):
        frame.provenance["plane_identity"] = asdict(item.identity)
        frame.provenance["reference_index"] = reference_index
        frame.provenance["reference_observation_id"] = reference.validated.report.observation_id
    overlap = np.logical_and.reduce([frame.usable_mask for frame in frames])
    status = "ALIGNED" if overlap.any() else "INSUFFICIENT_EVIDENCE"
    if not overlap.any():
        warnings.append("NO_COMMON_USABLE_OVERLAP")
    return AlignedSeries(
        frames, reference_index, overlap, float(overlap.mean()), status, tuple(warnings)
    )


def run_phase2(
    paths: list[str | Path],
    identities: list[PlaneIdentity],
    flag_policy: FlagPolicy,
    *,
    product_policy: ProductPolicy | None = None,
    reference_index: int = 0,
    threshold_sigma: float = 5.0,
    centroid_radius: int = 6,
    saturation_level: float | None = None,
) -> Phase2Result:
    """Read local FITS only; reuse SCI-001/002 and preserve their provenance.

    Detection is per aligned epoch; this does not match sources or claim motion.
    Incompatible/no-overlap series never proceed to measurement.
    """
    if len(paths) != len(identities):
        raise ValueError("ONE_PLANE_IDENTITY_PER_OBSERVATION_REQUIRED")
    product_policy = product_policy or ProductPolicy()
    observations = []
    for path, identity in zip(paths, identities, strict=True):
        validated = validate_fits(path, product_policy).require_valid()
        observations.append(
            PreparedObservation(validated, build_quality_masks(validated, flag_policy), identity)
        )
    alignment = align_series(observations, reference_index=reference_index)
    if alignment.status != "ALIGNED":
        return Phase2Result(alignment, (), ())
    detections = tuple(
        detect_sources(frame, threshold_sigma=threshold_sigma, saturation_level=saturation_level)
        for frame in alignment.frames
    )
    centroids = tuple(
        tuple(
            measure_centroid(
                frame, source, radius=centroid_radius, saturation_level=saturation_level
            )
            for source in detection.sources
        )
        for frame, detection in zip(alignment.frames, detections, strict=True)
    )
    return Phase2Result(alignment, detections, centroids)
