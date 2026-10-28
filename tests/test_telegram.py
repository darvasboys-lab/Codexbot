import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from telethon import events, utils  # type: ignore[import-untyped]
from telethon.tl.types import PeerChannel  # type: ignore[import-untyped]

from codexbot import (
    Action,
    BotSettings,
    CheckDisposition,
    CheckReport,
    ExecutionMode,
    OperatorFeedbackService,
    ParsedMessage,
    ParseReason,
    ProcessingResult,
    SecretValue,
    SignalProcessor,
    SignalReceipt,
    SQLiteJournal,
    TelegramCredentials,
    TelegramListenerError,
    TelethonListener,
    harden_telegram_session,
    telegram_envelope_from_event,
    validate_telegram_session,
)

NOW = datetime(2026, 10, 27, 4, 0, tzinfo=UTC)


def event(
    *,
    forwarded_peer: object | None = None,
    sender_id: int | None = 2001,
    chat_id: int = -1001,
    message_id: int = 42,
    text: str = "CDSL 1400CE OCT @33-35",
) -> Any:
    forward = (
        SimpleNamespace(from_id=forwarded_peer, saved_from_peer=None)
        if forwarded_peer is not None
        else None
    )
    return SimpleNamespace(
        chat_id=chat_id,
        sender_id=sender_id,
        raw_text=text,
        message=SimpleNamespace(id=message_id, date=NOW, fwd_from=forward),
    )


def settings(session_path: Path) -> BotSettings:
    return BotSettings(
        mode=ExecutionMode.TEST,
        equity_active=False,
        fno_active=True,
        allowed_group_ids=frozenset({-1001}),
        authorized_source_ids=frozenset({2001}),
        authorized_operator_ids=frozenset({3001}),
        log_group_id=-9001,
        database_path=session_path.parent / "codexbot.sqlite3",
        instrument_cache_directory=session_path.parent / "instruments",
        instrument_maximum_age=timedelta(hours=1),
        telegram_session_path=session_path,
    )


class FakeClient:
    def __init__(self, *, authorized: bool) -> None:
        self.authorized = authorized
        self.connected = False
        self.event_builders: list[object] = []
        self.sent_messages: list[tuple[int, str, object, bool]] = []

    def on(self, event_builder: object) -> Any:
        self.event_builders.append(event_builder)

        def decorator(function: Any) -> Any:
            return function

        return decorator

    async def connect(self) -> None:
        self.connected = True

    def is_connected(self) -> bool:
        return self.connected

    async def is_user_authorized(self) -> bool:
        return self.authorized

    async def run_until_disconnected(self) -> None:
        return None

    async def disconnect(self) -> None:
        self.connected = False

    async def send_message(
        self,
        entity: int,
        message: str,
        *,
        parse_mode: object,
        link_preview: bool,
    ) -> None:
        self.sent_messages.append((entity, message, parse_mode, link_preview))


class StubProcessor:
    def process(self, envelope: object) -> ProcessingResult:
        del envelope
        return ProcessingResult(
            receipt=SignalReceipt(
                id=1,
                source_group_id=-1001,
                telegram_message_id=42,
                sent_at=NOW,
                first_durable_received_at=NOW,
            ),
            parsed=ParsedMessage(
                action=Action.BUY,
                segment=None,
                reason=ParseReason.UNSUPPORTED_PATTERN,
                symbol="CDSL",
            ),
            instrument=None,
            report=CheckReport(
                disposition=CheckDisposition.REJECTED,
                reasons=(),
                pending_gates=(),
                execution_mode=ExecutionMode.TEST,
            ),
            duplicate_claim=None,
        )


class FailingProcessor:
    def process(self, envelope: object) -> ProcessingResult:
        del envelope
        raise RuntimeError("sensitive upstream detail")


def private_session(tmp_path: Path) -> Path:
    tmp_path.chmod(0o700)
    path = tmp_path / "udit.session"
    path.write_bytes(b"session fixture")
    path.chmod(0o600)
    return path


def test_event_conversion_preserves_source_and_forward_origin() -> None:
    origin = PeerChannel(channel_id=12345)

    envelope = telegram_envelope_from_event(event(forwarded_peer=origin))

    assert envelope.source_group_id == -1001
    assert envelope.source_sender_or_channel_id == 2001
    assert envelope.telegram_message_id == 42
    assert envelope.sent_at == NOW
    assert envelope.is_forwarded is True
    assert envelope.forwarded_from_source_id == utils.get_peer_id(origin)


def test_hidden_forward_origin_remains_unverified() -> None:
    candidate = event()
    candidate.message.fwd_from = SimpleNamespace(from_id=None, saved_from_peer=None)

    envelope = telegram_envelope_from_event(candidate)

    assert envelope.is_forwarded is True
    assert envelope.forwarded_from_source_id is None


def test_missing_sender_identity_remains_missing() -> None:
    envelope = telegram_envelope_from_event(event(sender_id=None))

    assert envelope.source_sender_or_channel_id is None


def test_session_requires_owner_only_regular_files(tmp_path: Path) -> None:
    session_path = private_session(tmp_path)

    validate_telegram_session(session_path)
    session_path.chmod(0o640)
    with pytest.raises(TelegramListenerError, match="owner-only"):
        validate_telegram_session(session_path)


