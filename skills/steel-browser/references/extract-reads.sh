#!/usr/bin/env bash
# Operation family: extraction reads - cookies, storage, URL, and bounded eval.
# Every read is projected before it returns (names, counts, slices), so no read
# dumps a whole cookie jar or document into context, and no value is printed.
# Runnable verbatim through steel_exec(script=<text>, script_lang="sh") or `bash <file>`.
if [ -z "${BASH_VERSION:-}" ]; then exec bash "$0" "$@"; fi
set -euo pipefail

FLOW="extract"
URL="${URL:-https://the-internet.herokuapp.com/}"
SESSION="${SESSION:-polymerhus-${FLOW}-$(date +%s)}"
STARTED=0

release() {
  if [ "$STARTED" = 1 ]; then
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

START_JSON=$(steel browser start --session "$SESSION" --session-timeout 600000 --json)
STARTED=1
printf '%s' "$START_JSON" | python3 -c \
  'import json,sys; d=json.load(sys.stdin)["data"]; print("started", d["name"])'

steel browser navigate "$URL" --wait-until domcontentloaded --session "$SESSION" --json >/dev/null

# Cookie read: the count and the cookie NAMES only. Values are target secrets in
# flight; they stay out of stdout and out of the trace.
steel browser cookies --session "$SESSION" --json | python3 -c '
import json,sys
cookies=json.load(sys.stdin)["data"] or []
print("cookies:", len(cookies), "names:", ",".join(sorted(c["name"] for c in cookies)))
'

# Storage reads: shape and key count, never a value dump.
for scope in local session; do
  steel browser storage "$scope" --session "$SESSION" --json | python3 -c '
import json,sys
scope=sys.argv[1]
data=json.load(sys.stdin).get("data") or {}
print("storage " + scope + ":", "empty" if not data else str(len(data)) + " keys")
' "$scope"
done

# URL read through eval (the verification primitive).
steel browser eval 'window.location.href' --session "$SESSION" --json \
  | python3 -c 'import json,sys; print("eval url ->", json.load(sys.stdin)["data"])'

# Projected eval read: a count, not the matched nodes.
steel browser eval 'document.querySelectorAll("a").length' --session "$SESSION" --json \
  | python3 -c 'import json,sys; print("eval link count ->", json.load(sys.stdin)["data"])'

# Explicit stop, then prove the name is gone; the trap is the backstop.
steel browser stop --session "$SESSION" --json >/dev/null
STARTED=0
steel browser sessions --json | python3 -c '
import json,sys
names={s.get("name") for s in (json.load(sys.stdin).get("data") or []) if isinstance(s, dict)}
print("released:", sys.argv[1] not in names)
' "$SESSION"

echo "extraction complete"
