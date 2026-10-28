# Requirements

Status date: 2026-10-28 (Asia/Kolkata)

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
- The protected environment file must be a regular, non-symlink file owned by the
  service user with no group/world permissions. Reject unknown or duplicate keys,
  missing IDs, zero IDs, invalid booleans, and missing credentials. Never display
  Telegram API hash, phone, Dhan client ID, PIN, or TOTP secret in object/log
  representations.
- Use one Telethon user session. The service listens only for new messages in
  configured groups; it does not register edit/delete handlers. Require an
  existing authorized session rather than prompting for OTP/password during
  unattended startup. Protect the session directory and session/journal/WAL/SHM
  files with owner-only permissions. Preserve marked Telegram IDs and hidden
  forwarded origins so deterministic source checks can fail closed.
- Process only `BUY` initially. Classify and log `SELL`/`EXIT` without execution.
  Ignore edits/deletions after processing.
- Recognize the supplied compact stock-option form
  `SYMBOL STRIKE CE/PE [MONTH] @ LOW[-HIGH]` as a BUY candidate. Preserve both
  bounds and use the upper value as the stated entry bound for later pricing.
  Telegram SL, target, holding-period, and quantity commentary do not change the
  entry fields.
- Recognize the supplied `Close SYMBOL STRIKE CE/PE at PRICE` and
  `SYMBOL exit at PRICE` forms as EXIT. They are classified and logged but never
  enter the BUY pipeline.
- Treat analysis, watchlist-only text, future-entry discussion, bot status/log
  messages, negated BUY instructions, unsupported text, and images without an
  actionable text caption as non-actionable. A compact option-shaped index
  message may be parsed, but canonical instrument facts must reject it as an
  index; symbol-name guessing is not authoritative.
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
- A rejected option candidate does not reserve the duplicate window. Create the
  atomic claim only after source authentication, freshness, BUY intent, active
  segment, listed stock-option identity, unique contract, canonical underlying,
  and valid stated-price checks pass. As later deterministic gates are added,
  they must also precede the final claim so a rejected candidate never consumes
  the window.
- Use SQLite in WAL mode on the single VM. Keep signal receipts, duplicate claims
  and decisions, and audit events append-only. Use atomic transactions for
  duplicate claims and maintain tested integrity, backup, and restore commands.
- Deterministic local rules have final authority. AI may recheck potential
  rejections when available, but cannot override deterministic validation or
  change rules without approval.
- Support NSE/BSE equities. Equity entry uses a validated current price plus a
  setup percentage and a `LIMIT` order. Product is delivery or MTF, selected in
  setup.
- Fixed equity shares and equity budget calculations are implemented as separate
  pure strategies. Budget mode floors to whole shares and rejects below one share;
  setup must still select exactly one strategy and value.
- Resolve instruments from Dhan's official detailed instrument-master schema.
  Require exact NSE/BSE exchange metadata, instrument type, security ID,
  underlying security ID for stock options, option type, strike, expiry, positive
  lot size, and a unique match. Use `OPTSTK`/`OPTIDX` metadata to reject indexes;
  never classify an index from its symbol text alone.
- When an option month is omitted, restrict resolution to the current
  Asia/Kolkata calendar month and year. When a month is present without a year,
  do not guess the year: match listed contracts for that month and reject unless
  exactly one remains.
- Cache the public detailed master outside Git. Bound download size, validate the
  full eligible schema before activation, use SHA-256 versioned snapshots and an
  atomic current pointer, verify size/checksum/age on load, retain last-known-good
  data after refresh failure, use restrictive permissions, and keep bounded old
  snapshots. A stale or corrupt cache fails closed.
- Use Yahoo Finance for equity market prices for now. The adapter must retain the
  Yahoo market timestamp and local receipt timestamp and fail closed on missing,
  malformed, non-positive, or non-unique responses. No other market-data API is
  requested at this stage.
- When equity is active, setup must explicitly provide the percentage above
  market, maximum Yahoo market-timestamp age, and maximum local response age.
  Missing values fail startup; there are no defaults for these open values.
