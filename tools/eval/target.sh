#!/usr/bin/env bash
set -euo pipefail
#
# target.sh - the light eval harness's target-lifecycle primitive.
#
# Runs WebExploitBench `scripts/targetctl` on a REMOTE machine over ssh (the
# benchmark targets run on a remote docker host, not the polymerhus host) and
# fronts the target with the remote nginx (a system service) so the eval sees
# the app on the STANDARD port of a bare domain - the seed shape the polymerhus
# platform's domain-mode scope supports natively.
#
# The nginx front matters for three reasons:
#   1. targetctl publishes the app on a RANDOM host port per `up`; a seed of
#      the form http://<domain>:<random-port> breaks the platform's scope gate
#      (a domain-mode seed must be a bare host - a dev-side defect, tracked
#      separately). Through nginx the seed is http://<domain>/ on port 80.
#   2. The target has no TLS capability; nginx is the TLS-capable front.
#   3. The front is reconfigured per trial (proxy_pass follows the published
#      port), and removed on `down`, so no stale config ever lingers.
#
# The kali container still aliases the domain -> public IP (hosts.sh): belt
# and braces, deterministic resolution from the recon fleet.
#
# Env:
#   EVAL_SSH_HOST          ssh target (default ubuntu@dj-viscon-workshop-1.vsos.ethz.ch)
#   EVAL_REMOTE_DIR        remote WebExploitBench checkout (default ~/WebExploitBench)
#   EVAL_NGINX_CONF        the nginx conf.d file the front block lives in
#                          (default /etc/nginx/conf.d/eval-target.conf)
#   EVAL_READY_RETRIES     readiness poll count (default 60)
#   EVAL_READY_INTERVAL_S  readiness poll interval (default 5)

EVAL_SSH_HOST="${EVAL_SSH_HOST:-ubuntu@dj-viscon-workshop-1.vsos.ethz.ch}"
EVAL_REMOTE_DIR="${EVAL_REMOTE_DIR:-~/WebExploitBench}"
EVAL_NGINX_CONF="${EVAL_NGINX_CONF:-/etc/nginx/conf.d/eval-target.conf}"
EVAL_READY_RETRIES="${EVAL_READY_RETRIES:-60}"
EVAL_READY_INTERVAL_S="${EVAL_READY_INTERVAL_S:-5}"

die() {
    echo "target.sh: $*" >&2
    exit 1
}

usage() {
    cat <<'EOF'
Usage:
  target.sh up <target>    Start a target on the remote host, front it with
                           the remote nginx, wait for readiness, print
                           TARGET_URL=<front url> TARGET_BACKEND=<direct url>
  target.sh down <target>  Remove the nginx front and stop the target
  target.sh list           List the remote checkout's targets
  target.sh ps [target]    Show running remote targets and URLs
EOF
}

ssh_remote() {
    ssh -o BatchMode=yes -o ConnectTimeout=15 "$EVAL_SSH_HOST" "$@"
}

public_host() {
    printf '%s' "${EVAL_SSH_HOST#*@}"
}

ensure_checkout() {
    ssh_remote "test -d ${EVAL_REMOTE_DIR}/.git || (git clone --depth 1 https://github.com/AgentCyberRange/WebExploitBench.git ${EVAL_REMOTE_DIR})"
}

rewrite_url_host() {
    sed -E "s#http://(0\.0\.0\.0|127\.0\.0\.1|localhost):#http://$(public_host):#g"
}

url_port() {
    printf '%s' "$1" | sed -E 's#.*:([0-9]+)/?$#\1#'
}

