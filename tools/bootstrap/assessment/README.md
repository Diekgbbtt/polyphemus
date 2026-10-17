# Bootstrap artifact assessment

Grades the artifacts the shape validator passes, per target, with a portfolio view and baseline deltas.
The criteria, anchors, and acceptance rules live in `RUBRIC.md`; the semantic (LLM) half lives in `llm_judge_prompt.md`.

## Layout

- `RUBRIC.md` - the framework: scales, criteria A1-E2 and L1-L5, portfolio metrics, acceptance rules.
- `assess.py` - the deterministic engine: per-criterion scales and metrics, the portfolio markdown, the JSON.
- `llm_judge_prompt.md` - the per-target assessor prompt; its verdicts merge into `assess.py` output automatically.
- `baseline-pre-regeneration.json` - the eight targets' committed-view baseline before the W2 regeneration.

## 1. Gate first

`assess.py` grades; the shape validator gates.
Run the validator before any assessment, and never assess a target that fails it:

```bash
PYTHONPATH=src python3 tools/bootstrap/validate_data_dependencies.py --all <kbs_root>
```

## 2. Deterministic pass

```bash
# one target
PYTHONPATH=src python3 tools/bootstrap/assessment/assess.py eval/data/webexploitbench/comfyui

# the whole portfolio, persisted, with the auth bundle staged and the leak scan
# extended by the target-specific ground-truth directory names
PYTHONPATH=src python3 tools/bootstrap/assessment/assess.py \
    --portfolio eval/data/webexploitbench \
    --staging <staging_root> \
    --groundtruth <groundtruth_root> \
    --json out/portfolio.json \
    --baseline tools/bootstrap/assessment/baseline-pre-regeneration.json
```

Notes:

- `--staging` points at the runtime root that carries `auth/` and `skills/` outside git; without it, D1 fails by design.
- `--groundtruth` names the sealed root; only directory names feed the leak scan - no file content is ever read.
- Compare like with like: the committed baseline is a committed view, so produce a committed-view portfolio for the delta table and a staging-view portfolio for absolute quality.

## 3. Semantic pass (LLM assessors)

Run one fresh assessor agent per target with `llm_judge_prompt.md` (placeholders filled: target, artifact dir, staging dir, deterministic JSON).
Each writes `<TARGET_DIR>/assessment.yaml`.
Re-run step 2 afterwards: `assess.py` merges the verdicts into the same report.

## 4. Read the portfolio

- The table gives mean/min per criterion and the per-target scale row; a criterion at scale <= 1 is FAILING and is listed with its notes.
- `E2` at 0 is an integrity violation: stop and inspect the `file:line` notes before anything else.
- The delta table compares each target's `overall` with the baseline; the acceptance rules in `RUBRIC.md` section 5 decide whether a regenerated set ships.

## 5. Tests

```bash
python3 -m pytest tests/test_bootstrap_assessment.py -q
```

The tests drive crafted GOOD and BAD target directories and pin the scales, the metrics, the failing list, the baseline deltas, and the verdict merge.
