import base64
from datetime import date
import hashlib
import json
import socket
import ssl
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit
from urllib.request import Request

import pytest

from resmed_health_bridge.adapters.myair import (
    JSON_HEADERS,
    MAX_RESPONSE_BYTES,
    NORTH_AMERICA,
    SLEEP_OPERATION,
    MyAirError,
    MyAirFailure,
    ResMedMyAirAdapter,
    _Response,
    _country_from_id_token,
    _normalize_record,
    _pkce_pair,
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


def response(payload, status=200, headers=()):
    return _Response(status, json.dumps(payload).encode(), tuple(headers))


def id_token(country="US"):
    encoded = base64.urlsafe_b64encode(json.dumps({"myAirCountryId": country}).encode())
    return "header." + encoded.decode().rstrip("=") + ".signature"


def successful_responses(items=()):
    return [
        _Response(400, b"", (("Set-Cookie", "DT=remembered; Secure; HttpOnly"),)),
        response({"status": "SUCCESS", "sessionToken": "synthetic-session"}),
        _Response(302, b"", (("Location", "https://myair.resmed.com/#code=synthetic-code"),)),
        response({"access_token": "synthetic-access", "id_token": id_token()}),
        response({"data": {"getPatientWrapper": {"sleepRecords": {"items": list(items)}}}}),
    ]


def test_verified_na_region_and_endpoints():
    assert NORTH_AMERICA.product == "myAir"
    assert NORTH_AMERICA.authn_url == "https://resmed-ext-1.okta.com/api/v1/authn"
    assert NORTH_AMERICA.authorize_url == (
        "https://resmed-ext-1.okta.com/oauth2/aus4ccsxvnidQgLmA297/v1/authorize"
    )
    assert NORTH_AMERICA.token_url.endswith("/oauth2/aus4ccsxvnidQgLmA297/v1/token")
    assert NORTH_AMERICA.introspect_url.endswith(
        "/oauth2/aus4ccsxvnidQgLmA297/v1/introspect"
    )
    assert NORTH_AMERICA.userinfo_url.endswith("/oauth2/aus4ccsxvnidQgLmA297/v1/userinfo")
    assert NORTH_AMERICA.graphql_url == "https://graphql.myair-prd.dht.live/graphql"
    assert NORTH_AMERICA.mfa_url("factor") == (
        "https://resmed-ext-1.okta.com/api/v1/authn/factors/factor/verify?rememberDevice=true"
    )


def test_success_auth_pkce_token_exchange_and_graphql(monkeypatch):
    monkeypatch.setattr("resmed_health_bridge.adapters.myair.os.urandom", lambda _: b"A" * 40)
    transport = MockTransport(successful_responses([
        {"startDate": "2026-09-03", "totalUsage": "420.9", "ahi": 1.7,
         "leakPercentile": 99, "sleepRecordPatientId": "not-retained"}
    ]))
    records = ResMedMyAirAdapter(
        "person@example.invalid", "synthetic-password", transport=transport,
        today=lambda: date(2026, 9, 3),
    ).fetch_range(date(2026, 9, 3), date(2026, 9, 3))

    prime, auth, authorize, token, graphql = transport.requests
    assert prime.full_url == NORTH_AMERICA.authorize_url and prime.method == "GET"
    assert auth.full_url == NORTH_AMERICA.authn_url and auth.method == "POST"
    assert json.loads(auth.data) == {
        "username": "person@example.invalid", "password": "synthetic-password"
    }
    assert auth.get_header("Cookie") == "DT=remembered"

    query = parse_qs(urlsplit(authorize.full_url).query)
    verifier, challenge = _pkce_pair()
    assert query == {
        "client_id": [NORTH_AMERICA.authorize_client_id],
        "code_challenge": [challenge], "code_challenge_method": ["S256"],
        "prompt": ["none"], "redirect_uri": [NORTH_AMERICA.oauth_redirect_url],
        "response_mode": ["fragment"], "response_type": ["code"],
        "sessionToken": ["synthetic-session"], "scope": ["openid profile email"],
        "state": ["abcdef"],
    }
    assert challenge == base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).decode().replace("=", "")
    assert parse_qs(token.data.decode()) == {
        "client_id": [NORTH_AMERICA.authorize_client_id],
        "redirect_uri": [NORTH_AMERICA.oauth_redirect_url],
        "grant_type": ["authorization_code"],
        "code_verifier": [verifier], "code": ["synthetic-code"],
    }
    assert token.get_header("Content-type") == "application/x-www-form-urlencoded"

    expected_headers = {
        "X-api-key": NORTH_AMERICA.myair_api_key,
        "Authorization": "Bearer synthetic-access",
        "Rmdhandsetid": "02c1c662-c289-41fd-a9ae-196ff15b5166",
        "Rmdlanguage": "en", "Rmdhandsetmodel": "Chrome",
        "Rmdhandsetosversion": "127.0.6533.119", "Rmdproduct": "myAir",
        "Rmdappversion": "1.0.0", "Rmdhandsetplatform": "Web",
        "Rmdcountry": "US", "Accept-language": "en-US,en;q=0.9",
    }
    for key, value in expected_headers.items():
        assert graphql.get_header(key) == value
    envelope = json.loads(graphql.data)
    assert envelope["operationName"] == SLEEP_OPERATION
    assert envelope["variables"] == {}
    assert 'startMonth: "2026-08-04"' in envelope["query"]
    assert 'endMonth: "2026-09-03"' in envelope["query"]
    assert "serialNumber" not in envelope["query"]
    assert [record.public_dict() for record in records] == [{
        "night": "2026-09-03", "usage_minutes": 420, "ahi": 1.7,
        "leak_95_lpm": None, "pressure_95_cmh2o": None, "source": "myair",
    }]


