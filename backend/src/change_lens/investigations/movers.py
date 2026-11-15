"""Possible-mover screening for an investigation (BE wiring of SCI phase 2/3).

Runs the SCI workstream's pipeline unchanged:
    run_phase2 (validate, mask, align, detect, centroid)
    -> run_phase3 (associate, measure motion/brightness, controls)
    -> possible_movers (final screened candidates)
on the real FITS files behind one investigation's timeline frames.

BE defaults below were chosen from live SPHEREx DR1 cutouts (WISE 0855 field,
D2 and D6) and should be confirmed by SCI:
- FLAGS bit 21 (value 2097152) is SOURCE, an informational flag set on ~50% of
  pixels. It is retained; every other set bit stays UNKNOWN_POLICY (excluded).
  Source: SPXQuery docs; to be checked against Table 10 of the SPHEREx
  Explanatory Supplement.
- centroid_radius=3 px. SPHEREx PSFs are compact (~6.2"/px); a 6 px radius
  blends neighbours and marks most centroids AMBIGUOUS.
"""

import hashlib
import logging
from collections import Counter, OrderedDict
from pathlib import Path

from change_lens.contracts import MoverCandidate, MoversResponse

LOGGER = logging.getLogger(__name__)

SOURCE_BIT = 1 << 21
CENTROID_RADIUS_PX = 3
FLAG_POLICY_VERSION = "spherex-source-informational-v0"
MIN_FRAMES = 2


Source = tuple[str, float, Path, str | None, str | None]

# Small in-process memo so /movers and /evidence on the same frames run SCI once.
_SCI_MEMO: OrderedDict[tuple, tuple] = OrderedDict()
_SCI_MEMO_SIZE = 4


def clear_sci_memo() -> None:
    _SCI_MEMO.clear()


def sci_method() -> dict:
    return {
        "pipeline": "sci-phase2+phase3",
        "flag_policy": FLAG_POLICY_VERSION,
        "retained_flag_bits": {str(SOURCE_BIT): "SOURCE (informational)"},
        "centroid_radius_px": CENTROID_RADIUS_PX,
    }


def usable_sources(sources: list[Source]) -> tuple[list[Source], str | None, str | None]:
    """Frames with a FITS on disk, their single detector, and why SCI can't run (or None)."""
    usable = [s for s in sources if s[2].is_file()]
    detectors = {s[3] for s in usable}
    detector = next(iter(detectors)) if len(detectors) == 1 else None
    if len(usable) < MIN_FRAMES:
        return usable, detector, (
            "NO_FITS_FOR_SYNTHETIC_OR_MISSING_FRAMES" if not usable else "FEWER_THAN_TWO_FRAMES"
        )
    if len(detectors) > 1:
        return usable, detector, "MIXED_DETECTORS"
    return usable, detector, None


def run_sci(usable: list[Source], detector: str | None) -> tuple:
    """Run SCI phase 2 + 3 unchanged on chronological frames; returns (phase2, phase3)."""
    from change_lens.pipeline.masks import FlagAction, FlagPolicy
    from change_lens.pipeline.phase2 import PlaneIdentity, run_phase2
    from change_lens.pipeline.phase3 import run_phase3

    key = tuple((str(s[2]), s[2].stat().st_mtime_ns, s[4]) for s in usable) + (
        FLAG_POLICY_VERSION,
        CENTROID_RADIUS_PX,
    )
    if key in _SCI_MEMO:
        _SCI_MEMO.move_to_end(key)
        return _SCI_MEMO[key]
    det = detector or "UNKNOWN"
    identities = [
        # spectral_plane is detector-level: per-pixel wavelength varies across a SPHEREx
        # detector (WCS-WAVE), which SCI flags as a limitation rather than a mismatch.
        PlaneIdentity(det, "spherex_l2_spectral_image", det, s[4] or "UNKNOWN")
        for s in usable
    ]
    policy = FlagPolicy(
        FLAG_POLICY_VERSION, "SPHEREX_L2_SPECTRAL_IMAGE", {SOURCE_BIT: FlagAction.RETAIN}
    )
    phase2 = run_phase2(
        [s[2] for s in usable], identities, policy, centroid_radius=CENTROID_RADIUS_PX
    )
    phase3 = run_phase3(phase2)
    _SCI_MEMO[key] = (phase2, phase3)
    while len(_SCI_MEMO) > _SCI_MEMO_SIZE:
        _SCI_MEMO.popitem(last=False)
    return phase2, phase3


