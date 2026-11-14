"""Boundary between the backend and the DATA workstream.

The API only talks to an ``ArchiveClient``. DATA implements a real IRSA/SPHEREx
client with the same ``discover`` method; until then ``MockArchiveClient``
(archive/mock.py) serves clearly labelled SYNTHETIC frames.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol


@dataclass
class DiscoveredEpoch:
    """One observation found by the archive, before the backend stores it."""

    epoch_id: str
    observation_time_utc: str  # ISO-8601 UTC, e.g. "2025-05-10T04:12:00Z"
    mjd: float
    band_id: str  # e.g. "D2"
    data_origin: str  # "authentic_live" | "authentic_cached" | "synthetic"
    preview_path: Path | None = None  # PNG on disk, or None if no preview could be made
    flags_summary: dict[str, int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


@dataclass
class DiscoveryResult:
    epochs: list[DiscoveredEpoch]  # any order, the backend sorts them
    warnings: list[str] = field(default_factory=list)


class ArchiveClient(Protocol):
    name: str

    def discover(self, ra: float, dec: float, radius_arcsec: float) -> DiscoveryResult:
        """Return every epoch covering (ra, dec).

        - Return an empty list (not an error) if nothing covers the position.
        - Keep frames that failed validation, with a reason in ``warnings``.
        - Raise ``change_lens.api.errors.ArchiveUnavailableError`` if IRSA is down.
        - Write preview PNGs under the configured previews/derived directories only.
        """
        ...
