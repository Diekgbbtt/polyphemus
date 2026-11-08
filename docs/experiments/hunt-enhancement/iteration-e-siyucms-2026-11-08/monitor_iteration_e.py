#!/usr/bin/env python3
"""Poll the iteration E trial: spend, hunting, recon, units, and the pool.

Read-only. One JSON line per poll to `--out`; a compact line to stdout.
The trial's own token budget is the stopping authority; this monitor never
stops the run. It is the live feed for the browser and crawl evidence that
the final assessment reads from disk and Langfuse.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import re
import subprocess
import time
import urllib.error
import urllib.request

import yaml

TERMINAL = ("complete", "stopped", "failed", "interrupted")


def api(base: str, path: str) -> object | None:
    try:
        with urllib.request.urlopen(f"{base}{path}", timeout=20) as response:
            return json.load(response)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return None


def newest_project(api_base: str, data_root: pathlib.Path, name: str) -> str | None:
    listing = api(api_base, "/projects")
    rows = listing if isinstance(listing, list) else (
        listing.get("projects") if isinstance(listing, dict) else None
    )
    if isinstance(rows, list):
        for row in rows:
            if isinstance(row, dict) and row.get("name") == name:
                return str(row.get("id") or row.get("project_id") or "")
    candidates = [
        path for path in data_root.iterdir()
        if path.is_dir() and (path / "hunting").exists()
    ] if data_root.exists() else []
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime).name


def latest_run(api_base: str, project_id: str, kind: str) -> dict:
    rows = api(api_base, f"/projects/{project_id}/{kind}")
    if isinstance(rows, dict):
        rows = rows.get(kind) or rows.get("runs") or rows.get("items")
    if not isinstance(rows, list) or not rows:
        return {}
    return rows[-1] if isinstance(rows[-1], dict) else {}


def run_detail(api_base: str, project_id: str, kind: str, run_id: str) -> dict:
    if not run_id:
        return {}
    body = api(api_base, f"/projects/{project_id}/{kind}/{run_id}")
    return body if isinstance(body, dict) else {}


def unit_counts(data_root: pathlib.Path, project_id: str) -> dict:
    base = data_root / project_id / "hunting" / "threat_modeller"
    counts = {"units": 0, "threats": 0, "impact_rows": 0}
    for stage in ("produced", "consumed", "abandoned"):
        for path in (base / stage).glob("*/*.yaml"):
            if path.name.startswith("threat-"):
                continue
            counts["units"] += 1
            try:
                model = yaml.safe_load(path.read_text(encoding="utf-8"))
            except (OSError, yaml.YAMLError):
                continue
            if not isinstance(model, dict):
                continue
            counts["impact_rows"] += len(model.get("impact_assessment") or [])
            counts["threats"] += len(model.get("threats") or [])
    return counts


def crawl_manifests(data_root: pathlib.Path, project_id: str) -> list[str]:
    base = data_root / project_id
    found = []
    for path in base.glob("**/manifest.json"):
        text = str(path)
        if "crawl" in text or "steel" in text:
            found.append(text)
    return found[-5:]


def pool_events(compose_project: str | None) -> dict:
    if not compose_project:
        return {}
    result = subprocess.run(
        ["docker", "compose", "-p", compose_project, "logs", "--tail", "400", "kali"],
        capture_output=True, text=True, check=False, timeout=20,
    )
    text = (result.stdout or "") + (result.stderr or "")
    discovered = re.findall(r"pool\.discovered[^\n]*", text)
    browser = re.findall(r"browser MCP[^\n]*", text)
    sessions = subprocess.run(
        ["docker", "compose", "-p", compose_project, "exec", "-T", "kali",
         "sh", "-lc", "ls -1 /var/lib/steel/sessions 2>/dev/null | wc -l"],
        capture_output=True, text=True, check=False, timeout=20,
    )
    return {
        "pool": discovered[-3:],
        "browser_mcp": browser[-3:],
        "session_files": (sessions.stdout or "").strip(),
    }


def trial_terminal(runs_root: pathlib.Path, target: str) -> str | None:
    for path in sorted((runs_root / target).glob("*/trial.yaml"), key=lambda p: p.stat().st_mtime):
        try:
            record = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError):
            continue
        if isinstance(record, dict):
            terminal = record.get("terminal")
            if isinstance(terminal, str):
                return terminal
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", default="http://127.0.0.1:8080")
    parser.add_argument("--project-name", required=True)
    parser.add_argument("--data-root", type=pathlib.Path, required=True)
    parser.add_argument("--runs-root", type=pathlib.Path, required=True)
    parser.add_argument("--compose-project", default=None)
    parser.add_argument("--poll-s", type=int, default=120)
    parser.add_argument("--out", type=pathlib.Path, default=None)
    args = parser.parse_args()
    out = args.out or args.runs_root / "monitor.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)

    idle_polls = 0
    while True:
        now = dt.datetime.now(dt.timezone.utc).isoformat()
        project_id = newest_project(args.api, args.data_root, args.project_name)
        record: dict = {"ts": now, "project_id": project_id}
        if project_id:
            usage = api(args.api, f"/projects/{project_id}/usage")
            if isinstance(usage, dict):
                record["capped_tokens"] = usage.get("capped_tokens")
                record["total_tokens"] = usage.get("total_tokens")
            hunting = latest_run(args.api, project_id, "hunting")
            hunt = run_detail(args.api, project_id, "hunting", str(hunting.get("hunting_run_id") or hunting.get("run_id") or ""))
            record["hunting_status"] = hunt.get("status") or hunting.get("status")
            record["risk_total"] = hunt.get("risk_total")
            recon = latest_run(args.api, project_id, "recon")
            recon_detail = run_detail(args.api, project_id, "recon", str(recon.get("run_id") or ""))
            record["recon_status"] = recon_detail.get("status") or recon.get("status")
            jobs = recon_detail.get("per_job") or recon_detail.get("jobs") or {}
            record["recon_jobs"] = jobs
            stats = recon_detail.get("stats") or {}
            record["steel_crawl"] = {
                key: value for key, value in (jobs.items() if isinstance(jobs, dict) else [])
                if "steel" in str(key) or "crawl" in str(key)
            }
            record["recon_stats"] = stats
            record.update(unit_counts(args.data_root, project_id))
            record["crawl_manifests"] = crawl_manifests(args.data_root, project_id)
            record["pool"] = pool_events(args.compose_project)
            if record.get("hunting_status") in TERMINAL or record.get("recon_status") in TERMINAL:
                idle_polls += 1
            else:
                idle_polls = 0
        terminal = trial_terminal(args.runs_root, "siyucms-web")
        record["trial_terminal"] = terminal
        with out.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        print(json.dumps(record, ensure_ascii=False)[:600], flush=True)
        if terminal or idle_polls >= 6:
            return 0
        time.sleep(args.poll_s)


if __name__ == "__main__":
    raise SystemExit(main())
