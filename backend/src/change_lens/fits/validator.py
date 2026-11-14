"""SCI-local FITS validation. Arrays are owned copies; no open file escapes.

Default policy requires IMAGE/VARIANCE/FLAGS and surface-brightness units.
Custom products may supply extension names and equivalent required units.
Reports are local to SCI pending INT-001 alignment.
"""

from dataclasses import dataclass
from pathlib import Path

import numpy as np
from astropy import units as u
from astropy.io import fits
from astropy.wcs import WCS
from pydantic import BaseModel, Field


def _header_value(value: object) -> object:
    """Normalize FITS scalar values explicitly, never stringify unknown objects."""
    if isinstance(value, fits.card.Undefined):
        return None
    if isinstance(value, np.generic):
        return _header_value(value.item())
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not np.isfinite(value):
            return {
                "type": "nonfinite_float",
                "value": "nan" if np.isnan(value) else ("inf" if value > 0 else "-inf"),
            }
        return value
    if isinstance(value, complex):
        return {
            "type": "complex",
            "real": _header_value(value.real),
            "imag": _header_value(value.imag),
        }
    raise TypeError(f"Unsupported FITS header value: {type(value).__name__}")


def _header_metadata(header: fits.Header, warnings: list[str], context: str) -> dict:
    """Read individual cards to preserve ordered commentary and repeated keywords.

    HISTORY/COMMENT/blank cards are always lists. Other duplicate keywords also
    become lists. Unsupported values are omitted with a visible warning; this
    metadata conversion does not change scientific acceptance criteria.
    """
    grouped: dict[str, list] = {}
    for card in header.cards:
        try:
            value = _header_value(card.value)
        except TypeError:
            warnings.append(f"UNSUPPORTED_HEADER_VALUE:{context}:{card.keyword}")
            continue
        grouped.setdefault(card.keyword, []).append(value)
    return {
        key: values if key in ("HISTORY", "COMMENT", "") or len(values) > 1 else values[0]
        for key, values in grouped.items()
    }


@dataclass(frozen=True)
class ProductPolicy:
    version: str = "sci-structural-v1"
    image: str = "IMAGE"
    variance: str = "VARIANCE"
    flags: str = "FLAGS"
    image_unit: str = "MJy/sr"


class FitsValidationReport(BaseModel):
    """Serializable public structural report; errors/warnings are stable reason codes."""

    passed: bool = False
    observation_id: str | None = None
    required_extensions: dict[str, str] = Field(default_factory=dict)
    image_shape: tuple[int, int] | None = None
    image_unit: str | None = None
    has_spatial_wcs: bool = False
    has_wcs_wave: bool = False
    has_variance: bool = False
    has_flags: bool = False
    finite_fraction: float | None = None
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    policy_version: str
    extensions: dict[str, dict] = Field(default_factory=dict)
    metadata: dict = Field(default_factory=dict)
    wcs_summary: dict = Field(default_factory=dict)


@dataclass
class ValidationResult:
    report: FitsValidationReport
    image: np.ndarray | None = None
    variance: np.ndarray | None = None
    flags: np.ndarray | None = None
    wcs: WCS | None = None

    def require_valid(self) -> "ValidationResult":
        if not self.report.passed:
            raise ValueError("INVALID_PRODUCT: " + ",".join(self.report.errors))
        return self


