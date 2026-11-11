#!/usr/bin/env bash
# Drive the hunting-only iteration-E repetition on opencode-go/glm-5.3-flash.
#
# The target and the L0/L1 graph already exist. This driver:
#   1. rewrites every LLM role env to opencode-go:glm-5.3-flash and recreates the
#      agent service so the container sees it;
#   2. runs the live capability preflight (the go/no-go gate);
#   3. duplicates the completed project into a fresh id (graph, settings,
#      HTTP history, auth sessions, authn skill; no hunting artifacts);
#   4. runs `orchestrator trial` at hunting via the seeded-project path;
#   5. runs the post-execution monitor and the measurement.
#
# It does NOT run recon, analysis, or the L1 scaffold.
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

INSTANCE=eval-server-2
TARGET=siyucms-web
INSTANCE_DIR="$EVAL_INSTANCES_ROOT/$INSTANCE"
SETUP="$EVAL_REPO/eval/setups/siyucms-iteration-e-glm53.yaml"
EXP_DIR="$EVAL_REPO/docs/experiments/hunt-enhancement/iteration-e-glm53-hunt-only-2026-11-11"
OC="${OC:-/root/.opencode/bin/opencode}"
COMPOSE_PROJECT="$(
  cd "$EVAL_REPO" && PYTHONPATH=eval python3 -c \
    'from orchestrator.ids import short_id; print("ph-" + short_id("eval-server-2"))'
)"
AGENT="${COMPOSE_PROJECT}-agent-1"
KALI="${COMPOSE_PROJECT}-kali-1"
POSTGRES="${COMPOSE_PROJECT}-postgres-1"
SKILLS_HOST="$INSTANCE_DIR/skills-host"
PREFLIGHT="$EVAL_RUNS_ROOT/preflight.json"
PROJECT_NAME="eval-siyucms-web-glm53-hunt"

mkdir -p "$EVAL_RUNS_ROOT"
LOG="$EVAL_RUNS_ROOT/driver.log"
exec > >(tee -a "$LOG") 2>&1

echo "== glm53 hunting-only driver start $(date -u +%FT%TZ)"
echo "== repo $EVAL_REPO"
echo "== instance $INSTANCE target $TARGET"
echo "== compose project $COMPOSE_PROJECT"
echo "== setup $SETUP"
echo "== runs root $EVAL_RUNS_ROOT"
echo "== data root $EVAL_DATA_ROOT"

if [ ! -f "$SETUP" ]; then
  echo "== setup missing: $SETUP"
  exit 1
fi
if [ ! -f "$EXP_DIR/duplicate_project.py" ]; then
  echo "== duplication script missing"
  exit 1
fi

# 1. Rewrite every LLM role to glm-5.3-flash and recreate the agent.
ENV_FILE="$INSTANCE_DIR/.env"
if [ ! -f "$ENV_FILE" ]; then
  echo "== instance .env missing"
  exit 1
fi
cp -a "$ENV_FILE" "$ENV_FILE.pre-glm53-flash"
python3 - "$ENV_FILE" <<'PY'
import pathlib
import re
import sys

path = pathlib.Path(sys.argv[1])
text = path.read_text(encoding="utf-8")
keys = (
    "LLM_TRIAGER", "LLM_CONFIGURATOR", "LLM_JOB_ORCHESTRATOR", "LLM_CRAWLER",
    "LLM_ANALYSER", "LLM_HUNTING_HUNTER", "LLM_HUNTING_ORCHESTRATOR",
    "LLM_POD_RUNNER", "LLM_POD_TRIAGER", "LLM_SKILL_EVOLVER",
    "LLM_HUNTING_THREAT_MODELLER",
)
for key in keys:
    text, count = re.subn(rf"^{key}=.*$", f"{key}=opencode-go:glm-5.3-flash", text,
                          flags=re.M)
    if count == 0:
        raise SystemExit(f"{key} is not present in {path}")
path.write_text(text, encoding="utf-8")
missing = [key for key in keys
           if not re.search(rf"^{key}=opencode-go:glm-5\.3-flash$", text, flags=re.M)]
