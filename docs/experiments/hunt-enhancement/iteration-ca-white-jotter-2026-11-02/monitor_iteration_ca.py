#!/usr/bin/env python3
"""Poll the iteration C.a run: spend, risk, v5 assessment rows, chains, fence.

Read-only. One JSON line per poll to --out and one compact line to stdout.
Runs inside the agent container so the app data root is the live store.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import re
import time
import urllib.request

import yaml

TERMINAL = ("complete", "stopped", "failed", "interrupted")
FENCE_PATTERNS = {
    "rate_limit": re.compile(
        r"rate[ -]?limit|throttl|request quota|volumetric defence", re.I),
    "plaintext_channel": re.compile(
        r"plain[ -]?text (?:channel|communication|transport|connection)|"
        r"clear[ -]?text|non[- ]?tls|no tls\b|without tls\b", re.I),
    "preliminary_step": re.compile(
        r"phish|social engineer|malicious attachment|browser extension|"
        r"compromised browser|drive[- ]?by", re.I),
}
FENCE_FIELDS = (
    "statement", "impact_description", "exploitability_description",
    "capability", "characterisation", "damage",
)


def api(base: str, path: str) -> dict:
    with urllib.request.urlopen(f"{base}{path}", timeout=20) as response:
        return json.load(response)


def load(path: pathlib.Path) -> dict:
    try:
        body = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return {}
    return body if isinstance(body, dict) else {}


def unit_models(root: pathlib.Path):
    for stage in ("produced", "consumed", "abandoned"):
        for path in (root / stage).glob("*/*.yaml"):
            if path.name.startswith("threat-"):
                continue
            yield path


def fence_hits(model: dict) -> list[dict]:
    hits: list[dict] = []

    def walk(value, path: str) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                walk(child, f"{path}.{key}" if path else str(key))
        elif isinstance(value, list):
            for index, child in enumerate(value):
                walk(child, f"{path}[{index}]")
        elif isinstance(value, str):
            for name, pattern in FENCE_PATTERNS.items():
                if pattern.search(value):
                    hits.append({
                        "kind": name, "path": path, "text": value[:240]})

    walk(model, "")
    return hits


def model_summary(model: dict) -> dict:
    rows = [row for row in (model.get("impact_assessment") or [])
            if isinstance(row, dict)]
    threats = [row for row in (model.get("threats") or [])
               if isinstance(row, dict)]
    bands: dict[str, int] = {}
    risks: list[float] = []
    chained = 0
    cross_unit = 0
    depth: dict[int, int] = {}
    for row in rows:
        risk = row.get("risk")
        if isinstance(risk, (int, float)):
            risks.append(float(risk))
            if risk >= 9.0:
                bands["critical"] = bands.get("critical", 0) + 1
            elif risk >= 7.0:
                bands["high"] = bands.get("high", 0) + 1
            elif risk >= 4.0:
                bands["medium"] = bands.get("medium", 0) + 1
            elif risk > 0:
                bands["low"] = bands.get("low", 0) + 1
        path = [str(p) for p in (row.get("capability_path") or [])]
        if path:
            chained += 1
            depth[len(path)] = depth.get(len(path), 0) + 1
            cross_unit += sum(1 for p in path if "::" in p)
    threat_risks = [
        float(t.get("risk")) for t in threats
        if isinstance(t.get("risk"), (int, float))]
    return {
        "state": str(model.get("state") or ""),
        "rows": len(rows),
        "threat_rows": sum(
            1 for r in rows if r.get("disposition") == "threat"),
        "precursor_rows": sum(
            1 for r in rows if r.get("disposition") == "precursor"),
        "threats": len(threats),
        "assessed_rows": len(risks),
        "chain_rows": chained,
        "cross_unit_refs": cross_unit,
        "chain_depth": depth,
        "risk_total": round(sum(threat_risks), 2),
        "bands": bands,
    }


def snapshot(root: pathlib.Path) -> dict:
    totals = {
        "units": 0, "rows": 0, "threat_rows": 0, "precursor_rows": 0,
        "threats": 0, "assessed_rows": 0, "chain_rows": 0,
        "cross_unit_refs": 0,
    }
    depth: dict[int, int] = {}
    bands: dict[str, int] = {}
    fence: list[dict] = []
    states: dict[str, int] = {}
    models = 0
    for path in unit_models(root):
        model = load(path)
        if not model:
            continue
        models += 1
        summary = model_summary(model)
        totals["units"] += 1
        for key in ("rows", "threat_rows", "precursor_rows", "threats",
                    "assessed_rows", "chain_rows", "cross_unit_refs"):
            totals[key] += summary[key]
        for k, v in summary["bands"].items():
            bands[k] = bands.get(k, 0) + v
        for k, v in summary["chain_depth"].items():
            depth[str(k)] = depth.get(str(k), 0) + v
        states[summary["state"]] = states.get(summary["state"], 0) + 1
        for hit in fence_hits(model):
            fence.append({"unit": path.parent.name, **hit})
    risk_total = round(sum(
        float(t.get("risk"))
        for path in unit_models(root)
        for t in (load(path).get("threats") or [])
        if isinstance(t, dict) and isinstance(t.get("risk"), (int, float))
    ), 2)
    return {
        **totals,
        "models": models,
        "states": states,
        "bands": bands,
        "chain_depth": depth,
        "risk_total": risk_total,
        "fence_hits": len(fence),
        "fence": fence[:8],
        "test_specs": len(list((root.parent / "hunter" / "test-specs").glob("*"))),
        "pods": len(list((root.parent / "test-executor-pod").glob("*"))),
        "pod_exports": len(list((root.parent / "test-executor-pod").glob("*/*.yaml"))),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", default="http://127.0.0.1:8080")
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--run-id", default=None, help="the hunting run to poll")
    parser.add_argument("--data-root", type=pathlib.Path, default=pathlib.Path("/srv/data"))
    parser.add_argument("--out", type=pathlib.Path, required=True)
    parser.add_argument("--interval", type=int, default=120)
    parser.add_argument("--token-budget", type=int, default=7_000_000)
    parser.add_argument("--max-minutes", type=int, default=1440)
    args = parser.parse_args()

    started = time.time()
    while True:
        ts = dt.datetime.now(dt.timezone.utc).isoformat()
        try:
            usage = api(args.api, f"/projects/{args.project_id}/usage")
        except Exception as exc:  # noqa: BLE001
            usage = {"error": str(exc)}
        try:
            if args.run_id:
                run = api(
                    args.api,
                    f"/projects/{args.project_id}/hunting/{args.run_id}")
            else:
                runs = api(args.api, f"/projects/{args.project_id}/hunting")
                run = (runs.get("runs") or [None])[0] if isinstance(runs, dict) else None
        except Exception as exc:  # noqa: BLE001
            run = {"error": str(exc)}
        arts = snapshot(args.data_root / args.project_id / "hunting" / "threat_modeller")
        record = {
            "ts": ts,
            "capped_tokens": usage.get("capped_tokens"),
            "calls": usage.get("calls"),
            "by_agent": {
                name: {"capped": body.get("capped_tokens"),
                       "calls": body.get("calls")}
                for name, body in (usage.get("by_agent") or {}).items()
            },
            "run": run,
            "artefacts": arts,
        }
        with args.out.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, default=str) + "\n")
        print(
            f"{ts} tokens={record['capped_tokens']} calls={record['calls']} "
            f"run={(run or {}).get('status') if isinstance(run, dict) else run} "
            f"units={arts['units']} rows={arts['rows']} threats={arts['threats']} "
            f"chains={arts['chain_rows']} fence={arts['fence_hits']}",
            flush=True,
        )
        if record["capped_tokens"] and record["capped_tokens"] >= args.token_budget:
            print("token cap reached", flush=True)
            return 0
        if isinstance(run, dict) and run.get("status") in TERMINAL:
            print(f"run terminal: {run.get('status')}", flush=True)
            return 0
        if (time.time() - started) >= args.max_minutes * 60:
            print("monitor max minutes", flush=True)
            return 0
        time.sleep(args.interval)


if __name__ == "__main__":
    raise SystemExit(main())
