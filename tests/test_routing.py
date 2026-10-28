from decimal import Decimal

from codexbot import EquityProduct, RoutingReason, select_delivery_route


def test_delivery_route_uses_only_95_percent_of_available_cash() -> None:
    accepted = select_delivery_route(
        required_trade_value=Decimal("95000"), available_cash=Decimal("100000")
    )
    rejected = select_delivery_route(
        required_trade_value=Decimal("95000.01"), available_cash=Decimal("100000")
    )

    assert accepted.accepted is True
    assert accepted.product is EquityProduct.DELIVERY_CNC
    assert rejected.accepted is False
    assert rejected.product is None
    assert rejected.reasons == (
        RoutingReason.DELIVERY_CASH_INSUFFICIENT,
        RoutingReason.MTF_DEFERRED,
    )
