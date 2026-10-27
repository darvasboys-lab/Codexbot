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

The runtime database is SQLite in WAL mode. Offline maintenance is exposed as
`codexbot-db integrity`, `codexbot-db backup`, and `codexbot-db restore-test`.
Production scheduling, encrypted backup destination, retention, file ownership,
disk alerts, and recovery objectives will be set in the VM plan.

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