wait_ready() {
    local url="$1" i code
    for i in $(seq 1 "${EVAL_READY_RETRIES}"); do
        code="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 10 "$url" 2>/dev/null || true)"
        # 502/503/504 are the FRONT answering "backend not ready" - the app is
        # still booting; keep polling. Any other HTTP code means the app spoke.
        if [ -n "$code" ] && [ "$code" != "000" ] && [ "$code" != "502" ] \
            && [ "$code" != "503" ] && [ "$code" != "504" ]; then
            echo "target.sh: target answered HTTP ${code} after $(( (i - 1) * EVAL_READY_INTERVAL_S ))s"
            return 0
        fi
        sleep "${EVAL_READY_INTERVAL_S}"
    done
    echo "target.sh: WARNING: target did not answer within the readiness window: $url" >&2
    return 1
}

nginx_front_apply() {
    local domain="$1" port="$2" conf
    conf=$(cat <<EOF
server {
    listen 80;
    server_name ${domain};
    location / {
        proxy_pass http://127.0.0.1:${port};
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
EOF
)
    printf '%s\n' "$conf" | ssh_remote "sudo tee ${EVAL_NGINX_CONF} >/dev/null && sudo nginx -t && sudo systemctl reload nginx"
    echo "target.sh: nginx front http://${domain}/ -> 127.0.0.1:${port}"
}

nginx_front_remove() {
    ssh_remote "sudo rm -f ${EVAL_NGINX_CONF} && sudo nginx -t && sudo systemctl reload nginx"
    echo "target.sh: nginx front removed"
}

cmd_up() {
    local target="$1"
    ensure_checkout
    echo "target.sh: preparing images for ${target} (skips when already present)"
    ssh_remote "cd ${EVAL_REMOTE_DIR} && scripts/targetctl build ${target}" | sed 's/^/  [remote] /'
    echo "target.sh: starting ${target} on ${EVAL_SSH_HOST}"
    local out url ip port domain
    out="$(ssh_remote "cd ${EVAL_REMOTE_DIR} && scripts/targetctl up ${target}")"
    printf '%s\n' "$out" | sed 's/^/  [remote] /'
    url="$(printf '%s\n' "$out" | grep -oE 'https?://[^ ]+' | head -n1 | rewrite_url_host || true)"
    [ -n "$url" ] || die "no accessible URL in targetctl output"
    port="$(url_port "$url")"
    domain="$(public_host)"
    ip="$(ssh_remote "hostname -I | awk '{print \$1}'" 2>/dev/null || true)"
    nginx_front_apply "$domain" "$port"
    wait_ready "http://${domain}/" || true
    printf 'TARGET_URL=http://%s/\n' "$domain"
    printf 'TARGET_BACKEND=%s\n' "$url"
    if [ -n "$ip" ]; then
        printf 'TARGET_IP=%s\n' "$ip"
    fi
}

cmd_down() {
    local target="$1"
    ensure_checkout
    ssh_remote "cd ${EVAL_REMOTE_DIR} && scripts/targetctl down ${target}" | sed 's/^/  [remote] /'
    nginx_front_remove
    echo "target.sh: ${target} down"
}

cmd_list() {
    ensure_checkout
    ssh_remote "cd ${EVAL_REMOTE_DIR} && scripts/targetctl list" | sed 's/^/  [remote] /'
}

cmd_ps() {
    ensure_checkout
    local target="${1:-}"
    if [ -n "$target" ]; then
        ssh_remote "cd ${EVAL_REMOTE_DIR} && scripts/targetctl ps ${target}" | sed 's/^/  [remote] /'
    else
        ssh_remote "cd ${EVAL_REMOTE_DIR} && scripts/targetctl ps" | sed 's/^/  [remote] /'
    fi
}

main() {
    [ "$#" -ge 1 ] || { usage; exit 1; }
    case "$1" in
        up) [ "$#" -ge 2 ] || die "up needs a target"; cmd_up "$2" ;;
        down) [ "$#" -ge 2 ] || die "down needs a target"; cmd_down "$2" ;;
        list) cmd_list ;;
        ps) cmd_ps "${2:-}" ;;
        *) usage; exit 1 ;;
    esac
}

main "$@"