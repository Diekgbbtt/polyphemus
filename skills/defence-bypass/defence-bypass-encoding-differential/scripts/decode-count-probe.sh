#!/usr/bin/env bash
# decode-count-probe.sh - layer-one-step-at-a-time decode probe.
#
# Sends the same effect at increasing encode depths and records the control's
# verdict at each depth, so the layer where the checking side and the consuming
# side read the value differently is named from the recorded pair.
#
# Usage:
#   decode-count-probe.sh -u <url-with-FUZZ> [-t <plain-value>] [-d <max-depth>] [-H <header>]... [-w <seconds>]
#
#   -u  probe URL; the literal FUZZ is replaced by the layered value
#   -t  the plain hostile value to layer (default: probe)
#   -d  deepest encode layer to send, 0 through 5 (default: 3)
#   -H  extra request header, repeatable (for example a session cookie)
#   -w  wait in seconds between attempts (default: 0)
#   -h  print this header
#
# Read-only: the script issues GET requests only, never a state-changing verb,
# and writes nothing except its report on stdout.
# Dependencies: bash, curl, and coreutils only.
set -euo pipefail

usage() {
  sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'
}

url=""
token="probe"
max_depth="3"
wait_s="0"
headers=()

while [ "$#" -gt 0 ]; do
  case "$1" in
    -u) url="$2"; shift 2 ;;
    -t) token="$2"; shift 2 ;;
    -d) max_depth="$2"; shift 2 ;;
    -H) headers+=(-H "$2"); shift 2 ;;
    -w) wait_s="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) printf 'unknown option: %s\n' "$1" >&2; usage >&2; exit 2 ;;
  esac
done

[ -n "$url" ] || { printf 'missing -u\n' >&2; usage >&2; exit 2; }
case "$url" in
  http://*|https://*) ;;
  *) printf 'only http and https URLs are probed\n' >&2; exit 2 ;;
esac
case "$url" in
  *FUZZ*) ;;
  *) printf 'the URL must carry the FUZZ placeholder\n' >&2; exit 2 ;;
esac
case "$max_depth" in
  ''|*[!0-9]*) printf 'depth must be a whole number\n' >&2; exit 2 ;;
esac
[ "$max_depth" -le 5 ] || { printf 'depth is capped at 5\n' >&2; exit 2; }
case "$wait_s" in
  ''|*[!0-9.]*) printf 'wait must be a number of seconds\n' >&2; exit 2 ;;
esac

pct_encode() {
  local s="$1" out="" ch i
  for ((i = 0; i < ${#s}; i++)); do
    ch="${s:i:1}"
    case "$ch" in
      [A-Za-z0-9._~-]) out+="$ch" ;;
      *) out+="$(printf '%%%02X' "'$ch")" ;;
    esac
  done
  printf '%s' "$out"
}

verdict() {
  local target="$1" line
  if line="$(curl -s -o /dev/null -w '%{http_code} %{size_download} %{time_total}' \
      --max-time 20 "${headers[@]+"${headers[@]}"}" "$target" 2>/dev/null)"; then
    printf '%s' "$line"
  else
    printf 'error 0 0'
  fi
}

layered="$token"
baseline=""
layer=0

while [ "$layer" -le "$max_depth" ]; do
  target="${url//FUZZ/$layered}"
  line="$(verdict "$target")"
  stable="${line% *}"
  if [ "$layer" -eq 0 ]; then
    baseline="$stable"
    note="baseline"
  elif [ "$stable" = "$baseline" ]; then
    note="matches baseline"
  else
    note="divergence"
  fi
  printf 'layer %s  %-32s -> %s  (%s)\n' "$layer" "$layered" "$line" "$note"
  [ "$wait_s" = "0" ] || sleep "$wait_s"
  layered="$(pct_encode "$layered")"
  layer=$((layer + 1))
done

printf '%s\n' '---'
printf 'a layer marked divergence names the decode step where the two readings part\n'
printf 'record both readings for a divergence: the benign one the check consumed and the sink effect\n'
