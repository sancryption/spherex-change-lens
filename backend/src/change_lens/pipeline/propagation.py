"""Explicit linear response and uncertainty propagation on the SCI alignment grid.

The same nonzero bilinear contributors determine image, spectral mixtures, and
covariance. No interpolation of variances as intensities, no renormalized holes,
and no conversion of CWAVE/CBAND into invented transmission curves.
"""

from dataclasses import dataclass

import numpy as np
from astropy.wcs.utils import pixel_to_pixel
from scipy import sparse

from change_lens.pipeline.alignment import celestial_grid
from change_lens.pipeline.preparation import array_digest


@dataclass(frozen=True)
class AlignmentOperator:
    matrix: sparse.csr_matrix
    input_shape: tuple[int, int]
    output_shape: tuple[int, int]
    usable_mask: np.ndarray
    provenance: dict

    def apply(self, values):
        if values.shape != self.input_shape:
            raise ValueError("OPERATOR_INPUT_SHAPE_MISMATCH")
        active = np.asarray(self.matrix.getnnz(axis=0)).ravel() > 0
        if not np.isfinite(values.ravel()[active]).all():
            raise ValueError("NONFINITE_OPERATOR_INPUT")
        result = np.asarray(self.matrix @ np.where(active, values.ravel(), 0)).reshape(
            self.output_shape
        )
        result[~self.usable_mask] = np.nan
        return result


def build_alignment_operator(source_wcs, input_shape, target_wcs, output_shape, usable_mask):
    """Match SCI-003's integer snapping and strict bilinear support."""
    source = celestial_grid(source_wcs, input_shape)
    target = celestial_grid(target_wcs, output_shape)
    if usable_mask.shape != input_shape or usable_mask.dtype != np.bool_:
        raise ValueError("INVALID_OPERATOR_MASK")
    yy, xx = np.indices(output_shape, dtype=float)
    x, y = pixel_to_pixel(target, source, xx, yy)
    finite = np.isfinite(x) & np.isfinite(y)
    finite &= (x >= -1) & (x <= input_shape[1]) & (y >= -1) & (y <= input_shape[0])
    x, y = np.where(finite, x, -2), np.where(finite, y, -2)
    x = np.where(abs(x - np.rint(x)) < 1e-7, np.rint(x), x)
    y = np.where(abs(y - np.rint(y)) < 1e-7, np.rint(y), y)
    x0, y0 = np.floor(x).astype(int), np.floor(y).astype(int)
    dx, dy = x - x0, y - y0
    rows, cols, weights = [], [], []
    valid = finite.copy()
    indexes = np.arange(np.prod(output_shape)).reshape(output_shape)
    for ox, oy, w in (
        (0, 0, (1 - dx) * (1 - dy)),
        (1, 0, dx * (1 - dy)),
        (0, 1, (1 - dx) * dy),
        (1, 1, dx * dy),
    ):
        xi, yi = x0 + ox, y0 + oy
        inside = finite & (xi >= 0) & (xi < input_shape[1]) & (yi >= 0) & (yi < input_shape[0])
        xi, yi = np.clip(xi, 0, input_shape[1] - 1), np.clip(yi, 0, input_shape[0] - 1)
        active = w > 0
        good = inside & usable_mask[yi, xi]
        valid &= ~active | good
        selected = active & good
        rows.extend(indexes[selected])
        cols.extend((yi * input_shape[1] + xi)[selected])
        weights.extend(w[selected])
    matrix = sparse.csr_matrix(
        (weights, (rows, cols)), shape=(int(np.prod(output_shape)), int(np.prod(input_shape)))
    )
    matrix = sparse.diags(valid.ravel().astype(float)) @ matrix
    matrix.eliminate_zeros()
    return AlignmentOperator(
        matrix.tocsr(),
        input_shape,
        output_shape,
        valid,
        {
            "method": "bilinear-strict-v1",
            "source_wcs": source.to_header(relax=True).tostring(),
            "target_wcs": target.to_header(relax=True).tostring(),
            "input_mask_sha256": array_digest(usable_mask),
            "weights_sha256": array_digest(matrix.data),
            "indices_sha256": array_digest(matrix.indices),
            "indptr_sha256": array_digest(matrix.indptr),
        },
    )


@dataclass(frozen=True)
class SpectralMixture:
    """Native intervals with sparse aligned weights; not a top-hat response model."""

    operator: AlignmentOperator
    wavelength_um: np.ndarray
    bandwidth_um: np.ndarray
    calibration_sha256: str
    calibration_identity_verified: bool = False

    def contributors(self, output_index: int):
        row = self.operator.matrix.getrow(output_index)
        return {
            "native_indices": row.indices.copy(),
            "weights": row.data.copy(),
            "wavelength_um": self.wavelength_um.ravel()[row.indices],
            "bandwidth_um": self.bandwidth_um.ravel()[row.indices],
        }