def validate_fits(path: str | Path, policy: ProductPolicy = ProductPolicy()) -> ValidationResult:
    """Inspect read-only; invalid results never expose scientific arrays.

    Image/variance copies normalize to float64 in their original units; FLAGS
    retains its integer dtype and values. Unit equivalence does not rescale data.
    """
    report = FitsValidationReport(policy_version=policy.version)
    arrays = {}
    wcs = None
    try:
        with fits.open(path, mode="readonly", memmap=False) as hdus:
            hdus.verify("exception")
            size = Path(path).stat().st_size
            for hdu in hdus:
                info = hdu.fileinfo()
                if info and info["datLoc"] + info["datSpan"] > size:
                    raise ValueError("truncated FITS")
            for role, name in (
                ("IMAGE", policy.image),
                ("VARIANCE", policy.variance),
                ("FLAGS", policy.flags),
            ):
                matches = [h for h in hdus if h.name.upper() == name.upper()]
                report.required_extensions[role] = name
                if len(matches) != 1:
                    report.errors.append(f"MISSING_OR_DUPLICATE_EXTENSION:{role}")
                    continue
                hdu = matches[0]
                data = hdu.data
                if data is None or data.ndim != 2 or not data.size:
                    report.errors.append(f"INVALID_ARRAY_SHAPE:{role}")
                    continue
                if data.dtype.kind not in ("iu" if role == "FLAGS" else "iuf"):
                    report.errors.append(f"UNSUPPORTED_DTYPE:{role}")
                    continue
                if role == "FLAGS" and np.any(data < 0):
                    report.errors.append("NEGATIVE_FLAGS")
                    continue
                arrays[role] = np.array(
                    data, dtype=None if role == "FLAGS" else np.float64, copy=True
                )
                report.extensions[role] = {
                    "shape": list(data.shape),
                    "original_dtype": str(data.dtype),
                    "normalized_dtype": str(arrays[role].dtype),
                    "unit": hdu.header.get("BUNIT"),
                    "finite_fraction": float(np.isfinite(data).mean()),
                }
                if role != "FLAGS":
                    try:
                        unit = u.Unit(hdu.header["BUNIT"])
                        expected = u.Unit(policy.image_unit) ** (2 if role == "VARIANCE" else 1)
                        if not unit.is_equivalent(expected):
                            raise ValueError("incompatible unit")
                        if role == "VARIANCE" and "IMAGE" in arrays:
                            if unit != u.Unit(hdus[policy.image].header["BUNIT"]) ** 2:
                                raise ValueError("variance scale differs from image squared")
                    except (KeyError, ValueError):
                        report.errors.append(f"INVALID_REQUIRED_UNITS:{role}")
            report.has_flags = "FLAGS" in arrays
            report.has_variance = "VARIANCE" in arrays
            if "IMAGE" in arrays:
                header = hdus[policy.image].header
                report.image_shape = arrays["IMAGE"].shape
                report.image_unit = header.get("BUNIT")
                report.finite_fraction = float(np.isfinite(arrays["IMAGE"]).mean())
                if report.finite_fraction < 1:
                    report.warnings.append("NONFINITE_IMAGE_PIXELS")
                if any(a.shape != arrays["IMAGE"].shape for a in arrays.values()):
                    report.errors.append("INCOMPATIBLE_ARRAY_SHAPES")
                try:
                    if not all(
                        k in header
                        for k in ("CRPIX1", "CRPIX2", "CRVAL1", "CRVAL2", "CTYPE1", "CTYPE2")
                    ):
                        raise ValueError("missing WCS metadata")
                    if not any(k.startswith(("CD1_", "PC1_", "CDELT")) for k in header):
                        raise ValueError("missing transform")
                    wcs = WCS(header).celestial
                    scale = wcs.pixel_scale_matrix
                    if (
                        not wcs.has_celestial
                        or scale.shape != (2, 2)
                        or not np.isfinite(scale).all()
                        or abs(np.linalg.det(scale)) == 0
                    ):
                        raise ValueError("invalid transform")
                    points = np.array(
                        [
                            [0.0, 0.0],
                            [arrays["IMAGE"].shape[1] - 1.0, arrays["IMAGE"].shape[0] - 1.0],
                        ]
                    )
                    sky = wcs.all_pix2world(points, 0)
                    if not np.isfinite(sky).all() or not np.allclose(
                        wcs.all_world2pix(sky, 0), points, atol=1e-4
                    ):
                        raise ValueError("invalid WCS roundtrip")
                    report.has_spatial_wcs = True
                    report.wcs_summary = {
                        "crpix": wcs.wcs.crpix.tolist(),
                        "crval": wcs.wcs.crval.tolist(),
                        "ctype": list(wcs.wcs.ctype),
                        "pixel_scale_matrix": scale.tolist(),
                    }
                except Exception:
                    report.errors.append("INVALID_WCS")
                for key in (
                    "OBSID",
                    "DATE-OBS",
                    "MJD-OBS",
                    "BAND",
                    "RELEASE",
                    "PRODTYPE",
                    "CALVER",
                    "SYNTHET",
                    "HISTORY",
                ):
                    value = header.get(key, hdus[0].header.get(key))
                    if value is not None:
                        report.metadata[key] = (
                            list(value) if key == "HISTORY" else str(_header_value(value))
                        )
                    else:
                        report.warnings.append(f"MISSING_METADATA:{key}")
                report.observation_id = report.metadata.get("OBSID")
            for name in ("PSF", "ZODI", "WCS-WAVE"):
                if name not in hdus:
                    report.warnings.append(f"MISSING_OPTIONAL:{name}")
                else:
                    hdu = hdus[name]
                    report.extensions[name] = {
                        "shape": list(hdu.data.shape) if hdu.data is not None else None,
                        "header": _header_metadata(hdu.header, report.warnings, name),
                    }
            report.has_wcs_wave = "WCS-WAVE" in hdus
    except FileNotFoundError:
        report.errors.append("FILE_NOT_FOUND")
    except Exception:
        report.errors.append("MALFORMED_FITS")
    report.passed = not report.errors
    if not report.passed:
        return ValidationResult(report)
    return ValidationResult(report, arrays["IMAGE"], arrays["VARIANCE"], arrays["FLAGS"], wcs)
