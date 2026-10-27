"""Atomic local cache for Dhan's public detailed instrument master."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import secrets
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Protocol
from urllib.request import Request, urlopen

from codexbot.instruments import DhanInstrumentResolver, Exchange, InstrumentMasterError

DHAN_DETAILED_MASTER_URL = "https://images.dhan.co/api-data/api-scrip-master-detailed.csv"
_DEFAULT_MAX_BYTES = 128 * 1024 * 1024
_POINTER_FILE = "current.json"
_LOCK_FILE = ".refresh.lock"
_MASTER_NAME = re.compile(r"master-([0-9a-f]{64})\.csv")


class InstrumentCacheError(RuntimeError):
    """Raised when the cached instrument master cannot be trusted."""


@dataclass(frozen=True, slots=True)
class DownloadEvidence:
    byte_count: int
    etag: str | None
    last_modified: str | None


@dataclass(frozen=True, slots=True)
class InstrumentSnapshot:
    path: Path
    sha256: str
    byte_count: int
    downloaded_at: datetime
    source_url: str
    etag: str | None
    last_modified: str | None


@dataclass(frozen=True, slots=True)
class LoadedInstrumentMaster:
    snapshot: InstrumentSnapshot
    resolver: DhanInstrumentResolver


class InstrumentDownloadTransport(Protocol):
    def download(
        self,
        url: str,
        destination: Path,
        *,
        maximum_bytes: int,
    ) -> DownloadEvidence: ...


class UrllibInstrumentDownloadTransport:
    """Stream the public Dhan CSV without loading it into memory."""

    def __init__(self, *, timeout_seconds: float = 30.0) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self._timeout_seconds = timeout_seconds

    def download(
        self,
        url: str,
        destination: Path,
        *,
        maximum_bytes: int,
    ) -> DownloadEvidence:
        request = Request(
            url,
            headers={"Accept": "text/csv", "User-Agent": "Codexbot/0.1"},
            method="GET",
        )
        try:
            with urlopen(request, timeout=self._timeout_seconds) as response:  # noqa: S310
                content_length = response.headers.get("Content-Length")
                if content_length is not None and int(content_length) > maximum_bytes:
                    raise InstrumentCacheError("instrument master exceeds maximum size")
                byte_count = 0
                with destination.open("xb") as output:
                    os.chmod(destination, 0o600)
                    while chunk := response.read(1024 * 1024):
                        byte_count += len(chunk)
                        if byte_count > maximum_bytes:
                            raise InstrumentCacheError("instrument master exceeds maximum size")
                        output.write(chunk)
                    output.flush()
                    os.fsync(output.fileno())
                return DownloadEvidence(
                    byte_count=byte_count,
                    etag=response.headers.get("ETag"),
                    last_modified=response.headers.get("Last-Modified"),
                )
        except InstrumentCacheError:
            raise
        except Exception as error:
            raise InstrumentCacheError("Dhan instrument-master download failed") from error


class DhanInstrumentMasterCache:
    """Activate only validated, checksummed Dhan instrument snapshots."""

    def __init__(
        self,
        cache_directory: str | Path,
        *,
        transport: InstrumentDownloadTransport | None = None,
        clock: Callable[[], datetime] | None = None,
        source_url: str = DHAN_DETAILED_MASTER_URL,
        maximum_bytes: int = _DEFAULT_MAX_BYTES,
    ) -> None:
        if maximum_bytes <= 0:
            raise ValueError("maximum_bytes must be positive")
        self._directory = Path(cache_directory)
        self._transport = transport or UrllibInstrumentDownloadTransport()
        self._clock = clock or (lambda: datetime.now(UTC))
        self._source_url = source_url
        self._maximum_bytes = maximum_bytes

    def refresh(self) -> InstrumentSnapshot:
        """Download, validate, and atomically activate a new snapshot."""

        self._prepare_directory()
        with self._locked(exclusive=True):
            temporary_path = self._directory / f".download-{secrets.token_hex(12)}.tmp"
            try:
                evidence = self._transport.download(
                    self._source_url,
                    temporary_path,
                    maximum_bytes=self._maximum_bytes,
                )
                actual_size = temporary_path.stat().st_size
                if evidence.byte_count != actual_size or actual_size == 0:
                    raise InstrumentCacheError("instrument-master byte count is invalid")

                digest = _sha256_file(temporary_path)
                try:
                    DhanInstrumentResolver.from_csv_file(temporary_path)
                except InstrumentMasterError as error:
                    raise InstrumentCacheError(
                        "downloaded instrument master failed validation"
                    ) from error
                final_name = f"master-{digest}.csv"
                final_path = self._directory / final_name
                if final_path.exists():
                    if _sha256_file(final_path) != digest:
                        raise InstrumentCacheError("existing snapshot checksum mismatch")
                    temporary_path.unlink()
                else:
                    os.replace(temporary_path, final_path)
                    os.chmod(final_path, 0o600)
                    _fsync_directory(self._directory)

                snapshot = InstrumentSnapshot(
                    path=final_path,
                    sha256=digest,
                    byte_count=actual_size,
                    downloaded_at=_aware_utc(self._clock()),
                    source_url=self._source_url,
                    etag=evidence.etag,
                    last_modified=evidence.last_modified,
                )
                self._activate(snapshot)
                return snapshot
            finally:
                temporary_path.unlink(missing_ok=True)

    def load(
        self,
        *,
        maximum_age: timedelta,
        now: datetime,
        enabled_exchanges: frozenset[Exchange] = frozenset({Exchange.NSE, Exchange.BSE}),
    ) -> LoadedInstrumentMaster:
        """Verify and load the active snapshot with an explicit age limit."""

        if maximum_age < timedelta(0):
            raise ValueError("maximum_age cannot be negative")
        self._prepare_directory()
        with self._locked(exclusive=False):
            snapshot = self._read_pointer()
            age = _aware_utc(now) - snapshot.downloaded_at
            if age < timedelta(0):
                raise InstrumentCacheError("instrument snapshot timestamp is in the future")
            if age > maximum_age:
                raise InstrumentCacheError("instrument snapshot is stale")
            if not snapshot.path.is_file():
                raise InstrumentCacheError("instrument snapshot file is missing")
            if snapshot.path.is_symlink():
                raise InstrumentCacheError("instrument snapshot cannot be a symlink")
            if snapshot.path.stat().st_size != snapshot.byte_count:
                raise InstrumentCacheError("instrument snapshot size mismatch")
            if _sha256_file(snapshot.path) != snapshot.sha256:
                raise InstrumentCacheError("instrument snapshot checksum mismatch")
            resolver = DhanInstrumentResolver.from_csv_file(
                snapshot.path,
                enabled_exchanges=enabled_exchanges,
            )
            return LoadedInstrumentMaster(snapshot=snapshot, resolver=resolver)

    def current_snapshot(self) -> InstrumentSnapshot:
        """Return verified pointer metadata without applying an age policy."""

        self._prepare_directory()
        with self._locked(exclusive=False):
            return self._read_pointer()

    def prune(self, *, keep: int = 2) -> tuple[Path, ...]:
        """Remove inactive validated-name snapshots, retaining newest versions."""

        if keep < 1:
            raise ValueError("keep must be at least one")
        self._prepare_directory()
        with self._locked(exclusive=True):
            active = self._read_pointer().path
            candidates = sorted(
                (
                    path
                    for path in self._directory.iterdir()
                    if _MASTER_NAME.fullmatch(path.name) and path.is_file()
                ),
                key=lambda path: path.stat().st_mtime_ns,
                reverse=True,
            )
            retained: set[Path] = {active}
            for path in candidates:
                if len(retained) >= keep:
                    break
                retained.add(path)
            removed: list[Path] = []
            for path in candidates:
                if path not in retained:
                    path.unlink()
                    removed.append(path)
            if removed:
                _fsync_directory(self._directory)
            return tuple(removed)

    def _prepare_directory(self) -> None:
        self._directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self._directory, 0o700)

    def _activate(self, snapshot: InstrumentSnapshot) -> None:
        payload = {
            "byte_count": snapshot.byte_count,
            "downloaded_at": snapshot.downloaded_at.isoformat(timespec="microseconds"),
            "etag": snapshot.etag,
            "file_name": snapshot.path.name,
            "last_modified": snapshot.last_modified,
            "sha256": snapshot.sha256,
            "source_url": snapshot.source_url,
            "version": 1,
        }
        temporary_pointer = self._directory / f".pointer-{secrets.token_hex(12)}.tmp"
        try:
            with temporary_pointer.open("x", encoding="utf-8") as pointer:
                os.chmod(temporary_pointer, 0o600)
                json.dump(payload, pointer, sort_keys=True, separators=(",", ":"))
                pointer.write("\n")
                pointer.flush()
                os.fsync(pointer.fileno())
            os.replace(temporary_pointer, self._directory / _POINTER_FILE)
            _fsync_directory(self._directory)
        finally:
            temporary_pointer.unlink(missing_ok=True)

    def _read_pointer(self) -> InstrumentSnapshot:
        pointer_path = self._directory / _POINTER_FILE
        try:
            payload = json.loads(pointer_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise InstrumentCacheError("instrument snapshot pointer is unavailable") from error
        if not isinstance(payload, dict) or payload.get("version") != 1:
            raise InstrumentCacheError("instrument snapshot pointer is invalid")

        file_name = payload.get("file_name")
        sha256 = payload.get("sha256")
        if not isinstance(file_name, str) or not isinstance(sha256, str):
            raise InstrumentCacheError("instrument snapshot identity is invalid")
        name_match = _MASTER_NAME.fullmatch(file_name)
        if name_match is None or name_match.group(1) != sha256:
            raise InstrumentCacheError("instrument snapshot file name is invalid")

        try:
            byte_count = int(payload["byte_count"])
            downloaded_at = _aware_utc(datetime.fromisoformat(payload["downloaded_at"]))
            source_url = str(payload["source_url"])
        except (KeyError, TypeError, ValueError) as error:
            raise InstrumentCacheError("instrument snapshot metadata is invalid") from error
        if byte_count <= 0 or source_url != self._source_url:
            raise InstrumentCacheError("instrument snapshot metadata is invalid")

        return InstrumentSnapshot(
            path=self._directory / file_name,
            sha256=sha256,
            byte_count=byte_count,
            downloaded_at=downloaded_at,
            source_url=source_url,
            etag=_optional_string(payload.get("etag")),
            last_modified=_optional_string(payload.get("last_modified")),
        )

    @contextmanager
    def _locked(self, *, exclusive: bool) -> Iterator[None]:
        lock_path = self._directory / _LOCK_FILE
        with lock_path.open("a+b") as lock_file:
            os.chmod(lock_path, 0o600)
            operation = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
            fcntl.flock(lock_file.fileno(), operation)
            try:
                yield
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime must be timezone-aware")
    return value.astimezone(UTC)


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
