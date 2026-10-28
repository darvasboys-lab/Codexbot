"""Plain-text operator reports derived from deterministic results and audit facts."""

from __future__ import annotations

from codexbot.persistence import DailyAuditSummary, OperatorFeedback
from codexbot.processing import ProcessingResult


def format_processing_result(result: ProcessingResult) -> str:
    """Format one signal result without raw message text or secret material."""

    instrument = result.instrument
    claim = result.duplicate_claim
    reasons = ", ".join(reason.value for reason in result.report.reasons) or "NONE"
    pending = ", ".join(gate.value for gate in result.report.pending_gates) or "NONE"
    if claim is None:
        duplicate = "NOT_APPLICABLE"
    else:
        duplicate = "ACCEPTED" if claim.accepted else "DUPLICATE"
    lines = [
        f"[{result.report.execution_mode.value}] SIGNAL {result.report.disposition.value}",
        f"Source group: {result.receipt.source_group_id}",
        f"Message ID: {result.receipt.telegram_message_id}",
        f"Action: {result.parsed.action.value}",
        f"Segment: {result.parsed.segment.value if result.parsed.segment else 'UNRESOLVED'}",
        f"Symbol: {result.parsed.symbol or 'UNRESOLVED'}",
        f"Instrument: {instrument.kind.value if instrument else 'NOT_RESOLVED'}",
        f"Security ID: {instrument.security_id if instrument else 'NONE'}",
        f"Reasons: {reasons}",
        f"Duplicate check: {duplicate}",
        f"Pending gates: {pending}",
        "Trade ready: NO",
        "Broker action: NONE",
    ]
    return "\n".join(lines)


def format_daily_summary(summary: DailyAuditSummary) -> str:
    """Format counts derived only from durable audit events."""

    return "\n".join(
        [
            f"DAILY SUMMARY {summary.service_date.isoformat()} Asia/Kolkata",
            f"Signals received: {summary.signals_received}",
            f"Redeliveries ignored: {summary.redeliveries_ignored}",
            f"Passed core: {summary.passed_core}",
            f"Rejected: {summary.rejected}",
            f"Filtered: {summary.filtered}",
            f"Duplicates rejected: {summary.duplicates_rejected}",
            f"Unhealthy system checks: {summary.unhealthy_system_checks}",
            f"Real broker snapshots: {summary.broker_snapshots}",
            f"Operator feedback pending review: {summary.operator_feedback_pending}",
            "Simulated orders/fills/holdings: NEVER CREATED",
        ]
    )


def format_listener_error(*, execution_mode: str, error_code: str) -> str:
    """Format only a fixed exception class/code; never include exception text."""

    return "\n".join(
        [
            f"[{execution_mode}] TELEGRAM PROCESSING ERROR",
            f"Error code: {error_code}",
            "Broker action: NONE",
        ]
    )


def format_feedback_recorded(feedback: OperatorFeedback) -> str:
    """Confirm durable review status without echoing the operator's note."""

    return "\n".join(
        [
            "FEEDBACK RECORDED",
            f"Feedback ID: {feedback.id}",
            f"Signal: {feedback.source_group_id}:{feedback.source_telegram_message_id}",
            "Status: PENDING_REVIEW",
            "Rule change: NONE",
            "Message replay: NONE",
            "Broker action: NONE",
        ]
    )


def format_feedback_rejected(error_code: str) -> str:
    """Report only the stable rejection code; never echo command content."""

    return "\n".join(
        [
            "FEEDBACK REJECTED",
            f"Reason: {error_code}",
            "Rule change: NONE",
            "Message replay: NONE",
            "Broker action: NONE",
        ]
    )
