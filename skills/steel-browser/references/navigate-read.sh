#!/usr/bin/env bash
# Operation family: navigation and page reading - go somewhere, then read back
# where you are (title, URL, a bounded slice of the accessibility tree).
# Runnable verbatim through steel_exec(script=<text>, script_lang="sh") or `bash <file>`.
if [ -z "${BASH_VERSION:-}" ]; then exec bash "$0" "$@"; fi
set -euo pipefail

FLOW="nav"
URL="${URL:-https://quotes.toscrape.com}"
SESSION="${SESSION:-polymerhus-${FLOW}-$(date +%s)}"
SESSION_NAMED=0

release() {
  # Fires on success, error, and signal alike. The mark is set before `start`
  # (past the catalogue guard), so a signal inside the start window still gets a
  # named stop; a name never created is a harmless no-op, and the explicit stop
  # below clears the mark so the trap no-ops on the happy path.
  if [ "$SESSION_NAMED" = 1 ]; then
    steel browser stop --session "$SESSION" --json >/dev/null 2>&1 || true
  fi
}
trap release EXIT INT TERM

# Catalogue guard (D13 amended): the live list is the source of truth for a name.
# This read is also the pre-call baseline: a `default` seen here is foreign and
# never addressed by this run.
if steel browser sessions --json 2>/dev/null | python3 -c '
import json,sys
try:
    names={s.get("name") for s in (json.load(sys.stdin).get("data") or []) if isinstance(s, dict)}
except Exception:
    sys.exit(1)  # cannot verify -> treat as free, never block the start
sys.exit(0 if sys.argv[1] in names else 1)
' "$SESSION"; then
  echo "refused: $SESSION is already live" >&2
  exit 3
fi

SESSION_NAMED=1
START_JSON=$(steel browser start --session "$SESSION" --session-timeout 600000 --json)
printf '%s' "$START_JSON" | python3 -c \
  'import json,sys; d=json.load(sys.stdin)["data"]; print("started", d["name"], "mode", d["mode"])'

# navigate returns {title, url}; --wait-until gates on the load state.
NAV_JSON=$(steel browser navigate "$URL" --wait-until domcontentloaded --session "$SESSION" --json)
printf '%s' "$NAV_JSON" | python3 -c \
  'import json,sys; d=json.load(sys.stdin)["data"]; print("navigated", d["url"], "|", d["title"])'

# Page-reading primitives: dedicated getters, then a compact tree slice.
steel browser get title --session "$SESSION" --json \
  | python3 -c 'import json,sys; d=json.load(sys.stdin)["data"]; print("get title ->", d.get("title", d) if isinstance(d, dict) else d)'
steel browser get url --session "$SESSION" --json \
  | python3 -c 'import json,sys; d=json.load(sys.stdin)["data"]; print("get url ->", d.get("url", d) if isinstance(d, dict) else d)'

# Projected read: only the count and the first few interactive lines, never the
# whole tree, so the result never explodes context.
steel browser snapshot -i -c --session "$SESSION" --json | python3 -c '
import json,sys
lines=json.load(sys.stdin)["data"].splitlines()
print("interactive nodes:", len(lines))
for line in lines[:5]:
    print("  " + line)
'

# Explicit stop, then prove the name is gone; the trap is the backstop.
steel browser stop --session "$SESSION" --json >/dev/null
SESSION_NAMED=0
steel browser sessions --json | python3 -c '
import json,sys
names={s.get("name") for s in (json.load(sys.stdin).get("data") or []) if isinstance(s, dict)}
print("released:", sys.argv[1] not in names)
' "$SESSION"

echo "read complete"