def propagate_spectral_map(spectral_map, operator: AlignmentOperator):
    from change_lens.pipeline.calibration import VerifiedCalibration

    return propagate_interval_arrays(
        spectral_map.wavelength_um,
        spectral_map.bandwidth_um,
        operator,
        spectral_map.calibration.sha256,
        identity_verified=isinstance(spectral_map.calibration, VerifiedCalibration),
    )


def propagate_interval_arrays(wave, band, operator, product_sha256, *, identity_verified=False):
    """Unverified candidate arrays can be diagnosed but cannot certify a pair."""
    if wave.shape != operator.input_shape or band.shape != operator.input_shape:
        raise ValueError("SPECTRAL_OPERATOR_SHAPE_MISMATCH")
    active = np.asarray(operator.matrix.getnnz(axis=0)).ravel() > 0
    for value in (wave, band):
        if not (np.isfinite(value.ravel()[active]) & (value.ravel()[active] > 0)).all():
            raise ValueError("INVALID_SPECTRAL_CONTRIBUTOR")
    return SpectralMixture(operator, wave.copy(), band.copy(), product_sha256, identity_verified)


def compare_spectral_mixtures(first: SpectralMixture, second: SpectralMixture, region, policy=None):
    """Conservative all-contributor interval checks over each measured output pixel.

    Retains weighted moments for diagnostics, but a small mean difference cannot
    hide incompatible contributors. Certification still needs a justified policy
    for the intended SED/measurement, not just agreement of interval moments.
    """
    shape = first.operator.output_shape
    if (
        region.dtype != np.bool_
        or region.shape != shape
        or second.operator.output_shape != shape
        or not region.any()
    ):
        raise ValueError("INVALID_MEASUREMENT_REGION")
    if first.operator.provenance["target_wcs"] != second.operator.provenance["target_wcs"]:
        raise ValueError("SPECTRAL_OUTPUT_GRID_MISMATCH")
    if not (first.operator.usable_mask & second.operator.usable_mask)[region].all():
        return {}, ("SPECTRAL_REGION_UNSUPPORTED",)
    maximum, minimum, mean_max = 0.0, 1.0, 0.0
    disjoint_pixels = 0
    for index in np.flatnonzero(region):
        a, b = first.contributors(index), second.contributors(index)
        ac, bc = a["wavelength_um"][:, None], b["wavelength_um"][None, :]
        aw, bw = a["bandwidth_um"][:, None], b["bandwidth_um"][None, :]
        overlap = np.maximum(
            0, np.minimum(ac + aw / 2, bc + bw / 2) - np.maximum(ac - aw / 2, bc - bw / 2)
        )
        if not np.any(overlap > 0):
            disjoint_pixels += 1
        maximum = max(maximum, float(np.max(abs(ac - bc))))
        minimum = min(minimum, float(np.min(overlap / (aw + bw - overlap))))
        mean_max = max(
            mean_max,
            float(abs(a["weights"] @ a["wavelength_um"] - b["weights"] @ b["wavelength_um"])),
        )
    reasons = []
    if disjoint_pixels:
        reasons.append("SPECTRAL_BANDWIDTH_INTERVALS_DISJOINT")
    if not first.calibration_identity_verified or not second.calibration_identity_verified:
        reasons.append("SPECTRAL_CALIBRATION_UNVERIFIED")
    if policy is None:
        reasons.append("SPECTRAL_POLICY_UNREVIEWED")
    elif maximum > policy.max_wavelength_delta_um or minimum < policy.min_interval_overlap:
        reasons.append("SPECTRAL_INCOMPATIBLE")
    return {
        "method": "all-bilinear-contributor-intervals-v1",
        "region_sha256": array_digest(region),
        "region_pixels": int(region.sum()),
        "max_contributor_delta_um": maximum,
        "min_contributor_interval_overlap": minimum,
        "max_weighted_mean_delta_um": mean_max,
        "disjoint_interval_pixels": disjoint_pixels,
        "operator_provenance": [first.operator.provenance, second.operator.provenance],
        "calibration_hashes": [first.calibration_sha256, second.calibration_sha256],
        "limitation": "Full transmission shapes and SED-dependent color terms are not supplied by CWAVE/CBAND",
    }, tuple(reasons)


