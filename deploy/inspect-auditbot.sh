#!/bin/sh
set -eu

# Read-only preflight for the approved TEST VM. It deliberately does not read
# application credentials or inspect any other application's files.
metadata='http://metadata.google.internal/computeMetadata/v1'
header='Metadata-Flavor: Google'

metadata_value() {
    curl --fail --silent --show-error --connect-timeout 2 --max-time 5 \
        -H "$header" "$metadata/$1"
}

project_id=$(metadata_value 'project/project-id')
instance_name=$(metadata_value 'instance/name')
zone_path=$(metadata_value 'instance/zone')
zone=${zone_path##*/}

[ "$project_id" = 'diamond-bot-511604' ] || {
    echo "REFUSED: unexpected project: $project_id" >&2
    exit 20
}
[ "$instance_name" = 'auditbot' ] || {
    echo "REFUSED: unexpected instance: $instance_name" >&2
    exit 21
}
[ "$zone" = 'asia-south1-c' ] || {
    echo "REFUSED: unexpected zone: $zone" >&2
    exit 22
}

. /etc/os-release
[ "${ID:-}" = 'debian' ] && [ "${VERSION_ID:-}" = '13' ] || {
    echo "REFUSED: Debian 13 required" >&2
    exit 23
}

echo "identity.project=$project_id"
echo "identity.instance=$instance_name"
echo "identity.zone=$zone"
echo "os.pretty_name=${PRETTY_NAME:-unknown}"
echo "kernel=$(uname -r)"
echo "architecture=$(uname -m)"
echo "uptime=$(uptime -p 2>/dev/null || true)"
echo "root_filesystem:"
df -hT /
echo "root_inodes:"
df -hi /
echo "memory:"
free -h
echo "swap:"
swapon --show --noheadings || true
echo "python:"
python3 --version 2>&1 || true
echo "systemd:"
systemctl --version | head -n 1
echo "codexbot_units:"
systemctl list-unit-files 'codexbot*' --no-legend --no-pager || true
echo "codexbot_paths:"
for path in /opt/codexbot /etc/codexbot /var/lib/codexbot /var/log/codexbot; do
    if [ -e "$path" ]; then
        stat --format='%A %U:%G %n' "$path"
    else
        echo "absent $path"
    fi
done
echo "listening_tcp_udp_sockets:"
ss --listening --tcp --udp --numeric --process 2>/dev/null || \
    ss --listening --tcp --udp --numeric 2>/dev/null || true
echo "failed_units:"
systemctl --failed --no-legend --no-pager || true

