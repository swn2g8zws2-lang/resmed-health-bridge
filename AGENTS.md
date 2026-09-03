# AGENTS.md

## Project invariants

This repository handles sensitive health data. Future changes must preserve these constraints:

- The bridge is private and read-only. Never add functions that change CPAP therapy settings or write to a CPAP device/account.
- Keep unofficial myAir access isolated in `src/resmed_health_bridge/adapters/myair.py`; do not invent undocumented endpoints.
- Inspect and record the license before using or copying third-party ResMed integration code. Prefer clean implementations and adapters.
- Credentials and secrets must come only from environment variables. Never commit real credentials, tokens, serial numbers, exports, or health data.
- Never log usernames, passwords, tokens, device serial numbers, raw authorization headers, or patient data.
- Treat database files and imported records as sensitive health data. Use synthetic data only in tests.
- Keep SD-card/OSCAR-compatible import separate from network adapters.
- MCP tools must remain query-only.
- Add tests for behavior and security-sensitive changes, and keep documentation and `.env.example` current.
- Keep the MCP runtime dependency pinned and test the real tool registry and schemas; exactly six query tools are allowed unless a reviewed requirement changes that inventory.
- Remote HTTP is disabled: never permit a non-loopback bind until authenticated TLS and access controls are implemented and security-reviewed.
- Keep MCP ranges and imports explicitly bounded. Preserve `0700` database-directory and `0600` database-file permissions, and avoid persistent SQLite WAL/shared-memory sidecars.
- Extend ignore and CI checks when new secret names, health-data formats, or deployment paths are introduced.
