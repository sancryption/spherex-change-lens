"""Fail-closed real-data pair preparation primitives.

Policies have no scientific defaults. A review reference records where tolerances,
source-free regions and uncertainty assumptions were justified. Interval overlap
is not a measurement of the full filter transmission function.
"""

import json
from dataclasses import asdict, dataclass
from hashlib import sha256
from pathlib import Path

import numpy as np
from astropy import units as u
from astropy.io import fits

from change_lens.pipeline.alignment import AlignedFrame
from change_lens.pipeline.calibration import (
    VerifiedCalibration,
    calibration_reasons,
    check_cached_product,
)


def array_digest(array):
    a = np.ascontiguousarray(array)
    return sha256(str((a.shape, a.dtype.str)).encode() + a.tobytes()).hexdigest()


def frame_digest(frame: AlignedFrame):
    """Bind evidence to arrays, masks, metadata and the exact aligned WCS."""
    content = {
        "arrays": {
            k: array_digest(getattr(frame, k))
            for k in ("image", "variance", "flags", "usable_mask", "footprint")
        },
        "reasons": {k: array_digest(v) for k, v in sorted(frame.reason_masks.items())},
        "wcs": frame.wcs.to_header(relax=True).tostring(),
        "provenance": frame.provenance,
    }
    return sha256(json.dumps(content, sort_keys=True, allow_nan=False).encode()).hexdigest()


@dataclass(frozen=True)
class ScientificPolicy:
    review_reference: str
    max_wavelength_delta_um: float
    min_interval_overlap: float
    max_psf_l1_distance: float

    def __post_init__(self):
        if (
            not self.review_reference.strip()
            or not all(
                np.isfinite(v)
                for v in (
                    self.max_wavelength_delta_um,
                    self.min_interval_overlap,
                    self.max_psf_l1_distance,
                )
            )
            or self.max_wavelength_delta_um < 0
            or not 0 <= self.min_interval_overlap <= 1
            or not 0 <= self.max_psf_l1_distance <= 2
        ):
            raise ValueError("INVALID_REVIEWED_SCIENTIFIC_POLICY")


@dataclass(frozen=True)
class SpectralMap:
    wavelength_um: np.ndarray
    bandwidth_um: np.ndarray
    calibration: VerifiedCalibration
    mapping_evidence: str


def load_spectral_map(
    product: VerifiedCalibration,
    path: Path,
    detector: int,
    detector_x: np.ndarray,
    detector_y: np.ndarray,
    mapping_evidence: str,
) -> SpectralMap:
    """Read official native-pixel CWAVE/CBAND at explicit detector coordinates.

    Coordinates are zero-based integers. Fractional/resampled pixels require a
    separate response-mixture model; nearest-neighbor approximation is refused.
    Cutout offsets must come from verified cutout provenance, not image dimensions.
    """
    check_cached_product(product, path)
    if product.reference.role != "spectral_wcs" or not mapping_evidence.strip():
        raise ValueError("SPECTRAL_MAPPING_EVIDENCE_REQUIRED")
    x, y = np.asarray(detector_x), np.asarray(detector_y)
    if (
        x.shape != y.shape
        or x.ndim != 2
        or not x.size
        or any(not np.isfinite(a).all() or np.any(a != np.floor(a)) for a in (x, y))
    ):
        raise ValueError("EXACT_NATIVE_DETECTOR_COORDINATES_REQUIRED")
    layers = []
    with fits.open(path, memmap=False) as hdus:
        for name in ("CWAVE", "CBAND"):
            hdu = hdus[name]
            declared = hdu.header.get("DETECTOR", hdus[0].header.get("DETECTOR"))
            if declared != detector:
                raise ValueError("CALIBRATION_DETECTOR_UNVERIFIED")
            if (
                hdu.data.ndim != 2
                or np.any(x < 0)
                or np.any(y < 0)
                or np.any(x >= hdu.data.shape[1])
                or np.any(y >= hdu.data.shape[0])
            ):
                raise ValueError("SPECTRAL_MAPPING_OUTSIDE_PRODUCT")
            factor = u.Unit(hdu.header["BUNIT"]).to(u.um)
            layers.append(np.array(hdu.data[y.astype(int), x.astype(int)], float) * factor)
    return SpectralMap(*layers, product, mapping_evidence)


