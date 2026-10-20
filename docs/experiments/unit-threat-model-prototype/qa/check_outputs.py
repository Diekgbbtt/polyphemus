#!/usr/bin/env python3
"""S5 - mechanical pass over the mock outputs.

Per output file: parse, contract-completeness, spec inventory, axis/coverage
summary. Judgement (W2 slice coverage, W3 grounding, quality) stays manual in S6.
"""

import os
import sys
import yaml

ROOT = os.path.dirname(os.path.abspath(__file__))
TRIALS = ("t1", "t2")

REQUIRED_TOP = (
    "loop_id", "unit_id", "class", "class_skill", "slice", "discrimination",
    "specs", "checks", "degradations",
)
REQUIRED_SPEC = (
    "spec_id", "label", "sub_slice", "class_skill_parametrisation",
    "concretisation", "discrimination_axis", "discrimination_note",
    "proxy_technique", "verification_symptoms", "payload_vector_space",
    "assumptions", "rationale", "interpretation_guidance",
)
AXES = ("chaining-advanced", "tech-misconfiguration", "payload-vector")


def check_spec(spec, loop_id):
    problems = []
    for key in REQUIRED_SPEC:
        if key not in spec or spec[key] in (None, "", [], {}):
            problems.append(f"spec {spec.get('spec_id', '?')}: missing {key}")
    axis = spec.get("discrimination_axis")
    if axis and axis not in AXES:
        problems.append(f"spec {spec.get('spec_id', '?')}: bad axis {axis!r}")
    if axis == "chaining-advanced" and not spec.get("chaining_advanced_note"):
        problems.append(f"spec {spec.get('spec_id', '?')}: chaining-advanced without chaining_advanced_note")
    guidance = (spec.get("interpretation_guidance") or "").lower()
    if guidance and "absent" not in guidance:
        problems.append(f"spec {spec.get('spec_id', '?')}: guidance never reads symptom-absent")
    return problems


def check_file(path, expected_loop):
    problems = []
    try:
        with open(path) as fh:
            doc = yaml.safe_load(fh)
    except Exception as exc:  # noqa: BLE001
        return [f"unparseable: {exc}"], None
    if not isinstance(doc, dict):
        return ["not a mapping"], None
    for key in REQUIRED_TOP:
        if key not in doc:
            problems.append(f"missing top-level {key}")
    if doc.get("loop_id") != expected_loop:
        problems.append(f"loop_id {doc.get('loop_id')!r} != {expected_loop!r}")
    specs = doc.get("specs") or []
    if not specs:
        problems.append("no specs")
    for spec in specs:
        problems.extend(check_spec(spec, expected_loop))
    checks = doc.get("checks") or {}
    try:
        overlap = (checks.get("overlap") or {}).get("status")
        coverage = (checks.get("coverage") or {}).get("status")
    except AttributeError:
        overlap = coverage = None
        problems.append("checks malformed")
    axes = sorted({s.get("discrimination_axis") for s in specs if isinstance(s, dict)})
    summary = {
        "loop": expected_loop,
        "specs": len(specs),
        "axes": axes,
        "overlap": overlap,
        "coverage": coverage,
        "degradations": len(doc.get("degradations") or []),
    }
    return problems, summary


def main():
    total_problems = 0
    for trial in TRIALS:
        outdir = os.path.join(ROOT, trial, "output")
        print(f"===== {trial} =====")
        if not os.path.isdir(outdir):
            print("(no output dir)")
            continue
        names = sorted(
            (n for n in os.listdir(outdir) if n.startswith("loop-") and n.endswith(".yaml")),
            key=lambda n: int(n.split("-")[1].split(".")[0]),
        )
        for name in names:
            loop = name[:-5]
            problems, summary = check_file(os.path.join(outdir, name), loop)
            total_problems += len(problems)
            if summary:
                print(
                    f"{summary['loop']}: specs={summary['specs']} axes={','.join(summary['axes'])} "
                    f"overlap={summary['overlap']} coverage={summary['coverage']} "
                    f"degradations={summary['degradations']}"
                )
            for problem in problems:
                print(f"  !! {problem}")
        log = os.path.join(ROOT, trial, "run-log.md")
        print(f"run-log: {'present' if os.path.exists(log) else 'MISSING'}")
    print(f"total mechanical problems: {total_problems}")
    return 1 if total_problems else 0


if __name__ == "__main__":
    sys.exit(main())
