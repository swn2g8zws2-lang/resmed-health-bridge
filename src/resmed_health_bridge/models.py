"""Domain models for normalized nightly therapy data."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from math import isfinite
from typing import Any


@dataclass(frozen=True)
class NightlyRecord:
    """Normalized summary of one therapy night (never device settings)."""

    night: date | str
    usage_minutes: int
    source: str
    ahi: float | None = None
    leak_95_lpm: float | None = None
    pressure_95_cmh2o: float | None = None

    def __post_init__(self) -> None:
        if isinstance(self.night, str):
            object.__setattr__(self, "night", date.fromisoformat(self.night))
        if not 0 <= self.usage_minutes <= 24 * 60:
            raise ValueError("usage_minutes must be between 0 and 1440")
        if not self.source or len(self.source) > 40:
            raise ValueError("source must contain 1 to 40 characters")
        for field in ("ahi", "leak_95_lpm", "pressure_95_cmh2o"):
            value = getattr(self, field)
            if value is not None and (value < 0 or not isfinite(value)):
                raise ValueError(f"{field} must be a finite non-negative number")

    def public_dict(self) -> dict[str, Any]:
        return {
            "night": self.night.isoformat(),
            "usage_minutes": self.usage_minutes,
            "ahi": self.ahi,
            "leak_95_lpm": self.leak_95_lpm,
            "pressure_95_cmh2o": self.pressure_95_cmh2o,
            "source": self.source,
        }
