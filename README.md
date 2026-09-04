# ResMed AirSense 11 Health-Data Bridge

A private, **read-only** Python MCP server for querying locally cached nightly CPAP
summary metrics. It is intended to give ChatGPT a small, auditable data boundary that
can later be combined with Apple Health and Withings data.

> This is an early scaffold, not a medical device and not medical advice. It does not
> control therapy, change settings, or write to a ResMed account/device.

## What is included

- Six query-only MCP tools: `get_last_night`, `get_therapy_range`, `get_ahi_trend`,
  `get_leak_trend`, `get_usage_trend`, and `get_pressure_summary`.
- A normalized nightly model and local SQLite cache.
- An offline CSV fallback for summary data derived from an AirSense 11 SD card via an
  OSCAR-compatible workflow.
- A bounded, explicit myAir importer using the unofficial read-only consumer API.
- Container configuration with a non-root user, dropped capabilities, read-only root
  filesystem, no network, and no published port.

The bridge stores date, usage minutes, AHI, 95th-percentile leak, 95th-percentile
pressure, and source. It intentionally does not store device serial numbers.

## Architecture

```text
OSCAR-compatible CSV --> adapters/oscar.py --\
                                               > NightlyStore (SQLite) --> TherapyQueries --> MCP
unofficial myAir --------> adapters/myair.py -/
```

`myAir` access is unofficial, reverse-engineered, and unstable. ResMed does not provide a
documented public consumer API contract used by this project, and the integration may
break without notice. The adapter is an independent implementation based on a
2026-09-03 review of the MIT-licensed `prestomation/resmed_myair_sensors` region,
authentication, GraphQL transport, REST-client/query, and model sources. The reviewed
North America flow uses Okta authentication, optional email MFA, OAuth Authorization
Code with PKCE, and a fixed read-only GraphQL sleep-record operation. No third-party
source was copied. All upstream hosts, paths, metadata, and the GraphQL document are
fixed in `adapters/myair.py`; callers cannot supply a region, origin, arbitrary endpoint,
or query. No unverified Europe or Australia configuration is included.

## Setup

