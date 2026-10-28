"""Operator-attended creation of the one protected Telethon user session."""

from __future__ import annotations

import argparse
import asyncio
import os
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Protocol

from telethon import TelegramClient  # type: ignore[import-untyped]

from codexbot.settings import TelegramCredentials, load_protected_environment
from codexbot.telegram import TelegramListenerError, harden_telegram_session


class TelegramAuthorizationClient(Protocol):
    async def start(self, *, phone: str | None = None) -> object: ...

    async def is_user_authorized(self) -> bool: ...

    async def disconnect(self) -> None: ...


ClientFactory = Callable[[str, int, str], TelegramAuthorizationClient]


async def authorize_telegram_session(
    session_path: Path,
    credentials: TelegramCredentials,
    *,
    client_factory: ClientFactory = TelegramClient,
) -> None:
    """Create or verify one session interactively, then enforce owner-only files."""

    harden_telegram_session(session_path)
    phone = credentials.phone_number.reveal() if credentials.phone_number is not None else None
    client = client_factory(
        str(session_path),
        credentials.api_id,
        credentials.api_hash.reveal(),
    )
    try:
        await client.start(phone=phone)
        if not await client.is_user_authorized():
            raise TelegramListenerError("Telegram authorization did not complete")
    finally:
        await client.disconnect()
        harden_telegram_session(session_path)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--environment", type=Path, required=True)
    arguments = parser.parse_args(argv)
    previous_umask = os.umask(0o077)
    try:
        configuration = load_protected_environment(arguments.environment)
        asyncio.run(
            authorize_telegram_session(
                configuration.settings.telegram_session_path,
                configuration.telegram,
            )
        )
    finally:
        os.umask(previous_umask)
    print("TELEGRAM_SESSION_AUTHORIZED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

