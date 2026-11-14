"""Real SPHEREx archive client (INT-003).

Adapts the DATA workstream's code in ``changelens.data`` (IRSA TAP discovery,
cutout retrieval with checksums and cache, FITS -> PNG previews) to the
backend's ``ArchiveClient`` protocol. The DATA logic is reused as-is; this
module only selects frames, wires directories, and maps errors and labels.

Frame selection, so the player shows a fair "little video":
- Only one (detector, release) group is played. Mixing detectors means mixing
  wavelengths, and mixing releases mixes processing versions. Both look like
  change but are not.
- The group with the most observations is chosen.
- Up to ``max_frames`` epochs are sampled evenly across the time range, so
  every visit is represented without downloading hundreds of cutouts.

Alignment: SPHEREx cutouts come in detector orientation, which differs between
visits (frames can be rotated by ~180 degrees). Every preview is reprojected onto
one shared north-up TAN grid centred on the target, so stars stay still and only
real motion or brightness change remains when the frames are played in sequence.
"""

import logging
import math
from collections import Counter
from pathlib import Path

from changelens.contracts import (
    DiscoveryStatus,
    InvestigationRequest,
    ObservationRecord,
    RetrievalMode,
    TargetRecord,
)
from changelens.data import PreviewError, discover, generate_preview, retrieve
from changelens.data.retrieval import RetrievalError

from change_lens.api.errors import ArchiveUnavailableError
from change_lens.archive.base import DiscoveredEpoch, DiscoveryResult

LOGGER = logging.getLogger(__name__)

_UNAVAILABLE = {DiscoveryStatus.TIMEOUT, DiscoveryStatus.HTTP_5XX}
# SPHEREx pixels are ~6.2 arcsec, so 10 arcmin gives ~100 px previews.
MIN_FOV_ARCMIN = 10.0
MAX_FOV_ARCMIN = 30.0


def _short_band(band: str | None) -> str:
    """'SPHEREx-D2' -> 'D2' (keeps unknown values as-is)."""
    if not band:
        return "UNKNOWN"
    return band.split("-")[-1] if band.upper().startswith("SPHEREX-") else band


def _sample_evenly(items: list, n: int) -> list:
    """Pick up to n items (sorted by .mjd) closest to n evenly spaced times."""
    if len(items) <= n:
        return items
    if n <= 1:
        return items[:1]
    t0, t1 = items[0].mjd, items[-1].mjd
    picked: list = []
    for i in range(n):
        t = t0 + (t1 - t0) * i / (n - 1)
        best = min((o for o in items if o not in picked), key=lambda o: abs(o.mjd - t))
        picked.append(best)
    return sorted(picked, key=lambda o: o.mjd)


def select_frames(
    observations: list[ObservationRecord], max_frames: int
) -> tuple[list[ObservationRecord], list[str]]:
    """Pick one detector+release group and sample it evenly in time."""
    usable = [o for o in observations if o.mjd is not None and o.access_url is not None]
    if not usable:
        return [], []
    # Dedupe by observation_id, keep chronological order.
    unique = {o.observation_id: o for o in sorted(usable, key=lambda o: o.mjd)}
    groups = Counter((o.band, o.release) for o in unique.values())
    (band, release), count = groups.most_common(1)[0]
    group = [o for o in unique.values() if (o.band, o.release) == (band, release)]
    chosen = _sample_evenly(group, max_frames)
    notes = [
        f"DISCOVERED_{len(unique)}_OBSERVATIONS",
        f"PLAYING_{_short_band(band)}_{release}_{len(chosen)}_OF_{count}",
    ]
    if len(groups) > 1:
        notes.append("OTHER_DETECTORS_OR_RELEASES_NOT_MIXED")
    return chosen, notes


SPHEREX_PIXEL_ARCSEC = 6.15


def align_north_up(
    png_path: Path, wcs_header: dict, ra: float, dec: float, fov_arcmin: float, out_path: Path
) -> Path:
    """Reproject a preview onto a shared north-up TAN grid centred on (ra, dec).

    The input PNG rows follow FITS order (row 0 = bottom), matching ``wcs_header``.
    The output PNG is in display order (north up, east left).
    """
    import numpy as np
    from astropy.io.fits import Header
    from astropy.wcs import WCS
    from PIL import Image
    from reproject import reproject_interp

    data = np.asarray(Image.open(png_path), dtype=float)
    src_wcs = WCS(Header(wcs_header)).celestial
    n = max(16, math.ceil(fov_arcmin * 60 / SPHEREX_PIXEL_ARCSEC))
    target = WCS(naxis=2)
    target.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    target.wcs.crval = [ra, dec]
    target.wcs.crpix = [(n + 1) / 2, (n + 1) / 2]
    target.wcs.cdelt = [-SPHEREX_PIXEL_ARCSEC / 3600, SPHEREX_PIXEL_ARCSEC / 3600]
    aligned, _ = reproject_interp((data, src_wcs), target, shape_out=(n, n), order="bilinear")
    pixels = np.nan_to_num(aligned, nan=0.0).clip(0, 255).astype(np.uint8)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(np.flipud(pixels), mode="L").save(out_path)
    return out_path


