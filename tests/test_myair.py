from datetime import date
import json
import socket
import ssl
from urllib.error import HTTPError, URLError
from urllib.request import Request

import pytest

from resmed_health_bridge.adapters.myair import (
    API_ORIGIN,
    LOGIN_PATH,
    SLEEP_RECORDS_PATH,
    MyAirError,
    MyAirFailure,
    ResMedMyAirAdapter,
    _Response,
    _urlopen_transport,
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


@pytest.mark.parametrize("responses, category, status", [
    ([_Response(401, b'{"detail":"synthetic"}')], MyAirFailure.CREDENTIAL_REJECTION, 401),
    ([_Response(403, b'{"detail":"synthetic"}')], MyAirFailure.HTTP_STATUS, 403),
    ([response({"unexpected": "shape"})], MyAirFailure.MALFORMED_RESPONSE, None),
    ([response({"token": "x"}), _Response(200, b"not-json")], MyAirFailure.MALFORMED_RESPONSE, None),
    ([response({"token": "x"}), response({"sleepRecords": [{}]})], MyAirFailure.MALFORMED_RESPONSE, None),
])
def test_failures_are_sanitized_and_classified(responses, category, status):
    with pytest.raises(MyAirError) as caught:
        ResMedMyAirAdapter("secret-user", "secret-password", transport=MockTransport(responses)).fetch_range(
            date(2026, 1, 1), date(2026, 1, 1)
        )
    assert caught.value.category is category
    assert caught.value.status == status
    assert "secret" not in str(caught.value)


@pytest.mark.parametrize("reason, category", [
    (socket.gaierror("secret DNS detail"), MyAirFailure.DNS),
    (ssl.SSLError("secret TLS detail"), MyAirFailure.TLS),
    (TimeoutError("secret timeout detail"), MyAirFailure.TIMEOUT),
    (ConnectionError("secret network detail"), MyAirFailure.NETWORK),
])
def test_transport_failures_are_classified_without_leaking_details(monkeypatch, reason, category):
    def fail(_request, timeout):
        assert timeout == 30
        raise URLError(reason)

    monkeypatch.setattr("resmed_health_bridge.adapters.myair.urlopen", fail)
    with pytest.raises(MyAirError) as caught:
        _urlopen_transport(Request(API_ORIGIN + LOGIN_PATH))
    assert caught.value.category is category
    assert caught.value.status is None
    assert "secret" not in str(caught.value)


def test_http_error_body_is_not_read_or_exposed(monkeypatch):
    error = HTTPError(API_ORIGIN + LOGIN_PATH, 429, "secret reason", {}, None)

    def fail(_request, timeout):
        raise error

    monkeypatch.setattr("resmed_health_bridge.adapters.myair.urlopen", fail)
    result = _urlopen_transport(Request(API_ORIGIN + LOGIN_PATH))
    assert result == _Response(429, b"")


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
