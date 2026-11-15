"""SCI-011 conservative aligned difference products; legacy scaffold API retained."""

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Literal

import numpy as np
from astropy.io.fits import Header

from change_lens.pipeline.alignment import AlignedFrame, celestial_grid
from change_lens.pipeline.brightness import compatibility_reasons
from change_lens.pipeline.phase3 import observation_time
from change_lens.pipeline.preparation import PairPreparation


@dataclass(frozen=True)
class DifferenceResult:
    """Owned arrays on the unchanged aligned grid; invalid pixels are NaN.

    AVAILABLE means computable supporting imagery, never a screened discovery.
    REJECTED means incompatible inputs; UNAVAILABLE means no usable pixels.
    Variance requires strictly positive input variance, as in SCI-002/003.
    """

    status: Literal["AVAILABLE", "REJECTED", "UNAVAILABLE"]
    earlier_observation_id: str | None
    later_observation_id: str | None
    earlier_mjd_utc: float | None
    later_mjd_utc: float | None
    plane_identity: dict
    unit: str | None
    image: np.ndarray | None
    variance: np.ndarray | None
    variance_status: Literal["AVAILABLE", "PARTIAL", "UNAVAILABLE"]
    usable_mask: np.ndarray | None
    flags: np.ndarray | None
    reason_masks: dict[str, np.ndarray]
    footprint: np.ndarray | None
    grid: dict
    reason_codes: tuple[str, ...]
    warnings: tuple[str, ...]
    provenance: dict
    subtraction_order: str = "later_epoch - earlier_epoch"

    @property
    def absolute_image(self) -> np.ndarray | None:
        return None if self.image is None else np.abs(self.image)

    @property
    def normalized_image(self) -> np.ndarray | None:
        """Inspection statistic only, NOT calibrated detection significance."""
        if self.image is None or self.variance is None:
            return None
        with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
            value = self.image / np.sqrt(self.variance)
        return np.where(np.isfinite(value), value, np.nan)


