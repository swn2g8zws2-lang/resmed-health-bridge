from datetime import date
import json

import pytest

from resmed_health_bridge.adapters.myair import (
    API_ORIGIN,
    LOGIN_PATH,
    SLEEP_RECORDS_PATH,
    MyAirError,
    ResMedMyAirAdapter,
    _Response,
    ingest_myair,
)
from resmed_health_bridge.storage import NightlyStore


class MockTransport:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.requests = []

    def __call__(self, request):
        self.requests.append(request)
        return next(self.responses)


def response(payload, status=200):
    return _Response(status, json.dumps(payload).encode())


def test_authentication_and_read_only_nightly_request():
    transport = MockTransport([
        response({"token": "synthetic-token"}),
        response({"sleepRecords": []}),
    ])
    adapter = ResMedMyAirAdapter("person@example.invalid", "synthetic-password", transport=transport)

    assert adapter.fetch_range(date(2026, 1, 1), date(2026, 1, 2)) == []
    login, nightly = transport.requests
    assert login.full_url == API_ORIGIN + LOGIN_PATH
    assert login.method == "POST"
    assert json.loads(login.data) == {
        "email": "person@example.invalid", "password": "synthetic-password"
    }
    assert nightly.full_url == (
        API_ORIGIN + SLEEP_RECORDS_PATH + "?startDate=2026-01-01&endDate=2026-01-02"
    )
    assert nightly.method == "GET"
    assert nightly.get_header("Authorization") == "Bearer synthetic-token"
    assert all(request.method in {"GET", "POST"} for request in transport.requests)


def test_nightly_data_is_normalized_and_sorted():
    transport = MockTransport([
        response({"token": "synthetic-token"}),
        response({"sleepRecords": [
            {"date": "2026-01-02", "usage": 28_860, "eventsPerHour": 1.7,
             "score": 94, "maskSeal": 20},
            {"date": "2026-01-01", "usage": 23_400, "eventsPerHour": None},
        ]}),
    ])
    records = ResMedMyAirAdapter("u", "p", transport=transport).fetch_range(
        date(2026, 1, 1), date(2026, 1, 2)
    )
    assert [record.public_dict() for record in records] == [
        {"night": "2026-01-01", "usage_minutes": 390, "ahi": None,
         "leak_95_lpm": None, "pressure_95_cmh2o": None, "source": "myair"},
        {"night": "2026-01-02", "usage_minutes": 481, "ahi": 1.7,
         "leak_95_lpm": None, "pressure_95_cmh2o": None, "source": "myair"},
    ]


@pytest.mark.parametrize("responses, message", [
    ([_Response(401, b'{"detail":"synthetic"}')], "HTTP status 401"),
    ([response({"unexpected": "shape"})], "did not contain a token"),
    ([response({"token": "x"}), _Response(200, b"not-json")], "not valid JSON"),
    ([response({"token": "x"}), response({"sleepRecords": [{}]})], "invalid record"),
])
def test_failures_are_sanitized(responses, message):
    with pytest.raises(MyAirError, match=message) as caught:
        ResMedMyAirAdapter("secret-user", "secret-password", transport=MockTransport(responses)).fetch_range(
            date(2026, 1, 1), date(2026, 1, 1)
        )
    assert "secret" not in str(caught.value)


def test_range_is_bounded_before_authentication():
    transport = MockTransport([])
    with pytest.raises(ValueError, match="366"):
        ResMedMyAirAdapter("u", "p", transport=transport).fetch_range(
            date(2025, 1, 1), date(2026, 1, 2)
        )
    assert transport.requests == []


def test_ingestion_persists_only_normalized_records(tmp_path):
    transport = MockTransport([
        response({"token": "x"}),
        response({"sleepRecords": [
            {"date": "2026-01-03", "usage": 25_200, "eventsPerHour": 2.1}
        ]}),
    ])
    store = NightlyStore(tmp_path / "private" / "synthetic.sqlite3")
    store.initialize()
    count = ingest_myair(
        ResMedMyAirAdapter("u", "p", transport=transport), store,
        date(2026, 1, 3), date(2026, 1, 3),
    )
    assert count == 1
    assert store.last().public_dict() == {
        "night": "2026-01-03", "usage_minutes": 420, "ahi": 2.1,
        "leak_95_lpm": None, "pressure_95_cmh2o": None, "source": "myair",
    }
