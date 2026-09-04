"""Local SQLite cache for normalized nightly records."""

from __future__ import annotations

import os
import sqlite3
from datetime import date
from pathlib import Path

from .models import NightlyRecord


def _supports_posix_permissions() -> bool:
    """Return whether chmod mode bits provide the filesystem access control."""
    return os.name != "nt"


class NightlyStore:
    MAX_RANGE_RESULTS = 366

    def __init__(self, path: str | Path):
        self.path = str(Path(path).expanduser()) if str(path) != ":memory:" else ":memory:"

    def initialize(self) -> None:
        if self.path != ":memory:":
            database = Path(self.path)
            parent_existed = database.parent.exists()
            database.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            if database.parent.is_symlink():
                raise ValueError("database directory must not be a symbolic link")
            if _supports_posix_permissions():
                if parent_existed and database.parent.stat().st_mode & 0o077:
                    raise PermissionError("database directory must have mode 0700 or stricter")
                database.parent.chmod(0o700)
            if database.is_symlink():
                raise ValueError("database path must not be a symbolic link")
        with self._connect() as connection:
            connection.execute("""
                CREATE TABLE IF NOT EXISTS nightly_records (
                    night TEXT PRIMARY KEY,
                    usage_minutes INTEGER NOT NULL CHECK (usage_minutes >= 0),
                    ahi REAL,
                    leak_95_lpm REAL,
                    pressure_95_cmh2o REAL,
                    source TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)
        if self.path != ":memory:" and _supports_posix_permissions():
            Path(self.path).chmod(0o600)

    def upsert(self, record: NightlyRecord) -> None:
        with self._connect() as connection:
            connection.execute("""
                INSERT INTO nightly_records
                    (night, usage_minutes, ahi, leak_95_lpm, pressure_95_cmh2o, source)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(night) DO UPDATE SET
                    usage_minutes=excluded.usage_minutes,
                    ahi=excluded.ahi,
                    leak_95_lpm=excluded.leak_95_lpm,
                    pressure_95_cmh2o=excluded.pressure_95_cmh2o,
                    source=excluded.source,
                    updated_at=CURRENT_TIMESTAMP
            """, (record.night.isoformat(), record.usage_minutes, record.ahi,
                  record.leak_95_lpm, record.pressure_95_cmh2o, record.source))

    def range(self, start: date, end: date) -> list[NightlyRecord]:
        with self._connect() as connection:
            rows = connection.execute("""
                SELECT night, usage_minutes, ahi, leak_95_lpm, pressure_95_cmh2o, source
                FROM nightly_records WHERE night BETWEEN ? AND ? ORDER BY night LIMIT ?
            """, (start.isoformat(), end.isoformat(), self.MAX_RANGE_RESULTS + 1)).fetchall()
        if len(rows) > self.MAX_RANGE_RESULTS:
            raise ValueError("query result exceeds maximum number of nights")
        return [NightlyRecord(**dict(row)) for row in rows]

    def last(self) -> NightlyRecord | None:
        with self._connect() as connection:
            row = connection.execute("""
                SELECT night, usage_minutes, ahi, leak_95_lpm, pressure_95_cmh2o, source
                FROM nightly_records ORDER BY night DESC LIMIT 1
            """).fetchone()
        return NightlyRecord(**dict(row)) if row else None

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=DELETE")
        connection.execute("PRAGMA temp_store=MEMORY")
        return connection
