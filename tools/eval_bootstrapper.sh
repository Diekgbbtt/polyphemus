#!/usr/bin/env bash
#
# Comparative Bootstrapper prompt-configuration eval, over the LIVE system.
#
#   tools/eval_bootstrapper.sh                       # all arms, 3 repeats
#   CONFIGS="baseline skill_in_prompt" REPEATS=5 tools/eval_bootstrapper.sh
#   KB_FILE=/path/to/kb.txt TAG=daytona tools/eval_bootstrapper.sh
#
# Each arm needs its own agent process: uvicorn's `--reload` re-reads SOURCE but
# NOT the environment, so `BOOTSTRAP_PROMPT_CONFIG` only takes effect on a
# container recreate. The script recreates, waits for health, then VERIFIES the
# container actually reports the arm before running it - a mislabelled arm would
# silently corrupt the comparison, which is worse than a missing one, so a
# mismatch skips rather than proceeds.
#
# Every evaluated project is LEFT IN THE GRAPH for inspection (start-only wipes).
set -uo pipefail
cd "$(dirname "$0")/.."

set -a; [ -f .env ] && . ./.env; set +a
# The eval runs host-side; .env carries the in-network view of the services.
export NEO4J_URI="${NEO4J_URI_HOST:-bolt://localhost:7687}"
# The package lives under src/ (pyproject `packages.find where = ["src"]`) and the
# venv has it on the path only for pytest, not for a bare `-m`.
export PYTHONPATH="src${PYTHONPATH:+:$PYTHONPATH}"

REPEATS="${REPEATS:-3}"
TAG="${TAG:-eval-$(date +%m%d%H%M)}"
OUT="${OUT:-/tmp/${TAG}-results.jsonl}"
CONFIGS="${CONFIGS:-baseline skill_in_prompt more_fewshot breadth_verbatim combined}"
COMPOSE="docker compose -f docker-compose.yml -f docker-compose.dev.yml"

for cfg in $CONFIGS; do
  echo "=== arm: $cfg ==="
  BOOTSTRAP_PROMPT_CONFIG="$cfg" $COMPOSE up -d --force-recreate agent >/dev/null 2>&1
  until curl -s -m 3 http://localhost:8080/health >/dev/null 2>&1; do sleep 2; done
  actual=$(docker exec polymerhus-agent-1 sh -c 'echo "$BOOTSTRAP_PROMPT_CONFIG"')
  if [ "$actual" != "$cfg" ]; then
    echo "    !! container reports '$actual', expected '$cfg' - SKIPPING (would mislabel results)"
    continue
  fi
  echo "    container confirmed: $actual"
  CONFIGS="$cfg" REPEATS="$REPEATS" TAG="$TAG" OUT="$OUT" KB_FILE="${KB_FILE:-}" \
    .venv/bin/python -m polymerhus.analysis.eval_cli
done

echo
echo "=== comparison ==="
RESULTS="$OUT" .venv/bin/python -m polymerhus.analysis.eval_cli --summarise
echo
echo "results: $OUT   (graphs persist in Neo4j under the printed project ids)"
