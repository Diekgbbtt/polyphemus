#!/usr/bin/env bash
set -euo pipefail
#
# target.sh - the light eval harness's target-lifecycle primitive.
#
# Runs WebExploitBench `scripts/targetctl` on a REMOTE machine over ssh (the
# benchmark targets run on a remote docker host, not the polymerhus host) and
# rewrites the published URL to the remote hostname so the polymerhus kali
# container can reach the target.
#
# targetctl already publishes on 0.0.0.0 with a random host port per `up`, so
# the only wrapping here is: ensure the remote checkout, build images when
# missing, translate the printed URL to the public host, and wait for the
# target to answer HTTP.
#
# Env:
#   EVAL_SSH_HOST          ssh target (default ubuntu@dj-viscon-workshop-1.vsos.ethz.ch)
#   EVAL_REMOTE_DIR        remote WebExploitBench checkout (default ~/WebExploitBench)
#   EVAL_READY_RETRIES     readiness poll count (default 60)
#   EVAL_READY_INTERVAL_S  readiness poll interval (default 5)

EVAL_SSH_HOST="${EVAL_SSH_HOST:-ubuntu@dj-viscon-workshop-1.vsos.ethz.ch}"
EVAL_REMOTE_DIR="${EVAL_REMOTE_DIR:-~/WebExploitBench}"
EVAL_READY_RETRIES="${EVAL_READY_RETRIES:-60}"
EVAL_READY_INTERVAL_S="${EVAL_READY_INTERVAL_S:-5}"

die() {
    echo "target.sh: $*" >&2
    exit 1
}

usage() {
    cat <<'EOF'
Usage:
  target.sh up <target>    Start a target on the remote host, wait for
                           readiness, print TARGET_URL=<published url>
  target.sh down <target>  Stop a target on the remote host
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

wait_ready() {
    local url="$1" i code
    for i in $(seq 1 "${EVAL_READY_RETRIES}"); do
        code="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 10 "$url" 2>/dev/null || true)"
        if [ -n "$code" ] && [ "$code" != "000" ]; then
            echo "target.sh: target answered HTTP ${code} after $(( (i - 1) * EVAL_READY_INTERVAL_S ))s"
            return 0
        fi
        sleep "${EVAL_READY_INTERVAL_S}"
    done
    echo "target.sh: WARNING: target did not answer within the readiness window: $url" >&2
    return 1
}

cmd_up() {
    local target="$1"
    ensure_checkout
    echo "target.sh: preparing images for ${target} (skips when already present)"
    ssh_remote "cd ${EVAL_REMOTE_DIR} && scripts/targetctl build ${target}" | sed 's/^/  [remote] /'
    echo "target.sh: starting ${target} on ${EVAL_SSH_HOST}"
    local out url ip
    out="$(ssh_remote "cd ${EVAL_REMOTE_DIR} && scripts/targetctl up ${target}")"
    printf '%s\n' "$out" | sed 's/^/  [remote] /'
    url="$(printf '%s\n' "$out" | grep -oE 'https?://[^ ]+' | head -n1 | rewrite_url_host || true)"
    [ -n "$url" ] || die "no accessible URL in targetctl output"
    ip="$(ssh_remote "hostname -I | awk '{print \$1}'" 2>/dev/null || true)"
    wait_ready "$url" || true
    printf 'TARGET_URL=%s\n' "$url"
    if [ -n "$ip" ]; then
        printf 'TARGET_IP=%s\n' "$ip"
    fi
}

cmd_down() {
    local target="$1"
    ensure_checkout
    ssh_remote "cd ${EVAL_REMOTE_DIR} && scripts/targetctl down ${target}" | sed 's/^/  [remote] /'
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