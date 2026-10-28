import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from codexbot import (
    Action,
    CheckerPolicy,
    DhanOrderSnapshot,
    DhanPositionSnapshot,
    DhanReconciliationSnapshot,
    DhanTradeSnapshot,
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


def test_real_broker_snapshot_is_atomic_append_only_evidence(tmp_path: Path) -> None:
    database_path = tmp_path / "codexbot.sqlite3"
    journal = SQLiteJournal(database_path, clock=lambda: NOW)
    journal.initialize()
    snapshot = DhanReconciliationSnapshot(
        orders=(
            DhanOrderSnapshot(
                order_id="order-1",
                correlation_id="codexbot-1",
                order_status="PART_TRADED",
                transaction_type="BUY",
                exchange_segment="NSE_EQ",
                product_type="CNC",
                order_type="LIMIT",
                trading_symbol="TCS",
                security_id="11536",
                quantity=40,
                remaining_quantity=25,
                filled_quantity=15,
                average_traded_price=Decimal("3345.8"),
                received_at=NOW,
            ),
        ),
        trades=(
            DhanTradeSnapshot(
                order_id="order-1",
                exchange_order_id="exchange-order-1",
                exchange_trade_id="trade-1",
                transaction_type="BUY",
                exchange_segment="NSE_EQ",
                product_type="CNC",
                order_type="LIMIT",
                trading_symbol="TCS",
                security_id="11536",
                traded_quantity=15,
                traded_price=Decimal("3345.8"),
                exchange_time="2026-10-28 09:20:06",
                received_at=NOW,
            ),
        ),
        positions=(
            DhanPositionSnapshot(
                trading_symbol="TCS",
                security_id="11536",
                position_type="LONG",
                exchange_segment="NSE_EQ",
                product_type="CNC",
                buy_average=Decimal("3345.8"),
                buy_quantity=15,
                sell_average=Decimal("0"),
                sell_quantity=0,
                net_quantity=15,
                realized_profit=Decimal("0"),
                unrealized_profit=Decimal("10.5"),
                received_at=NOW,
            ),
        ),
        started_at=NOW - timedelta(milliseconds=100),
        completed_at=NOW,
    )

    status = journal.record_broker_reconciliation_snapshot(snapshot)

    assert status.order_count == 1
    assert status.trade_count == 1
    assert status.position_count == 1
    assert journal.latest_broker_snapshot_status() == status
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM broker_order_observations").fetchone() == (
            1,
        )
        assert connection.execute("SELECT COUNT(*) FROM broker_trade_observations").fetchone() == (
            1,
        )
        assert connection.execute(
            "SELECT COUNT(*) FROM broker_position_observations"
        ).fetchone() == (1,)
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute("DELETE FROM broker_order_observations")


def test_invalid_broker_snapshot_rolls_back_every_item(tmp_path: Path) -> None:
    database_path = tmp_path / "codexbot.sqlite3"
    journal = SQLiteJournal(database_path, clock=lambda: NOW)
    journal.initialize()
    duplicate = DhanOrderSnapshot(
        order_id="duplicate",
        correlation_id=None,
        order_status="PENDING",
        transaction_type="BUY",
        exchange_segment="NSE_EQ",
        product_type="CNC",
        order_type="LIMIT",
        trading_symbol=None,
        security_id="11536",
        quantity=1,
        remaining_quantity=1,
        filled_quantity=0,
        average_traded_price=Decimal("0"),
        received_at=NOW,
    )
    snapshot = DhanReconciliationSnapshot(
        orders=(duplicate, duplicate),
        trades=(),
        positions=(),
        started_at=NOW,
        completed_at=NOW,
    )

    with pytest.raises(sqlite3.IntegrityError):
        journal.record_broker_reconciliation_snapshot(snapshot)

    assert journal.latest_broker_snapshot_status() is None
    with sqlite3.connect(database_path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM broker_reconciliation_snapshots"
        ).fetchone() == (0,)


