#!/usr/bin/env bash
# Drive the iteration E_a dataease trial: one fresh project through recon,
# analysis, and hunting on the local Steel pool, then the assessment,
# diagnosis, close verification, store materialisation, and measurement.
#
# The branch, the instance worktree, and the instance `.env` are prepared
# separately; this driver asserts them and then runs the trial.
set -uo pipefail

export EVAL_REPO="${EVAL_REPO:-/opt/polymerhus-dev}"
export EVAL_INSTANCES_ROOT="${EVAL_INSTANCES_ROOT:-/opt/polymerhus-dev/eval/instances}"
export EVAL_BRANCH="${EVAL_BRANCH:-iter-e_a-dataease-authn-pod-context}"
export EVAL_DATA_ROOT="${EVAL_DATA_ROOT:-$EVAL_INSTANCES_ROOT/data/eval-server-2}"
export EVAL_ALIGNMENT_STATE="${EVAL_ALIGNMENT_STATE:-$EVAL_REPO/eval/state/alignment.yaml}"
export EVAL_RUNS_ROOT="${EVAL_RUNS_ROOT:-$EVAL_REPO/eval/runs-iteration-e-a-dataease-20261116}"
export EVAL_GROUND_TRUTH="${EVAL_GROUND_TRUTH:-/root/WebExploitBench/dataease}"
export EVAL_CORPUS="${EVAL_CORPUS:-/root/utm-groundtruth}"
export EVAL_TARGET_RUN_ID="${EVAL_TARGET_RUN_ID:-itere-a-dataease-web}"
export EVAL_REQUIRE_IMPACT_REVIEW=1
export PH_API="${PH_API:-http://localhost:8080}"
# The instance `.env` still names the eval-server-1 root; bind the run's own
# data root explicitly so the compose substitution cannot mount the wrong one.
export INSTANCE_DATA_ROOT="$EVAL_DATA_ROOT"

cd "$EVAL_REPO" || exit 1
INSTANCE=eval-server-2
TARGET=dataease-web
PROJECT_NAME="${PROJECT_NAME:-eval-dataease-web-iter-e-a}"
INSTANCE_DIR="$EVAL_INSTANCES_ROOT/$INSTANCE"
SETUP="$EVAL_REPO/eval/setups/dataease-iteration-e-a.yaml"
EXP_DIR="$EVAL_REPO/docs/experiments/hunt-enhancement/iteration-e_a-dataease-2026-11-16"
OC="${OC:-/root/.opencode/bin/opencode}"
COMPOSE_PROJECT="$(
  PYTHONPATH=eval python3 -c \
    'from orchestrator.ids import short_id; print("ph-" + short_id("eval-server-2"))'
)"
AGENT="${COMPOSE_PROJECT}-agent-1"
KALI="${COMPOSE_PROJECT}-kali-1"
POSTGRES="${COMPOSE_PROJECT}-postgres-1"
SKILLS_HOST="$INSTANCE_DIR/skills-host"

mkdir -p "$EVAL_RUNS_ROOT"
LOG="$EVAL_RUNS_ROOT/driver.log"
exec > >(tee -a "$LOG") 2>&1

echo "== iteration E_a dataease driver start $(date -u +%FT%TZ)"
echo "== repo $EVAL_REPO"
echo "== branch $EVAL_BRANCH"
echo "== instance $INSTANCE target $TARGET"
echo "== compose project $COMPOSE_PROJECT"
echo "== setup $SETUP"
echo "== runs root $EVAL_RUNS_ROOT"
echo "== data root $EVAL_DATA_ROOT"

if [ ! -f "$SETUP" ]; then
  echo "== setup missing: $SETUP"
  exit 1
fi
if [ ! -f "$EXP_DIR/seed_dataease.py" ]; then
  echo "== seed script missing"
  exit 1
fi
if [ ! -f "$INSTANCE_DIR/.env" ]; then
  echo "== instance .env missing"
  exit 1
fi

