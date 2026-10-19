#!/usr/bin/env bash
# axis-probe.sh - one-axis-per-attempt matcher probe.
#
# Sends the refused spelling of an effect once, then one candidate spelling per
# attempt along a single axis, and prints the control's verdict for each so the
# admitting axis is attributable from the recorded pair.
#
# Usage:
#   axis-probe.sh -u <url-with-FUZZ> [-t <refused-token>] [-a <axis>] [-H <header>]... [-w <seconds>]
#
#   -u  probe URL; the literal FUZZ is replaced by each candidate spelling
#   -t  the refused spelling the candidates derive from (default: probe)
#   -a  axis to sweep: case | split | whitespace | encode | all (default: all)
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
axis="all"
wait_s="0"
headers=()

while [ "$#" -gt 0 ]; do
  case "$1" in
    -u) url="$2"; shift 2 ;;
    -t) token="$2"; shift 2 ;;
    -a) axis="$2"; shift 2 ;;
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

emit() {
  local label="$1" value="$2" target verdict_line
  target="${url//FUZZ/$value}"
  verdict_line="$(verdict "$target")"
  printf '%-10s %-28s -> %s\n' "$label" "$value" "$verdict_line"
  [ "$wait_s" = "0" ] || sleep "$wait_s"
}

case_variants() {
  printf '%s\n' "$token"
  printf '%s\n' "$(printf '%s' "$token" | tr '[:lower:]' '[:upper:]')"
  printf '%s\n' "$(printf '%s' "$token" | tr '[:upper:]' '[:lower:]')"
  printf '%s\n' "$(printf '%s' "$token" | tr 'a-zA-Z' 'A-Za-z')"
}

split_variants() {
  local i
  for ((i = 1; i < ${#token} - 1; i++)); do
    printf "%s'%s'\n" "${token:0:i}" "${token:i}"
    printf '%s"%s"\n' "${token:0:i}" "${token:i}"
  done
}

whitespace_variants() {
  printf '%s\n' "$(pct_encode "$token")"
  printf '%s\n' "$(printf '%s' "$token" | sed 's/ /%09/g')"
  printf '%s\n' "$(printf '%s' "$token" | sed 's/ /+/g')"
  printf '%s\n' "$(printf '%s' "$token" | sed 's/ /%0A/g')"
}

encode_variants() {
  local once twice
  once="$(pct_encode "$token")"
  printf '%s\n' "$once"
  twice="$(pct_encode "$once")"
  [ "$twice" = "$once" ] || printf '%s\n' "$twice"
}

printf 'baseline   %-28s -> %s\n' "$token" "$(verdict "${url//FUZZ/$token}")"
printf '%s\n' '---'

case "$axis" in
  case) case_variants | while IFS= read -r candidate; do emit case "$candidate"; done ;;
  split) split_variants | while IFS= read -r candidate; do emit split "$candidate"; done ;;
  whitespace) whitespace_variants | while IFS= read -r candidate; do emit whitespace "$candidate"; done ;;
  encode) encode_variants | while IFS= read -r candidate; do emit encode "$candidate"; done ;;
  all)
    case_variants | while IFS= read -r candidate; do emit case "$candidate"; done
    split_variants | while IFS= read -r candidate; do emit split "$candidate"; done
    whitespace_variants | while IFS= read -r candidate; do emit whitespace "$candidate"; done
    encode_variants | while IFS= read -r candidate; do emit encode "$candidate"; done
    ;;
  *) printf 'unknown axis: %s\n' "$axis" >&2; exit 2 ;;
esac

printf '%s\n' '---'
printf 'a candidate whose verdict differs from the baseline names the axis to re-probe alone\n'
printf 'a candidate whose verdict matches the baseline is recorded as a refusal, not a dead end\n'
