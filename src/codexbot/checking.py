"""Deterministic, side-effect-free signal checks."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from codexbot.models import (
    Action,
    CheckDisposition,
    CheckerPolicy,
    CheckReport,
    InstrumentFacts,
    InstrumentKind,
    NormalizedSignal,
    PendingGate,
    ReasonCode,
    Segment,
)

_ALL_PENDING_GATES = tuple(PendingGate)
_MAX_MESSAGE_AGE = timedelta(seconds=60)
_FUTURE_CLOCK_TOLERANCE = timedelta(seconds=2)


class SignalChecker:
    """Apply only the deterministic rules approved for the first build slice."""

    def __init__(self, policy: CheckerPolicy) -> None:
        self._policy = policy

    def check(
        self,
        signal: NormalizedSignal,
        instrument: InstrumentFacts | None,
    ) -> CheckReport:
        reasons: list[ReasonCode] = []

        if signal.source_group_id not in self._policy.allowed_group_ids:
            reasons.append(ReasonCode.SOURCE_NOT_CONFIGURED)

        if not _is_aware(signal.sent_at) or not _is_aware(signal.first_durable_received_at):
            reasons.append(ReasonCode.INVALID_TIMESTAMP)
        else:
            age = signal.first_durable_received_at.astimezone(UTC) - signal.sent_at.astimezone(UTC)
            if age < -_FUTURE_CLOCK_TOLERANCE:
                reasons.append(ReasonCode.INVALID_TIMESTAMP)
            elif age > _MAX_MESSAGE_AGE:
                reasons.append(ReasonCode.MESSAGE_TOO_OLD)

        if signal.action is Action.UNKNOWN:
            reasons.append(ReasonCode.UNRECOGNIZED_MESSAGE)
        elif signal.action is not Action.BUY:
            reasons.append(ReasonCode.NON_BUY_ACTION)

        if signal.action is not Action.BUY:
            return CheckReport(
                disposition=_disposition(signal.action, reasons),
                reasons=tuple(reasons),
                pending_gates=(),
                execution_mode=self._policy.execution_mode,
            )

        if signal.segment is None:
            reasons.append(ReasonCode.SEGMENT_UNRESOLVED)
        elif signal.segment is Segment.EQUITY and not self._policy.equity_active:
            reasons.append(ReasonCode.SEGMENT_INACTIVE)
        elif signal.segment is Segment.FNO and not self._policy.fno_active:
            reasons.append(ReasonCode.SEGMENT_INACTIVE)

        if signal.symbol is None or not signal.symbol.strip():
            reasons.append(ReasonCode.INSTRUMENT_REFERENCE_MISSING)

        if instrument is None or not instrument.resolved:
            reasons.append(ReasonCode.INSTRUMENT_UNRESOLVED)
        else:
            if instrument.security_id is None or not instrument.security_id.strip():
                reasons.append(ReasonCode.INSTRUMENT_IDENTITY_INCOMPLETE)
            if not instrument.listed:
                reasons.append(ReasonCode.INSTRUMENT_NOT_LISTED)

            if instrument.kind is InstrumentKind.INDEX:
                reasons.append(ReasonCode.INDEX_NOT_ALLOWED)
            elif instrument.kind is InstrumentKind.STOCK_FUTURE:
                reasons.append(ReasonCode.FUTURES_NOT_APPROVED)
            elif instrument.kind is InstrumentKind.UNKNOWN:
                reasons.append(ReasonCode.INSTRUMENT_KIND_UNSUPPORTED)

            if signal.segment is not None and not _segment_matches(signal.segment, instrument.kind):
                reasons.append(ReasonCode.SEGMENT_INSTRUMENT_MISMATCH)

            if instrument.kind is InstrumentKind.STOCK_OPTION:
                if signal.stated_price is None:
                    reasons.append(ReasonCode.OPTION_PRICE_REQUIRED)
                elif not signal.stated_price.is_finite() or signal.stated_price <= 0:
                    reasons.append(ReasonCode.OPTION_PRICE_INVALID)
                if not instrument.unique_contract:
                    reasons.append(ReasonCode.OPTION_CONTRACT_NOT_UNIQUE)
                if (
                    instrument.canonical_underlying_id is None
                    or not instrument.canonical_underlying_id.strip()
                ):
                    reasons.append(ReasonCode.OPTION_UNDERLYING_IDENTITY_MISSING)

        disposition = _disposition(signal.action, reasons)
        pending_gates = _ALL_PENDING_GATES if disposition is CheckDisposition.PASSED_CORE else ()
        return CheckReport(
            disposition=disposition,
            reasons=tuple(reasons),
            pending_gates=pending_gates,
            execution_mode=self._policy.execution_mode,
        )


def _is_aware(value: datetime) -> bool:
    return value.tzinfo is not None and value.utcoffset() is not None


def _segment_matches(segment: Segment, kind: InstrumentKind) -> bool:
    if kind is InstrumentKind.EQUITY:
        return segment is Segment.EQUITY
    if kind in {InstrumentKind.STOCK_OPTION, InstrumentKind.STOCK_FUTURE}:
        return segment is Segment.FNO
    return True


def _disposition(action: Action, reasons: list[ReasonCode]) -> CheckDisposition:
    if action is not Action.BUY:
        safety_reasons = {
            reason
            for reason in reasons
            if reason not in {ReasonCode.NON_BUY_ACTION, ReasonCode.UNRECOGNIZED_MESSAGE}
        }
        return CheckDisposition.REJECTED if safety_reasons else CheckDisposition.FILTERED
    if reasons:
        return CheckDisposition.REJECTED
    return CheckDisposition.PASSED_CORE
