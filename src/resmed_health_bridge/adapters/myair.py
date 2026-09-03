"""Boundary for unofficial ResMed myAir access.

No endpoint is implemented here because myAir has no supported public consumer API
contract for this use case. A future implementation must be independently reviewed,
licensed, tested, and kept behind this interface rather than guessing endpoints.
"""

from __future__ import annotations

from datetime import date
from typing import Protocol

from ..models import NightlyRecord


class MyAirAdapter(Protocol):
    """Read-only contract implemented only after an API integration is validated."""

    def fetch_range(self, start: date, end: date) -> list[NightlyRecord]: ...


class UnavailableMyAirAdapter:
    def fetch_range(self, start: date, end: date) -> list[NightlyRecord]:
        raise NotImplementedError(
            "myAir access is unofficial and intentionally not implemented; "
            "import an OSCAR-compatible CSV instead"
        )
