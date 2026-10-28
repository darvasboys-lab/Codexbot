"""Bounded, atomic cache for NSE's official trading-holiday endpoint."""

from __future__ import annotations

import json
import os
import stat
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Protocol, cast
from urllib.request import Request, urlopen

NSE_TRADING_HOLIDAY_URL = "https://www.nseindia.com/api/holiday-master?type=trading"
_MAX_RESPONSE_BYTES = 1_048_576
_FUTURE_TOLERANCE = timedelta(seconds=2)


class CalendarCacheError(RuntimeError):
    """A fixed failure safe to expose without response content."""


class NSECalendarSegment(StrEnum):
    CASH = "NSE_CM"
    FNO = "NSE_FO"


@dataclass(frozen=True, slots=True)
class NSECalendarSnapshot:
    fetched_at: datetime
    source_url: str
    year: int
    cash_holidays: frozenset[date]
    fno_holidays: frozenset[date]

    def market_open(self, day: date, segment: NSECalendarSegment) -> bool:
        if day.year != self.year:
            raise CalendarCacheError("NSE_CALENDAR_YEAR_MISMATCH")
        if day.weekday() >= 5:
            return False
        holidays = self.cash_holidays if segment is NSECalendarSegment.CASH else self.fno_holidays
        return day not in holidays


class CalendarTransport(Protocol):
    def get_json(self, url: str, *, timeout_seconds: float) -> object: ...


class UrllibCalendarTransport:
    def get_json(self, url: str, *, timeout_seconds: float) -> object:
        request = Request(
            url,
            headers={
                "Accept": "application/json",
                "Referer": "https://www.nseindia.com/",
                "User-Agent": "Codexbot/0.1",
            },
            method="GET",
        )
        with urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310
            body = response.read(_MAX_RESPONSE_BYTES + 1)
        if len(body) > _MAX_RESPONSE_BYTES:
            raise CalendarCacheError("NSE_CALENDAR_RESPONSE_TOO_LARGE")
        try:
            return cast(object, json.loads(body))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise CalendarCacheError("NSE_CALENDAR_INVALID_JSON") from error


