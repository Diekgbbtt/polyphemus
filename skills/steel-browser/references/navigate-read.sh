#!/usr/bin/env bash
# Operation family: navigation and page reading - go somewhere, then read back
# where you are (title, URL, a bounded slice of the accessibility tree).
# Runnable verbatim through steel_exec(script=<text>, script_lang="sh") or `bash <file>`.
if [ -z "${BASH_VERSION:-}" ]; then exec bash "$0" "$@"; fi
set -euo pipefail

FLOW="nav"
URL="${URL:-https://quotes.toscrape.com}"
SESSION="${SESSION:-polymerhus-${FLOW}-$(date +%s)}"
STARTED=0

release() {
  if [ "$STARTED" = 1 ]; then
    steel browser stop --session "$SESSION" --json >/dev/null 2>&1 || true
  fi
}
trap release EXIT INT TERM

if steel browser live --session "$SESSION" --json >/dev/null 2>&1; then
  echo "refused: $SESSION is already used" >&2
  exit 3
fi

START_JSON=$(steel browser start --session "$SESSION" --session-timeout 600000 --json)
STARTED=1
printf '%s' "$START_JSON" | python3 -c \
  'import json,sys; d=json.load(sys.stdin)["data"]; print("started", d["name"], "mode", d["mode"])'

# navigate returns {title, url}; --wait-until gates on the load state.
NAV_JSON=$(steel browser navigate "$URL" --wait-until domcontentloaded --session "$SESSION" --json)
printf '%s' "$NAV_JSON" | python3 -c \
  'import json,sys; d=json.load(sys.stdin)["data"]; print("navigated", d["url"], "|", d["title"])'

# Page reading primitives: dedicated getters, then a compact tree slice.
TITLE_JSON=$(steel browser get title --session "$SESSION" --json)
URL_JSON=$(steel browser get url --session "$SESSION" --json)
printf '%s' "$TITLE_JSON" | python3 -c 'import json,sys; print("get title ->", json.load(sys.stdin)["data"])'
printf '%s' "$URL_JSON" | python3 -c 'import json,sys; print("get url ->", json.load(sys.stdin)["data"])'

# Bounded read: only the count and the first few interactive lines, never the
# whole tree, so the tool result never explodes agent context.
SNAP_JSON=$(steel browser snapshot -i -c --session "$SESSION" --json)
printf '%s' "$SNAP_JSON" | python3 -c '
import json,sys
lines=json.load(sys.stdin)["data"].splitlines()
print("interactive nodes:", len(lines))
for line in lines[:5]:
    print("  " + line)
'

echo "read complete; the trap releases $SESSION on exit"
