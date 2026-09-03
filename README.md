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
- A deliberately unimplemented myAir adapter boundary.
- Container configuration with a non-root user, dropped capabilities, read-only root
  filesystem, and a loopback-only published port.

The bridge stores date, usage minutes, AHI, 95th-percentile leak, 95th-percentile
pressure, and source. It intentionally does not store device serial numbers.

## Architecture

```text
OSCAR-compatible CSV --> adapters/oscar.py --\
                                               > NightlyStore (SQLite) --> TherapyQueries --> MCP
future unofficial myAir --> adapters/myair.py -/
```

`myAir` access is unofficial and unstable. ResMed does not provide a documented public
consumer API contract used by this project. Consequently, the scaffold does **not**
invent URLs, authentication flows, or response schemas. `UnavailableMyAirAdapter`
fails explicitly. Before implementing it, validate current terms and behavior, inspect
the license of every third-party project considered, and implement against the local
read-only adapter contract. No open-source ResMed integration code has been copied into
this repository.

## Setup

Requirements: Python 3.11+.

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'
cp .env.example .env
```

`.env` is ignored by Git. The application reads configuration from the process
environment; it does not parse `.env` itself. Export variables manually or use a trusted
secret manager/process supervisor. `MYAIR_*` placeholders are reserved for a future
adapter and are not currently consumed.

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
resmed-import-oscar /private/path/to/summary.csv
```

CSV layouts vary between OSCAR versions and locales. This first-pass importer accepts
the explicit normalized schema above rather than pretending every raw OSCAR export has
a stable layout. Raw EDF parsing is out of scope.

## Run locally

For a local MCP client using stdio:

```bash
export RESMED_DB_PATH="$HOME/.local/share/resmed-bridge/resmed.sqlite3"
export RESMED_MCP_TRANSPORT=stdio
resmed-health-bridge
```

Configure the client to execute `resmed-health-bridge`. For local HTTP development:

```bash
export RESMED_MCP_TRANSPORT=streamable-http
export RESMED_MCP_HOST=127.0.0.1
resmed-health-bridge
```

## Docker

```bash
docker compose build
mkdir -p private-import
# Import files through a separately controlled local workflow, then:
docker compose up -d
```

The Compose port is published only on `127.0.0.1:8000`. The named volume contains
sensitive health data; include it in encrypted backups only and apply a suitable
retention/deletion policy.

## Secure remote deployment

The MCP application does not implement authentication or TLS. **Never expose port 8000
directly to the internet.** For remote ChatGPT access:

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

- There is no functioning myAir network integration; the isolated adapter documents the
  intended read-only boundary and fails closed.
- No automatic sync scheduler, conflict provenance beyond `source`, pagination, timezone
  normalization, multi-user tenancy, or database encryption is provided.
- A "night" is the date supplied by the import source. Day-boundary and timezone behavior
  must be normalized by a future validated adapter.
- The importer handles a documented normalized CSV subset, not arbitrary OSCAR reports or
  raw ResMed EDF files.
- Summary metrics may differ from clinician software and should not be treated as a
  clinical record.
- HTTP authentication/TLS must be supplied by deployment infrastructure.

## Development and tests

Tests use synthetic records only:

```bash
pytest
```

Keep all MCP additions query-only. See `AGENTS.md` before making changes.
