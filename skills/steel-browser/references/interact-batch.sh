#!/usr/bin/env bash
# Operation family: interaction - snapshot for refs, then act in ONE batch.
# Text entry is batch-routed because standalone `fill`/`type`/`setvalue` return
# `Unknown ref: eN` on CLI 0.4.4 (the ref never resolves on the single-command path).
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

if steel browser live --session "$SESSION" --json >/dev/null 2>&1; then
  echo "refused: $SESSION is already used" >&2
  exit 3
fi

START_JSON=$(steel browser start --session "$SESSION" --session-timeout 600000 --json)
STARTED=1
printf '%s' "$START_JSON" | python3 -c \
  'import json,sys; d=json.load(sys.stdin)["data"]; print("started", d["name"])'

steel browser navigate "$URL" --wait-until domcontentloaded --session "$SESSION" --json >/dev/null

# Explicit synchronisation with steel's own clock: --timeout 15000 ms sits well
# below the tool's 600000 ms budget, so the tool clock never cuts the wait short.
steel browser wait --load-state networkidle --timeout 15000 --session "$SESSION" --json \
  | python3 -c 'import json,sys; print("wait ->", "ok" if json.load(sys.stdin)["success"] else "not ok")'

# Snapshot once to read refs. Refs are valid for the immediately following act
# and never across a navigate, so a fresh snapshot opens every post-nav sequence.
SNAP_JSON=$(steel browser snapshot -i --session "$SESSION" --json)
REF=$(printf '%s' "$SNAP_JSON" | python3 -c '
import json,sys,re
tree=json.load(sys.stdin)["data"]
m=re.search(r"-\s+spinbutton\b[^\n]*\[ref=(\w+)\]", tree)
print(m.group(1) if m else "MISS")
')
if [ "$REF" = "MISS" ]; then
  echo "ref not found in snapshot" >&2
  exit 4
fi

# One batch: its own `snapshot -i` refreshes the refs first, then the batch-routed
# text entry rides the ref discovered from the snapshot taken immediately before
# (never a ref carried across a navigate), then the submitting act where the flow
# calls for one.
BATCH_JSON=$(steel browser batch "snapshot -i" "fill @${REF} ${VALUE}" --session "$SESSION" --json)
printf '%s' "$BATCH_JSON" | python3 -c '
import json,sys
d=json.load(sys.stdin)
print("batch success:", d["success"])
for r in d["data"]["results"]:
    print("  " + r["command"], "->", r.get("data", r.get("error")))
'

# Verify the entry landed by reading the value back, never by trusting the fill.
steel browser get value "input" --session "$SESSION" --json \
  | python3 -c 'import json,sys; print("input value ->", json.load(sys.stdin)["data"])'

echo "interaction complete; the trap releases $SESSION on exit"
