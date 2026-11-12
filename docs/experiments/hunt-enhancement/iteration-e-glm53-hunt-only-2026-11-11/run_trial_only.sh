#!/usr/bin/env bash
# Run the hunting-only trial and its post-execution workflow on an already
# duplicated project. This is the resumable tail of drive_hunt_only.sh.
#
# Required: PROJECT_ID - the fresh project created by duplicate_project.py.
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
SETUP="${SETUP:-$EVAL_REPO/eval/setups/siyucms-iteration-e-glm53.yaml}"
EXP_DIR="$EVAL_REPO/docs/experiments/hunt-enhancement/iteration-e-glm53-hunt-only-2026-11-11"
OC="${OC:-/root/.opencode/bin/opencode}"
COMPOSE_PROJECT="$(
  cd "$EVAL_REPO" && python3 -c \
    'from orchestrator.ids import short_id; print("ph-" + short_id("eval-server-2"))'
)"
AGENT="${COMPOSE_PROJECT}-agent-1"
SKILLS_HOST="$INSTANCE_DIR/skills-host"

if [ -z "${PROJECT_ID:-}" ]; then
  echo "== PROJECT_ID is required"
  exit 1
fi
DATA_MOUNT="$(docker inspect "$AGENT" --format \
  '{{range .Mounts}}{{if eq .Destination "/srv/data"}}{{.Source}}{{end}}{{end}}' 2>/dev/null)"
if [ "$DATA_MOUNT" != "$EVAL_DATA_ROOT" ]; then
  echo "== agent /srv/data is ${DATA_MOUNT:-<missing>}, expected $EVAL_DATA_ROOT"
  echo "== refusing to run the hunt against mismatched project data"
  exit 1
fi
mkdir -p "$EVAL_RUNS_ROOT"
LOG="$EVAL_RUNS_ROOT/trial-driver.log"
exec > >(tee -a "$LOG") 2>&1

echo "== hunting-only trial driver start $(date -u +%FT%TZ)"
echo "== project $PROJECT_ID"

SKILLS_VOLUME="$(docker volume inspect "${COMPOSE_PROJECT}_skills-procedures" \
  --format '{{.Mountpoint}}' 2>/dev/null || true)"
if [ -z "$SKILLS_VOLUME" ]; then
  echo "== cannot resolve the skills volume; stopping"
  exit 1
fi
mkdir -p "$SKILLS_HOST"
if [ -e "$SKILLS_HOST/target-specific-procedure" ] && [ ! -L "$SKILLS_HOST/target-specific-procedure" ]; then
  rm -rf "$SKILLS_HOST/target-specific-procedure"
fi
ln -sfn "$SKILLS_VOLUME" "$SKILLS_HOST/target-specific-procedure"

EVAL_SHA="$(git -C "$INSTANCE_DIR" rev-parse HEAD)"
export EVAL_SHA
export EVAL_STACK_FINGERPRINT="${EVAL_STACK_FINGERPRINT:-$(
  cd "$EVAL_REPO" && python3 -c "
from pathlib import Path
from advance import fingerprint, images, manifest
repo, sha, project = Path('$EVAL_REPO'), '$EVAL_SHA', '$COMPOSE_PROJECT'
m = manifest.build_manifest(repo, sha, images.collect_image_digests(images.default_containers(project)))
print(fingerprint.fingerprint(m))
" 2>/dev/null
)}"
echo "== eval sha $EVAL_SHA"
echo "== stack fingerprint $EVAL_STACK_FINGERPRINT"

export EVAL_ASSESS_COMMAND="$OC run --agent eval-assessor --dir $EVAL_REPO \"Follow {prompt}. trial_record={trial_record}; ground_truth={ground_truth}; data_root={data_root}; destination={destination}; trace_id={trace_id}. Write only {destination} and its sibling impact_review.yaml.\""
export EVAL_DIAGNOSE_COMMAND="$OC run --agent eval-diagnoser --dir $EVAL_REPO \"Follow {prompt}. trial_record={trial_record}; verdicts={verdicts}; ground_truth={ground_truth}; data_root={data_root}; vulns={vulns}; destination={destination}; trace_id={trace_id}. Write only {destination}.\""

echo "== hunting trial $(date -u +%FT%TZ)"
python3 -m orchestrator trial "$SETUP" "$INSTANCE" "$TARGET" \
  --repo "$EVAL_REPO" \
  --instances-root "$EVAL_INSTANCES_ROOT" \
  --branch "$EVAL_BRANCH" \
  --state "$EVAL_ALIGNMENT_STATE" \
  --api "$PH_API" \
  --existing-project-id "$PROJECT_ID" \
  --skip-up \
  --data-root "$EVAL_DATA_ROOT" \
  --skills-root "$SKILLS_HOST" \
  --runs-root "$EVAL_RUNS_ROOT" \
  --target-run-id "$EVAL_TARGET_RUN_ID" \
  --eval-sha "$EVAL_SHA" \
  --stack-fingerprint "$EVAL_STACK_FINGERPRINT" \
  --budget-s 86400 \
  --poll-s 15
TRIAL_CODE=$?
echo "== trial exit $TRIAL_CODE $(date -u +%FT%TZ)"

TRIAL_DIR="$(ls -dt "$EVAL_RUNS_ROOT/$TARGET"/*/ 2>/dev/null | head -1)"
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
  bash "$INSTANCE_DIR/eval/measure_trial.sh" siyucms "$TRIAL_DIR" \
  "$EVAL_DATA_ROOT" 2>&1 | sed 's/^/  [measure] /'
MEASURE_CODE=$?

echo "== hunting-only trial driver done $(date -u +%FT%TZ) measure=$MEASURE_CODE"
exit 0
