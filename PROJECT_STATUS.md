# Project status

Status date: 2026-10-28 (Asia/Kolkata)

## Implemented

- Python 3.12 package baseline and GitHub CI definition.
- Typed, deterministic, side-effect-free signal-checking core.
- Common execution-mode model with safe `TEST` default and separate equity/F&O
  active flags.
- Strict configured-group authentication with sender/forward-origin audit metadata,
  first-durable-receipt freshness with 2-second future skew, action, segment,
  instrument resolution/listing, verified instrument-kind, index, futures, and
  basic stock-option gates.
- SQLite journal in WAL mode with durable idempotent signal receipts, append-only
  audit/receipt/deduplication tables, and atomic 20-second stock-option claims.
- Enforced service-user ownership and owner-only SQLite directory, database,
  WAL/SHM sidecar, and backup permissions with symlink/path refusal.
- Append-only emergency-stop controls that default to engaged, audit actor/reason,
  block candidates before deduplication, and expose local SSH administration.
- Aggressive stock-option duplicate identity based on canonical underlying only;
  strike, expiry, price, and CE/PE do not distinguish signals in the window.
- Database integrity, consistent backup, and temporary restore-test functions and
  CLI commands.
- Read-only Yahoo Finance NSE/BSE quote adapter with market/receipt timestamps,
  previous completed one-minute close, previous-day close, and strict response
  validation. Pricing enforces 3-second market/local age, 3% minute and 5% daily
  anomaly limits, plus a 24-hour daily-data freshness primitive.
- Fail-closed equity price policy still requires the setup percentage, plus the
  approved option `1.04` ceiling rounded down to a verified price-unit tick.
- Conservative Telegram parser for the supplied compact option BUY and two EXIT
  forms. It preserves price bounds, month, strike, and CE/PE; ignores Telegram
  SL/target prose; and fails closed for the supplied analysis, watchlist,
  future-intent, status/log, negated-BUY, and chart-only examples.
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
  active flags/groups/paths/freshness, owner/mode/symlink checks,
  typed Telegram and Dhan TOTP credentials, and redacted secret representations.
- Telethon NewMessage-only listener for one pre-authorized user session, with
  configured-chat subscription, sender/channel and forwarded-origin extraction,
  hidden-origin rejection support, finite reconnect settings, protected session
  files/sidecars, worker-thread processing, and health/error state.
- Attended `codexbot-telegram-auth` session creation that reads the protected
  environment, disconnects after authorization, and reapplies owner-only session
  permissions; unattended listener startup still refuses interactive login.
- Default plain-text log-group result/error reporting without raw message or
  exception text, explicit no-broker-action labeling, and audit-derived
  Asia/Kolkata daily summary counts.
- Authenticated log-group feedback commands tied to existing signal receipts,
  with separate operator IDs, forwarded-command rejection, idempotent append-only
  `PENDING_REVIEW` storage, safe acknowledgements, daily counts, and bounded SSH
  history. There is no rule-apply or signal-replay path.
- `PROGRESS.md` milestone/decision dashboard separating offline implementation,
  credentialed TEST evidence, deployment, and LIVE authorization.
- Secret-safe Dhan TOTP generation, access-token response identity/expiry checks,
  and read-only fund-limit health verification. Tokens remain in memory; the
  broker module contains no order write endpoint.
- Strict read-only Dhan order-book, trade-book, and position snapshots for future
  restart/uncertain-state reconciliation, including partial quantities, prices,
  identity checks, and position quantity consistency.
- Atomic append-only persistence for real Dhan reconciliation snapshots and their
  normalized order/trade/position observations, plus a secret-free local status
  summary. No TEST path invents these rows.
- Secret-free system health composition for Telegram, Dhan token/funds, SQLite
  integrity, emergency-stop state, and absent executor; fixed 08:00
  Asia/Kolkata schedule calculation and append-only health audit.
- Mandatory typed setup for all five requested absolute risk limits whenever a
  segment is active, plus a positive starting-capital basis and pure evaluation
  for those limits, the 5% cash buffer,
  2% daily-capital halt, 1% per-position hard-stop signal, and three-position
  sector cap. Current account/sector evidence is required to authorize entry.
