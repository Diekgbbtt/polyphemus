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
SESSION_NAMED=0

release() {
  # Trap-owned stop: fires on success, error, and signal alike. SESSION_NAMED is
  # set once the name is marked free (past the catalogue guard) and BEFORE
  # `start`, so a signal landing inside the start window still gets a named stop;
  # a name never created is a harmless no-op. A refusal leaves the mark down, so
  # a stranger's live name is never addressed, and the explicit stop below clears
  # the mark so the trap no-ops on the happy path.
  if [ "$SESSION_NAMED" = 1 ]; then
    steel browser stop --session "$SESSION" --json >/dev/null 2>&1 || true
  fi
}
trap release EXIT INT TERM

# Survey: one catalogue read answers the name question (D13 amended) and is the
# pre-call baseline for `default` attribution - a `default` here is foreign, so
# this run never addresses it; only a `default` that appears because of our call
# would be ours to stop by name.
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

# Mark the name before `start`: the stop decision rides this mark, never a flag
# set only after `start` returns, so a signal inside the start window is not
# orphaned. Session lifetime 600000 ms outlives the script; provisioning consumes
# part of it before the receipt, so remainingMs lands below what was requested.
SESSION_NAMED=1
START_JSON=$(steel browser start --session "$SESSION" --session-timeout 600000 --json)
printf '%s' "$START_JSON" | python3 -c \
  'import json,sys; d=json.load(sys.stdin)["data"]; print("started", d["name"], "mode", d["mode"], "remainingMs", d.get("remainingMs"))'

NAV_JSON=$(steel browser navigate "$URL" --wait-until domcontentloaded --session "$SESSION" --json)
printf '%s' "$NAV_JSON" | python3 -c \
  'import json,sys; d=json.load(sys.stdin)["data"]; print("at", d["url"], "title", d["title"])'

# Explicit stop first, so this run proves the catalogue clean itself; the trap
# stays armed as the backstop on the error and signal paths.
steel browser stop --session "$SESSION" --json >/dev/null
SESSION_NAMED=0
steel browser sessions --json | python3 -c '
import json,sys
names={s.get("name") for s in (json.load(sys.stdin).get("data") or []) if isinstance(s, dict)}
print("released:", sys.argv[1] not in names)
' "$SESSION"

echo "lifecycle complete"
