# Codexbot

Codexbot is a new single-operator Telegram-to-Dhan trading bot for Udit. The
repository contains a deterministic signal checker, a SQLite audit/deduplication
journal, a conservative Telegram text parser, and a read-only Yahoo Finance
equity quote adapter. A read-only resolver consumes Dhan's official detailed
instrument-master CSV. A TEST-safe processor composes durable receipt, parsing,
resolution, checking, audit, and option deduplication. It cannot place broker
orders, create fills, or simulate holdings.

## Current behavior

The checker accepts an already-normalized signal and applies only agreed rules:

- both the configured Telegram group ID and authorized sender/channel ID must
  match; forwarded messages also require an authorized original source ID;
- message age is measured at the first durable receipt, is at most 60 seconds
  inclusive, and allows exactly 2 seconds of future clock skew;
- `BUY` is the only executable action under consideration;
- `SELL` and `EXIT` are classified and filtered;
- equity and F&O activation are independent, while one `TEST`/`LIVE` mode is
  shared and defaults to `TEST`;
- indexes, unapproved stock futures, unresolved instruments, and unlisted
  instruments are rejected;
- a stock option requires a stated price and one unique listed contract.

The parser recognizes the supplied stock-option form
`SYMBOL STRIKE CE/PE [MONTH] @ LOW[-HIGH]`, using the upper value as the entry
bound. It recognizes the supplied prefix and infix EXIT forms. Analysis,
watchlist-only text, future-entry discussion, bot status messages, negated BUY
instructions, unsupported text, and chart-only messages without a caption fail
closed as non-actionable. Telegram SL, target, holding-period, and sizing prose do
not alter parsed entry fields.

The SQLite journal uses WAL mode and immutable first receipts. Its atomic
20-second stock-option claim uses canonical underlying ID + `BUY` + stock-option
family, deliberately ignoring strike, expiry, price, and CE/PE. Audit, receipt,
claim, and decision rows are append-only. The Yahoo adapter retrieves timestamped
NSE (`.NS`) and BSE (`.BO`) equity quotes and requires the caller to supply the
still-open maximum acceptable quote age.

Rejected option candidates do not reserve the duplicate window. The processor
creates a claim only after the currently implemented source, freshness, BUY,
segment, listing, stock-option identity, unique-contract, canonical-underlying,
and price checks pass. A corrected signal can therefore claim immediately after
an invalid one. Future deterministic gates must be inserted before this claim.

The instrument resolver validates the documented CSV schema and eligible rows,
uses `OPTSTK` versus `OPTIDX` metadata instead of symbol guesses, requires one
matching contract, retains the canonical underlying security ID, and exposes lot,
expiry, exchange, and Dhan's raw tick-size value. It does not convert that raw
tick value into a price increment until Dhan's units are verified.

The instrument cache streams the public master with a size limit, validates it
before activation, stores SHA-256 versioned snapshots with `0600` permissions,
switches the current pointer atomically, preserves the last-known-good version on
failure, verifies age/size/checksum when loading, and prunes inactive snapshots.

Runtime configuration comes from one owner-only regular environment file. The
loader rejects symlinks, group/world permissions, unknown/duplicate keys, invalid
IDs, and missing values. Only `CODEXBOT_MODE` defaults, and it defaults to `TEST`;
equity/F&O activation, groups, source IDs, paths, snapshot age, Telegram values,
and Dhan TOTP credentials must be explicit. Secret representations are redacted.
See [.env.example](.env.example); keep the populated file outside Git with mode
`0600`.

The Telegram adapter uses one Telethon user session and registers only
`NewMessage` for configured groups. It extracts Telegram's marked group,
sender/channel, and forward-origin IDs, hands the event to durable processing,
and never handles edits or deletions. The service refuses interactive login and
requires an already-authorized owner-only session created during separate setup.

Passing these checks produces `PASSED_CORE`, never “valid order” or “trade
ready.” Applying the Yahoo quote to an entry, equity price percentage, sizing,
funds, risk, mode, emergency stop, and broker-reconciliation gates remain
mandatory and are not implemented.

## Development

Requires Python 3.12 or newer.

```bash
uv sync --frozen --extra dev
uv run --frozen ruff check .
uv run --frozen mypy
uv run --frozen pytest
```

SQLite maintenance commands operate on runtime files outside Git:

```bash
uv run --frozen codexbot-db integrity --database data/codexbot.sqlite3
uv run --frozen codexbot-db backup --database data/codexbot.sqlite3 --output /backup/codexbot.sqlite3
uv run --frozen codexbot-db restore-test --backup /backup/codexbot.sqlite3
uv run --frozen codexbot-instruments --cache-directory data/instruments refresh
uv run --frozen codexbot-instruments --cache-directory data/instruments status --maximum-age-hours HOURS
uv run --frozen codexbot-instruments --cache-directory data/instruments prune --keep 2
```

The CI workflow runs the same lint, type, and test checks. No credential is
needed for this build slice.

Read these before making changes:

- [Requirements](REQUIREMENTS.md)
- [Project status](PROJECT_STATUS.md)
- [Dhan API evidence](DHAN_API.md)
- [Deployment constraints](DEPLOYMENT.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Risk register](docs/RISKS.md)
- [Test plan](docs/TEST_PLAN.md)
- [Reference archive review](docs/REFERENCE_REVIEW.md)

## Safety boundary

There is no paper-trading feature. `TEST` will eventually report real signal
validation results without submitting an order. Production deployment and each
live order test require Udit's separate explicit approval.
