"""Runnable TEST-only Telegram signal-observation service composition."""

from __future__ import annotations

import argparse
import asyncio
import os
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path

from codexbot.checking import SignalChecker
from codexbot.instrument_cache import DhanInstrumentMasterCache
from codexbot.instruments import DhanInstrumentResolver, Exchange
from codexbot.models import ExecutionMode
from codexbot.parsing import TelegramMessageParser
from codexbot.persistence import SQLiteJournal
from codexbot.processing import SignalProcessor
from codexbot.settings import RuntimeConfiguration, load_protected_environment
from codexbot.telegram import TelethonListener


class RuntimeStartupError(RuntimeError):
    """A fixed startup failure suitable for service logs."""


def create_test_listener(
    configuration: RuntimeConfiguration,
    *,
    resolver: DhanInstrumentResolver,
    journal: SQLiteJournal | None = None,
) -> TelethonListener:
    """Build the complete safe listener graph and reject any LIVE configuration."""

    if configuration.settings.mode is not ExecutionMode.TEST:
        raise RuntimeStartupError("LIVE_EXECUTOR_ABSENT")
    active_journal = journal or SQLiteJournal(configuration.settings.database_path)
    active_journal.initialize()
    processor = SignalProcessor(
        journal=active_journal,
        parser=TelegramMessageParser(),
        checker=SignalChecker(configuration.settings.checker_policy()),
        instrument_resolver=resolver,
    )
    return TelethonListener(
        settings=configuration.settings,
        credentials=configuration.telegram,
        processor=processor,
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
        if configuration.settings.mode is not ExecutionMode.TEST:
            raise RuntimeStartupError("LIVE_EXECUTOR_ABSENT")
        now = (clock or (lambda: datetime.now(UTC)))()
        loaded = DhanInstrumentMasterCache(configuration.settings.instrument_cache_directory).load(
            maximum_age=configuration.settings.instrument_maximum_age,
            now=now,
            enabled_exchanges=frozenset({Exchange.NSE, Exchange.BSE}),
        )
        listener = create_test_listener(configuration, resolver=loaded.resolver)
        asyncio.run(listener.run())
        return 0
    finally:
        os.umask(previous_umask)


if __name__ == "__main__":
    raise SystemExit(main())
