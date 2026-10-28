from __future__ import annotations

import http.client
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import cast

import pytest

from codexbot import (
    DhanCredentials,
    DhanError,
    DhanHttpsTransport,
    DhanReadOnlySession,
    SecretValue,
    generate_totp,
)

NOW = datetime(2026, 10, 27, 2, 30, tzinfo=UTC)  # 08:00 Asia/Kolkata


class FakeTransport:
    def __init__(
        self,
        *,
        token_payload: Mapping[str, object] | None = None,
        fund_payload: Mapping[str, object] | None = None,
        orders_payload: object | None = None,
        trades_payload: object | None = None,
        positions_payload: object | None = None,
        error: DhanError | None = None,
    ) -> None:
        self.token_payload = token_payload or token_response()
        self.fund_payload = fund_payload or fund_response()
        self.orders_payload = [] if orders_payload is None else orders_payload
        self.trades_payload = [] if trades_payload is None else trades_payload
        self.positions_payload = [] if positions_payload is None else positions_payload
        self.error = error
        self.auth_call: tuple[str, str, str] | None = None
        self.fund_token: str | None = None

    def generate_access_token(self, *, client_id: str, pin: str, totp: str) -> Mapping[str, object]:
        self.auth_call = (client_id, pin, totp)
        if self.error is not None:
            raise self.error
        return self.token_payload

    def get_fund_limits(self, *, access_token: str) -> Mapping[str, object]:
        self.fund_token = access_token
        if self.error is not None:
            raise self.error
        return self.fund_payload

    def get_order_book(self, *, access_token: str) -> object:
        self.fund_token = access_token
        return self.orders_payload

    def get_trade_book(self, *, access_token: str) -> object:
        self.fund_token = access_token
        return self.trades_payload

    def get_positions(self, *, access_token: str) -> object:
        self.fund_token = access_token
        return self.positions_payload


def credentials() -> DhanCredentials:
    return DhanCredentials(
        client_id=SecretValue("1000000009"),
        pin=SecretValue("123456"),
        totp_secret=SecretValue("JBSWY3DPEHPK3PXP"),
    )


def token_response(**overrides: object) -> dict[str, object]:
    response: dict[str, object] = {
        "dhanClientId": "1000000009",
        "accessToken": "private-jwt",
        "expiryTime": "2026-10-28T08:00:00.000",
    }
    response.update(overrides)
    return response


def fund_response(**overrides: object) -> dict[str, object]:
    response: dict[str, object] = {
        "dhanClientId": "1000000009",
        "availabelBalance": 98_440.0,
        "sodLimit": 113_642,
        "collateralAmount": 0.0,
        "receiveableAmount": 0.0,
        "utilizedAmount": 15_202.0,
        "blockedPayoutAmount": 0.0,
        "withdrawableBalance": 90_000.0,
    }
    response.update(overrides)
    return response


def order_row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "dhanClientId": "1000000009",
        "orderId": "112111182198",
        "correlationId": "codexbot-abc",
        "orderStatus": "PART_TRADED",
        "transactionType": "BUY",
        "exchangeSegment": "NSE_EQ",
        "productType": "CNC",
        "orderType": "LIMIT",
        "tradingSymbol": "TCS",
        "securityId": "11536",
        "quantity": 40,
        "remainingQuantity": 25,
        "filledQty": 15,
        "averageTradedPrice": 3345.8,
    }
    row.update(overrides)
    return row


def trade_row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "dhanClientId": "1000000009",
        "orderId": "112111182198",
        "exchangeOrderId": "15112111182045",
        "exchangeTradeId": "15112111182046",
        "transactionType": "BUY",
        "exchangeSegment": "NSE_EQ",
        "productType": "CNC",
        "orderType": "LIMIT",
        "tradingSymbol": "TCS",
        "securityId": "11536",
        "tradedQuantity": 15,
        "tradedPrice": 3345.8,
        "exchangeTime": "2026-10-28 09:20:06",
    }
    row.update(overrides)
    return row


def position_row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "dhanClientId": "1000000009",
        "tradingSymbol": "TCS",
        "securityId": "11536",
        "positionType": "LONG",
        "exchangeSegment": "NSE_EQ",
        "productType": "CNC",
        "buyAvg": 3345.8,
        "buyQty": 40,
        "sellAvg": 3350.0,
        "sellQty": 10,
        "netQty": 30,
        "realizedProfit": 42.0,
        "unrealizedProfit": -120.5,
    }
    row.update(overrides)
    return row


def test_totp_matches_rfc_6238_sha1_vector_truncated_to_six_digits() -> None:
    # RFC 6238's SHA-1 test secret and T=59 produce 94287082 at eight digits.
    secret = SecretValue("GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ")

    code = generate_totp(secret, at=datetime.fromtimestamp(59, tz=UTC))

    assert code == "287082"


def test_totp_rejects_invalid_secret_without_echoing_it() -> None:
    invalid = "invalid-secret!"

    with pytest.raises(DhanError, match="DHAN_TOTP_SECRET_INVALID") as caught:
        generate_totp(SecretValue(invalid), at=NOW)

    assert invalid not in str(caught.value)


