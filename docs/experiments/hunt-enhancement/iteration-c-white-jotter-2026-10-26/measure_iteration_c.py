#!/usr/bin/env python3
"""Iteration C measurement: the CIA red/green share and its companions.

The primary metric is defined by `docs/design/impact-assessment-system-spec.md`
section 9 over every `impact_assessment` row of every unit model:

    green_share = green / impact_rows

where a row is green when any CIA value is not `none`, red when every value is
`none`, and a placeholder row is red by the invariant.

The severe share is the damage-bearing subset at impact weight 3 or above:

    severe_share = threats with impact_weight >= 3 / damage-bearing threats

The retired class-based green share is still computed and marked superseded, so
iteration B and B.a stay comparable as a continuity note and never as a gate.

Usage:
    measure_iteration_c.py --project-root DIR --suite DIR \\
        [--trial trial.yaml] [--monitor monitor.jsonl] [--out metrics.yaml]
"""
from __future__ import annotations

import argparse
import collections
import json
from pathlib import Path

import yaml

CIA_KEYS = ("confidentiality", "integrity", "availability")
STAGES = ("produced", "consumed", "abandoned")

# The retired class-based set, kept only for the continuity note.
NARROW = {
    "xss", "ssrf", "broken-function-level-authorization", "idor",
    "mass-assignment", "business-logic", "race-conditions",
    "session-management", "rce", "insecure-deserialization",
    "sql-injection", "nosql-injection", "ssti", "csrf",
}
BROAD = NARROW | {
    "path-traversal-lfi-rfi", "xxe", "header-injection",
    "http-request-smuggling", "prototype-pollution", "cache-poisoning",
    "open-redirect", "graphql", "ldap-injection", "xpath-injection",
    "email-header-injection", "insecure-file-uploads", "authentication-jwt",
    "oauth", "mfa-bypass", "account-recovery", "weak-credential-discovery",
    "crypto-weakness", "http-method-tampering", "http-parameter-pollution",
    "subdomain-takeover", "llm-prompt-injection",
}


def load_yaml(path: Path) -> dict:
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def suite_index(suite: Path) -> dict[str, str]:
    parent: dict[str, str] = {}
    for directory in sorted(suite.iterdir()):
        if not directory.is_dir():
            continue
        parent[directory.name] = directory.name
        for child in directory.iterdir():
            if child.is_dir() and (child / "SKILL.md").is_file():
                parent[child.name] = directory.name
    return parent


def unit_models(project_root: Path) -> list[dict]:
    models: list[dict] = []
    modeller = project_root / "hunting/threat_modeller"
    for stage in STAGES:
        stage_dir = modeller / stage
        if not stage_dir.is_dir():
            continue
        for directory in sorted(stage_dir.iterdir()):
            if not directory.is_dir():
                continue
            for path in sorted(directory.glob("*.yaml")):
                if path.name.startswith("threat-"):
                    continue
                models.append({
                    "unit": directory.name,
                    "stage": stage,
                    "path": str(path),
                    "model": load_yaml(path),
                })
    return models


def impact_rows(models: list[dict]) -> list[dict]:
    rows: list[dict] = []
    for entry in models:
        model = entry["model"]
        threats = {
            str(row.get("id") or ""): row
            for row in (model.get("threats") or [])
            if isinstance(row, dict)
        }
        for assessment in (model.get("impact_assessment") or []):
            if not isinstance(assessment, dict):
                continue
            ref = str(assessment.get("vulnerability_ref") or "")
            threat = threats.get(ref) or {}
            impact = threat.get("impact") or {}
            vector = {key: str(impact.get(key) or "none") for key in CIA_KEYS}
            green = any(level != "none" for level in vector.values())
            rows.append({
                "unit": entry["unit"],
                "stage": entry["stage"],
                "id": str(assessment.get("id") or ""),
                "disposition": str(assessment.get("disposition") or ""),
                "vulnerability_ref": ref,
                "vector": vector,
                "green": green,
                "impact_weight": int(threat.get("impact_weight") or 0),
                "risk": int(threat.get("risk") or 0),
                "class": str(threat.get("web_vulnerability_class") or ""),
                "threat_id": str(threat.get("id") or ""),
            })
    return rows


