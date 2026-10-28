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
  files with owner-only permissions. Preserve marked Telegram IDs and forwarded
  origins for audit even though signal authorization is group-only.
- Provide a separate operator-attended Telegram authorization command that reads
  credentials from the protected environment, never command-line arguments,
  disconnects after authorization, and hardens the resulting session files.
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
- Require a configured signal-group ID. Every sender and forwarded origin inside
  the three configured signal groups may enter deterministic parsing and
  validation; sender identity remains audit metadata. Reject every other group.
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
- Require an owner-owned `0700` journal directory; reject symlinked or
  group/world-accessible database paths; protect database, WAL/SHM sidecars, and
  backups as `0600` files.
- Deterministic local rules have final authority. AI may recheck potential
  rejections when available, but cannot override deterministic validation or
  change rules without approval.
- Support NSE/BSE equities. Equity entry uses a validated current price plus a
  setup percentage and a `LIMIT` order. Delivery (`CNC`) is the only equity route
  in the current stage. MTF is deferred.
- Delivery equity uses fixed-fractional sizing. Setup supplies the exact risk
  percentage per trade greater than zero and no more than the 1% position-loss
  cap, plus an allocation cap from 10% through 15% of starting
  capital. Quantity is the smaller whole-share result from
  `(capital × risk%) / (entry − stop)` and the allocation cap. Reject below one
  share. Earlier fixed-share and budget calculators remain isolated primitives.
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
- During attended TEST, the Dhan instrument snapshot and official NSE calendar
  cache each have a maximum accepted age of 86,400 seconds. Production refresh
  and missed-run escalation remain separate decisions.
- Use Yahoo Finance for equity market prices for now. The adapter retains the
  Yahoo market timestamp, local receipt timestamp, previous completed one-minute
  close, and previous-day close. It fails closed on missing, malformed,
  non-positive, or non-unique responses. No other market-data API is requested.
- A tick and its local receipt must each be no more than 3 seconds old at
  evaluation; allow the existing 2-second future tolerance. Reject a tick more
  than 3% from the previous one-minute close or more than 5% from the previous
  day's close. Daily-timeframe data must be no more than 24 hours old. Active
  equity still requires the setup percentage above market.
- Support stock-option `BUY` only. Require a stated price. The upper entry ceiling
  is that price multiplied by `1.04`; round down to a verified price tick so tick
  handling never exceeds the ceiling.
  Use current calendar month when expiry is omitted and reject unless exactly one
  listed contract matches. No option writing or index options.
- Fixed option lots and option budget calculations are implemented as separate
  pure strategies. Budget mode floors to complete lots using the validated lot
  size and rejects below one lot; setup selects one strategy and positive value
  when F&O is active. Fixed share/lot values must be whole numbers.
- Stop loss and target are setup values, with the previously chosen defaults of
  3% each based on actual fills. Telegram SL/target text is ignored. Prevent
  over-exits and reconcile state on restart.
- Risk setup includes maximum order amount, daily loss, total exposure, open
  positions, and daily trade count. Halt new entries at 2%
  accumulated daily loss from starting capital, require a hard stop-management
  action when one position loses 1% of starting capital, and cap new positions at
  three in the same sector.
- All five absolute risk settings are mandatory and positive when either segment
  is active. Keep 5% of starting capital as cash after a proposed entry and treat
  only 95% of currently available funds as spendable. Insufficient cash rejects;
  quantity is not silently reduced. Authorization requires current account and
  sector data; there is no separate ambiguous minimum-funds setting.
- TEST setup activates both equity and F&O with starting capital INR 20,000,
  maximum order INR 20,000, total exposure INR 20,000, at most two open
  positions and two daily trades, fixed option sizing of one lot, 3% equity
  limit uplift, 1% risk per trade, and a 10% allocation cap. The absolute daily
  loss limit is INR 400 from the approved 2% rule.
- Emergency stop blocks new entries, cancels pending entries, continues managing
  filled positions, and exposes a separate explicit close action.
- The durable emergency-stop entry gate fails closed on a new database. Only an
  explicit local operator release allows candidates to proceed. Engage/release
  actions and reasons are append-only audit facts. Until broker writes exist, the
  admin status reports pending-entry cancellation as a required future action.
- Reconcile an uncertain submission outcome before any retry. On partial fill
  after timeout, manage actual fills and make at most one retry for the unfilled
  quantity only after confirming the original remainder is cancelled.
- API connect timeout is 3 seconds and response/read timeout is 5 seconds. A LIMIT
  fill timeout is 45 seconds. Reconcile status before action and confirm remainder
  cancellation before the one retry. Market conversion is disabled under the
  LIMIT-only scope; the retry-price calculation remains unresolved.
- On an open day, initialization runs 08:45-09:15 Asia/Kolkata with no entries,
  followed by a no-entry guard until 09:16. Normal entry runs 09:16-15:10. From
  15:10, halt entries and mark pending-entry cancellation due. Delivery positions
  carry; MIS is outside current scope. At 15:35 reconciliation/log rotation are due.
