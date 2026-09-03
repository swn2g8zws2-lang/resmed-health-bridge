"""Import normalized summaries exported from OSCAR/SD-card workflows."""

from __future__ import annotations

import csv
from pathlib import Path

from ..models import NightlyRecord

_REQUIRED = {"date", "usage_minutes"}


def import_oscar_csv(path: str | Path) -> list[NightlyRecord]:
    """Read a CSV without retaining device identifiers or changing source data."""
    records: list[NightlyRecord] = []
    with Path(path).open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        missing = _REQUIRED - set(reader.fieldnames or ())
        if missing:
            raise ValueError(f"missing required columns: {', '.join(sorted(missing))}")
        for row in reader:
            records.append(NightlyRecord(
                night=row["date"],
                usage_minutes=int(row["usage_minutes"]),
                ahi=_optional_float(row.get("ahi")),
                leak_95_lpm=_optional_float(row.get("leak_95_lpm")),
                pressure_95_cmh2o=_optional_float(row.get("pressure_95_cmh2o")),
                source="oscar_csv",
            ))
    return records


def _optional_float(value: str | None) -> float | None:
    return None if value is None or not value.strip() else float(value)