def compare_spectra(
    first: SpectralMap, second: SpectralMap, region: np.ndarray, policy: ScientificPolicy | None
):
    """Compare every selected pixel; never silently shrink a measurement region."""
    arrays = (first.wavelength_um, first.bandwidth_um, second.wavelength_um, second.bandwidth_um)
    if (
        region.dtype != np.bool_
        or region.ndim != 2
        or not region.any()
        or any(a.shape != region.shape for a in arrays)
    ):
        raise ValueError("INVALID_MEASUREMENT_REGION")
    reasons = []
    valid = np.logical_and.reduce([np.isfinite(a) & (a > 0) for a in arrays])
    evidence = {
        "region_sha256": array_digest(region),
        "region_pixels": int(region.sum()),
        "calibrations": [first.calibration.to_dict(), second.calibration.to_dict()],
        "mapping_evidence": [first.mapping_evidence, second.mapping_evidence],
        "method": "CWAVE-CBAND-interval-intersection-over-union-v1",
        "limitation": "Intervals are not full transmission curves or a color correction",
        "policy": asdict(policy) if policy else None,
    }
    if not valid[region].all():
        reasons.append("INVALID_SPECTRAL_PIXELS")
    else:
        a, aw, b, bw = (v[region] for v in arrays)
        left, right = np.maximum(a - aw / 2, b - bw / 2), np.minimum(a + aw / 2, b + bw / 2)
        intersection = np.maximum(right - left, 0)
        overlap = intersection / (aw + bw - intersection)
        evidence.update(
            max_delta_um=float(np.max(abs(a - b))),
            median_delta_um=float(np.median(abs(a - b))),
            min_interval_overlap=float(np.min(overlap)),
        )
        if policy and (
            evidence["max_delta_um"] > policy.max_wavelength_delta_um
            or evidence["min_interval_overlap"] < policy.min_interval_overlap
        ):
            reasons.append("SPECTRAL_INCOMPATIBLE")
    if policy is None:
        reasons.append("SPECTRAL_POLICY_UNREVIEWED")
    return evidence, tuple(reasons)


@dataclass(frozen=True)
class BackgroundResult:
    image: np.ndarray
    variance: np.ndarray
    usable_mask: np.ndarray
    offset: float
    offset_variance: float
    provenance: dict
    reasons: tuple[str, ...]


def prepare_background(
    image,
    variance,
    zodi,
    flags,
    usable_mask,
    source_free,
    *,
    source_free_reference: str,
    zodi_variance=None,
    uncertainty_reference: str = "",
) -> BackgroundResult:
    """IMAGE-ZODI then constant residual background on supplied source-free pixels.

    All flagged pixels are conservatively excluded. The mean's covariance is
    retained as a rank-one term, not hidden in an independent-pixel variance.
    Source-free pixels must be disjoint from subsequent measurement pixels.
    Missing ZODI uncertainty permits diagnostics only and blocks certification.
    """
    shape = image.shape
    if image.ndim != 2 or any(
        a.shape != shape for a in (variance, zodi, flags, usable_mask, source_free)
    ):
        raise ValueError("INVALID_BACKGROUND_SHAPES")
    if (
        usable_mask.dtype != np.bool_
        or source_free.dtype != np.bool_
        or flags.dtype.kind not in "iu"
        or np.any(flags < 0)
    ):
        raise ValueError("INVALID_BACKGROUND_MASKS")
    good = (
        usable_mask
        & (flags == 0)
        & np.isfinite(image)
        & np.isfinite(zodi)
        & np.isfinite(variance)
        & (variance > 0)
    )
    reasons = []
    total_var = np.array(variance, float, copy=True)
    if zodi_variance is None:
        reasons.append("ZODI_UNCERTAINTY_UNKNOWN")
    else:
        if zodi_variance.shape != shape:
            raise ValueError("INVALID_ZODI_VARIANCE_SHAPE")
        good &= np.isfinite(zodi_variance) & (zodi_variance >= 0)
        total_var += zodi_variance
    if not source_free_reference.strip():
        reasons.append("SOURCE_FREE_REGION_UNVERIFIED")
    if not uncertainty_reference.strip():
        reasons.append("BACKGROUND_UNCERTAINTY_UNREVIEWED")
    bg = good & source_free
    n = int(bg.sum())
    residual = np.asarray(image, float) - zodi
    if n < 2:
        raise ValueError("INSUFFICIENT_SOURCE_FREE_PIXELS")
    offset = float(np.mean(residual[bg]))
    # Empirical scatter includes unmodeled spatial structure; does not certify
    # that a constant model is adequate. That is an explicit review input.
    offset_var = float(max(np.sum(total_var[bg]) / n**2, np.var(residual[bg], ddof=1) / n))
    residual -= offset
    residual[~good] = np.nan
    total_var[~good] = np.nan
    evidence = {
        "method": "IMAGE-ZODI-source-free-constant-mean-v1",
        "source_free_reference": source_free_reference,
        "uncertainty_reference": uncertainty_reference,
        "source_free_sha256": array_digest(source_free),
        "source_free_pixels": n,
        "mask_policy": "exclude-all-nonzero-FLAGS",
        "zodi_sha256": array_digest(zodi),
        "offset": offset,
        "offset_variance": offset_var,
        "covariance": "offset_variance * ones; measurement disjoint from background",
        "limitations": "constant-model adequacy and correlated ZODI errors require review",
    }
    return BackgroundResult(residual, total_var, good, offset, offset_var, evidence, tuple(reasons))


