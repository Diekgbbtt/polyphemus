#!/usr/bin/env bash
# Allowlist the Steel API port at Docker's DOCKER-USER chain (#359, D359-3).
#
# The Steel API has no authentication, and the deployment host is exposed to
# the internet. Restrict inbound TCP 3000 to the polymerhus eval server and the
# operator's admin addresses. Rules are installed in a dedicated chain, jumped
# from DOCKER-USER, for both IPv4 (iptables) and IPv6 (ip6tables).
#
# Usage:
#   sudo ./allowlist.sh <source> [<source> ...]
#   sudo ./allowlist.sh --remove
#
# <source> is an IPv4 or IPv6 address or CIDR, for example:
#   sudo ./allowlist.sh 46.224.225.245 2a04:ee40:214a:f500:9ce6:f07f:fafd:4b6b
#
# The script is idempotent: it flushes and rebuilds its own chain, so a re-run
# with a different source list replaces the old one and never duplicates the
# DOCKER-USER jump. Any table without a source denies all TCP 3000 traffic
# (fail closed).
#
# Environment:
#   STEEL_PORT  the API port (default 3000)
set -euo pipefail

PORT="${STEEL_PORT:-3000}"
CHAIN="POLYMERHUS-STEEL"
REMOVE=0
SOURCES=()

usage() {
  sed -n '2,22p' "$0" | sed 's/^# \{0,1\}//'
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --remove)
      REMOVE=1
      shift
      ;;
    --port)
      if [ "$#" -lt 2 ]; then
        echo "allowlist: --port needs a value" >&2
        exit 2
      fi
      PORT="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    --)
      shift
      while [ "$#" -gt 0 ]; do
        SOURCES+=("$1")
        shift
      done
      ;;
    -*)
      echo "allowlist: unknown option: $1" >&2
      exit 2
      ;;
    *)
      SOURCES+=("$1")
      shift
      ;;
  esac
done

if [ "$(id -u)" -ne 0 ]; then
  echo "allowlist: run as root (sudo)" >&2
  exit 1
fi

if [ "$REMOVE" -eq 0 ] && [ "${#SOURCES[@]}" -eq 0 ]; then
  echo "allowlist: at least one allowed source is required" >&2
  usage >&2
  exit 2
fi

if ! [[ "$PORT" =~ ^[0-9]+$ ]] || [ "$PORT" -lt 1 ] || [ "$PORT" -gt 65535 ]; then
  echo "allowlist: invalid port: $PORT" >&2
  exit 2
fi

source_family() {
  case "$1" in
    *:*) echo 6 ;;
    *) echo 4 ;;
  esac
}

is_address() {
  case "$1" in
    *[!0-9a-fA-F:./]*) return 1 ;;
    *:*|*.*) return 0 ;;
    *) return 1 ;;
  esac
}

for src in "${SOURCES[@]}"; do
  if ! is_address "$src"; then
    echo "allowlist: not an IP address or CIDR: $src" >&2
    exit 2
  fi
done

table_cmd() {
  if [ "$1" -eq 6 ]; then
    echo ip6tables
  else
    echo iptables
  fi
}

ensure_docker_user() {
  local ipt="$1"
  if ! "$ipt" -w 5 -S DOCKER-USER >/dev/null 2>&1; then
    echo "allowlist: $ipt has no DOCKER-USER chain (is Docker running?)" >&2
    exit 1
  fi
}

remove_table() {
  local ipt="$1"
  if ! "$ipt" -w 5 -S DOCKER-USER >/dev/null 2>&1; then
    return 0
  fi
  while "$ipt" -w 5 -C DOCKER-USER -j "$CHAIN" >/dev/null 2>&1; do
    "$ipt" -w 5 -D DOCKER-USER -j "$CHAIN"
  done
  if "$ipt" -w 5 -S "$CHAIN" >/dev/null 2>&1; then
    "$ipt" -w 5 -F "$CHAIN"
    "$ipt" -w 5 -X "$CHAIN"
  fi
}

apply_table() {
  local ipt="$1"
  shift
  ensure_docker_user "$ipt"
  if "$ipt" -w 5 -S "$CHAIN" >/dev/null 2>&1; then
    "$ipt" -w 5 -F "$CHAIN"
  else
    "$ipt" -w 5 -N "$CHAIN"
  fi
  # Keep exactly one jump, at the top of DOCKER-USER, on every run.
  while "$ipt" -w 5 -C DOCKER-USER -j "$CHAIN" >/dev/null 2>&1; do
    "$ipt" -w 5 -D DOCKER-USER -j "$CHAIN"
  done
  "$ipt" -w 5 -I DOCKER-USER 1 -j "$CHAIN"
  # The allowed sources first, then deny everything else on the port. Traffic
  # for other ports returns from the chain and continues down DOCKER-USER.
  local src
  for src in "$@"; do
    "$ipt" -w 5 -A "$CHAIN" -p tcp --dport "$PORT" -s "$src" -j ACCEPT
  done
  "$ipt" -w 5 -A "$CHAIN" -p tcp --dport "$PORT" -j DROP
  echo "allowlist: $ipt TCP $PORT accepts ${*:-<none>} and drops the rest"
}

if [ "$REMOVE" -eq 1 ]; then
  remove_table iptables
  remove_table ip6tables
  echo "allowlist: removed the Steel rules"
  exit 0
fi

V4=()
V6=()
for src in "${SOURCES[@]}"; do
  if [ "$(source_family "$src")" -eq 6 ]; then
    V6+=("$src")
  else
    V4+=("$src")
  fi
done

apply_table iptables "${V4[@]}"
apply_table ip6tables "${V6[@]}"
