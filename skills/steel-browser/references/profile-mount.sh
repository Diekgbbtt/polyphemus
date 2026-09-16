#!/usr/bin/env bash
# Operation family: server-side profile mounts - mount by name, settle, verify.
# Read-only by default; set WRITE=1 to accumulate state back on release.
# There is no CLI state poll, so a mount is proven by a settle pause plus a
# navigation, never by a READY field (none exists in `steel profile list`).
# Runnable verbatim through steel_exec(script=<text>, script_lang="sh") or `bash <file>`.
if [ -z "${BASH_VERSION:-}" ]; then exec bash "$0" "$@"; fi
set -euo pipefail

FLOW="profile"
PROFILE="${PROFILE:-}"
WRITE="${WRITE:-0}"
URL="${URL:-https://example.com}"
SESSION="${SESSION:-polymerhus-${FLOW}-$(date +%s)}"
STARTED=0

if [ -z "$PROFILE" ]; then
  echo "usage: PROFILE=<profile-name> [WRITE=1] $0" >&2
  exit 2
fi

release() {
  # The stop IS the persistence call: with --update-profile the release writes
  # the session state back; a read-only mount releases without writing.
  if [ "$STARTED" = 1 ]; then
    steel browser stop --session "$SESSION" --json >/dev/null 2>&1 || true
  fi
}
trap release EXIT INT TERM

if steel browser live --session "$SESSION" --json >/dev/null 2>&1; then
  echo "refused: $SESSION is already used" >&2
  exit 3
fi

# One live session per profile: the semantic name keeps this flow's session
# addressable, and the uniqueness oracle above keeps it from attaching to one.
if [ "$WRITE" = 1 ]; then
  START_JSON=$(steel browser start --session "$SESSION" --session-timeout 600000 --profile "$PROFILE" --update-profile --json)
else
  START_JSON=$(steel browser start --session "$SESSION" --session-timeout 600000 --profile "$PROFILE" --json)
fi
STARTED=1
printf '%s' "$START_JSON" | python3 -c \
  'import json,sys; d=json.load(sys.stdin)["data"]; print("mounted profile session", d["name"], "write-back", sys.argv[1])' "$WRITE"

# Settle-then-verify: pause for the server-side mount, then prove the session is
# usable by navigating. An unverified mount never passes a verdict.
sleep 3
NAV_JSON=$(steel browser navigate "$URL" --wait-until domcontentloaded --session "$SESSION" --json)
printf '%s' "$NAV_JSON" | python3 -c \
  'import json,sys; d=json.load(sys.stdin)["data"]; print("verified mount via", d["url"], "|", d["title"])'

echo "profile mount complete; the trap releases and persists on exit"
