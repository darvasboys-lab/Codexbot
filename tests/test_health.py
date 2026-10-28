import json
import sqlite3
from datetime import UTC, date, datetime
from pathlib import Path

from codexbot import (
    DhanHealthResult,
    ExecutionMode,
    SQLiteJournal,
    SystemHealthCoordinator,
    TelegramHealth,
    scheduled_health_time,
)

NOW = datetime(2026, 10, 28, 2, 30, tzinfo=UTC)


class StubDhanHealth:
    def __init__(self, result: DhanHealthResult) -> None:
        self.result = result
        self.calls = 0

    def refresh_and_check(self) -> tuple[None, DhanHealthResult]:
        self.calls += 1
        return None, self.result


def healthy_dhan() -> DhanHealthResult:
    return DhanHealthResult(
        healthy=True,
        checked_at=NOW,
        token_expires_at=datetime(2026, 10, 29, 2, 30, tzinfo=UTC),
        available_balance=None,
        error_code=None,
    )


def test_scheduled_health_time_is_exactly_0800_asia_kolkata() -> None:
    scheduled = scheduled_health_time(date(2026, 10, 28))

    assert scheduled.hour == 8
    assert scheduled.minute == 0
    assert scheduled.utcoffset() is not None
    assert scheduled.astimezone(UTC) == NOW


def test_test_mode_health_is_audited_without_claiming_live_capability(tmp_path: Path) -> None:
    database = tmp_path / "codexbot.sqlite3"
    journal = SQLiteJournal(database, clock=lambda: NOW)
    journal.initialize()
    dhan = StubDhanHealth(healthy_dhan())
    telegram = TelegramHealth(connected=True, authorized=True)
    coordinator = SystemHealthCoordinator(
        journal=journal,
        dhan=dhan,
        telegram_health=lambda: telegram,
        calendar_health=lambda: (True, None),
        execution_mode=ExecutionMode.TEST,
        clock=lambda: NOW,
    )

    report = coordinator.run_once()

    assert report.observation_healthy is True
    assert report.live_entry_capable is False
    assert report.executor_state == "ABSENT_TEST_MODE"
    assert report.emergency_stop_engaged is True
    assert dhan.calls == 1
    with sqlite3.connect(database) as connection:
        row = connection.execute(
            "SELECT state, details_json FROM audit_events WHERE event_type='SYSTEM_HEALTH_CHECKED'"
        ).fetchone()
    assert row is not None
    details = json.loads(row[1])
    assert row[0] == "HEALTHY"
    assert details["live_entry_capable"] is False
    assert "available_balance" not in details


def test_component_failure_produces_fixed_non_secret_health_codes(tmp_path: Path) -> None:
    journal = SQLiteJournal(tmp_path / "codexbot.sqlite3", clock=lambda: NOW)
    journal.initialize()
    dhan = StubDhanHealth(
        DhanHealthResult(
            healthy=False,
            checked_at=NOW,
            token_expires_at=None,
            available_balance=None,
            error_code="DHAN_HTTP_401",
        )
    )
    coordinator = SystemHealthCoordinator(
        journal=journal,
        dhan=dhan,
        telegram_health=lambda: TelegramHealth(
            connected=False,
            authorized=True,
            last_error_code="TelegramListenerError",
        ),
        calendar_health=lambda: (False, "NSE_CALENDAR_CACHE_STALE"),
        execution_mode=ExecutionMode.LIVE,
        clock=lambda: NOW,
    )

    report = coordinator.run_once()

    assert report.observation_healthy is False
    assert report.executor_state == "ABSENT_LIVE_BLOCKED"
    assert report.dhan_error_code == "DHAN_HTTP_401"
    assert report.telegram_error_code == "TelegramListenerError"
    assert report.calendar_error_code == "NSE_CALENDAR_CACHE_STALE"
    assert report.live_entry_capable is False
