#!/usr/bin/env bash
# Measure one finished unit-threat-model trial.
#
# Usage:
#   eval/measure_trial.sh <target> <trial-dir> [data-root]
#
# Deterministic metrics land in <trial-dir>/metrics.yaml.
# The eval-measurer subagent writes <trial-dir>/measurements.yaml and
# measurements.md from those metrics, the official records, the artifacts, the
# private corpus, Langfuse, and the live usage endpoint.
set -euo pipefail

TARGET="${1:?usage: measure_trial.sh <target> <trial-dir> [data-root]}"
TRIAL_DIR="${2:?usage: measure_trial.sh <target> <trial-dir> [data-root]}"
DATA_ROOT="${3:-/opt/polymerhus-dev/eval/instances/data/eval-server-1}"
REPO="${EVAL_REPO:-/opt/polymerhus-dev}"
CORPUS="${EVAL_CORPUS:-/root/utm-groundtruth}"
GROUND_TRUTH="${EVAL_WEB_DIR:-/root/WebExploitBench}/$TARGET"
PLAN="$REPO/docs/experiments/unit-threat-model-eval-2026-10-20/PLAN.md"
PYTHON="${SCAFFOLD_PYTHON:-/opt/eval-scaffold-venv/bin/python}"
OC="${OC:-/root/.opencode/bin/opencode}"

if [ ! -f "$TRIAL_DIR/trial.yaml" ]; then
  echo "measure_trial: no trial.yaml in $TRIAL_DIR" >&2
  exit 2
fi
if [ ! -d "$GROUND_TRUTH" ]; then
  echo "measure_trial: no ground truth at $GROUND_TRUTH" >&2
  exit 2
fi
if [ ! -d "$CORPUS/$TARGET" ]; then
  echo "measure_trial: no corpus bundle at $CORPUS/$TARGET" >&2
  exit 2
fi

PROJECT_ID="$("$PYTHON" - "$TRIAL_DIR/trial.yaml" <<'PY'
import sys, yaml
print(yaml.safe_load(open(sys.argv[1]))["project_id"])
PY
)"
USAGE_URL="http://localhost:8080/projects/$PROJECT_ID/usage"

echo "== deterministic metrics: $TRIAL_DIR/metrics.yaml"
"$PYTHON" "$REPO/eval/measure_utm.py" \
  --trial "$TRIAL_DIR" \
  --data-root "$DATA_ROOT" \
  --corpus "$CORPUS" \
  --target "$TARGET" \
  --ground-truth "$GROUND_TRUTH" \
  --api http://localhost:8080 \
  --out "$TRIAL_DIR/metrics.yaml"

echo "== measurement subagent"
"$OC" run --agent eval-measurer --dir "$REPO" \
  "Follow $REPO/eval/prompts/measure.md. trial_record=$TRIAL_DIR/trial.yaml; metrics=$TRIAL_DIR/metrics.yaml; verdicts=$TRIAL_DIR/verdicts.yaml; diagnoses=$TRIAL_DIR/diagnoses.yaml; data_root=$DATA_ROOT; corpus=$CORPUS; target=$TARGET; ground_truth=$GROUND_TRUTH; usage_url=$USAGE_URL; destination=$TRIAL_DIR; plan=$PLAN. Write only $TRIAL_DIR/measurements.yaml and $TRIAL_DIR/measurements.md."

echo "== measured: $TRIAL_DIR"
