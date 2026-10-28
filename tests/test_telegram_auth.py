from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from codexbot.settings import SecretValue, TelegramCredentials
from codexbot.telegram import TelegramListenerError
from codexbot.telegram_auth import authorize_telegram_session


class FakeAuthorizationClient:
    def __init__(self, session: str, api_id: int, api_hash: str, *, authorized: bool) -> None:
        self.session = Path(session)
        self.api_id = api_id
        self.api_hash = api_hash
        self.authorized = authorized
        self.phone: str | None = None
        self.disconnected = False

    async def start(self, *, phone: str | None = None) -> object:
        self.phone = phone
        self.session.write_text("session-state", encoding="utf-8")
        self.session.chmod(0o666)
        return self

    async def is_user_authorized(self) -> bool:
        return self.authorized

    async def disconnect(self) -> None:
        self.disconnected = True


def test_authorization_creates_and_hardens_session_without_exposing_secrets(
    tmp_path: Path,
) -> None:
    tmp_path.chmod(0o700)
    created: list[FakeAuthorizationClient] = []

    def factory(session: str, api_id: int, api_hash: str) -> FakeAuthorizationClient:
        client = FakeAuthorizationClient(session, api_id, api_hash, authorized=True)
        created.append(client)
        return client

    credentials = TelegramCredentials(
        api_id=123,
        api_hash=SecretValue("api-secret"),
        phone_number=SecretValue("+910000000000"),
    )
    session = tmp_path / "udit.session"

    asyncio.run(authorize_telegram_session(session, credentials, client_factory=factory))

    assert session.stat().st_mode & 0o077 == 0
    assert created[0].phone == "+910000000000"
    assert created[0].disconnected is True


def test_failed_authorization_still_disconnects_and_hardens_session(tmp_path: Path) -> None:
    tmp_path.chmod(0o700)
    created: list[FakeAuthorizationClient] = []

    def factory(session: str, api_id: int, api_hash: str) -> FakeAuthorizationClient:
        client = FakeAuthorizationClient(session, api_id, api_hash, authorized=False)
        created.append(client)
        return client

    credentials = TelegramCredentials(api_id=123, api_hash=SecretValue("api-secret"))
    session = tmp_path / "udit.session"

    with pytest.raises(TelegramListenerError, match="did not complete"):
        asyncio.run(authorize_telegram_session(session, credentials, client_factory=factory))

    assert session.stat().st_mode & 0o077 == 0
    assert created[0].disconnected is True

