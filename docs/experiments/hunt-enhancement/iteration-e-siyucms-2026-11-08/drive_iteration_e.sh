#!/usr/bin/env bash
# Iteration E driver - one fresh siyucms trial through recon, analysis, and
# hunting on the local Steel pool, then the assessment, diagnosis, store
# materialisation, and measurement.
set -uo pipefail

export EVAL_REPO="${EVAL_REPO:-/opt/polymerhus-dev}"
export EVAL_INSTANCES_ROOT="${EVAL_INSTANCES_ROOT:-/opt/polymerhus-dev/eval/instances}"
export EVAL_BRANCH="${EVAL_BRANCH:-eval-e}"
export EVAL_DATA_ROOT="${EVAL_DATA_ROOT:-$EVAL_INSTANCES_ROOT/data/eval-server-2}"
export EVAL_ALIGNMENT_STATE="${EVAL_ALIGNMENT_STATE:-$EVAL_REPO/eval/state/alignment.yaml}"
export EVAL_RUNS_ROOT="${EVAL_RUNS_ROOT:-$EVAL_REPO/eval/runs-iteration-e-20261108}"
export EVAL_GROUND_TRUTH="${EVAL_GROUND_TRUTH:-/root/WebExploitBench/siyucms}"
export EVAL_CORPUS="${EVAL_CORPUS:-/root/utm-groundtruth}"
export PH_API="${PH_API:-http://localhost:8080}"
export EVAL_TARGET_RUN_ID="${EVAL_TARGET_RUN_ID:-itere-siyucms-web}"
export EVAL_REQUIRE_IMPACT_REVIEW=1

cd "$EVAL_REPO"
INSTANCE=eval-server-2
TARGET=siyucms-web
INSTANCE_DIR="$EVAL_INSTANCES_ROOT/$INSTANCE"
SETUP="$EVAL_REPO/eval/setups/siyucms-iteration-e.yaml"
MONITOR="$EVAL_REPO/docs/experiments/hunt-enhancement/iteration-e-siyucms-2026-11-08/monitor_iteration_e.py"
OC=/root/.opencode/bin/opencode

mkdir -p "$EVAL_RUNS_ROOT"
LOG="$EVAL_RUNS_ROOT/driver.log"
exec > >(tee -a "$LOG") 2>&1

echo "== iteration E driver start $(date -u +%FT%TZ)"
echo "== repo $EVAL_REPO"
echo "== branch $EVAL_BRANCH"
echo "== instance $INSTANCE"
echo "== data root $EVAL_DATA_ROOT"
echo "== setup $SETUP"
echo "== runs root $EVAL_RUNS_ROOT"

if ! git -C "$EVAL_REPO" rev-parse --verify "refs/heads/$EVAL_BRANCH" >/dev/null 2>&1; then
  git -C "$EVAL_REPO" branch "$EVAL_BRANCH" HEAD || {
    echo "== cannot create $EVAL_BRANCH; stopping"
    exit 1
  }
  echo "== created $EVAL_BRANCH at $(git -C "$EVAL_REPO" rev-parse "$EVAL_BRANCH")"
fi

if [ ! -e "$INSTANCE_DIR/.git" ]; then
  git -C "$EVAL_REPO" worktree add --detach "$INSTANCE_DIR" "$EVAL_BRANCH" || {
    echo "== cannot create the instance worktree; stopping"
    exit 1
  }
fi
if [ ! -f "$INSTANCE_DIR/.env" ]; then
  cp "$EVAL_INSTANCES_ROOT/eval-server-1/.env" "$INSTANCE_DIR/.env" || {
    echo "== cannot copy the instance .env; stopping"
    exit 1
  }
  echo "== copied the instance .env from eval-server-1"
fi

