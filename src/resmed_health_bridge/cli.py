"""Offline import command for OSCAR-compatible summary CSV files."""

import argparse

from .adapters.oscar import import_oscar_csv
from .config import Settings
from .storage import NightlyStore


def main() -> None:
    parser = argparse.ArgumentParser(description="Import an OSCAR-compatible summary CSV")
    parser.add_argument("csv", help="path to CSV (date, usage_minutes, optional metrics)")
    args = parser.parse_args()
    store = NightlyStore(Settings.from_env().db_path)
    store.initialize()
    records = import_oscar_csv(args.csv)
    for record in records:
        store.upsert(record)
    print(f"Imported {len(records)} nightly record(s)")


if __name__ == "__main__":
    main()
