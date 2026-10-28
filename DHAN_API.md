# Dhan API and regulatory evidence

Reviewed: 2026-10-28 (Asia/Kolkata). No credentialed, broker-write, or live-order
request was made during this review.

This file records behavior verified from current official sources. It is not an
authorization to implement or enable LIVE execution. Broker capabilities and
regulatory onboarding must be reconfirmed with Dhan immediately before live use.

## Authentication and static IP

The official authentication documentation says:

- a Dhan access token is valid for 24 hours;
- an individual account with TOTP enabled can generate a token with the documented
  `generateAccessToken` endpoint; its response includes `expiryTime`;
- `RenewToken` works only for an active token generated from Dhan Web, expires the
  current token, and returns another 24-hour token;
- static-IP whitelisting is mandatory under the current SEBI/exchange rules;
- Dhan explicitly requires static IP for order-placement APIs and says it is not
  required merely to fetch order or trade details; and
- a configured IP normally cannot be changed more than once in seven days.

The TOTP generation endpoint takes client ID, PIN, and TOTP as query parameters.
An eventual implementation must prevent URLs, headers, exceptions, tracing, and
proxy/access logs from exposing these values. The 08:00 Asia/Kolkata workflow must
use the documented expiry, fail closed for new LIVE entries on failure, and retain
a manual recovery path. No code may assume reauthentication always succeeds.

The implemented adapter generates RFC 6238 SHA-1 six-digit TOTP codes, makes the
documented POST with a bounded HTTPS response, validates the returned client ID,
and treats an offset-less `expiryTime` as Asia/Kolkata. It converts transport,
HTTP, and JSON failures to fixed error codes so credential query values and token
headers are not copied into logs. The token is held only in memory. Successful
authentication is followed by the documented read-only `GET /v2/fundlimit` and
strict client-ID/number validation. No order endpoint is present.

