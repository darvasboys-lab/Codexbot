"""Pure share/lot sizing calculations; no broker funds or order side effects."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_FLOOR, Decimal
from enum import StrEnum


class SizingError(ValueError):
    """Raised when configured sizing cannot produce a valid quantity."""


class SizingMode(StrEnum):
    FIXED = "FIXED"
    BUDGET = "BUDGET"


@dataclass(frozen=True, slots=True)
class SizingSelection:
    """One explicit setup selection; interpretation is segment-specific."""

    mode: SizingMode
    configured_value: Decimal

    def __post_init__(self) -> None:
        if not self.configured_value.is_finite() or self.configured_value <= 0:
            raise ValueError("configured sizing value must be finite and positive")
        if (
            self.mode is SizingMode.FIXED
            and self.configured_value != self.configured_value.to_integral_value()
        ):
            raise ValueError("fixed sizing value must be a whole number")


@dataclass(frozen=True, slots=True)
class SizeResult:
    mode: SizingMode
    quantity: int
    lots: int | None
    unit_price: Decimal
    notional: Decimal


@dataclass(frozen=True, slots=True)
class FixedFractionalPolicy:
    """Explicit capital-risk inputs; the approved 10-15% range has no default."""

    risk_percent_per_trade: Decimal
    maximum_capital_allocation_percent: Decimal

    def __post_init__(self) -> None:
        if (
            not self.risk_percent_per_trade.is_finite()
            or self.risk_percent_per_trade <= 0
            or self.risk_percent_per_trade > Decimal("1.0")
        ):
            raise ValueError("risk percent per trade must be greater than 0 and at most 1")
        if not self.maximum_capital_allocation_percent.is_finite() or not Decimal(
            "10"
        ) <= self.maximum_capital_allocation_percent <= Decimal("15"):
            raise ValueError("maximum capital allocation percent must be between 10 and 15")


@dataclass(frozen=True, slots=True)
class FixedFractionalSizeResult:
    quantity: int
    lots: int | None
    risk_budget: Decimal
    capital_allocation_ceiling: Decimal
    risk_based_quantity: int
    allocation_based_quantity: int
    entry_price: Decimal
    stop_loss_price: Decimal
    notional: Decimal


def size_equity_fixed_shares(*, shares: int, limit_price: Decimal) -> SizeResult:
    """Return an explicit positive share count."""

    _positive_price(limit_price)
    if isinstance(shares, bool) or shares <= 0:
        raise SizingError("EQUITY_FIXED_SHARES_INVALID")
    return SizeResult(
        mode=SizingMode.FIXED,
        quantity=shares,
        lots=None,
        unit_price=limit_price,
        notional=limit_price * shares,
    )


def size_equity_budget(*, budget: Decimal, limit_price: Decimal) -> SizeResult:
    """Floor shares to budget and reject a budget below one share."""

    _positive_budget(budget)
    _positive_price(limit_price)
    shares = int((budget / limit_price).to_integral_value(rounding=ROUND_FLOOR))
    if shares < 1:
        raise SizingError("EQUITY_BUDGET_CANNOT_BUY_ONE_SHARE")
    return SizeResult(
        mode=SizingMode.BUDGET,
        quantity=shares,
        lots=None,
        unit_price=limit_price,
        notional=limit_price * shares,
    )


def size_option_fixed_lots(*, lots: int, lot_size: Decimal, limit_price: Decimal) -> SizeResult:
    """Convert an explicit positive lot count to broker quantity."""

    lot_units = _lot_units(lot_size)
    _positive_price(limit_price)
    if isinstance(lots, bool) or lots <= 0:
        raise SizingError("OPTION_FIXED_LOTS_INVALID")
    quantity = lots * lot_units
    return SizeResult(
        mode=SizingMode.FIXED,
        quantity=quantity,
        lots=lots,
        unit_price=limit_price,
        notional=limit_price * quantity,
    )


def size_option_budget(*, budget: Decimal, lot_size: Decimal, limit_price: Decimal) -> SizeResult:
    """Floor to complete lots and reject a budget below one lot."""

    _positive_budget(budget)
    lot_units = _lot_units(lot_size)
    _positive_price(limit_price)
    one_lot_notional = limit_price * lot_units
    lots = int((budget / one_lot_notional).to_integral_value(rounding=ROUND_FLOOR))
    if lots < 1:
        raise SizingError("OPTION_BUDGET_CANNOT_BUY_ONE_LOT")
    quantity = lots * lot_units
    return SizeResult(
        mode=SizingMode.BUDGET,
        quantity=quantity,
        lots=lots,
        unit_price=limit_price,
        notional=limit_price * quantity,
    )


def size_equity_fixed_fractional(
    *,
    total_capital: Decimal,
    entry_price: Decimal,
    stop_loss_price: Decimal,
    policy: FixedFractionalPolicy,
) -> FixedFractionalSizeResult:
    """Floor shares by both loss-at-stop risk and the configured allocation cap."""

    risk_budget, allocation_ceiling, risk_units, allocation_units = _fractional_limits(
        total_capital=total_capital,
        entry_price=entry_price,
        stop_loss_price=stop_loss_price,
        policy=policy,
    )
    quantity = min(risk_units, allocation_units)
    if quantity < 1:
        raise SizingError("FIXED_FRACTIONAL_CANNOT_BUY_ONE_SHARE")
    return FixedFractionalSizeResult(
        quantity=quantity,
        lots=None,
        risk_budget=risk_budget,
        capital_allocation_ceiling=allocation_ceiling,
        risk_based_quantity=risk_units,
        allocation_based_quantity=allocation_units,
        entry_price=entry_price,
        stop_loss_price=stop_loss_price,
        notional=entry_price * quantity,
    )


def size_option_fixed_fractional(
    *,
    total_capital: Decimal,
    entry_price: Decimal,
    stop_loss_price: Decimal,
    lot_size: Decimal,
    policy: FixedFractionalPolicy,
) -> FixedFractionalSizeResult:
    """Floor the risk-limited quantity again to complete listed option lots."""

    lot_units = _lot_units(lot_size)
    risk_budget, allocation_ceiling, risk_units, allocation_units = _fractional_limits(
        total_capital=total_capital,
        entry_price=entry_price,
        stop_loss_price=stop_loss_price,
        policy=policy,
    )
    raw_quantity = min(risk_units, allocation_units)
    lots = raw_quantity // lot_units
    if lots < 1:
        raise SizingError("FIXED_FRACTIONAL_CANNOT_BUY_ONE_LOT")
    quantity = lots * lot_units
    return FixedFractionalSizeResult(
        quantity=quantity,
        lots=lots,
        risk_budget=risk_budget,
        capital_allocation_ceiling=allocation_ceiling,
        risk_based_quantity=risk_units,
        allocation_based_quantity=allocation_units,
        entry_price=entry_price,
        stop_loss_price=stop_loss_price,
        notional=entry_price * quantity,
    )


def _fractional_limits(
    *,
    total_capital: Decimal,
    entry_price: Decimal,
    stop_loss_price: Decimal,
    policy: FixedFractionalPolicy,
) -> tuple[Decimal, Decimal, int, int]:
    _positive_budget(total_capital)
    _positive_price(entry_price)
    _positive_price(stop_loss_price)
    if stop_loss_price >= entry_price:
        raise SizingError("STOP_LOSS_MUST_BE_BELOW_ENTRY")
    loss_per_unit = entry_price - stop_loss_price
    risk_budget = total_capital * policy.risk_percent_per_trade / Decimal(100)
    allocation_ceiling = total_capital * policy.maximum_capital_allocation_percent / Decimal(100)
    risk_units = int((risk_budget / loss_per_unit).to_integral_value(rounding=ROUND_FLOOR))
    allocation_units = int(
        (allocation_ceiling / entry_price).to_integral_value(rounding=ROUND_FLOOR)
    )
    return risk_budget, allocation_ceiling, risk_units, allocation_units


def _positive_price(value: Decimal) -> None:
    if not value.is_finite() or value <= 0:
        raise SizingError("LIMIT_PRICE_INVALID")


def _positive_budget(value: Decimal) -> None:
    if not value.is_finite() or value <= 0:
        raise SizingError("BUDGET_INVALID")


def _lot_units(value: Decimal) -> int:
    if not value.is_finite() or value <= 0 or value != value.to_integral_value():
        raise SizingError("OPTION_LOT_SIZE_INVALID")
    return int(value)
