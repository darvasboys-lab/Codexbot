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
- Fail-closed same-group/message-ID redelivery handling: a replay is audited but never re-parsed, re-resolved, or re-evaluated for a duplicate claim, including after a restart or a prior rejection. First receipt timestamps remain immutable.
- TEST-safe processing composition for durable receipt, parsing, deterministic
  checking, append-only audit, and atomic option deduplication. Rejected source,
  freshness, index, listing, price, identity, and ambiguity cases create no
  duplicate claim; a later corrected candidate can claim immediately.
- Read-only Dhan detailed-instrument-master resolver with strict schema/row
  validation, NSE/BSE filters, equity ambiguity rejection, current-month handling,
  stock-option versus index classification, unique-contract resolution, and
  canonical security/underlying IDs. Lot, expiry, exchange, and raw Dhan tick
  values are retained without guessing tick units.
- Bounded public instrument-master downloader and atomic cache with file locking,
  schema validation before activation, SHA-256 identity, restrictive permissions,
  age/size/checksum verification, last-known-good preservation, and pruning CLI.
- Strict one-file runtime configuration with TEST-only mode default, explicit
  active flags/groups/source IDs/paths/freshness, owner/mode/symlink checks,
  typed Telegram and Dhan TOTP credentials, and redacted secret representations.
- Telethon NewMessage-only listener for one pre-authorized user session, with
  configured-chat subscription, sender/channel and forwarded-origin extraction,
  hidden-origin rejection support, finite reconnect settings, protected session
  files/sidecars, worker-thread processing, and health/error state.
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
- Production instrument refresh schedule and maximum accepted snapshot age.
- Interactive Telegram session setup and live credentialed listener verification;
  authenticated operator feedback remains planned.
- Read-only Dhan funds, margin, order, trade, and position connectivity.
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
- `.env.example` contains names and blank credential fields only; populated
  runtime settings remain excluded from Git.
- Yahoo integration is covered by injected-response unit tests. A read-only
  `RELIANCE.NS` request returned a timestamped INR response on 2026-10-27; it was
  a connectivity smoke check, not trading evidence. Quote-age limits remain unset.
- The resolver loaded Dhan's 2026-10-27 public detailed master. It uniquely
  resolved the supplied CDSL October 1400 CE to NSE security `62508`, underlying
  `21174`, lot `475`, and classified the supplied SENSEX option as a BSE index.
- The real cache CLI downloaded and validated the 36,835,408-byte public master
  on 2026-10-27 with SHA-256
  `8f080f9de30960b129974e3cc26dcd066b00957935fb31d3cc9d7a812ec54b5f`.
- Official BSE calendar and exchange-specific algo materials have not yet been
  verified; BSE remains blocked beyond offline core work.
- No broker connectivity, VM deployment, order submission, or production
  readiness is claimed.