def test_generate_token_validates_identity_and_interprets_naive_expiry_as_ist() -> None:
    transport = FakeTransport()
    session = DhanReadOnlySession(credentials=credentials(), transport=transport, clock=lambda: NOW)

    token = session.generate_access_token()

    assert token.expires_at == datetime(2026, 10, 28, 2, 30, tzinfo=UTC)
    assert token.received_at == NOW
    assert repr(token).find("private-jwt") == -1
    assert transport.auth_call is not None
    assert transport.auth_call[:2] == ("1000000009", "123456")
    assert len(transport.auth_call[2]) == 6


def test_generate_token_rejects_wrong_client_and_expired_token() -> None:
    wrong_client = FakeTransport(token_payload=token_response(dhanClientId="different"))
    expired = FakeTransport(token_payload=token_response(expiryTime="2026-10-27T07:59:59"))

    with pytest.raises(DhanError, match="DHAN_CLIENT_ID_MISMATCH"):
        DhanReadOnlySession(
            credentials=credentials(), transport=wrong_client, clock=lambda: NOW
        ).generate_access_token()
    with pytest.raises(DhanError, match="DHAN_TOKEN_ALREADY_EXPIRED"):
        DhanReadOnlySession(
            credentials=credentials(), transport=expired, clock=lambda: NOW
        ).generate_access_token()


def test_read_only_fund_probe_parses_documented_fields() -> None:
    transport = FakeTransport()
    session = DhanReadOnlySession(credentials=credentials(), transport=transport, clock=lambda: NOW)
    token = session.generate_access_token()

    limits = session.get_fund_limits(token)

    assert limits.available_balance == Decimal("98440.0")
    assert limits.utilized_amount == Decimal("15202.0")
    assert limits.received_at == NOW
    assert transport.fund_token == "private-jwt"


def test_order_book_accepts_documented_blank_trading_symbol() -> None:
    transport = FakeTransport(orders_payload=[order_row(tradingSymbol="")])
    session = DhanReadOnlySession(credentials=credentials(), transport=transport, clock=lambda: NOW)
    token = session.generate_access_token()

    orders = session.get_order_book(token)

    assert orders[0].trading_symbol is None


@pytest.mark.parametrize(
    ("overrides", "error_code"),
    [
        ({"availabelBalance": None}, "DHAN_RESPONSE_MISSING_FIELD"),
        ({"availabelBalance": -1}, "DHAN_RESPONSE_INVALID_NUMBER"),
        ({"availabelBalance": "nan"}, "DHAN_RESPONSE_INVALID_NUMBER"),
        ({"dhanClientId": "other"}, "DHAN_CLIENT_ID_MISMATCH"),
    ],
)
def test_read_only_fund_probe_fails_closed(overrides: dict[str, object], error_code: str) -> None:
    transport = FakeTransport(fund_payload=fund_response(**overrides))
    session = DhanReadOnlySession(credentials=credentials(), transport=transport, clock=lambda: NOW)
    token = session.generate_access_token()

    with pytest.raises(DhanError, match=error_code):
        session.get_fund_limits(token)


def test_read_only_fund_probe_refuses_expired_token_before_transport() -> None:
    times = iter((NOW, NOW + timedelta(days=2)))
    transport = FakeTransport()
    session = DhanReadOnlySession(
        credentials=credentials(), transport=transport, clock=lambda: next(times)
    )
    token = session.generate_access_token()

    with pytest.raises(DhanError, match="DHAN_TOKEN_EXPIRED"):
        session.get_fund_limits(token)

    assert transport.fund_token is None


def test_refresh_and_check_returns_non_secret_health_and_no_token_on_failure() -> None:
    transport = FakeTransport(error=DhanError("DHAN_HTTP_401"))
    session = DhanReadOnlySession(credentials=credentials(), transport=transport, clock=lambda: NOW)

    token, health = session.refresh_and_check()

    assert token is None
    assert health.healthy is False
    assert health.error_code == "DHAN_HTTP_401"
    assert "123456" not in repr(health)
    assert "private-jwt" not in repr(health)


def test_dhan_read_only_boundary_has_no_order_methods() -> None:
    session = DhanReadOnlySession(
        credentials=credentials(), transport=FakeTransport(), clock=lambda: NOW
    )

    assert not hasattr(session, "place_order")
    assert not hasattr(session, "modify_order")
    assert not hasattr(session, "cancel_order")


