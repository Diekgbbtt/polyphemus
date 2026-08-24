#!/usr/bin/env python3
"""ph.py - the light eval harness's polymerhus API client.

A thin subcommand client over the polymerhus REST surface, encoding the
payloads and polling semantics so the eval agent never guesses API shapes.
Stdlib only (urllib); the API base is PH_API (default http://localhost:8000).

Usage:
  ph.py project create <name>
  ph.py settings put <project> --target-seed URL [--operator-kb FILE]
                               [--toggle key=value ...]
  ph.py bootstrap <project> [--operator-kb FILE]
  ph.py recon launch <project> [--jobs a,b] [--no-analysis]
  ph.py recon poll <project> <run_id> [--timeout-s S] [--interval-s S]
  ph.py hunting launch <project>
  ph.py hunting poll <project> <hunting_run_id> [--timeout-s S] [--interval-s S]
  ph.py graph get <project> [--out FILE]

Terminal statuses: recon runs end in {complete, failed}; hunting runs end in
{complete, stopped, failed, interrupted}. Polling exits 0 only on a terminal
status and prints the run summary (recon: per-job statuses, the liveness gate
input; hunting: the status row).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

API_BASE = os.environ.get("PH_API", "http://localhost:8000").rstrip("/")

RECON_TERMINAL = {"complete", "failed"}
HUNTING_TERMINAL = {"complete", "stopped", "failed", "interrupted"}


def api(method: str, path: str, body: dict | None = None) -> dict:
    url = f"{API_BASE}{path}"
    data = None
    headers = {"Accept": "application/json"}
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = resp.read()
            return json.loads(payload) if payload else {}
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = json.loads(exc.read())["detail"]
        except Exception:  # noqa: BLE001 - best-effort detail extraction
            pass
        sys.exit(f"ph.py: HTTP {exc.code} {method} {path}: {detail or exc.reason}")
    except urllib.error.URLError as exc:
        sys.exit(f"ph.py: cannot reach {API_BASE}: {exc.reason}")


def _read_text(path: str | None) -> str | None:
    if path is None:
        return None
    with open(path) as fh:
        return fh.read()


def _parse_toggle(raw: str) -> tuple[str, object]:
    key, _, value = raw.partition("=")
    lowered = value.lower()
    if lowered in ("true", "false"):
        return key, lowered == "true"
    try:
        return key, int(value)
    except ValueError:
        return key, value


def cmd_project_create(args: argparse.Namespace) -> int:
    resp = api("POST", "/projects", {"name": args.name})
    print(resp["project_id"])
    return 0


def cmd_settings_put(args: argparse.Namespace) -> int:
    recon: dict = {}
    if args.target_seed:
        recon["target_seed"] = args.target_seed
    kb = _read_text(args.operator_kb)
    if kb is not None:
        recon["operator_kb"] = kb
    for raw in args.toggle or []:
        key, value = _parse_toggle(raw)
        recon[key] = value
    api("PUT", f"/projects/{args.project}/settings", {"recon": recon})
    print("ok")
    return 0


def cmd_bootstrap(args: argparse.Namespace) -> int:
    kb = _read_text(args.operator_kb)
    body = {"operator_kb": kb} if kb is not None else {"operator_kb": None}
    resp = api("POST", f"/projects/{args.project}/bootstrap", body)
    print(json.dumps(resp, indent=2))
    return 0


def cmd_recon_launch(args: argparse.Namespace) -> int:
    body: dict = {"with_analysis": not args.no_analysis}
    if args.jobs:
        body["jobs"] = [j.strip() for j in args.jobs.split(",") if j.strip()]
    resp = api("POST", f"/projects/{args.project}/recon", body)
    print(resp["run_id"])
    return 0


def _summarize_jobs(run: dict) -> str:
    per_job = run.get("per_job") or []
    if not per_job:
        return "(no job rows yet)"
    parts = []
    for job in per_job:
        stats = job.get("stats") or {}
        n = sum(1 for v in stats.values() if isinstance(v, (int, float)) and v)
        parts.append(f"{job.get('job')}={job.get('status')}{f'[{n}]' if n else ''}")
    return " ".join(parts)


def cmd_recon_poll(args: argparse.Namespace) -> int:
    deadline = time.time() + args.timeout_s
    while True:
        run = api("GET", f"/projects/{args.project}/recon/{args.run}")
        status = run.get("status")
        print(f"[{time.strftime('%H:%M:%S')}] status={status} "
              f"phase={run.get('current_phase')} jobs: {_summarize_jobs(run)}")
        if status in RECON_TERMINAL:
            if status != "complete":
                sys.exit(f"ph.py: recon run ended non-complete: {status}")
            return 0
        if time.time() > deadline:
            sys.exit("ph.py: recon poll timed out")
        time.sleep(args.interval_s)


def cmd_hunting_launch(args: argparse.Namespace) -> int:
    resp = api("POST", f"/projects/{args.project}/hunting", {"candidates": []})
    print(resp["hunting_run_id"])
    return 0


def cmd_hunting_poll(args: argparse.Namespace) -> int:
    deadline = time.time() + args.timeout_s
    while True:
        row = api("GET", f"/projects/{args.project}/hunting/{args.hunting_run_id}")
        status = row.get("status")
        print(f"[{time.strftime('%H:%M:%S')}] hunting status={status}")
        if status in HUNTING_TERMINAL:
            return 0
        if time.time() > deadline:
            sys.exit("ph.py: hunting poll timed out")
        time.sleep(args.interval_s)


def cmd_graph_get(args: argparse.Namespace) -> int:
    resp = api("GET", f"/projects/{args.project}/graph")
    if args.out:
        with open(args.out, "w") as fh:
            json.dump(resp, fh, indent=2)
        print(args.out)
    else:
        print(json.dumps(resp, indent=2))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("project", help="project subcommands")
    ps = p.add_subparsers(dest="sub", required=True)
    pc = ps.add_parser("create")
    pc.add_argument("name")
    pc.set_defaults(fn=cmd_project_create)

    p = sub.add_parser("settings", help="settings subcommands")
    ps = p.add_subparsers(dest="sub", required=True)
    sc = ps.add_parser("put")
    sc.add_argument("project")
    sc.add_argument("--target-seed")
    sc.add_argument("--operator-kb", help="path to the operator_kb text file")
    sc.add_argument("--toggle", action="append", metavar="key=value")
    sc.set_defaults(fn=cmd_settings_put)

    p = sub.add_parser("bootstrap")
    p.add_argument("project")
    p.add_argument("--operator-kb", help="path to the operator_kb text file")
    p.set_defaults(fn=cmd_bootstrap)

    p = sub.add_parser("recon", help="recon subcommands")
    ps = p.add_subparsers(dest="sub", required=True)
    rl = ps.add_parser("launch")
    rl.add_argument("project")
    rl.add_argument("--jobs", help="comma-separated job subset (omit = default plan)")
    rl.add_argument("--no-analysis", action="store_true")
    rl.set_defaults(fn=cmd_recon_launch)
    rp = ps.add_parser("poll")
    rp.add_argument("project")
    rp.add_argument("run")
    rp.add_argument("--timeout-s", type=int, default=7200)
    rp.add_argument("--interval-s", type=int, default=15)
    rp.set_defaults(fn=cmd_recon_poll)

    p = sub.add_parser("hunting", help="hunting subcommands")
    ps = p.add_subparsers(dest="sub", required=True)
    hl = ps.add_parser("launch")
    hl.add_argument("project")
    hl.set_defaults(fn=cmd_hunting_launch)
    hp = ps.add_parser("poll")
    hp.add_argument("project")
    hp.add_argument("hunting_run_id")
    hp.add_argument("--timeout-s", type=int, default=7200)
    hp.add_argument("--interval-s", type=int, default=15)
    hp.set_defaults(fn=cmd_hunting_poll)

    p = sub.add_parser("graph", help="graph subcommands")
    ps = p.add_subparsers(dest="sub", required=True)
    gg = ps.add_parser("get")
    gg.add_argument("project")
    gg.add_argument("--out", help="write the graph JSON to FILE")
    gg.set_defaults(fn=cmd_graph_get)

    args = ap.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())