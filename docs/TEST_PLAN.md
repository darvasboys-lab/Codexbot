# Test plan

Tests prove specific capabilities; they never create a paper portfolio, simulated
holdings, or user-facing fake fills. Broker order writes remain forbidden until a
separately approved live test.

## 1. Offline core — current phase

- Type-check and lint all code.
- Verify `TEST` default and the single common mode model.
- Verify both configured group and authorized sender/channel IDs, forwarded
  origin authorization, the inclusive 60-second durable-receipt age boundary,
  and the fixed 2-second future-clock tolerance.
- Verify `SELL`, `EXIT`, and chatter cannot pass the BUY pipeline.
- Verify independent equity/F&O active flags.
- Verify classification comes from resolved instrument facts; reject unresolved,
  unlisted, unknown, mismatched, index, futures, missing option price, non-positive
  option price, and ambiguous contracts.
- Verify a passing core report remains `trade_ready = false` and exposes every
  missing gate.

- Verify WAL configuration, immutable first-receipt idempotency, append-only
  enforcement, exact duplicate boundaries, cross-group behavior, and a concurrent
  two-writer claim race.
- Verify emergency stop defaults engaged, stores append-only actor/reason history,
  is operable through the local CLI, and blocks before a duplicate claim.
- Verify Yahoo NSE/BSE symbol construction, timestamps, caller-defined quote age,
  and fail-closed malformed-response handling with an injected local transport.
- Verify the supplied CDSL option range uses 35 as its upper bound; Telegram
  SL/target prose cannot modify it; SENSEX parses as an option candidate and is
  rejected only by verified index facts; supplied EXIT forms remain non-BUY; and
  analysis, watchlist, future intent, status/log, negated BUY, invalid ranges,
  and captionless media all fail closed.
- Verify the processing composition persists first receipt, audits parsing and
  the final decision, requires canonical underlying identity, and creates no
  duplicate claim for unauthorized, stale, unlisted, ambiguous-contract, or
  index candidates. Verify a correction after rejection can claim and that a
  valid claim blocks another strike, price, and CE/PE on the same underlying.
- Verify official detailed-master schema validation, malformed eligible-row
  failure, CDSL canonical option resolution, omitted/explicit month behavior,
  uniqueness rejection, disabled/expired listing facts, verified SENSEX index
  classification, and NSE/BSE equity ambiguity with an explicit exchange filter.
- Verify bounded download, validate-before-activate, last-known-good preservation,
  stale/future rejection, size/checksum corruption detection, restrictive file
  modes, immutable hash names, and bounded snapshot pruning. Smoke-test the real
  refresh/status CLI against the public master without credentials.
- Verify strict environment syntax, known/duplicate keys, TEST default, explicit
  segment flags and IDs, positive freshness, invalid modes, owner-only file mode,
  symlink rejection, secret redaction, and checker-policy construction.
- Verify Telegram envelope extraction, marked forwarded-channel IDs, hidden
  origins, missing sender identity, session file/directory permission checks,
  sidecar hardening, unauthorized-session refusal, authorized lifecycle cleanup,
  and NewMessage-only registration with a fake client.
- Verify TOTP against an RFC vector, naive IST token expiry, response client ID,
  token expiry, secret-free HTTP errors, strict fund-limit fields, and that the
  Dhan adapter exposes no write endpoint.
- Verify strict order/trade/position list shape, account identity, quantities,
  positive trade prices, signed P&L, position arithmetic, blank documented order
  symbols, and the explicitly non-atomic combined reconciliation snapshot.
- Verify inclusive Yahoo market/local age limits, 2-second future tolerance, INR,
  setup percentage calculation, option 4% ceiling, and floor-to-tick behavior.

Current result: 172 tests pass. Ruff and strict mypy pass.

## 2. Remaining parser and reference-rule tests

The supplied option, EXIT, and non-actionable examples are implemented as exact
fixtures. Equity BUY, SELL, expiry-omitted non-index stock-option, and additional
malformed examples remain needed before those forms are expanded. Confirm
edits/deletions do not reprocess a completed message. Fuzz malformed text and
prove it cannot silently become a BUY.

## 3. Remaining durable journal and restart tests

- verify event ordering under sustained concurrent group arrivals;
- restart the process and recover every incomplete state without creating orders;
- test production file ownership, disk-full behavior, scheduled encrypted backup,
  and recovery timing; offline integrity, backup, and restore tests are implemented;
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
