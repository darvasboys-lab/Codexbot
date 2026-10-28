"""Fail-closed exchange-day and Asia/Kolkata session policy primitives."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, time
from enum import StrEnum
from pathlib import Path
from typing import cast
from zoneinfo import ZoneInfo

INDIA = ZoneInfo("Asia/Kolkata")


class SessionPhase(StrEnum):
    CLOSED = "CLOSED"
    INITIALIZATION = "INITIALIZATION"
    OPENING_GUARD = "OPENING_GUARD"
    NORMAL_EXECUTION = "NORMAL_EXECUTION"
    SQUARE_OFF = "SQUARE_OFF"
    POST_MARKET = "POST_MARKET"
    EOD_RECONCILIATION = "EOD_RECONCILIATION"


@dataclass(frozen=True, slots=True)
class SessionDecision:
    phase: SessionPhase
    new_entries_allowed: bool
    exits_only: bool
    cancel_pending_entries_due: bool
    reconciliation_due: bool
    rotate_logs_due: bool


def session_decision(at: datetime, *, trading_day_open: bool) -> SessionDecision:
    """Classify the approved delivery-stage session without performing an action."""

    if at.tzinfo is None or at.utcoffset() is None:
        raise ValueError("session time must be timezone-aware")
    local_time = at.astimezone(INDIA).time().replace(tzinfo=None)
    if not trading_day_open:
        return _session(SessionPhase.CLOSED)
    if time(8, 45) <= local_time < time(9, 15):
        return _session(SessionPhase.INITIALIZATION)
    if time(9, 15) <= local_time < time(9, 16):
        return _session(SessionPhase.OPENING_GUARD)
    if time(9, 16) <= local_time < time(15, 10):
        return _session(SessionPhase.NORMAL_EXECUTION, new_entries_allowed=True)
    if time(15, 10) <= local_time < time(15, 15):
        return _session(
            SessionPhase.SQUARE_OFF,
            exits_only=True,
            cancel_pending_entries_due=True,
        )
    if time(15, 15) <= local_time < time(15, 35):
        return _session(
            SessionPhase.POST_MARKET,
            exits_only=True,
            cancel_pending_entries_due=True,
        )
    if local_time >= time(15, 35):
        return _session(
            SessionPhase.EOD_RECONCILIATION,
            cancel_pending_entries_due=True,
            reconciliation_due=True,
            rotate_logs_due=True,
        )
    return _session(SessionPhase.CLOSED)


def _session(
    phase: SessionPhase,
    *,
    new_entries_allowed: bool = False,
    exits_only: bool = False,
    cancel_pending_entries_due: bool = False,
    reconciliation_due: bool = False,
    rotate_logs_due: bool = False,
) -> SessionDecision:
    return SessionDecision(
        phase=phase,
        new_entries_allowed=new_entries_allowed,
        exits_only=exits_only,
        cancel_pending_entries_due=cancel_pending_entries_due,
        reconciliation_due=reconciliation_due,
        rotate_logs_due=rotate_logs_due,
    )


class CalendarSource(StrEnum):
    DYNAMIC = "DYNAMIC"
    LOCAL_FALLBACK = "LOCAL_FALLBACK"
    MANUAL_OVERRIDE = "MANUAL_OVERRIDE"


@dataclass(frozen=True, slots=True)
class TradingDayDecision:
    market_open: bool
    source: CalendarSource
    caution: bool
    manual_override_required: bool
    reason: str


@dataclass(frozen=True, slots=True)
class LocalHolidayCalendar:
    year: int
    source_url: str
    fetched_at: datetime
    holidays: frozenset[date]

    @classmethod
    def load(cls, path: str | Path, *, segment: str) -> LocalHolidayCalendar:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("calendar root must be an object")
        year = _calendar_int(raw, "year")
        source_url = _calendar_text(raw, "source_url")
        fetched_at = datetime.fromisoformat(_calendar_text(raw, "fetched_at"))
        if fetched_at.tzinfo is None or fetched_at.utcoffset() is None:
            raise ValueError("calendar fetched_at must be timezone-aware")
        segments = raw.get("segments")
        if not isinstance(segments, dict):
            raise ValueError("calendar segments must be an object")
        values = cast(dict[object, object], segments).get(segment)
        if not isinstance(values, list):
            raise ValueError("requested calendar segment is unavailable")
        holidays: set[date] = set()
        for raw_value in values:
            if not isinstance(raw_value, str):
                raise ValueError("calendar holiday must be an ISO date")
            parsed = date.fromisoformat(raw_value)
            if parsed.year != year:
                raise ValueError("calendar holiday year mismatch")
            holidays.add(parsed)
        return cls(
            year=year,
            source_url=source_url,
            fetched_at=fetched_at,
            holidays=frozenset(holidays),
        )


def decide_trading_day(
    day: date,
    *,
    dynamic_market_open: bool | None,
    local_calendar: LocalHolidayCalendar | None,
    manual_open_override: bool = False,
) -> TradingDayDecision:
    """Use dynamic truth when available; otherwise remain closed until override."""

    if dynamic_market_open is not None:
        return TradingDayDecision(
            market_open=dynamic_market_open,
            source=CalendarSource.DYNAMIC,
            caution=False,
            manual_override_required=False,
            reason="DYNAMIC_OPEN" if dynamic_market_open else "DYNAMIC_CLOSED",
        )
    if day.weekday() >= 5:
        return TradingDayDecision(False, CalendarSource.LOCAL_FALLBACK, False, False, "WEEKEND")
    if local_calendar is None or local_calendar.year != day.year:
        return TradingDayDecision(
            False,
            CalendarSource.LOCAL_FALLBACK,
            True,
            True,
            "LOCAL_CALENDAR_UNAVAILABLE",
        )
    if day in local_calendar.holidays:
        return TradingDayDecision(
            False, CalendarSource.LOCAL_FALLBACK, False, False, "LOCAL_HOLIDAY"
        )
    if not manual_open_override:
        return TradingDayDecision(
            False,
            CalendarSource.LOCAL_FALLBACK,
            True,
            True,
            "DYNAMIC_UNAVAILABLE_OVERRIDE_REQUIRED",
        )
    return TradingDayDecision(
        True,
        CalendarSource.MANUAL_OVERRIDE,
        True,
        False,
        "MANUAL_OPEN_WITH_LOCAL_WEEKDAY_CHECK",
    )


def _calendar_text(raw: dict[object, object], key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"calendar {key} is invalid")
    return value


def _calendar_int(raw: dict[object, object], key: str) -> int:
    value = raw.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"calendar {key} is invalid")
    return value