def _cache_path(cache_dir: Path, sources: list) -> Path:
    sig = repr(
        (FLAG_POLICY_VERSION, CENTROID_RADIUS_PX, sorted((s[0], Path(s[2]).name) for s in sources))
    )
    return cache_dir / f"{hashlib.sha256(sig.encode()).hexdigest()[:24]}.json"


def screen_movers(
    investigation_id: str,
    sources: list[Source],
    cache_dir: Path | None = None,
) -> MoversResponse:
    """sources: (epoch_id, mjd, fits_path, detector, release), chronological.

    With ``cache_dir``, results are reused for the same set of FITS frames, so a
    new investigation of a pre-warmed target returns instantly.
    """
    if cache_dir is not None and sources:
        cached = _cache_path(cache_dir, sources)
        if cached.is_file():
            try:
                hit = MoversResponse.model_validate_json(cached.read_text("utf-8"))
                return hit.model_copy(update={"investigation_id": investigation_id})
            except ValueError:
                pass
    result = _screen(investigation_id, sources)
    if cache_dir is not None and sources and result.status == "COMPLETED":
        try:
            cache_dir.mkdir(parents=True, exist_ok=True)
            _cache_path(cache_dir, sources).write_text(result.model_dump_json(), "utf-8")
        except OSError as exc:
            LOGGER.warning("Could not persist mover cache: %s", exc)
    return result


def _screen(
    investigation_id: str,
    sources: list[Source],
) -> MoversResponse:
    usable, detector, reason = usable_sources(sources)
    base = {"investigation_id": investigation_id, "detector": detector, "method": sci_method()}
    if reason is not None:
        return MoversResponse(status="UNAVAILABLE", frames_used=len(usable), warnings=[reason], **base)

    try:
        phase2, phase3 = run_sci(usable, detector)
        from change_lens.pipeline.phase3 import possible_movers

        candidates = possible_movers(phase3)
    except Exception as exc:  # report, never 500: the timeline must keep working
        LOGGER.warning("Mover screening failed for %s: %s", investigation_id, exc)
        return MoversResponse(
            status="FAILED",
            frames_used=len(usable),
            warnings=[f"SCI_PIPELINE_ERROR:{type(exc).__name__}"],
            **base,
        )

    releases = {s[4] or "UNKNOWN" for s in usable}
    warnings = list(dict.fromkeys([*phase2.alignment.warnings, *phase3.warnings]))
    if len(releases) > 1:
        warnings.append("MIXED_RELEASES")
    return MoversResponse(
        status="COMPLETED",
        frames_used=len(usable),
        tracks_screened=len(phase3.tracks),
        track_status_counts=dict(Counter(str(t.motion_status) for t in phase3.tracks)),
        candidates=[
            MoverCandidate(
                track_id=c.track_id,
                label=c.label,
                displacement_arcsec=c.displacement_arcsec,
                baseline_days=c.baseline_days,
                uncertainty_arcsec=c.uncertainty_arcsec,
                control_status=c.control_status,
                reason_codes=list(c.reason_codes),
                limitations=list(c.limitations),
            )
            for c in candidates
        ],
        warnings=warnings,
        limitations=[
            "SCREENING_ONLY_NOT_A_DISCOVERY",
            "FLAG_POLICY_UNREVIEWED_FOR_AUTHENTIC_SCIENCE",
            "PARALLAX_NOT_SEPARATELY_MODELED",
        ],
        **base,
    )
