#!/usr/bin/env python3
"""Comparison tooling for the T1-TBSG evaluation (see assessment-plan.md).

Subcommands:
  render <model.yaml> <out.md>     Render a model into a neutral, variant-blind corpus.
  inventory <model.yaml> <out.json>  Extract the boundary/assumption/vulnerability inventory.
  dups <model.yaml> [threshold]    Print near-duplicate assumption pairs (token Jaccard).

The renderer keeps the two schemas symmetric: both the baseline surface
(guard_verified / guard_assumed) and the integrated surface (establishes /
requires) render into the same "enforced checks" / "relied-on requirements"
lines, and only content common to both surfaces is rendered (treatment-only
fields such as boundary_ref / dimension / propagation are excluded by design,
per the pre-registered protocol).
"""

import json
import re
import sys

import yaml

STOPWORDS = {
    "the", "a", "an", "of", "to", "and", "or", "in", "on", "for", "with", "is",
    "are", "was", "were", "be", "been", "it", "its", "this", "that", "these",
    "those", "as", "at", "by", "from", "not", "no", "so", "if", "then", "than",
    "any", "all", "each", "can", "could", "may", "might", "must", "has", "have",
    "had", "does", "do", "did", "which", "when", "where", "who", "whom", "whose",
    "into", "over", "under", "after", "before", "but", "we", "they", "he", "she",
}


def load_model(path):
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def as_items(value):
    """Normalise a scalar-or-list field into a list of plain strings."""
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        out = []
        for item in value:
            if isinstance(item, dict):
                text = item.get("item") or item.get("statement") or json.dumps(item, ensure_ascii=False)
                out.append(str(text))
            else:
                out.append(str(item))
        return out
    return [str(value)]


def first_items(record, keys):
    for key in keys:
        if key in record and record[key] is not None:
            return as_items(record[key])
    return []


def render(model, out_path):
    lines = []
    lines.append(f"# Anonymous model rendering - unit {model.get('unit_id', '?')}")
    lines.append("")

    technical = model.get("technical_sharpening") or {}
    lines.append("## Interface agreements")
    for ia in technical.get("interface_agreements") or []:
        lines.append(f"- {ia.get('id')}: {ia.get('statement', '')}")
    lines.append("")

    trust = model.get("trust_model") or {}
    lines.append("## Trust agreements")
    for ta in trust.get("trust_agreements") or []:
        lines.append(f"- {ta.get('id')}: {ta.get('statement', '')}")
    lines.append("")

    dynamic = trust.get("dynamic_state_trust") or {}
    lines.append("## Dynamic-state transitions")
    for tr in dynamic.get("transitions") or []:
        lines.append(
            f"- {tr.get('id')}: {tr.get('state_from', '?')} -> {tr.get('state_to', '?')}: "
            f"{tr.get('trigger', '')}"
        )
        enforced = first_items(tr, ["guard_verified", "establishes"])
        relied = first_items(tr, ["guard_assumed", "requires"])
        if enforced:
            lines.append(f"    - enforced checks: {'; '.join(enforced)}")
        if relied:
            lines.append(f"    - relied-on requirements: {'; '.join(relied)}")
        if tr.get("side_effects"):
            lines.append(f"    - side effects: {tr['side_effects']}")
    lines.append("")

    faults = {f.get("id"): f.get("name", "") for f in (model.get("faults") or [])}
    lines.append("## Assumptions")
    for a in model.get("assumptions") or []:
        fault_id = a.get("induced_fault")
        lines.append(f"- {a.get('id')}: {a.get('statement', '')}")
        lines.append(f"    - induced fault: {fault_id} ({faults.get(fault_id, '?')})")
    lines.append("")

    lines.append("## Vulnerabilities")
    for v in model.get("vulnerabilities") or []:
        lines.append(f"- {v.get('id')}: {v.get('class', '')} (fault {v.get('fault_ref')})")
    lines.append("")

    lines.append("## Loops")
    for loop in model.get("loops") or []:
        lines.append(
            f"- {loop.get('loop_id')}: fault {loop.get('fault_ref')} -> "
            f"{loop.get('vulnerability_ref')} ({loop.get('likelihood', '?')})"
        )

    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


