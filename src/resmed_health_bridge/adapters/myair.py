"""Read-only adapter for the reverse-engineered myAir consumer interface.

Protocol constants in this module are deliberately closed-world.  They were recorded
from ``prestomation/resmed_myair_sensors`` on 2026-09-03; callers cannot provide an
origin, endpoint, API key, or GraphQL document.
"""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from enum import Enum
import hashlib
from http.cookies import SimpleCookie
import json
import os
import re
import socket
import ssl
from typing import Any, Callable, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urldefrag
from urllib.request import HTTPRedirectHandler, Request, build_opener

from ..models import NightlyRecord


@dataclass(frozen=True)
class MyAirRegion:
    """Verified, fixed protocol configuration for one myAir region."""

    product: str
    okta_url: str
    email_factor_id: str
    auth_server_id: str
    authorize_client_id: str
    myair_api_key: str
    graphql_url: str
    oauth_redirect_url: str

    @property
    def authn_url(self) -> str:
        return f"https://{self.okta_url}/api/v1/authn"

    @property
    def authorize_url(self) -> str:
        return f"https://{self.okta_url}/oauth2/{self.auth_server_id}/v1/authorize"

    @property
    def token_url(self) -> str:
        return f"https://{self.okta_url}/oauth2/{self.auth_server_id}/v1/token"

    @property
    def introspect_url(self) -> str:
        return f"https://{self.okta_url}/oauth2/{self.auth_server_id}/v1/introspect"

    @property
    def userinfo_url(self) -> str:
        return f"https://{self.okta_url}/oauth2/{self.auth_server_id}/v1/userinfo"

    def mfa_url(self, factor_id: str) -> str:
        return (
            f"https://{self.okta_url}/api/v1/authn/factors/{factor_id}/verify"
            "?rememberDevice=true"
        )


NORTH_AMERICA = MyAirRegion(
    product="myAir",
    okta_url="resmed-ext-1.okta.com",
    email_factor_id="xxx",
    auth_server_id="aus4ccsxvnidQgLmA297",
    authorize_client_id="0oa4ccq1v413ypROi297",
    myair_api_key="da2-cenztfjrezhwphdqtwtbpqvzui",
    graphql_url="https://graphql.myair-prd.dht.live/graphql",
    oauth_redirect_url="https://myair.resmed.com",
)

MAX_FETCH_DAYS = 366
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
JSON_HEADERS = {"Accept": "application/json", "Content-Type": "application/json"}
SLEEP_OPERATION = "GetPatientSleepRecords"
SLEEP_QUERY = """query GetPatientSleepRecords {
    getPatientWrapper {
        patient {
            firstName
        }
        sleepRecords(startMonth: "ONE_MONTH_AGO", endMonth: "DATE")
        {
            items {
                startDate
                totalUsage
                sleepScore
                usageScore
                ahiScore
                maskScore
                leakScore
                ahi
                maskPairCount
                leakPercentile
                sleepRecordPatientId
                __typename
            }
            __typename
        }
        __typename
    }
}"""


class MyAirFailure(str, Enum):
    """Stable, non-sensitive failure categories suitable for support reports."""

    HTTP_STATUS = "http_status"
    DNS = "dns_failure"
    TLS = "tls_failure"
    TIMEOUT = "network_timeout"
    NETWORK = "network_failure"
    CREDENTIAL_REJECTION = "credential_rejection"
    MFA_REQUIRED = "mfa_required"
    MALFORMED_RESPONSE = "malformed_response"
    RESPONSE_TOO_LARGE = "response_too_large"


class MyAirError(RuntimeError):
    """A deliberately non-sensitive, machine-classifiable upstream failure."""

    def __init__(
        self, category: MyAirFailure, operation: str, *, status: int | None = None
    ) -> None:
        self.category = category
        self.operation = operation
        self.status = status
        detail = f"; HTTP status {status}" if status is not None else ""
        super().__init__(f"myAir {operation} failed ({category.value}{detail})")


class MyAirAdapter(Protocol):
    def fetch_range(self, start: date, end: date) -> list[NightlyRecord]: ...


@dataclass(frozen=True)
class _Response:
    status: int
    body: bytes
    headers: tuple[tuple[str, str], ...] = ()

    def header_values(self, name: str) -> list[str]:
        return [value for key, value in self.headers if key.lower() == name.lower()]


Transport = Callable[[Request], _Response]
MfaCodeProvider = Callable[[], str]


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


def _response_headers(headers: Any) -> tuple[tuple[str, str], ...]:
    return tuple(headers.items()) if headers is not None else ()