- Support stock-option `BUY` only. Require a stated price. The upper entry ceiling
  is that price multiplied by `1.04`; round down to a verified price tick so tick
  handling never exceeds the ceiling.
  Use current calendar month when expiry is omitted and reject unless exactly one
  listed contract matches. No option writing or index options.
- Fixed option lots and option budget calculations are implemented as separate
  pure strategies. Budget mode floors to complete lots using the validated lot
  size and rejects below one lot; setup must still select one strategy and value.
- Stop loss and target are setup values, with the previously chosen defaults of
  3% each based on actual fills. Telegram SL/target text is ignored. Prevent
  over-exits and reconcile state on restart.
- Risk setup includes maximum order amount, minimum trade funds, daily loss,
  total exposure, open positions, and daily trade count.
- All six risk settings are mandatory and positive when either segment is active;
  none has a production default. The five clear hard caps are implemented as a
  pure evaluator. It cannot authorize entry while minimum-funds semantics remain
  unresolved.
- Emergency stop blocks new entries, cancels pending entries, continues managing
  filled positions, and exposes a separate explicit close action.
- The durable emergency-stop entry gate fails closed on a new database. Only an
  explicit local operator release allows candidates to proceed. Engage/release
  actions and reasons are append-only audit facts. Until broker writes exist, the
  admin status reports pending-entry cancellation as a required future action.
- Reconcile an uncertain submission outcome before any retry. On partial fill
  after timeout, manage actual fills and make at most one retry for the unfilled
  quantity only after confirming the original remainder is cancelled.
- Log recognized, rejected/filtered messages and reasons, validations, orders,
  errors, and a daily summary. Preserve an authenticated, immutable audit trail.
- Persist only actual Dhan order/trade/position reads as broker observations.
  Store each three-resource snapshot atomically and append-only; TEST must never
  populate these tables with invented or simulated state.
- Protect credentials and Telegram session data. Never commit either.
- Exclude Notion, Google Sheets, Kite, Railway, other brokers, and changes to the
  existing deployment.

## Open decisions — implementation blocked where affected

1. **Remaining parser examples:** stock-option, EXIT, analysis, watchlist,
   future-intent, status/log, negated-BUY, and chart-only examples were supplied
   and implemented without archive code. Supply redacted equity BUY, SELL,
   expiry-omitted non-index stock-option, and additional malformed-message
   examples before expanding those forms.
2. **Equity quote policy:** supply the maximum accepted age for Yahoo's market
   timestamp, the maximum local response age, and the percentage above market.
   Yahoo officially describes this data as informational and lists BSE as delayed
   by 15 minutes; these limits must be explicit before quote-based entry validation
   can pass.
3. **Option tick units:** floor-to-tick pricing is implemented. Dhan's detailed
   master currently supplies raw values such as `5.0000`; verify their price-unit
   conversion from current official/broker guidance before connecting that field
   to the calculation.
4. **Sizing priority:** choose fixed shares/lots versus budget when both are
   configured; decide whether insufficient funds always rejects or may reduce
   quantity; define whether minimum-trade-funds is checked before an entry or
   retained after it. This open policy is an explicit risk-evaluation blocker.
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
    assumed. The fixed 08:00 Asia/Kolkata instant and one-shot redacted component
    health audit are implemented without selecting these open policies.
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
17. **Equity exchange selection:** the same equity symbol may resolve on both NSE
    and BSE. Choose whether setup fixes an exchange, each signal must specify it,
    or an explicit preference rule applies. The resolver currently rejects the
    ambiguity rather than selecting an exchange.
18. **Instrument freshness:** set the maximum age of the active Dhan instrument
    snapshot and the refresh schedule. The cache requires an explicit age limit
    and has no implicit production default.

## Supplied dashboard references

The supplied setup image is a visual reference. Its “Paper Trading” control
conflicts with the approved requirements and will not be copied. A future setup
screen should instead show the single `TEST`/`LIVE` switch, explicit active flags,
and warnings that `TEST` does not simulate trades. The supplied Telegram log
example informs readability only; actual fields and redaction still need approval.
