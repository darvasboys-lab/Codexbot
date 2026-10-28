"""Telethon intake for one protected Telegram user session.

Only ``NewMessage`` events are registered. Edits and deletions are deliberately
ignored after first processing. This adapter contains no broker capability.
"""

from __future__ import annotations

import asyncio
import os
import stat
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from telethon import TelegramClient, events, utils  # type: ignore[import-untyped]

from codexbot.processing import ProcessingResult, SignalProcessor, TelegramEnvelope
from codexbot.reporting import format_listener_error, format_processing_result
from codexbot.settings import BotSettings, TelegramCredentials


class TelegramListenerError(RuntimeError):
    """Raised when listener or session state is unsafe or unavailable."""


class ResultHandler(Protocol):
    def __call__(self, result: ProcessingResult) -> Awaitable[None]: ...


class ErrorHandler(Protocol):
    def __call__(self, error_code: str) -> Awaitable[None]: ...


@dataclass(slots=True)
class TelegramHealth:
    connected: bool = False
    authorized: bool = False
    last_received_at: datetime | None = None
    last_processed_at: datetime | None = None
    last_error_code: str | None = None


class TelethonListener:
    """Receive configured chats and hand messages to the durable processor."""

    def __init__(
        self,
        *,
        settings: BotSettings,
        credentials: TelegramCredentials,
        processor: SignalProcessor,
        result_handler: ResultHandler | None = None,
        error_handler: ErrorHandler | None = None,
        clock: Callable[[], datetime] | None = None,
        client_factory: Callable[..., TelegramClient] = TelegramClient,
    ) -> None:
        self._settings = settings
        self._credentials = credentials
        self._processor = processor
        self._result_handler = result_handler
        self._error_handler = error_handler or _ignore_error
        self._clock = clock or (lambda: datetime.now(UTC))
        self._client_factory = client_factory
        self._client: TelegramClient | None = None
        self.health = TelegramHealth()

    async def run(self) -> None:
        """Connect an already-authorized session and run until disconnected."""

        validate_telegram_session(self._settings.telegram_session_path)
        previous_umask = os.umask(0o077)
        try:
            client = self._client_factory(
                str(self._settings.telegram_session_path),
                self._credentials.api_id,
                self._credentials.api_hash.reveal(),
                auto_reconnect=True,
                connection_retries=5,
                retry_delay=2,
                request_retries=3,
                raise_last_call_error=True,
            )
            self._client = client

            @client.on(  # type: ignore[untyped-decorator]
                events.NewMessage(chats=list(self._settings.allowed_group_ids))
            )
            async def handle_new_message(event: Any) -> None:
                await self._handle_event(event)

            await client.connect()
            self.health.connected = bool(client.is_connected())
            self.health.authorized = bool(await client.is_user_authorized())
            harden_telegram_session(self._settings.telegram_session_path)
            if not self.health.authorized:
                raise TelegramListenerError(
                    "Telegram session is not authorized; run interactive setup separately"
                )
            await client.run_until_disconnected()
        except TelegramListenerError:
            self.health.last_error_code = "TelegramListenerError"
            raise
        except Exception as error:
            self.health.last_error_code = type(error).__name__
            raise TelegramListenerError("Telegram listener stopped unexpectedly") from error
        finally:
            os.umask(previous_umask)
            client = self._client
            if client is not None and client.is_connected():
                await client.disconnect()
            self.health.connected = False

    async def stop(self) -> None:
        client = self._client
        if client is not None and client.is_connected():
            await client.disconnect()

    async def _handle_event(self, event: Any) -> None:
        self.health.last_received_at = _aware_utc(self._clock())
        try:
            envelope = telegram_envelope_from_event(event)
            result = await asyncio.to_thread(self._processor.process, envelope)
            self.health.last_processed_at = _aware_utc(self._clock())
            self.health.last_error_code = None
            if self._result_handler is not None:
                await self._result_handler(result)
            else:
                await self._send_result_to_log(result)
        except Exception as error:
            error_code = type(error).__name__
            self.health.last_error_code = error_code
            if self._error_handler is not _ignore_error:
                await self._error_handler(error_code)
            else:
                try:
                    await self._send_log_text(
                        format_listener_error(
                            execution_mode=self._settings.mode.value,
                            error_code=error_code,
                        )
                    )
                except Exception:
                    pass

    async def _send_result_to_log(self, result: ProcessingResult) -> None:
        await self._send_log_text(format_processing_result(result))

    async def _send_log_text(self, text: str) -> None:
        client = self._client
        if client is None or not client.is_connected():
            raise TelegramListenerError("Telegram log client is unavailable")
        await client.send_message(
            self._settings.log_group_id,
            text,
            parse_mode=None,
            link_preview=False,
        )


