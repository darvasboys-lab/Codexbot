from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from codexbot import (
    FeedbackEnvelope,
    FeedbackError,
    OperatorFeedbackService,
    feedback_envelope_from_event,
)
from codexbot.persistence import SQLiteJournal

NOW = datetime(2026, 10, 28, 4, 0, tzinfo=UTC)


def service(tmp_path: Path) -> OperatorFeedbackService:
    journal = SQLiteJournal(tmp_path / "codexbot.sqlite3", clock=lambda: NOW)
    journal.initialize()
    journal.record_signal_receipt(
        source_group_id=-1001,
        telegram_message_id=42,
        sent_at=NOW,
    )
    return OperatorFeedbackService(
        journal=journal,
        log_group_id=-9001,
        authorized_operator_ids=frozenset({3001}),
    )


def envelope(**overrides: object) -> FeedbackEnvelope:
    values: dict[str, object] = {
        "group_id": -9001,
        "telegram_message_id": 77,
        "sender_id": 3001,
        "sent_at": NOW,
        "text": "/feedback -1001:42 parser should keep this rejected",
        "is_forwarded": False,
    }
    values.update(overrides)
    return FeedbackEnvelope(**values)  # type: ignore[arg-type]


def test_authenticated_feedback_is_queued_only_for_review(tmp_path: Path) -> None:
    result = service(tmp_path).process(envelope())

    assert result.status == "PENDING_REVIEW"
    assert result.source_group_id == -1001
    assert result.source_telegram_message_id == 42
    assert result.feedback_text == "parser should keep this rejected"


@pytest.mark.parametrize(
    ("overrides", "error_code"),
    [
        ({"group_id": -9002}, "FEEDBACK_GROUP_UNAUTHORIZED"),
        ({"sender_id": 3002}, "FEEDBACK_OPERATOR_UNAUTHORIZED"),
        ({"is_forwarded": True}, "FEEDBACK_FORWARDED_REJECTED"),
        ({"text": "/feedback bad command"}, "FEEDBACK_COMMAND_INVALID"),
        ({"text": "/feedback -1001:999 missing"}, "FEEDBACK_TARGET_NOT_FOUND"),
    ],
)
def test_feedback_rejections_are_fixed_codes(
    tmp_path: Path, overrides: dict[str, object], error_code: str
) -> None:
    with pytest.raises(FeedbackError, match=error_code):
        service(tmp_path).process(envelope(**overrides))


def test_feedback_event_conversion_preserves_authentication_facts() -> None:
    event = SimpleNamespace(
        chat_id=-9001,
        sender_id=3001,
        raw_text="/feedback -1001:42 review",
        message=SimpleNamespace(id=77, date=NOW, fwd_from=None),
    )

    result = feedback_envelope_from_event(event)

    assert result == envelope(text="/feedback -1001:42 review")