def assess_effective_psfs(
    first,
    second,
    positions,
    *,
    alignment_reference: str,
    coverage_reference: str,
    policy: ScientificPolicy | None,
):
    """Compare spatially sampled ePSFs AFTER the actual alignment operator.

    Native stamps or matching FWHM alone cannot satisfy this API's evidence
    requirements. Stamps share pixel scale, orientation, centering and support.
    No deconvolution or unreviewed matching kernel is automatically applied.
    """
    a, b = np.asarray(first, float), np.asarray(second, float)
    xy = np.asarray(positions, float)
    if (
        a.shape != b.shape
        or a.ndim != 3
        or not a.size
        or xy.shape != (a.shape[0], 2)
        or not np.isfinite(xy).all()
    ):
        raise ValueError("INVALID_SPATIAL_PSF_SAMPLES")
    if (
        not np.isfinite(a).all()
        or not np.isfinite(b).all()
        or np.any(a < 0)
        or np.any(b < 0)
        or np.any(a.sum((1, 2)) <= 0)
        or np.any(b.sum((1, 2)) <= 0)
    ):
        raise ValueError("INVALID_EFFECTIVE_PSF")
    a = a / a.sum((1, 2))[:, None, None]
    b = b / b.sum((1, 2))[:, None, None]
    distances = np.abs(a - b).sum((1, 2))
    reasons = []
    if not alignment_reference.strip() or not coverage_reference.strip():
        reasons.append("EFFECTIVE_PSF_COVERAGE_UNVERIFIED")
    if policy is None:
        reasons.append("PSF_POLICY_UNREVIEWED")
    elif np.max(distances) > policy.max_psf_l1_distance:
        reasons.append("PSF_MATCHING_REQUIRED")
    return {
        "method": "normalized-aligned-spatial-ePSF-L1-v1",
        "positions": xy.tolist(),
        "distances": distances.tolist(),
        "alignment_reference": alignment_reference,
        "coverage_reference": coverage_reference,
        "matching_applied": False,
        "policy": asdict(policy) if policy else None,
        "input_hashes": [array_digest(first), array_digest(second)],
    }, tuple(reasons)


