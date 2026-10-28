"""Pure delivery-stage product routing decisions with no broker operations."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum


class EquityProduct(StrEnum):
    DELIVERY_CNC = "CNC"


class RoutingReason(StrEnum):
    DELIVERY_CASH_AVAILABLE = "DELIVERY_CASH_AVAILABLE"
    DELIVERY_CASH_INSUFFICIENT = "DELIVERY_CASH_INSUFFICIENT"
    MTF_DEFERRED = "MTF_DEFERRED"


@dataclass(frozen=True, slots=True)
class DeliveryRoutingDecision:
    accepted: bool
    product: EquityProduct | None
    required_trade_value: Decimal
    spendable_cash: Decimal
    reasons: tuple[RoutingReason, ...]


def select_delivery_route(
    *, required_trade_value: Decimal, available_cash: Decimal
) -> DeliveryRoutingDecision:
    """Select CNC when it fits the approved 5% buffer; otherwise reject for now.

    MTF eligibility and margin evidence are deliberately absent in the delivery-only
    stage, so this function cannot silently fall back to another product.
    """

    for name, value in (
        ("required_trade_value", required_trade_value),
        ("available_cash", available_cash),
    ):
        if not value.is_finite() or value < 0:
            raise ValueError(f"{name} must be finite and non-negative")
    if required_trade_value == 0:
        raise ValueError("required_trade_value must be positive")
    spendable = available_cash * Decimal("0.95")
    if required_trade_value <= spendable:
        return DeliveryRoutingDecision(
            accepted=True,
            product=EquityProduct.DELIVERY_CNC,
            required_trade_value=required_trade_value,
            spendable_cash=spendable,
            reasons=(RoutingReason.DELIVERY_CASH_AVAILABLE,),
        )
    return DeliveryRoutingDecision(
        accepted=False,
        product=None,
        required_trade_value=required_trade_value,
        spendable_cash=spendable,
        reasons=(RoutingReason.DELIVERY_CASH_INSUFFICIENT, RoutingReason.MTF_DEFERRED),
    )
