"""SQLite repository for investigations, timelines and preview artifacts (BE-004).

Only structured state lives in SQLite. Images stay on disk; the artifacts
table maps an opaque artifact_id to a file path.
"""

import sqlite3
import threading
from pathlib import Path

from change_lens.contracts import (
    EvidenceResponse,
    InvestigationMetadata,
    MoversResponse,
    TimelineResponse,
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS investigations (
    investigation_id TEXT PRIMARY KEY,
    body             TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS timelines (
    investigation_id TEXT PRIMARY KEY,
    body             TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS artifacts (
    artifact_id TEXT PRIMARY KEY,
    path        TEXT NOT NULL,
    media_type  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS epoch_sources (
    investigation_id TEXT NOT NULL,
    epoch_id         TEXT NOT NULL,
    mjd              REAL NOT NULL,
    fits_path        TEXT NOT NULL,
    detector         TEXT,
    release          TEXT,
    PRIMARY KEY (investigation_id, epoch_id)
);
CREATE TABLE IF NOT EXISTS mover_results (
    investigation_id TEXT PRIMARY KEY,
    body             TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS evidence_results (
    investigation_id TEXT PRIMARY KEY,
    body             TEXT NOT NULL
);
"""


class Repository:
    def __init__(self, db_path: Path | str):
        if str(db_path) != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._lock = threading.Lock()
        with self._lock:
            self._conn.executescript(_SCHEMA)
            self._conn.commit()

    def ping(self) -> None:
        with self._lock:
            self._conn.execute("SELECT 1")

    def _put(self, sql: str, params: tuple) -> None:
        with self._lock:
            self._conn.execute(sql, params)
            self._conn.commit()

    def _get(self, sql: str, params: tuple) -> tuple | None:
        with self._lock:
            return self._conn.execute(sql, params).fetchone()

    # investigations -------------------------------------------------------
    def save_investigation(self, inv: InvestigationMetadata) -> None:
        self._put(
            "INSERT OR REPLACE INTO investigations VALUES (?, ?)",
            (inv.investigation_id, inv.model_dump_json()),
        )

    def get_investigation(self, investigation_id: str) -> InvestigationMetadata | None:
        row = self._get("SELECT body FROM investigations WHERE investigation_id = ?", (investigation_id,))
        return InvestigationMetadata.model_validate_json(row[0]) if row else None

    # timelines ------------------------------------------------------------
    def save_timeline(self, timeline: TimelineResponse) -> None:
        self._put(
            "INSERT OR REPLACE INTO timelines VALUES (?, ?)",
            (timeline.investigation_id, timeline.model_dump_json()),
        )

    def get_timeline(self, investigation_id: str) -> TimelineResponse | None:
        row = self._get("SELECT body FROM timelines WHERE investigation_id = ?", (investigation_id,))
        return TimelineResponse.model_validate_json(row[0]) if row else None

    # artifacts ------------------------------------------------------------
    def save_artifact(self, artifact_id: str, path: Path, media_type: str) -> None:
        self._put(
            "INSERT OR REPLACE INTO artifacts VALUES (?, ?, ?)",
            (artifact_id, str(Path(path).resolve()), media_type),
        )

    def get_artifact(self, artifact_id: str) -> tuple[Path, str] | None:
        row = self._get("SELECT path, media_type FROM artifacts WHERE artifact_id = ?", (artifact_id,))
        return (Path(row[0]), row[1]) if row else None

    # epoch sources (real FITS per timeline frame) ---------------------------
    def save_epoch_source(
        self, investigation_id: str, epoch_id: str, mjd: float, fits_path: Path,
        detector: str | None, release: str | None,
    ) -> None:
        self._put(
            "INSERT OR REPLACE INTO epoch_sources VALUES (?, ?, ?, ?, ?, ?)",
            (investigation_id, epoch_id, mjd, str(Path(fits_path).resolve()), detector, release),
        )

    def get_epoch_sources(self, investigation_id: str) -> list[tuple[str, float, Path, str | None, str | None]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT epoch_id, mjd, fits_path, detector, release FROM epoch_sources "
                "WHERE investigation_id = ? ORDER BY mjd, epoch_id",
                (investigation_id,),
            ).fetchall()
        return [(r[0], r[1], Path(r[2]), r[3], r[4]) for r in rows]

    # mover results ------------------------------------------------------------
    def save_movers(self, result: MoversResponse) -> None:
        self._put(
            "INSERT OR REPLACE INTO mover_results VALUES (?, ?)",
            (result.investigation_id, result.model_dump_json()),
        )

    def get_movers(self, investigation_id: str) -> MoversResponse | None:
        row = self._get("SELECT body FROM mover_results WHERE investigation_id = ?", (investigation_id,))
        return MoversResponse.model_validate_json(row[0]) if row else None

    # evidence results (SCI phase 4) -------------------------------------------
    def save_evidence(self, result: EvidenceResponse) -> None:
        self._put(
            "INSERT OR REPLACE INTO evidence_results VALUES (?, ?)",
            (result.investigation_id, result.model_dump_json()),
        )

    def get_evidence(self, investigation_id: str) -> EvidenceResponse | None:
        row = self._get(
            "SELECT body FROM evidence_results WHERE investigation_id = ?", (investigation_id,)
        )
        return EvidenceResponse.model_validate_json(row[0]) if row else None
