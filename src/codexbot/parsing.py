"""Conservative, deterministic parsing for approved Telegram message examples."""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from codexbot.models import Action, Segment


class OptionType(StrEnum):
    CE = "CE"
    PE = "PE"


class ParseReason(StrEnum):
    OPTION_BUY_PATTERN = "OPTION_BUY_PATTERN"
    EXIT_INTENT = "EXIT_INTENT"
    WATCHLIST_ONLY = "WATCHLIST_ONLY"
    FUTURE_INTENT = "FUTURE_INTENT"
    NEGATED_INSTRUCTION = "NEGATED_INSTRUCTION"
    STATUS_OR_LOG_MESSAGE = "STATUS_OR_LOG_MESSAGE"
    NO_ACTIONABLE_TEXT = "NO_ACTIONABLE_TEXT"
    UNSUPPORTED_PATTERN = "UNSUPPORTED_PATTERN"
    INVALID_PRICE_RANGE = "INVALID_PRICE_RANGE"


@dataclass(frozen=True, slots=True)
class ParsedMessage:
    action: Action
    segment: Segment | None
    reason: ParseReason
    symbol: str | None = None
    option_strike: Decimal | None = None
    option_type: OptionType | None = None
    expiry_month: int | None = None
    entry_price_lower: Decimal | None = None
    entry_price_upper: Decimal | None = None
    reference_price: Decimal | None = None


class TelegramMessageParser:
    """Parse only message forms approved through supplied examples.

    Unknown, advisory, future-intent, and negated messages fail closed as
    ``Action.UNKNOWN``. Instrument identity and index rejection remain the
    responsibility of the canonical instrument resolver and signal checker.
    """

    def parse(self, text: str | None) -> ParsedMessage:
        if text is None or not text.strip():
            return _unknown(ParseReason.NO_ACTIONABLE_TEXT)

        normalized = _normalize_text(text)
        upper = normalized.upper()

        if _is_status_or_log_message(upper):
            return _unknown(ParseReason.STATUS_OR_LOG_MESSAGE)
        if _NEGATED_INSTRUCTION.search(upper):
            return _unknown(ParseReason.NEGATED_INSTRUCTION)
        if _WATCHLIST.search(upper):
            return _unknown(ParseReason.WATCHLIST_ONLY)
        if _FUTURE_INTENT.search(upper):
            return _unknown(ParseReason.FUTURE_INTENT)

        exit_message = _parse_exit(upper)
        if exit_message is not None:
            return exit_message

        option_match = _OPTION_BUY.search(upper)
        if option_match is None:
            return _unknown(ParseReason.UNSUPPORTED_PATTERN)

        lower = Decimal(option_match.group("price_lower"))
        upper_price_text = option_match.group("price_upper")
        upper_price = Decimal(upper_price_text) if upper_price_text else lower
        if lower <= 0 or upper_price <= 0 or upper_price < lower:
            return _unknown(ParseReason.INVALID_PRICE_RANGE)

        month_token = option_match.group("month")
        return ParsedMessage(
            action=Action.BUY,
            segment=Segment.FNO,
            reason=ParseReason.OPTION_BUY_PATTERN,
            symbol=option_match.group("symbol"),
            option_strike=Decimal(option_match.group("strike")),
            option_type=OptionType(option_match.group("option_type")),
            expiry_month=_MONTHS.get(month_token) if month_token else None,
            entry_price_lower=lower,
            entry_price_upper=upper_price,
        )


def _parse_exit(text: str) -> ParsedMessage | None:
    prefix_match = _EXIT_PREFIX.search(text)
    if prefix_match is not None:
        option_type_text = prefix_match.group("option_type")
        strike_text = prefix_match.group("strike")
        return ParsedMessage(
            action=Action.EXIT,
            segment=Segment.FNO if option_type_text else Segment.EQUITY,
            reason=ParseReason.EXIT_INTENT,
            symbol=prefix_match.group("symbol"),
            option_strike=Decimal(strike_text) if strike_text else None,
            option_type=OptionType(option_type_text) if option_type_text else None,
            reference_price=_optional_decimal(prefix_match.group("price")),
        )

    infix_match = _EXIT_INFIX.search(text)
    if infix_match is None:
        return None
    return ParsedMessage(
        action=Action.EXIT,
        segment=Segment.EQUITY,
        reason=ParseReason.EXIT_INTENT,
        symbol=infix_match.group("symbol"),
        reference_price=_optional_decimal(infix_match.group("price")),
    )


def _normalize_text(text: str) -> str:
    return text.replace("\u00a0", " ").replace("\r\n", "\n").replace("\r", "\n").strip()


def _is_status_or_log_message(text: str) -> bool:
    first_line = text.split("\n", maxsplit=1)[0]
    return "BLOCKED:" in first_line or "SIGNAL RECEIVED:" in first_line


def _optional_decimal(value: str | None) -> Decimal | None:
    return Decimal(value) if value is not None else None


def _unknown(reason: ParseReason) -> ParsedMessage:
    return ParsedMessage(action=Action.UNKNOWN, segment=None, reason=reason)


_MONTHS = {
    "JAN": 1,
    "FEB": 2,
    "MAR": 3,
    "APR": 4,
    "MAY": 5,
    "JUN": 6,
    "JUL": 7,
    "AUG": 8,
    "SEP": 9,
    "OCT": 10,
    "NOV": 11,
    "DEC": 12,
}
_SYMBOL = r"[A-Z][A-Z0-9&.-]*"
_NUMBER = r"\d+(?:\.\d+)?"
_MONTH = r"JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC"

_OPTION_BUY = re.compile(
    rf"(?m)^\s*#?(?P<symbol>{_SYMBOL})\s+"
    rf"(?P<strike>{_NUMBER})\s*(?P<option_type>CE|PE)"
    rf"(?:\s+(?P<month>{_MONTH}))?\s*@\s*"
    rf"(?P<price_lower>{_NUMBER})"
    rf"(?:\s*(?:-|TO)\s*(?P<price_upper>{_NUMBER}))?\b"
)
_EXIT_PREFIX = re.compile(
    rf"(?m)^\s*(?:CLOSE|EXIT)\s+#?(?P<symbol>{_SYMBOL})"
    rf"(?:\s+(?P<strike>{_NUMBER})\s*(?P<option_type>CE|PE))?"
    rf"(?:\s+(?:AT|@)\s*(?P<price>{_NUMBER}))?\b"
)
_EXIT_INFIX = re.compile(
    rf"(?m)^\s*#?(?P<symbol>{_SYMBOL})\s+EXIT"
    rf"(?:\s+(?:AT|@)\s*(?P<price>{_NUMBER}))?\b"
)
_NEGATED_INSTRUCTION = re.compile(r"\b(?:DON'T|DONT|DO\s+NOT)\s+(?:BUY|AVG|AVERAGE)\b")
_WATCHLIST = re.compile(r"\b(?:KEEP\s+)?WATCH\s*LIST\b")
_FUTURE_INTENT = re.compile(r"\b(?:NEXT\s+WEEK|WILL\s+MAKE\s+ENTRY)\b")
