#!/usr/bin/env python3
"""Score saved pipeline results against the hand-marked golden set.

Rehearsal loop:
  .venv/bin/python scripts/simulate_lightrag_query.py --direct --out answer.json
  .venv/bin/python scripts/evaluate_lightrag_answers.py --result answer.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lightrag.evaluation import GoldenSetV1, evaluate_answer  # noqa: E402
from lightrag.generation import AnswerBundleV1  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--golden",
        default="examples/evaluation/golden-answers.v1.json",
    )
    parser.add_argument("--result", action="append", required=True)
    args = parser.parse_args()

    golden = GoldenSetV1.model_validate_json(
        Path(args.golden).read_text(encoding="utf-8")
    )
    failed = False
    for result_path in args.result:
        data = json.loads(Path(result_path).read_text(encoding="utf-8"))
        bundle = AnswerBundleV1.model_validate(data["bundle"])
        entry = golden.by_scenario(data["scenario_id"])
        if entry is None:
            print(f"{result_path}: no golden entry for {data['scenario_id']}")
            failed = True
            continue
        result = evaluate_answer(
            bundle,
            entry=entry,
            allowed_reference_ids=data.get("allowed_reference_ids", []),
        )
        metrics = result.metrics
        print(f"{result_path} [{result.scenario_id}]")
        print(
            f"  composite={metrics.composite} "
            f"types={metrics.entity_type_coverage} "
            f"names={metrics.entity_name_coverage} "
            f"citations={metrics.citation_discipline} "
            f"grounded={metrics.grounded_explanations_rate}"
        )
        print(
            f"  forbidden_violations={metrics.forbidden_claim_violations} "
            f"fabricated={metrics.fabricated_references} "
            f"no_hypothesis_compliant={metrics.no_hypothesis_compliant} "
            f"gaps_ok={metrics.knowledge_gaps_satisfied}"
        )
        for note in result.notes:
            print(f"  note: {note}")
        if metrics.fabricated_references or metrics.forbidden_claim_violations:
            failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
