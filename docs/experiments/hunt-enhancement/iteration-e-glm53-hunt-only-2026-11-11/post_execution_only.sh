#!/usr/bin/env bash
# Run only the post-execution workflow for an already finished hunting trial.
# This is the resumable tail of run_trial_only.sh after the trial record exists.
#
# Required: PROJECT_ID - the project the trial ran on.
# Selects the newest trial directory under the runs root that has trial.yaml.
set -uo pipefail

export EVAL_REPO="${EVAL_REPO:-/opt/polymerhus-dev}"
export EVAL_INSTANCES_ROOT="${EVAL_INSTANCES_ROOT:-/opt/polymerhus-dev/eval/instances}"
export EVAL_BRANCH="${EVAL_BRANCH:-eval-e}"
export EVAL_DATA_ROOT="${EVAL_DATA_ROOT:-$EVAL_INSTANCES_ROOT/data/eval-server-2}"
export EVAL_ALIGNMENT_STATE="${EVAL_ALIGNMENT_STATE:-$EVAL_REPO/eval/state/alignment.yaml}"
export EVAL_RUNS_ROOT="${EVAL_RUNS_ROOT:-$EVAL_REPO/eval/runs-iteration-e-glm53-flash-20261111}"
export EVAL_GROUND_TRUTH="${EVAL_GROUND_TRUTH:-/root/WebExploitBench/siyucms}"
export EVAL_CORPUS="${EVAL_CORPUS:-/root/utm-groundtruth}"
export EVAL_TARGET_RUN_ID="${EVAL_TARGET_RUN_ID:-itere-siyucms-web-glm53}"
export EVAL_REQUIRE_IMPACT_REVIEW=1
export PH_API="${PH_API:-http://localhost:8080}"
export PYTHONPATH="$EVAL_REPO/eval:$EVAL_INSTANCES_ROOT/eval-server-2/eval${PYTHONPATH:+:$PYTHONPATH}"

INSTANCE=eval-server-2
TARGET=siyucms-web
INSTANCE_DIR="$EVAL_INSTANCES_ROOT/$INSTANCE"
SETUP="$EVAL_REPO/eval/setups/siyucms-iteration-e-glm53.yaml"
OC="${OC:-/root/.opencode/bin/opencode}"
COMPOSE_PROJECT="$(
  cd "$EVAL_REPO" && python3 -c \
    'from orchestrator.ids import short_id; print("ph-" + short_id("eval-server-2"))'
)"
AGENT="${COMPOSE_PROJECT}-agent-1"

if [ -z "${PROJECT_ID:-}" ]; then
  echo "== PROJECT_ID is required"
  exit 1
fi
DATA_MOUNT="$(docker inspect "$AGENT" --format \
  '{{range .Mounts}}{{if eq .Destination "/srv/data"}}{{.Source}}{{end}}{{end}}' 2>/dev/null)"
if [ "$DATA_MOUNT" != "$EVAL_DATA_ROOT" ]; then
  echo "== agent /srv/data is ${DATA_MOUNT:-<missing>}, expected $EVAL_DATA_ROOT"
  echo "== refusing to run the post-execution against mismatched project data"
  exit 1
fi

TRIAL_DIR="$(ls -dt "$EVAL_RUNS_ROOT/$TARGET"/*/ 2>/dev/null | head -1)"
TRIAL_DIR="${TRIAL_DIR%/}"
if [ -z "$TRIAL_DIR" ] || [ ! -f "$TRIAL_DIR/trial.yaml" ]; then
  echo "== no trial record under $EVAL_RUNS_ROOT/$TARGET; stopping"
  exit 1
fi
echo "== post-execution only start $(date -u +%FT%TZ)"
echo "== project $PROJECT_ID"
echo "== trial dir $TRIAL_DIR"
python3 - "$TRIAL_DIR/trial.yaml" <<'PY'
import sys, yaml
d = yaml.safe_load(open(sys.argv[1]))
print("== trial terminal", d.get("terminal"),
      "assessment", d.get("assessment"),
      "diagnosis", d.get("diagnosis"))
print("== trial spent", d.get("spent_tokens"), "of", d.get("token_budget"))
PY

echo "== monitor to convergence $(date -u +%FT%TZ)"
timeout 14400 "$OC" run --agent eval-orchestrator --dir "$EVAL_REPO" \
  "Call eval_monitor with setup=$SETUP, runs_root=$EVAL_RUNS_ROOT, data_root=$EVAL_DATA_ROOT, ground_truth=$EVAL_GROUND_TRUTH, repo=$EVAL_REPO, instances_root=$EVAL_INSTANCES_ROOT, branch=$EVAL_BRANCH, state=$EVAL_ALIGNMENT_STATE, budget_s=3600. Call it repeatedly until every trial is complete, deferred, or escalated; then STOP and end your turn." \
  2>&1 | sed 's/^/  [agent] /'
MONITOR_CODE=$?
echo "== monitor exit $MONITOR_CODE $(date -u +%FT%TZ)"

echo "== close-verify $(date -u +%FT%TZ)"
python3 -m orchestrator close-verify "$SETUP" \
  --repo "$EVAL_REPO" \
  --instances-root "$EVAL_INSTANCES_ROOT" \
  --branch "$EVAL_BRANCH" \
  --state "$EVAL_ALIGNMENT_STATE" \
  --ground-truth "$EVAL_GROUND_TRUTH" \
  --data-root "$EVAL_DATA_ROOT" \
  --runs-root "$EVAL_RUNS_ROOT" 2>&1 | sed 's/^/  [close] /'
CLOSE_CODE=$?

echo "== store materialize $(date -u +%FT%TZ)"
python3 -m orchestrator store materialize "$SETUP" \
  --repo "$EVAL_REPO" \
  --instances-root "$EVAL_INSTANCES_ROOT" \
  --branch "$EVAL_BRANCH" \
  --state "$EVAL_ALIGNMENT_STATE" \
  --trial "$TRIAL_DIR" \
  --data-root "$EVAL_DATA_ROOT" 2>&1 | sed 's/^/  [store] /'
STORE_CODE=$?

echo "== measurement $(date -u +%FT%TZ)"
EVAL_REPO="$INSTANCE_DIR" EVAL_WEB_DIR=/root/WebExploitBench \
  EVAL_CORPUS="$EVAL_CORPUS" \
  bash "$INSTANCE_DIR/eval/measure_trial.sh" siyucms "$TRIAL_DIR" \
  "$EVAL_DATA_ROOT" 2>&1 | sed 's/^/  [measure] /'
MEASURE_CODE=$?

echo "== post-execution only done $(date -u +%FT%TZ) monitor=$MONITOR_CODE close=$CLOSE_CODE store=$STORE_CODE measure=$MEASURE_CODE"
