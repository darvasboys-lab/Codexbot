import os
from pathlib import Path

import pytest

from codexbot import (
    ExecutionMode,
    SettingsError,
    configuration_from_mapping,
    load_protected_environment,
)


def valid_values() -> dict[str, str]:
    return {
        "CODEXBOT_EQUITY_ACTIVE": "false",
        "CODEXBOT_FNO_ACTIVE": "true",
        "CODEXBOT_GROUP_IDS": "-1001,-1002",
        "CODEXBOT_AUTHORIZED_SOURCE_IDS": "2001,2002",
        "CODEXBOT_OPERATOR_IDS": "3001",
        "CODEXBOT_LOG_GROUP_ID": "-9001",
        "CODEXBOT_DATABASE_PATH": "/var/lib/codexbot/codexbot.sqlite3",
        "CODEXBOT_INSTRUMENT_CACHE_DIRECTORY": "/var/lib/codexbot/instruments",
        "CODEXBOT_INSTRUMENT_MAX_AGE_SECONDS": "3600",
        "CODEXBOT_CALENDAR_CACHE_PATH": "/var/lib/codexbot/nse-calendar.json",
        "CODEXBOT_CALENDAR_MAX_AGE_SECONDS": "86400",
        "CODEXBOT_LOCAL_CALENDAR_PATH": "/opt/codexbot/config/exchange_holidays_2026.json",
        "CODEXBOT_MAX_ORDER_AMOUNT": "100000",
        "CODEXBOT_DAILY_LOSS_LIMIT": "5000",
        "CODEXBOT_TOTAL_EXPOSURE_LIMIT": "300000",
        "CODEXBOT_MAX_OPEN_POSITIONS": "5",
        "CODEXBOT_MAX_DAILY_TRADES": "10",
        "CODEXBOT_OPTION_SIZING_MODE": "BUDGET",
        "CODEXBOT_OPTION_SIZING_VALUE": "50000",
        "TELEGRAM_API_ID": "123456",
        "TELEGRAM_API_HASH": "telegram-secret-hash",
        "TELEGRAM_SESSION_PATH": "/var/lib/codexbot/udit.session",
        "DHAN_CLIENT_ID": "dhan-client",
        "DHAN_PIN": "123456",
        "DHAN_TOTP_SECRET": "BASE32SECRET",
    }


def environment_text(values: dict[str, str]) -> str:
    return "\n".join(f"{name}={value}" for name, value in values.items()) + "\n"


def test_configuration_defaults_only_common_mode_to_test() -> None:
    configuration = configuration_from_mapping(valid_values())

    assert configuration.settings.mode is ExecutionMode.TEST
    assert configuration.settings.equity_active is False
    assert configuration.settings.fno_active is True
    assert configuration.settings.allowed_group_ids == frozenset({-1001, -1002})
    assert configuration.settings.authorized_source_ids == frozenset({2001, 2002})
    assert configuration.settings.authorized_operator_ids == frozenset({3001})
    assert configuration.settings.instrument_maximum_age.total_seconds() == 3600
    assert configuration.settings.calendar_maximum_age.total_seconds() == 86400
    assert configuration.settings.risk_limits is not None
    assert str(configuration.settings.risk_limits.maximum_order_amount) == "100000"
    assert configuration.settings.option_sizing is not None
    assert configuration.settings.option_sizing.mode.value == "BUDGET"
    assert configuration.settings.checker_policy().execution_mode is ExecutionMode.TEST


def test_explicit_live_mode_does_not_create_an_execution_capability() -> None:
    values = valid_values()
    values["CODEXBOT_MODE"] = "LIVE"

    configuration = configuration_from_mapping(values)

    assert configuration.settings.mode is ExecutionMode.LIVE
    assert not hasattr(configuration, "place_order")


def test_active_equity_requires_all_unresolved_setup_price_values() -> None:
    values = valid_values()
    values["CODEXBOT_EQUITY_ACTIVE"] = "true"

    with pytest.raises(SettingsError, match="active equity requires"):
        configuration_from_mapping(values)

    values.update(
        {
            "CODEXBOT_EQUITY_PRICE_PERCENTAGE": "1.25",
            "CODEXBOT_YAHOO_MAX_MARKET_AGE_SECONDS": "3",
            "CODEXBOT_YAHOO_MAX_LOCAL_AGE_SECONDS": "3",
            "CODEXBOT_RISK_PERCENT_PER_TRADE": "1",
            "CODEXBOT_MAX_CAPITAL_ALLOCATION_PERCENT": "10",
        }
    )
    configuration = configuration_from_mapping(values)
    assert str(configuration.settings.equity_price_percentage) == "1.25"
    assert configuration.settings.yahoo_maximum_market_age is not None
    assert configuration.settings.yahoo_maximum_local_age is not None
    assert configuration.settings.yahoo_maximum_market_age.total_seconds() == 3
    assert configuration.settings.yahoo_maximum_local_age.total_seconds() == 3


def test_active_equity_rejects_stale_age_and_requires_fractional_values() -> None:
    values = valid_values()
    values.update(
        {
            "CODEXBOT_EQUITY_ACTIVE": "true",
            "CODEXBOT_EQUITY_PRICE_PERCENTAGE": "1.25",
            "CODEXBOT_YAHOO_MAX_MARKET_AGE_SECONDS": "4",
            "CODEXBOT_YAHOO_MAX_LOCAL_AGE_SECONDS": "3",
        }
    )
    with pytest.raises(SettingsError, match="cannot exceed 3 seconds"):
        configuration_from_mapping(values)

    values["CODEXBOT_YAHOO_MAX_MARKET_AGE_SECONDS"] = "3"
    with pytest.raises(SettingsError, match="fixed-fractional"):
        configuration_from_mapping(values)


