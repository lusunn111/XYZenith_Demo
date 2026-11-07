#!/usr/bin/env bash
set -euo pipefail

if [[ ${EUID} -ne 0 || $# -ne 1 ]]; then
    echo 'Usage (root): bash setup-vps.sh /path/to/a100-public-key.pub' >&2
    exit 1
fi
ssh-keygen -lf "$1" >/dev/null
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
if ! id xyzenith-tunnel >/dev/null 2>&1; then
    useradd --system --create-home --home-dir /var/lib/xyzenith-tunnel --shell /usr/sbin/nologin xyzenith-tunnel
fi
install -d -m 0700 -o xyzenith-tunnel -g xyzenith-tunnel /var/lib/xyzenith-tunnel/.ssh
public_key=$(cat "$1")
printf 'restrict,port-forwarding,permitlisten="127.0.0.1:13010" %s\n' "$public_key" > /var/lib/xyzenith-tunnel/.ssh/authorized_keys
chmod 0600 /var/lib/xyzenith-tunnel/.ssh/authorized_keys
chown xyzenith-tunnel:xyzenith-tunnel /var/lib/xyzenith-tunnel/.ssh/authorized_keys
install -m 0644 "$script_dir/sshd.conf" /etc/ssh/sshd_config.d/xyzenith-tunnel.conf
/usr/sbin/sshd -t
systemctl reload ssh.service
