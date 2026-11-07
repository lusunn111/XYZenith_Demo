#!/usr/bin/env bash
set -euo pipefail
script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
mkdir -p "$HOME/.config/systemd/user"
install -m 644 "$script_dir/xyzenith-inference.service" "$HOME/.config/systemd/user/xyzenith-inference.service"
systemctl --user daemon-reload
printf 'Service installed. After GPU validation, run systemctl --user enable --now xyzenith-inference.\n'