def test_active_segment_requires_all_risk_values() -> None:
    values = valid_values()
    for name in (
        "CODEXBOT_MAX_ORDER_AMOUNT",
        "CODEXBOT_DAILY_LOSS_LIMIT",
        "CODEXBOT_TOTAL_EXPOSURE_LIMIT",
        "CODEXBOT_MAX_OPEN_POSITIONS",
        "CODEXBOT_MAX_DAILY_TRADES",
    ):
        values.pop(name)

    with pytest.raises(SettingsError, match="active segment requires"):
        configuration_from_mapping(values)

    values["CODEXBOT_FNO_ACTIVE"] = "false"
    configuration = configuration_from_mapping(values)
    assert configuration.settings.risk_limits is None


def test_partial_risk_settings_fail_even_when_segments_are_inactive() -> None:
    values = valid_values()
    values["CODEXBOT_EQUITY_ACTIVE"] = "false"
    values["CODEXBOT_FNO_ACTIVE"] = "false"
    values.pop("CODEXBOT_MAX_DAILY_TRADES")

    with pytest.raises(SettingsError, match="supplied together"):
        configuration_from_mapping(values)


def test_active_segment_requires_explicit_valid_sizing_selection() -> None:
    values = valid_values()
    values.pop("CODEXBOT_OPTION_SIZING_MODE")
    values.pop("CODEXBOT_OPTION_SIZING_VALUE")

    with pytest.raises(SettingsError, match="active F&O requires"):
        configuration_from_mapping(values)

    values["CODEXBOT_OPTION_SIZING_MODE"] = "FIXED"
    values["CODEXBOT_OPTION_SIZING_VALUE"] = "1.5"
    with pytest.raises(SettingsError, match="whole number"):
        configuration_from_mapping(values)


def test_credentials_never_appear_in_repr_or_string() -> None:
    configuration = configuration_from_mapping(valid_values())
    rendered = repr(configuration)

    assert "telegram-secret-hash" not in rendered
    assert "BASE32SECRET" not in rendered
    assert "123456" not in rendered
    assert str(configuration.telegram.api_hash) == "<redacted>"
    assert configuration.telegram.api_hash.reveal() == "telegram-secret-hash"


@pytest.mark.parametrize(
    ("name", "value", "message"),
    [
        ("CODEXBOT_EQUITY_ACTIVE", "yes", "true or false"),
        ("CODEXBOT_GROUP_IDS", "-1001,-1001", "duplicate IDs"),
        ("CODEXBOT_AUTHORIZED_SOURCE_IDS", "0", "cannot contain zero"),
        ("CODEXBOT_LOG_GROUP_ID", "0", "cannot be zero"),
        ("CODEXBOT_INSTRUMENT_MAX_AGE_SECONDS", "0", "must be positive"),
        ("TELEGRAM_API_ID", "not-an-int", "must be an integer"),
        ("DHAN_PIN", "1234", "6-digit numeric"),
        ("CODEXBOT_MODE", "PAPER", "TEST or LIVE"),
    ],
)
def test_invalid_setting_fails_closed(name: str, value: str, message: str) -> None:
    values = valid_values()
    values[name] = value

    with pytest.raises(SettingsError, match=message):
        configuration_from_mapping(values)


def test_missing_secret_fails_without_echoing_secret_values() -> None:
    values = valid_values()
    del values["DHAN_PIN"]

    with pytest.raises(SettingsError, match="DHAN_PIN is required") as error:
        configuration_from_mapping(values)

    assert "BASE32SECRET" not in str(error.value)


def test_log_group_must_be_separate_from_signal_groups() -> None:
    values = valid_values()
    values["CODEXBOT_LOG_GROUP_ID"] = "-1001"

    with pytest.raises(SettingsError, match="separate from signal groups"):
        configuration_from_mapping(values)


def test_loads_owner_only_regular_environment_file(tmp_path: Path) -> None:
    environment_path = tmp_path / "codexbot.env"
    environment_path.write_text(environment_text(valid_values()), encoding="utf-8")
    environment_path.chmod(0o600)

    configuration = load_protected_environment(environment_path)

    assert configuration.settings.log_group_id == -9001


def test_rejects_group_or_world_readable_environment_file(tmp_path: Path) -> None:
    environment_path = tmp_path / "codexbot.env"
    environment_path.write_text(environment_text(valid_values()), encoding="utf-8")
    environment_path.chmod(0o640)

    with pytest.raises(SettingsError, match="0600"):
        load_protected_environment(environment_path)


def test_rejects_symlink_environment_file(tmp_path: Path) -> None:
    target = tmp_path / "target.env"
    target.write_text(environment_text(valid_values()), encoding="utf-8")
    target.chmod(0o600)
    link = tmp_path / "codexbot.env"
    os.symlink(target, link)

    with pytest.raises(SettingsError, match="symlink"):
        load_protected_environment(link)


@pytest.mark.parametrize(
    ("line", "message"),
    [
        ("UNKNOWN_KEY=value", "unknown environment key"),
        ("CODEXBOT_MODE=TEST\nCODEXBOT_MODE=LIVE", "duplicate environment key"),
        ('TELEGRAM_API_HASH="unterminated', "unterminated quote"),
        ("not an assignment", "invalid environment syntax"),
    ],
)
def test_environment_file_syntax_is_strict(tmp_path: Path, line: str, message: str) -> None:
    environment_path = tmp_path / "codexbot.env"
    environment_path.write_text(line + "\n", encoding="utf-8")
    environment_path.chmod(0o600)

    with pytest.raises(SettingsError, match=message):
        load_protected_environment(environment_path)
