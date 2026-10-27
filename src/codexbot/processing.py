"""TEST-safe composition of receipt, parsing, checking, audit, and option deduplication.

The processor contains no broker adapter and cannot submit, modify, or cancel an
order. Instrument facts come from an injected read-only resolver.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol
from zoneinfo import ZoneInfo

from codexbot.checking import SignalChecker
from codexbot.models import (
    Action,
    CheckDisposition,
    CheckReport,
    InstrumentFacts,
    InstrumentKind,
    NormalizedSignal,
    PendingGate,
    ReasonCode,
)
from codexbot.parsing import ParsedMessage, TelegramMessageParser
from codexbot.persistence import DuplicateClaimResult, SignalReceipt, SQLiteJournal

_INDIA_TIME = ZoneInfo("Asia/Kolkata")


class InstrumentResolver(Protocol):
    def resolve(self, parsed: ParsedMessage, *, as_of: date) -> InstrumentFacts: ...


@dataclass(frozen=True, slots=True)
class TelegramEnvelope:
    source_group_id: int
    source_sender_or_channel_id: int | None
    telegram_message_id: int
    sent_at: datetime
    text: str | None
    is_forwarded: bool = False
    forwarded_from_source_id: int | None = None


@dataclass(frozen=True, slots=True)
class ProcessingResult:
    receipt: SignalReceipt
    parsed: ParsedMessage
    instrument: InstrumentFacts | None
    report: CheckReport
    duplicate_claim: DuplicateClaimResult | None

    @property
    def trade_ready(self) -> bool:
        return False


class SignalProcessor:
    """Run the approved deterministic pipeline through option deduplication."""

    def __init__(
        self,
        *,
        journal: SQLiteJournal,
        parser: TelegramMessageParser,
        checker: SignalChecker,
        instrument_resolver: InstrumentResolver,
    ) -> None:
        self._journal = journal
        self._parser = parser
        self._checker = checker
        self._instrument_resolver = instrument_resolver

    def process(
        self,
        envelope: TelegramEnvelope,
    ) -> ProcessingResult:
        receipt = self._journal.record_signal_receipt(
            source_group_id=envelope.source_group_id,
            telegram_message_id=envelope.telegram_message_id,
            sent_at=envelope.sent_at,
        )
        parsed = self._parser.parse(envelope.text)
        self._record_parse(receipt, parsed)
        instrument = (
            self._instrument_resolver.resolve(
                parsed,
                as_of=envelope.sent_at.astimezone(_INDIA_TIME).date(),
            )
            if parsed.action is Action.BUY
            else None
        )
        if instrument is not None:
            self._record_instrument(receipt, instrument)

        signal = NormalizedSignal(
            source_group_id=envelope.source_group_id,
            source_sender_or_channel_id=envelope.source_sender_or_channel_id,
            telegram_message_id=envelope.telegram_message_id,
            sent_at=envelope.sent_at,
            first_durable_received_at=receipt.first_durable_received_at,
            is_forwarded=envelope.is_forwarded,
            forwarded_from_source_id=envelope.forwarded_from_source_id,
            action=parsed.action,
            segment=parsed.segment,
            symbol=parsed.symbol,
            stated_price=parsed.entry_price_upper,
        )
        report = self._checker.check(signal, instrument)
        duplicate_claim: DuplicateClaimResult | None = None

        if (
            report.disposition is CheckDisposition.PASSED_CORE
            and instrument is not None
            and instrument.kind is InstrumentKind.STOCK_OPTION
        ):
            underlying_id = instrument.canonical_underlying_id
            if underlying_id is None or not underlying_id.strip():
                raise RuntimeError("passed stock option is missing its canonical underlying ID")
            duplicate_claim = self._journal.claim_stock_option_signal(
                receipt_id=receipt.id,
                canonical_underlying_id=underlying_id,
            )
            report = _after_duplicate_check(report, duplicate_claim)

        report = _after_audit_durability(report)
        self._journal.record_signal_check(receipt_id=receipt.id, report=report)
        return ProcessingResult(
            receipt=receipt,
            parsed=parsed,
            instrument=instrument,
            report=report,
            duplicate_claim=duplicate_claim,
        )

    def _record_parse(self, receipt: SignalReceipt, parsed: ParsedMessage) -> None:
        self._journal.append_audit_event(
            event_type="SIGNAL_PARSED",
            entity_type="signal_receipt",
            entity_id=str(receipt.id),
            state=parsed.action.value,
            details={
                "entry_price_lower": _decimal_text(parsed.entry_price_lower),
                "entry_price_upper": _decimal_text(parsed.entry_price_upper),
                "expiry_month": parsed.expiry_month,
                "option_strike": _decimal_text(parsed.option_strike),
                "option_type": parsed.option_type.value if parsed.option_type else None,
                "parse_reason": parsed.reason.value,
                "segment": parsed.segment.value if parsed.segment else None,
                "symbol": parsed.symbol,
            },
        )

    def _record_instrument(self, receipt: SignalReceipt, instrument: InstrumentFacts) -> None:
        self._journal.append_audit_event(
            event_type="INSTRUMENT_RESOLVED",
            entity_type="signal_receipt",
            entity_id=str(receipt.id),
            state=instrument.kind.value,
            details={
                "canonical_underlying_id": instrument.canonical_underlying_id,
                "exchange": instrument.exchange,
                "expiry_date": (
                    instrument.expiry_date.isoformat() if instrument.expiry_date else None
                ),
                "listed": instrument.listed,
                "lot_size": _decimal_text(instrument.lot_size),
                "resolved": instrument.resolved,
                "security_id": instrument.security_id,
                "tick_size_raw": _decimal_text(instrument.tick_size_raw),
                "unique_contract": instrument.unique_contract,
            },
        )


def _after_duplicate_check(
    report: CheckReport,
    claim: DuplicateClaimResult,
) -> CheckReport:
    if not claim.accepted:
        return CheckReport(
            disposition=CheckDisposition.REJECTED,
            reasons=(ReasonCode.DUPLICATE_SIGNAL,),
            pending_gates=(),
            execution_mode=report.execution_mode,
        )
    return CheckReport(
        disposition=report.disposition,
        reasons=report.reasons,
        pending_gates=tuple(
            gate for gate in report.pending_gates if gate is not PendingGate.DUPLICATE
        ),
        execution_mode=report.execution_mode,
    )


def _after_audit_durability(report: CheckReport) -> CheckReport:
    return CheckReport(
        disposition=report.disposition,
        reasons=report.reasons,
        pending_gates=tuple(
            gate for gate in report.pending_gates if gate is not PendingGate.AUDIT_DURABILITY
        ),
        execution_mode=report.execution_mode,
    )


def _decimal_text(value: object | None) -> str | None:
    return str(value) if value is not None else None
