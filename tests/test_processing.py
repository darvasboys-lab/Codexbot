import sqlite3
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from codexbot import (
    CheckDisposition,
    CheckerPolicy,
    InstrumentFacts,
    InstrumentKind,
    PendingGate,
    ReasonCode,
    SignalChecker,
    SignalProcessor,
    SQLiteJournal,
    TelegramEnvelope,
    TelegramMessageParser,
)

NOW = datetime(2026, 10, 27, 4, 0, tzinfo=UTC)


class MutableClock:
    def __init__(self, current: datetime) -> None:
        self.current = current

    def __call__(self) -> datetime:
        return self.current


class MutableResolver:
    def __init__(self, facts: InstrumentFacts) -> None:
        self.facts = facts
        self.as_of_dates: list[date] = []

    def resolve(self, parsed: object, *, as_of: date) -> InstrumentFacts:
        self.as_of_dates.append(as_of)
        return self.facts


def processor(
    tmp_path: Path,
    clock: MutableClock,
    instrument: InstrumentFacts,
) -> tuple[SignalProcessor, Path, MutableResolver]:
    database_path = tmp_path / "codexbot.sqlite3"
    journal = SQLiteJournal(database_path, clock=clock)
    journal.initialize()
    journal.set_emergency_stop(
        engaged=False,
        reason="test fixture enables validation flow",
        actor="test-suite",
    )
    checker = SignalChecker(
        CheckerPolicy(
            allowed_group_ids=frozenset({1001, 1002}),
            authorized_source_ids=frozenset({2001}),
            equity_active=True,
            fno_active=True,
        )
    )
    resolver = MutableResolver(instrument)
    return (
        SignalProcessor(
            journal=journal,
            parser=TelegramMessageParser(),
            checker=checker,
            instrument_resolver=resolver,
        ),
        database_path,
        resolver,
    )


def envelope(
    *,
    message_id: int,
    text: str = "CDSL 1400CE OCT @33-35",
    group_id: int = 1001,
    source_id: int | None = 2001,
    sent_at: datetime = NOW,
) -> TelegramEnvelope:
    return TelegramEnvelope(
        source_group_id=group_id,
        source_sender_or_channel_id=source_id,
        telegram_message_id=message_id,
        sent_at=sent_at,
        text=text,
    )


def option_facts(
    *,
    security_id: str = "49081",
    listed: bool = True,
    unique_contract: bool = True,
    canonical_underlying_id: str | None = "INE736A01011",
) -> InstrumentFacts:
    return InstrumentFacts(
        resolved=True,
        listed=listed,
        kind=InstrumentKind.STOCK_OPTION,
        security_id=security_id,
        unique_contract=unique_contract,
        canonical_underlying_id=canonical_underlying_id,
    )


def claim_count(database_path: Path) -> int:
    with sqlite3.connect(database_path) as connection:
        row = connection.execute("SELECT COUNT(*) FROM option_duplicate_claims").fetchone()
    assert row is not None
    return int(row[0])


def test_valid_listed_option_claims_after_core_validation(tmp_path: Path) -> None:
    clock = MutableClock(NOW)
    signal_processor, database_path, resolver = processor(tmp_path, clock, option_facts())

    result = signal_processor.process(envelope(message_id=1))

    assert result.report.disposition is CheckDisposition.PASSED_CORE
    assert result.duplicate_claim is not None
    assert result.duplicate_claim.accepted is True
    assert PendingGate.DUPLICATE not in result.report.pending_gates
    assert PendingGate.AUDIT_DURABILITY not in result.report.pending_gates
    assert result.trade_ready is False
    assert result.instrument == option_facts()
    assert claim_count(database_path) == 1
    assert resolver.as_of_dates == [date(2026, 10, 27)]


def test_engaged_emergency_stop_rejects_before_duplicate_claim(tmp_path: Path) -> None:
    clock = MutableClock(NOW)
    signal_processor, database_path, _ = processor(tmp_path, clock, option_facts())
    SQLiteJournal(database_path, clock=clock).set_emergency_stop(
        engaged=True,
        reason="manual safety stop",
        actor="operator",
    )

    result = signal_processor.process(envelope(message_id=1))

    assert result.report.disposition is CheckDisposition.REJECTED
    assert result.report.reasons == (ReasonCode.EMERGENCY_STOP_ENGAGED,)
    assert result.duplicate_claim is None
    assert claim_count(database_path) == 0


