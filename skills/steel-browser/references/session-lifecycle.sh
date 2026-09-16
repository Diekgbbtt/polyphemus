#!/usr/bin/env bash
# Operation family: session lifecycle - prove a name free, open, use, release.
# Runnable verbatim through steel_exec(script=<text>, script_lang="sh") or `bash <file>`.
# The tool never scans script text, so this script owns its own uniqueness guard
# (the `live` oracle) and its own stop (the EXIT trap) - both are the skill's duty.
# Re-exec through bash when invoked as `sh <file>` (dash has no `set -o pipefail`).
if [ -z "${BASH_VERSION:-}" ]; then exec bash "$0" "$@"; fi
set -euo pipefail

FLOW="lifecycle"
SESSION="${SESSION:-polymerhus-${FLOW}-$(date +%s)}"
STARTED=0

release() {
  # Trap-owned stop: fires on success, error, and signal alike. Guarded by
  # STARTED so a refused-before-start run never touches a stranger's session.
  if [ "$STARTED" = 1 ]; then
    steel browser stop --session "$SESSION" --json >/dev/null 2>&1 || true
  fi
}
trap release EXIT INT TERM

# Oracle (D13): `live` exits 0 iff the name is TAKEN; a free name prints the
# typed `No running session` error. Refuse loudly instead of attaching.
if steel browser live --session "$SESSION" --json >/dev/null 2>&1; then
  echo "refused: $SESSION is already used" >&2
  exit 3
fi

# Session lifetime 600000 ms outlives the script; the tool budget is 600 s wall clock.
START_JSON=$(steel browser start --session "$SESSION" --session-timeout 600000 --json)
STARTED=1
printf '%s' "$START_JSON" | python3 -c \
  'import json,sys; d=json.load(sys.stdin)["data"]; print("started", d["name"], "mode", d["mode"], "remainingMs", d.get("remainingMs"))'

NAV_JSON=$(steel browser navigate "https://example.com" --wait-until domcontentloaded --session "$SESSION" --json)
printf '%s' "$NAV_JSON" | python3 -c \
  'import json,sys; d=json.load(sys.stdin)["data"]; print("at", d["url"], "title", d["title"])'

echo "flow complete; the trap releases $SESSION on exit"
