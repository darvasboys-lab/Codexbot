from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from codexbot import (
    EquityEntryReference,
    EquityPricingPolicy,
    EquityQuote,
    PricingError,
    calculate_option_entry_price,
    validate_equity_entry_reference,
)

NOW = datetime(2026, 10, 28, 4, 0, tzinfo=UTC)


def quote(
    *,
    price: str = "100",
    market_age: timedelta = timedelta(seconds=1),
    local_age: timedelta = timedelta(milliseconds=100),
    currency: str = "INR",
) -> EquityQuote:
    return EquityQuote(
        provider="YAHOO_FINANCE",
        ticker="SBIN.NS",
        price=Decimal(price),
        observed_at=NOW - market_age,
        received_at=NOW - local_age,
        currency=currency,
        exchange_name="NSI",
    )


def policy() -> EquityPricingPolicy:
    return EquityPricingPolicy(
        percentage_above_market=Decimal("1.25"),
        maximum_market_age=timedelta(seconds=5),
        maximum_local_age=timedelta(seconds=2),
    )


def test_equity_reference_uses_yahoo_price_and_setup_percentage() -> None:
    result = validate_equity_entry_reference(quote(), policy=policy(), evaluated_at=NOW)

    assert isinstance(result, EquityEntryReference)
    assert result.unrounded_limit_ceiling == Decimal("101.2500")
    assert result.percentage_above_market == Decimal("1.25")


@pytest.mark.parametrize(
    ("candidate", "error_code"),
    [
        (quote(market_age=timedelta(seconds=5, microseconds=1)), "YAHOO_MARKET_TIMESTAMP_STALE"),
        (quote(local_age=timedelta(seconds=2, microseconds=1)), "YAHOO_LOCAL_RECEIPT_STALE"),
        (quote(market_age=timedelta(seconds=-2, microseconds=-1)), "YAHOO_MARKET_TIMESTAMP_STALE"),
        (quote(currency="USD"), "YAHOO_CURRENCY_NOT_INR"),
    ],
)
def test_equity_reference_fails_closed_on_unusable_quote(
    candidate: EquityQuote, error_code: str
) -> None:
    with pytest.raises(PricingError, match=error_code):
        validate_equity_entry_reference(candidate, policy=policy(), evaluated_at=NOW)


def test_equity_quote_age_boundaries_are_inclusive() -> None:
    accepted = quote(market_age=timedelta(seconds=5), local_age=timedelta(seconds=2))
    future = quote(market_age=timedelta(seconds=-2), local_age=timedelta(seconds=-2))

    validate_equity_entry_reference(accepted, policy=policy(), evaluated_at=NOW)
    validate_equity_entry_reference(future, policy=policy(), evaluated_at=NOW)


def test_option_entry_multiplies_by_four_percent_and_floors_to_tick() -> None:
    result = calculate_option_entry_price(
        signal_upper_bound=Decimal("35.03"), tick_size=Decimal("0.05")
    )

    assert result.unrounded_ceiling == Decimal("36.4312")
    assert result.limit_price == Decimal("36.40")
    assert result.limit_price <= result.unrounded_ceiling
    assert result.unrounded_ceiling - result.limit_price < result.tick_size


def test_option_entry_preserves_exact_tick_ceiling() -> None:
    result = calculate_option_entry_price(
        signal_upper_bound=Decimal("35"), tick_size=Decimal("0.05")
    )

    assert result.unrounded_ceiling == Decimal("36.40")
    assert result.limit_price == Decimal("36.40")


@pytest.mark.parametrize(
    ("upper", "tick", "error_code"),
    [
        ("0", "0.05", "OPTION_SIGNAL_UPPER_BOUND_INVALID"),
        ("NaN", "0.05", "OPTION_SIGNAL_UPPER_BOUND_INVALID"),
        ("35", "0", "OPTION_TICK_SIZE_INVALID"),
        ("0.01", "1", "OPTION_TICK_ROUNDED_TO_ZERO"),
    ],
)
def test_option_entry_rejects_invalid_or_unrepresentable_values(
    upper: str, tick: str, error_code: str
) -> None:
    with pytest.raises(PricingError, match=error_code):
        calculate_option_entry_price(signal_upper_bound=Decimal(upper), tick_size=Decimal(tick))
