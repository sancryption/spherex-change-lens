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

Rendering: previews are made from the float FITS cutout (not an 8-bit PNG):
reproject north-up -> subtract a smooth background (removes stray-light
gradients) -> stretch in units of each frame's own noise, so brightness is
comparable between frames.
"""

import hashlib
import json
import logging
import math
from collections import Counter
from pathlib import Path, PurePosixPath, PureWindowsPath

from changelens.contracts import (
    DiscoveryStatus,
    InvestigationRequest,
    ObservationRecord,
    RetrievalMode,
    TargetRecord,
)
from changelens.data import PreviewError, discover, generate_preview, retrieve
from changelens.data.previews import _load_image_cutout, _load_source_manifest
from changelens.data.retrieval import RetrievalError

from change_lens.api.errors import ArchiveUnavailableError
from change_lens.archive.base import DiscoveredEpoch, DiscoveryResult

LOGGER = logging.getLogger(__name__)

_UNAVAILABLE = {DiscoveryStatus.TIMEOUT, DiscoveryStatus.HTTP_5XX}
# SPHEREx pixels are ~6.2 arcsec, so 10 arcmin gives ~100 px previews.
MIN_FOV_ARCMIN = 10.0
MAX_FOV_ARCMIN = 30.0

# Nominal SPHEREx detector bandpasses (microns).
DETECTOR_WAVELENGTH_UM = {
    "D1": [0.75, 1.09],
    "D2": [1.10, 1.62],
    "D3": [1.63, 2.41],
    "D4": [2.42, 3.82],
    "D5": [3.83, 4.41],
    "D6": [4.42, 5.00],
}


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
    observations: list[ObservationRecord], max_frames: int, detector: str | None = None
) -> tuple[list[ObservationRecord], list[str]]:
    """Pick one detector+release group and sample it evenly in time."""
    usable = [o for o in observations if o.mjd is not None and o.access_url is not None]
    if detector:
        usable = [o for o in usable if _short_band(o.band) == detector]
        if not usable:
            return [], [f"NO_OBSERVATIONS_FOR_{detector}"]
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


def reproject_north_up(data, wcs, ra: float, dec: float, fov_arcmin: float):
    """Reproject a float image onto a shared north-up TAN grid centred on (ra, dec).

    Returns a float array in FITS row order (row 0 = south), NaN outside the source.
    """
    import numpy as np
    from astropy.wcs import WCS
    from reproject import reproject_interp

    n = max(16, math.ceil(fov_arcmin * 60 / SPHEREX_PIXEL_ARCSEC))
    target = WCS(naxis=2)
    target.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    target.wcs.crval = [ra, dec]
    target.wcs.crpix = [(n + 1) / 2, (n + 1) / 2]
    target.wcs.cdelt = [-SPHEREX_PIXEL_ARCSEC / 3600, SPHEREX_PIXEL_ARCSEC / 3600]
    aligned, _ = reproject_interp(
        (np.asarray(data, dtype=float), wcs.celestial), target, shape_out=(n, n), order="bilinear"
    )
    return aligned


def render_display(aligned):
    """Background-subtract and noise-normalise a float image; return uint8 in display order."""
    import numpy as np
    from scipy.ndimage import median_filter

    finite = np.isfinite(aligned)
    if not finite.any():
        raise ValueError("no finite pixels after alignment")
    filled = np.where(finite, aligned, np.nanmedian(aligned))
    # Smooth background: large median filter ignores stars, follows stray-light gradients.
    size = max(9, min(aligned.shape) // 5) | 1
    background = median_filter(filled, size=size, mode="nearest")
    residual = filled - background
    vals = residual[finite]
    sigma = 1.4826 * np.median(np.abs(vals - np.median(vals)))
    if not np.isfinite(sigma) or sigma <= 0:
        sigma = float(np.std(vals)) or 1.0
    # Same stretch in noise units for every frame: -2 sigma -> black, +60 sigma -> white.
    scaled = np.clip((residual + 2 * sigma) / (62 * sigma), 0.0, 1.0)
    stretched = np.arcsinh(10.0 * scaled) / np.arcsinh(10.0)
    pixels = np.rint(stretched * 255).astype(np.uint8)
    pixels[~finite] = 0
    return np.flipud(pixels)  # north up


def save_png(pixels, out_path: Path) -> Path:
    from PIL import Image

    out_path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(pixels, mode="L").save(out_path)
    return out_path


def _portable(path: Path | None, data_dir: Path) -> str | None:
    """Store paths under data_dir relative (posix), so a copied data/ folder works elsewhere."""
    if path is None:
        return None
    try:
        return Path(path).resolve().relative_to(data_dir.resolve()).as_posix()
    except ValueError:
        return str(path)


def _relocate(raw: str | None, data_dir: Path) -> Path | None:
    """Resolve a stored path; remap absolute paths from another machine into data_dir."""
    if not raw:
        return None
    pure = PureWindowsPath(raw) if "\\" in raw or ":" in raw[1:3] else PurePosixPath(raw)
    if not pure.is_absolute():
        return data_dir / Path(*pure.parts)
    if Path(raw).is_file():
        return Path(raw)
    # e.g. C:\Users\x\repo\data\previews\a.png -> <data_dir>/previews/a.png
    parts = pure.parts
    for i in range(len(parts) - 1, -1, -1):
        if parts[i] == data_dir.name:
            return data_dir / Path(*parts[i + 1 :])
    return Path(raw)


def _epoch_to_json(e: DiscoveredEpoch, data_dir: Path) -> dict:
    d = dict(vars(e))
    for k in ("preview_path", "source_fits_path"):
        d[k] = _portable(d[k], data_dir)
    return d


def _epoch_from_json(d: dict, data_dir: Path) -> DiscoveredEpoch:
    d = dict(d)
    for k in ("preview_path", "source_fits_path"):
        d[k] = _relocate(d.get(k), data_dir)
    return DiscoveredEpoch(**d)


class IrsaArchiveClient:
    name = "irsa"

    def __init__(self, data_dir: Path, previews_dir: Path, cache_dir: Path, max_frames: int = 8):
        # Runtime TAP query/response artifacts go to an ignored folder; data/target_queries
        # holds DATA's committed evidence and must not collect every live query.
        self.query_dir = data_dir / "discovery_cache" / "queries"
        self.manifest_dir = data_dir / "manifests"
        self.previews_dir = previews_dir
        self.cache_dir = cache_dir
        self.max_frames = max_frames
        # Discovery is slow (TAP query, often 30-120 s). Cache results per position for
        # the life of the process so repeat queries and pre-warmed demo targets are fast.
        self._discovery_cache: dict[tuple, DiscoveryResult] = {}
        # Also persisted to disk so a server restart (or `make prewarm`) keeps demo targets warm.
        self.data_dir = data_dir
        self.discovery_cache_dir = data_dir / "discovery_cache"

    def discover(
        self, ra: float, dec: float, radius_arcsec: float, detector: str | None = None
    ) -> DiscoveryResult:
        fov_arcmin = min(max(2 * radius_arcsec / 60.0, MIN_FOV_ARCMIN), MAX_FOV_ARCMIN)
        key = (round(ra, 6), round(dec, 6), round(fov_arcmin, 4), detector)
        if key in self._discovery_cache:
            return self._discovery_cache[key]
        on_disk = self._load_cached(key)
        if on_disk is not None:
            self._discovery_cache[key] = on_disk
            return on_disk
        # Download ~1.42x wider (sqrt 2) so rotated frames still fill the square after alignment.
        request = InvestigationRequest(ra_deg=ra, dec_deg=dec, fov_arcmin=min(fov_arcmin * 1.42, 300))
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

        chosen, notes = select_frames(found.observations, self.max_frames, detector)
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
            self._store_cached(key, result)
        return result

    def _cache_file(self, key: tuple) -> Path:
        digest = hashlib.sha256(repr(key).encode()).hexdigest()[:24]
        return self.discovery_cache_dir / f"{digest}.json"

    def _load_cached(self, key: tuple) -> DiscoveryResult | None:
        path = self._cache_file(key)
        if not path.is_file():
            return None
        try:
            data = json.loads(path.read_text("utf-8"))
            epochs = [_epoch_from_json(e, self.data_dir) for e in data["epochs"]]
        except (OSError, ValueError, KeyError, TypeError):
            return None
        # Stale if any preview or FITS it points to has been deleted.
        for e in epochs:
            for p in (e.preview_path, e.source_fits_path):
                if p is not None and not p.is_file():
                    return None
        return DiscoveryResult(epochs=epochs, warnings=list(data.get("warnings", [])))

    def _store_cached(self, key: tuple, result: DiscoveryResult) -> None:
        try:
            self.discovery_cache_dir.mkdir(parents=True, exist_ok=True)
            payload = {
                "key": repr(key),
                "epochs": [_epoch_to_json(e, self.data_dir) for e in result.epochs],
                "warnings": result.warnings,
            }
            tmp = self._cache_file(key).with_suffix(".tmp")
            tmp.write_text(json.dumps(payload, indent=1), "utf-8")
            tmp.replace(self._cache_file(key))
        except OSError as exc:
            LOGGER.warning("Could not persist discovery cache: %s", exc)

    def _epoch(self, obs: ObservationRecord, target: TargetRecord, fov_arcmin: float) -> DiscoveredEpoch:
        warnings = list(obs.warnings)
        origin = "authentic_live"
        preview_path: Path | None = None
        source_path: Path | None = None
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
            source_path = _load_source_manifest(
                source, cache_directory=self.cache_dir, manifest_directory=self.manifest_dir
            )
            cutout, cutout_wcs, _, _ = _load_image_cutout(
                source_path, obs.observation_id, target, fov_arcmin=fov_arcmin * 1.5
            )
            aligned = reproject_north_up(cutout, cutout_wcs, target.ra_deg, target.dec_deg, fov_arcmin)
            preview_path = save_png(
                render_display(aligned), self.previews_dir / "aligned" / preview.preview_filename
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
            detector=_short_band(obs.band),
            release=obs.release,
            wavelength_range_um=DETECTOR_WAVELENGTH_UM.get(_short_band(obs.band)),
            source_fits_path=source_path,
        )
