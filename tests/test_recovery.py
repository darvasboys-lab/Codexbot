"""Tests for read-only restart inspection; no broker or replay behavior."""

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from codexbot.db_maintenance import main
from codexbot.persistence import SQLiteJournal
from codexbot.recovery import inspect_unfinished_receipts

NOW = datetime(2026, 10, 28, 1, 0, tzinfo=UTC)


def _journal(path: Path) -> SQLiteJournal:
    journal = SQLiteJournal(path, clock=lambda: NOW)
    journal.initialize()
    return journal


def test_empty_journal_has_no_unfinished_receipts(tmp_path: Path) -> None:
    path = tmp_path / "journal.sqlite3"
    _journal(path)
    report = inspect_unfinished_receipts(path)
    assert report.total == 0
    assert report.receipts == ()
    assert not report.truncated


def test_receipt_without_final_check_is_visible_after_restart(tmp_path: Path) -> None:
    path = tmp_path / "journal.sqlite3"
    journal = _journal(path)
    first = journal.record_signal_receipt(
        source_group_id=1001, telegram_message_id=9, sent_at=NOW
    )
    journal.append_audit_event(
        event_type="SIGNAL_PARSED",
        entity_type="signal_receipt",
        entity_id=str(first.id),
        state="BUY",
    )
    journal.record_signal_receipt(
        source_group_id=1001,
        telegram_message_id=9,
        sent_at=NOW + timedelta(seconds=30),
    )

    # Inspection opens a separate read-only connection as after a restart.
    report = inspect_unfinished_receipts(path)
    assert report.total == 1
    assert len(report.receipts) == 1
    item = report.receipts[0]
    assert item.receipt_id == first.id
    assert item.source_group_id == 1001
    assert item.telegram_message_id == 9
    assert item.last_processing_event == "SIGNAL_PARSED"
    assert not item.option_decision_recorded

    journal.append_audit_event(
        event_type="SIGNAL_CHECKED",
        entity_type="signal_receipt",
        entity_id=str(first.id),
        state="REJECTED",
    )
    assert inspect_unfinished_receipts(path).total == 0


def test_option_claim_without_final_check_is_flagged(tmp_path: Path) -> None:
    path = tmp_path / "journal.sqlite3"
    journal = _journal(path)
    receipt = journal.record_signal_receipt(
        source_group_id=1001, telegram_message_id=3, sent_at=NOW
    )
    journal.claim_stock_option_signal(
        receipt_id=receipt.id, canonical_underlying_id="UNDERLYING-1"
    )

    report = inspect_unfinished_receipts(path)
    assert report.total == 1
    assert report.receipts[0].option_decision_recorded
    assert report.receipts[0].last_processing_event == "OPTION_DUPLICATE_CLAIMED"

    with sqlite3.connect(path) as connection:
        before = connection.execute(
            "SELECT COUNT(*) FROM option_duplicate_claims"
        ).fetchone()
    assert before == (1,)
    # Inspection did not create any new claim, decision, or audit event.
    with sqlite3.connect(path) as connection:
        after = connection.execute(
            "SELECT COUNT(*) FROM option_duplicate_claims"
        ).fetchone()
    assert after == before


def test_inspection_is_bounded_and_keeps_oldest_receipt_first(tmp_path: Path) -> None:
    path = tmp_path / "journal.sqlite3"
    journal = _journal(path)
    for message_id in (5, 6, 7):
        journal.record_signal_receipt(
            source_group_id=1001, telegram_message_id=message_id, sent_at=NOW
        )

    report = inspect_unfinished_receipts(path, limit=2)
    assert report.total == 3
    assert report.truncated
    assert [item.telegram_message_id for item in report.receipts] == [5, 6]


def test_missing_or_invalid_database_fails_closed(tmp_path: Path) -> None:
    missing = tmp_path / "missing.sqlite3"
    with pytest.raises(FileNotFoundError):
        inspect_unfinished_receipts(missing)
    assert not missing.exists()

    path = tmp_path / "invalid.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE unrelated (id INTEGER)")
    with pytest.raises(ValueError, match="missing journal tables"):
        inspect_unfinished_receipts(path)

    with pytest.raises(ValueError, match="limit"):
        inspect_unfinished_receipts(path, limit=0)
    with pytest.raises(ValueError, match="limit"):
        inspect_unfinished_receipts(path, limit=1001)


def test_symlink_database_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "journal.sqlite3"
    _journal(path)
    alias = tmp_path / "alias.sqlite3"
    alias.symlink_to(path)
    with pytest.raises(ValueError, match="symlink"):
        inspect_unfinished_receipts(alias)


def test_cli_unfinished_exit_status_and_no_payload(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "journal.sqlite3"
    journal = _journal(path)
    receipt = journal.record_signal_receipt(
        source_group_id=1001, telegram_message_id=12, sent_at=NOW
    )

    assert main(["unfinished", "--database", str(path), "--limit", "1"]) == 1
    output = capsys.readouterr().out
    assert "unfinished_receipts=1" in output
    assert f"receipt_id={receipt.id}" in output
    assert "message_id=12" in output
    assert "raw_message" not in output

    journal.append_audit_event(
        event_type="SIGNAL_CHECKED",
        entity_type="signal_receipt",
        entity_id=str(receipt.id),
        state="FILTERED",
    )
    assert main(["unfinished", "--database", str(path)]) == 0
    assert "unfinished_receipts=0" in capsys.readouterr().out
