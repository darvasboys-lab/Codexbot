"""Authenticated operator feedback intake with no rule or trading side effects."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from codexbot.persistence import OperatorFeedback, SQLiteJournal

_COMMAND = re.compile(r"^/feedback\s+(-?\d+):(\d+)\s+(.+)$", re.DOTALL)


class FeedbackError(ValueError):
    """A fixed safe code for a rejected feedback command."""


@dataclass(frozen=True, slots=True)
class FeedbackEnvelope:
    group_id: int
    telegram_message_id: int
    sender_id: int | None
    sent_at: datetime
    text: str | None
    is_forwarded: bool


class OperatorFeedbackService:
    """Authenticate, parse, and durably queue feedback for manual review only."""

    def __init__(
        self,
        *,
        journal: SQLiteJournal,
        log_group_id: int,
        authorized_operator_ids: frozenset[int],
    ) -> None:
        if log_group_id == 0:
            raise ValueError("log_group_id cannot be zero")
        if not authorized_operator_ids or 0 in authorized_operator_ids:
            raise ValueError("authorized operator IDs are required and cannot contain zero")
        self._journal = journal
        self._log_group_id = log_group_id
        self._authorized_operator_ids = authorized_operator_ids

    def process(self, envelope: FeedbackEnvelope) -> OperatorFeedback:
        if envelope.group_id != self._log_group_id:
            raise FeedbackError("FEEDBACK_GROUP_UNAUTHORIZED")
        if envelope.sender_id not in self._authorized_operator_ids:
            raise FeedbackError("FEEDBACK_OPERATOR_UNAUTHORIZED")
        if envelope.is_forwarded:
            raise FeedbackError("FEEDBACK_FORWARDED_REJECTED")
        if envelope.telegram_message_id <= 0:
            raise FeedbackError("FEEDBACK_MESSAGE_ID_INVALID")
        text = envelope.text or ""
        match = _COMMAND.fullmatch(text.strip())
        if match is None:
            raise FeedbackError("FEEDBACK_COMMAND_INVALID")
        source_group_id = int(match.group(1))
        source_message_id = int(match.group(2))
        if source_group_id == 0 or source_message_id <= 0:
            raise FeedbackError("FEEDBACK_TARGET_INVALID")
        try:
            return self._journal.record_operator_feedback(
                source_group_id=source_group_id,
                source_telegram_message_id=source_message_id,
                feedback_group_id=envelope.group_id,
                feedback_telegram_message_id=envelope.telegram_message_id,
                operator_id=envelope.sender_id,
                feedback_text=match.group(3),
            )
        except ValueError as error:
            if str(error) == "feedback target signal receipt does not exist":
                raise FeedbackError("FEEDBACK_TARGET_NOT_FOUND") from error
            if "1000 characters" in str(error):
                raise FeedbackError("FEEDBACK_TEXT_TOO_LONG") from error
            raise FeedbackError("FEEDBACK_REJECTED") from error


def feedback_envelope_from_event(event: Any) -> FeedbackEnvelope:
    """Extract the minimal Telegram facts needed by the feedback service."""

    message = event.message
    sender_id = getattr(event, "sender_id", None)
    return FeedbackEnvelope(
        group_id=int(event.chat_id),
        telegram_message_id=int(message.id),
        sender_id=int(sender_id) if sender_id is not None else None,
        sent_at=message.date,
        text=getattr(event, "raw_text", None) or None,
        is_forwarded=getattr(message, "fwd_from", None) is not None,
    )