- Dynamic exchange calendar data is authoritative. On failure, weekends and dates
  in the validated local annual file stay closed. Any other weekday stays closed
  until an authenticated manual open override, marked cautionary. The repository
  contains the official NSE 2026 CM/FO fallback; BSE stays closed without its
  separately verified official fallback.
- Download the bounded official NSE CM/FO holiday response into an owner-only
  atomic cache. Validate its shape, dates, single year, source, permissions, and
  explicit maximum age before use; refresh failure preserves last-known-good.
  Calendar cache health is part of the 08:00 system health decision. Dated NSE
  manual open/clear actions require a local OS actor and reason in append-only
  history and may cover verified special sessions. BSE has no override.
- Log recognized, rejected/filtered messages and reasons, validations, orders,
  errors, and a daily summary. Preserve an authenticated, immutable audit trail.
- Accept operator feedback only in the separate configured log group from an
  explicitly configured operator Telegram ID. The exact command is
  `/feedback <source_group_id>:<message_id> <review note>`. Reject forwarded,
  unauthorized, malformed, oversized, and unknown-target commands. Store accepted
  notes append-only as `PENDING_REVIEW`; feedback cannot apply a rule, replay a
  signal, change a decision, or perform a broker action.
- The initial log-group format is plain text and excludes raw message and
  exception text. It shows stable reasons/pending gates, source/message identity,
  `Trade ready: NO`, and `Broker action: NONE`. Daily counts come only from the
  immutable audit journal; delivery timing remains tied to the open calendar policy.
- Persist only actual Dhan order/trade/position reads as broker observations.
  Store each three-resource snapshot atomically and append-only; TEST must never
  populate these tables with invented or simulated state.
- Protect credentials and Telegram session data. Never commit either.
- Exclude Notion, Google Sheets, Kite, Railway, other brokers, and changes to the
  existing deployment.
- Deploy TEST only to the existing Debian 13 `auditbot` VM in project
  `diamond-bot-511604`, zone `asia-south1-c`. Refuse any other target. Do not
  create, replace, reimage, resize, or expose a port without separate approval,
  and never modify the sapphairebot production VM.
- Provide a runnable TEST observation service that loads only the protected
  environment and validated instrument cache, then composes the journal, parser,
  deterministic checker, resolver, Telegram listener, feedback, and reporting.
  It must refuse `LIVE` while the broker write executor is absent.

## Open decisions — implementation blocked where affected

1. **Remaining parser examples:** stock-option, EXIT, analysis, watchlist,
   future-intent, status/log, negated-BUY, and chart-only examples were supplied
   and implemented without archive code. Supply redacted equity BUY, SELL,
   expiry-omitted non-index stock-option, and additional malformed-message
   examples before expanding those forms.
2. **Equity entry percentage:** ages are fixed at 3 seconds and anomalies at
   3%/5%. Supply the percentage above market. Yahoo describes this data as
   informational and lists BSE as delayed by 15 minutes; data that cannot meet the
   approved limits fails closed.
3. **Option tick units:** floor-to-tick pricing is implemented. Dhan's detailed
   master currently supplies raw values such as `5.0000`; verify their price-unit
   conversion from current official/broker guidance before connecting that field
   to the calculation.
4. **Sizing values:** supply the exact fixed-fractional risk percentage and select
   the exact allocation cap from 10% through 15%.
5. **Equity product:** delivery/CNC is selected now. MTF eligibility, consent, and
   stock-specific margin checks remain a later-stage feature.
6. **Futures:** confirm whether stock futures are in scope. “OK” is not treated as
   approval. Futures remain blocked.
7. **Retry pricing:** fill timeout is 45 seconds, connect timeout 3 seconds, and
   read timeout 5 seconds. Supply the one-retry price/recalculation rule.
8. **Mode changes:** define handling of pending entries, exits, and open
    positions when changing `TEST`/`LIVE`.
9. **End of day:** delivery-stage times are approved. Failure handling during
   future cancellation/reconciliation and exit-protection behavior remain open.
10. **Restart gaps:** decide whether missed Telegram messages are logged only or
    may be evaluated; old messages must never become automatic trades.
11. **Calendar and 08:00 health check:** NSE cache, fallback, special-session
    override history, and cache health are implemented. Supply production cache
    age/refresh timing; add a verified official BSE source; define late/missed
    checks, token-refresh/service failure, and notification retry. Automatic
    reauthentication is not assumed.
12. **AI review:** authenticated feedback storage is implemented. Choose which
    filtered chatter/rejections invoke AI, provider, data policy, cost ceiling,
    latency deadline, timeout behavior, and the later manual rule-approval flow.
13. **Risk and setup values:** provide the actual risk limits, active segments,
    group IDs, log destination, optional private broker-ack destination, equity
    percentage, sizing values, starting-capital source, sector classification
    source, and SL/target confirmation.
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
