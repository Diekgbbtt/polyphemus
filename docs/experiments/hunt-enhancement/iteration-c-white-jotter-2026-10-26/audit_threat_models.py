#!/usr/bin/env python3
"""Audit every threat-modeller unit model: state, threats, impact rows, precursors.

Red-capable signal: a unit whose model state is terminal and whose threat list is
empty.  Deterministic and fast: it reads only the persisted artifacts.

Usage:
  python3 audit_threat_models.py --project-root <root>            # table + red signal
  python3 audit_threat_models.py --project-root <root> --zero     # decision detail for zero-threat units
  python3 audit_threat_models.py --project-root <root> --json
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

import yaml

CIA = ("confidentiality", "integrity", "availability")


def load(path: pathlib.Path) -> dict:
    try:
        return yaml.safe_load(path.read_text()) or {}
    except Exception as exc:  # pragma: no cover - evidence script
        return {"__error__": f"{type(exc).__name__}: {exc}"}


def row_levels(row: dict) -> tuple[str, ...]:
    scores = row.get("scores") or row.get("impact") or {}
    if isinstance(scores, dict) and scores:
        return tuple(str(scores.get(k) or "none") for k in CIA)
    return tuple(str(row.get(k) or "none") for k in CIA)


def model_rows(model: dict) -> list[dict]:
    return [r for r in (model.get("impact_assessment") or []) if isinstance(r, dict)]


def audit(root: pathlib.Path) -> list[dict]:
    model_root = root / "hunting/threat_modeller"
    out: list[dict] = []
    for stage in ("produced", "consumed"):
        for unit_dir in sorted((model_root / stage).glob("*")):
            if not unit_dir.is_dir():
                continue
            candidate = unit_dir / f"{unit_dir.name}.yaml"
            if not candidate.is_file():
                candidates = [
                    p for p in sorted(unit_dir.glob("*.yaml")) if not p.name.startswith("threat-")
                ]
                candidate = candidates[0] if candidates else None
            if candidate is None:
                out.append(
                    {
                        "unit_dir": unit_dir.name,
                        "stage": stage,
                        "state": "MISSING_MODEL",
                        "threats": 0,
                        "bugs": ["no model file in unit directory"],
                    }
                )
                continue
            model = load(candidate)
            threats = [t for t in (model.get("threats") or []) if isinstance(t, dict)]
            rows = model_rows(model)
            dispatch = [r for r in rows if r.get("disposition") != "placeholder"]
            placeholders = [r for r in rows if r.get("disposition") == "placeholder"]
            precursors = [p for p in (model.get("precursors") or []) if isinstance(p, dict)]
            out.append(
                {
                    "unit": model.get("unit_id") or unit_dir.name,
                    "stage": stage,
                    "state": str(model.get("state") or "UNKNOWN"),
                    "threats": len(threats),
                    "threat_risks": [int(t.get("risk") or 0) for t in threats],
                    "rows": len(rows),
                    "dispatch_rows": len(dispatch),
                    "placeholders": len(placeholders),
                    "placeholder_refs": [str(r.get("precursor_refs") or []) for r in placeholders],
                    "precursors": len(precursors),
                    "precursor_ids": [str(p.get("id")) for p in precursors],
                    "vulns": [
                        {
                            "id": str(v.get("id")),
                            "class": str(v.get("web_vulnerability_class") or ""),
                            "dropped": bool(v.get("dropped")),
                            "confidence": str(v.get("confidence") or ""),
                        }
                        for v in (model.get("vulnerabilities") or [])
                        if isinstance(v, dict)
                    ],
                    "validation_valid": (model.get("validation") or {}).get("valid"),
                    "path": str(candidate),
                }
            )
    return out


def print_zero_detail(rows: list[dict]) -> None:
    for r in rows:
        if r["threats"]:
            continue
        print("=" * 100)
        print(f"UNIT {r.get('unit')} [{r['stage']}] state={r['state']} valid={r.get('validation_valid')}")
        for v in r.get("vulns") or []:
            print(f"  V {v['id']} class={v['class']} dropped={v['dropped']} conf={v['confidence']}")
        print(f"  impact rows={r['rows']} dispatch={r['dispatch_rows']} placeholders={r['placeholders']}")
        print(f"  precursors={r['precursors']} {r.get('precursor_ids')}")
        model = load(pathlib.Path(r["path"]))
        for row in model_rows(model):
            if row.get("disposition") == "placeholder":
                damage = " ".join(str(row.get("damage") or "").split())
                refs = row.get("precursor_refs") or []
                path = row.get("capability_path") or []
                print(f"    PLACEHOLDER {row.get('id')} vuln={row.get('vulnerability_ref')} refs={refs} path={path}")
                print(f"      {damage[:700]}")
        for p in (model.get("precursors") or []):
            if isinstance(p, dict):
                print(f"    PRECURSOR {p}")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project-root", required=True)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--zero", action="store_true")
    args = ap.parse_args(argv)
    root = pathlib.Path(args.project_root)
    rows = audit(root)
    if args.json:
        print(json.dumps(rows, indent=1, default=str))
    elif args.zero:
        print_zero_detail(rows)
    else:
        hdr = "% -36s % -9s % -12s %4s %4s %4s %4s %4s  %s"
        print(hdr % ("unit", "stage", "state", "thr", "rows", "disp", "ph", "prec", "risk"))
        for r in rows:
            print(
                hdr
                % (
                    str(r.get("unit"))[:36],
                    r["stage"],
                    r["state"][:12],
                    r["threats"],
                    r["rows"],
                    r["dispatch_rows"],
                    r["placeholders"],
                    r["precursors"],
                    sum(r.get("threat_risks") or []),
                )
            )
    zero = [r for r in rows if r["threats"] == 0]
    print(f"\nunits={len(rows)} zero_threat={len(zero)}")
    for r in zero:
        print(
            "ZERO-THREAT %s [%s] state=%s rows=%s placeholders=%s precursors=%s vulns=%s"
            % (
                r.get("unit"),
                r["stage"],
                r["state"],
                r.get("rows"),
                r.get("placeholders"),
                r.get("precursors"),
                ",".join(v["class"] for v in (r.get("vulns") or [])) or "-",
            )
        )
    return 1 if zero else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