Requirements: Python 3.11+.

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'
cp .env.example .env
```

On POSIX systems, storage initialization rejects a pre-existing database directory
that is accessible by group or other users, then enforces mode `0700` on the directory
and `0600` on the database. Windows access is governed by ACLs rather than POSIX mode
bits, so the bridge preserves the directory's inherited ACL instead of applying or
rejecting meaningless numeric modes. Put the database beneath a private per-user
directory (for example, `%LOCALAPPDATA%`) and restrict its ACL to the account running
the bridge. Symbolic-link checks and SQLite sidecar protections apply on every platform.

`.env` is ignored by Git. The application reads configuration from the process
environment; it does not parse `.env` itself. Export variables manually or use a trusted
secret manager/process supervisor.

### Import myAir summaries (unofficial)

The command performs the North America Okta/PKCE flow followed by one read-only GraphQL
nightly-summary request. It neither calls the separate device query nor discovers or
stores a device serial number. Input ranges remain bounded to 366 inclusive days; the
current cloud operation exposes only the most recent 31 calendar days and rejects a
requested date outside that window. Responses are limited to 2 MiB. Only date, usage in
whole minutes, and AHI are retained. The verified summary semantics do not establish a
95th-percentile leak in L/min and expose no pressure statistic, so both normalized fields
remain null.

```bash
export RESMED_DB_PATH="$HOME/.local/share/resmed-bridge/resmed.sqlite3"
export MYAIR_USERNAME='your account email'
export MYAIR_PASSWORD='read from your secret manager'
resmed-import-myair 2026-09-03 2026-09-03
unset MYAIR_USERNAME MYAIR_PASSWORD
```

On Windows, a safe single-night smoke test is:

```powershell
.\.venv\Scripts\resmed-import-myair.exe 2026-09-03 2026-09-03
```

If Okta requires email MFA, the importer triggers the email challenge and then securely
prompts for its verification code in the same process. Terminal input is not echoed, and
the in-memory Okta transaction state is used continuously from challenge through
verification. For controlled noninteractive use, the short-lived `MYAIR_MFA_CODE`
environment variable remains supported; remove it immediately afterward. If neither a
secure terminal nor that variable is available, the importer fails with the sanitized
`mfa_required` category instead of attempting echoed input or starting another session.

Credentials and bearer tokens are held only in memory. They are not written to SQLite
or included in adapter errors. Avoid shell history for literal secrets and do not enable
HTTP debug logging or capture raw upstream traffic.

Authentication and transport errors expose only a stable category and, when an HTTP
response was received, its numeric status. Categories distinguish credential rejection
(`401` during authentication), other HTTP status, DNS, TLS, timeout, other network,
oversize response, and malformed JSON/response shape. Upstream error bodies and exception
details are discarded. An HTTP status alone is not treated as proof of a region/origin
problem; without a documented status mapping that would be a guess.

For support, do not enable HTTP debugging, capture traffic, or share request headers,
cookies, redirects, tokens, MFA codes, or response bodies. Share only the sanitized
failure category and optional numeric HTTP status printed by the failure.

### Import SD-card / OSCAR-compatible data

Export or produce a summary CSV with these headers:

```csv
date,usage_minutes,ahi,leak_95_lpm,pressure_95_cmh2o
2026-01-03,390,1.5,7.2,9.8
```

Only `date` and `usage_minutes` are required. The other fields may be blank. Use a copy
of an export, not the mounted SD card itself:

```bash
export RESMED_DB_PATH="$HOME/.local/share/resmed-bridge/resmed.sqlite3"
install -d -m 0700 "$(dirname "$RESMED_DB_PATH")"
resmed-import-oscar /private/path/to/summary.csv
```

CSV layouts vary between OSCAR versions and locales. This first-pass importer accepts
the explicit normalized schema above rather than pretending every raw OSCAR export has
a stable layout. Raw EDF parsing is out of scope.

## Run locally

For a local MCP client using stdio:

```bash
export RESMED_DB_PATH="$HOME/.local/share/resmed-bridge/resmed.sqlite3"
install -d -m 0700 "$(dirname "$RESMED_DB_PATH")"
export RESMED_MCP_TRANSPORT=stdio
resmed-health-bridge
```

Configure the client to execute `resmed-health-bridge`. Query ranges are limited to 366
days/results. For local HTTP development only:

```bash
export RESMED_MCP_TRANSPORT=streamable-http
export RESMED_MCP_HOST=127.0.0.1
resmed-health-bridge
```

Non-loopback HTTP hosts (including `0.0.0.0`) are rejected. There is no override. HTTP
must remain local until authenticated TLS is implemented and reviewed.

## Docker

```bash
docker compose build
docker compose config --quiet
# Run an MCP stdio session attached to a local client:
docker compose run --rm -T bridge
```

Compose publishes no port and disables networking for the runtime container. The named
volume contains sensitive health data; include it in encrypted backups only and apply a
suitable retention/deletion policy. Import data through a separately controlled offline
workflow; no raw export directory is mounted by default.

## Secure remote deployment

Remote MCP deployment is intentionally unavailable in this scaffold. The application
does not implement authentication or TLS and rejects non-loopback HTTP binding. Do not
work around that check or expose port 8000. Before remote ChatGPT access is enabled in a
future reviewed change:

1. Deploy on a private host/network with an encrypted disk and restricted operator access.
2. Keep the application port private. Put a well-maintained gateway or zero-trust tunnel
   in front that provides TLS, strong per-user authentication, authorization, rate
   limiting, and request-size/time limits.
3. Store gateway and future upstream credentials in a secret manager, injected as
   environment variables—not in Compose files, images, source control, URLs, or logs.
4. Permit only the MCP route and expected clients. Review gateway access logs, while
   ensuring bodies, tool arguments, authorization headers, and responses are redacted.
5. Validate your MCP client's current remote-server requirements before deployment.

Transport encryption protects data in transit; SQLite itself is not encrypted. Use
full-disk/volume encryption, restrictive filesystem permissions, encrypted backups,
and host-level access controls for data at rest.

## Security and privacy model

- All therapy tools query cached data only. There are no therapy-setting mutations,
  device writes, account writes, or generic SQL/network tools.
- Credentials are environment-only. Application code intentionally does not log
  credentials, tokens, serial numbers, records, tool arguments, or responses.
- Imported CSVs, SQLite volumes, backups, MCP responses, and dates are sensitive health
  data. Do not commit them or use real records in tests/support requests.
- Prefer short retention, least privilege, a dedicated service identity, patched
  dependencies, and authenticated encrypted connections.
- MCP tool output is data, not diagnosis. Clinical decisions belong with a qualified
  clinician and the original device reports.

## Known limitations

- myAir is unofficial, can change without notice, supports only the verified North
  America Okta/GraphQL configuration, and has no live-account integration test in CI.
- The myAir summary response does not provide 95th-percentile leak or pressure, so those
  normalized fields are null for myAir records. Score and mask-fit fields are deliberately
  not retained by the current domain model.
- No automatic sync scheduler, conflict provenance beyond `source`, pagination, timezone
  normalization, multi-user tenancy, or database encryption is provided.
- A "night" is the date supplied by the import source. Day-boundary and timezone behavior
  must be normalized by a future validated adapter.
- The importer handles a documented normalized CSV subset, not arbitrary OSCAR reports or
  raw ResMed EDF files.
- Summary metrics may differ from clinician software and should not be treated as a
  clinical record.
- HTTP authentication/TLS must be supplied by deployment infrastructure.
- MCP range queries are capped at 366 nights. CSV input is streamed and capped at 10 MiB
  and 10,000 rows to constrain accidental bulk processing and memory use.

## Development and tests

Tests use synthetic records only:

```bash
pytest
docker compose config --quiet
docker build -t resmed-health-bridge:test .
```

CI installs the pinned MCP SDK, exercises the real server/tool registry, calls all six
tools with synthetic data, compiles Python sources, validates Compose, and builds the
image. Keep all MCP additions query-only. See `AGENTS.md` before making changes.
