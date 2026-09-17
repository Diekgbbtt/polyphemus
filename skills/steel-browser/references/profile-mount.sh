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
SESSION_NAMED=0

if [ -z "$PROFILE" ]; then
  echo "usage: PROFILE=<profile-name> [WRITE=1] bash $0" >&2
  exit 2
fi

release() {
  # The stop IS the persistence call: a WRITE=1 session releases its state back
  # into the profile; a read-only mount releases without writing. The mark is
  # set before `start` (past the catalogue guard), so a signal inside the start
  # window still gets a named stop; a name never created is a harmless no-op.
  if [ "$SESSION_NAMED" = 1 ]; then
    steel browser stop --session "$SESSION" --json >/dev/null 2>&1 || true
  fi
}
trap release EXIT INT TERM

# Catalogue guard (D13 amended). One live session per profile holds the last
# This read is also the pre-call baseline: a `default` seen here is foreign and
# never addressed by this run.
# writer, so the semantic name keeps this flow's session addressable.
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
if [ "$WRITE" = 1 ]; then
  START_JSON=$(steel browser start --session "$SESSION" --session-timeout 600000 --profile "$PROFILE" --update-profile --json)
else
  START_JSON=$(steel browser start --session "$SESSION" --session-timeout 600000 --profile "$PROFILE" --json)
fi
printf '%s' "$START_JSON" | python3 -c \
  'import json,sys; d=json.load(sys.stdin)["data"]; print("mounted profile session", d["name"], "write-back", sys.argv[1])' "$WRITE"

# Settle-then-verify: pause for the server-side mount, then prove the session is
# usable by navigating. An unverified mount never passes a verdict.
sleep 3
NAV_JSON=$(steel browser navigate "$URL" --wait-until domcontentloaded --session "$SESSION" --json)
printf '%s' "$NAV_JSON" | python3 -c \
  'import json,sys; d=json.load(sys.stdin)["data"]; print("verified mount via", d["url"], "|", d["title"])'

# Explicit stop (the persistence call) before the exit trap.
steel browser stop --session "$SESSION" --json >/dev/null
SESSION_NAMED=0
steel browser sessions --json | python3 -c '
import json,sys
names={s.get("name") for s in (json.load(sys.stdin).get("data") or []) if isinstance(s, dict)}
print("released:", sys.argv[1] not in names)
' "$SESSION"

echo "profile mount complete"
