from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from codexbot.market_data import (
    MarketDataError,
    YahooExchange,
    YahooFinanceMarketData,
)

NOW = datetime(2026, 10, 27, 4, 0, tzinfo=UTC)


class StubTransport:
    def __init__(self, payload: object) -> None:
        self.payload = payload
        self.urls: list[str] = []

    def get_json(self, url: str, *, timeout_seconds: float) -> object:
        assert timeout_seconds == 3.0
        self.urls.append(url)
        return self.payload


def payload(
    *,
    price: object = 1_250.5,
    timestamp: object | None = None,
    previous_minute_close: object = 1_249.0,
    previous_day_close: object = 1_240.0,
) -> object:
    market_timestamp = timestamp if timestamp is not None else int(NOW.timestamp())
    return {
        "chart": {
            "error": None,
            "result": [
                {
                    "meta": {
                        "regularMarketPrice": price,
                        "regularMarketTime": market_timestamp,
                        "currency": "INR",
                        "exchangeName": "NSI",
                        "chartPreviousClose": previous_day_close,
                    },
                    "timestamp": [int(NOW.timestamp()) - 120, int(NOW.timestamp()) - 60],
                    "indicators": {"quote": [{"close": [1248.0, previous_minute_close]}]},
                }
            ],
        }
    }


@pytest.mark.parametrize(
    ("exchange", "expected_ticker"),
    [(YahooExchange.NSE, "RELIANCE.NS"), (YahooExchange.BSE, "RELIANCE.BO")],
)
def test_yahoo_adapter_returns_timestamped_equity_quote(
    exchange: YahooExchange, expected_ticker: str
) -> None:
    transport = StubTransport(payload())
    client = YahooFinanceMarketData(
        transport=transport,
        clock=lambda: NOW + timedelta(milliseconds=50),
        timeout_seconds=3.0,
    )

    quote = client.get_equity_quote("reliance", exchange)

    assert quote.provider == "YAHOO_FINANCE"
    assert quote.ticker == expected_ticker
    assert quote.price == Decimal("1250.5")
    assert quote.observed_at == NOW
    assert quote.received_at == NOW + timedelta(milliseconds=50)
    assert quote.previous_minute_close == Decimal("1249.0")
    assert quote.previous_day_close == Decimal("1240.0")
    assert transport.urls == [
        f"https://query1.finance.yahoo.com/v8/finance/chart/{expected_ticker}?interval=1m&range=1d"
    ]


def test_quote_freshness_requires_caller_supplied_maximum_age() -> None:
    transport = StubTransport(payload(timestamp=int((NOW - timedelta(seconds=5)).timestamp())))
    quote = YahooFinanceMarketData(
        transport=transport, clock=lambda: NOW, timeout_seconds=3.0
    ).get_equity_quote("SBIN", YahooExchange.NSE)

    assert (
        quote.is_fresh(
            evaluated_at=NOW,
            maximum_age=timedelta(seconds=5),
            future_tolerance=timedelta(0),
        )
        is True
    )
    assert (
        quote.is_fresh(
            evaluated_at=NOW,
            maximum_age=timedelta(seconds=4, milliseconds=999),
            future_tolerance=timedelta(0),
        )
        is False
    )


@pytest.mark.parametrize(
    "bad_payload",
    [
        {"chart": {"error": {"code": "Not Found"}, "result": None}},
        {"chart": {"error": None, "result": []}},
        payload(price=0),
        payload(timestamp="not-a-timestamp"),
        payload(previous_minute_close=None),
        payload(previous_day_close=None),
    ],
)
def test_yahoo_adapter_fails_closed_on_invalid_response(bad_payload: object) -> None:
    client = YahooFinanceMarketData(
        transport=StubTransport(bad_payload), clock=lambda: NOW, timeout_seconds=3.0
    )

    with pytest.raises(MarketDataError):
        client.get_equity_quote("SBIN", YahooExchange.NSE)


@pytest.mark.parametrize("symbol", ["", "RELIANCE.NS", "BAD SYMBOL"])
def test_yahoo_symbol_must_be_an_unsuffixed_single_token(symbol: str) -> None:
    client = YahooFinanceMarketData(
        transport=StubTransport(payload()), clock=lambda: NOW, timeout_seconds=3.0
    )

    with pytest.raises(ValueError):
        client.get_equity_quote(symbol, YahooExchange.NSE)
