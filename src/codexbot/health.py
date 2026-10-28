"""Secret-free runtime health composition for the single Codexbot process."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Protocol
from zoneinfo import ZoneInfo

from codexbot.calendar_cache import CalendarCacheError, NSECalendarCache
from codexbot.dhan import DhanAccessToken, DhanHealthResult
from codexbot.models import ExecutionMode
from codexbot.persistence import SQLiteJournal, integrity_check
from codexbot.telegram import TelegramHealth

_INDIA = ZoneInfo("Asia/Kolkata")
_HEALTH_TIME = time(hour=8, minute=0)


class DhanHealthProvider(Protocol):
    def refresh_and_check(self) -> tuple[DhanAccessToken | None, DhanHealthResult]: ...


@dataclass(frozen=True, slots=True)
class SystemHealthReport:
    checked_at: datetime
    execution_mode: ExecutionMode
    telegram_connected: bool
    telegram_authorized: bool
    telegram_error_code: str | None
    dhan_healthy: bool
    dhan_error_code: str | None
    dhan_token_expires_at: datetime | None
    journal_healthy: bool
    journal_error_code: str | None
    calendar_healthy: bool
    calendar_error_code: str | None
    emergency_stop_engaged: bool
    executor_state: str
    observation_healthy: bool
    live_entry_capable: bool


class SystemHealthCoordinator:
    """Run and audit health checks without enabling broker execution."""

    def __init__(
        self,
        *,
        journal: SQLiteJournal,
        dhan: DhanHealthProvider,
        telegram_health: Callable[[], TelegramHealth],
        calendar_health: Callable[[], tuple[bool, str | None]],
        execution_mode: ExecutionMode,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._journal = journal
        self._dhan = dhan
        self._telegram_health = telegram_health
        self._calendar_health = calendar_health
        self._execution_mode = execution_mode
        self._clock = clock or (lambda: datetime.now(UTC))

    def run_once(self) -> SystemHealthReport:
        """Refresh Dhan auth, inspect components, and append one redacted audit event."""

        checked_at = _aware_utc(self._clock())
        telegram = self._telegram_health()
        _, dhan = self._dhan.refresh_and_check()
        journal_healthy, journal_error = self._journal_health()
        calendar_healthy, calendar_error = self._calendar_health()
        stop = self._journal.emergency_stop_status()
        telegram_ok = (
            telegram.connected and telegram.authorized and telegram.last_error_code is None
        )
        observation_healthy = telegram_ok and dhan.healthy and journal_healthy and calendar_healthy
        executor_state = (
            "ABSENT_TEST_MODE"
            if self._execution_mode is ExecutionMode.TEST
            else "ABSENT_LIVE_BLOCKED"
        )
        report = SystemHealthReport(
            checked_at=checked_at,
            execution_mode=self._execution_mode,
            telegram_connected=telegram.connected,
            telegram_authorized=telegram.authorized,
            telegram_error_code=telegram.last_error_code,
            dhan_healthy=dhan.healthy,
            dhan_error_code=dhan.error_code,
            dhan_token_expires_at=dhan.token_expires_at,
            journal_healthy=journal_healthy,
            journal_error_code=journal_error,
            calendar_healthy=calendar_healthy,
            calendar_error_code=calendar_error,
            emergency_stop_engaged=stop.engaged,
            executor_state=executor_state,
            observation_healthy=observation_healthy,
            live_entry_capable=False,
        )
        self._journal.append_audit_event(
            event_type="SYSTEM_HEALTH_CHECKED",
            entity_type="system",
            entity_id=None,
            state="HEALTHY" if observation_healthy else "UNHEALTHY",
            details={
                "dhan_error_code": report.dhan_error_code,
                "dhan_healthy": report.dhan_healthy,
                "dhan_token_expires_at": (
                    report.dhan_token_expires_at.isoformat()
                    if report.dhan_token_expires_at
                    else None
                ),
                "emergency_stop_engaged": report.emergency_stop_engaged,
                "calendar_error_code": report.calendar_error_code,
                "calendar_healthy": report.calendar_healthy,
                "execution_mode": report.execution_mode.value,
                "executor_state": report.executor_state,
                "journal_error_code": report.journal_error_code,
                "journal_healthy": report.journal_healthy,
                "live_entry_capable": False,
                "telegram_authorized": report.telegram_authorized,
                "telegram_connected": report.telegram_connected,
                "telegram_error_code": report.telegram_error_code,
            },
            occurred_at=checked_at,
        )
        return report

    def _journal_health(self) -> tuple[bool, str | None]:
        try:
            results = integrity_check(self._journal.database_path)
        except (OSError, sqlite3.Error):
            return False, "JOURNAL_INTEGRITY_CHECK_FAILED"
        if results != ("ok",):
            return False, "JOURNAL_INTEGRITY_INVALID"
        return True, None


def scheduled_health_time(service_date: date) -> datetime:
    """Return the fixed 08:00 Asia/Kolkata instant for an externally approved day."""

    return datetime.combine(service_date, _HEALTH_TIME, tzinfo=_INDIA)


def calendar_cache_health(
    cache: NSECalendarCache, *, maximum_age: timedelta
) -> tuple[bool, str | None]:
    """Return only a fixed cache error code; never expose payload or paths."""

    try:
        cache.load(maximum_age=maximum_age)
    except CalendarCacheError as error:
        return False, str(error)
    return True, None


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("health clock must be timezone-aware")
    return value.astimezone(UTC)
