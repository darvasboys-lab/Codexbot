"""SQLite journal, durable receipts, audit events, and option deduplication.

This module stores facts and decisions only. It has no broker dependency and no
order-placement capability.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from codexbot.models import CheckReport

_DUPLICATE_WINDOW = timedelta(seconds=20)
_REQUIRED_TABLES = frozenset(
    {
        "audit_events",
        "signal_receipts",
        "option_duplicate_claims",
        "option_duplicate_decisions",
        "runtime_control_events",
    }
)


@dataclass(frozen=True, slots=True)
class SignalReceipt:
    id: int
    source_group_id: int
    telegram_message_id: int
    sent_at: datetime
    first_durable_received_at: datetime


@dataclass(frozen=True, slots=True)
class DuplicateClaimResult:
    accepted: bool
    receipt_id: int
    canonical_underlying_id: str
    first_durable_received_at: datetime
    matched_claim_id: int | None


@dataclass(frozen=True, slots=True)
class EmergencyStopStatus:
    """Latest durable entry-gate state; absence of a release fails closed."""

    engaged: bool
    changed_at: datetime | None
    reason: str
    actor: str | None
    event_id: int | None

    @property
    def new_entries_allowed(self) -> bool:
        return not self.engaged


class SQLiteJournal:
    """Single-process SQLite journal configured for WAL operation."""

    def __init__(
        self,
        database_path: str | Path,
        *,
        clock: Callable[[], datetime] | None = None,
        busy_timeout_ms: int = 5_000,
    ) -> None:
        if busy_timeout_ms <= 0:
            raise ValueError("busy_timeout_ms must be positive")
        self._path = Path(database_path)
        self._clock = clock or (lambda: datetime.now(UTC))
        self._busy_timeout_ms = busy_timeout_ms

    @property
    def database_path(self) -> Path:
        return self._path

    def initialize(self) -> None:
        """Create the journal schema and enforce WAL mode."""

        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(_SCHEMA)

    def journal_mode(self) -> str:
        with self._connect() as connection:
            row = connection.execute("PRAGMA journal_mode").fetchone()
        if row is None:
            raise RuntimeError("SQLite did not return a journal mode")
        return str(row[0]).lower()

    def record_signal_receipt(
        self,
        *,
        source_group_id: int,
        telegram_message_id: int,
        sent_at: datetime,
    ) -> SignalReceipt:
        """Persist first receipt once and return its immutable timestamp.

        The timestamp is captured inside the transaction that first inserts the
        Telegram message identity. Redelivery returns the original timestamp.
        """

        sent_at_text = _datetime_text(sent_at)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                """
                SELECT id, source_group_id, telegram_message_id, sent_at,
                       first_durable_received_at
                FROM signal_receipts
                WHERE source_group_id = ? AND telegram_message_id = ?
                """,
                (source_group_id, telegram_message_id),
            ).fetchone()
            if existing is not None:
                self._append_audit_event(
                    connection,
                    event_type="SIGNAL_REDELIVERED",
                    entity_type="signal_receipt",
                    entity_id=str(existing["id"]),
                    state="IGNORED",
                    details={
                        "source_group_id": source_group_id,
                        "telegram_message_id": telegram_message_id,
                    },
                    occurred_at=self._now(),
                )
                connection.commit()
                return _receipt_from_row(existing)

            durable_at = self._now()
            cursor = connection.execute(
                """
                INSERT INTO signal_receipts (
                    source_group_id, telegram_message_id, sent_at,
                    first_durable_received_at
                ) VALUES (?, ?, ?, ?)
                """,
                (
                    source_group_id,
                    telegram_message_id,
                    sent_at_text,
                    _datetime_text(durable_at),
                ),
            )
            receipt_id = _last_row_id(cursor)
            self._append_audit_event(
                connection,
                event_type="SIGNAL_RECEIVED",
                entity_type="signal_receipt",
                entity_id=str(receipt_id),
                state="DURABLE",
                details={
                    "source_group_id": source_group_id,
                    "telegram_message_id": telegram_message_id,
                },
                occurred_at=durable_at,
            )
            connection.commit()
            return SignalReceipt(
                id=receipt_id,
                source_group_id=source_group_id,
                telegram_message_id=telegram_message_id,
                sent_at=sent_at.astimezone(UTC),
                first_durable_received_at=durable_at,
            )

    def append_audit_event(
        self,
        *,
        event_type: str,
        entity_type: str,
        entity_id: str | None,
        state: str,
        details: Mapping[str, object] | None = None,
        occurred_at: datetime | None = None,
    ) -> int:
        """Append a generic system or signal-processing event."""

        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            event_id = self._append_audit_event(
                connection,
                event_type=event_type,
                entity_type=entity_type,
                entity_id=entity_id,
                state=state,
                details=details or {},
                occurred_at=occurred_at or self._now(),
            )
            connection.commit()
        return event_id

    def record_signal_check(self, *, receipt_id: int, report: CheckReport) -> int:
        """Append the complete deterministic checker outcome for a receipt."""

        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            receipt_exists = connection.execute(
                "SELECT 1 FROM signal_receipts WHERE id = ?", (receipt_id,)
            ).fetchone()
            if receipt_exists is None:
                raise ValueError(f"unknown signal receipt ID: {receipt_id}")
            event_id = self._append_audit_event(
                connection,
                event_type="SIGNAL_CHECKED",
                entity_type="signal_receipt",
                entity_id=str(receipt_id),
                state=report.disposition.value,
                details={
                    "execution_mode": report.execution_mode.value,
                    "pending_gates": [gate.value for gate in report.pending_gates],
                    "reasons": [reason.value for reason in report.reasons],
                    "trade_ready": report.trade_ready,
                },
                occurred_at=self._now(),
            )
            connection.commit()
        return event_id

    def claim_stock_option_signal(
        self,
        *,
        receipt_id: int,
        canonical_underlying_id: str,
    ) -> DuplicateClaimResult:
        """Atomically claim the approved stock-option deduplication key.

        Strike, expiry, price, and CE/PE are deliberately absent. The key is the
        canonical underlying ID, BUY action, STOCK_OPTION product family, and the
        persisted first durable receipt timestamp. An accepted claim blocks the
        same key for 20 seconds in either timestamp direction, which also fails
        closed across a small wall-clock correction.
        """

        underlying_id = canonical_underlying_id.strip()
        if not underlying_id:
            raise ValueError("canonical_underlying_id is required")

        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            receipt_row = connection.execute(
                """
                SELECT id, first_durable_received_at
                FROM signal_receipts
                WHERE id = ?
                """,
                (receipt_id,),
            ).fetchone()
            if receipt_row is None:
                raise ValueError(f"unknown signal receipt ID: {receipt_id}")

            receipt_at = _parse_datetime(str(receipt_row["first_durable_received_at"]))
            existing_decision = connection.execute(
                """
                SELECT accepted, matched_claim_id, canonical_underlying_id
                FROM option_duplicate_decisions
                WHERE signal_receipt_id = ?
                """,
                (receipt_id,),
            ).fetchone()
            if existing_decision is not None:
                stored_underlying_id = str(existing_decision["canonical_underlying_id"])
                if stored_underlying_id != underlying_id:
                    raise ValueError(
                        "signal receipt already has a duplicate decision for a different underlying"
                    )
                connection.commit()
                matched = existing_decision["matched_claim_id"]
                return DuplicateClaimResult(
                    accepted=bool(existing_decision["accepted"]),
                    receipt_id=receipt_id,
                    canonical_underlying_id=stored_underlying_id,
                    first_durable_received_at=receipt_at,
                    matched_claim_id=int(matched) if matched is not None else None,
                )

            lower = _datetime_text(receipt_at - _DUPLICATE_WINDOW)
            upper = _datetime_text(receipt_at + _DUPLICATE_WINDOW)
            matching_claim = connection.execute(
                """
                SELECT id
                FROM option_duplicate_claims
                WHERE canonical_underlying_id = ?
                  AND action = 'BUY'
                  AND product_family = 'STOCK_OPTION'
                  AND first_durable_received_at BETWEEN ? AND ?
                ORDER BY first_durable_received_at ASC, id ASC
                LIMIT 1
                """,
                (underlying_id, lower, upper),
            ).fetchone()

            if matching_claim is not None:
                matched_claim_id = int(matching_claim["id"])
                connection.execute(
                    """
                    INSERT INTO option_duplicate_decisions (
                        signal_receipt_id, canonical_underlying_id, action,
                        product_family, first_durable_received_at, accepted,
                        matched_claim_id
                    ) VALUES (?, ?, 'BUY', 'STOCK_OPTION', ?, 0, ?)
                    """,
                    (
                        receipt_id,
                        underlying_id,
                        _datetime_text(receipt_at),
                        matched_claim_id,
                    ),
                )
                self._append_audit_event(
                    connection,
                    event_type="OPTION_DUPLICATE_REJECTED",
                    entity_type="signal_receipt",
                    entity_id=str(receipt_id),
                    state="DUPLICATE",
                    details={
                        "canonical_underlying_id": underlying_id,
                        "matched_claim_id": matched_claim_id,
                        "window_seconds": 20,
                    },
                    occurred_at=self._now(),
                )
                connection.commit()
                return DuplicateClaimResult(
                    accepted=False,
                    receipt_id=receipt_id,
                    canonical_underlying_id=underlying_id,
                    first_durable_received_at=receipt_at,
                    matched_claim_id=matched_claim_id,
                )

            claim_cursor = connection.execute(
                """
                INSERT INTO option_duplicate_claims (
                    signal_receipt_id, canonical_underlying_id, action,
                    product_family, first_durable_received_at
                ) VALUES (?, ?, 'BUY', 'STOCK_OPTION', ?)
                """,
                (receipt_id, underlying_id, _datetime_text(receipt_at)),
            )
            claim_id = _last_row_id(claim_cursor)
            connection.execute(
                """
                INSERT INTO option_duplicate_decisions (
                    signal_receipt_id, canonical_underlying_id, action,
                    product_family, first_durable_received_at, accepted,
                    matched_claim_id
                ) VALUES (?, ?, 'BUY', 'STOCK_OPTION', ?, 1, ?)
                """,
                (receipt_id, underlying_id, _datetime_text(receipt_at), claim_id),
            )
            self._append_audit_event(
                connection,
                event_type="OPTION_DUPLICATE_CLAIMED",
                entity_type="signal_receipt",
                entity_id=str(receipt_id),
                state="ACCEPTED",
                details={
                    "canonical_underlying_id": underlying_id,
                    "claim_id": claim_id,
                    "window_seconds": 20,
                },
                occurred_at=self._now(),
            )
            connection.commit()
            return DuplicateClaimResult(
                accepted=True,
                receipt_id=receipt_id,
                canonical_underlying_id=underlying_id,
                first_durable_received_at=receipt_at,
                matched_claim_id=claim_id,
            )

    def emergency_stop_status(self) -> EmergencyStopStatus:
        """Return the latest stop state; a new database starts engaged."""

        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT id, occurred_at, engaged, reason, actor
                FROM runtime_control_events
                ORDER BY id DESC
                LIMIT 1
                """
            ).fetchone()
        if row is None:
            return EmergencyStopStatus(
                engaged=True,
                changed_at=None,
                reason="NO_RELEASE_RECORDED",
                actor=None,
                event_id=None,
            )
        return _emergency_stop_from_row(row)

    def set_emergency_stop(self, *, engaged: bool, reason: str, actor: str) -> EmergencyStopStatus:
        """Append an operator control event and matching immutable audit fact."""

        normalized_reason = reason.strip()
        normalized_actor = actor.strip()
        if not normalized_reason:
            raise ValueError("emergency-stop reason is required")
        if len(normalized_reason) > 500:
            raise ValueError("emergency-stop reason cannot exceed 500 characters")
        if not normalized_actor:
            raise ValueError("emergency-stop actor is required")
        if len(normalized_actor) > 200:
            raise ValueError("emergency-stop actor cannot exceed 200 characters")

        occurred_at = self._now()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                """
                INSERT INTO runtime_control_events (
                    occurred_at, control_name, engaged, reason, actor
                ) VALUES (?, 'EMERGENCY_STOP', ?, ?, ?)
                """,
                (
                    _datetime_text(occurred_at),
                    int(engaged),
                    normalized_reason,
                    normalized_actor,
                ),
            )
            event_id = _last_row_id(cursor)
            state = "ENGAGED" if engaged else "RELEASED"
            self._append_audit_event(
                connection,
                event_type="EMERGENCY_STOP_CHANGED",
                entity_type="runtime_control",
                entity_id=str(event_id),
                state=state,
                details={"actor": normalized_actor, "reason": normalized_reason},
                occurred_at=occurred_at,
            )
            connection.commit()
        return EmergencyStopStatus(
            engaged=engaged,
            changed_at=occurred_at,
            reason=normalized_reason,
            actor=normalized_actor,
            event_id=event_id,
        )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._path, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(f"PRAGMA busy_timeout = {self._busy_timeout_ms}")
        mode_row = connection.execute("PRAGMA journal_mode = WAL").fetchone()
        if mode_row is None or str(mode_row[0]).lower() != "wal":
            connection.close()
            raise RuntimeError("SQLite database did not enter WAL mode")
        connection.execute("PRAGMA synchronous = NORMAL")
        return connection

    def _append_audit_event(
        self,
        connection: sqlite3.Connection,
        *,
        event_type: str,
        entity_type: str,
        entity_id: str | None,
        state: str,
        details: Mapping[str, object],
        occurred_at: datetime,
    ) -> int:
        if not event_type.strip() or not entity_type.strip() or not state.strip():
            raise ValueError("event_type, entity_type, and state are required")
        cursor = connection.execute(
            """
            INSERT INTO audit_events (
                occurred_at, event_type, entity_type, entity_id, state,
                details_json
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                _datetime_text(occurred_at),
                event_type,
                entity_type,
                entity_id,
                state,
                json.dumps(dict(details), sort_keys=True, separators=(",", ":")),
            ),
        )
        return _last_row_id(cursor)

    def _now(self) -> datetime:
        return _aware_utc(self._clock())


def integrity_check(database_path: str | Path) -> tuple[str, ...]:
    """Run SQLite's full integrity check without changing application data."""

    with sqlite3.connect(Path(database_path)) as connection:
        rows = connection.execute("PRAGMA integrity_check").fetchall()
    return tuple(str(row[0]) for row in rows)


def backup_database(database_path: str | Path, backup_path: str | Path) -> Path:
    """Create a transactionally consistent SQLite backup, including WAL data."""

    source_path = Path(database_path)
    destination_path = Path(backup_path)
    if not source_path.is_file():
        raise FileNotFoundError(source_path)
    if destination_path.exists():
        raise FileExistsError(destination_path)
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    with (
        sqlite3.connect(source_path) as source,
        sqlite3.connect(destination_path) as destination,
    ):
        source.backup(destination)
    return destination_path


def restore_test(backup_path: str | Path) -> tuple[str, ...]:
    """Restore a backup to a temporary database and verify schema/integrity."""

    source_path = Path(backup_path)
    if not source_path.is_file():
        raise FileNotFoundError(source_path)
    with tempfile.TemporaryDirectory(prefix="codexbot-restore-") as temporary_directory:
        restored_path = Path(temporary_directory) / "restored.sqlite3"
        shutil.copy2(source_path, restored_path)
        results = integrity_check(restored_path)
        if results != ("ok",):
            return results
        with sqlite3.connect(restored_path) as connection:
            rows = connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        present_tables = {str(row[0]) for row in rows}
        missing = sorted(_REQUIRED_TABLES - present_tables)
        if missing:
            return (f"missing required tables: {', '.join(missing)}",)
        return results


def _receipt_from_row(row: sqlite3.Row) -> SignalReceipt:
    return SignalReceipt(
        id=int(row["id"]),
        source_group_id=int(row["source_group_id"]),
        telegram_message_id=int(row["telegram_message_id"]),
        sent_at=_parse_datetime(str(row["sent_at"])),
        first_durable_received_at=_parse_datetime(str(row["first_durable_received_at"])),
    )


def _emergency_stop_from_row(row: sqlite3.Row) -> EmergencyStopStatus:
    return EmergencyStopStatus(
        engaged=bool(row["engaged"]),
        changed_at=_parse_datetime(str(row["occurred_at"])),
        reason=str(row["reason"]),
        actor=str(row["actor"]),
        event_id=int(row["id"]),
    )


def _last_row_id(cursor: sqlite3.Cursor) -> int:
    if cursor.lastrowid is None:
        raise RuntimeError("SQLite did not return a row ID")
    return int(cursor.lastrowid)


def _datetime_text(value: datetime) -> str:
    return _aware_utc(value).isoformat(timespec="microseconds")


def _parse_datetime(value: str) -> datetime:
    return _aware_utc(datetime.fromisoformat(value))


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime must be timezone-aware")
    return value.astimezone(UTC)


_SCHEMA = """
CREATE TABLE IF NOT EXISTS signal_receipts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_group_id INTEGER NOT NULL,
    telegram_message_id INTEGER NOT NULL,
    sent_at TEXT NOT NULL,
    first_durable_received_at TEXT NOT NULL,
    UNIQUE (source_group_id, telegram_message_id)
);

CREATE TABLE IF NOT EXISTS audit_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    occurred_at TEXT NOT NULL,
    event_type TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id TEXT,
    state TEXT NOT NULL,
    details_json TEXT NOT NULL CHECK (json_valid(details_json))
);

CREATE INDEX IF NOT EXISTS audit_events_entity_time
ON audit_events (entity_type, entity_id, occurred_at, id);

CREATE TABLE IF NOT EXISTS option_duplicate_claims (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_receipt_id INTEGER NOT NULL UNIQUE REFERENCES signal_receipts(id),
    canonical_underlying_id TEXT NOT NULL,
    action TEXT NOT NULL CHECK (action = 'BUY'),
    product_family TEXT NOT NULL CHECK (product_family = 'STOCK_OPTION'),
    first_durable_received_at TEXT NOT NULL,
    UNIQUE (
        canonical_underlying_id,
        action,
        product_family,
        first_durable_received_at
    )
);

CREATE INDEX IF NOT EXISTS option_claims_dedup_window
ON option_duplicate_claims (
    canonical_underlying_id,
    action,
    product_family,
    first_durable_received_at
);

CREATE TABLE IF NOT EXISTS option_duplicate_decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_receipt_id INTEGER NOT NULL UNIQUE REFERENCES signal_receipts(id),
    canonical_underlying_id TEXT NOT NULL,
    action TEXT NOT NULL CHECK (action = 'BUY'),
    product_family TEXT NOT NULL CHECK (product_family = 'STOCK_OPTION'),
    first_durable_received_at TEXT NOT NULL,
    accepted INTEGER NOT NULL CHECK (accepted IN (0, 1)),
    matched_claim_id INTEGER NOT NULL REFERENCES option_duplicate_claims(id)
);

CREATE TABLE IF NOT EXISTS runtime_control_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    occurred_at TEXT NOT NULL,
    control_name TEXT NOT NULL CHECK (control_name = 'EMERGENCY_STOP'),
    engaged INTEGER NOT NULL CHECK (engaged IN (0, 1)),
    reason TEXT NOT NULL CHECK (length(reason) BETWEEN 1 AND 500),
    actor TEXT NOT NULL CHECK (length(actor) BETWEEN 1 AND 200)
);

CREATE TRIGGER IF NOT EXISTS audit_events_no_update
BEFORE UPDATE ON audit_events
BEGIN
    SELECT RAISE(ABORT, 'audit_events is append-only');
END;

CREATE TRIGGER IF NOT EXISTS audit_events_no_delete
BEFORE DELETE ON audit_events
BEGIN
    SELECT RAISE(ABORT, 'audit_events is append-only');
END;

CREATE TRIGGER IF NOT EXISTS signal_receipts_no_update
BEFORE UPDATE ON signal_receipts
BEGIN
    SELECT RAISE(ABORT, 'signal_receipts is append-only');
END;

CREATE TRIGGER IF NOT EXISTS signal_receipts_no_delete
BEFORE DELETE ON signal_receipts
BEGIN
    SELECT RAISE(ABORT, 'signal_receipts is append-only');
END;

CREATE TRIGGER IF NOT EXISTS option_claims_no_update
BEFORE UPDATE ON option_duplicate_claims
BEGIN
    SELECT RAISE(ABORT, 'option_duplicate_claims is append-only');
END;

CREATE TRIGGER IF NOT EXISTS option_claims_no_delete
BEFORE DELETE ON option_duplicate_claims
BEGIN
    SELECT RAISE(ABORT, 'option_duplicate_claims is append-only');
END;

CREATE TRIGGER IF NOT EXISTS option_decisions_no_update
BEFORE UPDATE ON option_duplicate_decisions
BEGIN
    SELECT RAISE(ABORT, 'option_duplicate_decisions is append-only');
END;

CREATE TRIGGER IF NOT EXISTS option_decisions_no_delete
BEFORE DELETE ON option_duplicate_decisions
BEGIN
    SELECT RAISE(ABORT, 'option_duplicate_decisions is append-only');
END;

CREATE TRIGGER IF NOT EXISTS runtime_control_no_update
BEFORE UPDATE ON runtime_control_events
BEGIN
    SELECT RAISE(ABORT, 'runtime_control_events is append-only');
END;

CREATE TRIGGER IF NOT EXISTS runtime_control_no_delete
BEFORE DELETE ON runtime_control_events
BEGIN
    SELECT RAISE(ABORT, 'runtime_control_events is append-only');
END;
"""
