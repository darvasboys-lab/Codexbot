from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from codexbot import (
    EquityEntryReference,
    EquityPricingPolicy,
    EquityQuote,
    HistoricalPricePoint,
    PricingError,
    calculate_option_entry_price,
    validate_equity_entry_reference,
    validate_historical_price_point,
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
        previous_minute_close=Decimal("99"),
        previous_day_close=Decimal("98"),
    )


def policy() -> EquityPricingPolicy:
    return EquityPricingPolicy(
        percentage_above_market=Decimal("1.25"),
        maximum_market_age=timedelta(seconds=3),
        maximum_local_age=timedelta(seconds=3),
    )


def test_equity_reference_uses_yahoo_price_and_setup_percentage() -> None:
    result = validate_equity_entry_reference(quote(), policy=policy(), evaluated_at=NOW)

    assert isinstance(result, EquityEntryReference)
    assert result.unrounded_limit_ceiling == Decimal("101.2500")
    assert result.percentage_above_market == Decimal("1.25")


@pytest.mark.parametrize(
    ("candidate", "error_code"),
    [
        (quote(market_age=timedelta(seconds=3, microseconds=1)), "YAHOO_MARKET_TIMESTAMP_STALE"),
        (quote(local_age=timedelta(seconds=3, microseconds=1)), "YAHOO_LOCAL_RECEIPT_STALE"),
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
    accepted = quote(market_age=timedelta(seconds=3), local_age=timedelta(seconds=3))
    future = quote(market_age=timedelta(seconds=-2), local_age=timedelta(seconds=-2))

    validate_equity_entry_reference(accepted, policy=policy(), evaluated_at=NOW)
    validate_equity_entry_reference(future, policy=policy(), evaluated_at=NOW)


def test_equity_tick_anomaly_limits_are_inclusive_and_fail_above_limit() -> None:
    minute_boundary = quote(price="103")
    object.__setattr__(minute_boundary, "previous_minute_close", Decimal("100"))
    object.__setattr__(minute_boundary, "previous_day_close", Decimal("100"))
    validate_equity_entry_reference(minute_boundary, policy=policy(), evaluated_at=NOW)

    bad_minute = quote(price="103.01")
    object.__setattr__(bad_minute, "previous_minute_close", Decimal("100"))
    object.__setattr__(bad_minute, "previous_day_close", Decimal("100"))
    with pytest.raises(PricingError, match="YAHOO_TICK_MINUTE_ANOMALY"):
        validate_equity_entry_reference(bad_minute, policy=policy(), evaluated_at=NOW)

    bad_day = quote(price="105.01")
    object.__setattr__(bad_day, "previous_minute_close", Decimal("105"))
    object.__setattr__(bad_day, "previous_day_close", Decimal("100"))
    with pytest.raises(PricingError, match="YAHOO_TICK_DAILY_ANOMALY"):
        validate_equity_entry_reference(bad_day, policy=policy(), evaluated_at=NOW)


def test_daily_history_is_limited_to_24_hours() -> None:
    validate_historical_price_point(
        HistoricalPricePoint(price=Decimal("100"), observed_at=NOW - timedelta(hours=24)),
        evaluated_at=NOW,
    )
    with pytest.raises(PricingError, match="HISTORICAL_PRICE_STALE"):
        validate_historical_price_point(
            HistoricalPricePoint(
                price=Decimal("100"),
                observed_at=NOW - timedelta(hours=24, microseconds=1),
            ),
            evaluated_at=NOW,
        )


def test_equity_policy_rejects_tick_age_above_three_seconds() -> None:
    with pytest.raises(ValueError, match="3-second"):
        EquityPricingPolicy(
            percentage_above_market=Decimal("1"),
            maximum_market_age=timedelta(seconds=4),
            maximum_local_age=timedelta(seconds=3),
        )


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
