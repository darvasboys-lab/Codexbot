from decimal import Decimal

import pytest

from codexbot import EntryRiskFacts, RiskLimits, RiskReason, evaluate_entry_risk


def limits() -> RiskLimits:
    return RiskLimits(
        maximum_order_amount=Decimal("100000"),
        minimum_trade_funds=Decimal("10000"),
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


def test_hard_caps_can_pass_but_unresolved_funds_policy_still_blocks() -> None:
    result = evaluate_entry_risk(facts(), limits())

    assert result.cap_checks_passed is True
    assert result.fully_evaluated is False
    assert result.entry_allowed is False
    assert result.reasons == (RiskReason.MINIMUM_TRADE_FUNDS_POLICY_UNRESOLVED,)


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
    assert set(result.reasons) == set(RiskReason)
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
        {"minimum_trade_funds": Decimal("NaN")},
        {"maximum_open_positions": 0},
        {"maximum_daily_trades": -1},
    ],
)
def test_invalid_limits_fail_closed(overrides: dict[str, object]) -> None:
    values: dict[str, object] = {
        "maximum_order_amount": Decimal("100000"),
        "minimum_trade_funds": Decimal("10000"),
        "daily_loss_limit": Decimal("5000"),
        "total_exposure_limit": Decimal("300000"),
        "maximum_open_positions": 5,
        "maximum_daily_trades": 10,
    }
    values.update(overrides)

    with pytest.raises(ValueError):
        RiskLimits(**values)  # type: ignore[arg-type]
