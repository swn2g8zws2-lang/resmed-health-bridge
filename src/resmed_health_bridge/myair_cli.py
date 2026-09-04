"""Explicit, bounded command for importing read-only myAir summaries."""

import argparse
from datetime import date
import os

from .adapters.myair import ResMedMyAirAdapter, ingest_myair
from .config import Settings
from .storage import NightlyStore


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
    count = ingest_myair(ResMedMyAirAdapter(username, password), store, args.start, args.end)
    print(f"Imported {count} nightly record(s) from myAir")


if __name__ == "__main__":
    main()
