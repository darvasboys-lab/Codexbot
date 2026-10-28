"""Fail-closed, secret-free readiness check for the TEST observation service."""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Protocol

from codexbot.calendar_cache import NSECalendarCache, NSECalendarSnapshot
from codexbot.instrument_cache import DhanInstrumentMasterCache, LoadedInstrumentMaster
from codexbot.instruments import Exchange
from codexbot.models import ExecutionMode
from codexbot.persistence import SQLiteJournal, integrity_check
from codexbot.settings import RuntimeConfiguration, load_protected_environment
from codexbot.telegram import validate_telegram_session


class PreflightError(RuntimeError):
    """A fixed deployment-readiness failure without credential content."""


class InstrumentCacheReader(Protocol):
    def load(
        self,
        *,
        maximum_age: timedelta,
        now: datetime,
        enabled_exchanges: frozenset[Exchange],
    ) -> LoadedInstrumentMaster: ...


class CalendarCacheReader(Protocol):
    def load(self, *, maximum_age: timedelta) -> NSECalendarSnapshot: ...


@dataclass(frozen=True, slots=True)
class TestPreflightReport:
    mode: str
    equity_active: bool
    fno_active: bool
    signal_group_count: int
    feedback_enabled: bool
    instrument_sha256: str
    instrument_downloaded_at: str
    calendar_year: int
    calendar_fetched_at: str
    journal_mode: str
    emergency_stop_engaged: bool
    broker_executor: str = "ABSENT"


@dataclass(frozen=True, slots=True)
class TestPreflightResult:
    report: TestPreflightReport
    instruments: LoadedInstrumentMaster
    journal: SQLiteJournal


def perform_test_preflight(
    configuration: RuntimeConfiguration,
    *,
    now: datetime | None = None,
    instrument_cache: InstrumentCacheReader | None = None,
    calendar_cache: CalendarCacheReader | None = None,
    journal: SQLiteJournal | None = None,
) -> TestPreflightResult:
    """Validate every local TEST startup dependency without broker connectivity."""

    if configuration.settings.mode is not ExecutionMode.TEST:
        raise PreflightError("LIVE_EXECUTOR_ABSENT")
    supplied_time = now or datetime.now(UTC)
    if supplied_time.tzinfo is None or supplied_time.utcoffset() is None:
        raise ValueError("preflight time must be timezone-aware")
    current = supplied_time.astimezone(UTC)
    validate_telegram_session(configuration.settings.telegram_session_path)
    active_instrument_cache = instrument_cache or DhanInstrumentMasterCache(
        configuration.settings.instrument_cache_directory
    )
    instruments = active_instrument_cache.load(
        maximum_age=configuration.settings.instrument_maximum_age,
        now=current,
        enabled_exchanges=frozenset({Exchange.NSE, Exchange.BSE}),
    )
    active_calendar_cache = calendar_cache or NSECalendarCache(
        configuration.settings.calendar_cache_path,
        clock=lambda: current,
    )
    calendar = active_calendar_cache.load(
        maximum_age=configuration.settings.calendar_maximum_age
    )
    if calendar.year != current.year:
        raise PreflightError("NSE_CALENDAR_YEAR_MISMATCH")
    active_journal = journal or SQLiteJournal(configuration.settings.database_path)
    active_journal.initialize()
    if integrity_check(configuration.settings.database_path) != ("ok",):
        raise PreflightError("SQLITE_INTEGRITY_FAILED")
    stop = active_journal.emergency_stop_status()
    return TestPreflightResult(
        report=TestPreflightReport(
            mode=configuration.settings.mode.value,
            equity_active=configuration.settings.equity_active,
            fno_active=configuration.settings.fno_active,
            signal_group_count=len(configuration.settings.allowed_group_ids),
            feedback_enabled=bool(configuration.settings.authorized_operator_ids),
            instrument_sha256=instruments.snapshot.sha256,
            instrument_downloaded_at=instruments.snapshot.downloaded_at.isoformat(),
            calendar_year=calendar.year,
            calendar_fetched_at=calendar.fetched_at.isoformat(),
            journal_mode=active_journal.journal_mode(),
            emergency_stop_engaged=stop.engaged,
        ),
        instruments=instruments,
        journal=active_journal,
    )


def main(
    argv: Sequence[str] | None = None,
    *,
    clock: Callable[[], datetime] | None = None,
) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--environment", type=Path, required=True)
    arguments = parser.parse_args(argv)
    previous_umask = os.umask(0o077)
    try:
        configuration = load_protected_environment(arguments.environment)
        result = perform_test_preflight(
            configuration,
            now=(clock or (lambda: datetime.now(UTC)))(),
        )
    finally:
        os.umask(previous_umask)
    print(json.dumps(asdict(result.report), sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

