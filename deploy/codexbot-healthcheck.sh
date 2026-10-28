#!/bin/sh
set -eu

database=/var/lib/codexbot/codexbot.sqlite3
venv=/opt/codexbot/.venv/bin

systemctl is-active --quiet codexbot.service
[ -f "$database" ]
[ "$(stat --format='%a' "$database")" -le 600 ]
result=$($venv/codexbot-db integrity --database "$database")
[ "$result" = 'ok' ]