@dataclass(frozen=True)
class PropagatedNoise:
    """Covariance of L x where L=A-(A1)b.T, plus named nuisance modes.

    b contains background-mean weights; using this operator includes covariance
    between the estimated background and science pixels, even when they overlap.
    Modes are native one-sigma perturbations, not invented uncertainty estimates.
    """

    operator: AlignmentOperator
    native_variance: np.ndarray
    background_weights: np.ndarray
    nuisance_modes: dict[str, np.ndarray]
    review_reference: str

    def rows(self, indexes):
        rows = self.operator.matrix[np.asarray(indexes)].toarray()
        return rows - rows.sum(axis=1)[:, None] * self.background_weights[None, :]

    def covariance(self, indexes):
        indexes = np.asarray(indexes)
        if (
            indexes.ndim != 1
            or indexes.dtype.kind not in "iu"
            or np.any(indexes < 0)
            or np.any(indexes >= self.operator.matrix.shape[0])
        ):
            raise ValueError("INVALID_COVARIANCE_REGION")
        if not self.operator.usable_mask.ravel()[indexes].all():
            raise ValueError("COVARIANCE_REGION_UNSUPPORTED")
        rows = self.rows(indexes)
        result = (rows * self.native_variance) @ rows.T
        for mode in self.nuisance_modes.values():
            v = rows @ mode
            result += np.outer(v, v)
        return result

    def diagonal(self):
        a = self.operator.matrix
        b, v = self.background_weights, self.native_variance
        sums = np.asarray(a.sum(axis=1)).ravel()
        result = (
            np.asarray(a.power(2) @ v).ravel()
            - 2 * sums * (a @ (v * b))
            + sums * sums * np.sum(v * b * b)
        )
        for mode in self.nuisance_modes.values():
            result += (a @ mode - sums * (b @ mode)) ** 2
        result = np.asarray(result).reshape(self.operator.output_shape)
        result[~self.operator.usable_mask] = np.nan
        return result


def propagate_noise(
    operator, native_variance, *, background_weights=None, nuisance_modes=None, review_reference=""
):
    if native_variance.shape != operator.input_shape:
        raise ValueError("NOISE_OPERATOR_SHAPE_MISMATCH")
    n = operator.matrix.shape[1]
    b = np.zeros(n) if background_weights is None else np.asarray(background_weights, float).ravel()
    if (
        b.shape != (n,)
        or not np.isfinite(b).all()
        or np.any(b < 0)
        or (np.any(b) and not np.isclose(b.sum(), 1, rtol=0, atol=1e-12))
    ):
        raise ValueError("INVALID_BACKGROUND_WEIGHTS")
    active = (np.asarray(operator.matrix.getnnz(axis=0)).ravel() > 0) | (b > 0)
    v = native_variance.ravel()
    if not (np.isfinite(v[active]) & (v[active] > 0)).all():
        raise ValueError("INVALID_NATIVE_NOISE")
    modes = {}
    for name, mode in (nuisance_modes or {}).items():
        if (
            not name.strip()
            or mode.shape != operator.input_shape
            or not np.isfinite(mode.ravel()[active]).all()
        ):
            raise ValueError("INVALID_NUISANCE_MODE")
        modes[name] = np.where(active, mode.ravel(), 0)
    return PropagatedNoise(operator, np.where(active, v, 0), b.copy(), modes, review_reference)


def difference_covariance(
    first: PropagatedNoise, second: PropagatedNoise, indexes, *, shared_modes: tuple[str, ...]
):
    """Independent statistical epochs plus explicitly identified shared modes.

    Shared named modes use (L2 u2-L1 u1)(...)T, including cross-epoch terms.
    Distinct names represent independent modes. Caller must specify sharing;
    matching calibration UUIDs alone never supplies uncertainty amplitudes.
    """
    if (
        first.operator.output_shape != second.operator.output_shape
        or first.operator.provenance["target_wcs"] != second.operator.provenance["target_wcs"]
    ):
        raise ValueError("COVARIANCE_OUTPUT_GRID_MISMATCH")
    result = first.covariance(indexes) + second.covariance(indexes)
    if len(set(shared_modes)) != len(shared_modes):
        raise ValueError("DUPLICATE_SHARED_MODE")
    a, b = first.rows(indexes), second.rows(indexes)
    for name in shared_modes:
        if name not in first.nuisance_modes or name not in second.nuisance_modes:
            raise ValueError("SHARED_UNCERTAINTY_MODE_MISSING")
        u, v = a @ first.nuisance_modes[name], b @ second.nuisance_modes[name]
        result -= np.outer(u, v) + np.outer(v, u)
    return result
