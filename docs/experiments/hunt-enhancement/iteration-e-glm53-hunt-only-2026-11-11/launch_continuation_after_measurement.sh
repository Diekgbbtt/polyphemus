#!/usr/bin/env bash
# Wait for the first trial's post-execution (assessment, diagnosis, measurement)
# to finish, then launch the 33-unit continuation trial detached.
#
# The first trial's deterministic metrics are already written, but its
# measurer subagent reads the live hunting tree. Starting a new hunting run
# before that read finishes would change the evidence under it, so this gate
# holds the launch until the post-execution marker lands with measure=0.
set -uo pipefail

export EVAL_REPO="${EVAL_REPO:-/opt/polymerhus-dev}"
export EVAL_INSTANCES_ROOT="${EVAL_INSTANCES_ROOT:-/opt/polymerhus-dev/eval/instances}"
export EVAL_DATA_ROOT="${EVAL_DATA_ROOT:-$EVAL_INSTANCES_ROOT/data/eval-server-2}"
export EVAL_RUNS_ROOT="${EVAL_RUNS_ROOT:-$EVAL_REPO/eval/runs-iteration-e-glm53-flash-20261111}"
export EVAL_TARGET_RUN_ID="${EVAL_TARGET_RUN_ID:-itere-siyucms-web-glm53-flash-cont}"
export SETUP="${SETUP:-$EVAL_REPO/eval/setups/siyucms-iteration-e-glm53-continuation.yaml}"
export PROJECT_ID="${PROJECT_ID:-10e451a3-025c-4648-a21e-0eec5cf9ebb8}"

POST_LOG="$EVAL_RUNS_ROOT/post-execution.log"
GATE_LOG="$EVAL_RUNS_ROOT/continuation-gate.log"
TRIAL_ROOT="$EVAL_RUNS_ROOT/siyucms-web"
DRIVER="$EVAL_REPO/docs/experiments/hunt-enhancement/iteration-e-glm53-hunt-only-2026-11-11/run_trial_only.sh"

exec >>"$GATE_LOG" 2>&1
echo "== continuation gate start $(date -u +%FT%TZ)"
echo "== waiting for $POST_LOG"

deadline=$(( $(date +%s) + 10800 ))
while [ "$(date +%s)" -lt "$deadline" ]; do
  if grep -q "post-execution only done" "$POST_LOG" 2>/dev/null; then
    code="$(grep -o 'measure=[0-9]*' "$POST_LOG" | tail -1 | cut -d= -f2)"
    echo "== post-execution done code=${code:-missing} $(date -u +%FT%TZ)"
    if [ "${code:-1}" != "0" ]; then
      echo "== measurement failed; refusing to launch the continuation"
      exit 1
    fi
    latest="$(ls -dt "$TRIAL_ROOT"/*/ 2>/dev/null | head -1)"
    latest="${latest%/}"
    if [ -z "$latest" ] || [ ! -f "$latest/measurements.yaml" ]; then
      echo "== no measurements.yaml under ${latest:-<none>}; refusing to launch"
      exit 1
    fi
    if [ -f "$latest/trial.yaml" ]; then
      echo "== measured trial $latest"
    fi
    echo "== launching the 33-unit continuation $(date -u +%FT%TZ)"
    cd "$EVAL_REPO" || exit 1
    setsid nohup env \
      PROJECT_ID="$PROJECT_ID" \
      SETUP="$SETUP" \
      EVAL_TARGET_RUN_ID="$EVAL_TARGET_RUN_ID" \
      EVAL_RUNS_ROOT="$EVAL_RUNS_ROOT" \
      EVAL_DATA_ROOT="$EVAL_DATA_ROOT" \
      bash "$DRIVER" \
      > "$EVAL_RUNS_ROOT/continuation-driver.log" 2>&1 < /dev/null &
    echo "== continuation driver pid $!"
    exit 0
  fi
  sleep 30
done
echo "== timed out waiting for the post-execution marker"
exit 1
