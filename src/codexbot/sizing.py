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
