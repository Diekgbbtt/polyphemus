#!/usr/bin/env python3
"""Survey the threat-modeller loops of one hunting run.

The survey is read-only over the persisted artifacts. It answers four
questions per loop: what class the modeller named, which trust boundary and
fault it rests on, how the loop was ranked, and whether the named class is a
real suite class or leaf.

Usage:
    python survey_modeller_loops.py \
        --hunting-dir /path/to/instance/hunting \
        --suite-dir skills/web-vulnerability-testing \
        --classification loop-classification.csv \
        --out /path/to/out

`--classification` is optional. It is a CSV keyed on `unit,loop` with the
manual impact tier, family, boundary shape, and note. Without it the script
still emits the structural census and the class-integrity findings.

The script never writes into the instance directory.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path

import yaml


def load_suite(suite_dir: Path) -> tuple[set[str], dict[str, str], set[str]]:
    """Return (class parents, leaf -> parent, level-1 technique families).

    A class parent is a level-1 directory with a SKILL.md. A leaf is a
    second-level directory with a SKILL.md. `defence-bypass` and
    `proxy-techniques` are class parents in the tree but technique families
    semantically; the caller decides how to treat them.
    """
    parents: set[str] = set()
    leaves: dict[str, str] = {}
    if not suite_dir.is_dir():
        return parents, leaves, set()
    for parent in sorted(suite_dir.iterdir()):
        if not parent.is_dir() or parent.name.startswith("."):
            continue
        if not (parent / "SKILL.md").is_file():
            continue
        parents.add(parent.name)
        for leaf in sorted(parent.iterdir()):
            if leaf.is_dir() and (leaf / "SKILL.md").is_file():
                leaves[leaf.name] = parent.name
    families = {"defence-bypass", "proxy-techniques", "two-principal-authz"}
    return parents, leaves, families


def iter_models(hunting_dir: Path):
    """Yield (bucket, model_path) for produced, consumed, and abandoned."""
    root = hunting_dir / "threat_modeller"
    for bucket in ("produced", "consumed", "abandoned"):
        bucket_dir = root / bucket
        if not bucket_dir.is_dir():
            continue
        for unit_dir in sorted(bucket_dir.iterdir()):
            if not unit_dir.is_dir():
                continue
            for path in sorted(unit_dir.glob("*.yaml")):
                if path.name.startswith("loop-"):
                    continue
                yield bucket, path


def index(model: dict) -> dict:
    faults = {}
    for assumption in model.get("assumptions") or []:
        fault = assumption.get("fault") or {}
        if fault.get("id"):
            faults[fault["id"]] = {
                **fault,
                "assumption": assumption.get("statement", ""),
                "boundary_ref": assumption.get("boundary_ref", ""),
            }
    return {
        "faults": faults,
        "vulnerabilities": {v["id"]: v for v in model.get("vulnerabilities") or []},
        "failure_modes": {m["id"]: m for m in model.get("failure_modes") or []},
        "trust_agreements": {
            t["id"]: t for t in (model.get("trust_model") or {}).get("trust_agreements") or []
        },
    }


def survey(hunting_dir: Path, parents, leaves, families) -> list[dict]:
    records: list[dict] = []
    for bucket, path in iter_models(hunting_dir):
        model = yaml.safe_load(path.read_text())
        idx = index(model)
        for rank, loop in enumerate(model.get("loops") or [], start=1):
            vulnerability = idx["vulnerabilities"].get(loop.get("vulnerability_ref"), {})
            fault = idx["faults"].get(loop.get("fault_ref"), {})
            trust = idx["trust_agreements"].get(fault.get("boundary_ref"), {})
            failure_modes = [
                idx["failure_modes"].get(ref, {})
                for ref in loop.get("failure_mode_refs") or []
            ]
            web = loop.get("web_vulnerability_class") or ""
            if not web:
                class_status = "empty"
            elif web in families:
                class_status = "technique-family"
            elif web in parents:
                class_status = "class-parent"
            elif web in leaves:
                class_status = "class-leaf"
            else:
                class_status = "not-in-suite"
            records.append(
                {
                    "bucket": bucket,
                    "unit": model.get("unit_id", ""),
                    "loop": loop.get("id", ""),
                    "rank": rank,
                    "likelihood": loop.get("likelihood", ""),
                    "web_vulnerability_class": web,
                    "class_status": class_status,
                    "class_parent": leaves.get(web, web if web in parents else ""),
                    "canonical_class": loop.get("canonical_class", ""),
                    "suite_gap": bool(loop.get("suite_gap")),
                    "fault_id": loop.get("fault_ref", ""),
                    "fault_label": fault.get("label", ""),
                    "fault_description": fault.get("description", ""),
                    "assumption": fault.get("assumption", ""),
                    "trust_boundary": trust.get("boundary", ""),
                    "trust_statement": trust.get("statement", ""),
                    "vulnerability_characterisation": vulnerability.get("characterisation", ""),
                    "failure_mode": " | ".join(m.get("mode", "") for m in failure_modes),
                    "failure_mode_feasibility": " | ".join(
                        m.get("feasibility", "") for m in failure_modes
                    ),
                    "failure_mode_rationale": " | ".join(
                        m.get("feasibility_rationale", "") for m in failure_modes
                    ),
                    "evidence_kinds": sorted(
                        {e.get("kind", "") for e in loop.get("evidences") or []}
                    ),
                }
            )
    return records


def load_classification(path: Path) -> dict[tuple[str, str], dict]:
    if not path:
        return {}
    out = {}
    with path.open(newline="") as handle:
        for row in csv.DictReader(handle):
            out[(row["unit"], row["loop"])] = row
    return out


def aggregates(records: list[dict], classification: dict[tuple[str, str], dict]) -> dict:
    def count(key):
        return Counter(r[key] for r in records)

    out = {
        "loops": len(records),
        "models": len({(r["bucket"], r["unit"]) for r in records}),
        "buckets": count("bucket"),
        "likelihood": count("likelihood"),
        "class_status": count("class_status"),
        "suite_gap": sum(1 for r in records if r["suite_gap"]),
        "empty_class": sum(1 for r in records if not r["web_vulnerability_class"]),
    }
    out["units"] = {
        unit: {
            "loops": len(sub),
            "severe": sum(1 for r in sub if classification.get((r["unit"], r["loop"]), {}).get("impact_tier") == "severe"),
            "low": sum(1 for r in sub if classification.get((r["unit"], r["loop"]), {}).get("impact_tier") == "low"),
        }
        for unit, sub in (
            (unit, [r for r in records if r["unit"] == unit])
            for unit in sorted({r["unit"] for r in records})
        )
    }
    if classification:
        for key in ("impact_tier", "impact_family", "boundary_shape"):
            out[key] = Counter(
                classification.get((r["unit"], r["loop"]), {}).get(key, "")
                for r in records
            )
        out["tier_x_bucket"] = {
            bucket: Counter(
                classification.get((r["unit"], r["loop"]), {}).get("impact_tier", "")
                for r in records
                if r["bucket"] == bucket
            )
            for bucket in ("produced", "consumed", "abandoned")
        }
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hunting-dir", required=True, type=Path)
    parser.add_argument("--suite-dir", type=Path, default=Path("skills/web-vulnerability-testing"))
    parser.add_argument("--classification", type=Path, default=None)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)

    parents, leaves, families = load_suite(args.suite_dir)
    records = survey(args.hunting_dir, parents, leaves, families)
    classification = load_classification(args.classification)
    args.out.mkdir(parents=True, exist_ok=True)

    with (args.out / "loops.jsonl").open("w") as handle:
        for record in records:
            handle.write(json.dumps(record, sort_keys=True) + "\n")
    with (args.out / "aggregates.json").open("w") as handle:
        json.dump(aggregates(records, classification), handle, indent=2, sort_keys=True)
    with (args.out / "loops.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)

    print(f"loops: {len(records)}")
    print(f"models: {len({(r['bucket'], r['unit']) for r in records})}")
    print(f"empty class: {sum(1 for r in records if not r['web_vulnerability_class'])}")
    print(f"suite gap: {sum(1 for r in records if r['suite_gap'])}")
    for status, count in Counter(r["class_status"] for r in records).most_common():
        print(f"  {status}: {count}")
    if classification:
        for tier, count in Counter(
            classification.get((r["unit"], r["loop"]), {}).get("impact_tier", "")
            for r in records
        ).most_common():
            print(f"  tier {tier}: {count}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
