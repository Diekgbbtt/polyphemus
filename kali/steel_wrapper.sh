#!/usr/bin/env bash
# The one Steel runtime edge (#395, D359-13).
#
# A local deployment sets STEEL_BROWSER_API_URL; this wrapper then supplies the
# global --local flag for `browser` and `scrape` commands and fixes the local
# user agent after a named `browser start`. A cloud deployment has no endpoint,
# so every argument passes through unchanged. The skill never learns either
# branch.
set -u

REAL="${STEEL_REAL_BINARY:-/opt/localbin/steel-real}"
ENDPOINT="${STEEL_BROWSER_API_URL:-}"
LOCAL_UA="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36"

if [ ! -x "$REAL" ]; then
  printf 'steel wrapper: real binary not executable: %s\n' "$REAL" >&2
  exit 127
fi

args=("$@")
family=""
is_start=0
after_family=0
has_mode_flag=0

for arg in "${args[@]}"; do
  case "$arg" in
    --local|--api-url|--api-url=*)
      has_mode_flag=1
      ;;
  esac
  if [ "$after_family" -eq 1 ]; then
    case "$arg" in
      start) is_start=1 ;;
    esac
    after_family=0
    continue
  fi
  case "$arg" in
    browser|scrape)
      family="$arg"
      after_family=1
      ;;
  esac
done

if [ -n "$ENDPOINT" ] && [ -n "$family" ] && [ "$has_mode_flag" -eq 0 ]; then
  args=("--local" "${args[@]}")
fi

session=""
want_session=0
for arg in "${args[@]}"; do
  if [ "$want_session" -eq 1 ]; then
    session="$arg"
    want_session=0
    continue
  fi
  case "$arg" in
    --session)
      want_session=1
      ;;
    --session=*)
      session="${arg#*=}"
      ;;
  esac
done

if [ -n "$ENDPOINT" ] && [ "$family" = "browser" ] && [ "$is_start" -eq 1 ] && [ -n "$session" ]; then
  envelope="$(mktemp)"
  trap 'rm -f "$envelope"' EXIT INT TERM
  "$REAL" "${args[@]}" >"$envelope"
  status=$?
  cat "$envelope"
  if [ "$status" -eq 0 ]; then
    "$REAL" browser set useragent --local --session "$session" --json "$LOCAL_UA" >/dev/null 2>&1 || true
  fi
  exit "$status"
fi

exec "$REAL" "${args[@]}"
