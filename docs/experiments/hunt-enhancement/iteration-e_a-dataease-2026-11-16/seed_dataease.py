#!/usr/bin/env python3
"""Seed the iteration E_a dataease trial: the project and the scope fence.

The full-pipeline trial creates and bootstraps its own project, but the
threat-model scope is a project attribute the eval setup schema does not
carry. This preflight:

1. finds or creates the throwaway project;
2. writes the reusable iteration-D scope verbatim to
   `settings.hunting.threat_model_scope`.

The trial then runs with `--project-id`, so its `_bootstrap` applies the
recon settings, the data dependencies, and the L1 scaffold, and its partial
hunting PUT deep-merges the four policy fields without clearing the scope.

Read-only for the target; writes only the throwaway project settings.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import urllib.request


def api_call(base: str, method: str, path: str, body: dict | None = None) -> object:
    data = None
    headers = {"Accept": "application/json"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(
        f"{base}{path}", data=data, headers=headers, method=method
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        payload = response.read()
    return json.loads(payload) if payload else {}


def find_project(base: str, name: str) -> str | None:
    body = api_call(base, "GET", "/projects")
    rows = body.get("projects") if isinstance(body, dict) else body
    if not isinstance(rows, list):
        return None
    for row in rows:
        if isinstance(row, dict) and row.get("name") == name:
            return str(row.get("project_id") or row.get("id") or "")
    return None


def ensure_project(base: str, name: str) -> str:
    existing = find_project(base, name)
    if existing:
        print(f"project {name} exists: {existing}", flush=True)
        return existing
    body = api_call(base, "POST", "/projects", {"name": name})
    project_id = str(body.get("project_id") or body.get("id") or "")
    if not project_id:
        raise SystemExit(f"project create returned no id: {body!r}")
    print(f"project {name} created: {project_id}", flush=True)
    return project_id


def put_scope(base: str, project_id: str, scope: str) -> None:
    api_call(base, "PUT", f"/projects/{project_id}/hunting/config",
             {"threat_model_scope": scope})
    stored = api_call(base, "GET", f"/projects/{project_id}/hunting/config")
    if not isinstance(stored, dict) or stored.get("threat_model_scope") != scope:
        raise SystemExit(f"scope did not persist: {stored!r}")
    print("scope fence frozen", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", default="http://127.0.0.1:8080")
    parser.add_argument("--name", required=True)
    parser.add_argument("--scope-file", type=pathlib.Path, required=True)
    args = parser.parse_args()

    scope = args.scope_file.read_text(encoding="utf-8").strip()
    if not scope:
        raise SystemExit(f"empty scope file: {args.scope_file}")
    project_id = ensure_project(args.api, args.name)
    put_scope(args.api, project_id, scope)
    print(project_id, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
