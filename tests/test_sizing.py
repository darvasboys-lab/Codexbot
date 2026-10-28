from decimal import Decimal

import pytest

from codexbot import (
    SizingError,
    SizingMode,
    size_equity_budget,
    size_equity_fixed_shares,
    size_option_budget,
    size_option_fixed_lots,
)


def test_fixed_equity_shares_preserve_configured_quantity() -> None:
    result = size_equity_fixed_shares(shares=7, limit_price=Decimal("123.45"))

    assert result.mode is SizingMode.FIXED
    assert result.quantity == 7
    assert result.lots is None
    assert result.notional == Decimal("864.15")


def test_equity_budget_floors_without_exceeding_budget() -> None:
    result = size_equity_budget(budget=Decimal("1000"), limit_price=Decimal("333"))

    assert result.mode is SizingMode.BUDGET
    assert result.quantity == 3
    assert result.notional == Decimal("999")


def test_equity_budget_rejects_when_one_share_does_not_fit() -> None:
    with pytest.raises(SizingError, match="EQUITY_BUDGET_CANNOT_BUY_ONE_SHARE"):
        size_equity_budget(budget=Decimal("332.99"), limit_price=Decimal("333"))


def test_fixed_option_lots_use_integral_instrument_lot_size() -> None:
    result = size_option_fixed_lots(lots=2, lot_size=Decimal("475"), limit_price=Decimal("36.40"))

    assert result.mode is SizingMode.FIXED
    assert result.lots == 2
    assert result.quantity == 950
    assert result.notional == Decimal("34580.00")


def test_option_budget_floors_to_whole_lots() -> None:
    result = size_option_budget(
        budget=Decimal("40000"), lot_size=Decimal("475"), limit_price=Decimal("36.40")
    )

    assert result.mode is SizingMode.BUDGET
    assert result.lots == 2
    assert result.quantity == 950
    assert result.notional == Decimal("34580.00")


def test_option_budget_rejects_when_one_lot_does_not_fit() -> None:
    with pytest.raises(SizingError, match="OPTION_BUDGET_CANNOT_BUY_ONE_LOT"):
        size_option_budget(
            budget=Decimal("17289.99"),
            lot_size=Decimal("475"),
            limit_price=Decimal("36.40"),
        )


@pytest.mark.parametrize("lot_size", ["0", "1.5", "NaN"])
def test_option_lot_size_must_be_positive_integral_units(lot_size: str) -> None:
    with pytest.raises(SizingError, match="OPTION_LOT_SIZE_INVALID"):
        size_option_fixed_lots(
            lots=1,
            lot_size=Decimal(lot_size),
            limit_price=Decimal("36.40"),
        )