Source: [Dhan authentication](https://dhanhq.co/docs/v2/authentication/)

## Market price and freshness

Dhan's Market Quote API offers LTP, OHLC, and full quote responses. The full
`/marketfeed/quote` response includes `last_trade_time`; `/marketfeed/ltp` does not
include a source timestamp. The live market feed is another documented source.

Dhan does not publish a maximum quote-age guarantee in the reviewed documentation.
Therefore these remain product decisions rather than broker facts:

- LTP versus best available ask as the entry reference;
- maximum local receive age;
- maximum `last_trade_time` age;
- behavior when ask data is absent or no recent trade exists; and
- behavior outside continuous market hours.

Sources:

- [Dhan Market Quote](https://dhanhq.co/docs/v2/market-quote/)
- [Dhan live market feed](https://dhanhq.co/docs/v2/live-market-feed/)

Udit approved Yahoo Finance for equity prices for the current phase and requested
that no other market-data API be pursued now. A read-only adapter retrieves
`regularMarketPrice` and `regularMarketTime` for NSE `.NS` and BSE `.BO` symbols,
and records local receipt time. It rejects missing, malformed, non-positive, or
non-unique results. The adapter has no broker-order capability.

Yahoo's official coverage page states its data is informational and not intended
for trading; it lists NSE as real-time and BSE as delayed by 15 minutes. Maximum
Yahoo market age and local response age remain required configuration decisions
before the price gate can pass. This known limitation remains part of the
pre-LIVE evidence review; it does not trigger work on another API now.

The implemented equity pricing policy requires both age limits and the setup
percentage, accepts those boundaries inclusively with the approved 2-second
future tolerance, requires INR, and returns an unrounded LIMIT ceiling. It has no
fallback price source.

## Instruments, tick sizes, lots, and MTF

The official instrument master contains fields for security ID, exchange/segment,
instrument type, expiry, strike, option type, lot units, tick size, and MTF
leverage for eligible equities. Contract resolution must use this canonical data
and reject stale, missing, unlisted, or non-unique matches. Index rejection must
come from verified instrument metadata, not symbol-name guesses. The resolver
must prove that the requested symbol/contract fields bind to the returned
security ID; a nonblank ID by itself is insufficient.

The implemented read-only resolver follows the documented **detailed** CSV at
`https://images.dhan.co/api-data/api-scrip-master-detailed.csv`. On 27 October
2026 the official file header included `EXCH_ID`, `SEGMENT`, `SECURITY_ID`,
`INSTRUMENT`, `UNDERLYING_SECURITY_ID`, `UNDERLYING_SYMBOL`, `LOT_SIZE`,
`SM_EXPIRY_DATE`, `STRIKE_PRICE`, `OPTION_TYPE`, `TICK_SIZE`, `EXPIRY_FLAG`,
`BUY_SELL_INDICATOR`, and `MTF_LEVERAGE`. The implementation fails closed if
required columns disappear or eligible NSE/BSE equity/derivative rows are
malformed.

A read-only full-file check on that date uniquely resolved `CDSL 1400CE OCT` to
NSE option security ID `62508`, underlying security ID `21174`, expiry
2026-10-27, and lot size 475. It classified `SENSEX 74500CE` as `OPTIDX` on BSE,
which the deterministic checker rejects. These values are time-sensitive evidence,
not pinned trading configuration.

The detailed file returned raw `TICK_SIZE` values such as `5.0000` for those
option rows and `10.0000` for the reviewed NSE equity row. The official page calls
the field the minimum decimal point but does not explain the conversion needed by
order-price units. Codexbot therefore stores `tick_size_raw` and does not use it
for rounding yet. The independent option-pricing function applies `1.04` and
rounds down when given an already verified price-unit tick.

The credential-free cache CLI was exercised against the public URL on 27 October
2026. It downloaded 36,835,408 bytes with SHA-256
`8f080f9de30960b129974e3cc26dcd066b00957935fb31d3cc9d7a812ec54b5f`,
validated the full eligible master, atomically activated it, and successfully
reloaded it under an explicit one-hour test limit. That one-hour value was only a
smoke-test input; production maximum age remains a user decision.

The Funds & Margin documentation provides funds and margin-calculator endpoints,
including `CNC`, `MARGIN`, and `MTF` product types. A documented product enum does
not establish that Udit's account or a specific instrument is eligible. Before an
MTF entry, the future read-only integration must verify account consent, positive
instrument eligibility/leverage, and a successful current margin calculation.
Whether an MTF failure rejects or falls back to delivery remains open; no fallback
will be inferred.

Sources:

- [Dhan instruments](https://dhanhq.co/docs/v2/instruments/)
- [Dhan funds and margin](https://dhanhq.co/docs/v2/funds/)

## Orders, partial fills, cancellation, and retries

The Orders API documents `PART_TRADED`, `filledQty`, `remainingQuantity`, and
`averageTradedPrice`. It supports lookup by `correlationId`. The documentation
describes correlation as a caller-provided tracking value; it does not promise
idempotent order creation.

Consequences for the approved retry rule:

1. A timeout or ambiguous response must never cause an immediate resubmission.
2. Reconcile order and trade data using all available broker identifiers and the
   unique correlation value.
3. Manage the actual filled quantity immediately.
4. Request cancellation of the original remainder.
5. A cancellation acknowledgement alone is insufficient. Confirm the terminal
   broker/exchange state and trades before calculating any unfilled quantity.
6. Make at most the one approved retry, after the timeout and retry-price policies
   are supplied. If cancellation or state cannot be confirmed, do not retry.

Source: [Dhan orders](https://dhanhq.co/docs/v2/orders/)

Codexbot implements only `GET /v2/orders` and `GET /v2/trades` from this API. The
typed readers validate account identity, broker/order/trade identifiers,
instrument identity, transaction/product/order fields, partial-fill quantities,
and prices. It also implements read-only `GET /v2/positions`, validates signed
P&L, and enforces Dhan's documented `netQty = buyQty - sellQty` relationship.
A combined reconciliation snapshot performs three sequential reads and is
explicitly non-atomic. It is evidence for later comparison, not permission to
retry, cancel, or exit.

Source: [Dhan portfolio and positions](https://dhanhq.co/docs/v2/portfolio/)

## Stop loss and target protection

Dhan documents Super Orders across exchanges/segments and product types including
`CNC`, `INTRADAY`, `MARGIN`, and `MTF`. The placement request requires target and
stop-loss prices at initial entry submission.

That behavior does not yet prove a fit for the approved requirement to calculate
3% stop and target from actual fills, particularly across partial fills. Before
implementation, Udit must choose between a broker-supported structure confirmed by
Dhan and separately managed exit orders, then approve gap, trigger, partial-fill,
restart, and over-exit behavior.

Source: [Dhan Super Orders](https://dhanhq.co/docs/v2/super-order/)

## Current retail-algo requirements and pre-LIVE blocker

SEBI's September 2025 extension states that, from **1 April 2026**, its February
2025 retail-algo framework, exchange implementation standards, and detailed
operational modalities apply to all stock brokers.

The reviewed NSE standards/modalities include these relevant obligations:

- a client static IP for API access;
- daily API-session logout before the next trading day;
- two-factor/permitted authentication and client-specific API access;
- registration-free client algos limited to no more than 10 orders per second per
  exchange/segment, with all algo orders still tagged for audit;
- broker audit trails identifying the user for at least five years;
- broker pre-trade risk controls for price, quantity, order value, cumulative open
  orders, margin, exposure, position, turnover, security limits, and runaway
  behavior;
- market-price protection accompanied by a limit price; the documented control
  says an algorithmic order must not be released as a market order;
- the broker server routing API/algo-provider orders to the exchange must be in
  India; and
- the detailed modalities state that strategies run on broker servers and order
  messages originate from broker servers.

The last two points require written/current clarification from Dhan for this exact
self-hosted Telegram automation. Before LIVE development is approved, Dhan must
confirm the account's API/algo classification, static-IP procedure, algo ID/tagging,
permitted hosting and data flow, order-rate limits, audit obligations, and whether
the planned client-side GCE service is supported under the post-April-2026 rules.
Until then, regulatory/live execution is blocked even if read-only APIs work.

Official sources:

- [SEBI retail-algo framework (4 February 2025)](https://www.sebi.gov.in/sebi_data/attachdocs/feb-2025/1738665456458.pdf)
- [SEBI implementation extension (30 September 2025)](https://www.sebi.gov.in/sebi_data/attachdocs/sep-2025/1759232056254.pdf)
- [NSE implementation standards](https://nsearchives.nseindia.com/content/circulars/INVG67858.pdf)
- [NSE detailed operational modalities](https://nsearchives.nseindia.com/content/circulars/INVG69255.zip)

## Trading calendar

NSE's official holiday endpoint provides segment-specific calendars, including
separate cash-market and F&O entries and special sessions. Monday-to-Friday alone
is insufficient for the 08:00 job. The final scheduler should use an auditable
cached calendar, define CM/FO mismatch behavior, and support an authenticated
manual override for official special sessions or emergency changes.

Source: [NSE trading holiday data](https://www.nseindia.com/api/holiday-master?type=trading)

### BSE verification still required

BSE equities are in product scope, but this review has not yet verified the
official BSE trading calendar, special-session source, or BSE-specific implementation
materials that apply to client API algos. NSE sources do not establish BSE rules.
BSE calendar/regulatory enablement therefore remains a pre-LIVE blocker and must
be researched from official BSE/SEBI sources before the BSE adapter is enabled.

## Release context

The reviewed Dhan release notes show an update dated 9 February 2026. Every
endpoint used by the project must be rechecked against the then-current release
notes during implementation and again before production approval.

Source: [Dhan release notes](https://dhanhq.co/docs/v2/releases/)
