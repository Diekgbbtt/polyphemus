#!/usr/bin/env bash
set -euo pipefail
#
# hosts.sh - alias the remote target's domain inside the kali container.
#
# The polymerhus recon tools execute inside the kali container, but the
# benchmark target runs on a REMOTE docker host reachable only through its
# domain name or public IP. The domain must resolve to that IP inside kali's
# /etc/hosts for the recon fleet to reach it. The alias is runtime-only
# (ephemeral, lost on container recreation), which is exactly right for a
# temporary harness: no compose edits, no stack restart.
#
# The domain name stays the project target seed (per the operator's ruling):
# the surface the pipeline observes then carries the domain, matching the
# ground truth's host shape.
#
# Usage:
#   hosts.sh alias <domain> <ip>   append/refresh the alias in kali /etc/hosts
#   hosts.sh clear <domain>        remove every alias line for the domain
#   hosts.sh show                  print the kali /etc/hosts tail

EVAL_COMPOSE_FILE="${EVAL_COMPOSE_FILE:-docker-compose.yml}"

die() {
    echo "hosts.sh: $*" >&2
    exit 1
}

kali_container() {
    local cid
    cid="$(docker compose -f "${EVAL_COMPOSE_FILE}" ps -q kali 2>/dev/null || true)"
    if [ -z "$cid" ]; then
        cid="$(docker ps --filter "name=kali" --format '{{.ID}}' | head -n1 || true)"
    fi
    [ -n "$cid" ] || die "no kali container found (compose file: ${EVAL_COMPOSE_FILE})"
    printf '%s' "$cid"
}

cmd_alias() {
    local domain="$1" ip="$2" cid
    cid="$(kali_container)"
    # /etc/hosts is a docker bind mount: sed -i cannot rename it (Device or
    # resource busy), so rewrite via a temp file and truncate-write back.
    docker exec "$cid" sh -c \
        "awk '!/[[:space:]]${domain}\$/' /etc/hosts > /tmp/hosts.tmp && cat /tmp/hosts.tmp > /etc/hosts && echo '${ip} ${domain}' >> /etc/hosts"
    echo "hosts.sh: aliased ${domain} -> ${ip} inside kali (${cid})"
}

cmd_clear() {
    local domain="$1" cid
    cid="$(kali_container)"
    docker exec "$cid" sh -c \
        "awk '!/[[:space:]]${domain}\$/' /etc/hosts > /tmp/hosts.tmp && cat /tmp/hosts.tmp > /etc/hosts"
    echo "hosts.sh: cleared ${domain} aliases from kali (${cid})"
}

cmd_show() {
    local cid
    cid="$(kali_container)"
    docker exec "$cid" cat /etc/hosts | tail -n 20
}

main() {
    [ "$#" -ge 1 ] || { echo "usage: hosts.sh alias <domain> <ip> | clear <domain> | show" >&2; exit 1; }
    case "$1" in
        alias) [ "$#" -ge 3 ] || die "alias needs a domain and an ip"; cmd_alias "$2" "$3" ;;
        clear) [ "$#" -ge 2 ] || die "clear needs a domain"; cmd_clear "$2" ;;
        show) cmd_show ;;
        *) die "unknown verb: $1" ;;
    esac
}

main "$@"