# Architecture

## Proposed single-VM flow

```text
Telegram client (one protected session)
  -> first durable SQLite receipt
  -> source and freshness gate
  -> parser/classifier
  -> read-only instrument validation
  -> local deterministic validation and later risk/funds gates
  -> optional AI review (advisory only)
  -> atomic SQLite option duplicate claim
  -> Yahoo equity quote validation where applicable
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

The current safe slice includes standalone deterministic price calculations but
ends before composing price, sizing, risk approval, or execution into a final
decision. The checker returns `PASSED_CORE` plus all currently known missing gates
and can never mark a signal trade-ready. Any later requirement adds a gate; this
list is never evidence that order submission is authorized.

`codexbot-listener` is the runnable observation composition. It loads the protected
configuration and fresh validated instrument cache, constructs the journal,
parser, checker, resolver, Telegram/feedback listener, and reporting, and refuses
LIVE mode while no executor exists.

## Component boundaries

- **Telegram adapter:** receives message events, reconnects safely, protects
  session state, provides group/sender/channel/forward audit metadata, and applies the
  approved restart/backlog policy once Udit chooses it. The service registers
  only `NewMessage`, uses finite reconnect attempts, and refuses interactive
  authorization at startup. Its default result path sends a plain-text,
  no-broker-action report to the configured log group and redacts errors to a
  fixed class name.
- **Parser:** conservatively recognizes the supplied compact stock-option BUY and
  two EXIT forms. It preserves the option request and price bounds while treating
  supplied advisory, negated, status/log, and no-caption media examples as
  non-actionable. It does not decide listing or index identity.
- **Rule engine:** deterministic checks with versioned reason codes. AI cannot
  override it.
- **TEST-safe processor:** composes receipt, parsing, an injected read-only
  resolver, checking, audit, and option deduplication. It has no broker dependency
  or order method. Only a candidate passing all currently implemented
  deterministic gates reaches the atomic claim.
- **Dhan instrument resolver:** loads the official detailed CSV from a local
  snapshot, validates its schema and eligible rows, and binds parsed contract
  fields to canonical security and underlying IDs. `OPTSTK` and `OPTIDX` decide
  instrument kind. It rejects no match, multiple matches, disabled buying,
  expiration, and cross-exchange equity ambiguity.
- **Instrument cache:** streams the public master into a bounded temporary file,
  validates before activation, names immutable snapshots by SHA-256, and switches
  a small pointer atomically under a file lock. Readers verify explicit age,
  byte count, checksum, path form, schema, and rows. Failed refreshes leave the
  prior pointer untouched; pruning retains the active and configured previous
  snapshots.
- **Dhan authentication and account health:** local TOTP generation, token
  identity/expiry validation, in-memory token handling, and documented read-only
  fund-limit verification. Strict order, trade, and position snapshots provide
  the broker side of later reconciliation. Their combined view is non-atomic and
  cannot itself authorize a retry or exit. A completed combined view is then
  persisted atomically in append-only observation tables. Margin remains planned.
- **Risk engine:** configured caps and portfolio-aware entry authorization. The
  pure layer applies order value, loss, exposure, position/trade counts, a 5% cash
  floor, 95% spendable funds, 2% daily halt, 1% position stop signal, and a
  three-position sector cap. Authorization requires current account/sector facts.
- **Sizing/routing:** isolated legacy fixed/budget calculations plus delivery-stage
  fixed-fractional sizing, with exact risk percentage and a selected 10-15%
  allocation cap. Pure routing selects CNC only within 95% of available cash and
  rejects otherwise; MTF is absent from the current route.
- **Execution/reconciliation:** LIVE-only order intents, duplicate-submission
  controls, state reconciliation, bounded partial-fill retry, and protection
  exits. Dhan correlation IDs are not assumed to provide idempotency.
- **Yahoo market data and pricing:** read-only NSE/BSE quote retrieval with price,
  market/receipt timestamps, prior minute/day closes, currency, and exchange.
  Policy enforces 3-second ages, 3%/5% anomalies, 24-hour daily data, and the
  explicit setup percentage. Option pricing applies the approved 4% ceiling.
- **Session/calendar policy:** pure IST phase decisions allow entries only
  09:16-15:10 on proven open days. Dynamic calendar failure remains closed unless
  an authenticated cautionary override follows validated local holiday checks.
- **NSE calendar cache:** bounded public download, complete CM/FO validation,
  atomic owner-only activation, explicit freshness, last-known-good preservation,
  and system-health integration. A coordinator composes cached official data,
  repository fallback, and append-only dated NSE override state. BSE is absent.
- **Journal:** SQLite WAL database containing immutable first receipts,
  append-only audit/control facts, and atomic option deduplication decisions.
  The runtime enforces service-user ownership, a non-symlinked owner-only parent,
  and owner-only database/WAL/SHM/backup files.
  Emergency stop defaults to engaged and is checked before a duplicate claim.
  Secrets and session material are excluded.
- **Reporting:** formats deterministic results without raw Telegram text and
  derives daily counts from immutable events using Asia/Kolkata date boundaries.
  Summary scheduling remains outside the formatter.
- **Operator feedback:** a log-group-only command authenticated by a separate
  operator-ID allowlist references an immutable source group/message identity.
  Accepted text is append-only and `PENDING_REVIEW`; acknowledgements never echo
  it. The component exposes no apply, replay, checker mutation, or broker API.
- **Admin CLI:** status, effective settings (redacted), orders, positions, errors,
  service control, emergency stop, and separately confirmed close action over SSH.
  The implemented status shows WAL, emergency stop, latest real-broker snapshot
  counts/time, and absent write executor; richer views remain planned.
- **Audit operations:** bounded `audit-history`, feedback history, and dated NSE
  calendar open/clear status are available over local SSH. Every override records
  the local OS actor and reason and cannot be updated or deleted.
- **VM boundary:** deployment assets verify GCE metadata for the approved
  `auditbot` TEST VM before mutation. Local systemd supervision, file logs, and
  SQLite health checks require no inbound port. Backup scheduling remains disabled
  until its storage destination and cost are approved.
- **Health coordinator:** composes Telegram, Dhan token/fund, SQLite integrity,
  emergency-stop, mode, and executor state into a redacted audit event. The
  executor is explicitly absent, so LIVE capability is always false. Scheduling
  policy remains outside this component; it only defines 08:00 Asia/Kolkata.

## Configuration boundary

One protected environment file supplies the single-instance runtime settings and
credentials. The loader requires service-user ownership, a regular non-symlink
file, and mode `0600` or stricter. It accepts only documented keys and performs no
shell expansion. TEST is the sole default; both segment flags, signal groups,
paths, instrument age, Telegram credentials/session path, and Dhan TOTP inputs are
explicit. Operator IDs are optional and blank disables feedback. Active equity
also requires Yahoo ages no greater than 3 seconds, the
percentage above market, and fixed-fractional values. Any active segment requires
all five positive absolute risk values. Secret
value objects render only `<redacted>` and require an explicit
adapter call to reveal their value.

## Telegram session boundary

The runtime accepts only a pre-authorized Telethon SQLite session in an owner-only
directory. The session and its journal/WAL/SHM sidecars must be regular,
non-symlink, service-user-owned files with no group/world access. Service startup
never requests an OTP or password. Message processing runs outside the async event
loop and catches per-message errors so one malformed event does not stop intake.
Health exposes connection, authorization, last receive/process times, and an
exception class name only; raw messages and exception text are excluded.

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
and deletes against receipt, audit, claim, decision, feedback, control, and broker
observation tables. Backup retention,
encryption, and recovery objectives remain deployment decisions.

## Failure posture

- Missing or stale facts fail closed for new entries.
- Absence of an explicit emergency-stop release blocks new entries. Engaging the
  stop again blocks candidates before they consume a duplicate window.
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
Rejected candidates create no claim and do not reserve or extend the window. A
corrected candidate inside 20 seconds can claim if no valid candidate claimed
first. Future deterministic validation stages must be composed before the claim
to preserve this rule.

## Instrument-master boundary

The resolver accepts only the official detailed header fields documented by Dhan.
For an omitted option month it uses the message's Asia/Kolkata calendar month and
year. An explicit month without a year is not assigned a year; all listed matches
for that month remain candidates, and more than one fails uniqueness. A contract
is marked listed for this offline gate only when the current master says
`BUY_SELL_INDICATOR=A` and its expiry date has not passed. Session status and
exchange controls remain later gates.

The detailed CSV's `TICK_SIZE` is stored as `tick_size_raw`. Current rows contain
values such as `5.0000` while displayed price limits use decimal rupees. The code
does not infer a paise/rupee conversion. The price function rounds down and cannot
exceed the 4% ceiling; wiring this raw field into it remains blocked until the raw
unit is verified.
