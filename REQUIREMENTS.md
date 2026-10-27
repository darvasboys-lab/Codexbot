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
- Validate configured source, source identity, message age of no more than 60
  seconds, instrument identity/listing, and sizing. Reject indexes.
- Use a 20-second cross-group duplicate window once its exact identity and clock
  semantics are approved. Re-entry after the window is permitted.
- Deterministic local rules have final authority. AI may recheck potential
  rejections when available, but cannot override deterministic validation or
  change rules without approval.
- Support NSE/BSE equities. Equity entry uses a validated current price plus a
  setup percentage and a `LIMIT` order. Product is delivery or MTF, selected in
  setup.
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

1. **Reference rules and examples:** provide `darvas_script-main.zip` and real,
   redacted signal examples before parsing rules are implemented or reused.
2. **Source identity and clock skew:** define whether an allowed group/channel
   alone is trusted, or whether permitted sender/admin IDs must also match; supply
   the permitted future timestamp tolerance for the 60-second freshness check;
   choose whether age is measured at first bot receipt or when processing starts.
3. **Duplicate identity and clock:** choose the exact key across cash symbols,
   option strikes and expiries; define whether the 20 seconds starts at Telegram
   send time, first receipt time, or durable-processing time and how restart races
   are handled.
4. **Equity quote:** choose the permitted Dhan price endpoint/feed and maximum
   quote age. Supply the percentage above market.
5. **Option tick rounding:** approve the exact rule. A safe candidate is to round
   down to the nearest valid tick so the price never exceeds `signal × 1.04`.
6. **Sizing priority:** choose fixed shares/lots versus budget when both are
   configured; decide whether insufficient funds always rejects or may reduce
   quantity; define the role of minimum-trade-funds.
7. **Equity product:** choose delivery or MTF and define Dhan MTF
   eligibility/margin checks after broker support is verified.
8. **Futures:** confirm whether stock futures are in scope. “OK” is not treated as
   approval. Futures remain blocked.
9. **Timeouts:** set equity initial timeout, option initial timeout, retry timeout,
   and retry-price rule.
10. **Mode changes:** define handling of pending entries, exits, and open
    positions when changing `TEST`/`LIVE`.
11. **End of day:** define each product's pending-order and open-position policy.
12. **Restart gaps:** decide whether missed Telegram messages are logged only or
    may be evaluated; old messages must never become automatic trades.
13. **Calendar and 08:00 health check:** use weekdays or the official exchange
    trading calendar; define late/missed checks, token-refresh failure, service
    failure, and notification retry semantics. Automatic reauthentication is not
    assumed.
14. **AI review:** choose which filtered chatter/rejections invoke AI, provider,
    data policy, cost ceiling, latency deadline, timeout behavior, and authorized
    feedback commands.
15. **Risk and setup values:** provide the actual risk limits, active segments,
    group IDs, log destination, optional private broker-ack destination, equity
    percentage, sizing values, and SL/target confirmation.
16. **Infrastructure:** provide the GCP project, region/zone, VM budget/size,
    backup/retention needs, and logging budget when VM work begins.
17. **Persistence:** approve SQLite on the single VM or request managed PostgreSQL;
    see the cost discussion in `docs/ARCHITECTURE.md`.
18. **Names and display:** confirm whether “Sapphire Bot” from the screenshot is
    the product name or only a visual reference.

## Supplied dashboard references

The supplied setup image is a visual reference. Its “Paper Trading” control
conflicts with the approved requirements and will not be copied. A future setup
screen should instead show the single `TEST`/`LIVE` switch, explicit active flags,
and warnings that `TEST` does not simulate trades. The supplied Telegram log
example informs readability only; actual fields and redaction still need approval.
