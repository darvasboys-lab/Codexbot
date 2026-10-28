import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from codexbot import (
    NSE_TRADING_HOLIDAY_URL,
    CalendarCacheError,
    NSECalendarCache,
    NSECalendarSegment,
    calendar_cache_health,
)

NOW = datetime(2026, 10, 28, 3, 30, tzinfo=UTC)


def payload() -> object:
    return {
        "CM": [
            {
                "tradingDate": "20-Oct-2026",
                "weekDay": "Tuesday",
                "description": "Dussehra",
            },
            {
                "tradingDate": "25-Dec-2026",
                "weekDay": "Friday",
                "description": "Christmas",
            },
        ],
        "FO": [
            {
                "tradingDate": "20-Oct-2026",
                "weekDay": "Tuesday",
                "description": "Dussehra",
            }
        ],
    }


class StubTransport:
    def __init__(self, response: object) -> None:
        self.response = response
        self.calls: list[str] = []

    def get_json(self, url: str, *, timeout_seconds: float) -> object:
        assert timeout_seconds == 5.0
        self.calls.append(url)
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def test_refresh_validates_and_atomically_persists_owner_only_cache(tmp_path: Path) -> None:
    cache_path = tmp_path / "calendar" / "nse.json"
    transport = StubTransport(payload())
    cache = NSECalendarCache(cache_path, transport=transport, clock=lambda: NOW)

    refreshed = cache.refresh()
    loaded = cache.load(maximum_age=timedelta(days=1))

    assert loaded == refreshed
    assert refreshed.year == 2026
    assert refreshed.market_open(date(2026, 10, 28), NSECalendarSegment.CASH) is True
    assert refreshed.market_open(date(2026, 10, 20), NSECalendarSegment.CASH) is False
    assert refreshed.market_open(date(2026, 10, 25), NSECalendarSegment.FNO) is False
    assert cache_path.stat().st_mode & 0o077 == 0
    assert transport.calls == [NSE_TRADING_HOLIDAY_URL]


def test_refresh_failure_preserves_last_known_good_cache(tmp_path: Path) -> None:
    cache_path = tmp_path / "nse.json"
    good = NSECalendarCache(cache_path, transport=StubTransport(payload()), clock=lambda: NOW)
    good.refresh()
    before = cache_path.read_bytes()
    failing = NSECalendarCache(
        cache_path,
        transport=StubTransport(RuntimeError("upstream unavailable")),
        clock=lambda: NOW + timedelta(minutes=1),
    )

    with pytest.raises(CalendarCacheError, match="DOWNLOAD_FAILED"):
        failing.refresh()

    assert cache_path.read_bytes() == before


def test_load_rejects_stale_corrupt_or_permissive_cache(tmp_path: Path) -> None:
    cache_path = tmp_path / "nse.json"
    NSECalendarCache(cache_path, transport=StubTransport(payload()), clock=lambda: NOW).refresh()

    stale = NSECalendarCache(cache_path, clock=lambda: NOW + timedelta(days=2))
    with pytest.raises(CalendarCacheError, match="STALE"):
        stale.load(maximum_age=timedelta(days=1))

    cache_path.chmod(0o644)
    with pytest.raises(CalendarCacheError, match="UNSAFE"):
        NSECalendarCache(cache_path, clock=lambda: NOW).load(maximum_age=timedelta(days=1))
    cache_path.chmod(0o600)
    cache_path.write_text("not-json", encoding="utf-8")
    with pytest.raises(CalendarCacheError, match="CACHE_INVALID"):
        NSECalendarCache(cache_path, clock=lambda: NOW).load(maximum_age=timedelta(days=1))


@pytest.mark.parametrize(
    "bad_payload",
    [
        {},
        {"CM": [], "FO": []},
        {"CM": [{"tradingDate": "bad", "description": "x"}], "FO": []},
        {
            "CM": [{"tradingDate": "20-Oct-2026", "description": "x"}],
            "FO": [{"tradingDate": "01-Jan-2027", "description": "x"}],
        },
    ],
)
def test_refresh_fails_closed_on_invalid_official_shape(
    tmp_path: Path, bad_payload: object
) -> None:
    cache = NSECalendarCache(
        tmp_path / "nse.json", transport=StubTransport(bad_payload), clock=lambda: NOW
    )

    with pytest.raises(CalendarCacheError):
        cache.refresh()


def test_cache_source_and_year_are_revalidated_on_load(tmp_path: Path) -> None:
    path = tmp_path / "nse.json"
    path.write_text(
        json.dumps(
            {
                "fetched_at": NOW.isoformat(),
                "source_url": "https://example.invalid",
                "year": 2026,
                "segments": {"NSE_CM": [], "NSE_FO": []},
            }
        ),
        encoding="utf-8",
    )
    path.chmod(0o600)

    with pytest.raises(CalendarCacheError, match="SOURCE_INVALID"):
        NSECalendarCache(path, clock=lambda: NOW).load(maximum_age=timedelta(days=1))


def test_calendar_health_returns_only_fixed_cache_error_code(tmp_path: Path) -> None:
    path = tmp_path / "nse.json"
    NSECalendarCache(path, transport=StubTransport(payload()), clock=lambda: NOW).refresh()

    healthy = calendar_cache_health(
        NSECalendarCache(path, clock=lambda: NOW), maximum_age=timedelta(days=1)
    )
    stale = calendar_cache_health(
        NSECalendarCache(path, clock=lambda: NOW + timedelta(days=2)),
        maximum_age=timedelta(days=1),
    )

    assert healthy == (True, None)
    assert stale == (False, "NSE_CALENDAR_CACHE_STALE")
