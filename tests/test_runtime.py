from datetime import timedelta
from pathlib import Path

import pytest

from codexbot import (
    BotSettings,
    DhanCredentials,
    DhanInstrumentResolver,
    ExecutionMode,
    RuntimeConfiguration,
    RuntimeStartupError,
    SecretValue,
    TelegramCredentials,
    create_test_listener,
)


def configuration(tmp_path: Path, *, mode: ExecutionMode) -> RuntimeConfiguration:
    settings = BotSettings(
        mode=mode,
        equity_active=False,
        fno_active=False,
        allowed_group_ids=frozenset({-1001}),
        authorized_source_ids=frozenset({2001}),
        authorized_operator_ids=frozenset({3001}),
        log_group_id=-9001,
        database_path=tmp_path / "codexbot.sqlite3",
        instrument_cache_directory=tmp_path / "instruments",
        instrument_maximum_age=timedelta(hours=1),
        calendar_cache_path=tmp_path / "nse-calendar.json",
        calendar_maximum_age=timedelta(days=1),
        local_calendar_path=tmp_path / "exchange_holidays_2026.json",
        telegram_session_path=tmp_path / "udit.session",
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


def test_runtime_builds_complete_test_listener_without_order_capability(tmp_path: Path) -> None:
    listener = create_test_listener(
        configuration(tmp_path, mode=ExecutionMode.TEST),
        resolver=DhanInstrumentResolver(tuple()),
    )

    assert not hasattr(listener, "place_order")
    assert not hasattr(listener, "modify_order")
    assert not hasattr(listener, "cancel_order")


def test_runtime_refuses_live_mode_while_executor_is_absent(tmp_path: Path) -> None:
    with pytest.raises(RuntimeStartupError, match="LIVE_EXECUTOR_ABSENT"):
        create_test_listener(
            configuration(tmp_path, mode=ExecutionMode.LIVE),
            resolver=DhanInstrumentResolver(tuple()),
        )