def tokens(text):
    words = re.findall(r"[a-z0-9_]+", (text or "").lower())
    return {w for w in words if w not in STOPWORDS and len(w) > 1}


def inventory(model, out_path):
    faults = {f.get("id"): f.get("name", "") for f in (model.get("faults") or [])}
    vulns_by_fault = {}
    for v in model.get("vulnerabilities") or []:
        vulns_by_fault.setdefault(v.get("fault_ref"), []).append(v.get("class"))
    loops_by_fault = {}
    for loop in model.get("loops") or []:
        loops_by_fault.setdefault(loop.get("fault_ref"), []).append(
            {"loop_id": loop.get("loop_id"), "likelihood": loop.get("likelihood")}
        )

    data = {
        "unit_id": model.get("unit_id"),
        "counts": {
            "interface_agreements": len((model.get("technical_sharpening") or {}).get("interface_agreements") or []),
            "trust_agreements": len((model.get("trust_model") or {}).get("trust_agreements") or []),
            "transitions": len(((model.get("trust_model") or {}).get("dynamic_state_trust") or {}).get("transitions") or []),
            "assumptions": len(model.get("assumptions") or []),
            "faults": len(model.get("faults") or []),
            "vulnerabilities": len(model.get("vulnerabilities") or []),
            "loops": len(model.get("loops") or []),
        },
        "assumptions": [],
        "boundaries": {
            "interface_agreements": [
                {"id": ia.get("id"), "statement": ia.get("statement")}
                for ia in (model.get("technical_sharpening") or {}).get("interface_agreements") or []
            ],
            "trust_agreements": [
                {"id": ta.get("id"), "statement": ta.get("statement")}
                for ta in (model.get("trust_model") or {}).get("trust_agreements") or []
            ],
            "transitions": [
                {
                    "id": tr.get("id"),
                    "state_from": tr.get("state_from"),
                    "state_to": tr.get("state_to"),
                    "trigger": tr.get("trigger"),
                }
                for tr in ((model.get("trust_model") or {}).get("dynamic_state_trust") or {}).get("transitions") or []
            ],
        },
    }
    for a in model.get("assumptions") or []:
        fault_id = a.get("induced_fault")
        data["assumptions"].append(
            {
                "id": a.get("id"),
                "statement": a.get("statement"),
                "fault_id": fault_id,
                "fault_name": faults.get(fault_id, ""),
                "vulnerabilities": vulns_by_fault.get(fault_id, []),
                "loops": loops_by_fault.get(fault_id, []),
            }
        )
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)


def dups(model, threshold):
    assumptions = model.get("assumptions") or []
    sets = [(a.get("id"), tokens(a.get("statement"))) for a in assumptions]
    for i in range(len(sets)):
        for j in range(i + 1, len(sets)):
            a_id, a_toks = sets[i]
            b_id, b_toks = sets[j]
            if not a_toks or not b_toks:
                continue
            jaccard = len(a_toks & b_toks) / len(a_toks | b_toks)
            if jaccard >= threshold:
                print(f"{a_id} ~ {b_id}: jaccard={jaccard:.2f}")


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    command = sys.argv[1]
    model = load_model(sys.argv[2])
    if command == "render":
        render(model, sys.argv[3])
    elif command == "inventory":
        inventory(model, sys.argv[3])
    elif command == "dups":
        threshold = float(sys.argv[3]) if len(sys.argv) > 3 else 0.6
        dups(model, threshold)
    else:
        print(f"unknown command: {command}")
        sys.exit(1)


if __name__ == "__main__":
    main()
