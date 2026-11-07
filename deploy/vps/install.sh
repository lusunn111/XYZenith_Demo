#!/usr/bin/env bash
set -Eeuo pipefail

if [[ ${EUID} -ne 0 || $# -ne 1 ]]; then
    echo 'Usage (root): bash deploy/vps/install.sh /opt/xyzenith/releases/REVISION' >&2
    exit 1
fi
release_dir=$(realpath "$1")
case "$release_dir" in
    /opt/xyzenith/releases/*) ;;
    *) echo 'Release must be inside /opt/xyzenith/releases' >&2; exit 1 ;;
esac
test -f "$release_dir/frontend/dist/index.html"
test -f "$release_dir/backend/pyproject.toml"
command -v ffprobe >/dev/null
command -v nginx >/dev/null

if ! id xyzenith >/dev/null 2>&1; then
    useradd --system --home-dir /var/lib/xyzenith --shell /usr/sbin/nologin xyzenith
fi
install -d -m 0750 -o xyzenith -g xyzenith /var/lib/xyzenith
install -d -m 0755 /etc/xyzenith
if [[ ! -e /etc/xyzenith/backend.env ]]; then
    install -m 0640 -o root -g xyzenith "$release_dir/deploy/vps/backend.env.example" /etc/xyzenith/backend.env
fi
if [[ ! -x "$release_dir/backend/.venv/bin/python" ]]; then
    python3 -m venv "$release_dir/backend/.venv"
fi
"$release_dir/backend/.venv/bin/python" -m pip install --no-cache-dir -r "$release_dir/backend/requirements.lock.txt"
"$release_dir/backend/.venv/bin/python" -m pip install --no-cache-dir --no-deps "$release_dir/backend"

previous_release=$(readlink /opt/xyzenith/current || true)
backup_dir=$(mktemp -d /tmp/xyzenith-deploy.XXXXXX)
nginx_config=/etc/nginx/conf.d/xyzenith.conf
service_config=/etc/systemd/system/xyzenith.service
[[ ! -f "$nginx_config" ]] || cp "$nginx_config" "$backup_dir/nginx.conf"
[[ ! -f "$service_config" ]] || cp "$service_config" "$backup_dir/service.conf"

rollback() {
    trap - ERR
    set +e
    for pair in "nginx.conf:$nginx_config" "service.conf:$service_config"; do
        saved=${pair%%:*}
        destination=${pair#*:}
        if [[ -f "$backup_dir/$saved" ]]; then
            cp "$backup_dir/$saved" "$destination"
        else
            rm -f "$destination"
        fi
    done
    if [[ -n "$previous_release" ]]; then
        ln -sfn "$previous_release" /opt/xyzenith/current.next
        mv -Tf /opt/xyzenith/current.next /opt/xyzenith/current
    else
        systemctl disable --now xyzenith.service
        rm -f /opt/xyzenith/current
    fi
    systemctl daemon-reload
    [[ -z "$previous_release" ]] || systemctl restart xyzenith.service
    nginx -t && systemctl reload nginx
    echo "Deployment failed; previous configuration restored. Backup: $backup_dir" >&2
    exit 1
}
trap rollback ERR

install -m 0644 "$release_dir/deploy/vps/nginx.conf" "$nginx_config"
nginx -t
ln -sfn "$release_dir" /opt/xyzenith/current.next
mv -Tf /opt/xyzenith/current.next /opt/xyzenith/current
install -m 0644 "$release_dir/deploy/vps/xyzenith.service" "$service_config"
systemctl daemon-reload
systemctl enable xyzenith.service
systemctl restart xyzenith.service
ready=false
for attempt in $(seq 1 10); do
    if curl --silent --fail --max-time 3 http://127.0.0.1:18000/api/health >/dev/null; then
        ready=true
        break
    fi
    sleep 1
done
[[ "$ready" == true ]]
systemctl reload nginx
systemctl is-active xyzenith.service
trap - ERR
