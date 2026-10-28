"""Strict protected-environment configuration for the single Codexbot instance."""

from __future__ import annotations

import os
import re
import stat
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path

from codexbot.models import CheckerPolicy, ExecutionMode
from codexbot.risk import RiskLimits


class SettingsError(ValueError):
    """Raised when configuration is missing, ambiguous, or insecure."""


@dataclass(frozen=True, slots=True)
class SecretValue:
    """Prevent accidental display while allowing explicit adapter access."""

    _value: str = field(repr=False)

    def __post_init__(self) -> None:
        if not self._value:
            raise SettingsError("secret value cannot be empty")

    def reveal(self) -> str:
        return self._value

    def __str__(self) -> str:
        return "<redacted>"

    def __repr__(self) -> str:
        return "SecretValue(<redacted>)"


@dataclass(frozen=True, slots=True)
class TelegramCredentials:
    api_id: int = field(repr=False)
    api_hash: SecretValue = field(repr=False)
    phone_number: SecretValue | None = field(default=None, repr=False)


@dataclass(frozen=True, slots=True)
class DhanCredentials:
    client_id: SecretValue = field(repr=False)
    pin: SecretValue = field(repr=False)
    totp_secret: SecretValue = field(repr=False)


@dataclass(frozen=True, slots=True)
class BotSettings:
    mode: ExecutionMode
    equity_active: bool
    fno_active: bool
    allowed_group_ids: frozenset[int]
    authorized_source_ids: frozenset[int]
    log_group_id: int
    database_path: Path
    instrument_cache_directory: Path
    instrument_maximum_age: timedelta
    telegram_session_path: Path
    equity_price_percentage: Decimal | None = None
    yahoo_maximum_market_age: timedelta | None = None
    yahoo_maximum_local_age: timedelta | None = None
    risk_limits: RiskLimits | None = None

    def checker_policy(self) -> CheckerPolicy:
        return CheckerPolicy(
            allowed_group_ids=self.allowed_group_ids,
            authorized_source_ids=self.authorized_source_ids,
            equity_active=self.equity_active,
            fno_active=self.fno_active,
            execution_mode=self.mode,
        )


@dataclass(frozen=True, slots=True)
class RuntimeConfiguration:
    settings: BotSettings
    telegram: TelegramCredentials = field(repr=False)
    dhan: DhanCredentials = field(repr=False)


def load_protected_environment(path: str | Path) -> RuntimeConfiguration:
    """Load one regular, owner-only environment file without interpolation."""

    environment_path = Path(path)
    _validate_protected_file(environment_path)
    try:
        text = environment_path.read_text(encoding="utf-8")
    except OSError as error:
        raise SettingsError("cannot read protected environment file") from error
    values = _parse_environment_text(text)
    return configuration_from_mapping(values)


def configuration_from_mapping(values: Mapping[str, str]) -> RuntimeConfiguration:
    """Build typed settings from explicit values; unrelated process env is ignored."""

    mode_text = values.get("CODEXBOT_MODE", ExecutionMode.TEST.value).strip().upper()
    try:
        mode = ExecutionMode(mode_text)
    except ValueError as error:
        raise SettingsError("CODEXBOT_MODE must be TEST or LIVE") from error

    equity_active = _required_bool(values, "CODEXBOT_EQUITY_ACTIVE")
    equity_price_percentage = _optional_nonnegative_decimal(
        values, "CODEXBOT_EQUITY_PRICE_PERCENTAGE"
    )
    yahoo_maximum_market_age = _optional_positive_duration(
        values, "CODEXBOT_YAHOO_MAX_MARKET_AGE_SECONDS"
    )
    yahoo_maximum_local_age = _optional_positive_duration(
        values, "CODEXBOT_YAHOO_MAX_LOCAL_AGE_SECONDS"
    )
    if equity_active and (
        equity_price_percentage is None
        or yahoo_maximum_market_age is None
        or yahoo_maximum_local_age is None
    ):
        raise SettingsError(
            "active equity requires price percentage and both Yahoo quote age limits"
        )

    fno_active = _required_bool(values, "CODEXBOT_FNO_ACTIVE")
    segment_active = equity_active or fno_active
    risk_limits = _optional_risk_limits(values)
    if segment_active and risk_limits is None:
        raise SettingsError("an active segment requires all six risk limit settings")

    settings = BotSettings(
        mode=mode,
        equity_active=equity_active,
        fno_active=fno_active,
        allowed_group_ids=_required_id_set(values, "CODEXBOT_GROUP_IDS"),
        authorized_source_ids=_required_id_set(values, "CODEXBOT_AUTHORIZED_SOURCE_IDS"),
        log_group_id=_required_nonzero_int(values, "CODEXBOT_LOG_GROUP_ID"),
        database_path=_required_path(values, "CODEXBOT_DATABASE_PATH"),
        instrument_cache_directory=_required_path(values, "CODEXBOT_INSTRUMENT_CACHE_DIRECTORY"),
        instrument_maximum_age=timedelta(
            seconds=_required_positive_int(values, "CODEXBOT_INSTRUMENT_MAX_AGE_SECONDS")
        ),
        telegram_session_path=_required_path(values, "TELEGRAM_SESSION_PATH"),
        equity_price_percentage=equity_price_percentage,
        yahoo_maximum_market_age=yahoo_maximum_market_age,
        yahoo_maximum_local_age=yahoo_maximum_local_age,
        risk_limits=risk_limits,
    )
    telegram = TelegramCredentials(
        api_id=_required_positive_int(values, "TELEGRAM_API_ID"),
        api_hash=SecretValue(_required(values, "TELEGRAM_API_HASH")),
        phone_number=_optional_secret(values, "TELEGRAM_PHONE_NUMBER"),
    )
    dhan_pin = _required(values, "DHAN_PIN")
    if len(dhan_pin) != 6 or not dhan_pin.isascii() or not dhan_pin.isdigit():
        raise SettingsError("DHAN_PIN must be a 6-digit numeric code")
    dhan = DhanCredentials(
        client_id=SecretValue(_required(values, "DHAN_CLIENT_ID")),
        pin=SecretValue(dhan_pin),
        totp_secret=SecretValue(_required(values, "DHAN_TOTP_SECRET")),
    )
    return RuntimeConfiguration(settings=settings, telegram=telegram, dhan=dhan)


