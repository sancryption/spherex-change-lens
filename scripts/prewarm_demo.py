#!/usr/bin/env python3
"""Pre-warm the demo: fetch real SPHEREx frames + run mover screening for the NASA targets.

The first query for a position takes minutes (IRSA TAP discovery, cutout downloads,
previews). This script does that work ahead of time and stores everything on disk
(data/cached_mefs, data/previews, data/discovery_cache, data/mover_cache,
data/evidence_cache, data/derived/differences), so during
the demo every preset target loads instantly, even after a server restart.

Usage (from the repo root, with the backend installed):
    python scripts/prewarm_demo.py                     # all 5 targets
    python scripts/prewarm_demo.py --targets barnards-star wise-0855
    python scripts/prewarm_demo.py --detector D6 --targets wise-0855

It uses the same parameters as the frontend (radius_arcsec=60 -> 10 arcmin FOV,
default detector), so the API hits these caches.
"""

import argparse
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "backend" / "src"))

from change_lens.archive.irsa import IrsaArchiveClient  # noqa: E402
from change_lens.config import get_settings, resolve_data_path  # noqa: E402
from change_lens.investigations.evidence import build_evidence  # noqa: E402
from change_lens.investigations.movers import screen_movers  # noqa: E402
from change_lens.targets import NASA_PRESET_TARGETS  # noqa: E402

FRONTEND_DEFAULT_RADIUS_ARCSEC = 60.0


def main() -> int:
    ids = [t.target_id for t in NASA_PRESET_TARGETS]
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--targets", nargs="+", choices=ids, default=ids)
    parser.add_argument("--detector", choices=[f"D{i}" for i in range(1, 7)], default=None)
    parser.add_argument("--radius", type=float, default=FRONTEND_DEFAULT_RADIUS_ARCSEC)
    parser.add_argument("--skip-movers", action="store_true", help="only fetch frames/previews (no SCI movers/evidence)")
    args = parser.parse_args()

    settings = get_settings()
    data_dir = resolve_data_path(settings.data_dir)
    archive = IrsaArchiveClient(
        data_dir=data_dir,
        previews_dir=resolve_data_path(settings.previews_dir),
        cache_dir=resolve_data_path(settings.cached_mefs_dir),
        max_frames=settings.spherex_max_frames,
    )
    targets = [t for t in NASA_PRESET_TARGETS if t.target_id in args.targets]
    print(f"Pre-warming {len(targets)} target(s), radius={args.radius}\", detector={args.detector or 'default'}")
    print(f"Data dir: {data_dir}\n")

    rows, failed = [], 0
    for t in targets:
        t0 = time.time()
        try:
            result = archive.discover(t.ra, t.dec, args.radius, detector=args.detector)
        except Exception as exc:  # keep going: one bad target must not block the others
            failed += 1
            rows.append((t.name, "-", "-", "-", f"FAILED: {exc}", time.time() - t0))
            print(f"  {t.name}: FAILED ({exc})", flush=True)
            continue
        frames = len(result.epochs)
        with_preview = sum(1 for e in result.epochs if e.preview_path)
        det = next((e.detector for e in result.epochs if e.detector), "-")
        movers = "skipped"
        if not args.skip_movers:
            sources = [
                (e.epoch_id, e.mjd, e.source_fits_path, e.detector, e.release)
                for e in result.epochs
                if e.source_fits_path is not None
            ]
            m = screen_movers("prewarm", sources, cache_dir=data_dir / "mover_cache")
            movers = f"{m.status}: {len(m.candidates)} candidate(s), {m.tracks_screened} tracks"
            ev, _ = build_evidence(
                "prewarm",
                sources,
                derived_dir=resolve_data_path(settings.derived_dir),
                cache_dir=data_dir / "evidence_cache",
            )
            diff = ev.difference.status if ev.difference else "-"
            movers += f"; evidence {ev.status}, diff {diff}"
        elapsed = time.time() - t0
        rows.append((t.name, det, frames, with_preview, movers, elapsed))
        print(f"  {t.name}: {frames} frames ({with_preview} previews, {det}), movers {movers}  [{elapsed:.0f}s]", flush=True)

    print("\nSummary")
    print(f"{'Target':<16} {'Det':<4} {'Frames':>6} {'Prev':>5}  {'Movers':<45} {'Time':>6}")
    for name, det, frames, prev, movers, el in rows:
        print(f"{name:<16} {det:<4} {frames!s:>6} {prev!s:>5}  {movers:<45} {el:>5.0f}s")
    print("\nRe-run any time: already-warm targets return instantly.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
