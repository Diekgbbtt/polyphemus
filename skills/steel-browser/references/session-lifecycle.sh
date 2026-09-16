#!/usr/bin/env bash
# Operation family: session lifecycle - survey the catalogue, open a free name,
# use it, release under a trap, prove the catalogue clean.
# Runnable verbatim through steel_exec(script=<text>, script_lang="sh") or `bash <file>`.
# Script text is never scanned, so this script owns its own name guard (the
# catalogue) and its own stop (the trap).
if [ -z "${BASH_VERSION:-}" ]; then exec bash "$0" "$@"; fi
set -euo pipefail

FLOW="lifecycle"
URL="${URL:-https://example.com}"
SESSION="${SESSION:-polymerhus-${FLOW}-$(date +%s)}"
STARTED=0

release() {
  # Trap-owned stop: fires on success, error, and signal alike. STARTED keeps a
  # refused-before-start run from touching a stranger's session, and the
  # explicit stop below clears it so the trap no-ops on the happy path.
  if [ "$STARTED" = 1 ]; then
    steel browser stop --session "$SESSION" --json >/dev/null 2>&1 || true
  fi
}
trap release EXIT INT TERM

# Survey: one catalogue read answers the name question (D13 amended) and shows
# what else is live, so a foreign `default` is never mistaken for ours.
CATA_JSON=$(steel browser sessions --json)
printf '%s' "$CATA_JSON" | python3 -c '
import json,sys
data=json.load(sys.stdin).get("data") or []
names=sorted(s["name"] for s in data if isinstance(s, dict) and s.get("name"))
print("live sessions:", len(data), "| names:", ",".join(names) or "none")
'
if printf '%s' "$CATA_JSON" | python3 -c '
import json,sys
data=json.load(sys.stdin).get("data") or []
names={s.get("name") for s in data if isinstance(s, dict)}
sys.exit(0 if sys.argv[1] in names else 1)
' "$SESSION"; then
  echo "refused: $SESSION is already live" >&2
  exit 3
fi

# Session lifetime 600000 ms outlives the script; provisioning consumes part of
# it before the receipt, so remainingMs lands below what was requested.
START_JSON=$(steel browser start --session "$SESSION" --session-timeout 600000 --json)
STARTED=1
printf '%s' "$START_JSON" | python3 -c \
  'import json,sys; d=json.load(sys.stdin)["data"]; print("started", d["name"], "mode", d["mode"], "remainingMs", d.get("remainingMs"))'

NAV_JSON=$(steel browser navigate "$URL" --wait-until domcontentloaded --session "$SESSION" --json)
printf '%s' "$NAV_JSON" | python3 -c \
  'import json,sys; d=json.load(sys.stdin)["data"]; print("at", d["url"], "title", d["title"])'

# Explicit stop first, so this run proves the catalogue clean itself; the trap
# stays armed as the backstop on the error and signal paths.
steel browser stop --session "$SESSION" --json >/dev/null
STARTED=0
steel browser sessions --json | python3 -c '
import json,sys
names={s.get("name") for s in (json.load(sys.stdin).get("data") or []) if isinstance(s, dict)}
print("released:", sys.argv[1] not in names)
' "$SESSION"

echo "lifecycle complete"
