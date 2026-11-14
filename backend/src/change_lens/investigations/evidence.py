"""Evidence synthesis for an investigation (BE wiring of SCI phase 4: SCI-011/012).

Runs the SCI workstream's code unchanged on the same frames as /movers:
    run_phase2 -> run_phase3                 (shared with movers, run once)
    compute_difference(first, last frame)    (SCI-011, longest baseline)
    synthesize_evidence(phase3, differences) (SCI-012)

BE responsibilities kept out of SCI (per SCI_PHASE4_HANDOFF.md): choosing the
earlier/later pair, turning NumPy arrays/NaN into a PNG artifact and JSON nulls,
and caching. Statuses are reported as SCI produced them; nothing is promoted.
"""

import hashlib
import logging
import math
from collections import Counter
from pathlib import Path

from change_lens.contracts import DifferenceSummary, EvidenceResponse, TrackEvidenceSummary
from change_lens.investigations.movers import (
    CENTROID_RADIUS_PX,
    FLAG_POLICY_VERSION,
    Source,
    run_sci,
    sci_method,
    usable_sources,
)

LOGGER = logging.getLogger(__name__)

MAX_NOTABLE_TRACKS = 50
DIFF_CLIP_SIGMA = 5.0
QUIET_STATUS = "NO_RELIABLE_CHANGE"
EVIDENCE_VERSION = "be-evidence-v1"


def _signature(sources: list[Source]) -> str:
    sig = repr(
        (
            EVIDENCE_VERSION,
            FLAG_POLICY_VERSION,
            CENTROID_RADIUS_PX,
            sorted((s[0], str(s[2])) for s in sources),
        )
    )
    return hashlib.sha256(sig.encode()).hexdigest()[:24]


def _finite_or_none(x) -> float | None:
    if x is None:
        return None
    x = float(x)
    return x if math.isfinite(x) else None


def render_difference_png(normalized, wcs, out_path: Path) -> list[str]:
    """Save D/sqrt(Var) as a north-up PNG: mid-grey = 0, white = brighter, black = fainter.

    Returns warnings (e.g. if north-up reprojection was not possible).
    """
    import numpy as np

    from change_lens.archive.irsa import SPHEREX_PIXEL_ARCSEC, reproject_north_up, save_png

    warnings: list[str] = []
    img = np.asarray(normalized, dtype=float)
    try:
        ny, nx = img.shape
        ra, dec = wcs.celestial.pixel_to_world_values((nx - 1) / 2, (ny - 1) / 2)
        fov = max(nx, ny) * SPHEREX_PIXEL_ARCSEC / 60
        img = reproject_north_up(img, wcs, float(ra), float(dec), fov)
    except Exception as exc:  # keep the SCI grid rather than drop the image
        LOGGER.warning("Difference reprojection failed: %s", exc)
        warnings.append("DIFFERENCE_IMAGE_NOT_NORTH_UP")
    scaled = np.clip(img / DIFF_CLIP_SIGMA, -1.0, 1.0)
    pixels = np.rint(127.5 + scaled * 127.5)
    pixels = np.where(np.isfinite(pixels), pixels, 128).astype(np.uint8)
    save_png(np.flipud(pixels), out_path)
    return warnings


def build_evidence(
    investigation_id: str,
    sources: list[Source],
    derived_dir: Path,
    cache_dir: Path | None = None,
) -> tuple[EvidenceResponse, Path | None]:
    """sources: (epoch_id, mjd, fits_path, detector, release), chronological.

    Returns the response (``difference.image_url`` left empty for the route to
    fill) and the difference PNG path, if one was produced.
    """
    sig = _signature(sources) if sources else None
    png_path = derived_dir / "differences" / f"{sig}.png" if sig else None
    if cache_dir is not None and sig:
        cached = cache_dir / f"{sig}.json"
        if cached.is_file():
            try:
                hit = EvidenceResponse.model_validate_json(cached.read_text("utf-8"))
                if hit.difference is None or hit.difference.status != "AVAILABLE" or png_path.is_file():
                    hit = hit.model_copy(update={"investigation_id": investigation_id})
                    return hit, png_path if png_path and png_path.is_file() else None
            except ValueError:
                pass

    result = _build(investigation_id, sources, png_path)
    if cache_dir is not None and sig and result.status == "COMPLETED":
        try:
            cache_dir.mkdir(parents=True, exist_ok=True)
            (cache_dir / f"{sig}.json").write_text(result.model_dump_json(), "utf-8")
        except OSError as exc:
            LOGGER.warning("Could not persist evidence cache: %s", exc)
    return result, png_path if png_path and png_path.is_file() else None


