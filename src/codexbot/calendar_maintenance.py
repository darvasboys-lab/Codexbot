"""Maintain the credential-free official NSE trading-calendar cache."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from datetime import timedelta
from pathlib import Path

from codexbot.calendar_cache import NSECalendarCache


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    refresh = subparsers.add_parser("refresh")
    refresh.add_argument("--cache", type=Path, required=True)
    status = subparsers.add_parser("status")
    status.add_argument("--cache", type=Path, required=True)
    status.add_argument("--max-age-seconds", type=int, required=True)
    arguments = parser.parse_args(argv)

    cache = NSECalendarCache(arguments.cache)
    if arguments.command == "refresh":
        snapshot = cache.refresh()
    else:
        snapshot = cache.load(maximum_age=timedelta(seconds=arguments.max_age_seconds))
    print(
        json.dumps(
            {
                "cash_holiday_count": len(snapshot.cash_holidays),
                "fetched_at": snapshot.fetched_at.isoformat(),
                "fno_holiday_count": len(snapshot.fno_holidays),
                "source_url": snapshot.source_url,
                "year": snapshot.year,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