# 1. Assert the prepared trial input. Stop before touching the stack when a
#    value disagrees with the iteration design.
ENV_FILE="$INSTANCE_DIR/.env"
set -a
. "$ENV_FILE"
set +a
required_env=(
  "API_KEY_OPENCODE_GO"
  "STEEL_CRAWL_MAX_DURATION_S=7200"
  "HUNT_RISK_THRESHOLD=360"
  "HUNT_POD_SESSION_TIMEOUT_S=5400"
  "SKILL_EVOLUTION_ENABLED=0"
)
for entry in "${required_env[@]}"; do
  if [[ "$entry" == *=* ]]; then
    key="${entry%%=*}"
    want="${entry#*=}"
    got="$(grep -E "^${key}=" "$ENV_FILE" | tail -1 | cut -d= -f2-)"
    if [ "$got" != "$want" ]; then
      echo "== env mismatch: ${key}=${got:-<unset>} (want $want); stopping"
      exit 1
    fi
  else
    if [ -z "$(grep -E "^${entry}=." "$ENV_FILE" | tail -1)" ]; then
      echo "== env missing: $entry; stopping"
      exit 1
    fi
  fi
done
for key in LLM_TRIAGER LLM_CONFIGURATOR LLM_JOB_ORCHESTRATOR LLM_CRAWLER \
           LLM_ANALYSER LLM_HUNTING_HUNTER LLM_HUNTING_ORCHESTRATOR \
           LLM_POD_RUNNER LLM_POD_TRIAGER LLM_SKILL_EVOLVER \
           LLM_HUNTING_THREAT_MODELLER; do
  got="$(grep -E "^${key}=" "$ENV_FILE" | tail -1 | cut -d= -f2-)"
  if [ "$got" != "opencode-go:glm-5.3-flash" ]; then
    echo "== env model mismatch: ${key}=${got:-<unset>}; stopping"
    exit 1
  fi
done
if ! grep -qE 'Role\("assigner",\s+"LLM_ANALYSER",\s+"session",\s+"medium"\)' \
     "$INSTANCE_DIR/src/polymerhus/app/llm/providers.py"; then
  echo "== providers.py is not on the default thinking efforts; revert the C.a patch and retry"
  exit 1
fi
echo "== env and thinking defaults verified"

# 2. The instance `.env` is loaded by the stack; the dataease images are
#    pre-pulled. Bring the stack and the target up.
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
echo "== skills host $SKILLS_HOST -> $SKILLS_VOLUME"

# 3. Seed the project and freeze the reusable iteration-D scope fence. The
#    trial then bootstraps settings, auth, L1, and the phases.
echo "== seed project and scope fence $(date -u +%FT%TZ)"
PROJECT_ID="$(python3 "$EXP_DIR/seed_dataease.py" \
  --api "$PH_API" \
  --name "$PROJECT_NAME" \
  --scope-file "$EXP_DIR/scope-fence.txt")"
if [ -z "$PROJECT_ID" ]; then
  echo "== the seed preflight returned no project id; stopping"
  exit 1
fi
echo "== project id $PROJECT_ID"

# 4. The live monitor feed.
echo "== monitor start $(date -u +%FT%TZ)"
nohup python3 "$EXP_DIR/monitor_iteration_e_a.py" \
  --api "$PH_API" \
  --project-name "$PROJECT_NAME" \
  --data-root "$EVAL_DATA_ROOT" \
  --runs-root "$EVAL_RUNS_ROOT" \
  --target "$TARGET" \
  --compose-project "$COMPOSE_PROJECT" \
  --poll-s 120 >> "$EVAL_RUNS_ROOT/monitor.log" 2>&1 &
MONITOR_PID=$!
echo "== monitor pid $MONITOR_PID"

# 5. Trial identity and the post-execution commands.
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

# 6. The full pipeline: recon, analysis, hunting.
echo "== trial $(date -u +%FT%TZ)"
python3 -m orchestrator trial "$SETUP" "$INSTANCE" "$TARGET" \
  --repo "$EVAL_REPO" \
  --instances-root "$EVAL_INSTANCES_ROOT" \
  --branch "$EVAL_BRANCH" \
  --state "$EVAL_ALIGNMENT_STATE" \
  --api "$PH_API" \
  --project-id "$PROJECT_ID" \
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

# 7. Post-execution: assessment, diagnosis, close verification, store, measure.
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
  bash "$INSTANCE_DIR/eval/measure_trial.sh" dataease "$TRIAL_DIR" \
  "$EVAL_DATA_ROOT" 2>&1 | sed 's/^/  [measure] /'
MEASURE_CODE=$?

echo "== iteration E_a dataease driver done $(date -u +%FT%TZ) measure=$MEASURE_CODE"
exit 0
