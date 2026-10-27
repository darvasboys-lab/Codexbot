from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from codexbot import (
    Action,
    CheckDisposition,
    CheckerPolicy,
    ExecutionMode,
    InstrumentFacts,
    InstrumentKind,
    NormalizedSignal,
    ReasonCode,
    Segment,
    SignalChecker,
)

NOW = datetime(2026, 10, 27, 4, 0, tzinfo=UTC)
LISTED_EQUITY = InstrumentFacts(
    resolved=True,
    listed=True,
    kind=InstrumentKind.EQUITY,
    security_id="2885",
    unique_contract=True,
)
LISTED_OPTION = InstrumentFacts(
    resolved=True,
    listed=True,
    kind=InstrumentKind.STOCK_OPTION,
    security_id="49081",
    unique_contract=True,
)


def policy(
    *,
    equity_active: bool = True,
    fno_active: bool = True,
    mode: ExecutionMode = ExecutionMode.TEST,
) -> CheckerPolicy:
    return CheckerPolicy(
        allowed_group_ids=frozenset({1001, 1002}),
        authorized_source_ids=frozenset({2001, 2002}),
        equity_active=equity_active,
        fno_active=fno_active,
        execution_mode=mode,
    )


def signal(
    *,
    action: Action = Action.BUY,
    segment: Segment = Segment.EQUITY,
    group_id: int = 1001,
    sent_at: datetime = NOW,
    durable_received_at: datetime = NOW,
    source_id: int | None = 2001,
    is_forwarded: bool = False,
    forwarded_from_source_id: int | None = None,
    symbol: str | None = "RELIANCE",
    price: Decimal | None = None,
) -> NormalizedSignal:
    return NormalizedSignal(
        source_group_id=group_id,
        source_sender_or_channel_id=source_id,
        telegram_message_id=42,
        sent_at=sent_at,
        first_durable_received_at=durable_received_at,
        is_forwarded=is_forwarded,
        forwarded_from_source_id=forwarded_from_source_id,
        action=action,
        segment=segment,
        symbol=symbol,
        stated_price=price,
    )


def test_default_mode_is_test_and_core_pass_is_never_trade_ready() -> None:
    report = SignalChecker(policy()).check(signal(), LISTED_EQUITY)

    assert report.disposition is CheckDisposition.PASSED_CORE
    assert report.execution_mode is ExecutionMode.TEST
    assert report.pending_gates
    assert report.trade_ready is False


def test_live_mode_still_cannot_make_the_core_trade_ready() -> None:
    report = SignalChecker(policy(mode=ExecutionMode.LIVE)).check(signal(), LISTED_EQUITY)

    assert report.disposition is CheckDisposition.PASSED_CORE
    assert report.execution_mode is ExecutionMode.LIVE
    assert report.trade_ready is False


@pytest.mark.parametrize("age_seconds", [0, 60])
def test_message_age_boundary_is_inclusive(age_seconds: int) -> None:
    candidate = signal(sent_at=NOW - timedelta(seconds=age_seconds))

    report = SignalChecker(policy()).check(candidate, LISTED_EQUITY)

    assert ReasonCode.MESSAGE_TOO_OLD not in report.reasons


def test_message_older_than_sixty_seconds_is_rejected() -> None:
    candidate = signal(sent_at=NOW - timedelta(seconds=60, microseconds=1))

    report = SignalChecker(policy()).check(candidate, LISTED_EQUITY)

    assert report.disposition is CheckDisposition.REJECTED
    assert ReasonCode.MESSAGE_TOO_OLD in report.reasons


@pytest.mark.parametrize(
    ("sent_at", "durable_received_at"),
    [
        (datetime(2026, 10, 27, 4, 0), NOW),
        (NOW, datetime(2026, 10, 27, 4, 0)),
        (NOW + timedelta(seconds=2, microseconds=1), NOW),
    ],
)
def test_invalid_or_future_timestamp_is_rejected(
    sent_at: datetime, durable_received_at: datetime
) -> None:
    report = SignalChecker(policy()).check(
        signal(sent_at=sent_at, durable_received_at=durable_received_at), LISTED_EQUITY
    )

    assert ReasonCode.INVALID_TIMESTAMP in report.reasons
    assert report.disposition is CheckDisposition.REJECTED


def test_two_second_future_clock_tolerance_is_fixed() -> None:
    candidate = signal(sent_at=NOW + timedelta(seconds=2))

    report = SignalChecker(policy()).check(candidate, LISTED_EQUITY)

    assert ReasonCode.INVALID_TIMESTAMP not in report.reasons


