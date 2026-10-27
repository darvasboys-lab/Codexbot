"""Read-only resolver for Dhan's official detailed instrument-master CSV."""

from __future__ import annotations

import csv
import io
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from pathlib import Path

from codexbot.models import Action, InstrumentFacts, InstrumentKind, Segment
from codexbot.parsing import OptionType, ParsedMessage


class InstrumentMasterError(ValueError):
    """Raised when the official master schema or an eligible row is invalid."""


class Exchange(StrEnum):
    NSE = "NSE"
    BSE = "BSE"


@dataclass(frozen=True, slots=True)
class DhanInstrument:
    exchange: Exchange
    segment: str
    security_id: str
    isin: str | None
    instrument_code: str
    kind: InstrumentKind
    underlying_security_id: str | None
    underlying_symbol: str
    display_name: str
    series: str | None
    lot_size: Decimal
    expiry_date: date | None
    strike_price: Decimal | None
    option_type: OptionType | None
    tick_size_raw: Decimal
    expiry_flag: str | None
    buy_sell_indicator: str
    mtf_leverage: Decimal | None

    def is_listed_for_buy(self, *, as_of: date) -> bool:
        if self.buy_sell_indicator != "A":
            return False
        return self.expiry_date is None or self.expiry_date >= as_of


@dataclass(frozen=True, slots=True)
class InstrumentResolution:
    facts: InstrumentFacts
    matches: tuple[DhanInstrument, ...]


class DhanInstrumentResolver:
    """Resolve parsed NSE/BSE equity and option requests without network access."""

    def __init__(
        self,
        instruments: tuple[DhanInstrument, ...],
        *,
        enabled_exchanges: frozenset[Exchange] = frozenset({Exchange.NSE, Exchange.BSE}),
    ) -> None:
        if not enabled_exchanges:
            raise ValueError("at least one exchange must be enabled")
        self._instruments = instruments
        self._enabled_exchanges = enabled_exchanges
        equities: defaultdict[str, list[DhanInstrument]] = defaultdict(list)
        options: defaultdict[str, list[DhanInstrument]] = defaultdict(list)
        for instrument in instruments:
            if instrument.kind is InstrumentKind.EQUITY:
                equities[instrument.underlying_symbol].append(instrument)
            elif instrument.instrument_code in {"OPTSTK", "OPTIDX"}:
                options[instrument.underlying_symbol].append(instrument)
        self._equities_by_symbol = {symbol: tuple(records) for symbol, records in equities.items()}
        self._options_by_symbol = {symbol: tuple(records) for symbol, records in options.items()}

    @classmethod
    def from_csv_text(
        cls,
        text: str,
        *,
        enabled_exchanges: frozenset[Exchange] = frozenset({Exchange.NSE, Exchange.BSE}),
    ) -> DhanInstrumentResolver:
        reader = csv.DictReader(io.StringIO(text.lstrip("\ufeff")))
        _validate_header(reader.fieldnames)
        instruments: list[DhanInstrument] = []
        for row_number, row in enumerate(reader, start=2):
            instrument = _parse_row(row, row_number=row_number)
            if instrument is not None:
                instruments.append(instrument)
        return cls(tuple(instruments), enabled_exchanges=enabled_exchanges)

    @classmethod
    def from_csv_file(
        cls,
        path: str | Path,
        *,
        enabled_exchanges: frozenset[Exchange] = frozenset({Exchange.NSE, Exchange.BSE}),
    ) -> DhanInstrumentResolver:
        text = Path(path).read_text(encoding="utf-8-sig")
        return cls.from_csv_text(text, enabled_exchanges=enabled_exchanges)

    def resolve(self, parsed: ParsedMessage, *, as_of: date) -> InstrumentFacts:
        return self.resolve_details(parsed, as_of=as_of).facts

    def resolve_details(self, parsed: ParsedMessage, *, as_of: date) -> InstrumentResolution:
        if parsed.action is not Action.BUY or parsed.symbol is None or parsed.segment is None:
            return _unresolved()

        if parsed.segment is Segment.EQUITY:
            matches = self._equity_matches(parsed.symbol, as_of=as_of)
        elif (
            parsed.segment is Segment.FNO
            and parsed.option_strike is not None
            and parsed.option_type is not None
        ):
            matches = self._option_matches(parsed, as_of=as_of)
        else:
            return _unresolved()
        return _resolution(matches, as_of=as_of)

    def _equity_matches(self, symbol: str, *, as_of: date) -> tuple[DhanInstrument, ...]:
        canonical_symbol = symbol.strip().upper()
        return tuple(
            instrument
            for instrument in self._equities_by_symbol.get(canonical_symbol, ())
            if instrument.exchange in self._enabled_exchanges
            and instrument.kind is InstrumentKind.EQUITY
            and instrument.underlying_symbol == canonical_symbol
        )

    def _option_matches(
        self,
        parsed: ParsedMessage,
        *,
        as_of: date,
    ) -> tuple[DhanInstrument, ...]:
        assert parsed.symbol is not None
        assert parsed.option_strike is not None
        assert parsed.option_type is not None
        expiry_month = parsed.expiry_month or as_of.month
        require_current_year = parsed.expiry_month is None
        return tuple(
            instrument
            for instrument in self._options_by_symbol.get(parsed.symbol.strip().upper(), ())
            if instrument.exchange in self._enabled_exchanges
            and instrument.kind in {InstrumentKind.STOCK_OPTION, InstrumentKind.INDEX}
            and instrument.underlying_symbol == parsed.symbol.strip().upper()
            and instrument.strike_price == parsed.option_strike
            and instrument.option_type is parsed.option_type
            and instrument.expiry_date is not None
            and instrument.expiry_date.month == expiry_month
            and (not require_current_year or instrument.expiry_date.year == as_of.year)
        )


