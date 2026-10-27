# Risk register

Status date: 2026-10-27 (Asia/Kolkata)

| Risk | Current control or required mitigation | Status |
| --- | --- | --- |
| LIVE use may not meet post-April-2026 retail-algo rules | Obtain current written Dhan classification/onboarding guidance; confirm hosting, static IP, algo tagging, audit, and rate limits before implementing writes | LIVE blocker |
| Duplicate order after timeout or ambiguous response | Durable unique intent/correlation record; reconcile broker orders and trades; never blind-retry | Design approved; not implemented |
| Over-exit after partial fills or restart | Derive exits from reconciled broker net quantity; serialize exit changes; enforce one-retry policy only after confirmed cancellation | Not implemented |
| Stale or wrong quote | Use a timestamped official Dhan source, VM clock health, market-session/calendar gate, and user-approved age limits | Policy open |
| Wrong stock/contract | Resolve canonical security ID, exchange, segment, expiry, strike/type, lot, and tick from current instrument data; reject ambiguity | Core boundary implemented; adapter pending |
| Duplicate Telegram events across groups/reconnects | Durable receipt identity plus atomic approved duplicate key/window | Key/clock policy open |
| Backlog traded after reconnect | Fail closed; no old-message auto-trading; exact still-fresh backlog policy remains open | Policy open |
| Token/TOTP or Telegram session exposure | Files outside Git with restrictive permissions; redact logs/errors/URLs; manual recovery; no secrets in images or command history | Git exclusions implemented; runtime pending |
| Unexpected mode transition | Reconcile first; recheck durable common mode at submission boundary; manage filled exposure under an approved policy | Policy open |
| AI hallucination, latency, or data disclosure | Advisory-only review, deterministic revalidation, bounded timeout/cost, audit, and approved provider/data policy | Policy open |
| VM/SQLite loss or corruption | WAL, short transactions, integrity checks, encrypted backups, restore drills, disk alerts | Persistence decision open |
| Emergency stop gives false safety | Check durable stop immediately before entry; cancel/reconcile pending entries; separately authenticate close action | Not implemented |
| Broker/API behavior changes | Pin tested client behavior, monitor official release notes, contract-test read APIs, reverify before LIVE | Ongoing |
