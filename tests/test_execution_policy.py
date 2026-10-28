from datetime import timedelta

import pytest

from codexbot import (
    LimitOrderLifecyclePolicy,
    NetworkTimeoutPolicy,
    TimeoutAction,
    timeout_action,
)


def test_approved_timeout_defaults_are_explicit_and_limit_only() -> None:
    network = NetworkTimeoutPolicy()
    order = LimitOrderLifecyclePolicy()

    assert network.connect_timeout == timedelta(seconds=3)
    assert network.read_timeout == timedelta(seconds=5)
    assert order.fill_timeout == timedelta(seconds=45)
    assert order.maximum_retries == 1
    assert order.allow_market_conversion is False


def test_timeout_requires_cancel_reconciliation_before_one_retry() -> None:
    assert (
        timeout_action(
            ordered_quantity=10,
            filled_quantity=4,
            remainder_cancel_confirmed=False,
            retry_count=0,
            signal_still_valid=True,
            retry_price_approved=True,
        )
        is TimeoutAction.CANCEL_REMAINDER_AND_RECONCILE
    )
    assert (
        timeout_action(
            ordered_quantity=10,
            filled_quantity=4,
            remainder_cancel_confirmed=True,
            retry_count=0,
            signal_still_valid=True,
            retry_price_approved=True,
        )
        is TimeoutAction.RETRY_REMAINDER
    )
    assert (
        timeout_action(
            ordered_quantity=10,
            filled_quantity=4,
            remainder_cancel_confirmed=True,
            retry_count=1,
            signal_still_valid=True,
            retry_price_approved=True,
        )
        is TimeoutAction.STOP_WITHOUT_RETRY
    )


def test_market_conversion_cannot_be_enabled() -> None:
    with pytest.raises(ValueError, match="LIMIT-only"):
        LimitOrderLifecyclePolicy(allow_market_conversion=True)
