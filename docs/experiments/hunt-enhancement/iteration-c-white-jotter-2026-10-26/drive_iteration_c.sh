#!/usr/bin/env bash
# Iteration C driver - one fresh white-jotter trial on the impact-assessment
# trunk, with the frozen hunting policy applied by the eval setup.
#
# The thinking change is applied IN PLACE on the instance checkout and recorded
# in the experiment document; it is not committed.
set -uo pipefail

export EVAL_REPO="${EVAL_REPO:-/opt/polymerhus-dev}"
cd "$EVAL_REPO" || exit 1
export PYTHONPATH=eval
export EVAL_INSTANCES_ROOT="${EVAL_INSTANCES_ROOT:-/opt/polymerhus-dev/eval/instances}"
export EVAL_BRANCH="${EVAL_BRANCH:-eval}"
export EVAL_WEB_DIR="${EVAL_WEB_DIR:-/root/WebExploitBench}"
export EVAL_TARGET_PLATFORM="${EVAL_TARGET_PLATFORM:-linux/amd64}"
export EVAL_DATA_ROOT="${EVAL_DATA_ROOT:-$EVAL_INSTANCES_ROOT/data/eval-server-1}"
export EVAL_ALIGNMENT_STATE="${EVAL_ALIGNMENT_STATE:-$EVAL_REPO/eval/state/alignment.yaml}"
export EVAL_RUNS_ROOT="${EVAL_RUNS_ROOT:-$EVAL_REPO/eval/runs-iteration-c-20261026}"
export EVAL_GROUND_TRUTH="${EVAL_GROUND_TRUTH:-$EVAL_WEB_DIR/white-jotter}"
export PH_API="${PH_API:-http://localhost:8080}"
export EVAL_TARGET_RUN_ID="iterc-white-jotter"

INSTANCE=eval-server-1
INSTANCE_DIR="$EVAL_INSTANCES_ROOT/$INSTANCE"
# The eval harness checkout and the eval arm code are separate lineages: the
# orchestrator that understands the arm setup must come from the instance
# worktree. The driver shell needs it on PYTHONPATH, and the harness plugin that
# runs `next_target` overrides PYTHONPATH itself, so it reads the dedicated var.
export PYTHONPATH="$INSTANCE_DIR/eval:$PYTHONPATH"
export EVAL_ORCHESTRATOR_PYTHONPATH="$INSTANCE_DIR/eval:eval"
SETUP="$INSTANCE_DIR/eval/setups/white-jotter-iteration-c.yaml"
CHAIN_STATE="$INSTANCE_DIR/chain-state.yaml"
MONITOR="$EVAL_REPO/eval/monitor-iteration-c.py"
OC=/root/.opencode/bin/opencode
mkdir -p "$EVAL_RUNS_ROOT"
LOG="$EVAL_RUNS_ROOT/driver.log"
exec > >(tee -a "$LOG") 2>&1

set -a
. "$INSTANCE_DIR/.env"
set +a
export PH_API
export EVAL_REPO EVAL_INSTANCES_ROOT EVAL_BRANCH EVAL_WEB_DIR EVAL_TARGET_PLATFORM
export EVAL_DATA_ROOT EVAL_ALIGNMENT_STATE EVAL_RUNS_ROOT EVAL_GROUND_TRUTH
export EVAL_TARGET_RUN_ID

echo "== iteration C driver start $(date -u +%FT%TZ)"
echo "== repo $EVAL_REPO"
echo "== instance $INSTANCE"
echo "== setup $SETUP"
echo "== runs root $EVAL_RUNS_ROOT"

if [ -f "$CHAIN_STATE" ]; then
  cp "$CHAIN_STATE" "$CHAIN_STATE.bak-iterc-$(date -u +%Y%m%dT%H%M%SZ)"
  rm -f "$CHAIN_STATE"
fi

EVAL_SHA="$(git -C "$INSTANCE_DIR" rev-parse HEAD)"
export EVAL_SHA
export EVAL_STACK_FINGERPRINT="${EVAL_STACK_FINGERPRINT:-$(PYTHONPATH=eval python3 -c "
from pathlib import Path
from advance import fingerprint, images, manifest
repo, sha, project = Path('$EVAL_REPO'), '$EVAL_SHA', 'ph-dd131acc'
m = manifest.build_manifest(repo, sha, images.collect_image_digests(images.default_containers(project)))
print(fingerprint.fingerprint(m))
" 2>/dev/null)}"
echo "== eval sha $EVAL_SHA"
echo "== stack fingerprint $EVAL_STACK_FINGERPRINT"

export EVAL_ASSESS_COMMAND="$OC run --agent eval-assessor --dir $EVAL_REPO \"Follow {prompt}. trial_record={trial_record}; ground_truth={ground_truth}; data_root={data_root}; destination={destination}; trace_id={trace_id}. Write only {destination}.\""
export EVAL_DIAGNOSE_COMMAND="$OC run --agent eval-diagnoser --dir $EVAL_REPO \"Follow {prompt}. trial_record={trial_record}; verdicts={verdicts}; ground_truth={ground_truth}; data_root={data_root}; vulns={vulns}; destination={destination}; trace_id={trace_id}. Write only {destination}.\""

