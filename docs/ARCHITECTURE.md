# Architecture

## Proposed single-VM flow

```text
Telegram client (one protected session)
  -> source and freshness gate
  -> parser/classifier
  -> local deterministic validation
  -> optional AI review (advisory only)
  -> atomic SQLite option duplicate claim
  -> read-only instrument validation and Yahoo equity quote validation
  -> sizing, funds/margin, and risk gates
  -> TEST report OR LIVE execution gate
  -> Dhan order state reconciliation
  -> fill-based protection management
  -> audit journal and log-group notifications
```

The live execution adapter will be absent from the TEST processing path rather
than disabled by a loose Boolean inside order-submission code. The emergency stop
will be a durable gate checked immediately before every new entry. Submission will
use a durable intent/correlation record so a timeout triggers reconciliation, not
blind retry.

The current safe slice ends before pricing an entry, sizing, risk approval, or
execution. The deterministic checker returns `PASSED_CORE` plus all currently
known missing gates and can never mark a signal trade-ready. Any requirement found
later adds a gate; this list is never evidence that order submission is authorized.

## Component boundaries

- **Telegram adapter:** receives message events, reconnects safely, protects
  session state, provides trusted source metadata, and applies the approved
  restart/backlog policy once Udit chooses it.
- **Parser:** turns approved message formats into normalized signals. It will be
  implemented after archive review and real examples.
- **Rule engine:** deterministic checks with versioned reason codes. AI cannot
  override it.
- **Dhan read model:** instruments, funds/margins, orders, trades, and positions
  from documented read-only interfaces. The instrument resolver must
  prove that the normalized symbol/contract fields bind to the returned canonical
  security ID; this early checker accepts resolver facts but cannot prove that
  binding itself.
- **Risk engine:** configured caps and portfolio-aware entry authorization.
- **Execution/reconciliation:** LIVE-only order intents, duplicate-submission
  controls, state reconciliation, bounded partial-fill retry, and protection
  exits. Dhan correlation IDs are not assumed to provide idempotency.
- **Yahoo market data:** read-only NSE/BSE equity quote retrieval. Each accepted
  response contains a positive price, Yahoo market timestamp, local receipt
  timestamp, currency, and exchange. Final quote-age limits remain blocked.
- **Journal:** SQLite WAL database containing immutable first receipts,
  append-only audit facts, and atomic option deduplication decisions. Secrets and
  session material are excluded.
- **Admin CLI:** status, effective settings (redacted), orders, positions, errors,
  service control, emergency stop, and separately confirmed close action over SSH.

## Persistence decision

For one process on one VM, SQLite in WAL mode is approved and implemented.
It has no separate service fee, network hop, database credentials, or database
server to patch. The costs are disciplined backups, one-writer constraints, and
careful recovery testing. Those limits fit the stated single-account workload if
all writes go through one journal owner.

Managed PostgreSQL adds monthly instance/storage/backup/network cost and more
credentials, but gives stronger remote availability, concurrent writers, and
managed point-in-time recovery. Those benefits are useful for multiple services
or high availability, neither of which is currently requested.

Every connection enables foreign keys, a bounded busy timeout, WAL mode, and
`synchronous=NORMAL`. First receipt uses `(group ID, Telegram message ID)` as its
idempotent identity. Duplicate checks run in `BEGIN IMMEDIATE`, so concurrent
groups cannot both accept the same option key. Database triggers reject updates
and deletes against receipt, audit, claim, and decision tables. Backup retention,
encryption, and recovery objectives remain deployment decisions.

## Failure posture

- Missing or stale facts fail closed for new entries.
- Telegram reconnect does not automatically trade a backlog.
- Dhan authentication or health failure blocks new LIVE entries and alerts the
  log group; exact retry/escalation semantics remain open.
- Ambiguous instruments, contracts, submission outcomes, or position state block
  retry until reconciled.
- Filled exposure continues to be managed during emergency stop, subject to the
  approved mode-change and end-of-day policies.

## Freshness and duplicate clock boundaries

The journal captures `first_durable_received_at` inside the transaction that first
persists a Telegram message identity. Redelivery returns the original timestamp.
The checker compares Telegram `sent_at` with that stored value, accepts age from
-2 through +60 seconds inclusive, and does not read the wall clock itself.

An accepted stock-option claim blocks the same canonical underlying + `BUY` +
stock-option-family key for 20 seconds inclusive. Strike, expiry, price, and CE/PE
are not stored in the key. Only accepted claims start windows, so rejected
duplicates do not extend a window. `BEGIN IMMEDIATE` serializes the query and
insert, while an exact key-plus-timestamp unique constraint adds a final guard.
