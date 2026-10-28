"""Side-effect-free entry risk caps with unresolved policies kept explicit."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum


class RiskReason(StrEnum):
    MAX_ORDER_AMOUNT_EXCEEDED = "MAX_ORDER_AMOUNT_EXCEEDED"
    DAILY_LOSS_LIMIT_REACHED = "DAILY_LOSS_LIMIT_REACHED"
    TOTAL_EXPOSURE_LIMIT_EXCEEDED = "TOTAL_EXPOSURE_LIMIT_EXCEEDED"
    OPEN_POSITION_LIMIT_EXCEEDED = "OPEN_POSITION_LIMIT_EXCEEDED"
    DAILY_TRADE_LIMIT_EXCEEDED = "DAILY_TRADE_LIMIT_EXCEEDED"
    MINIMUM_TRADE_FUNDS_POLICY_UNRESOLVED = "MINIMUM_TRADE_FUNDS_POLICY_UNRESOLVED"


@dataclass(frozen=True, slots=True)
class RiskLimits:
    maximum_order_amount: Decimal
    minimum_trade_funds: Decimal
    daily_loss_limit: Decimal
    total_exposure_limit: Decimal
    maximum_open_positions: int
    maximum_daily_trades: int

    def __post_init__(self) -> None:
        for name, value in (
            ("maximum_order_amount", self.maximum_order_amount),
            ("minimum_trade_funds", self.minimum_trade_funds),
            ("daily_loss_limit", self.daily_loss_limit),
            ("total_exposure_limit", self.total_exposure_limit),
        ):
            if not value.is_finite() or value <= 0:
                raise ValueError(f"{name} must be finite and positive")
        if self.maximum_open_positions <= 0:
            raise ValueError("maximum_open_positions must be positive")
        if self.maximum_daily_trades <= 0:
            raise ValueError("maximum_daily_trades must be positive")


@dataclass(frozen=True, slots=True)
class EntryRiskFacts:
    proposed_order_amount: Decimal
    accumulated_daily_loss: Decimal
    current_total_exposure: Decimal
    current_open_positions: int
    current_daily_trades: int
    adds_new_position: bool

    def __post_init__(self) -> None:
        for name, value in (
            ("proposed_order_amount", self.proposed_order_amount),
            ("accumulated_daily_loss", self.accumulated_daily_loss),
            ("current_total_exposure", self.current_total_exposure),
        ):
            if not value.is_finite() or value < 0:
                raise ValueError(f"{name} must be finite and non-negative")
        if self.proposed_order_amount == 0:
            raise ValueError("proposed_order_amount must be positive")
        if self.current_open_positions < 0 or self.current_daily_trades < 0:
            raise ValueError("position and trade counts cannot be negative")


@dataclass(frozen=True, slots=True)
class RiskEvaluation:
    cap_checks_passed: bool
    fully_evaluated: bool
    reasons: tuple[RiskReason, ...]

    @property
    def entry_allowed(self) -> bool:
        """Risk cannot authorize entry while the funds policy remains open."""

        return self.cap_checks_passed and self.fully_evaluated


def evaluate_entry_risk(facts: EntryRiskFacts, limits: RiskLimits) -> RiskEvaluation:
    """Apply agreed hard caps; retain minimum-funds semantics as a blocker."""

    reasons: list[RiskReason] = []
    if facts.proposed_order_amount > limits.maximum_order_amount:
        reasons.append(RiskReason.MAX_ORDER_AMOUNT_EXCEEDED)
    if facts.accumulated_daily_loss >= limits.daily_loss_limit:
        reasons.append(RiskReason.DAILY_LOSS_LIMIT_REACHED)
    if facts.current_total_exposure + facts.proposed_order_amount > limits.total_exposure_limit:
        reasons.append(RiskReason.TOTAL_EXPOSURE_LIMIT_EXCEEDED)
    projected_positions = facts.current_open_positions + int(facts.adds_new_position)
    if projected_positions > limits.maximum_open_positions:
        reasons.append(RiskReason.OPEN_POSITION_LIMIT_EXCEEDED)
    if facts.current_daily_trades + 1 > limits.maximum_daily_trades:
        reasons.append(RiskReason.DAILY_TRADE_LIMIT_EXCEEDED)

    caps_passed = not reasons
    reasons.append(RiskReason.MINIMUM_TRADE_FUNDS_POLICY_UNRESOLVED)
    return RiskEvaluation(
        cap_checks_passed=caps_passed,
        fully_evaluated=False,
        reasons=tuple(reasons),
    )