class NSECalendarCache:
    def __init__(
        self,
        cache_path: str | Path,
        *,
        transport: CalendarTransport | None = None,
        clock: Callable[[], datetime] | None = None,
        timeout_seconds: float = 5.0,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self._path = Path(cache_path)
        self._transport = transport or UrllibCalendarTransport()
        self._clock = clock or (lambda: datetime.now(UTC))
        self._timeout_seconds = timeout_seconds

    @property
    def cache_path(self) -> Path:
        return self._path

    def refresh(self) -> NSECalendarSnapshot:
        """Validate the complete response before atomically replacing the cache."""

        fetched_at = _aware_utc(self._clock())
        try:
            payload = self._transport.get_json(
                NSE_TRADING_HOLIDAY_URL, timeout_seconds=self._timeout_seconds
            )
            snapshot = _snapshot_from_nse_payload(payload, fetched_at=fetched_at)
        except CalendarCacheError:
            raise
        except Exception as error:
            raise CalendarCacheError("NSE_CALENDAR_DOWNLOAD_FAILED") from error
        self._write(snapshot)
        return snapshot

    def load(self, *, maximum_age: timedelta) -> NSECalendarSnapshot:
        """Load only an owner-protected, current, validated cache file."""

        if maximum_age <= timedelta(0):
            raise ValueError("maximum_age must be positive")
        _validate_private_cache_file(self._path)
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
            snapshot = _snapshot_from_cache_payload(payload)
        except CalendarCacheError:
            raise
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise CalendarCacheError("NSE_CALENDAR_CACHE_INVALID") from error
        age = _aware_utc(self._clock()) - snapshot.fetched_at
        if not -_FUTURE_TOLERANCE <= age <= maximum_age:
            raise CalendarCacheError("NSE_CALENDAR_CACHE_STALE")
        return snapshot

    def _write(self, snapshot: NSECalendarSnapshot) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self._path.parent.is_symlink():
            raise CalendarCacheError("NSE_CALENDAR_CACHE_DIRECTORY_UNSAFE")
        try:
            self._path.parent.chmod(0o700)
            payload = _cache_payload(snapshot)
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self._path.parent,
                prefix=f".{self._path.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                temporary_path = Path(temporary.name)
                os.chmod(temporary_path, 0o600)
                json.dump(payload, temporary, sort_keys=True, separators=(",", ":"))
                temporary.flush()
                os.fsync(temporary.fileno())
            os.replace(temporary_path, self._path)
            os.chmod(self._path, 0o600)
        except OSError as error:
            raise CalendarCacheError("NSE_CALENDAR_CACHE_WRITE_FAILED") from error
        finally:
            if "temporary_path" in locals() and temporary_path.exists():
                temporary_path.unlink()


def _snapshot_from_nse_payload(payload: object, *, fetched_at: datetime) -> NSECalendarSnapshot:
    root = _mapping(payload)
    cash = _holiday_dates(root.get("CM"), field="CM")
    fno = _holiday_dates(root.get("FO"), field="FO")
    years = {item.year for item in cash | fno}
    if len(years) != 1:
        raise CalendarCacheError("NSE_CALENDAR_YEAR_INVALID")
    year = next(iter(years))
    return NSECalendarSnapshot(
        fetched_at=fetched_at,
        source_url=NSE_TRADING_HOLIDAY_URL,
        year=year,
        cash_holidays=frozenset(cash),
        fno_holidays=frozenset(fno),
    )


def _snapshot_from_cache_payload(payload: object) -> NSECalendarSnapshot:
    root = _mapping(payload)
    if root.get("source_url") != NSE_TRADING_HOLIDAY_URL:
        raise CalendarCacheError("NSE_CALENDAR_CACHE_SOURCE_INVALID")
    fetched_raw = root.get("fetched_at")
    year_raw = root.get("year")
    segments = root.get("segments")
    if not isinstance(fetched_raw, str):
        raise CalendarCacheError("NSE_CALENDAR_CACHE_INVALID")
    try:
        fetched_at = _aware_utc(datetime.fromisoformat(fetched_raw))
    except ValueError as error:
        raise CalendarCacheError("NSE_CALENDAR_CACHE_INVALID") from error
    if isinstance(year_raw, bool) or not isinstance(year_raw, int):
        raise CalendarCacheError("NSE_CALENDAR_CACHE_INVALID")
    segment_map = _mapping(segments)
    cash = _iso_dates(segment_map.get(NSECalendarSegment.CASH.value), year=year_raw)
    fno = _iso_dates(segment_map.get(NSECalendarSegment.FNO.value), year=year_raw)
    return NSECalendarSnapshot(
        fetched_at=fetched_at,
        source_url=NSE_TRADING_HOLIDAY_URL,
        year=year_raw,
        cash_holidays=frozenset(cash),
        fno_holidays=frozenset(fno),
    )


def _cache_payload(snapshot: NSECalendarSnapshot) -> dict[str, object]:
    return {
        "fetched_at": snapshot.fetched_at.isoformat(),
        "source_url": snapshot.source_url,
        "year": snapshot.year,
        "segments": {
            NSECalendarSegment.CASH.value: sorted(
                item.isoformat() for item in snapshot.cash_holidays
            ),
            NSECalendarSegment.FNO.value: sorted(
                item.isoformat() for item in snapshot.fno_holidays
            ),
        },
    }


def _mapping(value: object) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise CalendarCacheError("NSE_CALENDAR_SHAPE_INVALID")
    return cast(Mapping[str, object], value)


def _holiday_dates(value: object, *, field: str) -> set[date]:
    if not isinstance(value, list) or not value:
        raise CalendarCacheError(f"NSE_CALENDAR_{field}_INVALID")
    result: set[date] = set()
    for raw_row in value:
        row = _mapping(raw_row)
        raw_date = row.get("tradingDate")
        description = row.get("description")
        if not isinstance(raw_date, str) or not isinstance(description, str) or not description:
            raise CalendarCacheError(f"NSE_CALENDAR_{field}_INVALID")
        result.add(_nse_date(raw_date))
    return result


def _nse_date(value: str) -> date:
    parts = value.split("-")
    months = {
        "Jan": 1,
        "Feb": 2,
        "Mar": 3,
        "Apr": 4,
        "May": 5,
        "Jun": 6,
        "Jul": 7,
        "Aug": 8,
        "Sep": 9,
        "Oct": 10,
        "Nov": 11,
        "Dec": 12,
    }
    try:
        if len(parts) != 3:
            raise ValueError
        return date(int(parts[2]), months[parts[1]], int(parts[0]))
    except (KeyError, ValueError) as error:
        raise CalendarCacheError("NSE_CALENDAR_DATE_INVALID") from error


def _iso_dates(value: object, *, year: int) -> set[date]:
    if not isinstance(value, list):
        raise CalendarCacheError("NSE_CALENDAR_CACHE_INVALID")
    result: set[date] = set()
    for raw in value:
        if not isinstance(raw, str):
            raise CalendarCacheError("NSE_CALENDAR_CACHE_INVALID")
        try:
            parsed = date.fromisoformat(raw)
        except ValueError as error:
            raise CalendarCacheError("NSE_CALENDAR_CACHE_INVALID") from error
        if parsed.year != year:
            raise CalendarCacheError("NSE_CALENDAR_YEAR_INVALID")
        result.add(parsed)
    return result


def _validate_private_cache_file(path: Path) -> None:
    if path.is_symlink():
        raise CalendarCacheError("NSE_CALENDAR_CACHE_UNSAFE")
    try:
        metadata = path.stat()
    except OSError as error:
        raise CalendarCacheError("NSE_CALENDAR_CACHE_MISSING") from error
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.geteuid():
        raise CalendarCacheError("NSE_CALENDAR_CACHE_UNSAFE")
    if stat.S_IMODE(metadata.st_mode) & 0o077:
        raise CalendarCacheError("NSE_CALENDAR_CACHE_UNSAFE")


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("calendar time must be timezone-aware")
    return value.astimezone(UTC)
