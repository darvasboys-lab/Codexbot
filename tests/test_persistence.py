import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from codexbot import (
    Action,
    CheckerPolicy,
    InstrumentFacts,
    InstrumentKind,
    NormalizedSignal,
    Segment,
    SignalChecker,
)
from codexbot.persistence import (
    SQLiteJournal,
    backup_database,
    integrity_check,
    restore_test,
)

NOW = datetime(2026, 10, 27, 4, 0, tzinfo=UTC)


class MutableClock:
    def __init__(self, current: datetime) -> None:
        self.current = current

    def __call__(self) -> datetime:
        return self.current


def test_database_uses_wal_and_first_receipt_is_immutable(tmp_path: Path) -> None:
    database_path = tmp_path / "codexbot.sqlite3"
    clock = MutableClock(NOW)
    journal = SQLiteJournal(database_path, clock=clock)
    journal.initialize()

    first = journal.record_signal_receipt(
        source_group_id=1001,
        telegram_message_id=42,
        sent_at=NOW - timedelta(seconds=3),
    )
    clock.current = NOW + timedelta(seconds=10)
    redelivery = journal.record_signal_receipt(
        source_group_id=1001,
        telegram_message_id=42,
        sent_at=NOW - timedelta(seconds=3),
    )

    assert journal.journal_mode() == "wal"
    assert redelivery == first
    assert not first.is_redelivery
    assert redelivery.is_redelivery
    assert first.first_durable_received_at == NOW
    with sqlite3.connect(database_path) as connection:
        states = connection.execute("SELECT event_type FROM audit_events ORDER BY id").fetchall()
    assert states == [("SIGNAL_RECEIVED",), ("SIGNAL_REDELIVERED",)]


def test_audit_and_receipt_tables_reject_update_and_delete(tmp_path: Path) -> None:
    database_path = tmp_path / "codexbot.sqlite3"
    journal = SQLiteJournal(database_path, clock=lambda: NOW)
    journal.initialize()
    receipt = journal.record_signal_receipt(
        source_group_id=1001,
        telegram_message_id=1,
        sent_at=NOW,
    )

    with sqlite3.connect(database_path) as connection:
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute("UPDATE audit_events SET state = 'CHANGED' WHERE id = 1")
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute("DELETE FROM signal_receipts WHERE id = ?", (receipt.id,))


def test_signal_check_report_is_appended_to_audit(tmp_path: Path) -> None:
    database_path = tmp_path / "codexbot.sqlite3"
    journal = SQLiteJournal(database_path, clock=lambda: NOW)
    journal.initialize()
    receipt = journal.record_signal_receipt(
        source_group_id=1001, telegram_message_id=1, sent_at=NOW
    )
    report = SignalChecker(
        CheckerPolicy(
            allowed_group_ids=frozenset({1001}),
            authorized_source_ids=frozenset({2001}),
            equity_active=True,
            fno_active=True,
        )
    ).check(
        NormalizedSignal(
            source_group_id=1001,
            source_sender_or_channel_id=2001,
            telegram_message_id=1,
            sent_at=NOW,
            first_durable_received_at=receipt.first_durable_received_at,
            is_forwarded=False,
            forwarded_from_source_id=None,
            action=Action.BUY,
            segment=Segment.EQUITY,
            symbol="RELIANCE",
        ),
        InstrumentFacts(
            resolved=True,
            listed=True,
            kind=InstrumentKind.EQUITY,
            security_id="2885",
            unique_contract=True,
        ),
    )

    journal.record_signal_check(receipt_id=receipt.id, report=report)

    with sqlite3.connect(database_path) as connection:
        row = connection.execute(
            """
            SELECT state, details_json
            FROM audit_events
            WHERE event_type = 'SIGNAL_CHECKED'
            """
        ).fetchone()
    assert row is not None
    assert row[0] == "PASSED_CORE"
    assert '"trade_ready":false' in row[1]


