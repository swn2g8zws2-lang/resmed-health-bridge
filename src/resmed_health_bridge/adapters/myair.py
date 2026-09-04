"""Read-only adapter for the unofficial myAir consumer API.

The deliberately small protocol implemented here was independently written after
reviewing ``prestomation/resmed_myair_sensors``.  Keep all unofficial API knowledge in
this module: callers receive normalized records and never tokens or upstream payloads.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import json
from typing import Any, Callable, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from ..models import NightlyRecord


API_ORIGIN = "https://myair2-api.resmed.com"
LOGIN_PATH = "/v1/login"
SLEEP_RECORDS_PATH = "/v1/sleepRecords"
MAX_FETCH_DAYS = 366
MAX_RESPONSE_BYTES = 2 * 1024 * 1024


class MyAirError(RuntimeError):
    """A deliberately non-sensitive description of an upstream failure."""


class MyAirAdapter(Protocol):
    def fetch_range(self, start: date, end: date) -> list[NightlyRecord]: ...


@dataclass(frozen=True)
class _Response:
    status: int
    body: bytes


Transport = Callable[[Request], _Response]


def _urlopen_transport(request: Request) -> _Response:
    try:
        with urlopen(request, timeout=30) as response:  # noqa: S310 - fixed HTTPS origin
            body = response.read(MAX_RESPONSE_BYTES + 1)
            if len(body) > MAX_RESPONSE_BYTES:
                raise MyAirError("myAir response exceeded the size limit")
            return _Response(response.status, body)
    except HTTPError as error:
        # Never include an upstream response body: it may contain account data.
        raise MyAirError(f"myAir request failed with HTTP status {error.code}") from None
    except (URLError, TimeoutError, OSError):
        raise MyAirError("myAir request failed") from None


class ResMedMyAirAdapter:
    """Authenticate and retrieve nightly summaries without changing account state."""

    def __init__(self, username: str, password: str, *, transport: Transport | None = None):
        if not username or not password:
            raise ValueError("myAir username and password are required")
        self._username = username
        self._password = password
        self._transport = transport or _urlopen_transport

    def fetch_range(self, start: date, end: date) -> list[NightlyRecord]:
        _validate_range(start, end)
        token = self._authenticate()
        request = Request(
            f"{API_ORIGIN}{SLEEP_RECORDS_PATH}?startDate={start.isoformat()}&endDate={end.isoformat()}",
            headers={"Accept": "application/json", "Authorization": f"Bearer {token}"},
            method="GET",
        )
        payload = self._json(self._transport(request), "nightly data")
        raw_records = payload.get("sleepRecords") if isinstance(payload, dict) else None
        if not isinstance(raw_records, list):
            raise MyAirError("myAir nightly-data response has an unexpected shape")
        records = [_normalize_record(item) for item in raw_records]
        if any(record.night < start or record.night > end for record in records):
            raise MyAirError("myAir returned a record outside the requested range")
        return sorted(records, key=lambda record: record.night)

    def _authenticate(self) -> str:
        body = json.dumps({"email": self._username, "password": self._password}).encode()
        request = Request(
            f"{API_ORIGIN}{LOGIN_PATH}",
            data=body,
            headers={"Accept": "application/json", "Content-Type": "application/json"},
            method="POST",
        )
        payload = self._json(self._transport(request), "authentication")
        token = payload.get("token") if isinstance(payload, dict) else None
        if not isinstance(token, str) or not token:
            raise MyAirError("myAir authentication response did not contain a token")
        return token

    @staticmethod
    def _json(response: _Response, operation: str) -> Any:
        if response.status < 200 or response.status >= 300:
            raise MyAirError(f"myAir {operation} failed with HTTP status {response.status}")
        if len(response.body) > MAX_RESPONSE_BYTES:
            raise MyAirError("myAir response exceeded the size limit")
        try:
            return json.loads(response.body)
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise MyAirError(f"myAir {operation} response was not valid JSON") from None


def _validate_range(start: date, end: date) -> None:
    if start > end:
        raise ValueError("start must be on or before end")
    if (end - start).days + 1 > MAX_FETCH_DAYS:
        raise ValueError(f"myAir date range must not exceed {MAX_FETCH_DAYS} days")


def _normalize_record(value: Any) -> NightlyRecord:
    if not isinstance(value, dict):
        raise MyAirError("myAir nightly-data response contains an invalid record")
    try:
        # The reviewed response reports usage as seconds and calls AHI
        # ``eventsPerHour``. It does not include 95th-percentile summary fields.
        usage_seconds = int(value["usage"])
        if usage_seconds < 0 or usage_seconds % 60:
            raise ValueError("usage must be whole non-negative minutes")
        return NightlyRecord(
            night=str(value["date"]),
            usage_minutes=usage_seconds // 60,
            ahi=_optional_number(value.get("eventsPerHour")),
            leak_95_lpm=None,
            pressure_95_cmh2o=None,
            source="myair",
        )
    except (KeyError, TypeError, ValueError, OverflowError):
        raise MyAirError("myAir nightly-data response contains an invalid record") from None


def _optional_number(value: Any) -> float | None:
    return None if value is None else float(value)


def ingest_myair(adapter: MyAirAdapter, store: Any, start: date, end: date) -> int:
    """Fetch a bounded range and persist only normalized summary records."""
    records = adapter.fetch_range(start, end)
    for record in records:
        store.upsert(record)
    return len(records)
