"""Read-only inspection of journal receipts lacking a final check decision.

This is an operator diagnostic, not replay, reconciliation, or an order engine.
An unfinished receipt is never automatically reprocessed.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

_REQUIRED_TABLES = frozenset(
    {"signal_receipts", "audit_events", "option_duplicate_decisions"}
)


@dataclass(frozen=True, slots=True)
class UnfinishedReceipt:
    receipt_id: int
    source_group_id: int
    telegram_message_id: int
    first_durable_received_at: str
    last_processing_event: str | None
    option_decision_recorded: bool


@dataclass(frozen=True, slots=True)
class UnfinishedReceiptReport:
    total: int
    receipts: tuple[UnfinishedReceipt, ...]

    @property
    def truncated(self) -> bool:
        return self.total > len(self.receipts)


def inspect_unfinished_receipts(
    database_path: str | Path, *, limit: int = 50
) -> UnfinishedReceiptReport:
    """List durable receipts without SIGNAL_CHECKED, without mutating the journal.

    A crash may leave a receipt with only SIGNAL_RECEIVED, or even an option
    duplicate decision but no final check event. Neither case authorizes a
    replay or a broker order. A consistent SQLite read snapshot is used for
    the count and the bounded detail list.
    """

    if not 1 <= limit <= 1000:
        raise ValueError("limit must be between 1 and 1000")
    path = Path(database_path)
    if path.is_symlink():
        raise ValueError("database path must not be a symlink")
    if not path.is_file():
        raise FileNotFoundError(path)

    # SQLite URI mode=ro prevents accidental database creation and writes.
    uri = f"{path.absolute().as_uri()}?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only = ON")
        connection.execute("BEGIN")
        tables = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        missing = sorted(_REQUIRED_TABLES - tables)
        if missing:
            raise ValueError(f"missing journal tables: {', '.join(missing)}")

        unfinished_condition = """
            NOT EXISTS (
                SELECT 1 FROM audit_events AS completed
                WHERE completed.entity_type = 'signal_receipt'
                  AND completed.entity_id = CAST(receipt.id AS TEXT)
                  AND completed.event_type = 'SIGNAL_CHECKED'
            )
        """
        count_row = connection.execute(
            f"SELECT COUNT(*) FROM signal_receipts AS receipt WHERE {unfinished_condition}"
        ).fetchone()
        if count_row is None:
            raise RuntimeError("SQLite did not return an unfinished receipt count")
        total = int(count_row[0])

        rows = connection.execute(
            f"""
            SELECT receipt.id, receipt.source_group_id,
                   receipt.telegram_message_id,
                   receipt.first_durable_received_at,
                   (
                       SELECT event.event_type
                       FROM audit_events AS event
                       WHERE event.entity_type = 'signal_receipt'
                         AND event.entity_id = CAST(receipt.id AS TEXT)
                         AND event.event_type != 'SIGNAL_REDELIVERED'
                       ORDER BY event.id DESC LIMIT 1
                   ) AS last_processing_event,
                   EXISTS (
                       SELECT 1 FROM option_duplicate_decisions AS decision
                       WHERE decision.signal_receipt_id = receipt.id
                   ) AS option_decision_recorded
            FROM signal_receipts AS receipt
            WHERE {unfinished_condition}
            ORDER BY receipt.id ASC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return UnfinishedReceiptReport(
            total=total,
            receipts=tuple(
                UnfinishedReceipt(
                    receipt_id=int(row["id"]),
                    source_group_id=int(row["source_group_id"]),
                    telegram_message_id=int(row["telegram_message_id"]),
                    first_durable_received_at=str(row["first_durable_received_at"]),
                    last_processing_event=(
                        str(row["last_processing_event"])
                        if row["last_processing_event"] is not None
                        else None
                    ),
                    option_decision_recorded=bool(row["option_decision_recorded"]),
                )
                for row in rows
            ),
        )
