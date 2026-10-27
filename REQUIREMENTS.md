# Requirements

Status date: 2026-10-27 (Asia/Kolkata)

This document separates approved rules from decisions that still require Udit's
answer. Code must not turn an open decision into an implicit default.

## Approved scope and safety rules

- One installation, operator (Udit), Telegram account, Dhan account, and new GCE
  VM. No multi-user architecture.
- One common `TEST`/`LIVE` switch, default `TEST`. Equity and F&O each have an
  independent active/inactive setting.
- `TEST` checks and reports real signals. It places no order and creates no fake
  fill, simulated order, holding, or position. Paper trading is forbidden.
- Production deployment and a live order test each need explicit approval.
- Monitor multiple configured Telegram groups, including a test group. Settings
  live in one protected environment file; restart-to-apply is acceptable.
- Process only `BUY` initially. Classify and log `SELL`/`EXIT` without execution.
  Ignore edits/deletions after processing.
- Require both a configured group ID and an authorized sender/channel ID.
  Forwarded messages also require an explicitly authorized original-source ID;
  hidden or unauthorized origins are rejected.
- Measure the inclusive 60-second age limit at the first durable receipt and
  allow exactly 2 seconds of future clock skew.
- For stock options, use a 20-second cross-group duplicate window anchored to
  first durable receipt. The atomic key is canonical underlying ID + `BUY` +
  stock-option family + first durable receipt timestamp. Ignore strike, expiry,
  price, and CE/PE. A signal exactly 20 seconds after an accepted claim is a
  duplicate; re-entry after 20 seconds is permitted.
- Use SQLite in WAL mode on the single VM. Keep signal receipts, duplicate claims
  and decisions, and audit events append-only. Use atomic transactions for
  duplicate claims and maintain tested integrity, backup, and restore commands.
- Deterministic local rules have final authority. AI may recheck potential
  rejections when available, but cannot override deterministic validation or
  change rules without approval.
- Support NSE/BSE equities. Equity entry uses a validated current price plus a
  setup percentage and a `LIMIT` order. Product is delivery or MTF, selected in
  setup.
- Use Yahoo Finance for equity market prices for now. The adapter must retain the
  Yahoo market timestamp and local receipt timestamp and fail closed on missing,
  malformed, non-positive, or non-unique responses. No other market-data API is
  requested at this stage.
- Support stock-option `BUY` only. Require a stated price. The upper entry ceiling
  is that price multiplied by `1.04`; tick handling must never exceed the ceiling.
  Use current calendar month when expiry is omitted and reject unless exactly one
  listed contract matches. No option writing or index options.
- Stop loss and target are setup values, with the previously chosen defaults of
  3% each based on actual fills. Telegram SL/target text is ignored. Prevent
  over-exits and reconcile state on restart.
- Risk setup includes maximum order amount, minimum trade funds, daily loss,
  total exposure, open positions, and daily trade count.
- Emergency stop blocks new entries, cancels pending entries, continues managing
  filled positions, and exposes a separate explicit close action.
- Reconcile an uncertain submission outcome before any retry. On partial fill
  after timeout, manage actual fills and make at most one retry for the unfilled
  quantity only after confirming the original remainder is cancelled.
- Log recognized, rejected/filtered messages and reasons, validations, orders,
  errors, and a daily summary. Preserve an authenticated, immutable audit trail.
- Protect credentials and Telegram session data. Never commit either.
- Exclude Notion, Google Sheets, Kite, Railway, other brokers, and changes to the
  existing deployment.

## Open decisions — implementation blocked where affected

1. **Reference rules and examples:** `darvas_script-main.zip` has been reviewed;
   no code was copied. Confirm the candidate formats in
   `docs/REFERENCE_REVIEW.md` and provide real, redacted messages before parsing
   rules are implemented.
2. **Equity quote policy:** supply the maximum accepted age for Yahoo's market
   timestamp, the maximum local response age, and the percentage above market.
   Yahoo officially describes this data as informational and lists BSE as delayed
   by 15 minutes; these limits must be explicit before quote-based entry validation
   can pass.
3. **Option tick rounding:** approve the exact rule. A safe candidate is to round
   down to the nearest valid tick so the price never exceeds `signal × 1.04`.
4. **Sizing priority:** choose fixed shares/lots versus budget when both are
   configured; decide whether insufficient funds always rejects or may reduce
   quantity; define the role of minimum-trade-funds.
5. **Equity product:** choose delivery or MTF and define Dhan MTF
   eligibility/margin checks after broker support is verified.
6. **Futures:** confirm whether stock futures are in scope. “OK” is not treated as
   approval. Futures remain blocked.
7. **Timeouts:** set equity initial timeout, option initial timeout, retry timeout,
   and retry-price rule.
8. **Mode changes:** define handling of pending entries, exits, and open
    positions when changing `TEST`/`LIVE`.
9. **End of day:** define each product's pending-order and open-position policy.
10. **Restart gaps:** decide whether missed Telegram messages are logged only or
    may be evaluated; old messages must never become automatic trades.
11. **Calendar and 08:00 health check:** use weekdays or the official exchange
    trading calendar; define late/missed checks, token-refresh failure, service
    failure, and notification retry semantics. Automatic reauthentication is not
    assumed.
12. **AI review:** choose which filtered chatter/rejections invoke AI, provider,
    data policy, cost ceiling, latency deadline, timeout behavior, and authorized
    feedback commands.
13. **Risk and setup values:** provide the actual risk limits, active segments,
    group IDs, log destination, optional private broker-ack destination, equity
    percentage, sizing values, and SL/target confirmation.
14. **Infrastructure:** provide the GCP project, region/zone, VM budget/size,
    backup/retention needs, and logging budget when VM work begins.
15. **Audit operations:** choose production retention, backup schedule/location,
    encryption, recovery target, and restore-drill schedule before VM setup.
16. **Names and display:** confirm whether “Sapphire Bot” from the screenshot is
    the product name or only a visual reference.

## Supplied dashboard references

The supplied setup image is a visual reference. Its “Paper Trading” control
conflicts with the approved requirements and will not be copied. A future setup
screen should instead show the single `TEST`/`LIVE` switch, explicit active flags,
and warnings that `TEST` does not simulate trades. The supplied Telegram log
example informs readability only; actual fields and redaction still need approval.
