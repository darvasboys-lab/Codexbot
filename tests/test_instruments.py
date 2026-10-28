import csv
import io
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from codexbot import (
    Action,
    CheckerPolicy,
    DhanInstrumentResolver,
    Exchange,
    InstrumentKind,
    InstrumentMasterError,
    ParsedMessage,
    ParseReason,
    Segment,
    SignalChecker,
    SignalProcessor,
    SQLiteJournal,
    TelegramEnvelope,
    TelegramMessageParser,
)

AS_OF = date(2026, 10, 27)
HEADER = (
    "EXCH_ID",
    "SEGMENT",
    "SECURITY_ID",
    "ISIN",
    "INSTRUMENT",
    "UNDERLYING_SECURITY_ID",
    "UNDERLYING_SYMBOL",
    "DISPLAY_NAME",
    "SERIES",
    "LOT_SIZE",
    "SM_EXPIRY_DATE",
    "STRIKE_PRICE",
    "OPTION_TYPE",
    "TICK_SIZE",
    "EXPIRY_FLAG",
    "BUY_SELL_INDICATOR",
    "MTF_LEVERAGE",
)


def instrument_row(**overrides: str) -> dict[str, str]:
    row = {
        "EXCH_ID": "NSE",
        "SEGMENT": "D",
        "SECURITY_ID": "62508",
        "ISIN": "NA",
        "INSTRUMENT": "OPTSTK",
        "UNDERLYING_SECURITY_ID": "21174",
        "UNDERLYING_SYMBOL": "CDSL",
        "DISPLAY_NAME": "CDSL 27 OCT 1400 CALL",
        "SERIES": "NA",
        "LOT_SIZE": "475.0",
        "SM_EXPIRY_DATE": "2026-10-27",
        "STRIKE_PRICE": "1400.00000",
        "OPTION_TYPE": "CE",
        "TICK_SIZE": "5.0000",
        "EXPIRY_FLAG": "M",
        "BUY_SELL_INDICATOR": "A",
        "MTF_LEVERAGE": "0",
    }
    row.update(overrides)
    return row


def master_text(*rows: dict[str, str]) -> str:
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=HEADER, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue()


def test_resolves_current_official_cds_option_fields() -> None:
    resolver = DhanInstrumentResolver.from_csv_text(master_text(instrument_row()))
    parsed = TelegramMessageParser().parse("CDSL 1400CE OCT @33-35")

    resolution = resolver.resolve_details(parsed, as_of=AS_OF)

    assert len(resolution.matches) == 1
    assert resolution.facts.resolved is True
    assert resolution.facts.listed is True
    assert resolution.facts.kind is InstrumentKind.STOCK_OPTION
    assert resolution.facts.security_id == "62508"
    assert resolution.facts.canonical_underlying_id == "21174"
    assert resolution.facts.exchange == "NSE"
    assert resolution.facts.lot_size == Decimal("475.0")
    assert resolution.facts.tick_size_raw == Decimal("5.0000")
    assert resolution.facts.expiry_date == AS_OF


def test_omitted_month_uses_current_calendar_month() -> None:
    resolver = DhanInstrumentResolver.from_csv_text(
        master_text(
            instrument_row(),
            instrument_row(
                SECURITY_ID="83247",
                DISPLAY_NAME="CDSL 23 NOV 1400 CALL",
                SM_EXPIRY_DATE="2026-11-23",
            ),
        )
    )

    facts = resolver.resolve(TelegramMessageParser().parse("CDSL 1400CE @33-35"), as_of=AS_OF)

    assert facts.unique_contract is True
    assert facts.security_id == "62508"


def test_explicit_month_selects_that_month_without_guessing_year() -> None:
    resolver = DhanInstrumentResolver.from_csv_text(
        master_text(
            instrument_row(),
            instrument_row(
                SECURITY_ID="83247",
                DISPLAY_NAME="CDSL 23 NOV 1400 CALL",
                SM_EXPIRY_DATE="2026-11-23",
            ),
        )
    )

    facts = resolver.resolve(TelegramMessageParser().parse("CDSL 1400CE NOV @33-35"), as_of=AS_OF)

    assert facts.unique_contract is True
    assert facts.security_id == "83247"


def test_explicit_month_without_year_rejects_multiple_years() -> None:
    resolver = DhanInstrumentResolver.from_csv_text(
        master_text(
            instrument_row(),
            instrument_row(
                SECURITY_ID="future-year",
                SM_EXPIRY_DATE="2027-10-28",
            ),
        )
    )

    facts = resolver.resolve(TelegramMessageParser().parse("CDSL 1400CE OCT @33-35"), as_of=AS_OF)

    assert facts.unique_contract is False
    assert facts.security_id is None


def test_multiple_matching_contracts_fail_unique_resolution() -> None:
    resolver = DhanInstrumentResolver.from_csv_text(
        master_text(
            instrument_row(),
            instrument_row(SECURITY_ID="62509"),
        )
    )

    facts = resolver.resolve(TelegramMessageParser().parse("CDSL 1400CE OCT @33-35"), as_of=AS_OF)

    assert facts.resolved is True
    assert facts.unique_contract is False
    assert facts.security_id is None
    assert facts.kind is InstrumentKind.STOCK_OPTION
    assert facts.canonical_underlying_id == "21174"


