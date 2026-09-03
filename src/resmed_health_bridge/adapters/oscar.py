"""Import normalized summaries exported from OSCAR/SD-card workflows."""

from __future__ import annotations

import csv
from pathlib import Path
from collections.abc import Iterator

from ..models import NightlyRecord

_REQUIRED = {"date", "usage_minutes"}
MAX_IMPORT_BYTES = 10 * 1024 * 1024
MAX_IMPORT_ROWS = 10_000


def import_oscar_csv(path: str | Path) -> list[NightlyRecord]:
    """Return a bounded CSV import; prefer ``iter_oscar_csv`` for ingestion."""
    return list(iter_oscar_csv(path))


def iter_oscar_csv(path: str | Path) -> Iterator[NightlyRecord]:
    """Stream a bounded CSV without retaining identifiers or changing source data."""
    csv_path = Path(path)
    if csv_path.stat().st_size > MAX_IMPORT_BYTES:
        raise ValueError("CSV exceeds maximum import size")
    with csv_path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        missing = _REQUIRED - set(reader.fieldnames or ())
        if missing:
            raise ValueError(f"missing required columns: {', '.join(sorted(missing))}")
        for row_number, row in enumerate(reader, start=1):
            if row_number > MAX_IMPORT_ROWS:
                raise ValueError("CSV exceeds maximum row count")
            yield NightlyRecord(
                night=row["date"],
                usage_minutes=int(row["usage_minutes"]),
                ahi=_optional_float(row.get("ahi")),
                leak_95_lpm=_optional_float(row.get("leak_95_lpm")),
                pressure_95_cmh2o=_optional_float(row.get("pressure_95_cmh2o")),
                source="oscar_csv",
            )


def _optional_float(value: str | None) -> float | None:
    return None if value is None or not value.strip() else float(value)
