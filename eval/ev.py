#!/usr/bin/env python3
"""ev.py - the light eval harness's evidence-bundle collector.

Assembles ONE self-contained bundle directory per trial: the L0/L1 graph, the
hunt-store trail, the hunter working memory, and the pod artifact tree when
present, plus the run statuses and a manifest. The bundle is the oracle's only
input, and the migration seam: a later deterministic oracle replays the same
bundles.

Stdlib only. The polymerhus API base is PH_API (default http://localhost:8080).

Usage:
  ev.py collect <project_id> <hunting_run_id> --out <dir>
                [--recon-run RUN_ID] [--target-url URL] [--challenge ID]

Bundle sources resolve under the #234 app-owned data root
(<repo>/data/<project_id>/hunting/...): the orchestration, hunter, and
test-executor-pod buckets are copied once each, so no file lands twice in
the bundle. The slot mapping is provisional pending the automation rewrite.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

# Shared eval data-root resolver (HUNT_DATA_ROOT override, else <repo>/data).
from data_root import resolve

API_BASE = os.environ.get("PH_API", "http://localhost:8080").rstrip("/")


def api_get(path: str) -> dict | None:
    try:
        with urllib.request.urlopen(f"{API_BASE}{path}", timeout=30) as resp:
            payload = resp.read()
            return json.loads(payload) if payload else {}
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        print(f"ev.py: HTTP {exc.code} GET {path} (recorded as missing)", file=sys.stderr)
        return None
    except urllib.error.URLError as exc:
        print(f"ev.py: cannot reach {API_BASE}: {exc.reason}", file=sys.stderr)
        return None


def _copy_tree(src: Path, dst: Path) -> dict:
    if not src.exists():
        return {"present": False}
    shutil.copytree(src, dst)
    n_files = sum(1 for p in dst.rglob("*") if p.is_file())
    return {"present": True, "files": n_files}


def collect(project_id: str, hunting_run_id: str, out: Path, *,
            recon_run: str | None, target_url: str | None,
            challenge: str | None) -> int:
    out.mkdir(parents=True, exist_ok=True)
    started = time.time()

    graph = api_get(f"/projects/{project_id}/graph")
    (out / "graph.json").write_text(json.dumps(graph, indent=2) if graph else "null")

    hunting_status = api_get(f"/projects/{project_id}/hunting/{hunting_run_id}")
    (out / "hunting_status.json").write_text(
        json.dumps(hunting_status, indent=2) if hunting_status else "null")

    recon_status = api_get(f"/projects/{project_id}/recon/{recon_run}") if recon_run else None
    (out / "recon_status.json").write_text(
        json.dumps(recon_status, indent=2) if recon_status else "null")

    analysis_status = api_get(f"/projects/{project_id}/analysis/{recon_run}") if recon_run else None
    (out / "analysis_status.json").write_text(
        json.dumps(analysis_status, indent=2) if analysis_status else "null")

    hunting = resolve() / str(project_id) / "hunting"
    hunt_store = _copy_tree(hunting / "orchestration", out / "hunt_store")
    project_memory = _copy_tree(hunting / "hunter", out / "project_memory")
    pod_memory = _copy_tree(hunting / "test-executor-pod", out / "pod_memory")

    kb_files = {
        name: (out / name).exists()
        for name in ("operator_kb.md", "research-notes.md")
    }

    manifest = {
        "collected_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "project_id": project_id,
        "hunting_run_id": hunting_run_id,
        "recon_run": recon_run,
        "target_url": target_url,
        "challenge": challenge,
        "hunting_status": (hunting_status or {}).get("status"),
        "recon_status": (recon_status or {}).get("status"),
        "analysis_status": (analysis_status or {}).get("status"),
        "stores": {
            "hunt_store": hunt_store,
            "project_memory": project_memory,
            "pod_memory": pod_memory,
        },
        "kb": kb_files,
        "elapsed_s": round(time.time() - started, 1),
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(json.dumps(manifest, indent=2))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("collect")
    c.add_argument("project_id")
    c.add_argument("hunting_run_id")
    c.add_argument("--out", required=True, help="bundle directory")
    c.add_argument("--recon-run", help="the recon run id (for the liveness gate)")
    c.add_argument("--target-url", help="the published target URL")
    c.add_argument("--challenge", help="the WebExploitBench challenge id")
    c.set_defaults(fn=collect)
    args = ap.parse_args()
    return args.fn(
        args.project_id, args.hunting_run_id, Path(args.out),
        recon_run=args.recon_run, target_url=args.target_url,
        challenge=args.challenge,
    )


if __name__ == "__main__":
    sys.exit(main())
