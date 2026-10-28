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


def test_admin_status_is_read_only_summary_without_fake_portfolio(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    database = tmp_path / "codexbot.sqlite3"

    assert main(["status", "--database", str(database)]) == 0

    status = json.loads(capsys.readouterr().out)
    assert status["journal_mode"] == "wal"
    assert status["write_executor"] == "ABSENT"
    assert status["broker_snapshot"] is None
    assert status["emergency_stop"]["emergency_stop"] == "ENGAGED"
    assert "simulated" not in json.dumps(status).lower()


def test_admin_daily_summary_uses_requested_service_date(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    database = tmp_path / "codexbot.sqlite3"
    journal = SQLiteJournal(database, clock=lambda: NOW)
    journal.initialize()
    journal.append_audit_event(
        event_type="SIGNAL_RECEIVED",
        entity_type="signal_receipt",
        entity_id="1",
        state="DURABLE",
        occurred_at=NOW,
    )

    assert (
        main(
            [
                "daily-summary",
                "--database",
                str(database),
                "--date",
                "2026-10-28",
            ]
        )
        == 0
    )

    output = capsys.readouterr().out
    assert "DAILY SUMMARY 2026-10-28 Asia/Kolkata" in output
    assert "Signals received: 1" in output
    assert "Simulated orders/fills/holdings: NEVER CREATED" in output


def test_admin_feedback_history_shows_pending_review_without_applying_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    database = tmp_path / "codexbot.sqlite3"
    journal = SQLiteJournal(database, clock=lambda: NOW)
    journal.initialize()
    journal.record_signal_receipt(
        source_group_id=-1001,
        telegram_message_id=42,
        sent_at=NOW,
    )
    journal.record_operator_feedback(
        source_group_id=-1001,
        source_telegram_message_id=42,
        feedback_group_id=-9001,
        feedback_telegram_message_id=77,
        operator_id=3001,
        feedback_text="review parser classification",
    )

    assert main(["feedback-history", "--database", str(database), "--limit", "5"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload == [
        {
            "feedback_id": 1,
            "feedback_text": "review parser classification",
            "operator_id": 3001,
            "received_at": NOW.isoformat(),
            "signal": "-1001:42",
            "status": "PENDING_REVIEW",
        }
    ]


def test_admin_calendar_override_open_status_and_clear(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    database = tmp_path / "codexbot.sqlite3"
    common = [
        "calendar-override",
        "--database",
        str(database),
        "--date",
        "2026-11-08",
        "--segment",
        "NSE_CM",
    ]

    assert main([*common, "open", "--reason", "official special session"]) == 0
    opened = json.loads(capsys.readouterr().out)
    assert opened["enabled"] is True
    assert opened["segment"] == "NSE_CM"
    assert main([*common, "status"]) == 0
    assert json.loads(capsys.readouterr().out)["enabled"] is True
    assert main([*common, "clear", "--reason", "session finished"]) == 0
    assert json.loads(capsys.readouterr().out)["enabled"] is False


def test_admin_audit_history_is_bounded_and_structured(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    database = tmp_path / "codexbot.sqlite3"
    journal = SQLiteJournal(database, clock=lambda: NOW)
    journal.initialize()
    journal.append_audit_event(
        event_type="SYSTEM_TEST",
        entity_type="system",
        entity_id=None,
        state="OK",
        details={"safe": True},
    )

    assert (
        main(
            [
                "audit-history",
                "--database",
                str(database),
                "--event-type",
                "SYSTEM_TEST",
                "--limit",
                "1",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload[0]["details"] == {"safe": True}
    assert payload[0]["event_type"] == "SYSTEM_TEST"