def test_session_rejects_symlink(tmp_path: Path) -> None:
    session_path = private_session(tmp_path)
    link = tmp_path / "link.session"
    link.symlink_to(session_path)

    with pytest.raises(TelegramListenerError, match="symlink"):
        validate_telegram_session(link)


def test_session_hardening_applies_to_sqlite_sidecars(tmp_path: Path) -> None:
    session_path = private_session(tmp_path)
    journal_path = Path(f"{session_path}-journal")
    journal_path.write_bytes(b"journal")
    journal_path.chmod(0o666)

    harden_telegram_session(session_path)

    assert session_path.stat().st_mode & 0o077 == 0
    assert journal_path.stat().st_mode & 0o077 == 0


def test_listener_refuses_unauthorized_session_without_interactive_login(tmp_path: Path) -> None:
    session_path = private_session(tmp_path)
    fake_client = FakeClient(authorized=False)
    listener = TelethonListener(
        settings=settings(session_path),
        credentials=TelegramCredentials(api_id=123, api_hash=SecretValue("secret")),
        processor=cast(SignalProcessor, object()),
        client_factory=cast(Any, lambda *args, **kwargs: fake_client),
    )

    with pytest.raises(TelegramListenerError, match="not authorized"):
        asyncio.run(listener.run())

    assert listener.health.authorized is False
    assert listener.health.connected is False
    assert fake_client.connected is False
    assert len(fake_client.event_builders) == 1
    assert isinstance(fake_client.event_builders[0], events.NewMessage)


def test_listener_runs_authorized_session_and_disconnects_cleanly(tmp_path: Path) -> None:
    session_path = private_session(tmp_path)
    fake_client = FakeClient(authorized=True)
    listener = TelethonListener(
        settings=settings(session_path),
        credentials=TelegramCredentials(api_id=123, api_hash=SecretValue("secret")),
        processor=cast(SignalProcessor, object()),
        client_factory=cast(Any, lambda *args, **kwargs: fake_client),
    )

    asyncio.run(listener.run())

    assert listener.health.authorized is True
    assert listener.health.connected is False
    assert listener.health.last_error_code is None
    assert fake_client.connected is False


def test_listener_sends_default_plain_text_result_to_configured_log_group(
    tmp_path: Path,
) -> None:
    session_path = private_session(tmp_path)
    fake_client = FakeClient(authorized=True)
    fake_client.connected = True
    listener = TelethonListener(
        settings=settings(session_path),
        credentials=TelegramCredentials(api_id=123, api_hash=SecretValue("secret")),
        processor=cast(SignalProcessor, StubProcessor()),
        clock=lambda: NOW,
    )
    listener._client = cast(Any, fake_client)

    asyncio.run(listener._handle_event(event()))

    assert listener.health.last_error_code is None
    assert len(fake_client.sent_messages) == 1
    destination, message, parse_mode, link_preview = fake_client.sent_messages[0]
    assert destination == -9001
    assert "[TEST] SIGNAL REJECTED" in message
    assert "Broker action: NONE" in message
    assert parse_mode is None
    assert link_preview is False


def test_listener_reports_only_error_class_without_sensitive_exception_text(
    tmp_path: Path,
) -> None:
    session_path = private_session(tmp_path)
    fake_client = FakeClient(authorized=True)
    fake_client.connected = True
    listener = TelethonListener(
        settings=settings(session_path),
        credentials=TelegramCredentials(api_id=123, api_hash=SecretValue("secret")),
        processor=cast(SignalProcessor, FailingProcessor()),
        clock=lambda: NOW,
    )
    listener._client = cast(Any, fake_client)

    asyncio.run(listener._handle_event(event()))

    assert listener.health.last_error_code == "RuntimeError"
    assert len(fake_client.sent_messages) == 1
    message = fake_client.sent_messages[0][1]
    assert "Error code: RuntimeError" in message
    assert "sensitive upstream detail" not in message
    assert "Broker action: NONE" in message


def test_listener_routes_authenticated_feedback_without_signal_processing(
    tmp_path: Path,
) -> None:
    session_path = private_session(tmp_path)
    fake_client = FakeClient(authorized=True)
    fake_client.connected = True
    journal = SQLiteJournal(tmp_path / "codexbot.sqlite3", clock=lambda: NOW)
    journal.initialize()
    journal.record_signal_receipt(
        source_group_id=-1001,
        telegram_message_id=42,
        sent_at=NOW,
    )
    feedback_service = OperatorFeedbackService(
        journal=journal,
        log_group_id=-9001,
        authorized_operator_ids=frozenset({3001}),
    )
    listener = TelethonListener(
        settings=settings(session_path),
        credentials=TelegramCredentials(api_id=123, api_hash=SecretValue("secret")),
        processor=cast(SignalProcessor, FailingProcessor()),
        feedback_service=feedback_service,
        clock=lambda: NOW,
    )
    listener._client = cast(Any, fake_client)

    asyncio.run(
        listener._route_event(
            event(
                chat_id=-9001,
                sender_id=3001,
                message_id=77,
                text="/feedback -1001:42 review parser rejection",
            )
        )
    )

    assert listener.health.last_error_code is None
    assert journal.recent_operator_feedback()[0].status == "PENDING_REVIEW"
    message = fake_client.sent_messages[0][1]
    assert "FEEDBACK RECORDED" in message
    assert "Rule change: NONE" in message
    assert "Message replay: NONE" in message
    assert "Broker action: NONE" in message
