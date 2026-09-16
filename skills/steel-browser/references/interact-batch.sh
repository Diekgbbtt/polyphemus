#!/usr/bin/env bash
# Operation family: interaction - snapshot for refs, then act in ONE batch.
# Text entry rides a batch because standalone `fill`/`type`/`setvalue` answer
# `Unknown ref: eN` on CLI 0.4.4 (the ref never resolves on the single-command path).
# A runtime VALUE is interpolated through the shell as "${VALUE}" - variable
# expansion never re-expands a `$` or backtick inside the value's contents, so
# this is the safe form; only a literal value would need single-quoting. The
# read-back prints a boolean, never the value.
# Runnable verbatim through steel_exec(script=<text>, script_lang="sh") or `bash <file>`.
if [ -z "${BASH_VERSION:-}" ]; then exec bash "$0" "$@"; fi
set -euo pipefail

FLOW="interact"
URL="${URL:-https://the-internet.herokuapp.com/inputs}"
VALUE="${VALUE:-42}"
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

# Explicit synchronisation with steel's own clock: --timeout 15000 ms sits well
# below the tool's 600000 ms budget, so the outer clock never cuts the wait short.
steel browser wait --load-state networkidle --timeout 15000 --session "$SESSION" --json \
  | python3 -c 'import json,sys; print("wait ->", "ok" if json.load(sys.stdin).get("success") else "not ok")'

# Discover the ref from the snapshot, then act in a batch whose FIRST element is
# a fresh `snapshot -i`. Within one document the ref registry is append-only, so
# the ref just read still resolves; across a navigate it would be silently rebound.
# The ref sits anywhere in the attribute list (`[ref=eN]` alone, or `[required,
# ref=eN]`), so match `ref=(\w+)` rather than anchoring on the opening bracket.
SNAP_JSON=$(steel browser snapshot -i --session "$SESSION" --json)
REF=$(printf '%s' "$SNAP_JSON" | python3 -c '
import json,sys,re
tree=json.load(sys.stdin)["data"]
m=re.search(r"-\s+spinbutton\b[^\n]*ref=(\w+)\]", tree)
print(m.group(1) if m else "MISS")
')
if [ "$REF" = "MISS" ]; then
  echo "ref not found in snapshot" >&2
  exit 4
fi

# One batch: a fresh snapshot, then the batch-routed text entry. Results are
# reported by op index and success, plus one deliberate exception on failure -
# a bounded typed `error`. The result envelope also echoes each `command`
# string, and a text-entry command carries its value, so that field is never
# printed; the `error` field names the failure without it.
BATCH_JSON=$(steel browser batch 'snapshot -i' "fill @${REF} ${VALUE}" --session "$SESSION" --json)
printf '%s' "$BATCH_JSON" | python3 -c '
import json,sys
d=json.load(sys.stdin)
data=d.get("data") if isinstance(d.get("data"), dict) else {}
results=data.get("results", [])
print("batch success:", d.get("success"), "| ops:", len(results))
for i,r in enumerate(results):
    status="ok" if r.get("success") else "FAIL"
    line="  op %d %s" % (i, status)
    if not r.get("success") and r.get("error"):
        line += " | " + str(r["error"])[:80]
    print(line)
'

# Verify the entry landed by reading the value back, and print only whether it
# matches - the value itself stays out of stdout.
steel browser get value 'input' --session "$SESSION" --json | python3 -c '
import json,sys
d=json.load(sys.stdin).get("data")
got=d.get("value") if isinstance(d, dict) else d
print("entry landed:", got == sys.argv[1])
' "$VALUE"

# Explicit stop, then prove the name is gone; the trap is the backstop.
steel browser stop --session "$SESSION" --json >/dev/null
STARTED=0
steel browser sessions --json | python3 -c '
import json,sys
names={s.get("name") for s in (json.load(sys.stdin).get("data") or []) if isinstance(s, dict)}
print("released:", sys.argv[1] not in names)
' "$SESSION"

echo "interaction complete"