# The C.a thinking baseline: the two analysis proposers and the two hunting
# design roles at `max`; the pod runner and triager stay `high`. This is a
# local experiment patch in the instance worktree, never a dev change.
python3 - "$INSTANCE_DIR/src/polymerhus/app/llm/providers.py" <<'PY'
import pathlib
import re
import sys

path = pathlib.Path(sys.argv[1])
text = path.read_text(encoding="utf-8")
patterns = [
    (r'(Role\("assigner",\s+"LLM_ANALYSER",\s+"session",\s+)"medium"',
     r'\1"max"'),
    (r'(Role\("mechanism_typist",\s+"LLM_ANALYSER",\s+"session",\s+)"medium"',
     r'\1"max"'),
    (r'(Role\("hunting_threat_modeller",\s+"LLM_HUNTING_THREAT_MODELLER",\s+"session",\s+)"xhigh"',
     r'\1"max"'),
    (r'(Role\("hunting_hunter",\s+"LLM_HUNTING_HUNTER",\s+"session",\s+)"xhigh"',
     r'\1"max"'),
]
changed = []
for pattern, replacement in patterns:
    new, count = re.subn(pattern, replacement, text)
    if count:
        changed.append(count)
    text = new
if changed:
    path.write_text(text, encoding="utf-8")
    print(f"== thinking patch applied ({sum(changed)} role rows)")
else:
    print("== thinking patch already present or role table changed")
PY
if [ "$?" -ne 0 ]; then
  echo "== thinking patch failed; stopping"
  exit 1
fi

set -a
. "$INSTANCE_DIR/.env"
set +a
export PH_API EVAL_REPO EVAL_INSTANCES_ROOT EVAL_BRANCH EVAL_DATA_ROOT
export EVAL_ALIGNMENT_STATE EVAL_RUNS_ROOT EVAL_GROUND_TRUTH EVAL_CORPUS
export EVAL_TARGET_RUN_ID EVAL_REQUIRE_IMPACT_REVIEW
export PYTHONPATH="$INSTANCE_DIR/eval:$EVAL_REPO/eval"

COMPOSE_PROJECT="$(PYTHONPATH=eval python3 -c 'from orchestrator.ids import short_id; print("ph-" + short_id("eval-server-2"))')"
echo "== compose project $COMPOSE_PROJECT"
EVAL_SHA="$(git -C "$INSTANCE_DIR" rev-parse HEAD)"
export EVAL_SHA
export EVAL_STACK_FINGERPRINT="${EVAL_STACK_FINGERPRINT:-$(PYTHONPATH=eval python3 -c "
from pathlib import Path
from advance import fingerprint, images, manifest
repo, sha, project = Path('$EVAL_REPO'), '$EVAL_SHA', '$COMPOSE_PROJECT'
m = manifest.build_manifest(repo, sha, images.collect_image_digests(images.default_containers(project)))
print(fingerprint.fingerprint(m))
" 2>/dev/null)}"
echo "== eval sha $EVAL_SHA"
echo "== stack fingerprint $EVAL_STACK_FINGERPRINT"
echo "== pod watchdog ${HUNT_POD_SESSION_TIMEOUT_S:-unset}"

echo "== up $(date -u +%FT%TZ)"
python3 -m orchestrator up "$SETUP" \
  --repo "$EVAL_REPO" \
  --instances-root "$EVAL_INSTANCES_ROOT" \
  --branch "$EVAL_BRANCH" \
  --state "$EVAL_ALIGNMENT_STATE"
UP_CODE=$?
echo "== up exit $UP_CODE $(date -u +%FT%TZ)"
if [ "$UP_CODE" -ne 0 ]; then
  echo "== the target did not come up; stopping"
  exit "$UP_CODE"
fi

echo "== wait for the agent API $(date -u +%FT%TZ)"
API_READY=0
for _ in $(seq 1 150); do
  CODE="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 2 "$PH_API/app-state" 2>/dev/null || true)"
  if [ "$CODE" = "200" ]; then
    API_READY=1
    break
  fi
  sleep 2