def load_native_epsf_samples(path: Path, detector_positions: np.ndarray):
    """Select spatial zones from the embedded DR1 EPSF table without averaging.

    Coordinates must already be mapped to the original detector. These are
    NATIVE stamps, not post-alignment evidence. Never pick a nearest zone outside
    its declared bounds. Half-open bounds give deterministic shared edges.
    """
    positions = np.asarray(detector_positions, float)
    if (
        positions.ndim != 2
        or positions.shape[1] != 2
        or not positions.size
        or not np.isfinite(positions).all()
    ):
        raise ValueError("INVALID_DETECTOR_PSF_POSITIONS")
    with fits.open(path, memmap=False) as hdus:
        table = hdus["EPSF"].data
        required = {"XCENTER", "YCENTER", "XWIDTH", "YWIDTH", "EPSF"}
        if not required.issubset(table.names):
            raise ValueError("UNSUPPORTED_EPSF_TABLE")
        for key in ("XCENTER", "YCENTER", "XWIDTH", "YWIDTH"):
            if not np.isfinite(table[key]).all():
                raise ValueError("INVALID_EPSF_ZONE_GEOMETRY")
        if np.any(table["XWIDTH"] <= 0) or np.any(table["YWIDTH"] <= 0):
            raise ValueError("INVALID_EPSF_ZONE_GEOMETRY")
        indexes = []
        for x, y in positions:
            inside = (
                (x >= table["XCENTER"] - table["XWIDTH"] / 2)
                & (x < table["XCENTER"] + table["XWIDTH"] / 2)
                & (y >= table["YCENTER"] - table["YWIDTH"] / 2)
                & (y < table["YCENTER"] + table["YWIDTH"] / 2)
            )
            found = np.flatnonzero(inside)
            if len(found) != 1:
                raise ValueError("EPSF_ZONE_MISSING_OR_AMBIGUOUS")
            indexes.append(int(found[0]))
        stamps = np.array(table["EPSF"][indexes], float, copy=True)
    return stamps, {
        "native_zone_indexes": indexes,
        "detector_positions": positions.tolist(),
        "file_sha256": sha256(Path(path).read_bytes()).hexdigest(),
        "post_alignment_verified": False,
    }


@dataclass(frozen=True)
class PairPreparation:
    """Immutable serialized record bound to the exact prepared pair and region.

    A record is not approval merely because it exists. Missing evidence is
    enumerated and prevents the difference gate from using these inputs.
    """

    frame_hashes: tuple[str, str]
    region_hash: str
    evidence_json: str
    reasons: tuple[str, ...]

    def to_dict(self):
        return {**asdict(self), "evidence": json.loads(self.evidence_json)}

    def calibration_signature(self, history):
        """Independent identities checked against cached product bytes by builder."""
        from change_lens.pipeline.calibration import history_calibrations

        if any(r.startswith("CALIBRATION_") for r in self.reasons):
            return None
        products = json.loads(self.evidence_json).get("calibrations", [])
        refs = history_calibrations(history)
        if not refs:
            return None
        signature = []
        for ref in refs:
            matches = [p for p in products if p.get("reference") == asdict(ref)]
            if len(matches) != 1 or not matches[0].get("identity_evidence"):
                return None
            signature.append((ref.role, ref.uuid, matches[0]["sha256"]))
        return tuple(sorted(signature))

    def rejection_reasons(self, first, second):
        reasons = list(self.reasons)
        # Capability checks are enforced here too, not trusted from a stored
        # record's reason list. Deserializing an edited JSON cannot approve it.
        reasons.extend(
            ("ALIGNED_SPECTRAL_RESPONSE_UNVERIFIED", "PAIR_COVARIANCE_MODEL_UNAVAILABLE")
        )
        try:
            if self.frame_hashes != (frame_digest(first), frame_digest(second)):
                reasons.append("PAIR_PREPARATION_INPUT_MISMATCH")
        except (ValueError, TypeError, AttributeError):
            reasons.append("PAIR_PREPARATION_INPUT_MISMATCH")
        return tuple(dict.fromkeys(reasons))


