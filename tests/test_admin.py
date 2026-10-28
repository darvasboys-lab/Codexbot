import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from codexbot.admin import main
from codexbot.persistence import SQLiteJournal

NOW = datetime(2026, 10, 28, 4, 0, tzinfo=UTC)


def test_new_database_fails_closed_with_emergency_stop_engaged(tmp_path: Path) -> None:
    journal = SQLiteJournal(tmp_path / "codexbot.sqlite3", clock=lambda: NOW)
    journal.initialize()

    status = journal.emergency_stop_status()

    assert status.engaged is True
    assert status.new_entries_allowed is False
    assert status.reason == "NO_RELEASE_RECORDED"
    assert status.event_id is None


def test_emergency_stop_history_is_append_only_and_audited(tmp_path: Path) -> None:
    database = tmp_path / "codexbot.sqlite3"
    journal = SQLiteJournal(database, clock=lambda: NOW)
    journal.initialize()

    released = journal.set_emergency_stop(
        engaged=False, reason="operator completed startup checks", actor="local-user:udit:uid:1000"
    )
    engaged = journal.set_emergency_stop(
        engaged=True, reason="broker health failed", actor="local-user:udit:uid:1000"
    )

    assert released.new_entries_allowed is True
    assert engaged.new_entries_allowed is False
    assert journal.emergency_stop_status() == engaged
    with sqlite3.connect(database) as connection:
        rows = connection.execute(
            "SELECT engaged, reason FROM runtime_control_events ORDER BY id"
        ).fetchall()
        audit_rows = connection.execute(
            "SELECT state FROM audit_events WHERE event_type = 'EMERGENCY_STOP_CHANGED' ORDER BY id"
        ).fetchall()
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute("DELETE FROM runtime_control_events")
    assert rows == [(0, "operator completed startup checks"), (1, "broker health failed")]
    assert audit_rows == [("RELEASED",), ("ENGAGED",)]


@pytest.mark.parametrize("reason", ["", " ", "x" * 501])
def test_emergency_stop_rejects_missing_or_oversized_reason(tmp_path: Path, reason: str) -> None:
    journal = SQLiteJournal(tmp_path / "codexbot.sqlite3", clock=lambda: NOW)
    journal.initialize()

    with pytest.raises(ValueError):
        journal.set_emergency_stop(engaged=True, reason=reason, actor="operator")


def test_admin_cli_changes_and_displays_durable_stop(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    database = tmp_path / "codexbot.sqlite3"

    assert (
        main(
            [
                "emergency-stop",
                "--database",
                str(database),
                "release",
                "--reason",
                "TEST observation approved",
            ]
        )
        == 0
    )
    released = json.loads(capsys.readouterr().out)
    assert released["emergency_stop"] == "RELEASED"
    assert released["new_entries_allowed"] is True
    assert released["position_management"] == "MUST_CONTINUE"

    assert (
        main(
            [
                "emergency-stop",
                "--database",
                str(database),
                "engage",
                "--reason",
                "manual safety stop",
            ]
        )
        == 0
    )
    engaged = json.loads(capsys.readouterr().out)
    assert engaged["emergency_stop"] == "ENGAGED"
    assert engaged["new_entries_allowed"] is False
    assert engaged["pending_entry_cancellation"] == "REQUIRED_WHEN_PENDING_ENTRIES_EXIST"
