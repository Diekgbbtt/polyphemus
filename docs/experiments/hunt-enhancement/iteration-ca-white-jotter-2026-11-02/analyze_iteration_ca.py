#!/usr/bin/env python3
"""Compute the iteration C.a metrics from the live v5 store.

Read-only. Run inside the agent container:

    python /tmp/analyze_iteration_ca.py \
        --project-id <id> --data-root /srv/data \
        --run-id <hunting-run-id> --api http://127.0.0.1:8080

It reads the unit models and threat files, reconstructs the global threat queue
from the run's intake order, and maps the seven ground-truth vulnerabilities to
the stored rows. It prints one JSON object; the report renders the tables.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import urllib.request

import yaml

GT = (
    {
        "id": "white-jotter-001",
        "label": "default credential",
        "unit_hints": ("sign-in", "AuthenticationMechanism"),
        "keywords": ("default credential", "weak credential", "cwe-1392", "seeded credential"),
    },
    {
        "id": "white-jotter-002",
        "label": "function-level authorization bypass",
        "unit_hints": ("ReverseProxy",),
        "keywords": ("function-level authorization", "bfla", "authorization bypass", "path-canonicalisation"),
    },
    {
        "id": "white-jotter-003",
        "label": "stored XSS",
        "unit_hints": ("article-management",),
        "keywords": ("xss", "cross-site scripting", "innerhtml"),
    },
    {
        "id": "white-jotter-004",
        "label": "JNDI injection",
        "unit_hints": ("AuthorizationSystem", "user-administration"),
        "keywords": ("jndi", "log4j", "log sink", "log4shell"),
    },
    {
        "id": "white-jotter-005",
        "label": "SQL injection",
        "unit_hints": ("RESTApi", "library-catalog"),
        "keywords": ("sql injection", "sqli", "concatenated search"),
    },
    {
        "id": "white-jotter-006",
        "label": "path traversal file read",
        "unit_hints": ("media-asset-serving", "book-cover", "library-catalog", "ReverseProxy"),
        "keywords": ("path traversal", "directory traversal", "arbitrary file", "cover.png", "double-decoded", "decode-twice", "lfi", "rfi"),
    },
    {
        "id": "white-jotter-007",
        "label": "mass assignment",
        "unit_hints": ("RESTApi", "register"),
        "keywords": ("mass assignment", "role association"),
    },
)

FENCE_PATTERNS = {
    "rate_limit": re.compile(r"rate[ -]?limit|throttl|request quota|volumetric defence", re.I),
    "plaintext_channel": re.compile(
        r"plain[ -]?text (?:channel|communication|transport|connection)|"
        r"clear[ -]?text|non[- ]?tls|no tls\b|without tls\b", re.I),
    "preliminary_step": re.compile(
        r"phish|social engineer|malicious attachment|browser extension|"
        r"compromised browser|drive[- ]?by", re.I),
}
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


def load(path: pathlib.Path) -> dict:
    try:
        body = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return {}
    return body if isinstance(body, dict) else {}


def models(root: pathlib.Path):
    seen: set[str] = set()
    for stage in ("produced", "consumed", "abandoned"):
        for path in (root / stage).glob("*/*.yaml"):
            if path.name.startswith("threat-"):
                continue
            key = path.parent.name
            if key in seen:
                continue
            seen.add(key)
            yield path


def api(base: str, path: str) -> dict:
    with urllib.request.urlopen(f"{base}{path}", timeout=20) as response:
        return json.load(response)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--data-root", type=pathlib.Path, default=pathlib.Path("/srv/data"))
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--api", default="http://127.0.0.1:8080")
    args = parser.parse_args()

    root = args.data_root / args.project_id / "hunting"
    unit_models = root / "threat_modeller"
    intake = []
    if args.run_id:
        try:
            run = api(args.api, f"/projects/{args.project_id}/hunting/{args.run_id}")
            intake = list((run.get("stats") or {}).get("intake_order") or [])
        except Exception as exc:  # noqa: BLE001
            print(json.dumps({"error": f"run read: {exc}"}))
            return 1

    rows: list[dict] = []
    threats: list[dict] = []
    fence: list[dict] = []
    models_count = 0
    for path in models(unit_models):
        model = load(path)
        if not model:
            continue
        models_count += 1
        unit = str(model.get("unit_id") or path.parent.name)
        for row in model.get("impact_assessment") or []:
            if not isinstance(row, dict):
                continue
            rows.append({
                "unit": unit,
                "id": row.get("id"),
                "disposition": row.get("disposition"),
                "risk": float(row.get("risk") or 0.0),
                "chain": list(row.get("capability_path") or []),
                "class": str(row.get("capability") or ""),
                "impact": str(row.get("impact_description") or ""),
                "exploitability": str(row.get("exploitability_description") or ""),
                "vector": row.get("risk_vector"),
            })
        for threat in model.get("threats") or []:
            if not isinstance(threat, dict):
                continue
            threats.append({
                "unit": unit,
                "unit_name": path.parent.name,
                "id": threat.get("id"),
                "risk": float(threat.get("risk") or 0.0),
                "class": str(threat.get("canonical_class") or ""),
                "ref": threat.get("impact_ref"),
                "chain": list(threat.get("enabling_precursors") or []),
            })
        for row in rows:
            if row["unit"] != unit:
                continue
            for name, pattern in FENCE_PATTERNS.items():
                for field in ("class", "impact", "exploitability"):
                    if pattern.search(row[field]):
                        fence.append({"unit": unit, "row": row["id"], "kind": name, "field": field})

    row_map = {(row["unit"], row["id"]): row for row in rows}
    for threat in threats:
        row = row_map.get((threat["unit"], threat["ref"])) or {}
        threat["row_class"] = str(row.get("class") or "")
        threat["impact"] = str(row.get("impact") or "")
        threat["row_chain"] = list(row.get("chain") or [])

    # The global queue: threat risk desc, intake position asc, threat rank asc.
    position = {unit: index for index, unit in enumerate(intake)}
    for threat in threats:
        threat["intake_position"] = position.get(threat["unit"], 10_000)
        threat["rank"] = int(str(threat["id"]).split("-")[-1]) if str(threat["id"]).startswith("threat-") else 10_000
    queue = sorted(threats, key=lambda t: (-t["risk"], t["intake_position"], t["rank"], str(t["id"])))
    for index, threat in enumerate(queue, start=1):
        threat["queue_rank"] = index

    spec_root = root / "hunter" / "test-specs"
    spec_names = {path.name for path in spec_root.iterdir()} if spec_root.is_dir() else set()

    def band_of(risk: float) -> str:
        return ("critical" if risk >= 9 else "high" if risk >= 7
                else "medium" if risk >= 4 else "low" if risk > 0 else "none")

    def matches(gt: dict, threat: dict) -> bool:
        hay = f"{threat['class']} {threat.get('row_class', '')} {threat.get('impact', '')}".lower()
        return any(keyword in hay for keyword in gt["keywords"])

    gt_result = {}
    for gt in GT:
        hits = [threat for threat in queue if matches(gt, threat)]
        best = max(hits, key=lambda threat: threat["risk"]) if hits else None
        gt_result[gt["id"]] = {
            "label": gt["label"],
            "produced": bool(best),
            "risk": best["risk"] if best else 0.0,
            "band": band_of(best["risk"]) if best else "none",
            "unit": best["unit"] if best else None,
            "chained": bool(best and (best["chain"] or best["row_chain"])) if best else False,
            "queue_rank": best["queue_rank"] if best else None,
            "dispatchable": bool(best and best["risk"] > 0),
            "dispatched": bool(best and any(
                name.startswith(f"{best['unit_name']}__{best['id']}")
                for name in spec_names)),
        }

    xss_hits = [
        threat for threat in queue
        if "xss" in threat["class"].lower()
        or "cross-site scripting" in threat["class"].lower()
    ]
    xss_best = max(xss_hits, key=lambda threat: threat["risk"]) if xss_hits else None
    xss_row = row_map.get((xss_best["unit"], xss_best["ref"])) if xss_best else {}
    xss = {
        "produced": bool(xss_best),
        "risk": xss_best["risk"] if xss_best else 0.0,
        "vector": xss_row.get("vector") if xss_row else None,
        "chain": (xss_best["chain"] or xss_row.get("chain")) if xss_best else [],
        "queue_rank": xss_best["queue_rank"] if xss_best else None,
        "unit": xss_best["unit"] if xss_best else None,
        "dispatchable": bool(xss_best and xss_best["risk"] > 0),
        "dispatched": bool(xss_best and any(
            name.startswith(f"{xss_best['unit_name']}__{xss_best['id']}")
            for name in spec_names)),
    }

    assumed = [
        {"unit": row["unit"], "row": row["id"]} for row in rows
        if ASSUMED_PENALTY.search(row["exploitability"]) or ASSUMED_PENALTY.search(row["impact"])
    ]
    victim = [
        {"unit": row["unit"], "row": row["id"]} for row in rows
        if VICTIM_PENALTY.search(row["exploitability"]) or VICTIM_PENALTY.search(row["impact"])
    ]
    chain_rows = [row for row in rows if row["chain"]]
    cross_unit = sum(
        1 for row in rows for ref in row["chain"] if "::" in ref)
    bands = {"none": 0, "low": 0, "medium": 0, "high": 0, "critical": 0}
    for threat in threats:
        risk = threat["risk"]
        band = "critical" if risk >= 9 else "high" if risk >= 7 else "medium" if risk >= 4 else "low" if risk > 0 else "none"
        bands[band] += 1

    out = {
        "models": models_count,
        "rows": len(rows),
        "threats": len(threats),
        "precursors": sum(1 for row in rows if row["disposition"] == "precursor"),
        "chain_rows": len(chain_rows),
        "impact_chain_rate": round(len(chain_rows) / len(rows), 3) if rows else 0.0,
        "cross_unit_refs": cross_unit,
        "risk_total": round(sum(t["risk"] for t in threats), 2),
        "bands": bands,
        "saturation_ge_9": sum(1 for t in threats if t["risk"] >= 9.0),
        "assumed_penalty_count": len(assumed),
        "assumed_penalty": assumed[:10],
        "victim_action_penalty_count": len(victim),
        "victim_action_penalty": victim[:10],
        "fence_hits": len(fence),
        "fence": fence[:10],
        "gt": gt_result,
        "xss": xss,
        "queue_top": [
            {"rank": t["queue_rank"], "unit": t["unit"], "risk": t["risk"], "class": t["class"]}
            for t in queue[:15]
        ],
    }
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
