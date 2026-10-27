"""Domain types for deterministic signal checking.

These types intentionally describe no broker orders, fills, holdings, or simulated
trades. A report that passes this early core is not trade-ready.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from enum import StrEnum


class ExecutionMode(StrEnum):
    """The single mode shared by equity and F&O."""

    TEST = "TEST"
    LIVE = "LIVE"


class Action(StrEnum):
    BUY = "BUY"
    SELL = "SELL"
    EXIT = "EXIT"
    UNKNOWN = "UNKNOWN"


class Segment(StrEnum):
    EQUITY = "EQUITY"
    FNO = "FNO"


class InstrumentKind(StrEnum):
    EQUITY = "EQUITY"
    STOCK_OPTION = "STOCK_OPTION"
    STOCK_FUTURE = "STOCK_FUTURE"
    INDEX = "INDEX"
    UNKNOWN = "UNKNOWN"


class CheckDisposition(StrEnum):
    """Outcome of the implemented core gates.

    PASSED_CORE never means that a signal is ready for order submission. Later
    quote, duplicate, sizing, funds, risk, and reconciliation gates are mandatory.
    """

    PASSED_CORE = "PASSED_CORE"
    FILTERED = "FILTERED"
    REJECTED = "REJECTED"


class ReasonCode(StrEnum):
    SOURCE_NOT_CONFIGURED = "SOURCE_NOT_CONFIGURED"
    SOURCE_IDENTITY_UNVERIFIED = "SOURCE_IDENTITY_UNVERIFIED"
    INVALID_TIMESTAMP = "INVALID_TIMESTAMP"
    MESSAGE_TOO_OLD = "MESSAGE_TOO_OLD"
    NON_BUY_ACTION = "NON_BUY_ACTION"
    UNRECOGNIZED_MESSAGE = "UNRECOGNIZED_MESSAGE"
    SEGMENT_INACTIVE = "SEGMENT_INACTIVE"
    INDEX_NOT_ALLOWED = "INDEX_NOT_ALLOWED"
    FUTURES_NOT_APPROVED = "FUTURES_NOT_APPROVED"
    INSTRUMENT_REFERENCE_MISSING = "INSTRUMENT_REFERENCE_MISSING"
    INSTRUMENT_UNRESOLVED = "INSTRUMENT_UNRESOLVED"
    INSTRUMENT_IDENTITY_INCOMPLETE = "INSTRUMENT_IDENTITY_INCOMPLETE"
    INSTRUMENT_NOT_LISTED = "INSTRUMENT_NOT_LISTED"
    INSTRUMENT_KIND_UNSUPPORTED = "INSTRUMENT_KIND_UNSUPPORTED"
    SEGMENT_INSTRUMENT_MISMATCH = "SEGMENT_INSTRUMENT_MISMATCH"
    OPTION_PRICE_REQUIRED = "OPTION_PRICE_REQUIRED"
    OPTION_PRICE_INVALID = "OPTION_PRICE_INVALID"
    OPTION_CONTRACT_NOT_UNIQUE = "OPTION_CONTRACT_NOT_UNIQUE"


class PendingGate(StrEnum):
    AUDIT_DURABILITY = "AUDIT_DURABILITY"
    DUPLICATE = "DUPLICATE"
    MARKET_SESSION_AND_CALENDAR = "MARKET_SESSION_AND_CALENDAR"
    REGULATORY_AND_BROKER_ENABLEMENT = "REGULATORY_AND_BROKER_ENABLEMENT"
    BROKER_AUTH_AND_HEALTH = "BROKER_AUTH_AND_HEALTH"
    CURRENT_QUOTE = "CURRENT_QUOTE"
    ENTRY_PRICE = "ENTRY_PRICE"
    TICK_SIZE = "TICK_SIZE"
    SIZING = "SIZING"
    FUNDS_AND_MARGIN = "FUNDS_AND_MARGIN"
    RISK_LIMITS = "RISK_LIMITS"
    MODE_AND_EMERGENCY_STOP = "MODE_AND_EMERGENCY_STOP"
    EXECUTION_POLICY = "EXECUTION_POLICY"
    BROKER_RECONCILIATION = "BROKER_RECONCILIATION"
    PROTECTION_PLAN = "PROTECTION_PLAN"


@dataclass(frozen=True, slots=True)
class CheckerPolicy:
    """Only policy values already fixed by the requirements.

    Segment activation is required explicitly because Udit has not chosen setup
    values. Execution mode safely defaults to TEST.
    """

    allowed_group_ids: frozenset[int]
    equity_active: bool
    fno_active: bool
    future_clock_tolerance: timedelta
    execution_mode: ExecutionMode = ExecutionMode.TEST

    def __post_init__(self) -> None:
        if self.future_clock_tolerance < timedelta(0):
            raise ValueError("future_clock_tolerance cannot be negative")


@dataclass(frozen=True, slots=True)
class NormalizedSignal:
    """A parsed Telegram message supplied to the checking core.

    Parsing is intentionally outside the first slice because real examples and the
    reference archive have not yet been reviewed.
    """

    source_group_id: int
    telegram_message_id: int
    sent_at: datetime
    source_identity_verified: bool
    action: Action
    segment: Segment
    symbol: str | None = None
    stated_price: Decimal | None = None


@dataclass(frozen=True, slots=True)
class InstrumentFacts:
    """Read-only facts that a later instrument resolver must provide."""

    resolved: bool
    listed: bool
    kind: InstrumentKind
    security_id: str | None
    unique_contract: bool


@dataclass(frozen=True, slots=True)
class CheckReport:
    disposition: CheckDisposition
    reasons: tuple[ReasonCode, ...]
    pending_gates: tuple[PendingGate, ...]
    execution_mode: ExecutionMode

    @property
    def trade_ready(self) -> bool:
        """The early core can never authorize an order."""

        return False