def _urlopen_transport(request: Request) -> _Response:
    try:
        with build_opener(_NoRedirect).open(request, timeout=30) as response:
            body = response.read(MAX_RESPONSE_BYTES + 1)
            if len(body) > MAX_RESPONSE_BYTES:
                raise MyAirError(MyAirFailure.RESPONSE_TOO_LARGE, "request")
            return _Response(response.status, body, _response_headers(response.headers))
    except HTTPError as error:
        # Never read the error body: authentication responses can contain secrets.
        return _Response(error.code, b"", _response_headers(error.headers))
    except URLError as error:
        reason = error.reason
        if isinstance(reason, socket.gaierror):
            category = MyAirFailure.DNS
        elif isinstance(reason, ssl.SSLError):
            category = MyAirFailure.TLS
        elif isinstance(reason, (TimeoutError, socket.timeout)):
            category = MyAirFailure.TIMEOUT
        else:
            category = MyAirFailure.NETWORK
        raise MyAirError(category, "request") from None
    except ssl.SSLError:
        raise MyAirError(MyAirFailure.TLS, "request") from None
    except (TimeoutError, socket.timeout):
        raise MyAirError(MyAirFailure.TIMEOUT, "request") from None
    except OSError:
        raise MyAirError(MyAirFailure.NETWORK, "request") from None