@pytest.mark.parametrize("action", [Action.SELL, Action.EXIT])
def test_sell_and_exit_are_classified_but_filtered(action: Action) -> None:
    inactive_policy = policy(equity_active=False, fno_active=False)
    report = SignalChecker(inactive_policy).check(
        signal(action=action, segment=Segment.FNO, symbol=None),
        None,
    )

    assert report.disposition is CheckDisposition.FILTERED
    assert report.reasons == (ReasonCode.NON_BUY_ACTION,)
    assert report.trade_ready is False


def test_unknown_message_is_filtered() -> None:
    inactive_policy = policy(equity_active=False, fno_active=False)
    report = SignalChecker(inactive_policy).check(
        signal(action=Action.UNKNOWN, segment=Segment.FNO, symbol=None),
        None,
    )

    assert report.disposition is CheckDisposition.FILTERED
    assert report.reasons == (ReasonCode.UNRECOGNIZED_MESSAGE,)


@pytest.mark.parametrize(
    ("group_id", "source_id", "reason"),
    [
        (9999, 2001, ReasonCode.SOURCE_NOT_CONFIGURED),
        (1001, 9998, ReasonCode.SOURCE_IDENTITY_UNAUTHORIZED),
        (1001, None, ReasonCode.SOURCE_IDENTITY_UNAUTHORIZED),
    ],
)
def test_both_group_and_source_identity_are_required(
    group_id: int, source_id: int | None, reason: ReasonCode
) -> None:
    candidate = signal(group_id=group_id, source_id=source_id)

    report = SignalChecker(policy()).check(candidate, LISTED_EQUITY)

    assert report.disposition is CheckDisposition.REJECTED
    assert reason in report.reasons


@pytest.mark.parametrize("forwarded_from_source_id", [None, 9998])
def test_forwarded_signal_requires_authorized_origin(
    forwarded_from_source_id: int | None,
) -> None:
    candidate = signal(
        is_forwarded=True,
        forwarded_from_source_id=forwarded_from_source_id,
    )

    report = SignalChecker(policy()).check(candidate, LISTED_EQUITY)

    assert report.disposition is CheckDisposition.REJECTED
    assert ReasonCode.FORWARDED_SOURCE_UNAUTHORIZED in report.reasons


def test_forwarded_signal_with_authorized_sender_and_origin_can_continue() -> None:
    candidate = signal(is_forwarded=True, forwarded_from_source_id=2002)

    report = SignalChecker(policy()).check(candidate, LISTED_EQUITY)

    assert report.disposition is CheckDisposition.PASSED_CORE


@pytest.mark.parametrize(
    ("candidate", "configured_policy"),
    [
        (signal(), policy(equity_active=False)),
        (
            signal(
                segment=Segment.FNO,
                price=Decimal("100"),
            ),
            policy(fno_active=False),
        ),
    ],
)
def test_inactive_segment_is_rejected(
    candidate: NormalizedSignal, configured_policy: CheckerPolicy
) -> None:
    facts = LISTED_OPTION if candidate.segment is Segment.FNO else LISTED_EQUITY
    report = SignalChecker(configured_policy).check(candidate, facts)

    assert report.disposition is CheckDisposition.REJECTED
    assert ReasonCode.SEGMENT_INACTIVE in report.reasons


@pytest.mark.parametrize(
    ("kind", "reason"),
    [
        (InstrumentKind.INDEX, ReasonCode.INDEX_NOT_ALLOWED),
        (InstrumentKind.STOCK_FUTURE, ReasonCode.FUTURES_NOT_APPROVED),
    ],
)
def test_indexes_and_unapproved_futures_are_rejected(
    kind: InstrumentKind, reason: ReasonCode
) -> None:
    facts = InstrumentFacts(
        resolved=True,
        listed=True,
        kind=kind,
        security_id="verified-id",
        unique_contract=True,
    )
    report = SignalChecker(policy()).check(signal(segment=Segment.FNO), facts)

    assert report.disposition is CheckDisposition.REJECTED
    assert reason in report.reasons


