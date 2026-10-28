# Progress and decision dashboard

Status date: 2026-10-28 (Asia/Kolkata)

This is the short tracking view. `PROJECT_STATUS.md` contains detailed evidence,
`REQUIREMENTS.md` is the rule source, and GitHub `main` plus CI are the code source
of truth. A milestone is **implemented** only when code, meaningful tests, and
required documentation are in the repository. Credentialed TEST and LIVE evidence
are tracked separately so offline tests cannot be mistaken for deployment proof.

## Milestones

| Milestone | State | Evidence or next gate |
| --- | --- | --- |
| Requirements and reference review | Implemented | Approved/open rules separated; archive reviewed without source reuse |
| Signal authentication, freshness, parser, and checker | Implemented offline | Credentialed Telegram TEST still required |
| SQLite WAL audit, deduplication, maintenance | Implemented offline | VM backup schedule, retention, and restore drill remain open |
| Dhan instrument resolver and atomic cache | Implemented and public-data tested | Production refresh frequency and maximum age required |
| Yahoo equity and option price calculations | Implemented offline | Yahoo percentage/ages and Dhan tick-unit conversion required |
| Fixed/budget sizing and risk cap primitives | Implemented offline | Funds policy and actual setup values required |
| Telegram listener and log-group reporting | Implemented offline | Operator-attended session and configured-group TEST required |
| Dhan authentication and read-only reconciliation | Implemented offline | Dhan credentials and account read-only TEST required |
| Emergency stop and SSH status | Implemented offline | VM permissions and pending-order cancellation require later executor |
| 08:00 component health | Implemented as one-shot check | Calendar, missed-run, retry, and notification policy required |
| Order execution, fills, protection, retries | Blocked | Trading decisions and current Dhan/regulatory approval required |
| New GCE TEST deployment | Not started | Infrastructure inputs and explicit deployment approval required |
| Live order test | Not authorized | Requires completed TEST evidence and separate explicit approval |

## Current verification

- Python 3.12 locked environment: passing.
- Ruff: passing.
- Strict mypy: passing.
- Automated tests: 205 passing.
- GitHub CI: required for every push to `main`.
- Broker write methods: absent.
- Paper trading and simulated portfolio state: absent.

## Decisions and inputs blocking composition

| ID | Decision/input | Blocks |
| --- | --- | --- |
| D-01 | Yahoo percentage above market, maximum market age, maximum local age | Equity price gate composition |
| D-02 | Verified Dhan raw tick conversion to rupee price increment | Final option/equity tick rounding |
| D-03 | Minimum funds meaning; insufficient funds reject versus reduce | Funds and final risk decision |
| D-04 | Delivery versus MTF; NSE/BSE selection rule | Equity product and instrument selection |
| D-05 | Equity/option initial timeout, retry timeout, retry price | Partial-fill one-retry state machine |
| D-06 | TEST/LIVE transition, end-of-day, and restart backlog policies | Runtime lifecycle and reconciliation actions |
| D-07 | Official exchange calendar, missed 08:00 run, retry/alert behavior | Automated daily health schedule |
| D-08 | AI provider, data policy, eligible rechecks, cost and timeout | Advisory AI layer |
| D-09 | Actual groups, source IDs, log destination, risk and sizing values | Credentialed TEST configuration |
| D-10 | GCP project, region/zone, budget, backup and logging retention | New VM plan |
| D-11 | Redacted equity BUY/SELL and more malformed examples | Remaining parser coverage |
| D-12 | Dhan confirmation for post-April-2026 client algo/static-IP/hosting rules | Any LIVE executor implementation |

## Next safe work queue

1. Add audit-derived daily summary delivery and terminal history views.
2. Add authenticated feedback command storage without automatic rule changes or
   replaying old messages.
3. Add read-only Dhan margin-calculator parsing and MTF evidence gates.
4. Compose pricing, sizing, and risk only after the corresponding decision IDs
   are answered; every rejection remains before the option duplicate claim.
5. Prepare the new VM plan after D-10 is supplied; deployment remains a separate
   approval step.

## Update rule

Every material implementation commit updates this file, `PROJECT_STATUS.md`, the
relevant requirements/API/deployment document, and the verified test count. A
status moves to credentialed TEST or LIVE only when that evidence actually exists.