@pytest.mark.parametrize(
    ("candidate", "instrument", "reason"),
    [
        (
            envelope(message_id=1, group_id=9999, source_id=9999),
            option_facts(),
            ReasonCode.SOURCE_NOT_CONFIGURED,
        ),
        (
            envelope(message_id=1, sent_at=NOW - timedelta(seconds=61)),
            option_facts(),
            ReasonCode.MESSAGE_TOO_OLD,
        ),
        (
            envelope(message_id=1),
            option_facts(listed=False),
            ReasonCode.INSTRUMENT_NOT_LISTED,
        ),
        (
            envelope(message_id=1),
            option_facts(unique_contract=False),
            ReasonCode.OPTION_CONTRACT_NOT_UNIQUE,
        ),
        (
            envelope(message_id=1),
            option_facts(canonical_underlying_id=None),
            ReasonCode.OPTION_UNDERLYING_IDENTITY_MISSING,
        ),
        (
            envelope(message_id=1, text="SENSEX 74500CE @450-460"),
            InstrumentFacts(
                resolved=True,
                listed=True,
                kind=InstrumentKind.INDEX,
                security_id="13",
                unique_contract=True,
            ),
            ReasonCode.INDEX_NOT_ALLOWED,
        ),
    ],
)
def test_rejected_candidate_never_reserves_duplicate_window(
    tmp_path: Path,
    candidate: TelegramEnvelope,
    instrument: InstrumentFacts,
    reason: ReasonCode,
) -> None:
    signal_processor, database_path, _ = processor(tmp_path, MutableClock(NOW), instrument)

    result = signal_processor.process(candidate)

    assert result.report.disposition is CheckDisposition.REJECTED
    assert reason in result.report.reasons
    assert result.duplicate_claim is None
    assert claim_count(database_path) == 0


def test_invalid_option_price_never_reserves_duplicate_window(tmp_path: Path) -> None:
    signal_processor, database_path, resolver = processor(
        tmp_path, MutableClock(NOW), option_facts()
    )

    result = signal_processor.process(envelope(message_id=1, text="CDSL 1400CE OCT @0"))

    assert result.report.disposition is CheckDisposition.FILTERED
    assert result.duplicate_claim is None
    assert claim_count(database_path) == 0
    assert resolver.as_of_dates == []


def test_valid_correction_after_rejected_candidate_can_claim(tmp_path: Path) -> None:
    clock = MutableClock(NOW)
    signal_processor, database_path, resolver = processor(
        tmp_path, clock, option_facts(unique_contract=False)
    )
    rejected = signal_processor.process(envelope(message_id=1))

    clock.current = NOW + timedelta(seconds=5)
    resolver.facts = option_facts()
    corrected = signal_processor.process(envelope(message_id=2, sent_at=clock.current))

    assert rejected.duplicate_claim is None
    assert corrected.report.disposition is CheckDisposition.PASSED_CORE
    assert corrected.duplicate_claim is not None
    assert corrected.duplicate_claim.accepted is True
    assert claim_count(database_path) == 1


def test_valid_claim_blocks_different_strike_price_and_option_type(tmp_path: Path) -> None:
    clock = MutableClock(NOW)
    signal_processor, database_path, resolver = processor(tmp_path, clock, option_facts())
    first = signal_processor.process(envelope(message_id=1))

    clock.current = NOW + timedelta(seconds=10)
    resolver.facts = option_facts(security_id="59001")
    duplicate = signal_processor.process(
        envelope(
            message_id=2,
            group_id=1002,
            sent_at=clock.current,
            text="CDSL 1600PE NOV @50-55",
        )
    )

    assert first.duplicate_claim is not None
    assert first.duplicate_claim.accepted is True
    assert duplicate.report.disposition is CheckDisposition.REJECTED
    assert duplicate.report.reasons == (ReasonCode.DUPLICATE_SIGNAL,)
    assert duplicate.duplicate_claim is not None
    assert duplicate.duplicate_claim.accepted is False
    assert claim_count(database_path) == 1


def test_processing_audit_records_parse_and_final_decision(tmp_path: Path) -> None:
    clock = MutableClock(NOW)
    signal_processor, database_path, _ = processor(tmp_path, clock, option_facts())

    signal_processor.process(envelope(message_id=1))

    with sqlite3.connect(database_path) as connection:
        event_types = [
            str(row[0])
            for row in connection.execute("SELECT event_type FROM audit_events ORDER BY id")
        ]
    assert event_types == [
        "EMERGENCY_STOP_CHANGED",
        "SIGNAL_RECEIVED",
        "SIGNAL_PARSED",
        "INSTRUMENT_RESOLVED",
        "OPTION_DUPLICATE_CLAIMED",
        "SIGNAL_CHECKED",
    ]
