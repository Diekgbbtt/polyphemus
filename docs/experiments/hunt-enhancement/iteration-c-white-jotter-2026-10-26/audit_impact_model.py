#!/usr/bin/env python3
"""Audit the impact-first threat model: severity, prose, precursors, paths.

Prints one row per threat plus distributions.  The scope-fencing question is
whether every threat carries a severe CIA effect and a concrete victim; the
precursor question is whether non-damage findings are carried as capability
steps and whether paths are well formed.

Usage:
  python3 audit_impact_model.py --project-root <root> [--threats] [--json]
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

import yaml


def load(path: pathlib.Path) -> dict:
    try:
        return yaml.safe_load(path.read_text()) or {}
    except Exception:
        return {}


def rows(root: pathlib.Path) -> list[dict]:
    out: list[dict] = []
    model_root = root / "hunting/threat_modeller"
    for stage in ("produced", "consumed"):
        for unit_dir in sorted((model_root / stage).glob("*")):
            model_file = unit_dir / f"{unit_dir.name}.yaml"
            if not model_file.is_file():
                continue
            model = load(model_file)
            precursors = {
                str(p.get("id")): p
                for p in (model.get("precursors") or [])
                if isinstance(p, dict)
            }
            impact = {
                str(r.get("id")): r
                for r in (model.get("impact_assessment") or [])
                if isinstance(r, dict)
            }
            for threat in model.get("threats") or []:
                if not isinstance(threat, dict):
                    continue
                assessment = impact.get(str(threat.get("impact_ref"))) or {}
                cia = threat.get("impact") or {}
                levels = tuple(str(cia.get(k) or "none") for k in ("confidentiality", "integrity", "availability"))
                path = [str(x) for x in (threat.get("enabling_precursors") or [])]
                damage = " ".join(str(assessment.get("damage") or "").split())
                out.append(
                    {
                        "unit": str(model.get("unit_id")),
                        "threat": str(threat.get("id")),
                        "class": str(threat.get("web_vulnerability_class")),
                        "risk": int(threat.get("risk") or 0),
                        "weight": int(threat.get("impact_weight") or 0),
                        "cia": levels,
                        "damage": damage,
                        "damage_words": len(damage.split()),
                        "path": path,
                        "path_len": len(path),
                        "precursors": [
                            {
                                "id": pid,
                                "capability": str((precursors.get(pid) or {}).get("capability") or ""),
                                "procedure_len": len(
                                    str((precursors.get(pid) or {}).get("procedure") or "").split()
                                ),
                            }
                            for pid in path
                        ],
                        "evidence": len(assessment.get("evidence_refs") or []),
                    }
                )
    return out


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project-root", required=True)
    ap.add_argument("--threats", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    data = rows(pathlib.Path(args.project_root))
    if args.json:
        print(json.dumps(data, indent=1))
        return 0
    if args.threats:
        for row in sorted(data, key=lambda r: r["risk"]):
            print(
                f"{row['risk']:3d} w={row['weight']} {row['unit'][:30]:30s} {row['threat']:9s} "
                f"{'/'.join(row['cia']):22s} path={row['path_len']} words={row['damage_words']:3d} "
                f"{row['class'][:48]}"
            )
            print(f"      {row['damage'][:260]}")
            print(f"      path={row['path']} caps={[p['capability'][:48] for p in row['precursors']]}")
        return 0
    weights: dict[int, int] = {}
    for row in data:
        weights[row["weight"]] = weights.get(row["weight"], 0) + 1
    paths = {row["path_len"]: 0 for row in data}
    for row in data:
        paths[row["path_len"]] += 1
    print(f"threats={len(data)}")
    print(f"impact_weight histogram: {dict(sorted(weights.items()))}")
    print(f"path length histogram: {dict(sorted(paths.items()))}")
    print(f"damage words: min={min(r['damage_words'] for r in data)} median={sorted(r['damage_words'] for r in data)[len(data)//2]} max={max(r['damage_words'] for r in data)}")
    nonsevere = [r for r in data if r["weight"] <= 2]
    print(f"non-severe (weight<=2): {len(nonsevere)}")
    for r in nonsevere:
        print(f"  {r['risk']:3d} w={r['weight']} {r['unit'][:32]:32s} {r['threat']:9s} {'/'.join(r['cia']):22s} {r['class'][:50]}")
    empty = [r for r in data if not r["path"]]
    print(f"empty paths: {len(empty)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
