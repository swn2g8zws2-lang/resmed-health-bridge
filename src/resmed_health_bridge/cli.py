"""Offline import command for OSCAR-compatible summary CSV files."""

import argparse

from .adapters.oscar import iter_oscar_csv
from .config import Settings
from .storage import NightlyStore


def main() -> None:
    parser = argparse.ArgumentParser(description="Import an OSCAR-compatible summary CSV")
    parser.add_argument("csv", help="path to CSV (date, usage_minutes, optional metrics)")
    args = parser.parse_args()
    store = NightlyStore(Settings.from_env().db_path)
    store.initialize()
    count = 0
    for record in iter_oscar_csv(args.csv):
        store.upsert(record)
        count += 1
    print(f"Imported {count} nightly record(s)")


if __name__ == "__main__":
    main()
