#!/usr/bin/env bash
# Iteration D driver - one seeded white-jotter trial on the capability-first
# impact modeller, on a copied data layer, with the scope fence.
#
# Unlike the iteration C driver this one does NOT run `next_target`: the target
# is already up and the project is seeded, so the trial starts at hunting and
# mutates neither. The driver runs the trial, then the eval monitor
# (assessment + diagnosis), close-verify, store materialisation, and the
# measurement.
set -uo pipefail

export EVAL_REPO="${EVAL_REPO:-/opt/polymerhus-dev}"
export EVAL_INSTANCES_ROOT="${EVAL_INSTANCES_ROOT:-/opt/polymerhus-dev/eval/instances}"
export EVAL_BRANCH="${EVAL_BRANCH:-eval}"
export EVAL_DATA_ROOT="${EVAL_DATA_ROOT:-$EVAL_INSTANCES_ROOT/data/eval-server-1}"
export EVAL_ALIGNMENT_STATE="${EVAL_ALIGNMENT_STATE:-$EVAL_REPO/eval/state/alignment.yaml}"
export EVAL_RUNS_ROOT="${EVAL_RUNS_ROOT:-$EVAL_REPO/eval/runs-iteration-d-20261027}"
export EVAL_GROUND_TRUTH="${EVAL_GROUND_TRUTH:-/root/WebExploitBench/white-jotter}"
export EVAL_CORPUS="${EVAL_CORPUS:-/root/utm-groundtruth}"
export PH_API="${PH_API:-http://localhost:8080}"
export EVAL_TARGET_RUN_ID="${EVAL_TARGET_RUN_ID:-iterd-white-jotter}"
export EVAL_REQUIRE_IMPACT_REVIEW=1

INSTANCE=eval-server-1
INSTANCE_DIR="$EVAL_INSTANCES_ROOT/$INSTANCE"
# The trial and its monitor must run the arm code from the instance worktree,
# which is deployed at the merged trunk commit; the eval harness checkout is a
# separate lineage.
export PYTHONPATH="$INSTANCE_DIR/eval:$EVAL_REPO/eval"
export EVAL_ORCHESTRATOR_PYTHONPATH="$INSTANCE_DIR/eval:$EVAL_REPO/eval"
SETUP="$INSTANCE_DIR/eval/setups/white-jotter-iteration-d.yaml"
OC=/root/.opencode/bin/opencode
mkdir -p "$EVAL_RUNS_ROOT"
LOG="$EVAL_RUNS_ROOT/driver.log"
exec > >(tee -a "$LOG") 2>&1

set -a
. "$INSTANCE_DIR/.env"
set +a
export PH_API EVAL_REPO EVAL_INSTANCES_ROOT EVAL_BRANCH EVAL_DATA_ROOT
export EVAL_ALIGNMENT_STATE EVAL_RUNS_ROOT EVAL_GROUND_TRUTH EVAL_CORPUS
export EVAL_TARGET_RUN_ID EVAL_REQUIRE_IMPACT_REVIEW

echo "== iteration D driver start $(date -u +%FT%TZ)"
echo "== repo $EVAL_REPO"
echo "== instance $INSTANCE"
echo "== setup $SETUP"
echo "== runs root $EVAL_RUNS_ROOT"

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

export EVAL_ASSESS_COMMAND="$OC run --agent eval-assessor --dir $EVAL_REPO \"Follow {prompt}. trial_record={trial_record}; ground_truth={ground_truth}; data_root={data_root}; destination={destination}; trace_id={trace_id}. Write only {destination} and its sibling impact_review.yaml.\""
export EVAL_DIAGNOSE_COMMAND="$OC run --agent eval-diagnoser --dir $EVAL_REPO \"Follow {prompt}. trial_record={trial_record}; verdicts={verdicts}; ground_truth={ground_truth}; data_root={data_root}; vulns={vulns}; destination={destination}; trace_id={trace_id}. Write only {destination}.\""

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

TRIAL_DIR="$(ls -dt "$EVAL_RUNS_ROOT"/white-jotter-1/*/ 2>/dev/null | head -1)"
TRIAL_DIR="${TRIAL_DIR%/}"
echo "== trial dir $TRIAL_DIR"
if [ -z "$TRIAL_DIR" ] || [ ! -f "$TRIAL_DIR/trial.yaml" ]; then
  echo "== no trial record; stopping after the trial"
  exit "$TRIAL_CODE"
fi

echo "== monitor to convergence $(date -u +%FT%TZ)"
timeout 14400 "$OC" run --agent eval-orchestrator --dir "$EVAL_REPO" \
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
EVAL_REPO="$INSTANCE_DIR" EVAL_WEB_DIR=/root/WebExploitBench \
  EVAL_CORPUS="$EVAL_CORPUS" \
  bash "$INSTANCE_DIR/eval/measure_trial.sh" white-jotter "$TRIAL_DIR" \
  "$EVAL_DATA_ROOT" 2>&1 | sed 's/^/  [measure] /'
MEASURE_CODE=$?
echo "== measurement exit $MEASURE_CODE $(date -u +%FT%TZ)"

echo "== iteration D driver done $(date -u +%FT%TZ)"
exit "$TRIAL_CODE"
