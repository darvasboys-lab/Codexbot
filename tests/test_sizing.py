from decimal import Decimal

import pytest

from codexbot import (
    FixedFractionalPolicy,
    SizingError,
    SizingMode,
    SizingSelection,
    size_equity_budget,
    size_equity_fixed_fractional,
    size_equity_fixed_shares,
    size_option_budget,
    size_option_fixed_fractional,
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


def test_setup_selection_requires_whole_fixed_units_but_allows_decimal_budget() -> None:
    assert SizingSelection(
        mode=SizingMode.BUDGET, configured_value=Decimal("50000.50")
    ).configured_value == Decimal("50000.50")
    with pytest.raises(ValueError, match="whole number"):
        SizingSelection(mode=SizingMode.FIXED, configured_value=Decimal("1.5"))


def test_fixed_fractional_equity_uses_tighter_risk_or_allocation_limit() -> None:
    result = size_equity_fixed_fractional(
        total_capital=Decimal("100000"),
        entry_price=Decimal("100"),
        stop_loss_price=Decimal("97"),
        policy=FixedFractionalPolicy(
            risk_percent_per_trade=Decimal("1"),
            maximum_capital_allocation_percent=Decimal("10"),
        ),
    )

    assert result.risk_based_quantity == 333
    assert result.allocation_based_quantity == 100
    assert result.quantity == 100
    assert result.notional == Decimal("10000")


def test_fixed_fractional_option_floors_to_whole_lots() -> None:
    result = size_option_fixed_fractional(
        total_capital=Decimal("100000"),
        entry_price=Decimal("20"),
        stop_loss_price=Decimal("18"),
        lot_size=Decimal("75"),
        policy=FixedFractionalPolicy(
            risk_percent_per_trade=Decimal("1"),
            maximum_capital_allocation_percent=Decimal("15"),
        ),
    )

    assert result.quantity == 450
    assert result.lots == 6
    assert result.notional == Decimal("9000")


@pytest.mark.parametrize("allocation", ["9.99", "15.01"])
def test_fractional_allocation_must_be_selected_within_approved_range(
    allocation: str,
) -> None:
    with pytest.raises(ValueError, match="between 10 and 15"):
        FixedFractionalPolicy(
            risk_percent_per_trade=Decimal("1"),
            maximum_capital_allocation_percent=Decimal(allocation),
        )


def test_fractional_risk_cannot_exceed_position_drawdown_cap() -> None:
    with pytest.raises(ValueError, match="at most 1"):
        FixedFractionalPolicy(
            risk_percent_per_trade=Decimal("1.01"),
            maximum_capital_allocation_percent=Decimal("10"),
        )
