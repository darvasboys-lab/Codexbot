# Risk register

Status date: 2026-10-28 (Asia/Kolkata)

| Risk | Current control or required mitigation | Status |
| --- | --- | --- |
| LIVE use may not meet post-April-2026 retail-algo rules | Obtain current written Dhan classification/onboarding guidance; confirm hosting, static IP, algo tagging, audit, and rate limits before implementing writes | LIVE blocker |
| Duplicate order after timeout or ambiguous response | Durable unique intent/correlation record; reconcile broker orders and trades; never blind-retry | Strict read snapshots implemented; intent/retry actions blocked |
| Over-exit after partial fills or restart | Derive exits from reconciled broker net quantity; serialize exit changes; enforce one-retry policy only after confirmed cancellation | Position/trade snapshots implemented; action policy blocked |
| TEST data is mistaken for a real holding or fill | Never create broker observation rows from TEST signals; persist only typed responses from Dhan read endpoints in explicitly named append-only tables | Implemented structurally; credentialed verification pending |
| Stale, delayed, anomalous, or informational quote | Yahoo is approved for now and reports BSE delayed by 15 minutes; enforce 3-second market/local age, 3% minute and 5% day anomaly, 24-hour daily data, clock/session/calendar health | Offline gates implemented; credentialed session evidence pending |
| Wrong stock/contract | Strictly validate Dhan's detailed master; activate checksummed snapshots atomically; enforce explicit age; resolve canonical identity and reject ambiguity | Resolver/cache implemented; production age and tick-unit verification pending |
| Duplicate Telegram events across groups/reconnects | Immutable first receipt plus atomic 20-second canonical-underlying option claim; ignore strike/expiry/price/CE-PE | Implemented for stock options |
| Backlog traded after reconnect | Fail closed; no old-message auto-trading; exact still-fresh backlog policy remains open | Policy open |
| Token/TOTP or Telegram session exposure | Owner-only non-symlink config/session/sidecars, redacted secret wrappers, files outside Git, no unattended login, fixed Dhan errors, in-memory tokens, URL/error redaction | Loader/listener/auth/Git controls implemented; live verification pending |
| Unexpected mode transition | Reconcile first; recheck durable common mode at submission boundary; manage filled exposure under an approved policy | Policy open |
| AI hallucination, latency, or data disclosure | Advisory-only review, deterministic revalidation, bounded timeout/cost, audit, and approved provider/data policy | Policy open |
| VM/SQLite loss or corruption | WAL, short transactions, integrity/backup/restore commands, encrypted scheduled backups, restore drills, disk alerts | Core tooling implemented; VM operations open |
| Emergency stop gives false safety | Append-only fail-closed entry gate is checked before deduplication; future write adapter must cancel/reconcile pending entries and separately authenticate close action | Entry gate implemented; broker actions blocked |
| Risk defaults silently permit oversized or correlated entries | Require all absolute values plus fixed-fractional risk/allocation setup; apply 5% cash, 2% daily halt, 1% position stop, and sector-three gates using current evidence | Pure gates implemented; composition/evidence pending |
| Sizing exceeds risk/allocation or creates fractional lots | Use the tighter loss-at-stop/allocation quantity, validate 10-15% selection, floor shares/lots, and reject below one unit | Pure sizing implemented; exact setup values open |
| Calendar/API failure opens trading incorrectly | Dynamic calendar is authoritative; local NSE fallback closes holidays/weekends and requires authenticated cautionary override for other weekdays; no BSE fallback means closed | Pure policy/NSE 2026 file implemented; dynamic cache/BSE source pending |
| Broker/API behavior changes | Pin tested client behavior, monitor official release notes, contract-test read APIs, reverify before LIVE | Ongoing |
| Health display creates false LIVE confidence | Separate observation health from LIVE capability; include stop and executor state; never log credentials or funds in the health audit | Implemented; notification policy open |
| Telegram log leaks signal or exception data | Plain text contains IDs, fixed reason/error codes, and no raw message/exception text; reports state no broker action | Implemented offline; credentialed log-group TEST pending |
| Feedback changes rules or trades an old message | Authenticate separate operator IDs in the separate log group; store only `PENDING_REVIEW`; expose no apply/replay/order path; acknowledge without echoing notes | Implemented offline; credentialed operator TEST pending |
