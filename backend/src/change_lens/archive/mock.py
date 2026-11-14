"""Mock archive: deterministic SYNTHETIC frames so FE can build the player offline.

Used when SPHEREX_ARCHIVE_MOCK_MODE=true (the default). Nothing here is SPHEREx
data. Every epoch has data_origin="synthetic" and every PNG is stamped
"SYNTHETIC".
"""

import random
from pathlib import Path

from change_lens.archive.base import DiscoveredEpoch, DiscoveryResult

_SIZE = 256
# (epoch suffix, UTC time, MJD, frame index for the moving dot, extra warnings)
_EPOCHS = [
    ("001", "2025-05-10T04:12:00Z", 60805.175, 0, []),
    ("002", "2025-08-02T11:40:00Z", 60889.486, 1, ["PSF_METADATA_INCOMPLETE"]),
    ("003", "2025-11-15T22:05:00Z", 60994.920, 2, ["OUTSIDE_FOOTPRINT"]),
    ("004", "2026-02-20T07:30:00Z", 61091.313, 3, []),
    ("005", "2026-05-28T16:55:00Z", 61188.705, 4, []),
]


def _render_png(path: Path, frame_index: int) -> None:
    from PIL import Image, ImageDraw, ImageFilter

    star_rng = random.Random(42)  # identical static stars in every frame
    stars = [
        (star_rng.uniform(8, _SIZE - 8), star_rng.uniform(8, _SIZE - 8), star_rng.uniform(1, 3))
        for _ in range(60)
    ]
    noise_rng = random.Random(frame_index)
    img = Image.new("L", (_SIZE, _SIZE))
    img.putdata([max(0, min(255, 12 + int(noise_rng.gauss(0, 6)))) for _ in range(_SIZE * _SIZE)])
    draw = ImageDraw.Draw(img)
    for x, y, r in stars:
        draw.ellipse([x - r, y - r, x + r, y + r], fill=200)
    mx, my = 90 + frame_index * 18, 150 - frame_index * 10  # slowly moving source
    draw.ellipse([mx - 3, my - 3, mx + 3, my + 3], fill=255)
    img = img.filter(ImageFilter.GaussianBlur(0.8))
    ImageDraw.Draw(img).text((6, _SIZE - 14), "SYNTHETIC", fill=255)
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path)


class MockArchiveClient:
    name = "mock"

    def __init__(self, synthetic_dir: Path):
        self.preview_dir = Path(synthetic_dir) / "previews"

    def discover(self, ra: float, dec: float, radius_arcsec: float) -> DiscoveryResult:
        epochs = []
        for suffix, when, mjd, idx, warnings in _EPOCHS:
            outside = "OUTSIDE_FOOTPRINT" in warnings
            preview = None
            if not outside:
                preview = self.preview_dir / f"syn_{suffix}.png"
                if not preview.is_file():
                    _render_png(preview, idx)
            epochs.append(
                DiscoveredEpoch(
                    epoch_id=f"syn_epoch_{suffix}",
                    observation_time_utc=when,
                    mjd=mjd,
                    band_id="D2",
                    data_origin="synthetic",
                    preview_path=preview,
                    flags_summary={"BAD_PIXEL": 3, "EDGE": 12} if warnings else {},
                    warnings=list(warnings),
                    detector="D2",
                    release="SYNTHETIC",
                    wavelength_range_um=[1.10, 1.62],
                )
            )
        return DiscoveryResult(
            epochs=epochs,
            warnings=["SYNTHETIC_DATA: mock archive mode, these are generated test images, not SPHEREx observations"],
        )
