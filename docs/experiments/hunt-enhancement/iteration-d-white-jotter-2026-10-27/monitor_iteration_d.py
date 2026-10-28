#!/usr/bin/env python3
"""Poll the iteration D hunting run: spend, risk, artefacts, fence compliance.

Read-only. One JSON line per poll to MONITOR_OUT, and one compact line to
stdout. The run is bounded by the token cap, so this monitor stops itself when
the usage read reaches the cap, the run row reports a terminal status, or
`--max-minutes` elapses. The risk halt is recorded but does NOT stop the
monitor: the batched phase barrier lifts at the halt and the hunt phase runs
afterwards, so the spend can still reach the cap.

The fence check is observational: a match is recorded with its unit and field,
never repaired. It looks for the three forbidden characterisations the project
scope names: rate-limit defence properties, the plain-text nature of a channel,
and a direction that needs a preliminary step (phishing and friends) to reach
full client-side code control.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import re
import sys
import time
import urllib.error
import urllib.request

import yaml

CIA = ("confidentiality", "integrity", "availability")
TERMINAL = ("complete", "stopped", "failed", "interrupted")
FENCE_PATTERNS = {
    "rate_limit": re.compile(
        r"rate[ -]?limit|throttl|request quota|volumetric defence", re.I
    ),
    "plaintext_channel": re.compile(
        r"plain[ -]?text (?:channel|communication|transport|connection)|"
        r"clear[ -]?text|non[- ]?tls|no tls\b|without tls\b", re.I
    ),
    "preliminary_step": re.compile(
        r"phish|social engineer|malicious attachment|browser extension|"
        r"compromised browser|drive[- ]?by", re.I
    ),
}
FENCE_FIELDS = (
    "statement", "damage", "capability", "characterisation", "rationale",
)


def api(base: str, path: str) -> dict:
    with urllib.request.urlopen(f"{base}{path}", timeout=15) as response:
        return json.load(response)


def load(path: pathlib.Path) -> dict:
    try:
        body = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return {}
    return body if isinstance(body, dict) else {}


def find_run(base: str, project_id: str) -> str | None:
    """The live hunting run id: the app-state view is the authoritative list.

    `/runs?status=running` only reports rows the liveness sweep still holds, so
    a running hunting row can be absent there while `app-state` has it.
    """
    try:
        state = api(base, f"/app-state?project_id={project_id}")
        for project in state.get("projects", []):
            for run in project.get("hunting", []):
                if run.get("status") == "running":
                    return str(run.get("hunting_run_id") or "") or None
    except (urllib.error.URLError, urllib.error.HTTPError, ValueError):
        pass
    for run in api(base, "/runs?status=running").get("runs", []):
        if run.get("project_id") == project_id and run.get("kind") == "hunting":
            return str(run.get("id") or "") or None
    return None


def unit_models(root: pathlib.Path) -> list[pathlib.Path]:
    models: list[pathlib.Path] = []
    for stage in ("produced", "consumed", "abandoned"):
        for directory in sorted((root / stage).glob("*")):
            if not directory.is_dir():
                continue
            for path in directory.glob("*.yaml"):
                if not path.name.startswith("threat-"):
                    models.append(path)
    return models


def _walk(value, field: str = ""):
    if isinstance(value, dict):
        for key, item in value.items():
            yield from _walk(item, key)
    elif isinstance(value, list):
        for item in value:
            yield from _walk(item, field)
    elif isinstance(value, str):
        yield field, value


def fence_hits(model: dict) -> list[dict]:
    hits: list[dict] = []
    for field, text in _walk(model):
        if field not in FENCE_FIELDS:
            continue
        for name, pattern in FENCE_PATTERNS.items():
            if pattern.search(text):
                hits.append({
                    "term": name,
                    "field": field,
                    "text": text[:200],
                })
    return hits


def model_summary(model: dict) -> dict:
    threats = {
        str(row.get("impact_ref") or ""): (row.get("impact") or {})
        for row in (model.get("threats") or [])
        if isinstance(row, dict) and row.get("impact_ref")
    }
    rows = [row for row in (model.get("impact_assessment") or [])
            if isinstance(row, dict)]
    green = 0
    threat_rows = 0
    precursor_rows = 0
    capability_rows = 0
    chain_pairs = 0
    for row in rows:
        impact = threats.get(str(row.get("id") or "")) or {}
        if any(str(impact.get(key) or "none") != "none" for key in CIA):
            green += 1
        disposition = str(row.get("disposition") or "")
        if disposition == "threat":
            threat_rows += 1
        elif disposition == "precursor":
            precursor_rows += 1
        if str(row.get("capability") or ""):
            capability_rows += 1
    for threat in model.get("threats") or []:
        if isinstance(threat, dict):
            chain_pairs += len(threat.get("enabling_precursors") or [])
    return {
        "state": str(model.get("state") or ""),
        "rows": len(rows),
        "green": green,
        "threat_rows": threat_rows,
        "precursor_rows": precursor_rows,
        "capability_rows": capability_rows,
        "threats": len(threats),
        "chain_pairs": chain_pairs,
    }


def artefact_snapshot(root: pathlib.Path) -> dict:
    models = unit_models(root)
    totals = {
        "units": 0, "rows": 0, "green": 0, "threat_rows": 0,
        "precursor_rows": 0, "capability_rows": 0, "threats": 0,
        "chain_pairs": 0,
    }
    fence: list[dict] = []
    states: dict[str, int] = {}
    for path in models:
        model = load(path)
        if not model:
            continue
        summary = model_summary(model)
        totals["units"] += 1
        for key in ("rows", "green", "threat_rows", "precursor_rows",
                    "capability_rows", "threats", "chain_pairs"):
            totals[key] += summary[key]
        states[summary["state"]] = states.get(summary["state"], 0) + 1
        for hit in fence_hits(model):
            fence.append({"unit": path.parent.name, **hit})
    promoted = 0
    demoted = 0
    for stage in ("produced", "consumed", "abandoned"):
        for path in (root / stage).glob("*/threat-*.yaml"):
            body = load(path)
            risk = int(((body.get("threat") or {}).get("risk")) or 0)
            if risk >= 4:
                promoted += 1
            else:
                demoted += 1
    return {
        **totals,
        "states": states,
        "promoted": promoted,
        "demoted": demoted,
        "test_specs": len(list((root.parent / "hunter" / "test-specs").glob("*"))),
        "pods": len(list((root.parent / "test-executor-pod").glob("*"))),
        "fence_hits": len(fence),
        "fence": fence[:8],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", default="http://127.0.0.1:8080")
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--run-id", default=None,
                        help="pin the hunting run id; otherwise discover it")
    parser.add_argument("--data-root", type=pathlib.Path,
                        default=pathlib.Path(
                            "/opt/polymerhus-dev/eval/instances/data/eval-server-1"))
    parser.add_argument("--out", type=pathlib.Path, required=True)
    parser.add_argument("--interval", type=int, default=120)
    parser.add_argument("--token-budget", type=int, default=7000000)
    parser.add_argument("--risk-threshold", type=int, default=180)
    parser.add_argument("--max-minutes", type=int, default=720)
    args = parser.parse_args()

    root = args.data_root / args.project_id / "hunting" / "threat_modeller"
    args.out.parent.mkdir(parents=True, exist_ok=True)
    started = dt.datetime.now(dt.timezone.utc)
    run_id: str | None = args.run_id
    while True:
        now = dt.datetime.now(dt.timezone.utc)
        elapsed = (now - started).total_seconds()
        usage = api(args.api, f"/projects/{args.project_id}/usage")
        if run_id is None:
            run_id = find_run(args.api, args.project_id)
        status: dict = {}
        if run_id:
            try:
                status = api(
                    args.api,
                    f"/projects/{args.project_id}/hunting/{run_id}",
                )
            except urllib.error.HTTPError:
                status = {}
        stats = status.get("stats") or {}
        agents = usage.get("by_agent") or {}
        snapshot = artefact_snapshot(root)
        record = {
            "at": now.isoformat(),
            "elapsed_s": int(elapsed),
            "run_id": run_id,
            "status": status.get("status"),
            "risk_total": stats.get("risk_total"),
            "risk_threshold": args.risk_threshold,
            "halt": stats.get("halt"),
            "intake_position": stats.get("intake_position"),
            "intake_count": stats.get("intake_count"),
            "capped_tokens": usage.get("capped_tokens"),
            "total_tokens": usage.get("total_tokens"),
            "calls": usage.get("calls"),
            "modeller_calls": (agents.get("hunting_threat_modeller") or {}).get("calls"),
            "hunter_calls": (agents.get("hunting_hunter") or {}).get("calls"),
            "pod_calls": (agents.get("pod_runner") or {}).get("calls"),
            "token_budget": args.token_budget,
            **snapshot,
        }
        with args.out.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, default=str) + "\n")
        print(
            f"{record['at']} run={record['status']} "
            f"risk={record['risk_total']}/{args.risk_threshold} "
            f"tokens={record['capped_tokens']}/{args.token_budget} "
            f"units={record['units']} rows={record['rows']} "
            f"threat={record['threat_rows']} precursor={record['precursor_rows']} "
            f"hunter_calls={record['hunter_calls']} specs={record['test_specs']} "
            f"fence={record['fence_hits']}",
            flush=True,
        )
        terminal = record["status"] in TERMINAL
        capped = (record["capped_tokens"] or 0) >= args.token_budget
        if terminal or capped or elapsed >= args.max_minutes * 60:
            break
        time.sleep(args.interval)
    return 0


if __name__ == "__main__":
    sys.exit(main())
