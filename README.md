# Codexbot

Codexbot is a new single-operator Telegram-to-Dhan trading bot for Udit. The
repository currently contains the first safe build slice: a deterministic,
side-effect-free signal checker. It cannot place broker orders, create fills, or
simulate holdings.

## Current behavior

The checker accepts an already-normalized signal and applies only agreed rules:

- only configured Telegram groups and verified source identities continue;
- message age is at most 60 seconds, inclusive, with future-clock tolerance
  required explicitly by policy;
- `BUY` is the only executable action under consideration;
- `SELL` and `EXIT` are classified and filtered;
- equity and F&O activation are independent, while one `TEST`/`LIVE` mode is
  shared and defaults to `TEST`;
- indexes, unapproved stock futures, unresolved instruments, and unlisted
  instruments are rejected;
- a stock option requires a stated price and one unique listed contract.

Passing these checks produces `PASSED_CORE`, never “valid order” or “trade
ready.” Quote, duplicate, price, tick-size, sizing, funds, risk, mode, emergency
stop, and broker-reconciliation gates remain mandatory and are not implemented.

## Development

Requires Python 3.12 or newer.

```bash
uv sync --frozen --extra dev
uv run --frozen ruff check .
uv run --frozen mypy
uv run --frozen pytest
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

## Safety boundary

There is no paper-trading feature. `TEST` will eventually report real signal
validation results without submitting an order. Production deployment and each
live order test require Udit's separate explicit approval.
