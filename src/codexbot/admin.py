"""Local SSH administration for durable Codexbot safety controls."""

from __future__ import annotations

import argparse
import json
import os
import pwd
from collections.abc import Sequence
from datetime import date
from pathlib import Path

from codexbot.persistence import EmergencyStopStatus, SQLiteJournal
from codexbot.reporting import format_daily_summary


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    status_parser = subparsers.add_parser("status", help="show durable local runtime state")
    status_parser.add_argument("--database", type=Path, required=True)
    summary_parser = subparsers.add_parser(
        "daily-summary", help="show an audit-derived Asia/Kolkata service date"
    )
    summary_parser.add_argument("--database", type=Path, required=True)
    summary_parser.add_argument("--date", type=date.fromisoformat, required=True)
    stop_parser = subparsers.add_parser(
        "emergency-stop", help="inspect or change the durable new-entry gate"
    )
    stop_parser.add_argument("--database", type=Path, required=True)
    stop_subparsers = stop_parser.add_subparsers(dest="action", required=True)
    stop_subparsers.add_parser("status")
    engage_parser = stop_subparsers.add_parser("engage")
    engage_parser.add_argument("--reason", required=True)
    release_parser = stop_subparsers.add_parser("release")
    release_parser.add_argument("--reason", required=True)

    arguments = parser.parse_args(argv)
    journal = SQLiteJournal(arguments.database)
    journal.initialize()
    if arguments.command == "status":
        print(json.dumps(_system_status_payload(journal), sort_keys=True, separators=(",", ":")))
        return 0
    if arguments.command == "daily-summary":
        print(format_daily_summary(journal.daily_audit_summary(arguments.date)))
        return 0
    if arguments.command != "emergency-stop":
        parser.error("unknown command")
    if arguments.action == "status":
        status = journal.emergency_stop_status()
    elif arguments.action in {"engage", "release"}:
        status = journal.set_emergency_stop(
            engaged=arguments.action == "engage",
            reason=str(arguments.reason),
            actor=_local_actor(),
        )
    else:
        parser.error("unknown emergency-stop action")
    print(json.dumps(_status_payload(status), sort_keys=True, separators=(",", ":")))
    return 0


def _local_actor() -> str:
    uid = os.geteuid()
    try:
        username = pwd.getpwuid(uid).pw_name
    except KeyError:
        username = "unknown"
    return f"local-user:{username}:uid:{uid}"


def _status_payload(status: EmergencyStopStatus) -> dict[str, object]:
    return {
        "actor": status.actor,
        "changed_at": status.changed_at.isoformat() if status.changed_at else None,
        "emergency_stop": "ENGAGED" if status.engaged else "RELEASED",
        "event_id": status.event_id,
        "new_entries_allowed": status.new_entries_allowed,
        "pending_entry_cancellation": "REQUIRED_WHEN_PENDING_ENTRIES_EXIST"
        if status.engaged
        else "NOT_REQUESTED",
        "position_management": "MUST_CONTINUE",
        "reason": status.reason,
    }


def _system_status_payload(journal: SQLiteJournal) -> dict[str, object]:
    broker = journal.latest_broker_snapshot_status()
    return {
        "broker_snapshot": (
            {
                "completed_at": broker.completed_at.isoformat(),
                "order_count": broker.order_count,
                "position_count": broker.position_count,
                "recorded_at": broker.recorded_at.isoformat(),
                "snapshot_id": broker.snapshot_id,
                "trade_count": broker.trade_count,
            }
            if broker is not None
            else None
        ),
        "emergency_stop": _status_payload(journal.emergency_stop_status()),
        "journal_mode": journal.journal_mode(),
        "write_executor": "ABSENT",
    }


if __name__ == "__main__":
    raise SystemExit(main())
