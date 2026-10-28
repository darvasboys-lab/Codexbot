"""Deterministic, side-effect-free entry-price validation and calculation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import ROUND_FLOOR, Decimal

from codexbot.market_data import EquityQuote


class PricingError(ValueError):
    """Raised when a price cannot be proved usable under the configured policy."""


@dataclass(frozen=True, slots=True)
class EquityPricingPolicy:
    """Setup values with no production defaults."""

    percentage_above_market: Decimal
    maximum_market_age: timedelta
    maximum_local_age: timedelta
    future_tolerance: timedelta = timedelta(seconds=2)

    def __post_init__(self) -> None:
        if not self.percentage_above_market.is_finite() or self.percentage_above_market < 0:
            raise ValueError("percentage_above_market must be finite and non-negative")
        if self.maximum_market_age <= timedelta(0):
            raise ValueError("maximum_market_age must be positive")
        if self.maximum_local_age <= timedelta(0):
            raise ValueError("maximum_local_age must be positive")
        if self.future_tolerance < timedelta(0):
            raise ValueError("future_tolerance cannot be negative")


@dataclass(frozen=True, slots=True)
class EquityEntryReference:
    """A validated Yahoo price and unrounded LIMIT ceiling."""

    quote: EquityQuote
    percentage_above_market: Decimal
    unrounded_limit_ceiling: Decimal
    evaluated_at: datetime


@dataclass(frozen=True, slots=True)
class OptionEntryPrice:
    """The approved 4% option ceiling rounded down to a verified tick."""

    signal_upper_bound: Decimal
    unrounded_ceiling: Decimal
    tick_size: Decimal
    limit_price: Decimal


def validate_equity_entry_reference(
    quote: EquityQuote,
    *,
    policy: EquityPricingPolicy,
    evaluated_at: datetime,
) -> EquityEntryReference:
    """Validate Yahoo market/local timestamps and apply the setup percentage."""

    now = _aware_utc(evaluated_at)
    market_age = now - quote.observed_at.astimezone(UTC)
    local_age = now - quote.received_at.astimezone(UTC)
    if not -policy.future_tolerance <= market_age <= policy.maximum_market_age:
        raise PricingError("YAHOO_MARKET_TIMESTAMP_STALE")
    if not -policy.future_tolerance <= local_age <= policy.maximum_local_age:
        raise PricingError("YAHOO_LOCAL_RECEIPT_STALE")
    if quote.currency != "INR":
        raise PricingError("YAHOO_CURRENCY_NOT_INR")
    multiplier = Decimal(1) + policy.percentage_above_market / Decimal(100)
    ceiling = quote.price * multiplier
    if not ceiling.is_finite() or ceiling <= 0:
        raise PricingError("EQUITY_LIMIT_CEILING_INVALID")
    return EquityEntryReference(
        quote=quote,
        percentage_above_market=policy.percentage_above_market,
        unrounded_limit_ceiling=ceiling,
        evaluated_at=now,
    )


def calculate_option_entry_price(
    *, signal_upper_bound: Decimal, tick_size: Decimal
) -> OptionEntryPrice:
    """Multiply by 1.04 and floor to a verified price tick without exceeding it."""

    if not signal_upper_bound.is_finite() or signal_upper_bound <= 0:
        raise PricingError("OPTION_SIGNAL_UPPER_BOUND_INVALID")
    if not tick_size.is_finite() or tick_size <= 0:
        raise PricingError("OPTION_TICK_SIZE_INVALID")
    ceiling = signal_upper_bound * Decimal("1.04")
    tick_count = (ceiling / tick_size).to_integral_value(rounding=ROUND_FLOOR)
    price = tick_count * tick_size
    if price <= 0:
        raise PricingError("OPTION_TICK_ROUNDED_TO_ZERO")
    return OptionEntryPrice(
        signal_upper_bound=signal_upper_bound,
        unrounded_ceiling=ceiling,
        tick_size=tick_size,
        limit_price=price,
    )


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise PricingError("EVALUATION_TIME_MUST_BE_TIMEZONE_AWARE")
    return value.astimezone(UTC)