def stored_threats(project_root: Path) -> list[dict]:
    threats: list[dict] = []
    modeller = project_root / "hunting/threat_modeller"
    for stage in ("produced", "consumed"):
        for path in sorted((modeller / stage).glob("*/threat-*.yaml")):
            data = load_yaml(path)
            body = data.get("threat") or {}
            impact = body.get("impact") or {}
            threats.append({
                "unit": str(data.get("unit_id") or path.parent.name),
                "id": str(data.get("threat_id") or path.stem),
                "class": str(body.get("web_vulnerability_class") or ""),
                "risk": int(body.get("risk") or 0),
                "impact_weight": int(body.get("impact_weight") or 0),
                "vector": {
                    key: str(impact.get(key) or "none") for key in CIA_KEYS},
                "stage": stage,
            })
    return threats


def specs(project_root: Path) -> list[dict]:
    rows: list[dict] = []
    for path in sorted(
        (project_root / "hunting/hunter/test-specs").rglob("*.yaml")
    ):
        if path.name == "terminal.yaml":
            continue
        data = load_yaml(path)
        provenance = data.get("provenance") or {}
        if not provenance:
            continue
        threat_id = str(
            provenance.get("threat_id") or provenance.get("loop_id") or "")
        if "__" in threat_id:
            threat_id = threat_id.rsplit("__", 1)[-1]
        rows.append({
            "unit": str(provenance.get("unit_id") or ""),
            "threat": threat_id,
            "status": data.get("status"),
            "discriminators": data.get("discriminators") or [],
        })
    return rows


def spec_summary(rows: list[dict]) -> dict:
    axes: list[str] = []
    for row in rows:
        axis = ""
        for discriminator in row.get("discriminators") or []:
            if isinstance(discriminator, dict) and discriminator.get("axis"):
                axis = str(discriminator["axis"])
                break
        axes.append(axis)
    present = [axis for axis in axes if axis]
    return {
        "spec_count": len(rows),
        "ratified_count": sum(1 for row in rows if row.get("status") == "ratified"),
        "substantial": len(rows) >= 3,
        "axes": axes,
        "axes_overlap": len(set(present)) != len(present),
        "well_formed": (
            len(rows) >= 3 and all(axes) and len(set(present)) == len(present)),
    }


def pods(project_root: Path) -> dict:
    root = project_root / "hunting/test-executor-pod"
    reasons: collections.Counter = collections.Counter()
    exports = 0
    resumes = 0
    if root.is_dir():
        resumes = len(list(root.glob("*/*.resume.yaml")))
        for path in root.glob("*/*.yaml"):
            if path.name.endswith(".resume.yaml") or path.name == "notes.yaml":
                continue
            data = load_yaml(path)
            reason = str(
                (data.get("evidence") or {}).get("terminal_reason") or "none")
            reasons[reason] += 1
            exports += 1
    return {"exports": exports, "resumes": resumes, "terminals": dict(reasons)}


