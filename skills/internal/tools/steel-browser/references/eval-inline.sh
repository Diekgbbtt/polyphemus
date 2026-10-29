#!/usr/bin/env bash
# Operation family: inline JS evaluation - the quoting patterns and the
# projection rule. `eval` runs one JS expression per call (no --file, no stdin);
# a proven snippet graduates into a script, never the default.
# Runnable verbatim through steel_exec(script=<text>, script_lang="sh") or `bash <file>`.
if [ -z "${BASH_VERSION:-}" ]; then exec bash "$0" "$@"; fi
set -euo pipefail

FLOW="eval"
URL="${URL:-https://quotes.toscrape.com}"
SESSION="${SESSION:-polymerhus-${FLOW}-$(date +%s)}"
SESSION_OWNED=0

release() {
  # Fires on success, error, and signal alike. Ownership is marked only after
  # `start` returns success: a `session_taken` denial means the name is foreign,
  # so the trap must not stop it. A signal inside the start window can orphan a
  # just-created session; the finite session clock reaps it. The explicit stop
  # below clears the mark so the trap no-ops on the happy path.
  if [ "$SESSION_OWNED" = 1 ]; then
    steel browser stop --session "$SESSION" --json >/dev/null 2>&1 || true
  fi
}
trap release EXIT INT TERM

# Catalogue guard (D13 amended).
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

START_JSON=$(steel browser start --session "$SESSION" --session-timeout 600000 --inactivity-timeout 300000 --json)
SESSION_OWNED=1
printf '%s' "$START_JSON" | python3 -c \
  'import json,sys; d=json.load(sys.stdin)["data"]; print("started", d["name"])'

steel browser navigate "$URL" --wait-until domcontentloaded --session "$SESSION" --json >/dev/null

run_eval() {
  steel browser eval "$1" --session "$SESSION" --json \
    | python3 -c 'import json,sys; print("  ->", json.dumps(json.load(sys.stdin).get("data")))'
}

# Plain read: single quotes so the shell never expands the JS.
echo "read:"; run_eval 'document.title'

# Projection before return: map, slice, JSON.stringify - a bounded result.
echo "projection:"; run_eval 'JSON.stringify(Array.from(document.querySelectorAll("a[href]")).slice(0,3).map(a => a.getAttribute("href")))'

# IIFE returning plain data: eval serialises an object result as JSON.
echo "iife:"; run_eval '(() => ({title: document.title, links: document.querySelectorAll("a").length}))()'

# Single quotes carry `$` and backticks verbatim; double quotes would expand them.
echo "dollar-and-backtick:"; run_eval '`${document.title} / ${document.querySelectorAll("a").length}`'

# Two live traps: a path argument parses as a regex literal (pass JS source,
# never a file path), and a bare `-` evaluates as source and raises.
# Prefer a boolean for a check, a count for a census, a slice for a shape.

# Explicit stop, then prove the name is gone; the trap is the backstop.
steel browser stop --session "$SESSION" --json >/dev/null
SESSION_OWNED=0
steel browser sessions --json | python3 -c '
import json,sys
names={s.get("name") for s in (json.load(sys.stdin).get("data") or []) if isinstance(s, dict)}
print("released:", sys.argv[1] not in names)
' "$SESSION"

echo "eval complete"
