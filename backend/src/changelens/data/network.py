"""Shared bound for concurrent IRSA archive requests."""

from __future__ import annotations

from threading import BoundedSemaphore


MAX_ARCHIVE_CONCURRENCY = 2
ARCHIVE_REQUEST_GATE = BoundedSemaphore(MAX_ARCHIVE_CONCURRENCY)


__all__ = ["ARCHIVE_REQUEST_GATE", "MAX_ARCHIVE_CONCURRENCY"]
