#!/usr/bin/env bash
# Operation family: interaction - snapshot for refs, then act in ONE batch.
# The batch is a choice to share the discovered ref and one spawn, not a
# workaround: standalone `fill`/`type`/`setvalue` resolve fine when every flag
# leads the positionals (a trailing `--session`/`--json` is swallowed as another
# VALUE). A runtime VALUE is interpolated through the shell as "${VALUE}" -
# variable expansion never re-expands a `$` or backtick inside the value's
# contents, so this is the safe form; only a literal value would need
# single-quoting. The read-back prints a boolean, never the value.
# Runnable verbatim through steel_exec(script=<text>, script_lang="sh") or `bash <file>`.
if [ -z "${BASH_VERSION:-}" ]; then exec bash "$0" "$@"; fi
set -euo pipefail

FLOW="interact"
URL="${URL:-https://the-internet.herokuapp.com/inputs}"
VALUE="${VALUE:-42}"
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

# Catalogue guard (D13 amended); this read is also the pre-call baseline, so a
# foreign `default` seen here is never addressed by this run.
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

# One batch: a fresh snapshot, then the text entry, options ahead of the value.
# Results are reported by op index and success, plus one deliberate exception on
# failure - a bounded typed `error`. The result envelope also echoes each
# `command` string, and a text-entry command carries its value, so that field is
# never printed; the `error` field names the failure without it.
# A failing batch has TWO shapes, told apart structurally: an op-level failure
# writes the results envelope (line 1, carrying data.results) then
# {"error":"One or more batch commands failed"} and exits 1, while a batch-level
# failure (a clap usage error, an empty session name) writes a SINGLE
# {"error":...} line with no results envelope. So a whole-stdout parse would die
# on Extra data; the parser keys on line 1 carrying data.results.
# `set -e` must not abort on the expected exit-1, so the exit status is captured
# instead: `if BATCH_JSON=$(...)` clears the errexit flag for this command, and
# the parser also receives the exit code as its last argument.
set +e
if BATCH_JSON=$(steel browser batch 'snapshot -i' "fill @${REF} ${VALUE}" --session "$SESSION" --json); then
  BATCH_RC=0
else
  BATCH_RC=$?
fi
set -e
printf '%s' "$BATCH_JSON" | python3 -c '
import json,sys
try:
    rc=int(sys.argv[1])
except (IndexError,ValueError):
    rc=None
lines=[l for l in sys.stdin.read().splitlines() if l.strip()]
if not lines:
    print("batch empty stdout | exit", rc); sys.exit(0)
first=json.loads(lines[0])
data=first.get("data") if isinstance(first.get("data"), dict) else {}
if "results" not in data:  # batch-level refusal: a single error line, no envelope
    print("batch refused:", first.get("error"), "| exit", rc)
    sys.exit(0)
results=data.get("results", [])
print("batch success:", first.get("success"), "| ops:", len(results), "| exit", rc)
for i,r in enumerate(results):
    status="ok" if r.get("success") else "FAIL"
    line="  op %d %s" % (i, status)
    if not r.get("success") and r.get("error"):
        line += " | " + str(r["error"])[:80]
    print(line)
if len(lines) > 1:
    print("batch exit signal:", json.loads(lines[1]).get("error"))
' "$BATCH_RC"

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
SESSION_NAMED=0
steel browser sessions --json | python3 -c '
import json,sys
names={s.get("name") for s in (json.load(sys.stdin).get("data") or []) if isinstance(s, dict)}
print("released:", sys.argv[1] not in names)
' "$SESSION"

echo "interaction complete"