done
if [ "$API_READY" -ne 1 ]; then
  echo "== the agent API did not answer /app-state; stopping"
  exit 1
fi
echo "== agent API ready"

# The app's project skills live in the `skills-procedures` volume at
# /srv/skills/target-specific-procedure. The trial's host-side predicate reads
# <skills-root>/target-specific-procedure/<project_id>/authn/SKILL.md, so the
# host view is one symlink from the worktree to that volume.
SKILLS_HOST="$INSTANCE_DIR/skills-host"
SKILLS_VOLUME="$(docker volume inspect "${COMPOSE_PROJECT}_skills-procedures" --format '{{.Mountpoint}}' 2>/dev/null || true)"
if [ -z "$SKILLS_VOLUME" ]; then
  echo "== cannot resolve the skills volume; stopping"
  exit 1
fi
mkdir -p "$SKILLS_HOST"
if [ -e "$SKILLS_HOST/target-specific-procedure" ] && [ ! -L "$SKILLS_HOST/target-specific-procedure" ]; then
  rm -rf "$SKILLS_HOST/target-specific-procedure"
fi
ln -sfn "$SKILLS_VOLUME" "$SKILLS_HOST/target-specific-procedure"
echo "== skills host $SKILLS_HOST -> $SKILLS_VOLUME"

echo "== seed project and browser context $(date -u +%FT%TZ)"
PROJECT_ID="$(python3 "$EVAL_REPO/docs/experiments/hunt-enhancement/iteration-e-siyucms-2026-11-08/seed_iteration_e.py" \
  --setup "$SETUP" \
  --api "$PH_API" \
  --compose-project "$COMPOSE_PROJECT" \
  --instance "$INSTANCE" \
  --target "$TARGET")"
if [ -z "$PROJECT_ID" ]; then
  echo "== the seed preflight returned no project id; stopping"
  exit 1
fi
echo "== project id $PROJECT_ID"

echo "== monitor start $(date -u +%FT%TZ)"
nohup python3 "$MONITOR" \
  --api "$PH_API" \
  --project-name "eval-$TARGET" \
  --data-root "$EVAL_DATA_ROOT" \
  --runs-root "$EVAL_RUNS_ROOT" \
  --compose-project "$COMPOSE_PROJECT" \
  --poll-s 120 >> "$EVAL_RUNS_ROOT/monitor.log" 2>&1 &
MONITOR_PID=$!
echo "== monitor pid $MONITOR_PID"

export EVAL_ASSESS_COMMAND="$OC run --agent eval-assessor --dir $EVAL_REPO \"Follow {prompt}. trial_record={trial_record}; ground_truth={ground_truth}; data_root={data_root}; destination={destination}; trace_id={trace_id}. Write only {destination} and its sibling impact_review.yaml.\""
export EVAL_DIAGNOSE_COMMAND="$OC run --agent eval-diagnoser --dir $EVAL_REPO \"Follow {prompt}. trial_record={trial_record}; verdicts={verdicts}; ground_truth={ground_truth}; data_root={data_root}; vulns={vulns}; destination={destination}; trace_id={trace_id}. Write only {destination}.\""

echo "== trial $(date -u +%FT%TZ)"
python3 -m orchestrator trial "$SETUP" "$INSTANCE" "$TARGET" \
  --repo "$EVAL_REPO" \
  --instances-root "$EVAL_INSTANCES_ROOT" \
  --branch "$EVAL_BRANCH" \
  --state "$EVAL_ALIGNMENT_STATE" \
  --api "$PH_API" \
  --project-id "$PROJECT_ID" \
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

kill "$MONITOR_PID" 2>/dev/null || true
wait "$MONITOR_PID" 2>/dev/null || true
echo "== monitor stopped $(date -u +%FT%TZ)"

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

echo "== iteration E driver done $(date -u +%FT%TZ) measure=$MEASURE_CODE"
