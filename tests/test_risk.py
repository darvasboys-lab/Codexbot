from decimal import Decimal

import pytest

from codexbot import (
    CapitalRiskFacts,
    EntryRiskFacts,
    RiskLimits,
    RiskReason,
    evaluate_capital_risk,
    evaluate_entry_risk,
)


def limits() -> RiskLimits:
    return RiskLimits(
        maximum_order_amount=Decimal("100000"),
        daily_loss_limit=Decimal("5000"),
        total_exposure_limit=Decimal("300000"),
        maximum_open_positions=5,
        maximum_daily_trades=10,
    )


def facts(**overrides: object) -> EntryRiskFacts:
    values: dict[str, object] = {
        "proposed_order_amount": Decimal("50000"),
        "accumulated_daily_loss": Decimal("1000"),
        "current_total_exposure": Decimal("100000"),
        "current_open_positions": 2,
        "current_daily_trades": 3,
        "adds_new_position": True,
    }
    values.update(overrides)
    return EntryRiskFacts(**values)  # type: ignore[arg-type]


def test_hard_caps_require_current_capital_facts_before_authorizing() -> None:
    result = evaluate_entry_risk(facts(), limits())

    assert result.cap_checks_passed is True
    assert result.fully_evaluated is False
    assert result.entry_allowed is False
    assert result.reasons == (RiskReason.CAPITAL_RISK_FACTS_REQUIRED,)


def test_each_breached_cap_is_reported_together() -> None:
    result = evaluate_entry_risk(
        facts(
            proposed_order_amount=Decimal("100001"),
            accumulated_daily_loss=Decimal("5000"),
            current_total_exposure=Decimal("299999"),
            current_open_positions=5,
            current_daily_trades=10,
        ),
        limits(),
    )

    assert result.cap_checks_passed is False
    assert set(result.reasons) == {
        RiskReason.MAX_ORDER_AMOUNT_EXCEEDED,
        RiskReason.DAILY_LOSS_LIMIT_REACHED,
        RiskReason.TOTAL_EXPOSURE_LIMIT_EXCEEDED,
        RiskReason.OPEN_POSITION_LIMIT_EXCEEDED,
        RiskReason.DAILY_TRADE_LIMIT_EXCEEDED,
        RiskReason.CAPITAL_RISK_FACTS_REQUIRED,
    }
    assert result.entry_allowed is False


def test_exact_non_loss_cap_boundaries_are_allowed() -> None:
    result = evaluate_entry_risk(
        facts(
            proposed_order_amount=Decimal("100000"),
            current_total_exposure=Decimal("200000"),
            current_open_positions=4,
            current_daily_trades=9,
        ),
        limits(),
    )

    assert result.cap_checks_passed is True


@pytest.mark.parametrize(
    "overrides",
    [
        {"maximum_order_amount": Decimal("0")},
        {"daily_loss_limit": Decimal("NaN")},
        {"maximum_open_positions": 0},
        {"maximum_daily_trades": -1},
    ],
)
def test_invalid_limits_fail_closed(overrides: dict[str, object]) -> None:
    values: dict[str, object] = {
        "maximum_order_amount": Decimal("100000"),
        "daily_loss_limit": Decimal("5000"),
        "total_exposure_limit": Decimal("300000"),
        "maximum_open_positions": 5,
        "maximum_daily_trades": 10,
    }
    values.update(overrides)

    with pytest.raises(ValueError):
        RiskLimits(**values)  # type: ignore[arg-type]


def test_capital_risk_applies_cash_floor_and_available_funds_buffer() -> None:
    result = evaluate_capital_risk(
        CapitalRiskFacts(
            starting_capital=Decimal("100000"),
            available_funds=Decimal("20000"),
            proposed_order_amount=Decimal("16000"),
            accumulated_daily_loss=Decimal("100"),
            position_drawdown=Decimal("100"),
            current_open_positions_in_sector=1,
            adds_new_sector_position=True,
        )
    )

    assert result.spendable_available_funds == Decimal("19000")
    assert result.required_cash_floor == Decimal("5000")
    assert RiskReason.TOTAL_CAPITAL_CASH_FLOOR_BREACHED in result.reasons
    assert result.entry_allowed is False


def test_capital_risk_emits_daily_halt_position_stop_and_sector_cap() -> None:
    result = evaluate_capital_risk(
        CapitalRiskFacts(
            starting_capital=Decimal("100000"),
            available_funds=Decimal("100000"),
            proposed_order_amount=Decimal("10000"),
            accumulated_daily_loss=Decimal("2000"),
            position_drawdown=Decimal("1000"),
            current_open_positions_in_sector=3,
            adds_new_sector_position=True,
        )
    )

    assert result.daily_loss_limit == Decimal("2000.0")
    assert result.position_loss_limit == Decimal("1000.0")
    assert result.system_halt_required is True
    assert result.position_hard_stop_required is True
    assert RiskReason.SECTOR_POSITION_LIMIT_REACHED in result.reasons
    assert result.entry_allowed is False


def test_entry_risk_can_authorize_when_all_caps_and_funds_evidence_pass() -> None:
    entry = facts(proposed_order_amount=Decimal("10000"))
    capital = CapitalRiskFacts(
        starting_capital=Decimal("100000"),
        available_funds=Decimal("50000"),
        proposed_order_amount=Decimal("10000"),
        accumulated_daily_loss=Decimal("100"),
        position_drawdown=Decimal("100"),
        current_open_positions_in_sector=1,
        adds_new_sector_position=True,
    )

    result = evaluate_entry_risk(entry, limits(), capital_facts=capital)

    assert result.fully_evaluated is True
    assert result.cap_checks_passed is True
    assert result.entry_allowed is True
    assert result.reasons == ()
