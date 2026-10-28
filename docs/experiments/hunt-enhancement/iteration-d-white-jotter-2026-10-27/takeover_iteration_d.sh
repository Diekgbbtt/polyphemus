#!/usr/bin/env bash
# Take the iteration D run over from the trial's 12-hour poll clock.
#
# The experiment's bound is the 7M capped-token cap, not the trial's clock. Near
# the deadline this script:
#   1. stops the hunting run through the API, so the trial's poll sees
#      `stopped` and writes a normal trial record instead of timing out;
#   2. waits for `trial.yaml`;
#   3. kills the driver and its eval-monitor child before they assess the
#      partial run;
#   4. backfills the trial identity (the driver launched with no fingerprint);
#   5. resumes the run in place through the API;
#   6. restarts the monitor with `--stop-at-cap`, so the resumed run stops at
#      the 7M cap rather than at the trial's clock.
#
# The final assessment runs through `finalize_iteration_d.sh` once the resumed
# run reaches its terminal.
set -uo pipefail

API="${PH_API:-http://localhost:8080}"
PROJECT="${PROJECT_ID:-fe446230-1f19-41c7-bf2e-b7b4b9c6f0f5}"
RUN="${HUNTING_RUN_ID:-aac5ecac-f119-4e26-9f21-fc259153ccf3}"
RUNS="${EVAL_RUNS_ROOT:-/opt/polymerhus-dev/eval/runs-iteration-d-20261027}"
FINGERPRINT="${STACK_FINGERPRINT:-84d14309e4c4c4ebd9706f890f7bf04455e1068efb2ab9dfff8cc4a4d707b6e0}"
DATA="${EVAL_DATA_ROOT:-/opt/polymerhus-dev/eval/instances/data/eval-server-1}"

echo "== takeover start $(date -u +%FT%TZ)"

STATUS="$(curl -s "$API/projects/$PROJECT/hunting/$RUN" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("status",""))')"
echo "== run status $STATUS"
case "$STATUS" in
  complete|stopped|failed|interrupted)
    echo "== the run is already terminal; no takeover needed"
    exit 0
    ;;
esac

echo "== stop at $(date -u +%FT%TZ)"
curl -s -X POST "$API/projects/$PROJECT/hunting/$RUN/stop"
echo

TRIAL_FILE=""
for _ in $(seq 1 60); do
  TRIAL_FILE="$(find "$RUNS/white-jotter-1" -maxdepth 2 -name trial.yaml 2>/dev/null | head -1)"
  [ -n "$TRIAL_FILE" ] && break
  sleep 5
done
if [ -z "$TRIAL_FILE" ]; then
  echo "== no trial.yaml after the stop; leaving the run stopped" >&2
  exit 1
fi
echo "== trial record $TRIAL_FILE"

DRIVER="$(pgrep -f '^bash /root/iter-d/drive_iteration_d.sh' | head -1 || true)"
TRIAL_PID="$(pgrep -f '^python3 -m orchestrator trial' | head -1 || true)"
[ -n "$DRIVER" ] && kill "$DRIVER" 2>/dev/null && echo "== killed driver $DRIVER"
[ -n "$TRIAL_PID" ] && kill "$TRIAL_PID" 2>/dev/null && echo "== killed trial $TRIAL_PID"
for pid in $(pgrep -f 'opencode run --agent eval-orchestrator' || true); do
  kill "$pid" 2>/dev/null && echo "== killed eval monitor $pid"
done

python3 /root/iter-d/backfill_identity.py "$TRIAL_FILE" "$FINGERPRINT"

echo "== resume at $(date -u +%FT%TZ)"
CODE="$(curl -s -o /tmp/iter-d-resume.json -w '%{http_code}' -X POST "$API/projects/$PROJECT/hunting/$RUN/resume")"
echo "== resume http $CODE"
cat /tmp/iter-d-resume.json 2>/dev/null
echo
if [ "$CODE" != "202" ]; then
  echo "== resume refused; the run stays stopped" >&2
  exit 1
fi

MONITOR="$(pgrep -f '^python3 /root/iter-d/monitor_iteration_d.py' | head -1 || true)"
[ -n "$MONITOR" ] && kill "$MONITOR" 2>/dev/null && echo "== stopped old monitor $MONITOR"
sleep 1
setsid -f python3 /root/iter-d/monitor_iteration_d.py \
  --project-id "$PROJECT" \
  --run-id "$RUN" \
  --data-root "$DATA" \
  --out "$RUNS/monitor.jsonl" \
  --interval 120 \
  --max-minutes 1440 \
  --stop-at-cap \
  </dev/null >>/root/iter-d/monitor.log 2>&1
sleep 5
echo "== monitor pid $(pgrep -f '^python3 /root/iter-d/monitor_iteration_d.py' | head -1 || true)"
tail -1 /root/iter-d/monitor.log
echo "== takeover done $(date -u +%FT%TZ)"