class IrsaArchiveClient:
    name = "irsa"

    def __init__(self, data_dir: Path, previews_dir: Path, cache_dir: Path, max_frames: int = 8):
        self.query_dir = data_dir / "target_queries"
        self.manifest_dir = data_dir / "manifests"
        self.previews_dir = previews_dir
        self.cache_dir = cache_dir
        self.max_frames = max_frames
        # Discovery is slow (TAP query, often 30-120 s). Cache results per position for
        # the life of the process so repeat queries and pre-warmed demo targets are fast.
        self._discovery_cache: dict[tuple[float, float, float], DiscoveryResult] = {}

    def discover(self, ra: float, dec: float, radius_arcsec: float) -> DiscoveryResult:
        fov_arcmin = min(max(2 * radius_arcsec / 60.0, MIN_FOV_ARCMIN), MAX_FOV_ARCMIN)
        key = (round(ra, 6), round(dec, 6), round(fov_arcmin, 4))
        if key in self._discovery_cache:
            return self._discovery_cache[key]
        request = InvestigationRequest(ra_deg=ra, dec_deg=dec, fov_arcmin=fov_arcmin)
        found = discover(request, artifact_directory=self.query_dir)

        if found.status in _UNAVAILABLE or found.error_code in {
            "ARCHIVE_CONNECTION_ERROR",
            "ARCHIVE_REQUEST_FAILED",
        }:
            raise ArchiveUnavailableError(
                "The NASA/IPAC IRSA archive did not respond. Try again in a minute.",
                {"discovery_status": found.status.value, "http_status": found.http_status},
            )
        if found.status == DiscoveryStatus.HTTP_4XX:
            raise ArchiveUnavailableError(
                "The IRSA archive rejected the query.",
                {"discovery_status": found.status.value, "http_status": found.http_status},
            )

        chosen, notes = select_frames(found.observations, self.max_frames)
        target = TargetRecord(
            target_id="user-query",
            name=f"RA {ra:.5f} Dec {dec:+.5f}",
            ra_deg=ra,
            dec_deg=dec,
            role="USER_QUERY",
        )
        epochs = [self._epoch(obs, target, fov_arcmin) for obs in chosen]
        result = DiscoveryResult(epochs=epochs, warnings=list(found.warnings) + notes)
        # Only cache clean results, so a transient retrieval failure can be retried.
        if not any("RETRIEVAL_FAILED" in e.warnings for e in epochs):
            self._discovery_cache[key] = result
        return result

    def _epoch(self, obs: ObservationRecord, target: TargetRecord, fov_arcmin: float) -> DiscoveredEpoch:
        warnings = list(obs.warnings)
        if obs.release:
            warnings.append(f"RELEASE_{obs.release}")
        origin = "authentic_live"
        preview_path: Path | None = None
        try:
            source = retrieve(obs, cache_directory=self.cache_dir, manifest_directory=self.manifest_dir)
            if source.retrieval_mode == RetrievalMode.CACHE:
                origin = "authentic_cached"
            preview = generate_preview(
                source,
                target,
                fov_arcmin=fov_arcmin,
                cache_directory=self.cache_dir,
                manifest_directory=self.manifest_dir,
                preview_directory=self.previews_dir,
            )
            raw_png = self.previews_dir / preview.preview_filename
            preview_path = align_north_up(
                raw_png,
                preview.wcs_header,
                target.ra_deg,
                target.dec_deg,
                fov_arcmin,
                self.previews_dir / "aligned" / preview.preview_filename,
            )
            warnings += preview.warnings
            if not preview.target_in_footprint:
                warnings.append("OUTSIDE_FOOTPRINT")
        except RetrievalError as exc:
            LOGGER.warning("Retrieval failed for %s: %s", obs.observation_id, exc)
            warnings.append("RETRIEVAL_FAILED")
        except PreviewError as exc:
            LOGGER.warning("Preview failed for %s: %s", obs.observation_id, exc)
            warnings.append("PREVIEW_FAILED")
        except Exception as exc:  # alignment/WCS problems must not kill the whole query
            LOGGER.warning("Alignment failed for %s: %s", obs.observation_id, exc)
            preview_path = None
            warnings.append("ALIGNMENT_FAILED")

        return DiscoveredEpoch(
            epoch_id=obs.observation_id,
            observation_time_utc=obs.observed_at.isoformat().replace("+00:00", "Z")
            if obs.observed_at
            else "",
            mjd=float(obs.mjd or 0.0),
            band_id=_short_band(obs.band),
            data_origin=origin,
            preview_path=preview_path,
            warnings=warnings,
        )