def test_mfa_factor_discovery_trigger_and_verification_same_session(caplog, tmp_path):
    transport = MockTransport([
        _Response(400, b"", (("Set-Cookie", "DT=synthetic-cookie; Secure"),)),
        response({
            "status": "MFA_REQUIRED", "stateToken": "synthetic-state",
            "_embedded": {"factors": [{
                "id": "synthetic-factor",
                "_links": {"verify": {"href": "https://resmed-ext-1.okta.com/verify"}},
            }]},
        }),
        response({"status": "MFA_CHALLENGE"}),
        response({"status": "SUCCESS", "sessionToken": "synthetic-session"}),
        _Response(302, b"", (("Location", "https://myair.resmed.com/#code=synthetic-code"),)),
        response({"access_token": "synthetic-access", "id_token": id_token()}),
        response({"data": {"getPatientWrapper": {"sleepRecords": {"items": []}}}}),
    ])

    def provide_code():
        # Priming, primary auth, and challenge must already have occurred in this
        # same transport/session before local terminal input is requested.
        assert len(transport.requests) == 3
        return "123456"

    adapter = ResMedMyAirAdapter(
        "u", "p", mfa_code_provider=provide_code, transport=transport,
        today=lambda: date(2026, 9, 3),
    )
    db_path = tmp_path / "private" / "synthetic.sqlite3"
    store = NightlyStore(db_path)
    store.initialize()
    assert ingest_myair(
        adapter, store, date(2026, 9, 3), date(2026, 9, 3)
    ) == 0
    trigger, verify = transport.requests[2:4]
    assert trigger.full_url == "https://resmed-ext-1.okta.com/verify?rememberDevice=true"
    assert json.loads(trigger.data) == {"passCode": "", "stateToken": "synthetic-state"}
    assert json.loads(verify.data) == {"passCode": "123456", "stateToken": "synthetic-state"}
    assert trigger.get_header("Cookie") == verify.get_header("Cookie") == "DT=synthetic-cookie"
    assert "123456" not in caplog.text
    assert "synthetic-state" not in caplog.text
    database = db_path.read_bytes()
    for secret in (
        b"123456", b"synthetic-state", b"synthetic-session", b"synthetic-cookie"
    ):
        assert secret not in database


def test_mfa_without_code_is_sanitized_after_trigger():
    transport = MockTransport([
        _Response(400, b""),
        response({"status": "MFA_REQUIRED", "stateToken": "do-not-expose"}),
        response({"status": "MFA_CHALLENGE"}),
    ])
    with pytest.raises(MyAirError) as caught:
        ResMedMyAirAdapter(
            "u", "p", mfa_code_provider=lambda: "", transport=transport,
            today=lambda: date(2026, 9, 3),
        ).fetch_range(
            date(2026, 9, 3), date(2026, 9, 3)
        )
    assert caught.value.category is MyAirFailure.MFA_REQUIRED
    assert "do-not-expose" not in str(caught.value)


@pytest.mark.parametrize("token_payload", [
    {"id_token": id_token()},
    {"access_token": "synthetic-access"},
])
def test_token_exchange_requires_access_and_id_tokens(token_payload):
    responses = successful_responses()
    responses[3] = response(token_payload)
    with pytest.raises(MyAirError) as caught:
        ResMedMyAirAdapter(
            "u", "p", transport=MockTransport(responses),
            today=lambda: date(2026, 9, 3),
        ).fetch_range(date(2026, 9, 3), date(2026, 9, 3))
    assert caught.value.category is MyAirFailure.MALFORMED_RESPONSE
    assert "synthetic" not in str(caught.value)


