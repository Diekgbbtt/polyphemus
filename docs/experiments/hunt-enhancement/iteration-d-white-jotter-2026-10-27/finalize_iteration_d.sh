#!/usr/bin/env bash
# Recovery path for iteration D: backfill the trial identity, then run the
# assessment gate, close-verify, materialisation, and the measurement.
#
# Use it when the trial record carries no stack fingerprint (the driver's
# manifest computation returned empty at launch) or after a manual re-run.
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
export EVAL_REQUIRE_IMPACT_REVIEW=1

INSTANCE=eval-server-1
INSTANCE_DIR="$EVAL_INSTANCES_ROOT/$INSTANCE"
export PYTHONPATH="$INSTANCE_DIR/eval:$EVAL_REPO/eval"
SETUP="$INSTANCE_DIR/eval/setups/white-jotter-iteration-d.yaml"
OC=/root/.opencode/bin/opencode

TRIAL_DIR="${1:-$(ls -dt "$EVAL_RUNS_ROOT"/white-jotter-1/*/ 2>/dev/null | head -1)}"
TRIAL_DIR="${TRIAL_DIR%/}"
if [ -z "$TRIAL_DIR" ] || [ ! -f "$TRIAL_DIR/trial.yaml" ]; then
  echo "no trial.yaml under $EVAL_RUNS_ROOT" >&2
  exit 2
fi

EVAL_SHA="$(git -C "$INSTANCE_DIR" rev-parse HEAD)"
FINGERPRINT="$(cd "$EVAL_REPO" && PYTHONPATH=eval python3 -c "
from pathlib import Path
from advance import fingerprint, images, manifest
repo, sha, project = Path('$EVAL_REPO'), '$EVAL_SHA', 'ph-dd131acc'
m = manifest.build_manifest(repo, sha, images.collect_image_digests(images.default_containers(project)))
print(fingerprint.fingerprint(m))
")"
if [ -z "$FINGERPRINT" ]; then
  echo "the stack fingerprint computed empty; refusing to backfill" >&2
  exit 2
fi

python3 "$(dirname "$0")/backfill_identity.py" "$TRIAL_DIR/trial.yaml" "$FINGERPRINT"

export EVAL_SHA
export EVAL_STACK_FINGERPRINT="$FINGERPRINT"
export EVAL_ASSESS_COMMAND="$OC run --agent eval-assessor --dir $EVAL_REPO \"Follow {prompt}. trial_record={trial_record}; ground_truth={ground_truth}; data_root={data_root}; destination={destination}; trace_id={trace_id}. Write only {destination} and its sibling impact_review.yaml.\""
export EVAL_DIAGNOSE_COMMAND="$OC run --agent eval-diagnoser --dir $EVAL_REPO \"Follow {prompt}. trial_record={trial_record}; verdicts={verdicts}; ground_truth={ground_truth}; data_root={data_root}; vulns={vulns}; destination={destination}; trace_id={trace_id}. Write only {destination}.\""

echo "== close-verify $(date -u +%FT%TZ)"
python3 -m orchestrator close-verify "$SETUP" \
  --repo "$EVAL_REPO" \
  --instances-root "$EVAL_INSTANCES_ROOT" \
  --branch "$EVAL_BRANCH" \
  --state "$EVAL_ALIGNMENT_STATE" \
  --ground-truth "$EVAL_GROUND_TRUTH" \
  --data-root "$EVAL_DATA_ROOT" \
  --runs-root "$EVAL_RUNS_ROOT"

echo "== store materialize $(date -u +%FT%TZ)"
python3 -m orchestrator store materialize "$SETUP" \
  --repo "$EVAL_REPO" \
  --instances-root "$EVAL_INSTANCES_ROOT" \
  --branch "$EVAL_BRANCH" \
  --state "$EVAL_ALIGNMENT_STATE" \
  --trial "$TRIAL_DIR" \
  --data-root "$EVAL_DATA_ROOT"

echo "== measurement $(date -u +%FT%TZ)"
EVAL_REPO="$INSTANCE_DIR" EVAL_WEB_DIR=/root/WebExploitBench \
  EVAL_CORPUS="$EVAL_CORPUS" \
  bash "$INSTANCE_DIR/eval/measure_trial.sh" white-jotter "$TRIAL_DIR" \
  "$EVAL_DATA_ROOT"

echo "== finalize done $(date -u +%FT%TZ)"