if missing:
    raise SystemExit(f"rewrite failed for {missing}")
print(f"== rewrote {len(keys)} role env keys to opencode-go:glm-5.3-flash")
PY
if [ "$?" -ne 0 ]; then
  echo "== model env rewrite failed; stopping"
  exit 1
fi

echo "== recreate agent with the glm-5.3-flash env $(date -u +%FT%TZ)"
(
  cd "$INSTANCE_DIR" || exit 1
  # The instance `.env` carries a stale INSTANCE_DATA_ROOT from the
  # eval-server-1 arm. The compose default must not silently mount the wrong
  # instance root, so the driver binds the run's own data root explicitly.
  INSTANCE_DATA_ROOT="$EVAL_DATA_ROOT" \
  docker compose -p "$COMPOSE_PROJECT" \
    -f docker-compose.yml -f docker-compose.dev.yml \
    -f docker-compose.pool.yml -f eval/docker-compose.eval.yml \
    up -d --no-deps --force-recreate agent
)
if [ "$?" -ne 0 ]; then
  echo "== agent recreate failed; stopping"
  exit 1
fi

for _ in $(seq 1 150); do
  CODE="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 2 "$PH_API/app-state" 2>/dev/null || true)"
  if [ "$CODE" = "200" ]; then
    break
  fi
  sleep 2
done
if [ "$(curl -sS -o /dev/null -w '%{http_code}' --max-time 2 "$PH_API/app-state" 2>/dev/null || true)" != "200" ]; then
  echo "== the agent API did not answer /app-state; stopping"
  exit 1
fi
echo "== agent API ready"

# 2. Live capability preflight (the go/no-go gate).
echo "== capability preflight $(date -u +%FT%TZ)"
docker exec -i -e PROJECT_ID=llm-capability-preflight "$AGENT" \
  python3 - --provider opencode-go --model glm-5.3-flash \
  --role hunting_threat_modeller --thinking xhigh --thinking high \
  < "$EVAL_REPO/eval/preflight_llm_capability.py" \
  > "$PREFLIGHT"
PREFLIGHT_CODE=$?
cat "$PREFLIGHT"
if [ "$PREFLIGHT_CODE" -ne 0 ]; then
  echo "== capability preflight FAILED; stopping before any project change"
  exit "$PREFLIGHT_CODE"
fi
echo "== capability preflight passed"

# 3. Duplicate the completed project.
echo "== duplicate project $(date -u +%FT%TZ)"
DUP_JSON="$(
  cd "$EVAL_REPO" && PYTHONPATH=eval python3 "$EXP_DIR/duplicate_project.py" \
    --api "$PH_API" \
    --old-project "${OLD_PROJECT_ID:-fb865e52-719d-4637-ae7f-e6856f571166}" \
    --name "$PROJECT_NAME" \
    --data-root "$EVAL_DATA_ROOT" \
    --compose-project "$COMPOSE_PROJECT" \
    --agent-container "$AGENT" \
    --kali-container "$KALI" \
    --postgres-container "$POSTGRES" \
    --setup "$SETUP" \
    --instance "$INSTANCE" \
    --target "$TARGET" \
    --scope-file "$EXP_DIR/scope-fence.txt"
)"
DUP_CODE=$?
if [ "$DUP_CODE" -ne 0 ] || [ -z "$DUP_JSON" ]; then
  echo "== duplication failed; stopping"
  exit 1
fi
echo "$DUP_JSON"
NEW_PROJECT="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["new_project"])' <<<"$DUP_JSON")"
if [ -z "$NEW_PROJECT" ]; then
  echo "== duplication returned no project id; stopping"
  exit 1
fi
echo "== new project $NEW_PROJECT"

# 4. Run the trial and its post-execution workflow.
echo "== start the hunting-only trial driver $(date -u +%FT%TZ)"
PROJECT_ID="$NEW_PROJECT" bash "$EXP_DIR/run_trial_only.sh"
exit $?
