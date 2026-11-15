"""Read-only real-pair audit; never updates discovery/evidence caches.

Run from the repository root with .venv/Scripts/python.exe.
Optional --output writes a small JSON report to an explicitly selected path.
No synthetic fallback and no use of data/sci_verification.
"""

import argparse
import json
from dataclasses import asdict
from hashlib import sha256
from pathlib import Path

import numpy as np
from astropy.io import fits
from change_lens.fits.validator import validate_fits
from change_lens.pipeline.alignment import reproject_frame
from change_lens.pipeline.calibration import history_calibrations
from change_lens.pipeline.calibration_mapping import verify_parent_cutout
from change_lens.pipeline.difference import compute_difference
from change_lens.pipeline.masks import FlagPolicy, build_quality_masks
from change_lens.pipeline.preparation import record_pair_preparation
from change_lens.pipeline.propagation import (
    build_alignment_operator,
    compare_spectral_mixtures,
    difference_covariance,
    propagate_interval_arrays,
    propagate_noise,
)

FILES = (
    "art_source_fe71283b63d108b56524ee0a.fits",
    "art_source_3c36ee083ab3b739b7a2df29.fits",
)


def audit(root: Path):
    inputs, reports, mappings = [], [], []
    calibration_cache = root / "data/derived/calibration_candidates"
    for name in FILES:
        path = root / "data" / "cached_mefs" / name
        validated = validate_fits(path).require_valid()
        inputs.append(validated)
        with fits.open(path, memmap=False) as hdus:
            header = hdus["IMAGE"].header
            refs = history_calibrations(header.get("HISTORY", ()))
            good = (
                (validated.flags == 0)
                & np.isfinite(validated.image)
                & np.isfinite(hdus["ZODI"].data)
            )
            residual = validated.image - hdus["ZODI"].data
            reports.append(
                {
                    "file": name,
                    "sha256": sha256(path.read_bytes()).hexdigest(),
                    "observation_id": validated.report.observation_id,
                    "date_obs": header.get("DATE-OBS"),
                    "structurally_valid": True,
                    "calver": header.get("CALVER"),
                    "detector": header.get("DETECTOR"),
                    "calibration_references": [asdict(ref) for ref in refs],
                    "zodi_diagnostic": {
                        "method": "IMAGE-ZODI; zero FLAGS only; no residual model fitted",
                        "pixels": int(good.sum()),
                        "median": float(np.median(residual[good])) if good.any() else None,
                        "unit": validated.report.image_unit,
                        "certified": False,
                    },
                    "native_epsf": {
                        "zones": len(hdus["EPSF"].data),
                        "stamp_shape": list(hdus["EPSF"].data["EPSF"].shape[1:]),
                        "aligned_compatibility_verified": False,
                    },
                    "detector_mapping": {
                        "CRPIX1A": header.get("CRPIX1A"),
                        "CRPIX2A": header.get("CRPIX2A"),
                        "status": "UNVERIFIED: require original-image/cutout mapping evidence",
                    },
                }
            )
        obs = validated.report.observation_id
        parent = calibration_cache / f"level2_{obs}D1_spx_l2b-v27-2026-239.fits"
        if parent.exists():
            px, py, mapping = verify_parent_cutout(parent, path)
            reports[-1]["detector_mapping"] = {**mapping, "status": "VERIFIED_EXACT_PARENT_SUBSET"}
            mappings.append((px, py))
        else:
            mappings.append(None)
    policy = FlagPolicy("conservative-zero-flags-v1", "SPHEREx-unreviewed", {})
    frames = [
        reproject_frame(v, build_quality_masks(v, policy), inputs[0].wcs, inputs[0].image.shape)
        for v in inputs
    ]
    region = frames[0].usable_mask & frames[1].usable_mask
    spectral_stage = None
    operators = [
        build_alignment_operator(
            v.wcs,
            v.image.shape,
            inputs[0].wcs,
            inputs[0].image.shape,
            build_quality_masks(v, policy).usable_mask,
        )
        for v in inputs
    ]
    noise = [propagate_noise(op, v.variance) for op, v in zip(operators, inputs, strict=True)]
    indexes = np.flatnonzero(region)
    covariance = (
        difference_covariance(*noise, indexes, shared_modes=())
        if indexes.size
        else np.empty((0, 0))
    )
    propagation = {
        "statistical_covariance_method": "strict-bilinear-operators-with-independent-native-statistical-variance",
        "region_pixels": int(indexes.size),
        "covariance_sha256": sha256(covariance.tobytes()).hexdigest(),
        "max_offdiagonal_covariance": float(np.max(abs(covariance - np.diag(np.diag(covariance)))))
        if covariance.size
        else None,
        "certified": False,
        "missing_uncertainty_inputs": [
            "source-free background model",
            "ZODI model covariance",
            "calibration covariance",
            "effective-PSF/model uncertainty",
        ],
    }
    candidate = calibration_cache / "spectral_wcs_D1_spx_cal-swcs-v5-2026-191.fits"
    if candidate.exists() and all(m is not None for m in mappings) and region.any():
        product_hash = sha256(candidate.read_bytes()).hexdigest()
        with fits.open(candidate, memmap=False) as hdus:
            mixtures = [
                propagate_interval_arrays(
                    np.array(hdus["CWAVE"].data[py, px], float),
                    np.array(hdus["CBAND"].data[py, px], float),
                    op,
                    product_hash,
                    identity_verified=False,
                )
                for (px, py), op in zip(mappings, operators, strict=True)
            ]
        evidence, reasons = compare_spectral_mixtures(*mixtures, region)
        spectral_stage = (evidence, reasons)
        evidence["native_cutout_interval_envelopes_um"] = [
            [
                float(np.min(m.wavelength_um - m.bandwidth_um / 2)),
                float(np.max(m.wavelength_um + m.bandwidth_um / 2)),
            ]
            for m in mixtures
        ]
        propagation["spectral_candidate_diagnostics"] = {
            "evidence": evidence,
            "reasons": reasons,
            "certified": False,
        }
    retrieval_path = root / "scientific/calibration_retrieval.json"
    retrieval = (
        json.loads(retrieval_path.read_text(encoding="utf-8")) if retrieval_path.exists() else None
    )
    record = (
        record_pair_preparation(*frames, region, spectral=spectral_stage) if region.any() else None
    )
    difference = compute_difference(*frames, preparation=record)
    return {
        "pair": "Barnard's Star 2025-09-30 / 2025-10-01",
        "inputs": reports,
        "candidate_region": {
            "pixels": int(region.sum()),
            "definition": "strict aligned zero-FLAGS intersection",
            "scientifically_selected": False,
        },
        "difference_status": difference.status,
        "difference_reasons": list(difference.reason_codes),
        "preparation": record.to_dict() if record else None,
        "propagation_diagnostics": propagation,
        "calibration_retrieval": retrieval,
        "official_product_access": {
            "url": "https://nasa-irsa-spherex.s3.amazonaws.com/",
            "note": "Local audit of DataLink-listed S3 products; product retrieval does not establish UUID identity.",
        },
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = audit(args.root)
    content = json.dumps(report, indent=2, allow_nan=False)
    if args.output:
        args.output.write_text(content + "\n", encoding="utf-8")
    # Keep console compact; optional report contains full per-pixel region.
    print(json.dumps({k: v for k, v in report.items() if k != "preparation"}, indent=2))