def batch_check(monitor: Path | None, width: int) -> dict:
    if monitor is None or not monitor.is_file():
        return {}
    counts: list[int] = []
    violations = 0
    for line in monitor.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except Exception:
            continue
        live = row.get("live_hunts")
        if isinstance(live, list):
            counts.append(len(live))
            if len(live) > width:
                violations += 1
    return {
        "samples": len(counts),
        "max_live_hunts": max(counts) if counts else None,
        "pod_batch_size": width,
        "violations": violations,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--suite", required=True)
    parser.add_argument("--trial")
    parser.add_argument("--monitor")
    parser.add_argument("--out", required=True)
    parser.add_argument("--pod-batch-size", type=int, default=3)
    parser.add_argument("--promotion-floor", type=int, default=0)
    parser.add_argument("--green-gate", type=float, default=0.90)
    args = parser.parse_args()

    project_root = Path(args.project_root)
    parent = suite_index(Path(args.suite))
    models = unit_models(project_root)
    rows = impact_rows(models)
    threats = stored_threats(project_root)
    spec_rows = specs(project_root)
    pod_rows = pods(project_root)

    total = len(rows)
    green = sum(1 for row in rows if row["green"])
    distribution: dict[str, dict[str, int]] = {key: {} for key in CIA_KEYS}
    for row in rows:
        for key in CIA_KEYS:
            level = row["vector"][key]
            distribution[key][level] = distribution[key].get(level, 0) + 1

    damage_bearing = [row for row in threats if any(
        level != "none" for level in row["vector"].values())]
    severe = [row for row in damage_bearing if row["impact_weight"] >= 3]

    by_threat: dict[tuple, list] = collections.defaultdict(list)
    for spec in spec_rows:
        by_threat[(spec["unit"], spec["threat"])].append(spec)
    spec_shapes = []
    for threat in threats:
        summary = spec_summary(
            by_threat.get((threat["unit"], threat["id"]), []))
        spec_shapes.append({**threat, **summary})

    promoted = [t for t in threats if args.promotion_floor <= 0
                or t["risk"] >= args.promotion_floor]
    demoted = [t for t in threats if args.promotion_floor > 0
               and t["risk"] < args.promotion_floor]

    class_binding = [t for t in threats if t["class"] in parent]
    narrow_green = [
        t for t in threats if parent.get(t["class"], t["class"]) in NARROW]
    broad_green = [
        t for t in threats if parent.get(t["class"], t["class"]) in BROAD]

    token_tax = {}
    trial_data = load_yaml(Path(args.trial)) if args.trial else {}
    if trial_data:
        by_agent = trial_data.get("spend_by_agent") or {}
        token_tax = {
            "spent_tokens": trial_data.get("spent_tokens"),
            "terminal": trial_data.get("terminal"),
            "by_agent": {
                name: {
                    "capped": value.get("capped_tokens"),
                    "calls": value.get("calls"),
                    "reasoning": (value.get("generated_tokens") or {}).get(
                        "reasoning"),
                    "visible": (value.get("generated_tokens") or {}).get(
                        "visible"),
                }
                for name, value in by_agent.items()
            },
        }

    payload = {
        "schema_version": 1,
        "project_root": str(project_root),
        "primary": {
            "impact_rows": total,
            "green": green,
            "red": total - green,
            "green_share": green / total if total else None,
            "threat_share": (
                sum(1 for row in rows if row["disposition"] == "threat") / total
                if total else None),
            "placeholder_share": (
                sum(1 for row in rows if row["disposition"] == "placeholder")
                / total if total else None),
            "gate": args.green_gate,
            "gate_met": (
                (green / total) > args.green_gate if total else None),
        },
        "severe": {
            "damage_bearing": len(damage_bearing),
            "severe": len(severe),
            "severe_share": (
                len(severe) / len(damage_bearing) if damage_bearing else None),
        },
        "cia_distribution": distribution,
        "promotion": {
            "stored": len(threats),
            "promoted": len(promoted),
            "demoted": len(demoted),
            "floor": args.promotion_floor,
            "demoted_ids": [t["id"] for t in demoted],
            "risk_total": sum(t["risk"] for t in threats),
        },
        "continuity_superseded": {
            "note": "class-based green share; retired as a gate",
            "green_narrow": len(narrow_green),
            "green_narrow_share": (
                len(narrow_green) / len(threats) if threats else None),
            "green_broad": len(broad_green),
            "green_broad_share": (
                len(broad_green) / len(threats) if threats else None),
            "class_binding": len(class_binding),
            "class_binding_rate": (
                len(class_binding) / len(threats) if threats else None),
        },
        "coverage": {
            "units_modelled": sorted({m["unit"] for m in models}),
            "units_consumed": sorted({
                m["unit"] for m in models if m["stage"] == "consumed"}),
            "threats_specced": len({
                (spec["unit"], spec["threat"]) for spec in spec_rows}),
            "specs_total": len(spec_rows),
            "specs_ratified": sum(
                1 for spec in spec_rows if spec["status"] == "ratified"),
            "substantial": sum(1 for row in spec_shapes if row["substantial"]),
            "well_formed": sum(1 for row in spec_shapes if row["well_formed"]),
            "pods": pod_rows,
        },
        "batch": batch_check(
            Path(args.monitor) if args.monitor else None,
            args.pod_batch_size),
        "token_tax": token_tax,
        "impact_rows": rows,
        "threats": [
            {
                "unit": t["unit"],
                "id": t["id"],
                "class": t["class"],
                "risk": t["risk"],
                "impact_weight": t["impact_weight"],
                "vector": t["vector"],
                "green": any(v != "none" for v in t["vector"].values()),
                "spec_count": t["spec_count"],
                "substantial": t["substantial"],
                "well_formed": t["well_formed"],
            }
            for t in spec_shapes
        ],
    }

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    primary = payload["primary"]
    print(
        f"impact_rows={primary['impact_rows']} green={primary['green']} "
        f"share={primary['green_share']} "
        f"severe={payload['severe']['severe']}/"
        f"{payload['severe']['damage_bearing']} "
        f"({payload['severe']['severe_share']}) "
        f"gate_met={primary['gate_met']}"
    )


if __name__ == "__main__":
    main()