class ResMedMyAirAdapter:
    """Authenticate and retrieve recent summaries without changing account state."""

    def __init__(
        self,
        username: str,
        password: str,
        *,
        mfa_code: str | None = None,
        mfa_code_provider: MfaCodeProvider | None = None,
        transport: Transport | None = None,
        today: Callable[[], date] | None = None,
    ) -> None:
        if not username or not password:
            raise ValueError("myAir username and password are required")
        self._username = username
        self._password = password
        self._mfa_code = mfa_code
        self._mfa_code_provider = mfa_code_provider
        self._transport = transport or _urlopen_transport
        self._today = today or date.today
        self._cookies: dict[str, str] = {}

    def fetch_range(self, start: date, end: date) -> list[NightlyRecord]:
        _validate_range(start, end)
        query_end = self._today()
        query_start = query_end - timedelta(days=30)
        if start < query_start or end > query_end:
            raise ValueError("myAir cloud summaries are limited to the most recent 31 days")

        access_token, id_token = self._authenticate()
        country = _country_from_id_token(id_token)
        query = SLEEP_QUERY.replace("ONE_MONTH_AGO", query_start.isoformat()).replace(
            "DATE", query_end.isoformat()
        )
        body = json.dumps(
            {"operationName": SLEEP_OPERATION, "variables": {}, "query": query}
        ).encode()
        headers = {
            "Content-Type": "application/json",
            "x-api-key": NORTH_AMERICA.myair_api_key,
            "Authorization": f"Bearer {access_token}",
            "rmdhandsetid": "02c1c662-c289-41fd-a9ae-196ff15b5166",
            "rmdlanguage": "en",
            "rmdhandsetmodel": "Chrome",
            "rmdhandsetosversion": "127.0.6533.119",
            "rmdproduct": NORTH_AMERICA.product,
            "rmdappversion": "1.0.0",
            "rmdhandsetplatform": "Web",
            "rmdcountry": country,
            "accept-language": "en-US,en;q=0.9",
        }
        request = Request(NORTH_AMERICA.graphql_url, data=body, headers=headers, method="POST")
        payload = self._json(self._send(request, "nightly data"), "nightly data")
        try:
            items = payload["data"]["getPatientWrapper"]["sleepRecords"]["items"]
        except (KeyError, TypeError):
            raise MyAirError(MyAirFailure.MALFORMED_RESPONSE, "nightly data") from None
        if not isinstance(items, list):
            raise MyAirError(MyAirFailure.MALFORMED_RESPONSE, "nightly data")
        records = [_normalize_record(item) for item in items]
        if any(record.night < query_start or record.night > query_end for record in records):
            raise MyAirError(MyAirFailure.MALFORMED_RESPONSE, "nightly data")
        return sorted(
            (record for record in records if start <= record.night <= end),
            key=lambda record: record.night,
        )

    def _authenticate(self) -> tuple[str, str]:
        # Prime only to acquire the remembered-device cookie; all statuses are tolerated.
        if "DT" not in self._cookies:
            try:
                response = self._transport(Request(
                    NORTH_AMERICA.authorize_url, headers=JSON_HEADERS, method="GET"
                ))
            except MyAirError as error:
                raise MyAirError(
                    error.category, "authentication", status=error.status
                ) from None
            self._capture_cookies(response)

        auth_request = self._json_request(
            NORTH_AMERICA.authn_url,
            {"username": self._username, "password": self._password},
        )
        auth_payload = self._json(
            self._send(auth_request, "authentication"), "authentication"
        )
        if not isinstance(auth_payload, dict):
            raise MyAirError(MyAirFailure.MALFORMED_RESPONSE, "authentication")
        status = auth_payload.get("status")
        if status == "SUCCESS":
            session_token = auth_payload.get("sessionToken")
        elif status == "MFA_REQUIRED":
            session_token = self._complete_mfa(auth_payload)
        else:
            raise MyAirError(MyAirFailure.MALFORMED_RESPONSE, "authentication")
        if not isinstance(session_token, str) or not session_token:
            raise MyAirError(MyAirFailure.MALFORMED_RESPONSE, "authentication")
        return self._oauth_tokens(session_token)

    def _complete_mfa(self, payload: dict[str, Any]) -> str:
        state_token = payload.get("stateToken")
        if not isinstance(state_token, str) or not state_token:
            raise MyAirError(MyAirFailure.MALFORMED_RESPONSE, "authentication")
        factor_id = NORTH_AMERICA.email_factor_id
        active_url: str | None = None
        try:
            factor = payload["_embedded"]["factors"][0]
            if isinstance(factor.get("id"), str) and factor["id"]:
                factor_id = factor["id"]
            href = factor["_links"]["verify"]["href"]
            if isinstance(href, str) and href:
                active_url = f"{href}?rememberDevice=true"
        except (KeyError, IndexError, TypeError):
            pass
        active_url = active_url or NORTH_AMERICA.mfa_url(factor_id)
        trigger = self._json_request(active_url, {"passCode": "", "stateToken": state_token})
        self._json(self._send(trigger, "MFA challenge"), "MFA challenge")
        mfa_code = self._mfa_code
        self._mfa_code = None
        if not mfa_code and self._mfa_code_provider is not None:
            try:
                mfa_code = self._mfa_code_provider()
            except Exception:
                # A provider may wrap terminal I/O; never retain its diagnostic text.
                raise MyAirError(MyAirFailure.MFA_REQUIRED, "authentication") from None
        if not isinstance(mfa_code, str) or not mfa_code:
            raise MyAirError(MyAirFailure.MFA_REQUIRED, "authentication")
        verify = self._json_request(
            active_url, {"passCode": mfa_code, "stateToken": state_token}
        )
        verified = self._json(self._send(verify, "MFA verification"), "MFA verification")
        if not isinstance(verified, dict) or verified.get("status") != "SUCCESS":
            raise MyAirError(MyAirFailure.CREDENTIAL_REJECTION, "MFA verification")
        session_token = verified.get("sessionToken")
        if not isinstance(session_token, str) or not session_token:
            raise MyAirError(MyAirFailure.MALFORMED_RESPONSE, "MFA verification")
        return session_token

    def _oauth_tokens(self, session_token: str) -> tuple[str, str]:
        verifier, challenge = _pkce_pair()
        params = urlencode({
            "client_id": NORTH_AMERICA.authorize_client_id,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "prompt": "none",
            "redirect_uri": NORTH_AMERICA.oauth_redirect_url,
            "response_mode": "fragment",
            "response_type": "code",
            "sessionToken": session_token,
            "scope": "openid profile email",
            "state": "abcdef",
        })
        response = self._send(
            Request(f"{NORTH_AMERICA.authorize_url}?{params}", headers=self._headers(JSON_HEADERS)),
            "authorization",
            allowed_statuses={302},
        )
        self._capture_cookies(response)
        locations = response.header_values("Location")
        if not locations:
            raise MyAirError(MyAirFailure.MALFORMED_RESPONSE, "authorization")
        codes = parse_qs(urldefrag(locations[0]).fragment).get("code", [])
        if not codes:
            raise MyAirError(MyAirFailure.MALFORMED_RESPONSE, "authorization")
        form = urlencode({
            "client_id": NORTH_AMERICA.authorize_client_id,
            "redirect_uri": NORTH_AMERICA.oauth_redirect_url,
            "grant_type": "authorization_code",
            "code_verifier": verifier,
            "code": codes[0],
        }).encode()
        token_request = Request(
            NORTH_AMERICA.token_url,
            data=form,
            headers=self._headers({
                "Accept": "application/json",
                "Content-Type": "application/x-www-form-urlencoded",
            }),
            method="POST",
        )
        payload = self._json(self._send(token_request, "token exchange"), "token exchange")
        access = payload.get("access_token") if isinstance(payload, dict) else None
        identity = payload.get("id_token") if isinstance(payload, dict) else None
        if not isinstance(access, str) or not access or not isinstance(identity, str) or not identity:
            raise MyAirError(MyAirFailure.MALFORMED_RESPONSE, "token exchange")
        return access, identity

    def _json_request(self, url: str, payload: dict[str, str]) -> Request:
        return Request(
            url,
            data=json.dumps(payload).encode(),
            headers=self._headers(JSON_HEADERS),
            method="POST",
        )

    def _headers(self, headers: dict[str, str]) -> dict[str, str]:
        result = dict(headers)
        if self._cookies:
            result["Cookie"] = "; ".join(f"{key}={value}" for key, value in self._cookies.items())
        return result

    def _capture_cookies(self, response: _Response) -> None:
        for raw in response.header_values("Set-Cookie"):
            cookie = SimpleCookie()
            try:
                cookie.load(raw)
            except Exception:  # Cookie parsing fails closed without exposing the value.
                continue
            for name in ("DT", "sid"):
                if name in cookie:
                    self._cookies[name] = cookie[name].value

    def _send(
        self, request: Request, operation: str, *, allowed_statuses: set[int] | None = None
    ) -> _Response:
        try:
            response = self._transport(request)
        except MyAirError as error:
            raise MyAirError(error.category, operation, status=error.status) from None
        self._capture_cookies(response)
        if response.status in (allowed_statuses or set()):
            return response
        if not 200 <= response.status < 300:
            category = (
                MyAirFailure.CREDENTIAL_REJECTION
                if operation in {"authentication", "MFA verification", "token exchange"}
                and response.status in {400, 401, 403}
                else MyAirFailure.HTTP_STATUS
            )
            raise MyAirError(category, operation, status=response.status)
        return response

    @staticmethod
    def _json(response: _Response, operation: str) -> Any:
        if len(response.body) > MAX_RESPONSE_BYTES:
            raise MyAirError(MyAirFailure.RESPONSE_TOO_LARGE, operation)
        try:
            return json.loads(response.body)
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise MyAirError(MyAirFailure.MALFORMED_RESPONSE, operation) from None


