# Architecture

## Proposed single-VM flow

```text
Telegram client (one protected session)
  -> source and freshness gate
  -> parser/classifier
  -> local deterministic validation
  -> optional AI review (advisory only)
  -> duplicate gate
  -> read-only instrument and quote validation
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

The first code slice ends after local deterministic validation. It returns
`PASSED_CORE` plus all currently known missing gates and can never mark a signal
trade-ready. Any requirement found later adds a gate; this list is never evidence
that order submission is authorized.

## Component boundaries

- **Telegram adapter:** receives message events, reconnects safely, protects
  session state, provides trusted source metadata, and applies the approved
  restart/backlog policy once Udit chooses it.
- **Parser:** turns approved message formats into normalized signals. It will be
  implemented after archive review and real examples.
- **Rule engine:** deterministic checks with versioned reason codes. AI cannot
  override it.
- **Dhan read model:** instruments, quotes, funds/margins, orders, trades, and
  positions from documented read-only interfaces. The instrument resolver must
  prove that the normalized symbol/contract fields bind to the returned canonical
  security ID; this early checker accepts resolver facts but cannot prove that
  binding itself.
- **Risk engine:** configured caps and portfolio-aware entry authorization.
- **Execution/reconciliation:** LIVE-only order intents, duplicate-submission
  controls, state reconciliation, bounded partial-fill retry, and protection
  exits. Dhan correlation IDs are not assumed to provide idempotency.
- **Journal:** append-only facts and decisions used for restart recovery and
  audit. Secrets and session material are excluded.
- **Admin CLI:** status, effective settings (redacted), orders, positions, errors,
  service control, emergency stop, and separately confirmed close action over SSH.

## Persistence cost decision

For one process on one VM, SQLite in WAL mode is the recommended starting point.
It has no separate service fee, network hop, database credentials, or database
server to patch. The costs are disciplined backups, one-writer constraints, and
careful recovery testing. Those limits fit the stated single-account workload if
all writes go through one journal owner.

Managed PostgreSQL adds monthly instance/storage/backup/network cost and more
credentials, but gives stronger remote availability, concurrent writers, and
managed point-in-time recovery. Those benefits are useful for multiple services
or high availability, neither of which is currently requested.

No durable adapter is implemented until Udit approves the choice and backup
expectations. The domain layer will depend on a journal interface so migration is
possible without changing trading rules.

## Failure posture

- Missing or stale facts fail closed for new entries.
- Telegram reconnect does not automatically trade a backlog.
- Dhan authentication or health failure blocks new LIVE entries and alerts the
  log group; exact retry/escalation semantics remain open.
- Ambiguous instruments, contracts, submission outcomes, or position state block
  retry until reconciled.
- Filled exposure continues to be managed during emergency stop, subject to the
  approved mode-change and end-of-day policies.

## Freshness clock boundary

The core accepts an explicit `evaluated_at` timestamp so tests and future adapters
cannot read an uncontrolled global clock. Production composition remains blocked
until Udit chooses whether the 60-second age is measured at first bot receipt or
at processing start, and supplies the permitted future-clock tolerance.
