from __future__ import annotations

from changelens.data.network import ARCHIVE_REQUEST_GATE, MAX_ARCHIVE_CONCURRENCY


def test_archive_request_gate_has_two_bounded_slots() -> None:
    assert MAX_ARCHIVE_CONCURRENCY == 2
    acquired = 0
    try:
        assert ARCHIVE_REQUEST_GATE.acquire(blocking=False)
        acquired += 1
        assert ARCHIVE_REQUEST_GATE.acquire(blocking=False)
        acquired += 1
        assert not ARCHIVE_REQUEST_GATE.acquire(blocking=False)
    finally:
        for _ in range(acquired):
            ARCHIVE_REQUEST_GATE.release()
