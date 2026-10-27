# Test plan

Tests prove specific capabilities; they never create a paper portfolio, simulated
holdings, or user-facing fake fills. Broker order writes remain forbidden until a
separately approved live test.

## 1. Offline core — current phase

- Type-check and lint all code.
- Verify `TEST` default and the single common mode model.
- Verify configured group, explicit source verification, and the inclusive
  60-second age boundary with an explicit future-clock tolerance.
- Verify `SELL`, `EXIT`, and chatter cannot pass the BUY pipeline.
- Verify independent equity/F&O active flags.
- Verify classification comes from resolved instrument facts; reject unresolved,
  unlisted, unknown, mismatched, index, futures, missing option price, non-positive
  option price, and ambiguous contracts.
- Verify a passing core report remains `trade_ready = false` and exposes every
  missing gate.

Current result: 33 tests pass. Ruff and strict mypy pass.

## 2. Parser and reference-rule tests

Blocked until Udit supplies `darvas_script-main.zip` and redacted real messages.
For each approved format, keep exact positive and negative examples. Confirm
edits/deletions do not reprocess a completed message. Fuzz malformed text and prove
it cannot silently become a BUY.

## 3. Durable journal and restart tests

After the persistence decision:

- verify receipt-before-processing and append-only audit behavior;
- verify uniqueness and event ordering under concurrent group arrivals;
- restart the process and recover every incomplete state without creating orders;
- test backup, integrity check, restore, file ownership, and disk-full behavior;
- verify logs and database records redact credentials/session data; and
- verify there are no runtime tables or services for paper orders, fake fills,
  simulated holdings, or a virtual portfolio.

## 4. Telegram test-group verification in TEST

With Udit present and credentials supplied through the protected runtime setup:

- authenticate one Telegram account and verify only configured group/sender
  identities;
- send the approved equity, option, SELL, EXIT, chatter, duplicate, stale, and
  malformed examples;
- disconnect/reconnect and restart to test session protection and backlog policy;
- verify log-group feedback authorization and immutable audit entries; and
- prove the running TEST composition has no broker order-submission capability.

## 5. Dhan read-only verification

After regulatory guidance and credentials are available, call only documented
read endpoints:

- authentication/expiry health;
- instrument master and exact contract resolution;
- timestamped quotes/live feed and stale-data behavior;
- funds, margin/MTF eligibility, market status, orders, trades, and positions;
- rate-limit, timeout, malformed-response, and token-expiry handling; and
- restart reconciliation against real account state without modifying it.

No placement, modification, or cancellation request belongs in this phase.

## 6. Extended TEST observation

Run during representative cash and F&O sessions. Udit compares instruments,
quotes, sizes, rejections, risk decisions, health alerts, and daily summaries with
independent broker data. Resolve every unexplained difference before deployment.

## 7. New-VM deployment test — explicit approval required

After Udit supplies the GCE project and approves the plan, verify hardened access,
static egress design, service restart, secrets/session permissions, backups and
restore, clock sync, exchange calendar updates, log retention, monitoring, and
rollback. Deployment remains in TEST.

## 8. Live test — separate explicit approval required

Immediately before one live test, document and obtain approval for the exact
instrument, side, quantity, limit, maximum loss, time window, operator presence,
cancel/reconcile steps, protection plan, and emergency exit. Recheck Dhan and
regulatory eligibility. AMO is a later phase.
