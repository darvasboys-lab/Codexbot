"""Secret-safe Dhan authentication and read-only account health.

This module intentionally exposes no order placement, modification, cancellation,
position mutation, or simulated-trading operation.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import http.client
import json
import ssl
import struct
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Protocol, cast
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from codexbot.settings import DhanCredentials, SecretValue

_DHAN_AUTH_HOST = "auth.dhan.co"
_DHAN_API_HOST = "api.dhan.co"
_MAX_RESPONSE_BYTES = 1_048_576
_INDIA = ZoneInfo("Asia/Kolkata")


class DhanError(RuntimeError):
    """A sanitized Dhan integration failure safe to record in an audit event."""


@dataclass(frozen=True, slots=True)
class DhanAccessToken:
    """An in-memory access token and its broker-reported expiry."""

    client_id: str = field(repr=False)
    value: SecretValue = field(repr=False)
    expires_at: datetime
    received_at: datetime

    def is_valid_at(self, when: datetime) -> bool:
        return _aware_utc(when, field_name="token validity time") < self.expires_at


@dataclass(frozen=True, slots=True)
class DhanFundLimits:
    """Read-only account values returned by Dhan's Fund Limit endpoint."""

    client_id: str = field(repr=False)
    available_balance: Decimal
    sod_limit: Decimal
    collateral_amount: Decimal
    receivable_amount: Decimal
    utilized_amount: Decimal
    blocked_payout_amount: Decimal
    withdrawable_balance: Decimal
    received_at: datetime


@dataclass(frozen=True, slots=True)
class DhanHealthResult:
    """Non-secret outcome suitable for logging and dashboard display."""

    healthy: bool
    checked_at: datetime
    token_expires_at: datetime | None
    available_balance: Decimal | None
    error_code: str | None


@dataclass(frozen=True, slots=True)
class DhanOrderSnapshot:
    """Strict read-only subset of an order-book row."""

    order_id: str
    correlation_id: str | None
    order_status: str
    transaction_type: str
    exchange_segment: str
    product_type: str
    order_type: str
    trading_symbol: str | None
    security_id: str
    quantity: int
    remaining_quantity: int
    filled_quantity: int
    average_traded_price: Decimal
    received_at: datetime


@dataclass(frozen=True, slots=True)
class DhanTradeSnapshot:
    """Strict read-only subset of a trade-book row."""

    order_id: str
    exchange_order_id: str
    exchange_trade_id: str
    transaction_type: str
    exchange_segment: str
    product_type: str
    order_type: str
    trading_symbol: str
    security_id: str
    traded_quantity: int
    traded_price: Decimal
    exchange_time: str
    received_at: datetime


@dataclass(frozen=True, slots=True)
class DhanPositionSnapshot:
    """Strict read-only subset of a current position row."""

    trading_symbol: str
    security_id: str
    position_type: str
    exchange_segment: str
    product_type: str
    buy_average: Decimal
    buy_quantity: int
    sell_average: Decimal
    sell_quantity: int
    net_quantity: int
    realized_profit: Decimal
    unrealized_profit: Decimal
    received_at: datetime


@dataclass(frozen=True, slots=True)
class DhanReconciliationSnapshot:
    """A bounded, non-atomic observation of broker orders, trades, and positions."""

    orders: tuple[DhanOrderSnapshot, ...]
    trades: tuple[DhanTradeSnapshot, ...]
    positions: tuple[DhanPositionSnapshot, ...]
    started_at: datetime
    completed_at: datetime


class DhanTransport(Protocol):
    """Narrow transport boundary used by unit tests and the HTTPS adapter."""

    def generate_access_token(
        self, *, client_id: str, pin: str, totp: str
    ) -> Mapping[str, object]: ...

    def get_fund_limits(self, *, access_token: str) -> Mapping[str, object]: ...

    def get_order_book(self, *, access_token: str) -> object: ...

    def get_trade_book(self, *, access_token: str) -> object: ...

    def get_positions(self, *, access_token: str) -> object: ...