def _build(investigation_id: str, sources: list[Source], png_path: Path | None) -> EvidenceResponse:
    usable, detector, reason = usable_sources(sources)
    method = {
        **sci_method(),
        "pipeline": "sci-phase2+phase3+phase4",
        "difference_pair": "first and last timeline frame (longest baseline)",
        "difference_png": f"D/sqrt(Var(D)) clipped to +/-{DIFF_CLIP_SIGMA:g}, north-up",
    }
    base = {"investigation_id": investigation_id, "detector": detector, "method": method}
    if reason is not None:
        return EvidenceResponse(status="UNAVAILABLE", frames_used=len(usable), warnings=[reason], **base)

    try:
        from change_lens.pipeline.difference import compute_difference
        from change_lens.pipeline.evidence import synthesize_evidence

        phase2, phase3 = run_sci(usable, detector)
        frames = phase2.alignment.frames
        warnings: list[str] = []
        differences = ()
        if len(frames) >= 2:
            differences = (compute_difference(frames[0], frames[-1]),)
        else:
            warnings.append("DIFFERENCE_NEEDS_TWO_ALIGNED_FRAMES")
        evidence = synthesize_evidence(phase3, differences=differences)
    except Exception as exc:  # report, never 500: the timeline must keep working
        LOGGER.warning("Evidence synthesis failed for %s: %s", investigation_id, exc)
        return EvidenceResponse(
            status="FAILED",
            frames_used=len(usable),
            warnings=[f"SCI_PIPELINE_ERROR:{type(exc).__name__}"],
            **base,
        )

    difference = None
    if evidence.differences:
        d = evidence.differences[0]
        product = d.product
        diff_warnings = list(product.warnings)
        if product.status == "AVAILABLE" and png_path is not None:
            try:
                diff_warnings += render_difference_png(
                    product.normalized_image, frames[0].wcs, png_path
                )
            except Exception as exc:
                LOGGER.warning("Could not render difference PNG: %s", exc)
                diff_warnings.append("DIFFERENCE_PNG_NOT_RENDERED")
        difference = DifferenceSummary(
            status=product.status,
            earlier_epoch_id=usable[0][0],
            later_epoch_id=usable[-1][0],
            earlier_mjd=_finite_or_none(product.earlier_mjd_utc),
            later_mjd=_finite_or_none(product.later_mjd_utc),
            subtraction_order=product.subtraction_order,
            unit=product.unit,
            variance_status=product.variance_status,
            valid_pixel_count=int(d.valid_pixel_count),
            minimum=_finite_or_none(d.minimum),
            maximum=_finite_or_none(d.maximum),
            reason_codes=list(dict.fromkeys([*product.reason_codes, *d.reason_codes])),
            warnings=diff_warnings,
        )

    counts = Counter(s for t in evidence.tracks for s in t.statuses)
    notable = [t for t in evidence.tracks if any(s != QUIET_STATUS for s in t.statuses)]
    if len(notable) > MAX_NOTABLE_TRACKS:
        warnings.append(f"NOTABLE_TRACKS_TRUNCATED:{len(notable)}->{MAX_NOTABLE_TRACKS}")
    releases = {s[4] or "UNKNOWN" for s in usable}
    if len(releases) > 1:
        warnings.append("MIXED_RELEASES")
    return EvidenceResponse(
        status="COMPLETED",
        frames_used=len(usable),
        tracks_total=len(evidence.tracks),
        status_counts=dict(counts),
        notable_tracks=[
            TrackEvidenceSummary(
                track_id=t.track_id,
                statuses=[str(s) for s in t.statuses],
                motion_status=str(t.screened.motion_status),
                brightness_status=str(t.screened.brightness_status),
                reason_codes=list(t.reason_codes),
                limitations=list(t.limitations),
            )
            for t in notable[:MAX_NOTABLE_TRACKS]
        ],
        difference=difference,
        warnings=list(dict.fromkeys([*phase3.warnings, *evidence.reason_codes, *warnings])),
        limitations=list(
            dict.fromkeys(
                [
                    "SCREENING_ONLY_NOT_A_DISCOVERY",
                    "FLAG_POLICY_UNREVIEWED_FOR_AUTHENTIC_SCIENCE",
                    *evidence.limitations,
                ]
            )
        ),
        **base,
    )
