"""Chronological timeline assembly (BE-003)."""

from collections.abc import Callable

from change_lens.archive.base import DiscoveredEpoch
from change_lens.contracts import EpochDescriptor, TimelineResponse


def build_timeline(
    investigation_id: str,
    epochs: list[DiscoveredEpoch],
    preview_url_for: Callable[[DiscoveredEpoch], str | None],
) -> TimelineResponse:
    """Dedupe by epoch_id, sort by (MJD, epoch_id), keep failed epochs visible."""
    unique: dict[str, DiscoveredEpoch] = {}
    for e in epochs:
        unique.setdefault(e.epoch_id, e)
    ordered = sorted(unique.values(), key=lambda e: (e.mjd, e.epoch_id))

    descriptors = [
        EpochDescriptor(
            epoch_id=e.epoch_id,
            observation_time_utc=e.observation_time_utc,
            mjd=e.mjd,
            band_id=e.band_id,
            preview_url=preview_url_for(e),
            flags_summary=e.flags_summary,
            quality_warning=bool(e.warnings) or e.preview_path is None,
            data_origin=e.data_origin,
            warnings=e.warnings,
            detector=e.detector,
            release=e.release,
            wavelength_range_um=e.wavelength_range_um,
        )
        for e in ordered
    ]
    return TimelineResponse(
        investigation_id=investigation_id, epochs=descriptors, total_epochs=len(descriptors)
    )
