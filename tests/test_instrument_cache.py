import os
import stat
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from codexbot import (
    DhanInstrumentMasterCache,
    DownloadEvidence,
    InstrumentCacheError,
    TelegramMessageParser,
)

NOW = datetime(2026, 10, 27, 3, 0, tzinfo=UTC)
HEADER = (
    "EXCH_ID,SEGMENT,SECURITY_ID,ISIN,INSTRUMENT,UNDERLYING_SECURITY_ID,"
    "UNDERLYING_SYMBOL,DISPLAY_NAME,SERIES,LOT_SIZE,SM_EXPIRY_DATE,STRIKE_PRICE,"
    "OPTION_TYPE,TICK_SIZE,EXPIRY_FLAG,BUY_SELL_INDICATOR,MTF_LEVERAGE\n"
)


def valid_master(security_id: str = "62508") -> bytes:
    row = (
        f"NSE,D,{security_id},NA,OPTSTK,21174,CDSL,CDSL 27 OCT 1400 CALL,NA,"
        "475.0,2026-10-27,1400.00000,CE,5.0000,M,A,0\n"
    )
    return (HEADER + row).encode()


class MutableClock:
    def __init__(self, current: datetime) -> None:
        self.current = current

    def __call__(self) -> datetime:
        return self.current


class FakeTransport:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload
        self.urls: list[str] = []

    def download(
        self,
        url: str,
        destination: Path,
        *,
        maximum_bytes: int,
    ) -> DownloadEvidence:
        self.urls.append(url)
        if len(self.payload) > maximum_bytes:
            raise InstrumentCacheError("instrument master exceeds maximum size")
        destination.write_bytes(self.payload)
        return DownloadEvidence(
            byte_count=len(self.payload),
            etag='"fixture-etag"',
            last_modified="Tue, 27 Oct 2026 02:50:07 GMT",
        )


def test_refresh_validates_and_atomically_loads_snapshot(tmp_path: Path) -> None:
    transport = FakeTransport(valid_master())
    cache = DhanInstrumentMasterCache(
        tmp_path / "instruments", transport=transport, clock=lambda: NOW
    )

    snapshot = cache.refresh()
    loaded = cache.load(maximum_age=timedelta(hours=1), now=NOW)
    facts = loaded.resolver.resolve(
        TelegramMessageParser().parse("CDSL 1400CE OCT @33-35"),
        as_of=NOW.date(),
    )

    assert snapshot == loaded.snapshot
    assert snapshot.path.name == f"master-{snapshot.sha256}.csv"
    assert snapshot.byte_count == len(valid_master())
    assert snapshot.etag == '"fixture-etag"'
    assert facts.security_id == "62508"
    assert stat.S_IMODE(snapshot.path.stat().st_mode) == 0o600
    assert stat.S_IMODE((tmp_path / "instruments").stat().st_mode) == 0o700
    assert len(transport.urls) == 1


def test_invalid_refresh_preserves_last_known_good_snapshot(tmp_path: Path) -> None:
    transport = FakeTransport(valid_master())
    clock = MutableClock(NOW)
    cache = DhanInstrumentMasterCache(tmp_path / "instruments", transport=transport, clock=clock)
    first = cache.refresh()
    transport.payload = b"not,a,valid,master\n"
    clock.current = NOW + timedelta(hours=1)

    with pytest.raises(InstrumentCacheError, match="failed validation"):
        cache.refresh()

    assert cache.current_snapshot() == first
    loaded = cache.load(maximum_age=timedelta(hours=2), now=clock.current)
    assert loaded.snapshot == first


def test_load_rejects_stale_or_future_snapshot_timestamp(tmp_path: Path) -> None:
    clock = MutableClock(NOW)
    cache = DhanInstrumentMasterCache(
        tmp_path / "instruments",
        transport=FakeTransport(valid_master()),
        clock=clock,
    )
    cache.refresh()

    with pytest.raises(InstrumentCacheError, match="stale"):
        cache.load(maximum_age=timedelta(minutes=59), now=NOW + timedelta(hours=1))
    with pytest.raises(InstrumentCacheError, match="future"):
        cache.load(maximum_age=timedelta(hours=1), now=NOW - timedelta(microseconds=1))


def test_load_rejects_snapshot_corruption(tmp_path: Path) -> None:
    cache = DhanInstrumentMasterCache(
        tmp_path / "instruments",
        transport=FakeTransport(valid_master()),
        clock=lambda: NOW,
    )
    snapshot = cache.refresh()
    with snapshot.path.open("ab") as output:
        output.write(b"corrupt")

    with pytest.raises(InstrumentCacheError, match="size mismatch"):
        cache.load(maximum_age=timedelta(hours=1), now=NOW)


def test_refresh_enforces_download_size_limit(tmp_path: Path) -> None:
    cache = DhanInstrumentMasterCache(
        tmp_path / "instruments",
        transport=FakeTransport(valid_master()),
        clock=lambda: NOW,
        maximum_bytes=10,
    )

    with pytest.raises(InstrumentCacheError, match="maximum size"):
        cache.refresh()
    with pytest.raises(InstrumentCacheError, match="pointer is unavailable"):
        cache.current_snapshot()


def test_prune_keeps_active_and_previous_snapshot(tmp_path: Path) -> None:
    transport = FakeTransport(valid_master("62508"))
    cache = DhanInstrumentMasterCache(
        tmp_path / "instruments", transport=transport, clock=lambda: NOW
    )
    first = cache.refresh()
    transport.payload = valid_master("62509")
    second = cache.refresh()
    transport.payload = valid_master("62510")
    active = cache.refresh()
    os.utime(first.path, ns=(1, 1))
    os.utime(second.path, ns=(2, 2))
    os.utime(active.path, ns=(3, 3))

    removed = cache.prune(keep=2)

    assert removed == (first.path,)
    assert not first.path.exists()
    assert second.path.exists()
    assert active.path.exists()
    assert cache.current_snapshot() == active