export MONITOR_SINCE="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
export MONITOR_DATA_ROOT="$EVAL_DATA_ROOT"
export MONITOR_OUT="$EVAL_RUNS_ROOT/monitor.jsonl"
export MONITOR_PROJECT_NAME="eval-white-jotter-1"
export MONITOR_INTERVAL_S=120
export MONITOR_POD_BATCH_SIZE=3
export MONITOR_PROMOTION_FLOOR=0
echo "== monitor since $MONITOR_SINCE"
python3 "$MONITOR" &
MONITOR_PID=$!

echo "== next_target $(date -u +%FT%TZ)"
timeout 2700 "$OC" run --agent eval-orchestrator --dir "$EVAL_REPO" \
  "Single step, then STOP. Call next_target exactly once with setup=$SETUP, instance=$INSTANCE, target=white-jotter-1, repo=$EVAL_REPO, instances_root=$EVAL_INSTANCES_ROOT, branch=$EVAL_BRANCH, chain_state=$CHAIN_STATE. Then end your turn. Do not call eval_monitor. Do not advance any other target." \
  2>&1 | sed 's/^/  [agent] /'
echo "== chain-state: $(tr '\n' ' ' < "$CHAIN_STATE" 2>/dev/null)"

echo "== trial $(date -u +%FT%TZ)"
python3 -m orchestrator trial "$SETUP" "$INSTANCE" white-jotter-1 \
  --repo "$EVAL_REPO" \
  --instances-root "$EVAL_INSTANCES_ROOT" \
  --branch "$EVAL_BRANCH" \
  --state "$EVAL_ALIGNMENT_STATE" \
  --api "$PH_API" \
  --data-root "$EVAL_DATA_ROOT" \
  --skills-root "$INSTANCE_DIR/skills" \
  --runs-root "$EVAL_RUNS_ROOT" \
  --target-run-id "$EVAL_TARGET_RUN_ID" \
  --eval-sha "$EVAL_SHA" \
  --stack-fingerprint "$EVAL_STACK_FINGERPRINT" \
  --budget-s 43200 \
  --poll-s 15
TRIAL_CODE=$?
echo "== trial exit $TRIAL_CODE $(date -u +%FT%TZ)"

kill "$MONITOR_PID" 2>/dev/null || true
wait "$MONITOR_PID" 2>/dev/null || true

TRIAL_DIR="$(ls -dt "$EVAL_RUNS_ROOT"/white-jotter-1/*/ 2>/dev/null | head -1)"
TRIAL_DIR="${TRIAL_DIR%/}"
echo "== trial dir $TRIAL_DIR"
if [ -z "$TRIAL_DIR" ] || [ ! -f "$TRIAL_DIR/trial.yaml" ]; then
  echo "== no trial record; stopping after the trial"
  exit "$TRIAL_CODE"
fi

echo "== monitor to convergence $(date -u +%FT%TZ)"
timeout 5400 "$OC" run --agent eval-orchestrator --dir "$EVAL_REPO" \
  "Call eval_monitor with setup=$SETUP, runs_root=$EVAL_RUNS_ROOT, data_root=$EVAL_DATA_ROOT, ground_truth=$EVAL_GROUND_TRUTH, repo=$EVAL_REPO, instances_root=$EVAL_INSTANCES_ROOT, branch=$EVAL_BRANCH, state=$EVAL_ALIGNMENT_STATE, budget_s=3600. Call it repeatedly until every trial is complete, deferred, or escalated; then STOP and end your turn." \
  2>&1 | sed 's/^/  [agent] /'

echo "== close-verify $(date -u +%FT%TZ)"
python3 -m orchestrator close-verify "$SETUP" \
  --repo "$EVAL_REPO" \
  --instances-root "$EVAL_INSTANCES_ROOT" \
  --branch "$EVAL_BRANCH" \
  --state "$EVAL_ALIGNMENT_STATE" \
  --ground-truth "$EVAL_GROUND_TRUTH" \
  --data-root "$EVAL_DATA_ROOT" \
  --runs-root "$EVAL_RUNS_ROOT" 2>&1 | sed 's/^/  [close] /'

echo "== store materialize $(date -u +%FT%TZ)"
python3 -m orchestrator store materialize "$SETUP" \
  --repo "$EVAL_REPO" \
  --instances-root "$EVAL_INSTANCES_ROOT" \
  --branch "$EVAL_BRANCH" \
  --state "$EVAL_ALIGNMENT_STATE" \
  --trial "$TRIAL_DIR" \
  --data-root "$EVAL_DATA_ROOT" 2>&1 | sed 's/^/  [store] /'

echo "== measurement $(date -u +%FT%TZ)"
EVAL_REPO="$EVAL_REPO" EVAL_WEB_DIR="$EVAL_WEB_DIR" EVAL_CORPUS=/root/utm-groundtruth \
  bash "$EVAL_REPO/eval/measure_trial.sh" white-jotter "$TRIAL_DIR" "$EVAL_DATA_ROOT" \
  2>&1 | sed 's/^/  [measure] /'
MEASURE_CODE=$?
echo "== measurement exit $MEASURE_CODE $(date -u +%FT%TZ)"

echo "== iteration B.a driver done $(date -u +%FT%TZ)"
exit "$TRIAL_CODE"