def test_cookie_and_redirect_secrets_never_appear_in_error():
    transport = MockTransport([
        _Response(400, b"", (("Set-Cookie", "DT=private-cookie; Secure"),)),
        response({"status": "SUCCESS", "sessionToken": "private-session"}),
        _Response(302, b"", (("Location", "https://myair.resmed.com/#state=private"),)),
    ])
    with pytest.raises(MyAirError) as caught:
        ResMedMyAirAdapter(
            "u", "p", transport=transport, today=lambda: date(2026, 9, 3)
        ).fetch_range(date(2026, 9, 3), date(2026, 9, 3))
    message = str(caught.value)
    assert "private" not in message
    assert caught.value.category is MyAirFailure.MALFORMED_RESPONSE


@pytest.mark.parametrize("raw, expected", [(420, 420), ("420", 420), (420.9, 420)])
def test_total_usage_is_minutes_and_fraction_is_truncated(raw, expected):
    assert _normalize_record({"startDate": "2026-09-03", "totalUsage": raw}).usage_minutes == expected


@pytest.mark.parametrize("token", ["bad", "a.e30.b", id_token("")])
def test_country_claim_is_required(token):
    with pytest.raises(MyAirError, match=r"myAir authentication failed \(malformed_response\)"):
        _country_from_id_token(token)


@pytest.mark.parametrize("responses, category, status", [
    ([_Response(400, b""), _Response(401, b"")], MyAirFailure.CREDENTIAL_REJECTION, 401),
    ([_Response(400, b""), _Response(429, b"")], MyAirFailure.HTTP_STATUS, 429),
    ([_Response(400, b""), response({"status": "UNKNOWN", "password": "secret"})],
     MyAirFailure.MALFORMED_RESPONSE, None),
    (successful_responses()[:-1] + [response({"data": {}})],
     MyAirFailure.MALFORMED_RESPONSE, None),
    (successful_responses()[:-1] + [_Response(200, b"x" * (MAX_RESPONSE_BYTES + 1))],
     MyAirFailure.RESPONSE_TOO_LARGE, None),
])
def test_failures_are_sanitized(responses, category, status):
    with pytest.raises(MyAirError) as caught:
        ResMedMyAirAdapter(
            "secret-user", "secret-password", transport=MockTransport(responses),
            today=lambda: date(2026, 9, 3),
        ).fetch_range(date(2026, 9, 3), date(2026, 9, 3))
    assert caught.value.category is category and caught.value.status == status
    assert "secret" not in str(caught.value)


@pytest.mark.parametrize("reason, category", [
    (socket.gaierror("secret DNS detail"), MyAirFailure.DNS),
    (ssl.SSLError("secret TLS detail"), MyAirFailure.TLS),
    (TimeoutError("secret timeout detail"), MyAirFailure.TIMEOUT),
    (ConnectionError("secret network detail"), MyAirFailure.NETWORK),
])
def test_transport_failures_are_classified(monkeypatch, reason, category):
    class Opener:
        def open(self, request, timeout):
            assert timeout == 30
            raise URLError(reason)

    monkeypatch.setattr("resmed_health_bridge.adapters.myair.build_opener", lambda *_: Opener())
    with pytest.raises(MyAirError) as caught:
        _urlopen_transport(Request(NORTH_AMERICA.authn_url))
    assert caught.value.category is category
    assert "secret" not in str(caught.value)


def test_http_error_body_is_not_read(monkeypatch):
    error = HTTPError(NORTH_AMERICA.authn_url, 429, "secret reason", {}, None)

    class Opener:
        def open(self, request, timeout):
            raise error

    monkeypatch.setattr("resmed_health_bridge.adapters.myair.build_opener", lambda *_: Opener())
    assert _urlopen_transport(Request(NORTH_AMERICA.authn_url)).body == b""


def test_range_is_bounded_before_authentication():
    transport = MockTransport([])
    with pytest.raises(ValueError, match="366"):
        ResMedMyAirAdapter("u", "p", transport=transport).fetch_range(
            date(2025, 1, 1), date(2026, 1, 2)
        )
    assert transport.requests == []


def test_ingestion_persists_only_normalized_fields(tmp_path):
    transport = MockTransport(successful_responses([
        {"startDate": "2026-09-03", "totalUsage": 420, "ahi": 2.1,
         "sleepRecordPatientId": "never-store", "leakPercentile": 12}
    ]))
    store = NightlyStore(tmp_path / "private" / "synthetic.sqlite3")
    store.initialize()
    count = ingest_myair(
        ResMedMyAirAdapter("u", "p", transport=transport, today=lambda: date(2026, 9, 3)),
        store, date(2026, 9, 3), date(2026, 9, 3),
    )
    assert count == 1
    assert "never-store" not in str(store.last().public_dict())
    assert store.last().leak_95_lpm is None and store.last().pressure_95_cmh2o is None