def _resolution(
    matches: tuple[DhanInstrument, ...],
    *,
    as_of: date,
) -> InstrumentResolution:
    if not matches:
        return _unresolved()
    if len(matches) == 1:
        instrument = matches[0]
        return InstrumentResolution(
            facts=InstrumentFacts(
                resolved=True,
                listed=instrument.is_listed_for_buy(as_of=as_of),
                kind=instrument.kind,
                security_id=instrument.security_id,
                unique_contract=True,
                canonical_underlying_id=(
                    instrument.underlying_security_id
                    if instrument.kind is InstrumentKind.STOCK_OPTION
                    else None
                ),
                exchange=instrument.exchange.value,
                lot_size=instrument.lot_size,
                tick_size_raw=instrument.tick_size_raw,
                expiry_date=instrument.expiry_date,
            ),
            matches=matches,
        )

    kinds = {instrument.kind for instrument in matches}
    kind = next(iter(kinds)) if len(kinds) == 1 else InstrumentKind.UNKNOWN
    underlying_ids = {
        instrument.underlying_security_id
        for instrument in matches
        if instrument.underlying_security_id
    }
    return InstrumentResolution(
        facts=InstrumentFacts(
            resolved=True,
            listed=all(instrument.is_listed_for_buy(as_of=as_of) for instrument in matches),
            kind=kind,
            security_id=None,
            unique_contract=False,
            canonical_underlying_id=(
                next(iter(underlying_ids))
                if kind is InstrumentKind.STOCK_OPTION and len(underlying_ids) == 1
                else None
            ),
        ),
        matches=matches,
    )


def _unresolved() -> InstrumentResolution:
    return InstrumentResolution(
        facts=InstrumentFacts(
            resolved=False,
            listed=False,
            kind=InstrumentKind.UNKNOWN,
            security_id=None,
            unique_contract=False,
        ),
        matches=(),
    )


