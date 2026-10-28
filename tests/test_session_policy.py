from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from codexbot import (
    CalendarSource,
    LocalHolidayCalendar,
    NSECalendarCache,
    NSECalendarSegment,
    SessionPhase,
    SQLiteJournal,
    TradingCalendarCoordinator,
    decide_trading_day,
    session_decision,
)


def test_session_boundaries_fail_closed_outside_normal_execution() -> None:
    initialization = session_decision(
        datetime(2026, 10, 28, 3, 15, tzinfo=UTC), trading_day_open=True
    )  # 08:45 IST
    normal = session_decision(
        datetime(2026, 10, 28, 3, 46, tzinfo=UTC), trading_day_open=True
    )  # 09:16 IST
    square_off = session_decision(
        datetime(2026, 10, 28, 9, 40, tzinfo=UTC), trading_day_open=True
    )  # 15:10 IST
    eod = session_decision(
        datetime(2026, 10, 28, 10, 5, tzinfo=UTC), trading_day_open=True
    )  # 15:35 IST

    assert initialization.phase is SessionPhase.INITIALIZATION
    assert initialization.new_entries_allowed is False
    assert normal.phase is SessionPhase.NORMAL_EXECUTION
    assert normal.new_entries_allowed is True
    assert square_off.phase is SessionPhase.SQUARE_OFF
    assert square_off.cancel_pending_entries_due is True
    assert eod.phase is SessionPhase.EOD_RECONCILIATION
    assert eod.reconciliation_due is True
    assert eod.rotate_logs_due is True


def test_local_calendar_and_dynamic_failure_require_manual_open_override() -> None:
    calendar = LocalHolidayCalendar.load(
        Path(__file__).parents[1] / "config" / "exchange_holidays_2026.json",
        segment="NSE_CM",
    )
    holiday = decide_trading_day(
        date(2026, 10, 20), dynamic_market_open=None, local_calendar=calendar
    )
    weekday = decide_trading_day(
        date(2026, 10, 28), dynamic_market_open=None, local_calendar=calendar
    )
    override = decide_trading_day(
        date(2026, 10, 28),
        dynamic_market_open=None,
        local_calendar=calendar,
        manual_open_override=True,
    )

    assert holiday.market_open is False
    assert holiday.reason == "LOCAL_HOLIDAY"
    assert weekday.market_open is False
    assert weekday.manual_override_required is True
    assert override.market_open is True
    assert override.source is CalendarSource.MANUAL_OVERRIDE
    assert override.caution is True


def test_dynamic_calendar_response_has_priority() -> None:
    decision = decide_trading_day(date(2026, 10, 28), dynamic_market_open=True, local_calendar=None)

    assert decision.market_open is True
    assert decision.source is CalendarSource.DYNAMIC


def test_authenticated_manual_override_can_open_an_official_special_session() -> None:
    decision = decide_trading_day(
        date(2026, 11, 8),
        dynamic_market_open=False,
        local_calendar=None,
        manual_open_override=True,
    )

    assert decision.market_open is True
    assert decision.source is CalendarSource.MANUAL_OVERRIDE
    assert decision.caution is True
    assert decision.reason == "MANUAL_OPEN_OVERRIDE"


def test_calendar_coordinator_uses_durable_override_when_dynamic_cache_is_missing(
    tmp_path: Path,
) -> None:
    journal = SQLiteJournal(
        tmp_path / "codexbot.sqlite3", clock=lambda: datetime(2026, 10, 28, tzinfo=UTC)
    )
    journal.initialize()
    coordinator = TradingCalendarCoordinator(
        cache=NSECalendarCache(tmp_path / "missing-calendar.json"),
        journal=journal,
        local_calendar_path=(Path(__file__).parents[1] / "config" / "exchange_holidays_2026.json"),
        maximum_cache_age=timedelta(days=1),
    )
    day = date(2026, 10, 28)

    closed = coordinator.decide(day, NSECalendarSegment.CASH)
    journal.set_calendar_override(
        service_date=day,
        segment="NSE_CM",
        enabled=True,
        reason="operator verified official special opening",
        actor="local-user:udit:uid:1000",
    )
    opened = coordinator.decide(day, NSECalendarSegment.CASH)

    assert closed.market_open is False
    assert closed.manual_override_required is True
    assert opened.market_open is True
    assert opened.source is CalendarSource.MANUAL_OVERRIDE