def test_operator_feedback_is_idempotent_append_only_and_audited(tmp_path: Path) -> None:
    database_path = tmp_path / "codexbot.sqlite3"
    journal = SQLiteJournal(database_path, clock=lambda: NOW)
    journal.initialize()
    journal.record_signal_receipt(
        source_group_id=-1001,
        telegram_message_id=42,
        sent_at=NOW,
    )

    first = journal.record_operator_feedback(
        source_group_id=-1001,
        source_telegram_message_id=42,
        feedback_group_id=-9001,
        feedback_telegram_message_id=77,
        operator_id=3001,
        feedback_text="  parser should keep this rejected  ",
    )
    redelivery = journal.record_operator_feedback(
        source_group_id=-1001,
        source_telegram_message_id=42,
        feedback_group_id=-9001,
        feedback_telegram_message_id=77,
        operator_id=3001,
        feedback_text="different redelivery text is ignored",
    )

    assert redelivery == first
    assert first.feedback_text == "parser should keep this rejected"
    assert first.status == "PENDING_REVIEW"
    assert journal.recent_operator_feedback() == (first,)
    with sqlite3.connect(database_path) as connection:
        audit = connection.execute(
            "SELECT state, details_json FROM audit_events "
            "WHERE event_type = 'OPERATOR_FEEDBACK_RECORDED'"
        ).fetchall()
        assert len(audit) == 1
        assert "parser should" not in str(audit[0][1])
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute("UPDATE operator_feedback_events SET status = 'PENDING_REVIEW'")


def test_operator_feedback_requires_existing_signal_receipt(tmp_path: Path) -> None:
    journal = SQLiteJournal(tmp_path / "codexbot.sqlite3", clock=lambda: NOW)
    journal.initialize()

    with pytest.raises(ValueError, match="does not exist"):
        journal.record_operator_feedback(
            source_group_id=-1001,
            source_telegram_message_id=42,
            feedback_group_id=-9001,
            feedback_telegram_message_id=77,
            operator_id=3001,
            feedback_text="review this",
        )


def test_calendar_override_history_is_dated_append_only_and_audited(tmp_path: Path) -> None:
    database_path = tmp_path / "codexbot.sqlite3"
    journal = SQLiteJournal(database_path, clock=lambda: NOW)
    journal.initialize()
    service_date = NOW.date()

    opened = journal.set_calendar_override(
        service_date=service_date,
        segment="NSE_CM",
        enabled=True,
        reason="official special session confirmed",
        actor="local-user:udit:uid:1000",
    )
    cleared = journal.set_calendar_override(
        service_date=service_date,
        segment="NSE_CM",
        enabled=False,
        reason="special session completed",
        actor="local-user:udit:uid:1000",
    )

    assert opened.enabled is True
    assert journal.calendar_override_status(service_date=service_date, segment="NSE_CM") == cleared
    audit = journal.recent_audit_events(event_type="CALENDAR_OVERRIDE_CHANGED")
    assert [item.state for item in audit] == ["CLEARED", "OPEN_ENABLED"]
    with sqlite3.connect(database_path) as connection:
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute("DELETE FROM calendar_override_events")


def test_calendar_override_defaults_closed_and_rejects_unknown_segment(tmp_path: Path) -> None:
    journal = SQLiteJournal(tmp_path / "codexbot.sqlite3", clock=lambda: NOW)
    journal.initialize()

    status = journal.calendar_override_status(service_date=NOW.date(), segment="NSE_FO")

    assert status.enabled is False
    assert status.reason == "NO_OVERRIDE_RECORDED"
    with pytest.raises(ValueError, match="calendar segment"):
        journal.calendar_override_status(service_date=NOW.date(), segment="UNKNOWN")


def test_recent_audit_history_is_bounded_and_filterable(tmp_path: Path) -> None:
    journal = SQLiteJournal(tmp_path / "codexbot.sqlite3", clock=lambda: NOW)
    journal.initialize()
    journal.append_audit_event(event_type="FIRST", entity_type="system", entity_id=None, state="OK")
    journal.append_audit_event(
        event_type="SECOND", entity_type="system", entity_id=None, state="OK"
    )

    assert [item.event_type for item in journal.recent_audit_events(limit=1)] == ["SECOND"]
    assert [item.event_type for item in journal.recent_audit_events(event_type="FIRST")] == [
        "FIRST"
    ]


def test_journal_and_backup_are_owner_only_and_unsafe_paths_fail(tmp_path: Path) -> None:
    database = tmp_path / "codexbot.sqlite3"
    journal = SQLiteJournal(database, clock=lambda: NOW)
    journal.initialize()

    assert database.stat().st_mode & 0o077 == 0
    backup = backup_database(database, tmp_path / "backup.sqlite3")
    assert backup.stat().st_mode & 0o077 == 0

    database.chmod(0o644)
    with pytest.raises(PermissionError, match="owner-only"):
        journal.journal_mode()


def test_journal_rejects_symlinked_database_directory(tmp_path: Path) -> None:
    real_directory = tmp_path / "real"
    real_directory.mkdir(mode=0o700)
    linked_directory = tmp_path / "linked"
    linked_directory.symlink_to(real_directory, target_is_directory=True)

    with pytest.raises(PermissionError, match="directory cannot be a symlink"):
        SQLiteJournal(linked_directory / "codexbot.sqlite3", clock=lambda: NOW).initialize()
