# Deployment templates

These files are reviewable examples for the new GCE VM. They have not been
installed or enabled anywhere. Production deployment still requires Udit's
explicit approval, and a live order test requires separate approval.

The approved TEST target is the existing `auditbot` instance in project
`diamond-bot-511604`, zone `asia-south1-c`, running Debian 13. Run
`inspect-auditbot.sh` before any mutation. It reads instance metadata and local
host state, refuses every other project/instance/zone/OS, and does not inspect
other application data. Never run these assets on the sapphairebot production VM.

`codexbot.service.example` runs only `codexbot-listener`. That entrypoint refuses
`LIVE` with `LIVE_EXECUTOR_ABSENT`, loads secrets only from the owner-only file
passed with `--environment`, verifies the active Dhan instrument cache, and has no
broker write adapter. Copy paths only after the final VM layout is agreed.

Before enabling the service:

1. Create the `codexbot` system user and owner-only `/etc/codexbot` and
   `/var/lib/codexbot` directories (`0700`, owned by `codexbot`).
2. Install the repository and locked Python 3.12 environment under the approved
   application path.
3. Put the populated environment file outside Git at mode `0600`; keep
   `CODEXBOT_MODE=TEST`.
4. Complete operator-attended Telegram authorization and protect the session and
   its parent directory.
5. Refresh and inspect the Dhan instrument cache and NSE calendar cache.
6. Run database integrity, backup, and restore tests.
7. Release the default emergency stop only for an attended TEST observation.
8. Run the complete automated suite and capture the exact Git SHA and CI result.

`codexbot-health.*.example` performs a local service and SQLite integrity check
every five minutes without opening a port. `codexbot.logrotate.example` proposes
separate application/error files with 14 daily rotations. The backup examples
propose a consistent local daily SQLite backup and delete files older than seven
days. They are templates only: do not enable backup scheduling until destination,
cost, disk headroom, and retention are approved. A backup on the same boot disk
does not protect against loss of that disk.

The audit journal remains append-only. The requested 30-day TEST-record retention
therefore requires an explicit archive/deletion policy before implementation; no
automatic deletion is inferred. TEST validation exercises signal processing and
reports `NO_BROKER_ACTION`; it does not create simulated orders or fills.

Calendar, instrument-refresh, summary, and reconciliation timers remain absent.
Their production ages, missed-run behavior, retries, and notification escalation
remain explicit inputs. Health and backup timer examples are present for review;
only the local health timer may be enabled during attended TEST deployment.
