#!/usr/bin/env bash
set -euo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
test -f "$HOME/.config/xyzenith/tunnel.env"
install -d -m 0700 "$HOME/.config/systemd/user"
install -m 0644 "$script_dir/xyzenith-tunnel.service" "$HOME/.config/systemd/user/xyzenith-tunnel.service"
systemctl --user daemon-reload
systemctl --user enable --now xyzenith-tunnel.service
systemctl --user is-active xyzenith-tunnel.service
