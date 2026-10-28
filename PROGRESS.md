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
| Group-only signal authentication, freshness, parser, and checker | Implemented offline | Credentialed Telegram TEST still required |
| SQLite WAL audit, deduplication, maintenance | Implemented offline | Owner/path protections enforced; VM backup schedule, retention, and restore drill remain open |
| Dhan instrument resolver and atomic cache | Implemented and public-data tested | TEST maximum age 24h; production refresh schedule remains open |
| Yahoo equity and option price calculations | Implemented offline | Equity percentage and Dhan tick-unit conversion required |
| Quote integrity and anomaly gates | Implemented offline | 3s tick/local, 3% minute, 5% daily, 24h EOD; credentialed feed evidence required |
| Fixed-fractional sizing and capital risk | Implemented offline | Exact risk/allocation values and sector classification evidence required |
| Delivery routing, NSE calendar, and session policy | Implemented/public-data tested | TEST NSE cache age 24h; BSE source and production refresh timing open |
| Telegram listener and log-group reporting | Implemented offline | Operator-attended session and configured-group TEST required |
| Authenticated operator feedback and history | Implemented offline | Actual operator/log IDs and credentialed TEST required |
| Runnable TEST listener service | Implemented offline | Protected values, caches, and operator-attended Telegram TEST required |
| Unified TEST deployment preflight | Implemented offline | Run on auditbot after credentials/session/caches are prepared |
| Dhan authentication and read-only reconciliation | Implemented offline | Dhan credentials and account read-only TEST required |
| Emergency stop and SSH status | Implemented offline | VM permissions and pending-order cancellation require later executor |
| 08:00 component health | Implemented with calendar health | Missed-run, retry, and notification policy required |
| Order execution, fills, protection, retries | Blocked | Trading decisions and current Dhan/regulatory approval required |
| Existing auditbot GCE TEST deployment | Approved, access blocked | Target fixed; managed workspace lacks GCP/SSH identity and TCP grant |
| Live order test | Not authorized | Requires completed TEST evidence and separate explicit approval |

## Current verification

- Python 3.12 locked environment: passing.
- Ruff: passing.
- Strict mypy: passing.
- Automated tests: 269 passing.
- GitHub CI: required for every push to `main`.
- Broker write methods: absent.
- Paper trading and simulated portfolio state: absent.

## Decisions resolved in this increment

- Funds: keep 5% of starting capital unallocated, treat 95% of available funds as
  spendable, and reject rather than reduce when the proposed entry does not fit.
- Equity product: delivery/CNC only for this stage; MTF is deferred.
- Data quality: 3-second tick/local ages, 3% previous-minute anomaly, 5%
  previous-day anomaly, and 24-hour daily-data age.
- Risk: 2% daily-capital halt, 1% position hard-stop signal, and three open
  positions per sector.
- Lifecycle: 3-second connect, 5-second read, 45-second LIMIT fill, reconcile and
  confirm cancellation before one retry; market conversion remains disabled.
- Session: 08:45 initialization, 09:16-15:10 entries, 15:10 entry halt/cancel due,
  and 15:35 reconciliation/log rotation due.

## Decisions and inputs blocking composition

| ID | Decision/input | Blocks |
| --- | --- | --- |
| D-01 | Yahoo percentage above market (3-second market/local ages are resolved) | Equity price gate composition |
| D-02 | Verified Dhan raw tick conversion to rupee price increment | Final option/equity tick rounding |
| D-04 | NSE/BSE selection rule (delivery now; MTF deferred) | Equity instrument selection |
| D-05 | Retry price/recalculation rule (3s/5s network and 45s fill resolved) | Partial-fill one-retry state machine |
| D-06 | TEST/LIVE transition and restart backlog (delivery EOD times resolved) | Runtime lifecycle actions |
| D-07 | BSE source, production refresh, missed 08:00 run, retry/alert behavior | Automated daily health schedule |
| D-08 | AI provider, data policy, eligible rechecks, cost and timeout | Advisory AI layer |
| D-09 | Groups/log, capital and numeric limits resolved; sector map and optional feedback operator IDs remain | Credentialed TEST configuration |
| D-10 | Project/VM/zone resolved; supply authorized GCP/SSH connection, backup destination/cost and test-record retention semantics | Existing auditbot deployment |
| D-11 | Redacted equity BUY/SELL and more malformed examples | Remaining parser coverage |
| D-12 | Dhan confirmation for post-April-2026 client algo/static-IP/hosting rules | Any LIVE executor implementation |

## Next safe work queue

1. Compose quote, sizing, delivery routing, capital, sector, and session gates
   after D-01/D-04/D-05/D-09 are answered; all rejections precede dedup.
2. Add production service/runbook templates without deploying; timer activation
   remains blocked on D-07 and VM creation on D-10.
3. Add a manual feedback review/export workflow after its approval semantics are
   agreed; storage must never auto-apply a rule or replay a signal.
4. Prepare the new VM plan after D-10 is supplied; deployment remains a separate
   approval step.

## Update rule

Every material implementation commit updates this file, `PROJECT_STATUS.md`, the
relevant requirements/API/deployment document, and the verified test count. A
status moves to credentialed TEST or LIVE only when that evidence actually exists.