def test_read_only_reconciliation_snapshots_parse_documented_subsets() -> None:
    transport = FakeTransport(
        orders_payload=[order_row()],
        trades_payload=[trade_row()],
        positions_payload=[position_row()],
    )
    session = DhanReadOnlySession(credentials=credentials(), transport=transport, clock=lambda: NOW)
    token = session.generate_access_token()

    orders = session.get_order_book(token)
    trades = session.get_trade_book(token)
    positions = session.get_positions(token)

    assert orders[0].order_status == "PART_TRADED"
    assert orders[0].filled_quantity == 15
    assert orders[0].remaining_quantity == 25
    assert trades[0].traded_quantity == 15
    assert trades[0].traded_price == Decimal("3345.8")
    assert positions[0].net_quantity == 30
    assert positions[0].unrealized_profit == Decimal("-120.5")
    assert transport.fund_token == "private-jwt"

    snapshot = session.get_reconciliation_snapshot(token)
    assert snapshot.orders[0].order_id == "112111182198"
    assert snapshot.trades[0].exchange_trade_id == "15112111182046"
    assert snapshot.positions[0].security_id == "11536"
    assert snapshot.started_at == NOW
    assert snapshot.completed_at == NOW


@pytest.mark.parametrize(
    ("resource", "payload", "error_code"),
    [
        ("orders", {}, "DHAN_RESPONSE_INVALID_SHAPE"),
        ("orders", [order_row(filledQty=-1)], "DHAN_RESPONSE_INVALID_INTEGER"),
        ("orders", [order_row(dhanClientId="other")], "DHAN_CLIENT_ID_MISMATCH"),
        ("trades", [trade_row(tradedQuantity=0)], "DHAN_RESPONSE_INVALID_INTEGER"),
        ("trades", [trade_row(tradedPrice=0)], "DHAN_RESPONSE_INVALID_NUMBER"),
        (
            "positions",
            [position_row(netQty=31)],
            "DHAN_POSITION_QUANTITY_INCONSISTENT",
        ),
        ("positions", [position_row(realizedProfit="nan")], "DHAN_RESPONSE_INVALID_NUMBER"),
    ],
)
def test_read_only_reconciliation_snapshots_fail_closed(
    resource: str, payload: object, error_code: str
) -> None:
    if resource == "orders":
        transport = FakeTransport(orders_payload=payload)
    elif resource == "trades":
        transport = FakeTransport(trades_payload=payload)
    else:
        transport = FakeTransport(positions_payload=payload)
    session = DhanReadOnlySession(credentials=credentials(), transport=transport, clock=lambda: NOW)
    token = session.generate_access_token()

    with pytest.raises(DhanError, match=error_code):
        if resource == "orders":
            session.get_order_book(token)
        elif resource == "trades":
            session.get_trade_book(token)
        else:
            session.get_positions(token)


class FakeHttpResponse:
    status = 401

    def read(self, amount: int) -> bytes:
        del amount
        return b'{"error":"bad credentials"}'


class FakeHttpConnection:
    requested_target = ""
    requested_headers: dict[str, str] = {}

    def __init__(self, *args: object, **kwargs: object) -> None:
        del args, kwargs

    def request(self, method: str, target: str, *, headers: dict[str, str]) -> None:
        del method
        type(self).requested_target = target
        type(self).requested_headers = headers

    def getresponse(self) -> FakeHttpResponse:
        return FakeHttpResponse()

    def close(self) -> None:
        return None


class EmptyListHttpResponse:
    status = 200

    def read(self, amount: int) -> bytes:
        del amount
        return b"[]"


class RecordingSuccessConnection:
    requested_targets: list[str] = []
    requested_methods: list[str] = []
    requested_headers: dict[str, str] = {}

    def __init__(self, *args: object, **kwargs: object) -> None:
        del args, kwargs

    def request(self, method: str, target: str, *, headers: dict[str, str]) -> None:
        type(self).requested_methods.append(method)
        type(self).requested_targets.append(target)
        type(self).requested_headers = headers

    def getresponse(self) -> EmptyListHttpResponse:
        return EmptyListHttpResponse()

    def close(self) -> None:
        return None


def test_https_transport_error_does_not_echo_query_credentials() -> None:
    transport = DhanHttpsTransport(
        connection_factory=cast(type[http.client.HTTPSConnection], FakeHttpConnection)
    )

    with pytest.raises(DhanError) as caught:
        transport.generate_access_token(client_id="client-secret", pin="pin-secret", totp="654321")

    assert str(caught.value) == "DHAN_HTTP_401"
    assert "client-secret" not in str(caught.value)
    assert "pin-secret" not in str(caught.value)
    assert "654321" not in str(caught.value)
    assert "dhanClientId=client-secret" in FakeHttpConnection.requested_target


def test_https_reconciliation_transport_uses_only_documented_get_paths() -> None:
    RecordingSuccessConnection.requested_targets = []
    RecordingSuccessConnection.requested_methods = []
    transport = DhanHttpsTransport(
        connection_factory=cast(type[http.client.HTTPSConnection], RecordingSuccessConnection)
    )

    assert transport.get_order_book(access_token="private-jwt") == []
    assert transport.get_trade_book(access_token="private-jwt") == []
    assert transport.get_positions(access_token="private-jwt") == []

    assert RecordingSuccessConnection.requested_methods == ["GET", "GET", "GET"]
    assert RecordingSuccessConnection.requested_targets == [
        "/v2/orders",
        "/v2/trades",
        "/v2/positions",
    ]
    assert all("private-jwt" not in path for path in RecordingSuccessConnection.requested_targets)
