# Project status

Status date: 2026-10-27 (Asia/Kolkata)

## Implemented

- Python 3.12 package baseline and GitHub CI definition.
- Typed, deterministic, side-effect-free signal-checking core.
- Common execution-mode model with safe `TEST` default and separate equity/F&O
  active flags.
- Configured-source, source-verification, 60-second age, action, segment,
  instrument resolution/listing, verified instrument-kind, index, futures, and
  basic stock-option gates.
- Structured reason codes and explicit remaining-gate list.
- Structural safety boundary: the package contains no broker client, order model,
  fill model, holdings model, or simulator; `trade_ready` is always false.
- Automated unit tests for implemented behavior and safety boundaries.

## Verified in this review

- Current official Dhan API documentation and official SEBI/NSE retail-algo
  materials were reviewed without credentials or broker writes. The resulting
  LIVE blocker and open broker questions are recorded in `DHAN_API.md`.
- The locked local development environment installs successfully. Ruff, strict
  mypy, and the full unit suite pass; exact results are kept in the test plan.

## Planned, blocked by inputs or approval

- Reference archive review and real-message parser.
- Exact duplicate detection.
- Telegram listener/session handling and authenticated operator feedback.
- Read-only Dhan instrument, quote, funds, margin, order, trade, and position
  connectivity.
- Durable journal and restart reconciliation.
- Pricing, sizing, funds, risk, emergency-stop, execution, partial-fill/retry, and
  protection logic.
- 08:00 Asia/Kolkata health/token workflow and exchange calendar.
- SSH terminal dashboard, Google Cloud Logging, Docker, and new GCE deployment.
- Any `LIVE` order path or live test.

## Evidence and limitations

- `darvas_script-main.zip` is not currently available in the workspace, so no
  reference rule has been reused.
- No Dhan or Telegram credential has been requested, stored, or tested.
- Official BSE calendar and exchange-specific algo materials have not yet been
  verified; BSE remains blocked beyond offline core work.
- No broker connectivity, VM deployment, order submission, or production
  readiness is claimed.