- Pure fixed-share/equity-budget and fixed-lot/option-budget sizing primitives,
  with whole-unit flooring and explicit rejection below one share or lot.
- Protected setup still requires an explicit `FIXED` or `BUDGET` lot selection for
  active F&O; fixed values must be positive whole units.
- Delivery equity now additionally requires explicit fixed-fractional risk and
  allocation percentages; the allocation must be selected from 10% through 15%.
  Pure sizing floors to whole shares/lots and applies both loss-at-stop and capital
  allocation ceilings.
- Pure delivery-only routing accepts `CNC` only within 95% of available cash and
  rejects otherwise; MTF is deferred. Pure lifecycle policy records 3-second
  connect, 5-second read, 45-second LIMIT fill, reconcile-before-retry, one retry,
  and no market conversion.
- Asia/Kolkata session classification implements initialization, opening guard,
  normal entry, square-off/no-entry, and 15:35 reconciliation/log-rotation phases.
  Calendar fallback is fail-closed with authenticated manual-open override support;
  the official NSE 2026 CM/FO holiday snapshot is stored as a small JSON file.
- Bounded official NSE holiday downloading and atomic owner-only cache with strict
  CM/FO schema/date/year/source/freshness validation, last-known-good preservation,
  CLI maintenance, calendar-aware system health, and a public-data smoke test.
- Attended TEST accepts Dhan instrument and NSE calendar caches for at most
  86,400 seconds; production refresh and missed-run policy remain open.
- Append-only dated NSE manual-open/clear history with local OS actor/reason,
  special-session precedence, terminal status, and filtered audit views.
- Callable Telegram delivery for audit-derived daily summaries. Automated timing
  remains blocked on missed-run/retry notification policy.
- Structured reason codes and explicit remaining-gate list.
- Structural safety boundary: the package contains no broker write method, order
  command/intent, simulated fill/holding model, or simulator; `trade_ready` is
  always false. Broker order/trade/position types are read-only observations.
- Runnable `codexbot-listener` TEST composition that loads protected settings and
  a fresh validated instrument snapshot, builds the complete observation graph,
  and refuses `LIVE` with `LIVE_EXECUTOR_ABSENT`. A hardened review-only systemd
  example and preflight checklist are present but have not been deployed.
- Runnable `codexbot-preflight` shared with listener startup that returns a
  secret-free local readiness record and fails closed on LIVE, unsafe session,
  stale caches, wrong calendar year, or SQLite integrity/path failures. The local
  health timer runs this same check as the service user.
- Target-locked read-only `auditbot` inspection, five-minute local health-check,
  14-rotation application-log, and seven-day local-backup systemd templates. The
  current managed workspace has no GCP identity or SSH/TCP connection, so none
  has been run or installed on the VM.
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
- Interactive Telegram session setup and live credentialed listener/feedback
  verification with actual group and operator IDs.
- Read-only Dhan margin connectivity. Token, fund, order, trade, and position
  readers are implemented but await credentialed verification.
- Journal retention/backup scheduling and comparison/action policy for restart
  reconciliation; broker observations are durable.
- Composition of pricing, sizing, sector facts, funds, risk, delivery routing,
  pending-entry cancellation, execution, partial-fill/retry, and protection logic.
- Official BSE calendar data, production NSE cache age/refresh timing, missed/late
  08:00 behavior, health retries, and automated notification/summary scheduling.
- SSH terminal dashboard, Google Cloud Logging, Docker, and new GCE deployment.
- Any `LIVE` order path or live test.

## Evidence and limitations

- `darvas_script-main.zip` was reviewed by SHA-256; no source file or unapproved
  rule was reused.
- No Dhan or Telegram credential has been requested, stored, or tested. Dhan
  authentication and fund parsing use injected transports in automated tests.
- `.env.example` contains names and blank credential fields only; populated
  runtime settings remain excluded from Git.
- Yahoo integration is covered by injected-response unit tests. A read-only
  `RELIANCE.NS` request returned a timestamped INR response on 2026-10-27; it was
  a connectivity smoke check before the new anomaly fields and is not trading
  evidence. The approved 3-second rule may reject Yahoo data in practice.
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
