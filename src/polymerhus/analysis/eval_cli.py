"""CLI for the analysis-agent configuration eval (`evaluation.py`).

Split from `evaluation.py` so the harness itself stays import-clean and testable:
the module holds the reusable core, this holds argument parsing, the KB source and
the terminal rendering. Driven by `tools/eval_bootstrapper.sh`, which owns the
per-arm container recreate that this process cannot do for itself.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys

from polymerhus.analysis.evaluation import (
    EvalOutcome,
    compare,
    evaluate_bootstrapper,
    format_comparison,
)

# The default subject: a rich, multi-journey marketplace architecture in business
# terms. Kept as the shared default so arms measured on different days stay
# comparable - changing the KB changes every number, so an eval that silently used
# a different one would be uninterpretable next to its predecessors.
_DEFAULT_KB_PATH = "tests/e2e/fixtures/juice_shop_kb.txt"


def _load_kb() -> str:
    path = os.environ.get("KB_FILE") or _DEFAULT_KB_PATH
    with open(path, encoding="utf-8") as fh:
        return fh.read().strip()


def _summarise(results_path: str) -> int:
    outcomes = []
    with open(results_path, encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                outcomes.append(EvalOutcome(**json.loads(line)))
    if not outcomes:
        print(f"no results in {results_path}")
        return 1
    summary = compare(outcomes)
    print(format_comparison(summary))
    print("\nBreadth is COMPARATIVE - rank the arms against each other, not against a bar.")
    print("Read the integrity columns alongside it: an arm can buy Service count by")
    print("losing role vocabulary or contract coverage, and that is not a win.")
    print("journey-split is a QUALITATIVE granularity note, deliberately not scored.")
    print("\npersisted projects (inspect any of them in Neo4j):")
    for config, s in summary.items():
        for pid in s.get("projects", []):
            print(f"  {pid}  {config}")
    return 0


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--summarise", action="store_true",
                    help="render the comparison from an existing results file ($RESULTS)")
    args = ap.parse_args(argv)

    if args.summarise:
        return _summarise(os.environ.get("RESULTS") or "/tmp/eval-results.jsonl")

    configs = (os.environ.get("CONFIGS") or "baseline").split()
    repeats = int(os.environ.get("REPEATS") or 3)
    out = os.environ.get("OUT") or "/tmp/eval-results.jsonl"
    summary = evaluate_bootstrapper(
        _load_kb(), configs, repeats=repeats,
        tag=os.environ.get("TAG") or "eval", results_path=out,
    )
    print(format_comparison(summary))
    return 0


if __name__ == "__main__":
    sys.exit(main())
