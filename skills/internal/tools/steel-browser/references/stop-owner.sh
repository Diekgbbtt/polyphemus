#!/usr/bin/env bash
# Operation family: the multi-call stop owner.
# A `trap` owns a stop only when the whole flow runs inside ONE invocation; a
# flow that spans separate `steel_exec` calls arms a dead-man watchdog here
# instead, and defuses it when the flow ends. The alternative owner is a
# wrapper script that runs the whole flow so a trap can span it.
# Runnable verbatim through steel_exec(script=<text>, script_lang="sh") or `bash <file>`.
# Usage: [SESSION=polymerhus-flow-<id>] [GRACE=300] bash stop-owner.sh [arm|defuse|status]
if [ -z "${BASH_VERSION:-}" ]; then exec bash "$0" "$@"; fi
set -euo pipefail

MODE="${1:-arm}"
SESSION="${SESSION:-polymerhus-flow-$(date +%s)}"
GRACE="${GRACE:-300}"
PIDFILE="${PIDFILE:-$SESSION.watchdog.pid}"

case "$MODE" in
  arm)
    if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
      echo "watchdog already armed pid=$(cat "$PIDFILE") session=$SESSION"
      exit 0
    fi
    # The watchdog fires only if the flow never reaches `defuse`: a bounded
    # grace period, then a named stop. It runs detached, so it outlives the
    # shell invocation that armed it.
    nohup bash -c 'sleep "$1"; steel browser stop --session "$2" --json >/dev/null 2>&1' \
      stop-owner "$GRACE" "$SESSION" >/dev/null 2>&1 &
    echo "$!" > "$PIDFILE"
    echo "watchdog armed pid=$! grace=${GRACE}s session=$SESSION"
    ;;
  defuse)
    if [ -f "$PIDFILE" ]; then
      pid=$(cat "$PIDFILE")
      kill "$pid" 2>/dev/null || true
      rm -f "$PIDFILE"
      echo "watchdog defused pid=$pid session=$SESSION"
    else
      echo "no watchdog armed session=$SESSION"
    fi
    ;;
  status)
    if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
      echo "watchdog armed pid=$(cat "$PIDFILE") session=$SESSION"
    else
      echo "watchdog not armed session=$SESSION"
    fi
    ;;
  *)
    echo "usage: bash $0 [arm|defuse|status]" >&2
    exit 2
    ;;
esac
