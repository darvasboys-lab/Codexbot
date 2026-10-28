"""Command-line maintenance for the Codexbot SQLite journal."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from codexbot.persistence import backup_database, integrity_check, restore_test
from codexbot.recovery import inspect_unfinished_receipts


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    integrity_parser = subparsers.add_parser("integrity", help="run PRAGMA integrity_check")
    integrity_parser.add_argument("--database", type=Path, required=True)

    backup_parser = subparsers.add_parser("backup", help="create a consistent backup")
    backup_parser.add_argument("--database", type=Path, required=True)
    backup_parser.add_argument("--output", type=Path, required=True)

    restore_parser = subparsers.add_parser(
        "restore-test", help="restore a backup temporarily and verify it"
    )
    restore_parser.add_argument("--backup", type=Path, required=True)

    unfinished_parser = subparsers.add_parser(
        "unfinished", help="read-only report of receipts missing a final check"
    )
    unfinished_parser.add_argument("--database", type=Path, required=True)
    unfinished_parser.add_argument("--limit", type=int, default=50)

    arguments = parser.parse_args(argv)
    if arguments.command == "integrity":
        results = integrity_check(arguments.database)
        print("\n".join(results))
        return 0 if results == ("ok",) else 1
    if arguments.command == "backup":
        output = backup_database(arguments.database, arguments.output)
        print(output)
        return 0
    if arguments.command == "restore-test":
        results = restore_test(arguments.backup)
        print("\n".join(results))
        return 0 if results == ("ok",) else 1
    if arguments.command == "unfinished":
        report = inspect_unfinished_receipts(arguments.database, limit=arguments.limit)
        print(f"unfinished_receipts={report.total}")
        for receipt in report.receipts:
            print(
                f"receipt_id={receipt.receipt_id} "
                f"group_id={receipt.source_group_id} "
                f"message_id={receipt.telegram_message_id} "
                f"first_durable_received_at={receipt.first_durable_received_at} "
                f"last_processing_event={receipt.last_processing_event or 'NONE'} "
                f"option_decision_recorded={str(receipt.option_decision_recorded).lower()}"
            )
        print(f"truncated={str(report.truncated).lower()}")
        return 1 if report.total else 0
    parser.error("unknown command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
