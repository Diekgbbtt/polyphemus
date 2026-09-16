#!/usr/bin/env bash
# Operation family: inline JS evaluation - the escaping patterns and the
# result-bounding rule. `eval` runs one JS expression per call (no --file, no
# stdin); files are the promotion path for a proven snippet, never the default.
# Runnable verbatim through steel_exec(script=<text>, script_lang="sh") or `bash <file>`.
if [ -z "${BASH_VERSION:-}" ]; then exec bash "$0" "$@"; fi
set -euo pipefail

FLOW="eval"
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
  'import json,sys; d=json.load(sys.stdin)["data"]; print("started", d["name"])'

steel browser navigate "$URL" --wait-until domcontentloaded --session "$SESSION" --json >/dev/null

run_eval() {
  steel browser eval "$1" --session "$SESSION" --json \
    | python3 -c 'import json,sys; print("  ->", json.dumps(json.load(sys.stdin).get("data")))'
}

# Plain read: wrap in single quotes so the shell never expands the JS.
echo "read:"; run_eval 'document.title'

# Projection before return: map, slice, JSON.stringify - a bounded result.
echo "projection:"; run_eval 'JSON.stringify(Array.from(document.querySelectorAll("a[href]")).slice(0,3).map(a => a.getAttribute("href")))'

# IIFE returning plain data: eval serialises an object result as JSON.
echo "iife:"; run_eval '(() => ({title: document.title, links: document.querySelectorAll("a").length}))()'

# $ and backticks survive inside single quotes; double quotes would expand $.
echo "dollar-and-backtick:"; run_eval '`${document.title} / ${document.querySelectorAll("a").length}`'

# Two live traps, kept in mind, never depended upon:
#   1. a path argument parses as a regex literal (pass JS source, never a file path);
#   2. a bare `-` evaluates as source and raises a SyntaxError.
# Prefer a boolean for a check, a count for a census, a slice for a shape.

echo "eval complete; the trap releases $SESSION on exit"
