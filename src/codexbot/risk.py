"""Side-effect-free entry, capital, drawdown, cash-buffer, and sector risk gates."""

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
    CAPITAL_RISK_FACTS_REQUIRED = "CAPITAL_RISK_FACTS_REQUIRED"
    AVAILABLE_FUNDS_BUFFER_BREACHED = "AVAILABLE_FUNDS_BUFFER_BREACHED"
    TOTAL_CAPITAL_CASH_FLOOR_BREACHED = "TOTAL_CAPITAL_CASH_FLOOR_BREACHED"
    DAILY_DRAWDOWN_HALT = "DAILY_DRAWDOWN_HALT"
    POSITION_DRAWDOWN_HARD_STOP = "POSITION_DRAWDOWN_HARD_STOP"
    SECTOR_POSITION_LIMIT_REACHED = "SECTOR_POSITION_LIMIT_REACHED"


@dataclass(frozen=True, slots=True)
class RiskLimits:
    maximum_order_amount: Decimal
    daily_loss_limit: Decimal
    total_exposure_limit: Decimal
    maximum_open_positions: int
    maximum_daily_trades: int

    def __post_init__(self) -> None:
        for name, value in (
            ("maximum_order_amount", self.maximum_order_amount),
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
        """Authorize only after every required fact and cap has been evaluated."""

        return self.cap_checks_passed and self.fully_evaluated


@dataclass(frozen=True, slots=True)
class CapitalRiskPolicy:
    """Approved portfolio protections expressed as percentages and a sector cap."""

    daily_drawdown_percent: Decimal = Decimal("2.0")
    position_drawdown_percent: Decimal = Decimal("1.0")
    cash_buffer_percent: Decimal = Decimal("5.0")
    maximum_open_positions_per_sector: int = 3

    def __post_init__(self) -> None:
        for name, value in (
            ("daily_drawdown_percent", self.daily_drawdown_percent),
            ("position_drawdown_percent", self.position_drawdown_percent),
            ("cash_buffer_percent", self.cash_buffer_percent),
        ):
            if not value.is_finite() or value <= 0 or value >= 100:
                raise ValueError(f"{name} must be between 0 and 100")
        if self.maximum_open_positions_per_sector <= 0:
            raise ValueError("maximum_open_positions_per_sector must be positive")


@dataclass(frozen=True, slots=True)
class CapitalRiskFacts:
    """Actual account/portfolio observations required by the capital checks."""

    starting_capital: Decimal
    available_funds: Decimal
    proposed_order_amount: Decimal
    accumulated_daily_loss: Decimal
    position_drawdown: Decimal
    current_open_positions_in_sector: int
    adds_new_sector_position: bool

    def __post_init__(self) -> None:
        for name, value in (
            ("starting_capital", self.starting_capital),
            ("available_funds", self.available_funds),
            ("proposed_order_amount", self.proposed_order_amount),
            ("accumulated_daily_loss", self.accumulated_daily_loss),
            ("position_drawdown", self.position_drawdown),
        ):
            if not value.is_finite() or value < 0:
                raise ValueError(f"{name} must be finite and non-negative")
        if self.starting_capital == 0 or self.proposed_order_amount == 0:
            raise ValueError("starting capital and proposed order amount must be positive")
        if self.current_open_positions_in_sector < 0:
            raise ValueError("sector position count cannot be negative")


@dataclass(frozen=True, slots=True)
class CapitalRiskEvaluation:
    """A decision plus explicit management signals; it performs no account mutation."""

    entry_allowed: bool
    system_halt_required: bool
    position_hard_stop_required: bool
    spendable_available_funds: Decimal
    required_cash_floor: Decimal
    daily_loss_limit: Decimal
    position_loss_limit: Decimal
    reasons: tuple[RiskReason, ...]


def evaluate_capital_risk(
    facts: CapitalRiskFacts, policy: CapitalRiskPolicy | None = None
) -> CapitalRiskEvaluation:
    """Apply the approved 5% buffer, 2% halt, 1% stop, and sector cap."""

    if policy is None:
        policy = CapitalRiskPolicy()
    hundred = Decimal(100)
    spendable = facts.available_funds * (hundred - policy.cash_buffer_percent) / hundred
    required_cash_floor = facts.starting_capital * policy.cash_buffer_percent / hundred
    daily_limit = facts.starting_capital * policy.daily_drawdown_percent / hundred
    position_limit = facts.starting_capital * policy.position_drawdown_percent / hundred
    reasons: list[RiskReason] = []
    if facts.proposed_order_amount > spendable:
        reasons.append(RiskReason.AVAILABLE_FUNDS_BUFFER_BREACHED)
    if facts.available_funds - facts.proposed_order_amount < required_cash_floor:
        reasons.append(RiskReason.TOTAL_CAPITAL_CASH_FLOOR_BREACHED)
    daily_halt = facts.accumulated_daily_loss >= daily_limit
    if daily_halt:
        reasons.append(RiskReason.DAILY_DRAWDOWN_HALT)
    position_stop = facts.position_drawdown >= position_limit
    if position_stop:
        reasons.append(RiskReason.POSITION_DRAWDOWN_HARD_STOP)
    projected_sector_count = facts.current_open_positions_in_sector + int(
        facts.adds_new_sector_position
    )
    if projected_sector_count > policy.maximum_open_positions_per_sector:
        reasons.append(RiskReason.SECTOR_POSITION_LIMIT_REACHED)
    entry_blockers = {
        RiskReason.AVAILABLE_FUNDS_BUFFER_BREACHED,
        RiskReason.TOTAL_CAPITAL_CASH_FLOOR_BREACHED,
        RiskReason.DAILY_DRAWDOWN_HALT,
        RiskReason.POSITION_DRAWDOWN_HARD_STOP,
        RiskReason.SECTOR_POSITION_LIMIT_REACHED,
    }
    return CapitalRiskEvaluation(
        entry_allowed=not any(reason in entry_blockers for reason in reasons),
        system_halt_required=daily_halt,
        position_hard_stop_required=position_stop,
        spendable_available_funds=spendable,
        required_cash_floor=required_cash_floor,
        daily_loss_limit=daily_limit,
        position_loss_limit=position_limit,
        reasons=tuple(reasons),
    )


def evaluate_entry_risk(
    facts: EntryRiskFacts,
    limits: RiskLimits,
    *,
    capital_facts: CapitalRiskFacts | None = None,
    capital_policy: CapitalRiskPolicy | None = None,
) -> RiskEvaluation:
    """Apply all caps, requiring current account facts for the approved cash policy."""

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

    if capital_facts is None:
        reasons.append(RiskReason.CAPITAL_RISK_FACTS_REQUIRED)
        return RiskEvaluation(
            cap_checks_passed=not reasons[:-1],
            fully_evaluated=False,
            reasons=tuple(reasons),
        )
    if capital_facts.proposed_order_amount != facts.proposed_order_amount:
        raise ValueError("entry and capital risk order amounts must match")
    capital = evaluate_capital_risk(capital_facts, capital_policy)
    reasons.extend(capital.reasons)
    return RiskEvaluation(
        cap_checks_passed=not reasons,
        fully_evaluated=True,
        reasons=tuple(reasons),
    )
