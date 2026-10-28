"""Order-lifecycle policy facts only; this module has no broker-write capability."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum


@dataclass(frozen=True, slots=True)
class NetworkTimeoutPolicy:
    connect_timeout: timedelta = timedelta(seconds=3)
    read_timeout: timedelta = timedelta(seconds=5)

    def __post_init__(self) -> None:
        if self.connect_timeout <= timedelta(0) or self.read_timeout <= timedelta(0):
            raise ValueError("network timeouts must be positive")


@dataclass(frozen=True, slots=True)
class LimitOrderLifecyclePolicy:
    fill_timeout: timedelta = timedelta(seconds=45)
    maximum_retries: int = 1
    require_status_reconciliation_after_ambiguous_submit: bool = True
    require_remainder_cancel_confirmation_before_retry: bool = True
    allow_market_conversion: bool = False

    def __post_init__(self) -> None:
        if self.fill_timeout <= timedelta(0):
            raise ValueError("fill timeout must be positive")
        if self.maximum_retries != 1:
            raise ValueError("exactly one retry is approved")
        if self.allow_market_conversion:
            raise ValueError("market conversion is outside the approved LIMIT-only scope")


class TimeoutAction(StrEnum):
    CONTINUE_MANAGING_FILL = "CONTINUE_MANAGING_FILL"
    CANCEL_REMAINDER_AND_RECONCILE = "CANCEL_REMAINDER_AND_RECONCILE"
    RETRY_REMAINDER = "RETRY_REMAINDER"
    STOP_WITHOUT_RETRY = "STOP_WITHOUT_RETRY"


def timeout_action(
    *,
    ordered_quantity: int,
    filled_quantity: int,
    remainder_cancel_confirmed: bool,
    retry_count: int,
    signal_still_valid: bool,
    retry_price_approved: bool,
) -> TimeoutAction:
    """Describe the next safe lifecycle step without cancelling or submitting."""

    if ordered_quantity <= 0 or not 0 <= filled_quantity <= ordered_quantity:
        raise ValueError("order quantities are invalid")
    if retry_count < 0 or retry_count > 1:
        raise ValueError("retry count is invalid")
    if filled_quantity == ordered_quantity:
        return TimeoutAction.CONTINUE_MANAGING_FILL
    if not remainder_cancel_confirmed:
        return TimeoutAction.CANCEL_REMAINDER_AND_RECONCILE
    if retry_count == 0 and signal_still_valid and retry_price_approved:
        return TimeoutAction.RETRY_REMAINDER
    return TimeoutAction.STOP_WITHOUT_RETRY