def test_unlisted_contract_resolves_but_fails_listing_fact() -> None:
    resolver = DhanInstrumentResolver.from_csv_text(
        master_text(instrument_row(BUY_SELL_INDICATOR="N"))
    )

    facts = resolver.resolve(TelegramMessageParser().parse("CDSL 1400CE OCT @33-35"), as_of=AS_OF)

    assert facts.resolved is True
    assert facts.listed is False
    assert facts.security_id == "62508"


def test_expired_contract_resolves_but_fails_listing_fact() -> None:
    resolver = DhanInstrumentResolver.from_csv_text(
        master_text(instrument_row(SM_EXPIRY_DATE="2025-10-30"))
    )

    facts = resolver.resolve(TelegramMessageParser().parse("CDSL 1400CE OCT @33-35"), as_of=AS_OF)

    assert facts.resolved is True
    assert facts.listed is False


def test_verified_index_option_is_classified_as_index() -> None:
    sensex = instrument_row(
        EXCH_ID="BSE",
        SECURITY_ID="864899",
        INSTRUMENT="OPTIDX",
        UNDERLYING_SECURITY_ID="1",
        UNDERLYING_SYMBOL="SENSEX",
        DISPLAY_NAME="SENSEX 29 OCT 74500 CALL",
        LOT_SIZE="20.0",
        SM_EXPIRY_DATE="2026-10-29",
        STRIKE_PRICE="74500.00000",
    )
    resolver = DhanInstrumentResolver.from_csv_text(master_text(sensex))

    facts = resolver.resolve(TelegramMessageParser().parse("SENSEX 74500CE @450-460"), as_of=AS_OF)

    assert facts.resolved is True
    assert facts.kind is InstrumentKind.INDEX
    assert facts.exchange == "BSE"


def test_equity_across_two_exchanges_is_ambiguous_until_exchange_is_configured() -> None:
    nse = instrument_row(
        SEGMENT="E",
        SECURITY_ID="21174",
        ISIN="INE736A01011",
        INSTRUMENT="EQUITY",
        UNDERLYING_SECURITY_ID="",
        DISPLAY_NAME="CDSL",
        SERIES="EQ",
        LOT_SIZE="1.0",
        SM_EXPIRY_DATE="",
        STRIKE_PRICE="",
        OPTION_TYPE="",
        EXPIRY_FLAG="NA",
    )
    bse = dict(nse, EXCH_ID="BSE", SECURITY_ID="201232", SERIES="NS")
    text = master_text(nse, bse)

    # The parser has no approved equity BUY form yet, so exercise the resolver's
    # equity branch with an explicit domain value rather than parsing new syntax.
    equity_request = ParsedMessage(
        action=Action.BUY,
        segment=Segment.EQUITY,
        reason=ParseReason.OPTION_BUY_PATTERN,
        symbol="CDSL",
    )
    ambiguous = DhanInstrumentResolver.from_csv_text(text).resolve(equity_request, as_of=AS_OF)
    nse_only = DhanInstrumentResolver.from_csv_text(
        text, enabled_exchanges=frozenset({Exchange.NSE})
    ).resolve(equity_request, as_of=AS_OF)

    assert ambiguous.unique_contract is False
    assert ambiguous.security_id is None
    assert nse_only.unique_contract is True
    assert nse_only.security_id == "21174"


def test_missing_schema_column_fails_closed() -> None:
    text = master_text(instrument_row()).replace("UNDERLYING_SECURITY_ID,", "", 1)

    with pytest.raises(InstrumentMasterError, match="missing columns"):
        DhanInstrumentResolver.from_csv_text(text)


def test_invalid_eligible_numeric_field_fails_closed() -> None:
    with pytest.raises(InstrumentMasterError, match="invalid eligible instrument row"):
        DhanInstrumentResolver.from_csv_text(master_text(instrument_row(LOT_SIZE="bad")))


def test_dhan_resolver_feeds_test_safe_processor(tmp_path: Path) -> None:
    now = datetime(2026, 10, 27, 4, 0, tzinfo=UTC)
    resolver = DhanInstrumentResolver.from_csv_text(master_text(instrument_row()))
    journal = SQLiteJournal(tmp_path / "codexbot.sqlite3", clock=lambda: now)
    journal.initialize()
    journal.set_emergency_stop(
        engaged=False,
        reason="test fixture enables validation flow",
        actor="test-suite",
    )
    signal_processor = SignalProcessor(
        journal=journal,
        parser=TelegramMessageParser(),
        checker=SignalChecker(
            CheckerPolicy(
                allowed_group_ids=frozenset({1001}),
                authorized_source_ids=frozenset({2001}),
                equity_active=True,
                fno_active=True,
            )
        ),
        instrument_resolver=resolver,
    )

    result = signal_processor.process(
        TelegramEnvelope(
            source_group_id=1001,
            source_sender_or_channel_id=2001,
            telegram_message_id=1,
            sent_at=now,
            text="CDSL 1400CE OCT @33-35",
        )
    )

    assert result.instrument is not None
    assert result.instrument.security_id == "62508"
    assert result.duplicate_claim is not None
    assert result.duplicate_claim.accepted is True
    assert result.trade_ready is False
