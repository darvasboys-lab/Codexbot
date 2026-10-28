from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from codexbot.calendar_cache import NSECalendarSnapshot
from codexbot.instrument_cache import InstrumentSnapshot, LoadedInstrumentMaster
from codexbot.instruments import DhanInstrumentResolver, Exchange
from codexbot.models import ExecutionMode
from codexbot.persistence import SQLiteJournal
from codexbot.preflight import PreflightError, perform_test_preflight
from codexbot.settings import (
    BotSettings,
    DhanCredentials,
    RuntimeConfiguration,
    SecretValue,
    TelegramCredentials,
)

NOW = datetime(2026, 10, 28, 5, 0, tzinfo=UTC)


class FakeInstrumentCache:
    def __init__(self, loaded: LoadedInstrumentMaster) -> None:
        self.loaded = loaded
        self.enabled_exchanges: frozenset[Exchange] | None = None

    def load(
        self,
        *,
        maximum_age: timedelta,
        now: datetime,
        enabled_exchanges: frozenset[Exchange],
    ) -> LoadedInstrumentMaster:
        assert maximum_age == timedelta(days=1)
        assert now == NOW
        self.enabled_exchanges = enabled_exchanges
        return self.loaded


class FakeCalendarCache:
    def __init__(self, snapshot: NSECalendarSnapshot) -> None:
        self.snapshot = snapshot

    def load(self, *, maximum_age: timedelta) -> NSECalendarSnapshot:
        assert maximum_age == timedelta(days=1)
        return self.snapshot


def configuration(
    tmp_path: Path, *, mode: ExecutionMode = ExecutionMode.TEST
) -> RuntimeConfiguration:
    tmp_path.chmod(0o700)
    session = tmp_path / "udit.session"
    session.write_text("authorized", encoding="utf-8")
    session.chmod(0o600)
    settings = BotSettings(
        mode=mode,
        equity_active=True,
        fno_active=True,
        allowed_group_ids=frozenset({-1001, -1002, -1003}),
        authorized_source_ids=frozenset(),
        authorized_operator_ids=frozenset(),
        log_group_id=-9001,
        database_path=tmp_path / "codexbot.sqlite3",
        instrument_cache_directory=tmp_path / "instruments",
        instrument_maximum_age=timedelta(days=1),
        calendar_cache_path=tmp_path / "nse-calendar.json",
        calendar_maximum_age=timedelta(days=1),
        local_calendar_path=tmp_path / "exchange_holidays_2026.json",
        telegram_session_path=session,
    )
    return RuntimeConfiguration(
        settings=settings,
        telegram=TelegramCredentials(api_id=123, api_hash=SecretValue("secret")),
        dhan=DhanCredentials(
            client_id=SecretValue("client"),
            pin=SecretValue("123456"),
            totp_secret=SecretValue("BASE32SECRET"),
        ),
    )


def instrument_cache(tmp_path: Path) -> FakeInstrumentCache:
    snapshot = InstrumentSnapshot(
        path=tmp_path / "master.csv",
        sha256="a" * 64,
        byte_count=123,
        downloaded_at=NOW - timedelta(hours=1),
        source_url="https://images.dhan.co/example.csv",
        etag=None,
        last_modified=None,
    )
    return FakeInstrumentCache(
        LoadedInstrumentMaster(snapshot=snapshot, resolver=DhanInstrumentResolver(tuple()))
    )


def calendar_cache(*, year: int = 2026) -> FakeCalendarCache:
    return FakeCalendarCache(
        NSECalendarSnapshot(
            fetched_at=NOW - timedelta(hours=1),
            source_url="https://www.nseindia.com/api/holiday-master?type=trading",
            year=year,
            cash_holidays=frozenset(),
            fno_holidays=frozenset(),
        )
    )


def test_preflight_validates_local_test_dependencies_and_stays_fail_closed(
    tmp_path: Path,
) -> None:
    instruments = instrument_cache(tmp_path)
    journal = SQLiteJournal(tmp_path / "codexbot.sqlite3", clock=lambda: NOW)

    result = perform_test_preflight(
        configuration(tmp_path),
        now=NOW,
        instrument_cache=instruments,
        calendar_cache=calendar_cache(),
        journal=journal,
    )

    assert result.report.mode == "TEST"
    assert result.report.signal_group_count == 3
    assert result.report.equity_active is True
    assert result.report.fno_active is True
    assert result.report.feedback_enabled is False
    assert result.report.journal_mode == "wal"
    assert result.report.emergency_stop_engaged is True
    assert result.report.broker_executor == "ABSENT"
    assert instruments.enabled_exchanges == frozenset({Exchange.NSE, Exchange.BSE})


def test_preflight_refuses_wrong_calendar_year(tmp_path: Path) -> None:
    with pytest.raises(PreflightError, match="NSE_CALENDAR_YEAR_MISMATCH"):
        perform_test_preflight(
            configuration(tmp_path),
            now=NOW,
            instrument_cache=instrument_cache(tmp_path),
            calendar_cache=calendar_cache(year=2025),
        )


def test_preflight_refuses_live_before_reading_local_runtime_state(tmp_path: Path) -> None:
    with pytest.raises(PreflightError, match="LIVE_EXECUTOR_ABSENT"):
        perform_test_preflight(configuration(tmp_path, mode=ExecutionMode.LIVE), now=NOW)


def test_preflight_rejects_naive_time(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        perform_test_preflight(
            configuration(tmp_path),
            now=datetime(2026, 10, 28, 5, 0),
        )