def record_pair_preparation(
    first: AlignedFrame,
    second: AlignedFrame,
    region,
    *,
    products: tuple[VerifiedCalibration, ...] = (),
    spectral=None,
    backgrounds=None,
    psf=None,
    uncertainty_reference: str = "",
    product_paths: dict[str, Path] | None = None,
):
    """Collect evaluated stage evidence, never turn absent evidence into success.

    This initial implementation records diagnostics but deliberately does not
    certify a real difference: full alignment covariance/calibration uncertainty
    and an effective-response mixture evaluator are not yet supported.
    """
    if (
        region.dtype != np.bool_
        or region.shape != first.image.shape
        or region.shape != second.image.shape
        or not region.any()
    ):
        raise ValueError("INVALID_MEASUREMENT_REGION")
    reasons = []
    verified_products = []
    for product in products:
        path = (product_paths or {}).get(product.sha256)
        if path is None:
            reasons.append("CALIBRATION_CACHE_UNVERIFIED")
            continue
        try:
            check_cached_product(product, path)
            verified_products.append(product)
        except (ValueError, OSError, KeyError):
            reasons.append("CALIBRATION_CACHE_UNVERIFIED")
    for frame in (first, second):
        reasons.extend(
            calibration_reasons(
                frame.provenance.get("validation", {}).get("metadata", {}).get("HISTORY"),
                tuple(verified_products),
            )
        )
        if not frame.usable_mask[region].all():
            reasons.append("MEASUREMENT_REGION_MASKED")
    evidence = {
        "calibrations": [p.to_dict() for p in verified_products],
        "measurement_region": {"shape": list(region.shape), "pixels": np.argwhere(region).tolist()},
        "uncertainty_reference": uncertainty_reference,
    }
    for name, stage in (("spectral", spectral), ("psf", psf)):
        if stage is None:
            reasons.append(f"{name.upper()}_EVIDENCE_MISSING")
        else:
            evidence[name], issues = stage
            reasons.extend(issues)
    if spectral is not None and spectral[0].get("region_sha256") != array_digest(region):
        reasons.append("SPECTRAL_REGION_MISMATCH")
    if backgrounds is None or len(backgrounds) != 2:
        reasons.append("BACKGROUND_EVIDENCE_MISSING")
    else:
        evidence["backgrounds"] = [b.provenance for b in backgrounds]
        for b in backgrounds:
            reasons.extend(b.reasons)
    # Explicit capability blockers. A string or externally supplied passed=True
    # must never substitute for an implemented uncertainty/response model.
    reasons.extend(("ALIGNED_SPECTRAL_RESPONSE_UNVERIFIED", "PAIR_COVARIANCE_MODEL_UNAVAILABLE"))
    if not uncertainty_reference.strip():
        reasons.append("PAIR_UNCERTAINTY_UNREVIEWED")
    return PairPreparation(
        (frame_digest(first), frame_digest(second)),
        array_digest(region),
        json.dumps(evidence, sort_keys=True, allow_nan=False),
        tuple(dict.fromkeys(reasons)),
    )


def apply_psf_kernel(
    image,
    variance,
    usable_mask,
    kernel,
    *,
    kernel_reference: str,
    kernel_uncertainty_reference: str,
):
    """Apply an externally justified nonnegative, unit-sum PSF matching kernel.

    Return diagonal variance AND the linear operator needed for covariance:
    Cov(output_i, output_j) = sum_p K(i,p) K(j,p) Var(input_p).
    It is not sufficient to use just the returned diagonal for photometry.
    Kernel uncertainty is not invented; the pair gate still requires a model.
    """
    from scipy.signal import convolve2d

    k = np.asarray(kernel, float)
    if (
        k.ndim != 2
        or not k.size
        or any(n % 2 == 0 for n in k.shape)
        or not np.isfinite(k).all()
        or np.any(k < 0)
        or not np.isclose(k.sum(), 1, atol=1e-12, rtol=0)
    ):
        raise ValueError("INVALID_MATCHING_KERNEL")
    if not kernel_reference.strip() or not kernel_uncertainty_reference.strip():
        raise ValueError("PSF_KERNEL_EVIDENCE_REQUIRED")
    if (
        image.ndim != 2
        or variance.shape != image.shape
        or usable_mask.shape != image.shape
        or usable_mask.dtype != np.bool_
    ):
        raise ValueError("INVALID_MATCHING_ARRAYS")
    good = usable_mask & np.isfinite(image) & np.isfinite(variance) & (variance > 0)
    support = k > 0
    covered = convolve2d(good.astype(int), support.astype(int), mode="same") == support.sum()
    result = convolve2d(np.where(good, image, 0), k, mode="same")
    var = convolve2d(np.where(good, variance, 0), k * k, mode="same")
    result[~covered] = np.nan
    var[~covered] = np.nan
    return (
        result,
        var,
        covered,
        {
            "method": "strict-support-convolution-v1",
            "kernel": k.tolist(),
            "kernel_reference": kernel_reference,
            "kernel_uncertainty_reference": kernel_uncertainty_reference,
            "input_variance_sha256": array_digest(variance),
            "covariance_operator": "K diag(input_variance) K.T",
            "reasons": ["KERNEL_UNCERTAINTY_MODEL_REQUIRED"],
        },
    )
