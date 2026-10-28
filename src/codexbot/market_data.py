"""Read-only Yahoo Finance equity quote adapter.

The adapter retrieves market data only. It cannot place or model an order.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Protocol, cast
from urllib.parse import quote as url_quote
from urllib.request import Request, urlopen


class YahooExchange(StrEnum):
    NSE = "NS"
    BSE = "BO"


class MarketDataError(RuntimeError):
    """Raised when a quote cannot be retrieved or proved valid."""


@dataclass(frozen=True, slots=True)
class EquityQuote:
    provider: str
    ticker: str
    price: Decimal
    observed_at: datetime
    received_at: datetime
    currency: str
    exchange_name: str
    previous_minute_close: Decimal
    previous_day_close: Decimal

    def age_at(self, evaluated_at: datetime) -> timedelta:
        return _aware_utc(evaluated_at) - self.observed_at

    def is_fresh(
        self,
        *,
        evaluated_at: datetime,
        maximum_age: timedelta,
        future_tolerance: timedelta,
    ) -> bool:
        """Apply a caller-supplied age limit; no trading age is assumed."""

        if maximum_age < timedelta(0) or future_tolerance < timedelta(0):
            raise ValueError("quote age limits cannot be negative")
        age = self.age_at(evaluated_at)
        return -future_tolerance <= age <= maximum_age


class JsonTransport(Protocol):
    def get_json(self, url: str, *, timeout_seconds: float) -> object: ...


class UrllibJsonTransport:
    """Small standard-library HTTP transport for Yahoo's read-only endpoint."""

    def get_json(self, url: str, *, timeout_seconds: float) -> object:
        request = Request(
            url,
            headers={"Accept": "application/json", "User-Agent": "Codexbot/0.1"},
            method="GET",
        )
        with urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310
            payload = response.read()
        return cast(object, json.loads(payload))


class YahooFinanceMarketData:
    """Retrieve NSE/BSE equity prices from Yahoo Finance chart metadata."""

    _BASE_URL = "https://query1.finance.yahoo.com/v8/finance/chart"

    def __init__(
        self,
        *,
        transport: JsonTransport | None = None,
        clock: Callable[[], datetime] | None = None,
        timeout_seconds: float = 3.0,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self._transport = transport or UrllibJsonTransport()
        self._clock = clock or (lambda: datetime.now(UTC))
        self._timeout_seconds = timeout_seconds

    def get_equity_quote(self, symbol: str, exchange: YahooExchange) -> EquityQuote:
        ticker = _ticker(symbol, exchange)
        encoded_ticker = url_quote(ticker, safe=".")
        url = f"{self._BASE_URL}/{encoded_ticker}?interval=1m&range=1d"
        try:
            payload = self._transport.get_json(url, timeout_seconds=self._timeout_seconds)
            result = _extract_result(payload)
            meta = _mapping(result.get("meta"), "quote metadata")
            price = _positive_decimal(meta.get("regularMarketPrice"), "regularMarketPrice")
            observed_at = _epoch_datetime(meta.get("regularMarketTime"))
            currency = _required_text(meta.get("currency"), "currency")
            exchange_name = _required_text(meta.get("exchangeName"), "exchangeName")
            previous_minute_close = _previous_minute_close(
                result, market_epoch=int(observed_at.timestamp())
            )
            previous_day_close = _positive_decimal(
                meta.get("chartPreviousClose", meta.get("previousClose")),
                "chartPreviousClose",
            )
        except MarketDataError:
            raise
        except Exception as error:
            raise MarketDataError("Yahoo Finance quote request failed") from error

        return EquityQuote(
            provider="YAHOO_FINANCE",
            ticker=ticker,
            price=price,
            observed_at=observed_at,
            received_at=_aware_utc(self._clock()),
            currency=currency,
            exchange_name=exchange_name,
            previous_minute_close=previous_minute_close,
            previous_day_close=previous_day_close,
        )


def _ticker(symbol: str, exchange: YahooExchange) -> str:
    base = symbol.strip().upper()
    if not base:
        raise ValueError("symbol is required")
    if base.endswith(".NS") or base.endswith(".BO"):
        raise ValueError("symbol must not include a Yahoo exchange suffix")
    if any(character.isspace() for character in base):
        raise ValueError("symbol cannot contain whitespace")
    return f"{base}.{exchange.value}"


def _extract_result(payload: object) -> Mapping[str, object]:
    root = _mapping(payload, "response")
    chart = _mapping(root.get("chart"), "chart")
    if chart.get("error") is not None:
        raise MarketDataError("Yahoo Finance returned a chart error")
    result = chart.get("result")
    if not isinstance(result, list) or len(result) != 1:
        raise MarketDataError("Yahoo Finance returned no unique quote result")
    return _mapping(result[0], "chart result")


def _previous_minute_close(result: Mapping[str, object], *, market_epoch: int) -> Decimal:
    timestamps = result.get("timestamp")
    if not isinstance(timestamps, list):
        raise MarketDataError("Yahoo Finance 1-minute timestamps are missing or invalid")
    indicators = _mapping(result.get("indicators"), "indicators")
    quotes = indicators.get("quote")
    if not isinstance(quotes, list) or len(quotes) != 1:
        raise MarketDataError("Yahoo Finance 1-minute quote series is missing or invalid")
    quote_series = _mapping(quotes[0], "1-minute quote series")
    closes = quote_series.get("close")
    if not isinstance(closes, list) or len(closes) != len(timestamps):
        raise MarketDataError("Yahoo Finance 1-minute closes are missing or invalid")
    current_minute = market_epoch - market_epoch % 60
    candidates: list[tuple[int, object]] = []
    for raw_timestamp, raw_close in zip(timestamps, closes, strict=True):
        if isinstance(raw_timestamp, bool) or not isinstance(raw_timestamp, (int, float)):
            raise MarketDataError("Yahoo Finance 1-minute timestamp is invalid")
        timestamp = int(raw_timestamp)
        if timestamp >= current_minute:
            continue
        candidates.append((timestamp, raw_close))
    if not candidates:
        raise MarketDataError("Yahoo Finance previous 1-minute close is unavailable")
    latest_close = max(candidates, key=lambda candidate: candidate[0])[1]
    return _positive_decimal(latest_close, "previous 1-minute close")


def _mapping(value: object, field_name: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise MarketDataError(f"Yahoo Finance {field_name} is missing or invalid")
    return cast(Mapping[str, object], value)


def _positive_decimal(value: object, field_name: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise MarketDataError(f"Yahoo Finance {field_name} is missing or invalid")
    try:
        result = Decimal(str(value))
    except InvalidOperation as error:
        raise MarketDataError(f"Yahoo Finance {field_name} is invalid") from error
    if not result.is_finite() or result <= 0:
        raise MarketDataError(f"Yahoo Finance {field_name} must be positive")
    return result


def _epoch_datetime(value: object) -> datetime:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise MarketDataError("Yahoo Finance regularMarketTime is missing or invalid")
    try:
        return datetime.fromtimestamp(value, tz=UTC)
    except (OverflowError, OSError, ValueError) as error:
        raise MarketDataError("Yahoo Finance regularMarketTime is invalid") from error


def _required_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MarketDataError(f"Yahoo Finance {field_name} is missing or invalid")
    return value.strip()


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime must be timezone-aware")
    return value.astimezone(UTC)