def _parse_row(row: dict[str | None, str | None], *, row_number: int) -> DhanInstrument | None:
    exchange_text = _text(row, "EXCH_ID")
    segment = _text(row, "SEGMENT")
    instrument_code = _text(row, "INSTRUMENT")
    if (
        exchange_text not in {Exchange.NSE.value, Exchange.BSE.value}
        or segment not in {"E", "D"}
        or instrument_code not in _KIND_BY_CODE
    ):
        return None

    try:
        exchange = Exchange(exchange_text)
        kind = _KIND_BY_CODE[instrument_code]
        expiry = _optional_date(_text(row, "SM_EXPIRY_DATE", required=False))
        option_type_text = _text(row, "OPTION_TYPE", required=False)
        option_type = OptionType(option_type_text) if option_type_text in {"CE", "PE"} else None
        strike = _optional_decimal(_text(row, "STRIKE_PRICE", required=False))
        instrument = DhanInstrument(
            exchange=exchange,
            segment=segment,
            security_id=_text(row, "SECURITY_ID"),
            isin=_optional_text(_text(row, "ISIN", required=False)),
            instrument_code=instrument_code,
            kind=kind,
            underlying_security_id=_optional_text(
                _text(row, "UNDERLYING_SECURITY_ID", required=False)
            ),
            underlying_symbol=_text(row, "UNDERLYING_SYMBOL").upper(),
            display_name=_text(row, "DISPLAY_NAME"),
            series=_optional_text(_text(row, "SERIES", required=False)),
            lot_size=_positive_decimal(_text(row, "LOT_SIZE"), "LOT_SIZE"),
            expiry_date=expiry,
            strike_price=strike,
            option_type=option_type,
            tick_size_raw=_positive_decimal(_text(row, "TICK_SIZE"), "TICK_SIZE"),
            expiry_flag=_optional_text(_text(row, "EXPIRY_FLAG", required=False)),
            buy_sell_indicator=_text(row, "BUY_SELL_INDICATOR"),
            mtf_leverage=_optional_decimal(_text(row, "MTF_LEVERAGE", required=False)),
        )
    except (InstrumentMasterError, ValueError) as error:
        raise InstrumentMasterError(
            f"invalid eligible instrument row {row_number}: {error}"
        ) from error

    if instrument_code in {"OPTSTK", "OPTIDX"} and (
        instrument.expiry_date is None
        or instrument.strike_price is None
        or instrument.option_type is None
        or instrument.underlying_security_id is None
    ):
        raise InstrumentMasterError(
            f"invalid eligible instrument row {row_number}: incomplete option identity"
        )
    return instrument


def _validate_header(fieldnames: Sequence[str] | None) -> None:
    if fieldnames is None:
        raise InstrumentMasterError("instrument master has no CSV header")
    missing = sorted(_REQUIRED_COLUMNS - set(fieldnames))
    if missing:
        raise InstrumentMasterError(f"instrument master missing columns: {', '.join(missing)}")


def _text(
    row: dict[str | None, str | None],
    name: str,
    *,
    required: bool = True,
) -> str:
    value = row.get(name)
    result = value.strip() if value is not None else ""
    if required and not result:
        raise InstrumentMasterError(f"{name} is required")
    return result


def _optional_text(value: str) -> str | None:
    return None if not value or value == "NA" else value


def _optional_decimal(value: str) -> Decimal | None:
    if not value:
        return None
    try:
        result = Decimal(value)
    except InvalidOperation as error:
        raise InstrumentMasterError(f"invalid decimal: {value}") from error
    if not result.is_finite():
        raise InstrumentMasterError(f"non-finite decimal: {value}")
    return result


def _positive_decimal(value: str, field_name: str) -> Decimal:
    result = _optional_decimal(value)
    if result is None or result <= 0:
        raise InstrumentMasterError(f"{field_name} must be positive")
    return result


def _optional_date(value: str) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise InstrumentMasterError(f"invalid date: {value}") from error


_KIND_BY_CODE = {
    "EQUITY": InstrumentKind.EQUITY,
    "OPTSTK": InstrumentKind.STOCK_OPTION,
    "OPTIDX": InstrumentKind.INDEX,
    "FUTSTK": InstrumentKind.STOCK_FUTURE,
    "FUTIDX": InstrumentKind.INDEX,
    "INDEX": InstrumentKind.INDEX,
}
_REQUIRED_COLUMNS = frozenset(
    {
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
    }
)
