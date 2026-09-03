"""Query-only application service used by MCP tools."""

from __future__ import annotations

from datetime import date
from statistics import mean
from typing import Any

from .storage import NightlyStore


class TherapyQueries:
    def __init__(self, store: NightlyStore):
        self.store = store

    def last_night(self) -> dict[str, Any] | None:
        record = self.store.last()
        return record.public_dict() if record else None

    def therapy_range(self, start: date, end: date) -> list[dict[str, Any]]:
        return [record.public_dict() for record in self._range(start, end)]

    def metric_trend(self, metric: str, start: date, end: date) -> dict[str, Any]:
        allowed = {"ahi", "leak_95_lpm", "usage_minutes"}
        if metric not in allowed:
            raise ValueError("unsupported metric")
        records = self._range(start, end)
        points = [
            {"night": record.night.isoformat(), "value": getattr(record, metric)}
            for record in records if getattr(record, metric) is not None
        ]
        values = [point["value"] for point in points]
        return {
            "metric": metric,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "points": points,
            "average": round(mean(values), 2) if values else None,
        }

    def pressure_summary(self, start: date, end: date) -> dict[str, Any]:
        records = self._range(start, end)
        values = [r.pressure_95_cmh2o for r in records if r.pressure_95_cmh2o is not None]
        return {
            "metric": "pressure_95_cmh2o",
            "start": start.isoformat(),
            "end": end.isoformat(),
            "nights_with_data": len(values),
            "minimum": min(values) if values else None,
            "maximum": max(values) if values else None,
            "average": round(mean(values), 2) if values else None,
        }

    def _range(self, start: date, end: date):
        if start > end:
            raise ValueError("start must be on or before end")
        return self.store.range(start, end)
