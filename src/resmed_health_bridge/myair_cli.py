"""Explicit, bounded command for importing read-only myAir summaries."""

import argparse
from datetime import date
import getpass
import os
import sys
import warnings

from .adapters.myair import ResMedMyAirAdapter, ingest_myair
from .config import Settings
from .storage import NightlyStore


def _read_mfa_code() -> str:
    """Read a transient MFA code without echoing it or requiring a second process."""
    configured = os.environ.get("MYAIR_MFA_CODE")
    if configured:
        return configured
    if not sys.stdin.isatty():
        return ""
    # getpass can otherwise warn and fall back to echoed stdin when secure terminal
    # control fails. Treat that warning as an error; the adapter sanitizes provider
    # failures to ``mfa_required``.
    with warnings.catch_warnings():
        warnings.simplefilter("error", getpass.GetPassWarning)
        return getpass.getpass("myAir email verification code: ")


def main() -> None:
    parser = argparse.ArgumentParser(description="Import a bounded range from myAir")
    parser.add_argument("start", type=date.fromisoformat, help="first night (YYYY-MM-DD)")
    parser.add_argument("end", type=date.fromisoformat, help="last night (YYYY-MM-DD)")
    args = parser.parse_args()
    username = os.environ.get("MYAIR_USERNAME")
    password = os.environ.get("MYAIR_PASSWORD")
    if not username or not password:
        parser.error("MYAIR_USERNAME and MYAIR_PASSWORD must be set in the environment")

    store = NightlyStore(Settings.from_env().db_path)
    store.initialize()
    count = ingest_myair(
        ResMedMyAirAdapter(username, password, mfa_code_provider=_read_mfa_code),
        store,
        args.start,
        args.end,
    )
    print(f"Imported {count} nightly record(s) from myAir")


if __name__ == "__main__":
    main()
