from datetime import UTC, datetime
from decimal import Decimal

import pytest

from codexbot import (
    Action,
    CheckDisposition,
    CheckerPolicy,
    InstrumentFacts,
    InstrumentKind,
    NormalizedSignal,
    OptionType,
    ParseReason,
    ReasonCode,
    Segment,
    SignalChecker,
    TelegramMessageParser,
)

NOW = datetime(2026, 10, 27, 17, 35, tzinfo=UTC)

CDSL_OPTION = """CDSL 1400CE OCT @33-35

SL_10

Target-100+

3 weeks holding

Go with limited qty if any chance we may need to avg"""

SENSEX_OPTION = """Sensex 74500CE@ 450-460

SL-360

Target-820,1100

a bit risky so add limited qty

Positional"""


def test_cds_option_message_is_parsed_using_upper_entry_bound() -> None:
    parsed = TelegramMessageParser().parse(CDSL_OPTION)

    assert parsed.action is Action.BUY
    assert parsed.segment is Segment.FNO
    assert parsed.reason is ParseReason.OPTION_BUY_PATTERN
    assert parsed.symbol == "CDSL"
    assert parsed.option_strike == Decimal("1400")
    assert parsed.option_type is OptionType.CE
    assert parsed.expiry_month == 10
    assert parsed.entry_price_lower == Decimal("33")
    assert parsed.entry_price_upper == Decimal("35")


def test_telegram_sl_target_and_position_text_do_not_change_option_entry() -> None:
    parsed = TelegramMessageParser().parse(CDSL_OPTION)

    assert parsed.entry_price_upper == Decimal("35")
    assert parsed.reference_price is None


def test_sensex_message_is_parsed_then_core_rejects_verified_index() -> None:
    parsed = TelegramMessageParser().parse(SENSEX_OPTION)
    assert parsed.action is Action.BUY
    assert parsed.symbol == "SENSEX"
    assert parsed.entry_price_upper == Decimal("460")
    assert parsed.expiry_month is None
    assert parsed.segment is Segment.FNO

    signal = NormalizedSignal(
        source_group_id=1001,
        source_sender_or_channel_id=2001,
        telegram_message_id=1,
        sent_at=NOW,
        first_durable_received_at=NOW,
        is_forwarded=False,
        forwarded_from_source_id=None,
        action=parsed.action,
        segment=parsed.segment,
        symbol=parsed.symbol,
        stated_price=parsed.entry_price_upper,
    )
    index_facts = InstrumentFacts(
        resolved=True,
        listed=True,
        kind=InstrumentKind.INDEX,
        security_id="13",
        unique_contract=True,
    )
    report = SignalChecker(
        CheckerPolicy(
            allowed_group_ids=frozenset({1001}),
            authorized_source_ids=frozenset({2001}),
            equity_active=True,
            fno_active=True,
        )
    ).check(signal, index_facts)

    assert report.disposition is CheckDisposition.REJECTED
    assert ReasonCode.INDEX_NOT_ALLOWED in report.reasons


@pytest.mark.parametrize(
    ("text", "symbol", "segment", "strike", "option_type", "price"),
    [
        (
            "Close Nifty 24200CE at 52",
            "NIFTY",
            Segment.FNO,
            Decimal("24200"),
            OptionType.CE,
            Decimal("52"),
        ),
        ("JIOFIn exit at 1.7", "JIOFIN", Segment.EQUITY, None, None, Decimal("1.7")),
    ],
)
def test_exit_messages_are_classified_without_becoming_buy_candidates(
    text: str,
    symbol: str,
    segment: Segment,
    strike: Decimal | None,
    option_type: OptionType | None,
    price: Decimal,
) -> None:
    parsed = TelegramMessageParser().parse(text)

    assert parsed.action is Action.EXIT
    assert parsed.reason is ParseReason.EXIT_INTENT
    assert parsed.symbol == symbol
    assert parsed.segment is segment
    assert parsed.option_strike == strike
    assert parsed.option_type is option_type
    assert parsed.reference_price == price


@pytest.mark.parametrize(
    ("text", "reason"),
    [
        (
            "#nifty one more attempt towards 24150-170 will play and then the BO "
            "worst case also we will get CTC exit with out profit so holding with patience",
            ParseReason.UNSUPPORTED_PATTERN,
        ),
        ("Eichermotors 7800CE keep watchlist", ParseReason.WATCHLIST_ONLY),
        (
            "LT next week will make entry for october once solid base forms",
            ParseReason.FUTURE_INTENT,
        ),
        (
            "[🛡️] BLOCKED: No BUY intent detected (casual chat or just a ticker)\n\n"
            "Message: We will have a Webinar at 09:45 PM today  ✍",
            ParseReason.STATUS_OR_LOG_MESSAGE,
        ),
        (
            "[🚀] Signal Received: Don't buy anything as of now, don't avg !!\n"
            "No lumsum investment , continue SIP..\n"
            "Many factors are changing at this point !!",
            ParseReason.STATUS_OR_LOG_MESSAGE,
        ),
        ("Don't buy CDSL 1400CE OCT @33-35", ParseReason.NEGATED_INSTRUCTION),
        (None, ParseReason.NO_ACTIONABLE_TEXT),
        ("", ParseReason.NO_ACTIONABLE_TEXT),
    ],
)
def test_non_actionable_examples_fail_closed(
    text: str | None,
    reason: ParseReason,
) -> None:
    parsed = TelegramMessageParser().parse(text)

    assert parsed.action is Action.UNKNOWN
    assert parsed.segment is None
    assert parsed.reason is reason
    assert parsed.symbol is None


@pytest.mark.parametrize(
    "text",
    [
        "CDSL 1400CE OCT @35-33",
        "CDSL 1400CE OCT @0",
    ],
)
def test_invalid_option_price_range_fails_closed(text: str) -> None:
    parsed = TelegramMessageParser().parse(text)

    assert parsed.action is Action.UNKNOWN
    assert parsed.reason is ParseReason.INVALID_PRICE_RANGE
