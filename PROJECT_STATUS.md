# Project status

Status date: 2026-10-27 (Asia/Kolkata)

## Implemented

- Python 3.12 package baseline and GitHub CI definition.
- Typed, deterministic, side-effect-free signal-checking core.
- Common execution-mode model with safe `TEST` default and separate equity/F&O
  active flags.
- Strict group plus sender/channel authentication, forwarded-origin checks,
  first-durable-receipt freshness with 2-second future skew, action, segment,
  instrument resolution/listing, verified instrument-kind, index, futures, and
  basic stock-option gates.
- SQLite journal in WAL mode with durable idempotent signal receipts, append-only
  audit/receipt/deduplication tables, and atomic 20-second stock-option claims.
- Aggressive stock-option duplicate identity based on canonical underlying only;
  strike, expiry, price, and CE/PE do not distinguish signals in the window.
- Database integrity, consistent backup, and temporary restore-test functions and
  CLI commands.
- Read-only Yahoo Finance NSE/BSE equity quote adapter with market and receipt
  timestamps, strict response validation, and caller-supplied freshness limits.
- Conservative Telegram parser for the supplied compact option BUY and two EXIT
  forms. It preserves price bounds, month, strike, and CE/PE; ignores Telegram
  SL/target prose; and fails closed for the supplied analysis, watchlist,
  future-intent, status/log, negated-BUY, and chart-only examples.
- TEST-safe processing composition for durable receipt, parsing, deterministic
  checking, append-only audit, and atomic option deduplication. Rejected source,
  freshness, index, listing, price, identity, and ambiguity cases create no
  duplicate claim; a later corrected candidate can claim immediately.
- Structured reason codes and explicit remaining-gate list.
- Structural safety boundary: the package contains no broker client, order model,
  fill model, holdings model, or simulator; `trade_ready` is always false.
- Automated unit tests for implemented behavior and safety boundaries.
- Completed reference-archive review with no source reuse; candidate formats,
  conflicts, and rejected legacy behavior are documented.

## Verified in this review

- Current official Dhan API documentation and official SEBI/NSE retail-algo
  materials were reviewed without credentials or broker writes. The resulting
  LIVE blocker and open broker questions are recorded in `DHAN_API.md`.
- The locked local development environment installs successfully. Ruff, strict
  mypy, and the full unit suite pass; exact results are kept in the test plan.

## Planned, blocked by inputs or approval

- Equity BUY, SELL, expiry-omitted non-index stock-option, and additional
  malformed parser examples.
- Read-only instrument-resolver adapter feeding canonical facts into the
  implemented processor.
- Telegram listener/session handling and authenticated operator feedback.
- Read-only Dhan instrument, funds, margin, order, trade, and position
  connectivity.
- Journal orchestration, retention/backup scheduling, and restart reconciliation.
- Pricing, sizing, funds, risk, emergency-stop, execution, partial-fill/retry, and
  protection logic.
- 08:00 Asia/Kolkata health/token workflow and exchange calendar.
- SSH terminal dashboard, Google Cloud Logging, Docker, and new GCE deployment.
- Any `LIVE` order path or live test.

## Evidence and limitations

- `darvas_script-main.zip` was reviewed by SHA-256; no source file or unapproved
  rule was reused.
- No Dhan or Telegram credential has been requested, stored, or tested.
- Yahoo integration is covered by injected-response unit tests. A read-only
  `RELIANCE.NS` request returned a timestamped INR response on 2026-10-27; it was
  a connectivity smoke check, not trading evidence. Quote-age limits remain unset.
- Official BSE calendar and exchange-specific algo materials have not yet been
  verified; BSE remains blocked beyond offline core work.
- No broker connectivity, VM deployment, order submission, or production
  readiness is claimed.