def _pkce_pair() -> tuple[str, str]:
    verifier = base64.urlsafe_b64encode(os.urandom(40)).decode("utf-8")
    verifier = re.sub("[^a-zA-Z0-9]+", "", verifier)
    digest = hashlib.sha256(verifier.encode("utf-8")).digest()
    challenge = base64.urlsafe_b64encode(digest).decode("utf-8").replace("=", "")
    return verifier, challenge


def _country_from_id_token(id_token: str) -> str:
    try:
        parts = id_token.split(".")
        if len(parts) != 3:
            raise ValueError
        payload = parts[1] + "=" * (-len(parts[1]) % 4)
        claims = json.loads(base64.urlsafe_b64decode(payload))
        if not isinstance(claims, dict):
            raise ValueError
        country = claims.get("myAirCountryId")
        if not isinstance(country, str) or not country:
            raise ValueError
        return country
    except (
        ValueError,
        binascii.Error,
        UnicodeDecodeError,
        json.JSONDecodeError,
        TypeError,
    ):
        raise MyAirError(MyAirFailure.MALFORMED_RESPONSE, "authentication") from None


def _validate_range(start: date, end: date) -> None:
    if start > end:
        raise ValueError("start must be on or before end")
    if (end - start).days + 1 > MAX_FETCH_DAYS:
        raise ValueError(f"myAir date range must not exceed {MAX_FETCH_DAYS} days")


def _normalize_record(value: Any) -> NightlyRecord:
    if not isinstance(value, dict):
        raise MyAirError(MyAirFailure.MALFORMED_RESPONSE, "nightly data")
    try:
        raw_usage = value["totalUsage"]
        if isinstance(raw_usage, bool):
            raise ValueError
        usage = raw_usage if isinstance(raw_usage, int) else int(Decimal(str(raw_usage)))
        return NightlyRecord(
            night=str(value["startDate"]),
            usage_minutes=usage,
            ahi=_optional_number(value.get("ahi")),
            leak_95_lpm=None,
            pressure_95_cmh2o=None,
            source="myair",
        )
    except (KeyError, TypeError, ValueError, OverflowError, InvalidOperation):
        raise MyAirError(MyAirFailure.MALFORMED_RESPONSE, "nightly data") from None


def _optional_number(value: Any) -> float | None:
    return None if value is None else float(value)


def ingest_myair(adapter: MyAirAdapter, store: Any, start: date, end: date) -> int:
    """Fetch a bounded range and persist only normalized summary records."""
    records = adapter.fetch_range(start, end)
    for record in records:
        store.upsert(record)
    return len(records)
