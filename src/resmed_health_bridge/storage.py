"""Local SQLite cache for normalized nightly records."""

from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path

from .models import NightlyRecord


class NightlyStore:
    def __init__(self, path: str | Path):
        self.path = str(path)

    def initialize(self) -> None:
        if self.path != ":memory:":
            Path(self.path).expanduser().parent.mkdir(parents=True, exist_ok=True, mode=0o700)
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
        if self.path != ":memory:":
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
                FROM nightly_records WHERE night BETWEEN ? AND ? ORDER BY night
            """, (start.isoformat(), end.isoformat())).fetchall()
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
        return connection
