#!/bin/sh
set -eu

venv=/opt/codexbot/.venv/bin

systemctl is-active --quiet codexbot.service
$venv/codexbot-preflight --environment /etc/codexbot/codexbot.env >/dev/null