def telegram_envelope_from_event(event: Any) -> TelegramEnvelope:
    """Extract only trusted Telegram metadata and message text from an event."""

    message = event.message
    forwarded_header = getattr(message, "fwd_from", None)
    forwarded_source_id = _forwarded_source_id(forwarded_header)
    return TelegramEnvelope(
        source_group_id=int(event.chat_id),
        source_sender_or_channel_id=(int(event.sender_id) if event.sender_id is not None else None),
        telegram_message_id=int(message.id),
        sent_at=message.date,
        text=event.raw_text or None,
        is_forwarded=forwarded_header is not None,
        forwarded_from_source_id=forwarded_source_id,
    )


def validate_telegram_session(session_path: str | Path) -> None:
    """Require an existing owner-only session and protected parent directory."""

    path = Path(session_path)
    _validate_private_directory(path.parent)
    _validate_private_file(path, description="Telegram session")


def harden_telegram_session(session_path: str | Path) -> None:
    """Reapply owner-only permissions to Telethon SQLite sidecar files."""

    path = Path(session_path)
    _validate_private_directory(path.parent)
    for candidate in (path, Path(f"{path}-journal"), Path(f"{path}-wal"), Path(f"{path}-shm")):
        if candidate.exists():
            if candidate.is_symlink() or not candidate.is_file():
                raise TelegramListenerError("Telegram session state must be regular files")
            os.chmod(candidate, 0o600)
            _validate_private_file(candidate, description="Telegram session state")


def _forwarded_source_id(forwarded_header: object | None) -> int | None:
    if forwarded_header is None:
        return None
    peer = getattr(forwarded_header, "from_id", None) or getattr(
        forwarded_header, "saved_from_peer", None
    )
    if peer is None:
        return None
    try:
        return int(utils.get_peer_id(peer))
    except (TypeError, ValueError):
        return None


def _validate_private_directory(path: Path) -> None:
    if path.is_symlink():
        raise TelegramListenerError("Telegram session directory cannot be a symlink")
    try:
        metadata = path.stat()
    except OSError as error:
        raise TelegramListenerError("Telegram session directory is unavailable") from error
    if not stat.S_ISDIR(metadata.st_mode):
        raise TelegramListenerError("Telegram session parent must be a directory")
    if metadata.st_uid != os.geteuid() or stat.S_IMODE(metadata.st_mode) & 0o077:
        raise TelegramListenerError("Telegram session directory must be owner-only")


def _validate_private_file(path: Path, *, description: str) -> None:
    if path.is_symlink():
        raise TelegramListenerError(f"{description} cannot be a symlink")
    try:
        metadata = path.stat()
    except OSError as error:
        raise TelegramListenerError(f"{description} file is unavailable") from error
    if not stat.S_ISREG(metadata.st_mode):
        raise TelegramListenerError(f"{description} must be a regular file")
    if metadata.st_uid != os.geteuid() or stat.S_IMODE(metadata.st_mode) & 0o077:
        raise TelegramListenerError(f"{description} file must be owner-only")


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise TelegramListenerError("Telegram listener clock must be timezone-aware")
    return value.astimezone(UTC)


async def _ignore_error(error_code: str) -> None:
    del error_code
