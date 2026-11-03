#!/usr/bin/env python3
"""Audit the iteration C.a pod verdicts and compute the model-side metrics.

Read-only. Run inside the agent container:

    python /opt/eval-tmp/analyze_pods_ca.py \
        --project-id <id> --run-id <run-id> --data-root /srv/data

It prints one JSON object with:
- the raw and audited pod confirmations (a `symptom-confirmed` whose own
  interpretation says runner-failure/zero-bytes is not counted);
- the verdict/reason distribution;
- the per-family audited confirmations;
- the model-side GT production, chain rows, queue rank, and the
  assumed/victim-action penalty counts.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import pathlib
import re
import urllib.request

import yaml

GT = (
    ("white-jotter-001", ("default credential", "weak credential", "cwe-1392", "seeded credential")),
    ("white-jotter-002", ("function-level authorization", "bfla", "authorization bypass", "path-canonicalisation")),
    ("white-jotter-003", ("xss", "cross-site scripting", "innerhtml")),
    ("white-jotter-004", ("jndi", "log4j", "log sink", "log4shell")),
    ("white-jotter-005", ("sql injection", "sqli", "concatenated search")),
    ("white-jotter-006", ("path traversal", "directory traversal", "arbitrary file", "cover.png", "double-decoded", "decode-twice")),
    ("white-jotter-007", ("mass assignment", "role association")),
)
ASSUMED_PENALTY = re.compile(
    r"(?:assumed|assumption)[^.]{0,120}(?:lower|demote|discount|reduce|penalt)|"
    r"(?:lower|demote|discount|reduce|penalt)[^.]{0,120}(?:assumed|assumption)",
    re.I,
)
VICTIM_PENALTY = re.compile(
    r"(?:victim|reader|user)[^.]{0,120}(?:must|has to|needs to)[^.]{0,80}"
    r"(?:open|click|render|visit|read)[^.]{0,120}(?:lower|demote|discount|reduce|cannot force)|"
    r"(?:victim action|reader opens)[^.]{0,120}(?:lower|demote|discount|reduce|cannot force)",
    re.I,
)
FALSE = ("runner-failure", "runner-divergence", "triager degraded", "0 bytes received")


def load(path: pathlib.Path) -> dict:
    try:
        body = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return {}
    return body if isinstance(body, dict) else {}


def model_metrics(root: pathlib.Path, intake: list[str]) -> dict:
    rows, threats, fence = [], [], []
    models_total = 0
    for stage in ("produced", "consumed", "abandoned"):
        for path in (root / stage).glob("*/*.yaml"):
            if path.name.startswith("threat-"):
                continue
            model = load(path)
            if not model:
                continue
            models_total += 1
            unit = str(model.get("unit_id") or path.parent.name)
            for row in model.get("impact_assessment") or []:
                if isinstance(row, dict):
                    rows.append({
                        "unit": unit,
                        "id": row.get("id"),
                        "disposition": row.get("disposition"),
                        "risk": float(row.get("risk") or 0.0),
                        "chain": list(row.get("capability_path") or []),
                        "class": str(row.get("capability") or ""),
                        "impact": str(row.get("impact_description") or ""),
                        "exploitability": str(row.get("exploitability_description") or ""),
                        "risk_vector": str(row.get("risk_vector") or ""),
                    })
            for threat in model.get("threats") or []:
                if isinstance(threat, dict):
                    threats.append({
                        "unit": unit,
                        "unit_name": path.parent.name,
                        "id": threat.get("id"),
                        "risk": float(threat.get("risk") or 0.0),
                        "class": str(threat.get("canonical_class") or ""),
                        "ref": threat.get("impact_ref"),
                        "chain": list(threat.get("enabling_precursors") or []),
                    })
    row_map = {(row["unit"], row["id"]): row for row in rows}
    for threat in threats:
        row = row_map.get((threat["unit"], threat["ref"])) or {}
        threat["row_class"] = str(row.get("class") or "")
        threat["impact"] = str(row.get("impact") or "")
        threat["row_chain"] = list(row.get("chain") or [])
    position = {unit: index for index, unit in enumerate(intake)}
    for threat in threats:
        threat["intake"] = position.get(threat["unit"], 10_000)
        threat["rank"] = int(str(threat["id"]).split("-")[-1]) if str(threat["id"]).startswith("threat-") else 10_000
    queue = sorted(threats, key=lambda t: (-t["risk"], t["intake"], t["rank"], str(t["id"])))
    for index, threat in enumerate(queue, start=1):
        threat["queue_rank"] = index
    gt = {}
    for gt_id, keywords in GT:
        hits = [
            threat for threat in queue
            if any(k in f"{threat['class']} {threat['row_class']} {threat['impact']}".lower()
                   for k in keywords)
        ]
        best = max(hits, key=lambda t: t["risk"]) if hits else None
        gt[gt_id] = {
            "produced": bool(best),
            "risk": best["risk"] if best else 0.0,
            "unit": best["unit"] if best else None,
            "chained": bool(best and (best["chain"] or best["row_chain"])) if best else False,
            "queue_rank": best["queue_rank"] if best else None,
        }
    xss = [t for t in queue if "xss" in t["class"].lower() or "cross-site scripting" in t["class"].lower()]
    xss_best = max(xss, key=lambda t: t["risk"]) if xss else None
    xss_row = row_map.get((xss_best["unit"], xss_best["ref"])) if xss_best else {}
    return {
        "models": models_total,
        "units_with_threats": len({threat["unit"] for threat in threats}),
        "rows": len(rows),
        "threats": len(threats),
        "precursors": sum(1 for row in rows if row["disposition"] == "precursor"),
        "chain_rows": sum(1 for row in rows if row["chain"]),
        "impact_chain_rate": round(sum(1 for row in rows if row["chain"]) / len(rows), 3) if rows else 0.0,
        "cross_unit_refs": sum(1 for row in rows for ref in row["chain"] if "::" in ref),
        "risk_total": round(sum(t["risk"] for t in threats), 2),
        "bands": {
            band: sum(1 for t in threats if (
                (band == "critical" and t["risk"] >= 9)
                or (band == "high" and 7 <= t["risk"] < 9)
                or (band == "medium" and 4 <= t["risk"] < 7)
                or (band == "low" and 0 < t["risk"] < 4)
                or (band == "none" and t["risk"] == 0)))
            for band in ("none", "low", "medium", "high", "critical")
        },
        "saturation_ge_9": sum(1 for t in threats if t["risk"] >= 9),
        "assumed_penalty_count": sum(
            1 for row in rows
            if ASSUMED_PENALTY.search(row["exploitability"]) or ASSUMED_PENALTY.search(row["impact"])),
        "victim_action_penalty_count": sum(
            1 for row in rows
            if VICTIM_PENALTY.search(row["exploitability"]) or VICTIM_PENALTY.search(row["impact"])),
        "fence_hits": len(fence),
        "gt": gt,
        "xss": {
            "produced": bool(xss_best),
            "risk": xss_best["risk"] if xss_best else 0.0,
            "vector": xss_row.get("risk_vector") if xss_row else None,
            "chain": (xss_best["chain"] or xss_row.get("chain")) if xss_best else [],
            "queue_rank": xss_best["queue_rank"] if xss_best else None,
            "unit": xss_best["unit"] if xss_best else None,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--data-root", type=pathlib.Path, default=pathlib.Path("/srv/data"))
    parser.add_argument("--api", default="http://127.0.0.1:8080")
    args = parser.parse_args()

    run = json.load(urllib.request.urlopen(
        f"{args.api}/projects/{args.project_id}/hunting/{args.run_id}", timeout=20))
    intake = list((run.get("stats") or {}).get("intake_order") or [])
    root = args.data_root / args.project_id / "hunting"
    pod_root = root / "test-executor-pod"

    families: dict[str, dict] = {}
    raw = audited = 0
    verdicts: dict[str, int] = {}
    reasons: dict[str, int] = {}
    false_positives: list[dict] = []
    weak: list[dict] = []
    for path in glob.glob(str(pod_root / "*" / "*.yaml")):
        if path.endswith(".resume.yaml") or path.endswith(".yaml.bak"):
            continue
        body = load(pathlib.Path(path))
        ev = body.get("evidence") or {}
        verdict = str(body.get("verdict") or "")
        reason = str(ev.get("terminal_reason") or "")
        interps = ev.get("interpretations") or []
        first = interps[0] if interps else {}
        note = str(first.get("note") or "")
        classification = str(first.get("classification") or "")
        family = os.path.basename(os.path.dirname(path)).split("__")[0]
        verdicts[verdict] = verdicts.get(verdict, 0) + 1
        reasons[reason] = reasons.get(reason, 0) + 1
        is_raw = verdict == "successful" and reason == "symptom-confirmed"

        # A pod may carry several interpretations: an early runner failure and a
        # later in-window confirmation. Audit every interpretation, not just the
        # first one. A genuine interpretation must not be a runner/triager
        # artefact, and it must make a positive claim.
        genuine = []
        for interp in interps:
            c = str(interp.get("classification") or "")
            n = str(interp.get("note") or "")
            low_c, low_n = c.lower(), n.lower()
            if any(marker in low_c for marker in FALSE):
                continue
            if "0 bytes received" in low_n and "symptom confirmed" not in low_n:
                continue
            if "unconfirmed" in low_n and "confirmed per" not in low_n:
                continue
            if not c.strip() and "confirm" not in low_n:
                continue
            genuine.append({"classification": c, "note": n})

        is_audited = is_raw and bool(genuine)
        if is_raw:
            raw += 1
        if is_audited:
            audited += 1
            # An unclassified positive note is a weaker attestation than a
            # classified one; record it so the report can qualify the count.
            if any(not g["classification"].strip() for g in genuine):
                weak.append({
                    "pod": os.path.basename(os.path.dirname(path)),
                    "note": genuine[-1]["note"][:240],
                })
        elif is_raw:
            false_positives.append({
                "pod": os.path.basename(os.path.dirname(path)),
                "classification": classification,
                "note": note[:240],
            })
        family_row = families.setdefault(family, {"raw": 0, "audited": 0, "failed": 0})
        if is_raw:
            family_row["raw"] += 1
        if is_audited:
            family_row["audited"] += 1
        else:
            family_row["failed"] += 1

    model = model_metrics(root / "threat_modeller", intake)
    out = {
        "pods": {
            "terminal": sum(1 for _ in glob.glob(str(pod_root / "*" / "*.yaml"))
                            if not _.endswith(".resume.yaml")),
            "raw_confirmed": raw,
            "audited_confirmed": audited,
            "false_positives": false_positives,
            "weak_attestations": weak,
            "verdicts": verdicts,
            "reasons": reasons,
            "families": families,
            "audited_rate": round(audited / max(1, raw), 3),
        },
        "model": model,
    }
    print(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