def _validate_protected_file(path: Path) -> None:
    if path.is_symlink():
        raise SettingsError("protected environment file cannot be a symlink")
    try:
        metadata = path.stat()
    except OSError as error:
        raise SettingsError("protected environment file is unavailable") from error
    if not stat.S_ISREG(metadata.st_mode):
        raise SettingsError("protected environment path must be a regular file")
    if metadata.st_uid != os.geteuid():
        raise SettingsError("protected environment file must be owned by the service user")
    if stat.S_IMODE(metadata.st_mode) & 0o077:
        raise SettingsError("protected environment file permissions must be 0600 or stricter")


def _parse_environment_text(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        match = _ENV_LINE.fullmatch(line)
        if match is None:
            raise SettingsError(f"invalid environment syntax on line {line_number}")
        name = match.group("name")
        if name not in _KNOWN_KEYS:
            raise SettingsError(f"unknown environment key on line {line_number}: {name}")
        if name in values:
            raise SettingsError(f"duplicate environment key on line {line_number}: {name}")
        values[name] = _unquote(match.group("value"), line_number=line_number)
    return values


def _unquote(value: str, *, line_number: int) -> str:
    stripped = value.strip()
    if not stripped:
        return ""
    if stripped[0] in {'"', "'"}:
        if len(stripped) < 2 or stripped[-1] != stripped[0]:
            raise SettingsError(f"unterminated quote on line {line_number}")
        return stripped[1:-1]
    if "#" in stripped:
        stripped = stripped.split("#", maxsplit=1)[0].rstrip()
    return stripped


def _required(values: Mapping[str, str], name: str) -> str:
    value = values.get(name, "").strip()
    if not value:
        raise SettingsError(f"{name} is required")
    return value


def _required_bool(values: Mapping[str, str], name: str) -> bool:
    value = _required(values, name).lower()
    if value == "true":
        return True
    if value == "false":
        return False
    raise SettingsError(f"{name} must be true or false")


def _required_int(values: Mapping[str, str], name: str) -> int:
    value = _required(values, name)
    try:
        return int(value)
    except ValueError as error:
        raise SettingsError(f"{name} must be an integer") from error


def _required_positive_int(values: Mapping[str, str], name: str) -> int:
    value = _required_int(values, name)
    if value <= 0:
        raise SettingsError(f"{name} must be positive")
    return value


def _required_nonzero_int(values: Mapping[str, str], name: str) -> int:
    value = _required_int(values, name)
    if value == 0:
        raise SettingsError(f"{name} cannot be zero")
    return value


def _required_id_set(values: Mapping[str, str], name: str) -> frozenset[int]:
    parts = [part.strip() for part in _required(values, name).split(",")]
    if any(not part for part in parts):
        raise SettingsError(f"{name} contains an empty ID")
    try:
        parsed = [int(part) for part in parts]
    except ValueError as error:
        raise SettingsError(f"{name} must contain comma-separated integers") from error
    if any(value == 0 for value in parsed):
        raise SettingsError(f"{name} cannot contain zero")
    result = frozenset(parsed)
    if len(result) != len(parsed):
        raise SettingsError(f"{name} cannot contain duplicate IDs")
    return result


def _required_path(values: Mapping[str, str], name: str) -> Path:
    return Path(_required(values, name)).expanduser()


def _optional_secret(values: Mapping[str, str], name: str) -> SecretValue | None:
    value = values.get(name, "").strip()
    return SecretValue(value) if value else None


def _optional_nonnegative_decimal(values: Mapping[str, str], name: str) -> Decimal | None:
    text = values.get(name, "").strip()
    if not text:
        return None
    try:
        value = Decimal(text)
    except InvalidOperation as error:
        raise SettingsError(f"{name} must be a decimal") from error
    if not value.is_finite() or value < 0:
        raise SettingsError(f"{name} must be finite and non-negative")
    return value


def _optional_positive_duration(values: Mapping[str, str], name: str) -> timedelta | None:
    text = values.get(name, "").strip()
    if not text:
        return None
    seconds = _required_positive_int(values, name)
    return timedelta(seconds=seconds)


def _optional_risk_limits(values: Mapping[str, str]) -> RiskLimits | None:
    names = (
        "CODEXBOT_MAX_ORDER_AMOUNT",
        "CODEXBOT_MINIMUM_TRADE_FUNDS",
        "CODEXBOT_DAILY_LOSS_LIMIT",
        "CODEXBOT_TOTAL_EXPOSURE_LIMIT",
        "CODEXBOT_MAX_OPEN_POSITIONS",
        "CODEXBOT_MAX_DAILY_TRADES",
    )
    supplied = [bool(values.get(name, "").strip()) for name in names]
    if not any(supplied):
        return None
    if not all(supplied):
        raise SettingsError("risk limit settings must be supplied together")
    return RiskLimits(
        maximum_order_amount=_required_positive_decimal(values, names[0]),
        minimum_trade_funds=_required_positive_decimal(values, names[1]),
        daily_loss_limit=_required_positive_decimal(values, names[2]),
        total_exposure_limit=_required_positive_decimal(values, names[3]),
        maximum_open_positions=_required_positive_int(values, names[4]),
        maximum_daily_trades=_required_positive_int(values, names[5]),
    )


def _required_positive_decimal(values: Mapping[str, str], name: str) -> Decimal:
    text = _required(values, name)
    try:
        value = Decimal(text)
    except InvalidOperation as error:
        raise SettingsError(f"{name} must be a decimal") from error
    if not value.is_finite() or value <= 0:
        raise SettingsError(f"{name} must be finite and positive")
    return value


_ENV_LINE = re.compile(r"(?:export\s+)?(?P<name>[A-Za-z_][A-Za-z0-9_]*)=(?P<value>.*)")
_KNOWN_KEYS = frozenset(
    {
        "CODEXBOT_MODE",
        "CODEXBOT_EQUITY_ACTIVE",
        "CODEXBOT_FNO_ACTIVE",
        "CODEXBOT_GROUP_IDS",
        "CODEXBOT_AUTHORIZED_SOURCE_IDS",
        "CODEXBOT_LOG_GROUP_ID",
        "CODEXBOT_DATABASE_PATH",
        "CODEXBOT_INSTRUMENT_CACHE_DIRECTORY",
        "CODEXBOT_INSTRUMENT_MAX_AGE_SECONDS",
        "CODEXBOT_EQUITY_PRICE_PERCENTAGE",
        "CODEXBOT_YAHOO_MAX_MARKET_AGE_SECONDS",
        "CODEXBOT_YAHOO_MAX_LOCAL_AGE_SECONDS",
        "CODEXBOT_MAX_ORDER_AMOUNT",
        "CODEXBOT_MINIMUM_TRADE_FUNDS",
        "CODEXBOT_DAILY_LOSS_LIMIT",
        "CODEXBOT_TOTAL_EXPOSURE_LIMIT",
        "CODEXBOT_MAX_OPEN_POSITIONS",
        "CODEXBOT_MAX_DAILY_TRADES",
        "TELEGRAM_API_ID",
        "TELEGRAM_API_HASH",
        "TELEGRAM_PHONE_NUMBER",
        "TELEGRAM_SESSION_PATH",
        "DHAN_CLIENT_ID",
        "DHAN_PIN",
        "DHAN_TOTP_SECRET",
    }
)
