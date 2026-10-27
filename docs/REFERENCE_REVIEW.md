# Reference archive review

Reviewed: 2026-10-27 (Asia/Kolkata)

Archive: `darvas_script-main.zip`
SHA-256: `02079e46b218241c8a8b8b165f58d8f2386a3c4d1679fcc55d6e74fb36f70c2e`

The archive contains 75 files and describes an older, separate system. Its
embedded README and agent instructions were treated as sample documentation, not
instructions for Codexbot. No source file or dependency was copied.

## Concepts consistent with already approved Codexbot rules

These concepts may inform a fresh implementation after their exact behavior is
approved:

- deterministic local parsing before an optional AI review;
- BUY-only entry classification and non-execution of SELL/EXIT messages;
- canonical Dhan instrument data for ticker, security ID, lot size, tick size,
  expiry, strike, and option type;
- rejection rather than guessing when a company name or contract is ambiguous;
- option messages carrying underlying, strike, CE/PE, optional expiry, and a
  mandatory entry price/range;
- ignoring Telegram stop-loss/target values in favor of configured percentages;
- stop and target levels derived from broker-reported actual fills;
- whole-lot budget sizing that rejects when one lot is unaffordable;
- durable receipt claiming, WAL-mode SQLite, and restart reconciliation as useful
  patterns, provided Codexbot uses an append-only audit model.

These are requirements already supplied by Udit. Their presence in the archive
does not independently approve archive code or edge-case behavior.

## Candidate message formats found

Equity examples:

- `Buy #SBIN @ 805-810 SL 780`
- `Bought in POLYCAB @ 7000`
- `Added more #SBIN`
- `Bought Manipal Payment at 450`
- `Buy State Bank of India @ 810`

Stock-option examples:

- `#POLYCAB 8000 PE OCT @90-105`
- `#LT 3900PE @80`
- `CDSL 1400CE OCT @33-35`
- `#M&M 3200 CE 30 OCT @50 to 55`

Exit examples include `Book profits ...` and `Exit ...`. These samples appear in
tests or documentation and are not assumed to be real production messages. Udit
must confirm which formats and misspellings actually occur before a parser is
implemented.

## Rules deliberately not reused

- Notion, Google Sheets, Discord, email, Kite, Railway, Koyeb, WebSocket
  broadcaster, multi-account, multi-broker, and split-service architecture.
- `DRY_RUN` behavior that creates simulated orders, statuses, fills, or protection.
- MARKET orders, automatic AMO, and default-quantity fallback when price lookup
  fails.
- Index options and index-specific routing.
- Catch-up that processes every missed equity message. The archive applies a
  120-second age check only to F&O, while Codexbot requires a fixed 60-second gate
  for every candidate and an approved restart policy.
- Duplicate identity based only on `<group_id>:<message_id>`; it does not implement
  the required 20-second semantic duplicate window across groups.
- Archive option pricing of `entry_max × 1.02` or `LTP + ticks`; Codexbot requires
  an upper ceiling of `entry_max × 1.04` with approved tick rounding.
- Nearest-expiry selection when the option month is omitted; Codexbot requires the
  current calendar month and rejection unless exactly one listed contract matches.
- Separate equity/F&O modes and per-channel trading switches that conflict with
  one common TEST/LIVE switch plus global segment active flags.
- Static JSON holidays, weekday-only AMO decisions, and missing-holiday fail-open
  behavior.

## Unsafe or ambiguous archive behavior

- The equity parser can accept an unvalidated ticker if the instrument download
  fails. Codexbot must fail closed.
- The parser treats words such as `SL`, `target`, `bot`, and `asd` as BUY intent;
  these can create false positives and are not approved.
- Equity price ranges keep the first value rather than the upper value.
- The index filter uses substring matching, and the analysis-word blacklist can
  reject unrelated text without reliable context.
- The Yahoo quote fallback is NSE-only, does not validate its timestamp, falls
  back to a default quantity on failure, and changes to MARKET orders.
- The archive retries a broker write after token refresh without first proving
  whether an ambiguous original request created an order.
- The SQLite journal mutates current rows and is not an append-only audit trail.
- Protection and Dhan Super/Forever Order behavior is assumed by code and must be
  reverified against current official documentation and Udit's account.

## Yahoo Finance finding

The archive calls the undocumented
`query1.finance.yahoo.com/v8/finance/chart/...` endpoint. A read-only check showed
that its response currently includes `regularMarketPrice`, `regularMarketTime`,
and exchange metadata, but endpoint availability and schema are not guaranteed.

Yahoo's official market-coverage page states that all Yahoo Finance data is for
informational purposes and is not intended for trading or investing. It currently
lists NSE (`.NS`) as real-time and BSE (`.BO`) as delayed by 15 minutes. Udit
subsequently approved Yahoo Finance as the equity market-data source for the
current phase and asked that no other market-data API be pursued now. The new
adapter validates price and timestamps and never copies the archive fallback.
Maximum age limits and all other pre-LIVE gates remain unresolved.

Official source: [Yahoo Finance exchanges and data providers](https://help.yahoo.com/kb/finance-for-web/exchanges-data-providers-yahoo-finance-sln2310.html)