class DhanHttpsTransport:
    """Bounded HTTPS transport which never reports credential-bearing URLs."""

    def __init__(
        self,
        *,
        connection_timeout_seconds: float = 3.0,
        read_timeout_seconds: float = 5.0,
        connection_factory: Callable[..., http.client.HTTPSConnection] | None = None,
    ) -> None:
        if connection_timeout_seconds <= 0 or read_timeout_seconds <= 0:
            raise ValueError("connection and read timeouts must be positive")
        self._connection_timeout_seconds = connection_timeout_seconds
        self._read_timeout_seconds = read_timeout_seconds
        self._connection_factory = connection_factory or http.client.HTTPSConnection

    def generate_access_token(self, *, client_id: str, pin: str, totp: str) -> Mapping[str, object]:
        query = urlencode({"dhanClientId": client_id, "pin": pin, "totp": totp})
        return _mapping_payload(
            self._request_json(
                host=_DHAN_AUTH_HOST,
                method="POST",
                target=f"/app/generateAccessToken?{query}",
                headers={"Accept": "application/json"},
            )
        )

    def get_fund_limits(self, *, access_token: str) -> Mapping[str, object]:
        return _mapping_payload(self._authenticated_get("/v2/fundlimit", access_token))

    def get_order_book(self, *, access_token: str) -> object:
        return self._authenticated_get("/v2/orders", access_token)

    def get_trade_book(self, *, access_token: str) -> object:
        return self._authenticated_get("/v2/trades", access_token)

    def get_positions(self, *, access_token: str) -> object:
        return self._authenticated_get("/v2/positions", access_token)

    def _authenticated_get(self, target: str, access_token: str) -> object:
        return self._request_json(
            host=_DHAN_API_HOST,
            method="GET",
            target=target,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "access-token": access_token,
            },
        )

    def _request_json(
        self, *, host: str, method: str, target: str, headers: Mapping[str, str]
    ) -> object:
        connection: http.client.HTTPSConnection | None = None
        try:
            connection = self._connection_factory(
                host,
                timeout=self._connection_timeout_seconds,
                context=ssl.create_default_context(),
            )
            connection.request(method, target, headers=dict(headers))
            socket = getattr(connection, "sock", None)
            if socket is not None:
                socket.settimeout(self._read_timeout_seconds)
            response = connection.getresponse()
            body = response.read(_MAX_RESPONSE_BYTES + 1)
            if len(body) > _MAX_RESPONSE_BYTES:
                raise DhanError("DHAN_RESPONSE_TOO_LARGE")
            if not 200 <= response.status < 300:
                raise DhanError(f"DHAN_HTTP_{response.status}")
            try:
                payload = json.loads(body.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise DhanError("DHAN_RESPONSE_INVALID_JSON") from error
            return cast(object, payload)
        except DhanError:
            raise
        except (OSError, http.client.HTTPException) as error:
            raise DhanError("DHAN_TRANSPORT_FAILURE") from error
        finally:
            if connection is not None:
                connection.close()


class DhanReadOnlySession:
    """Generate a token and perform a read-only credential/account health check."""

    def __init__(
        self,
        *,
        credentials: DhanCredentials,
        transport: DhanTransport | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._credentials = credentials
        self._transport = transport or DhanHttpsTransport()
        self._clock = clock or (lambda: datetime.now(UTC))

    def generate_access_token(self) -> DhanAccessToken:
        """Use the documented individual TOTP flow; retain the token in memory only."""

        received_at = _aware_utc(self._clock(), field_name="clock")
        client_id = self._credentials.client_id.reveal()
        code = generate_totp(self._credentials.totp_secret, at=received_at)
        payload = self._transport.generate_access_token(
            client_id=client_id,
            pin=self._credentials.pin.reveal(),
            totp=code,
        )
        response_client_id = _required_text(payload, "dhanClientId")
        if not hmac.compare_digest(response_client_id, client_id):
            raise DhanError("DHAN_CLIENT_ID_MISMATCH")
        expires_at = _parse_dhan_expiry(_required_text(payload, "expiryTime"))
        if expires_at <= received_at:
            raise DhanError("DHAN_TOKEN_ALREADY_EXPIRED")
        return DhanAccessToken(
            client_id=client_id,
            value=SecretValue(_required_text(payload, "accessToken")),
            expires_at=expires_at,
            received_at=received_at,
        )

    def get_fund_limits(self, token: DhanAccessToken) -> DhanFundLimits:
        """Fetch the documented fund-limit resource without changing broker state."""

        received_at = self._validate_read_token(token)
        expected_client_id = self._credentials.client_id.reveal()
        payload = self._transport.get_fund_limits(access_token=token.value.reveal())
        response_client_id = _required_text(payload, "dhanClientId")
        if not hmac.compare_digest(response_client_id, expected_client_id):
            raise DhanError("DHAN_CLIENT_ID_MISMATCH")
        return DhanFundLimits(
            client_id=response_client_id,
            available_balance=_required_decimal(payload, "availabelBalance"),
            sod_limit=_required_decimal(payload, "sodLimit"),
            collateral_amount=_required_decimal(payload, "collateralAmount"),
            receivable_amount=_required_decimal(payload, "receiveableAmount"),
            utilized_amount=_required_decimal(payload, "utilizedAmount"),
            blocked_payout_amount=_required_decimal(payload, "blockedPayoutAmount"),
            withdrawable_balance=_required_decimal(payload, "withdrawableBalance"),
            received_at=received_at,
        )

    def get_order_book(self, token: DhanAccessToken) -> tuple[DhanOrderSnapshot, ...]:
        """Retrieve and validate today's broker order book without mutation."""

        received_at = self._validate_read_token(token)
        rows = _list_payload(self._transport.get_order_book(access_token=token.value.reveal()))
        return tuple(self._parse_order(row, received_at=received_at) for row in rows)

    def get_trade_book(self, token: DhanAccessToken) -> tuple[DhanTradeSnapshot, ...]:
        """Retrieve and validate today's broker trade book without mutation."""

        received_at = self._validate_read_token(token)
        rows = _list_payload(self._transport.get_trade_book(access_token=token.value.reveal()))
        return tuple(self._parse_trade(row, received_at=received_at) for row in rows)

    def get_positions(self, token: DhanAccessToken) -> tuple[DhanPositionSnapshot, ...]:
        """Retrieve and validate current positions without mutation."""

        received_at = self._validate_read_token(token)
        rows = _list_payload(self._transport.get_positions(access_token=token.value.reveal()))
        return tuple(self._parse_position(row, received_at=received_at) for row in rows)

    def get_reconciliation_snapshot(self, token: DhanAccessToken) -> DhanReconciliationSnapshot:
        """Fetch all documented read models; callers must treat it as non-atomic."""

        started_at = _aware_utc(self._clock(), field_name="clock")
        orders = self.get_order_book(token)
        trades = self.get_trade_book(token)
        positions = self.get_positions(token)
        completed_at = _aware_utc(self._clock(), field_name="clock")
        return DhanReconciliationSnapshot(
            orders=orders,
            trades=trades,
            positions=positions,
            started_at=started_at,
            completed_at=completed_at,
        )

    def refresh_and_check(self) -> tuple[DhanAccessToken | None, DhanHealthResult]:
        """Return a token only after authentication and the read-only probe succeed."""

        checked_at = _aware_utc(self._clock(), field_name="clock")
        token: DhanAccessToken | None = None
        try:
            token = self.generate_access_token()
            limits = self.get_fund_limits(token)
            return token, DhanHealthResult(
                healthy=True,
                checked_at=checked_at,
                token_expires_at=token.expires_at,
                available_balance=limits.available_balance,
                error_code=None,
            )
        except DhanError as error:
            return None, DhanHealthResult(
                healthy=False,
                checked_at=checked_at,
                token_expires_at=None,
                available_balance=None,
                error_code=str(error),
            )

    def _validate_read_token(self, token: DhanAccessToken) -> datetime:
        received_at = _aware_utc(self._clock(), field_name="clock")
        expected_client_id = self._credentials.client_id.reveal()
        if not hmac.compare_digest(token.client_id, expected_client_id):
            raise DhanError("DHAN_TOKEN_CLIENT_ID_MISMATCH")
        if not token.is_valid_at(received_at):
            raise DhanError("DHAN_TOKEN_EXPIRED")
        return received_at

    def _validate_row_client(self, row: Mapping[str, object]) -> None:
        if not hmac.compare_digest(
            _required_text(row, "dhanClientId"), self._credentials.client_id.reveal()
        ):
            raise DhanError("DHAN_CLIENT_ID_MISMATCH")

    def _parse_order(
        self, row: Mapping[str, object], *, received_at: datetime
    ) -> DhanOrderSnapshot:
        self._validate_row_client(row)
        return DhanOrderSnapshot(
            order_id=_required_text(row, "orderId"),
            correlation_id=_optional_text(row, "correlationId"),
            order_status=_required_text(row, "orderStatus"),
            transaction_type=_required_text(row, "transactionType"),
            exchange_segment=_required_text(row, "exchangeSegment"),
            product_type=_required_text(row, "productType"),
            order_type=_required_text(row, "orderType"),
            trading_symbol=_optional_text(row, "tradingSymbol"),
            security_id=_required_text(row, "securityId"),
            quantity=_required_integer(row, "quantity", minimum=0),
            remaining_quantity=_required_integer(row, "remainingQuantity", minimum=0),
            filled_quantity=_required_integer(row, "filledQty", minimum=0),
            average_traded_price=_required_decimal(row, "averageTradedPrice"),
            received_at=received_at,
        )

    def _parse_trade(
        self, row: Mapping[str, object], *, received_at: datetime
    ) -> DhanTradeSnapshot:
        self._validate_row_client(row)
        return DhanTradeSnapshot(
            order_id=_required_text(row, "orderId"),
            exchange_order_id=_required_text(row, "exchangeOrderId"),
            exchange_trade_id=_required_text(row, "exchangeTradeId"),
            transaction_type=_required_text(row, "transactionType"),
            exchange_segment=_required_text(row, "exchangeSegment"),
            product_type=_required_text(row, "productType"),
            order_type=_required_text(row, "orderType"),
            trading_symbol=_required_text(row, "tradingSymbol"),
            security_id=_required_text(row, "securityId"),
            traded_quantity=_required_integer(row, "tradedQuantity", minimum=1),
            traded_price=_required_decimal(row, "tradedPrice", strictly_positive=True),
            exchange_time=_required_text(row, "exchangeTime"),
            received_at=received_at,
        )

    def _parse_position(
        self, row: Mapping[str, object], *, received_at: datetime
    ) -> DhanPositionSnapshot:
        self._validate_row_client(row)
        buy_quantity = _required_integer(row, "buyQty", minimum=0)
        sell_quantity = _required_integer(row, "sellQty", minimum=0)
        net_quantity = _required_integer(row, "netQty")
        if net_quantity != buy_quantity - sell_quantity:
            raise DhanError("DHAN_POSITION_QUANTITY_INCONSISTENT")
        return DhanPositionSnapshot(
            trading_symbol=_required_text(row, "tradingSymbol"),
            security_id=_required_text(row, "securityId"),
            position_type=_required_text(row, "positionType"),
            exchange_segment=_required_text(row, "exchangeSegment"),
            product_type=_required_text(row, "productType"),
            buy_average=_required_decimal(row, "buyAvg"),
            buy_quantity=buy_quantity,
            sell_average=_required_decimal(row, "sellAvg"),
            sell_quantity=sell_quantity,
            net_quantity=net_quantity,
            realized_profit=_required_signed_decimal(row, "realizedProfit"),
            unrealized_profit=_required_signed_decimal(row, "unrealizedProfit"),
            received_at=received_at,
        )


def generate_totp(secret: SecretValue, *, at: datetime) -> str:
    """Generate the RFC 6238 SHA-1 six-digit code used by Dhan TOTP setup."""

    instant = _aware_utc(at, field_name="TOTP time")
    normalized = "".join(secret.reveal().split()).upper()
    if not normalized:
        raise DhanError("DHAN_TOTP_SECRET_INVALID")
    padding = "=" * ((8 - len(normalized) % 8) % 8)
    try:
        key = base64.b32decode(normalized + padding, casefold=True)
    except (binascii.Error, ValueError) as error:
        raise DhanError("DHAN_TOTP_SECRET_INVALID") from error
    if not key:
        raise DhanError("DHAN_TOTP_SECRET_INVALID")
    counter = int(instant.timestamp()) // 30
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    binary = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return f"{binary % 1_000_000:06d}"


def _parse_dhan_expiry(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise DhanError("DHAN_TOKEN_EXPIRY_INVALID") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        parsed = parsed.replace(tzinfo=_INDIA)
    return parsed.astimezone(UTC)


def _required_text(payload: Mapping[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise DhanError("DHAN_RESPONSE_MISSING_FIELD")
    return value.strip()


def _required_decimal(
    payload: Mapping[str, object], key: str, *, strictly_positive: bool = False
) -> Decimal:
    value = payload.get(key)
    if isinstance(value, bool) or value is None:
        raise DhanError("DHAN_RESPONSE_MISSING_FIELD")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise DhanError("DHAN_RESPONSE_INVALID_NUMBER") from error
    if not result.is_finite() or result < 0 or (strictly_positive and result == 0):
        raise DhanError("DHAN_RESPONSE_INVALID_NUMBER")
    return result


def _required_signed_decimal(payload: Mapping[str, object], key: str) -> Decimal:
    value = payload.get(key)
    if isinstance(value, bool) or value is None:
        raise DhanError("DHAN_RESPONSE_MISSING_FIELD")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise DhanError("DHAN_RESPONSE_INVALID_NUMBER") from error
    if not result.is_finite():
        raise DhanError("DHAN_RESPONSE_INVALID_NUMBER")
    return result


def _required_integer(
    payload: Mapping[str, object], key: str, *, minimum: int | None = None
) -> int:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise DhanError("DHAN_RESPONSE_INVALID_INTEGER")
    if minimum is not None and value < minimum:
        raise DhanError("DHAN_RESPONSE_INVALID_INTEGER")
    return value


def _optional_text(payload: Mapping[str, object], key: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise DhanError("DHAN_RESPONSE_INVALID_FIELD")
    normalized = value.strip()
    return normalized or None


def _mapping_payload(payload: object) -> Mapping[str, object]:
    if not isinstance(payload, dict):
        raise DhanError("DHAN_RESPONSE_INVALID_SHAPE")
    return cast(Mapping[str, object], payload)


def _list_payload(payload: object) -> tuple[Mapping[str, object], ...]:
    if not isinstance(payload, list):
        raise DhanError("DHAN_RESPONSE_INVALID_SHAPE")
    rows: list[Mapping[str, object]] = []
    for row in payload:
        if not isinstance(row, dict):
            raise DhanError("DHAN_RESPONSE_INVALID_SHAPE")
        rows.append(cast(Mapping[str, object], row))
    return tuple(rows)


def _aware_utc(value: datetime, *, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise DhanError(f"{field_name.upper().replace(' ', '_')}_MUST_BE_TIMEZONE_AWARE")
    return value.astimezone(UTC)
