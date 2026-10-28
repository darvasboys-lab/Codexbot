# Risk register

Status date: 2026-10-28 (Asia/Kolkata)

| Risk | Current control or required mitigation | Status |
| --- | --- | --- |
| LIVE use may not meet post-April-2026 retail-algo rules | Obtain current written Dhan classification/onboarding guidance; confirm hosting, static IP, algo tagging, audit, and rate limits before implementing writes | LIVE blocker |
| Duplicate order after timeout or ambiguous response | Durable unique intent/correlation record; reconcile broker orders and trades; never blind-retry | Strict read snapshots implemented; intent/retry actions blocked |
| Over-exit after partial fills or restart | Derive exits from reconciled broker net quantity; serialize exit changes; enforce one-retry policy only after confirmed cancellation | Position/trade snapshots implemented; action policy blocked |
| Stale, delayed, or informational quote | Yahoo is the approved source for now and reports BSE delayed by 15 minutes; retain market/receipt timestamps, fail closed, require VM clock health, session/calendar checks, and explicit age limits | Adapter and configurable gate implemented; production values open |
| Wrong stock/contract | Strictly validate Dhan's detailed master; activate checksummed snapshots atomically; enforce explicit age; resolve canonical identity and reject ambiguity | Resolver/cache implemented; production age and tick-unit verification pending |
| Duplicate Telegram events across groups/reconnects | Immutable first receipt plus atomic 20-second canonical-underlying option claim; ignore strike/expiry/price/CE-PE | Implemented for stock options |
| Backlog traded after reconnect | Fail closed; no old-message auto-trading; exact still-fresh backlog policy remains open | Policy open |
| Token/TOTP or Telegram session exposure | Owner-only non-symlink config/session/sidecars, redacted secret wrappers, files outside Git, no unattended login, fixed Dhan errors, in-memory tokens, URL/error redaction | Loader/listener/auth/Git controls implemented; live verification pending |
| Unexpected mode transition | Reconcile first; recheck durable common mode at submission boundary; manage filled exposure under an approved policy | Policy open |
| AI hallucination, latency, or data disclosure | Advisory-only review, deterministic revalidation, bounded timeout/cost, audit, and approved provider/data policy | Policy open |
| VM/SQLite loss or corruption | WAL, short transactions, integrity/backup/restore commands, encrypted scheduled backups, restore drills, disk alerts | Core tooling implemented; VM operations open |
| Emergency stop gives false safety | Append-only fail-closed entry gate is checked before deduplication; future write adapter must cancel/reconcile pending entries and separately authenticate close action | Entry gate implemented; broker actions blocked |
| Broker/API behavior changes | Pin tested client behavior, monitor official release notes, contract-test read APIs, reverify before LIVE | Ongoing |
| Health display creates false LIVE confidence | Separate observation health from LIVE capability; include stop and executor state; never log credentials or funds in the health audit | Implemented; notification policy open |