@pytest.mark.parametrize(
    ("facts", "reason"),
    [
        (
            InstrumentFacts(
                resolved=False,
                listed=False,
                kind=InstrumentKind.UNKNOWN,
                security_id=None,
                unique_contract=False,
            ),
            ReasonCode.INSTRUMENT_UNRESOLVED,
        ),
        (
            InstrumentFacts(
                resolved=True,
                listed=False,
                kind=InstrumentKind.EQUITY,
                security_id="2885",
                unique_contract=True,
            ),
            ReasonCode.INSTRUMENT_NOT_LISTED,
        ),
    ],
)
def test_unresolved_or_unlisted_instrument_is_rejected(
    facts: InstrumentFacts, reason: ReasonCode
) -> None:
    report = SignalChecker(policy()).check(signal(), facts)

    assert report.disposition is CheckDisposition.REJECTED
    assert reason in report.reasons


def test_buy_without_instrument_facts_is_rejected() -> None:
    report = SignalChecker(policy()).check(signal(), None)

    assert report.disposition is CheckDisposition.REJECTED
    assert ReasonCode.INSTRUMENT_UNRESOLVED in report.reasons


def test_verified_instrument_kind_must_match_signal_segment() -> None:
    report = SignalChecker(policy()).check(
        signal(segment=Segment.FNO, price=Decimal("100")),
        LISTED_EQUITY,
    )

    assert report.disposition is CheckDisposition.REJECTED
    assert ReasonCode.SEGMENT_INSTRUMENT_MISMATCH in report.reasons


def test_unknown_verified_instrument_kind_is_rejected() -> None:
    unsupported = InstrumentFacts(
        resolved=True,
        listed=True,
        kind=InstrumentKind.UNKNOWN,
        security_id="verified-id",
        unique_contract=True,
    )

    report = SignalChecker(policy()).check(signal(), unsupported)

    assert report.disposition is CheckDisposition.REJECTED
    assert ReasonCode.INSTRUMENT_KIND_UNSUPPORTED in report.reasons


@pytest.mark.parametrize("symbol", [None, "", "   "])
def test_missing_instrument_reference_is_rejected(symbol: str | None) -> None:
    report = SignalChecker(policy()).check(signal(symbol=symbol), LISTED_EQUITY)

    assert report.disposition is CheckDisposition.REJECTED
    assert ReasonCode.INSTRUMENT_REFERENCE_MISSING in report.reasons


def test_resolved_instrument_requires_canonical_security_id() -> None:
    incomplete = InstrumentFacts(
        resolved=True,
        listed=True,
        kind=InstrumentKind.EQUITY,
        security_id=None,
        unique_contract=True,
    )

    report = SignalChecker(policy()).check(signal(), incomplete)

    assert report.disposition is CheckDisposition.REJECTED
    assert ReasonCode.INSTRUMENT_IDENTITY_INCOMPLETE in report.reasons


def test_stock_option_requires_price_and_unique_contract() -> None:
    candidate = signal(segment=Segment.FNO)
    ambiguous = InstrumentFacts(
        resolved=True,
        listed=True,
        kind=InstrumentKind.STOCK_OPTION,
        security_id="49081",
        unique_contract=False,
    )

    report = SignalChecker(policy()).check(candidate, ambiguous)

    assert report.disposition is CheckDisposition.REJECTED
    assert ReasonCode.OPTION_PRICE_REQUIRED in report.reasons
    assert ReasonCode.OPTION_CONTRACT_NOT_UNIQUE in report.reasons


@pytest.mark.parametrize(
    "price",
    [Decimal("0"), Decimal("-0.05"), Decimal("NaN"), Decimal("Infinity")],
)
def test_stock_option_price_must_be_positive(price: Decimal) -> None:
    report = SignalChecker(policy()).check(
        signal(segment=Segment.FNO, price=price),
        LISTED_OPTION,
    )

    assert report.disposition is CheckDisposition.REJECTED
    assert ReasonCode.OPTION_PRICE_INVALID in report.reasons


def test_stock_option_can_pass_only_the_implemented_core_checks() -> None:
    candidate = signal(
        segment=Segment.FNO,
        price=Decimal("100.00"),
    )

    report = SignalChecker(policy()).check(candidate, LISTED_OPTION)

    assert report.disposition is CheckDisposition.PASSED_CORE
    assert report.trade_ready is False


@pytest.mark.parametrize(
    ("groups", "sources", "message"),
    [
        (frozenset(), frozenset({2001}), "allowed group"),
        (frozenset({1001}), frozenset(), "authorized source"),
    ],
)
def test_source_policy_sets_cannot_be_empty(
    groups: frozenset[int], sources: frozenset[int], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        CheckerPolicy(
            allowed_group_ids=groups,
            authorized_source_ids=sources,
            equity_active=True,
            fno_active=True,
        )
