"""Command-line maintenance for the Codexbot SQLite journal."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from codexbot.persistence import backup_database, integrity_check, restore_test


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
    parser.error("unknown command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
