# Deployment templates

These files are reviewable examples for the new GCE VM. They have not been
installed or enabled anywhere. Production deployment still requires Udit's
explicit approval, and a live order test requires separate approval.

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

Calendar, health, instrument-refresh, summary, backup, and reconciliation timers
are intentionally absent. Their production ages, missed-run behavior, retries,
notification escalation, backup destination, and retention remain explicit inputs.
Do not invent or enable timers until those decisions are recorded.
