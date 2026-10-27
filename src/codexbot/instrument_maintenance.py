"""Command-line maintenance for the Dhan instrument-master cache."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path

from codexbot.instrument_cache import DhanInstrumentMasterCache


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-directory", type=Path, required=True)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("refresh", help="download, validate, and activate a snapshot")
    status_parser = subparsers.add_parser("status", help="verify active snapshot freshness")
    status_parser.add_argument("--maximum-age-hours", type=float, required=True)
    prune_parser = subparsers.add_parser("prune", help="remove inactive old snapshots")
    prune_parser.add_argument("--keep", type=int, default=2)
    arguments = parser.parse_args(argv)

    cache = DhanInstrumentMasterCache(arguments.cache_directory)
    if arguments.command == "refresh":
        snapshot = cache.refresh()
        print(snapshot.sha256, snapshot.byte_count, snapshot.downloaded_at.isoformat())
        return 0
    if arguments.command == "status":
        if arguments.maximum_age_hours < 0:
            parser.error("--maximum-age-hours cannot be negative")
        loaded = cache.load(
            maximum_age=timedelta(hours=arguments.maximum_age_hours),
            now=datetime.now(UTC),
        )
        snapshot = loaded.snapshot
        print(snapshot.sha256, snapshot.byte_count, snapshot.downloaded_at.isoformat())
        return 0
    if arguments.command == "prune":
        removed = cache.prune(keep=arguments.keep)
        for path in removed:
            print(path)
        return 0
    parser.error("unknown command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