def compute_difference(
    earlier: AlignedFrame, later: AlignedFrame, *, preparation: PairPreparation | None = None
) -> DifferenceResult:
    """Subtract an explicitly chronological, certified same-plane aligned pair.

    No sorting, unit conversion, resampling, background/PSF matching or calibration
    is performed. Var(D)=Var(later)+Var(earlier) assumes independent epochs;
    shared calibration and resampling covariance are not modeled. Missing or
    invalid uncertainty excludes affected pixels, never substitutes zero.
    Expected scientific incompatibilities return REJECTED with reason codes.
    """
    frames = (earlier, later)
    validations = [f.provenance.get("validation", {}) for f in frames]
    verified_calibrations = tuple(
        preparation.calibration_signature(v.get("metadata", {}).get("HISTORY"))
        if isinstance(preparation, PairPreparation)
        else None
        for v in validations
    )
    ids = [v.get("observation_id") for v in validations]
    times, reasons = [], []
    # Only explicitly synthetic fixtures retain the legacy demonstration path.
    # A CALVER string (even a real one) alone is not pair preparation evidence.
    synthetic = all(v.get("metadata", {}).get("SYNTHET") in (True, "True") for v in validations)
    if not synthetic or preparation is not None:
        if not isinstance(preparation, PairPreparation):
            reasons.append("PAIR_PREPARATION_REQUIRED")
        else:
            reasons.extend(preparation.rejection_reasons(earlier, later))
    warnings = [w for f in frames for w in f.warnings]
    warnings.extend(
        (
            "UTC_TIME_SCALE_ASSUMED",
            "INDEPENDENT_EPOCH_VARIANCE_ASSUMED",
            "RESAMPLING_COVARIANCE_NOT_MODELED",
            "CALIBRATION_UNCERTAINTY_OMITTED",
            "NO_PSF_OR_BACKGROUND_MATCHING",
            "NORMALIZED_DIFFERENCE_NOT_SIGNIFICANCE",
            "SUPPORTING_IMAGE_NOT_SCREENED_FINDING",
        )
    )
    for index, validation in enumerate(validations):
        metadata = validation.get("metadata", {})
        if validation.get("passed") is not True:
            reasons.append("INPUT_VALIDATION_NOT_PASSED")
        if "OBSID" in metadata and metadata["OBSID"] != validation.get("observation_id"):
            reasons.append("OBSERVATION_ID_CONFLICTS_WITH_HEADER")
        calibration = metadata.get("CALVER")
        if (
            not isinstance(calibration, str) or not calibration.strip()
        ) and not verified_calibrations[index]:
            reasons.append("CALIBRATION_UNKNOWN")
        time, issues = observation_time(metadata)
        times.append(time)
        reasons.extend(issues)
        if metadata.get("TIMESYS", "UTC") != "UTC":
            reasons.append("UNSUPPORTED_TIME_SCALE")
    if not all(isinstance(v, str) and v.strip() for v in ids) or ids[0] == ids[1]:
        reasons.append("UNIQUE_OBSERVATION_IDS_REQUIRED")
    if all(t is not None for t in times) and times[1] <= times[0]:
        reasons.append("INVALID_OBSERVATION_ORDER")
    grid = {}
    for frame in frames:
        shape = frame.image.shape
        if frame.image.ndim != 2 or not frame.image.size:
            reasons.append("INVALID_ARRAY_SHAPE")
        layers = [frame.usable_mask, frame.flags, frame.footprint, *frame.reason_masks.values()]
        if frame.variance is not None:
            layers.append(frame.variance)
        if any(layer.shape != shape for layer in layers):
            reasons.append("INVALID_ARRAY_SHAPE")
        if frame.usable_mask.dtype != np.bool_ or any(
            m.dtype != np.bool_ for m in frame.reason_masks.values()
        ):
            reasons.append("INVALID_MASK_TYPE")
        if frame.flags.dtype.kind not in "iu" or np.any(frame.flags < 0):
            reasons.append("INVALID_FLAGS")
        try:
            celestial_grid(frame.wcs, shape)
            # FITS header equality includes SIP but not external distortion tables.
            if any(
                getattr(frame.wcs, k) is not None
                for k in ("cpdis1", "cpdis2", "det2im1", "det2im2")
            ):
                reasons.append("UNSUPPORTED_GRID_DISTORTION_TABLE")
            header = frame.wcs.to_header(relax=True)
            if "target_wcs" not in frame.provenance or "shape_out" not in frame.provenance:
                reasons.append("MISSING_ALIGNMENT_PROVENANCE")
            elif (
                Header.fromstring(frame.provenance["target_wcs"]) != header
                or tuple(frame.provenance["shape_out"]) != shape
            ):
                reasons.append("GRID_PROVENANCE_MISMATCH")
            grid = {
                "wcs_header": header.tostring(),
                "shape": shape,
                "comparison": "exact-header-and-shape; no resampling",
            }
        except (ValueError, TypeError, AttributeError):
            reasons.append("INVALID_WCS_OR_GRID")
    if "INVALID_WCS_OR_GRID" not in reasons:
        reasons.extend(
            compatibility_reasons(list(frames), verified_calibrations=verified_calibrations)
        )
    for frame in frames:
        identity = frame.provenance.get("plane_identity", {})
        if not all(
            isinstance(identity.get(k), str) and identity[k].strip()
            for k in ("band", "product", "spectral_plane", "release")
        ):
            reasons.append("MISSING_PLANE_IDENTITY")
    provenance = deepcopy(
        {
            "method": "aligned-later-minus-earlier-v1",
            "earlier": earlier.provenance,
            "later": later.provenance,
            "variance_method": "independent_epoch_sum",
            "pair_preparation": preparation.to_dict()
            if isinstance(preparation, PairPreparation)
            else None,
        }
    )

    def result(
        status,
        image=None,
        variance=None,
        variance_status="UNAVAILABLE",
        usable=None,
        flags=None,
        masks=None,
        footprint=None,
    ):
        return DifferenceResult(
            status,
            *ids,
            *times,
            deepcopy(earlier.provenance.get("plane_identity", {})),
            validations[0].get("image_unit"),
            image,
            variance,
            variance_status,
            usable,
            flags,
            masks or {},
            footprint,
            grid,
            tuple(dict.fromkeys(reasons)),
            tuple(dict.fromkeys(warnings)),
            provenance,
        )

    if reasons:
        return result("REJECTED")
    shape = earlier.image.shape
    masks = {
        name: np.zeros(shape, bool)
        for name in sorted(set(earlier.reason_masks) | set(later.reason_masks))
    }
    for frame in frames:
        for name, mask in frame.reason_masks.items():
            masks[name] |= mask
    usable = earlier.usable_mask & later.usable_mask
    bad_image = ~np.isfinite(earlier.image) | ~np.isfinite(later.image)
    bad_coverage = np.zeros(shape, bool)
    bad_variance = np.zeros(shape, bool)
    for frame in frames:
        bad_coverage |= (
            ~np.isfinite(frame.footprint)
            | (frame.footprint < 1 - 1e-10)
            | (frame.footprint > 1 + 1e-10)
        )
        if frame.variance is None:
            bad_variance[:] = True
            reasons.append("MISSING_VARIANCE")
        else:
            bad_variance |= ~np.isfinite(frame.variance) | (frame.variance <= 0)
    with np.errstate(over="ignore", invalid="ignore"):
        image = np.asarray(later.image, dtype=float) - np.asarray(earlier.image, dtype=float)
        variance = (
            None
            if any(f.variance is None for f in frames)
            else np.asarray(earlier.variance, dtype=float) + np.asarray(later.variance, dtype=float)
        )
    bad_image |= ~np.isfinite(image)
    if variance is not None:
        bad_variance |= ~np.isfinite(variance) | (variance <= 0)
    for name, layer in (
        ("BAD_PIXEL", bad_image),
        ("INVALID_VARIANCE", bad_variance),
        ("OUTSIDE_FOOTPRINT", bad_coverage),
    ):
        masks.setdefault(name, np.zeros(shape, bool))[:] |= layer
    usable &= ~(bad_image | bad_variance | bad_coverage)
    image[~usable] = np.nan
    if variance is not None:
        variance[~usable] = np.nan
    for name, layer in masks.items():
        if layer.any():
            reasons.append(name)
    if not usable.all():
        reasons.append("EXCLUDED_INPUT_PIXELS")
    if not usable.any():
        reasons.append("NO_USABLE_DIFFERENCE_PIXELS")
    variance_status = (
        "UNAVAILABLE" if not usable.any() else "AVAILABLE" if usable.all() else "PARTIAL"
    )
    if variance_status == "UNAVAILABLE":
        variance = None
    return result(
        "AVAILABLE" if usable.any() else "UNAVAILABLE",
        image,
        variance,
        variance_status,
        usable,
        earlier.flags.astype(np.uint64) | later.flags.astype(np.uint64),
        masks,
        np.minimum(earlier.footprint, later.footprint),
    )


def compute_difference_image(
    reference_image: Any, target_image: Any, parameters: dict[str, Any]
) -> Any:
    """Legacy untyped scaffold; use compute_difference with certified AlignedFrames.

    Retained without enabling unsafe raw-array subtraction or interpreting an
    unversioned parameters dict as scientific compatibility certification.
    """
    raise NotImplementedError("Use SCI-local compute_difference(earlier, later).")