def test_stock_option_duplicate_window_ignores_contract_details(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "codexbot.sqlite3"
    clock = MutableClock(NOW)
    journal = SQLiteJournal(database_path, clock=clock)
    journal.initialize()

    first = journal.record_signal_receipt(
        source_group_id=1001,
        telegram_message_id=1,
        sent_at=NOW,
    )
    first_claim = journal.claim_stock_option_signal(
        receipt_id=first.id,
        canonical_underlying_id="INE002A01018",
    )

    # A second group can carry another strike, expiry, price, or CE/PE. None of
    # those contract details are accepted by the approved deduplication key.
    clock.current = NOW + timedelta(seconds=20)
    boundary = journal.record_signal_receipt(
        source_group_id=1002,
        telegram_message_id=2,
        sent_at=clock.current,
    )
    boundary_claim = journal.claim_stock_option_signal(
        receipt_id=boundary.id,
        canonical_underlying_id="INE002A01018",
    )

    clock.current = NOW + timedelta(seconds=20, microseconds=1)
    outside = journal.record_signal_receipt(
        source_group_id=1002,
        telegram_message_id=3,
        sent_at=clock.current,
    )
    outside_claim = journal.claim_stock_option_signal(
        receipt_id=outside.id,
        canonical_underlying_id="INE002A01018",
    )

    assert first_claim.accepted is True
    assert boundary_claim.accepted is False
    assert boundary_claim.matched_claim_id == first_claim.matched_claim_id
    assert outside_claim.accepted is True


def test_different_underlyings_do_not_collide(tmp_path: Path) -> None:
    journal = SQLiteJournal(tmp_path / "codexbot.sqlite3", clock=lambda: NOW)
    journal.initialize()
    first = journal.record_signal_receipt(source_group_id=1001, telegram_message_id=1, sent_at=NOW)
    second = journal.record_signal_receipt(source_group_id=1002, telegram_message_id=2, sent_at=NOW)

    first_claim = journal.claim_stock_option_signal(
        receipt_id=first.id, canonical_underlying_id="UNDERLYING-A"
    )
    second_claim = journal.claim_stock_option_signal(
        receipt_id=second.id, canonical_underlying_id="UNDERLYING-B"
    )

    assert first_claim.accepted is True
    assert second_claim.accepted is True


def test_receipt_cannot_be_reclaimed_for_a_different_underlying(tmp_path: Path) -> None:
    journal = SQLiteJournal(tmp_path / "codexbot.sqlite3", clock=lambda: NOW)
    journal.initialize()
    receipt = journal.record_signal_receipt(
        source_group_id=1001, telegram_message_id=1, sent_at=NOW
    )
    journal.claim_stock_option_signal(receipt_id=receipt.id, canonical_underlying_id="UNDERLYING-A")

    with pytest.raises(ValueError, match="different underlying"):
        journal.claim_stock_option_signal(
            receipt_id=receipt.id, canonical_underlying_id="UNDERLYING-B"
        )


def test_duplicate_claim_is_atomic_under_concurrency(tmp_path: Path) -> None:
    journal = SQLiteJournal(tmp_path / "codexbot.sqlite3", clock=lambda: NOW)
    journal.initialize()
    receipts = [
        journal.record_signal_receipt(
            source_group_id=group_id,
            telegram_message_id=group_id,
            sent_at=NOW,
        )
        for group_id in (1001, 1002)
    ]

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(
                journal.claim_stock_option_signal,
                receipt_id=receipt.id,
                canonical_underlying_id="UNDERLYING-A",
            )
            for receipt in receipts
        ]
    results = [future.result() for future in futures]

    assert sum(result.accepted for result in results) == 1
    assert len({result.matched_claim_id for result in results}) == 1


def test_integrity_backup_and_restore_test(tmp_path: Path) -> None:
    database_path = tmp_path / "codexbot.sqlite3"
    backup_path = tmp_path / "backups" / "codexbot.sqlite3"
    journal = SQLiteJournal(database_path, clock=lambda: NOW)
    journal.initialize()
    journal.append_audit_event(
        event_type="HEALTH_CHECKED",
        entity_type="system",
        entity_id=None,
        state="OK",
        details={"component": "journal"},
    )

    assert integrity_check(database_path) == ("ok",)
    assert backup_database(database_path, backup_path) == backup_path
    assert restore_test(backup_path) == ("ok",)
    with pytest.raises(FileExistsError):
        backup_database(database_path, backup_path)
