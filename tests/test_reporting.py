from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from codexbot import (
    Action,
    CheckDisposition,
    CheckReport,
    DailyAuditSummary,
    ExecutionMode,
    ParsedMessage,
    ParseReason,
    PendingGate,
    ProcessingResult,
    Segment,
    SignalReceipt,
    SQLiteJournal,
    format_daily_summary,
    format_listener_error,
    format_processing_result,
)

NOW = datetime(2026, 10, 28, 4, 0, tzinfo=UTC)


def processing_result() -> ProcessingResult:
    return ProcessingResult(
        receipt=SignalReceipt(
            id=1,
            source_group_id=-1001,
            telegram_message_id=42,
            sent_at=NOW,
            first_durable_received_at=NOW,
        ),
        parsed=ParsedMessage(
            action=Action.BUY,
            segment=Segment.FNO,
            reason=ParseReason.OPTION_BUY_PATTERN,
            symbol="CDSL",
        ),
        instrument=None,
        report=CheckReport(
            disposition=CheckDisposition.PASSED_CORE,
            reasons=(),
            pending_gates=(PendingGate.CURRENT_QUOTE, PendingGate.SIZING),
            execution_mode=ExecutionMode.TEST,
        ),
        duplicate_claim=None,
    )


def test_signal_report_is_explicitly_non_trading_and_omits_raw_text() -> None:
    report = format_processing_result(processing_result())

    assert "[TEST] SIGNAL PASSED_CORE" in report
    assert "Source group: -1001" in report
    assert "Pending gates: CURRENT_QUOTE, SIZING" in report
    assert "Trade ready: NO" in report
    assert "Broker action: NONE" in report
    assert "SL_10" not in report


def test_daily_summary_counts_only_events_inside_ist_service_date(tmp_path: Path) -> None:
    database = tmp_path / "codexbot.sqlite3"
    journal = SQLiteJournal(database, clock=lambda: NOW)
    journal.initialize()
    service_date = date(2026, 10, 28)
    events = [
        ("SIGNAL_RECEIVED", "DURABLE", NOW),
        ("SIGNAL_CHECKED", "PASSED_CORE", NOW),
        ("OPTION_DUPLICATE_REJECTED", "DUPLICATE", NOW),
        ("SYSTEM_HEALTH_CHECKED", "UNHEALTHY", NOW),
        ("BROKER_RECONCILIATION_OBSERVED", "DURABLE", NOW),
        ("SIGNAL_RECEIVED", "DURABLE", NOW - timedelta(days=1)),
    ]
    for event_type, state, occurred_at in events:
        journal.append_audit_event(
            event_type=event_type,
            entity_type="test",
            entity_id=None,
            state=state,
            occurred_at=occurred_at,
        )

    summary = journal.daily_audit_summary(service_date)

    assert summary.signals_received == 1
    assert summary.passed_core == 1
    assert summary.duplicates_rejected == 1
    assert summary.unhealthy_system_checks == 1
    assert summary.broker_snapshots == 1


def test_daily_summary_text_cannot_be_mistaken_for_paper_trading() -> None:
    summary = DailyAuditSummary(
        service_date=date(2026, 10, 28),
        signals_received=10,
        redeliveries_ignored=1,
        passed_core=2,
        rejected=3,
        filtered=5,
        duplicates_rejected=1,
        unhealthy_system_checks=0,
        broker_snapshots=0,
    )

    report = format_daily_summary(summary)

    assert "Signals received: 10" in report
    assert "Real broker snapshots: 0" in report
    assert "Simulated orders/fills/holdings: NEVER CREATED" in report


def test_listener_error_report_contains_code_without_exception_text() -> None:
    report = format_listener_error(execution_mode="TEST", error_code="InstrumentCacheError")

    assert report == (
        "[TEST] TELEGRAM PROCESSING ERROR\nError code: InstrumentCacheError\nBroker action: NONE"
    )
