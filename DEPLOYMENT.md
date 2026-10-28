# Deployment

No deployment has been created or changed. The existing deployment is out of
scope. The target is a new Google Compute Engine VM supplied by Udit later.

## Approval boundaries

- Preparing code, tests, documentation, and a deployment plan does not authorize
  production deployment.
- Creating or modifying the new production VM requires Udit's explicit approval
  after the plan is reviewable.
- A live broker order test requires separate explicit approval after successful
  TEST-mode verification.

## Planned shape

One process installation will host the Telegram listener, signal pipeline,
scheduled health/token task, durable journal, and terminal administration commands.
Systemd is the likely supervisor on GCE. Docker and Cloud Logging will be used only
if they provide a concrete operational benefit after VM and logging costs are
agreed.

Runtime values will live in one protected environment file readable only by the
service account. Telegram session files and durable state will live outside the
Git checkout with restrictive permissions and backups. No credential or session
belongs in an image, repository, command history, or log.

The loader now enforces service-user ownership, regular-file type, no symlink,
and mode `0600` or stricter. [.env.example](.env.example) documents required names
without values. VM setup must create the populated file outside the checkout and
must never pass PIN/TOTP/session credentials as command-line arguments.
Any active segment also requires six explicit positive risk settings; startup
fails if the set is missing or partial. Deployment templates must not invent
values for these operator decisions. Each active segment also requires an
explicit `FIXED` or `BUDGET` sizing mode and value; fixed values are whole units.

Telegram authorization must occur in a separate operator-attended setup step.
The unattended service refuses a missing or unauthorized session. The session
parent directory must be `0700`; the session and SQLite sidecars must be `0600`.
The session path remains outside the checkout and backup/log collection must
exclude its contents.
The same authorized Telegram client sends fixed plain-text processing results to
the configured log group. No bot token or second account is required. Credentialed
TEST must verify destination IDs and operator visibility before service rollout.

Dhan TOTP authentication can generate a 24-hour token and verify it through the
read-only fund endpoint. The current adapter keeps that token only in process
memory. The final service composition must run refresh at the approved calendar
time, journal only its fixed health result, and block new LIVE entries after any
failed health check. Failure and holiday semantics remain open.

The one-shot coordinator and exact 08:00 Asia/Kolkata conversion are implemented.
It audits component/error codes, token expiry, stop state, and the absent executor
without recording the token, credentials, account balance, or Telegram content.
The VM timer must remain disabled until the official calendar, missed-run, retry,
and log-group notification behavior is approved.

The runtime database is SQLite in WAL mode. Offline maintenance is exposed as
`codexbot-db integrity`, `codexbot-db backup`, and `codexbot-db restore-test`.
Production scheduling, encrypted backup destination, retention, file ownership,
disk alerts, and recovery objectives will be set in the VM plan.

`codexbot-admin emergency-stop` is the current SSH control surface. The database
starts engaged, and every release/engage action records local OS user identity,
reason, and time in append-only control and audit rows. Systemd permissions must
limit this command to the operator service account. Broker cancellation and
position management are still absent and cannot be inferred from this entry gate.
`codexbot-admin status` adds WAL mode and latest real-broker observation counts
and times without printing credentials, access tokens, balances, order details,
or position values.

The implemented cache stores Dhan's public detailed master as validated SHA-256
snapshots and atomically switches a current pointer while preserving last-known-good
data. The VM plan must schedule `codexbot-instruments refresh`, supply an explicit
maximum age to `status`/service startup, run `prune --keep 2`, and alert on refresh
or freshness failure. No large master file belongs in Git.

## Inputs needed before VM work

- GCP project and billing context;
- preferred region/zone and monthly budget;
- VM size or workload assumptions;
- operating-system preference if any;
- backup retention and recovery target;
- Cloud Logging retention/budget;
- DNS/VPN/SSH access policy;
- final service name and notification destinations.

Runbooks, systemd units, firewall policy, backup/restore tests, and rollback steps
will be written and reviewed before deployment approval is requested.
