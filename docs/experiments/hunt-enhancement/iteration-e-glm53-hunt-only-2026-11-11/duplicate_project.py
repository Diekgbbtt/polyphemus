#!/usr/bin/env python3
"""Duplicate a completed project into a fresh hunting-only project.

WHAT THIS DOES
--------------
Creates a NEW project id and copies only the inputs hunting needs:

- the L0/L1 Neo4j graph (every node and relationship with the old
  `project_id`, relabelled to the new id; Observations get fresh ids because
  their unique constraint is global),
- the recon settings (`operator_kb`, `target_seed`, `application_overview`,
  `streaming_analysis`) and the hunting policy,
- the HTTP-history evidence store (SQLite + bodies, `flows.project_id`
  rewritten),
- the operator auth records and a freshly minted browser/request session for
  every scaffolded account,
- the project `authn` skill bundle.

WHAT IT DELIBERATELY DOES NOT COPY
----------------------------------
- the old `hunting/` data root (threat models, hunter specs, pod exports,
  notes) - no hunting artifact survives,
- the old usage ledger - the new trial starts its budget at zero,
- the old `hunting_runs` / checkpoint state - the new project has no run ids
  and therefore no tracked session thread. The script asserts this.
- the old recon/analysis run rows.

The old project is never mutated. The new project is not started here; the
seeded trial (`orchestrator trial --existing-project-id`) enters at hunting.

Run on the eval host, from the repo root, with the instance `.env` sourced or
with `--api`/`--compose-project` explicit.

Example:

    python3 docs/experiments/hunt-enhancement/iteration-e-glm53-hunt-only-2026-11-11/duplicate_project.py \
      --api http://127.0.0.1:8080 \
      --old-project fb865e52-719d-4637-ae7f-e6856f571166 \
      --name eval-siyucms-web-glm53-hunt \
      --data-root /opt/polymerhus-dev/eval/instances/data/eval-server-2 \
      --compose-project ph-17747005 \
      --agent-container ph-17747005-agent-1 \
      --kali-container ph-17747005-kali-1 \
      --postgres-container ph-17747005-postgres-1 \
      --setup /opt/polymerhus-dev/eval/setups/siyucms-iteration-e.yaml \
      --instance eval-server-2 \
      --target siyucms-web \
      --scope-file docs/experiments/hunt-enhancement/iteration-e-glm53-hunt-only-2026-11-11/scope-fence.txt
"""
from __future__ import annotations

import argparse
import datetime as dt
import importlib.util
import io
import json
import os
import pathlib
import subprocess
import sys
import tarfile
import urllib.parse
import urllib.request
import uuid

HERE = pathlib.Path(__file__).resolve().parent
COPY_GRAPH = HERE / "copy_graph.py"
COPY_HTTP = HERE / "copy_http_history.py"
SEED_SCRIPT = HERE.parent / "iteration-e-siyucms-2026-11-08" / "seed_iteration_e.py"


def log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def api_json(base: str, method: str, path: str, body: dict | None = None) -> object:
    data = None
    headers = {"Accept": "application/json"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(f"{base}{path}", data=data, headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=120) as response:
        payload = response.read()
    return json.loads(payload) if payload else {}


def api_multipart(base: str, path: str, filename: str, data: bytes,
                  content_type: str = "application/octet-stream") -> object:
    boundary = uuid.uuid4().hex
    parts: list[bytes] = []
    for name, value in (("fileName", filename),):
        parts.append(
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n".encode()
            + value.encode()
            + b"\r\n"
        )
    parts.append(
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; "
        f"filename=\"{filename}\"\r\nContent-Type: {content_type}\r\n\r\n".encode()
        + data
        + b"\r\n"
    )
    parts.append(f"--{boundary}--\r\n".encode())
    body = b"".join(parts)
    request = urllib.request.Request(
        f"{base}{path}",
        data=body,
        headers={
            "Accept": "application/json",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=180) as response:
        payload = response.read()
    return json.loads(payload) if payload else {}


def load_seed_module():
    if not SEED_SCRIPT.is_file():
        raise SystemExit(f"missing seed preflight: {SEED_SCRIPT}")
    spec = importlib.util.spec_from_file_location("seed_iteration_e", SEED_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    # Python 3.14's dataclass processing resolves string annotations through
    # `sys.modules[cls.__module__]`; a dynamically loaded module must be
    # registered under its spec name before `exec_module` runs.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def find_project(base: str, name: str) -> str | None:
    body = api_json(base, "GET", "/projects")
    rows = body.get("projects") if isinstance(body, dict) else body
    for row in rows or []:
        if isinstance(row, dict) and row.get("name") == name:
            return str(row.get("project_id") or row.get("id") or "")
    return None


def docker_exec(container: str, script: pathlib.Path, env: dict[str, str]) -> str:
    command = ["docker", "exec", "-i"]
    for key, value in env.items():
        command.extend(["-e", f"{key}={value}"])
    command.extend([container, "python3", "-"])
    result = subprocess.run(
        command, input=script.read_bytes(), capture_output=True, check=False
    )
    if result.returncode != 0:
        raise SystemExit(
            f"{script.name} in {container} failed: "
            f"{result.stderr.decode('utf-8', 'replace')}"
        )
    return result.stdout.decode("utf-8", "replace")


def pack_skill(skill_dir: pathlib.Path) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for path in sorted(skill_dir.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(skill_dir).as_posix()
            payload = path.read_bytes()
            info = tarfile.TarInfo(relative)
            info.size = len(payload)
            archive.addfile(info, io.BytesIO(payload))
    return buffer.getvalue()


def _stamp_snapshot(account: dict, value: str) -> None:
    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()
    headers = {"User-Agent": "polymerhus-eval-preflight/1", "Accept": "*/*"}
    existing = account.get("snapshot")
    if isinstance(existing, dict) and isinstance(existing.get("headers"), dict):
        headers = existing["headers"]
    tokens = dict(account.get("tokens") or {})
    tokens["PHPSESSID"] = {
        "value": value, "location": "cookie", "target": "PHPSESSID"
    }
    account["tokens"] = tokens
    account["snapshot"] = {
        "headers": headers,
        "cookies": [{"name": "PHPSESSID", "value": value}],
        "captured_at": now,
    }


def psql_count(postgres_container: str, sql: str) -> int:
    result = subprocess.run(
        ["docker", "exec", postgres_container, "psql", "-U", "polymerhus",
         "-d", "polymerhus", "-tAc", sql],
        capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        raise SystemExit(f"psql failed: {result.stderr.strip()}")
    return int(result.stdout.strip() or 0)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", default="http://127.0.0.1:8080")
    parser.add_argument("--old-project", required=True)
    parser.add_argument("--name", required=True,
                        help="the fresh project's display name")
    parser.add_argument("--data-root", required=True,
                        help="the instance data root (host path)")
    parser.add_argument("--compose-project", required=True,
                        help="the compose project id, e.g. ph-17747005")
    parser.add_argument("--agent-container", default=None,
                        help="default: <compose-project>-agent-1")
    parser.add_argument("--kali-container", default=None,
                        help="default: <compose-project>-kali-1")
    parser.add_argument("--postgres-container", default=None,
                        help="default: <compose-project>-postgres-1")
    parser.add_argument("--setup", required=True, help="the eval setup YAML")
    parser.add_argument("--instance", default="eval-server-2")
    parser.add_argument("--target", default="siyucms-web")
    parser.add_argument("--scope-file", required=True,
                        help="the threat_model_scope text, stored verbatim")
    parser.add_argument("--risk-threshold", type=float, default=None,
                        help="override the copied risk_threshold")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    base = args.api.rstrip("/")
    agent = args.agent_container or f"{args.compose_project}-agent-1"
    kali = args.kali_container or f"{args.compose_project}-kali-1"
    postgres = args.postgres_container or f"{args.compose_project}-postgres-1"
    data_root = pathlib.Path(args.data_root)
    scope = pathlib.Path(args.scope_file).read_text(encoding="utf-8").strip()
    if not scope:
        raise SystemExit("the scope file is empty")

    # The setup is the single source for the target host, source data dir, and
    # the source authn bundle. Importing `orchestrator` is host-side only.
    sys.path.insert(0, str(pathlib.Path(os.environ.get("EVAL_REPO", "/opt/polymerhus-dev")) / "eval"))
    from orchestrator import routing
    from orchestrator.setup import load_eval_setup

    setup = load_eval_setup(pathlib.Path(args.setup))
    instance = next(i for i in setup.instances if i.instance_id == args.instance)
    run = next(t for t in instance.targets if t.target_id == args.target)
    host = routing.synthetic_host(f"{args.instance}/{args.target}")
    source_data_dir = pathlib.Path(run.target_config.data_dir or "")
    log(f"host={host} source_data_dir={source_data_dir}")
    if not source_data_dir.is_dir():
        raise SystemExit(f"missing source data dir {source_data_dir}")
    if not (source_data_dir / "auth" / "credentials.yaml").is_file():
        raise SystemExit(f"missing {source_data_dir}/auth/credentials.yaml")
    if not (source_data_dir / "skills" / "authn").is_dir():
        raise SystemExit(f"missing {source_data_dir}/skills/authn")

    existing = find_project(base, args.name)
    if existing:
        raise SystemExit(
            f"a project named {args.name!r} already exists ({existing}); "
            "refusing to reuse or overwrite it"
        )

    if args.dry_run:
        print(json.dumps({
            "name": args.name, "old_project": args.old_project,
            "host": host, "source_data_dir": str(source_data_dir),
            "agent": agent, "kali": kali, "postgres": postgres,
        }, indent=2))
        return 0

    created = api_json(base, "POST", "/projects", {"name": args.name})
    new = str(created.get("project_id") or created.get("id") or "")
    if not new:
        raise SystemExit(f"project create returned no id: {created!r}")
    log(f"created project {args.name}: {new}")

    # 1. Copy the recon settings and the hunting policy.
    recon = api_json(base, "GET", f"/projects/{args.old_project}/settings")
    api_json(base, "PUT", f"/projects/{new}/settings", recon)
    hunting = api_json(base, "GET", f"/projects/{args.old_project}/hunting/config")
    hunting["threat_model_scope"] = scope
    if args.risk_threshold is not None:
        hunting["risk_threshold"] = args.risk_threshold
    api_json(base, "PUT", f"/projects/{new}/hunting/config", hunting)
    log(f"copied settings and hunting policy (risk_threshold="
        f"{hunting.get('risk_threshold')}, scope={len(scope)} chars)")

    # 2. Copy the L0/L1 graph inside the agent image.
    output = docker_exec(agent, COPY_GRAPH,
                         {"OLD_PROJECT_ID": args.old_project, "NEW_PROJECT_ID": new})
    log(output.strip())

    # 3. Copy the HTTP-history evidence inside Kali.
    output = docker_exec(kali, COPY_HTTP,
                         {"OLD_PROJECT_ID": args.old_project, "NEW_PROJECT_ID": new})
    log(output.strip())

    # 4. Mint fresh auth sessions and place the auth data dependencies.
    seed = load_seed_module()
    credentials_path = source_data_dir / "auth" / "credentials.yaml"
    overview_path = source_data_dir / "auth" / "overview.yaml"
    credentials_doc = seed.yaml.safe_load(credentials_path.read_text(encoding="utf-8")) or {}
    accounts = credentials_doc.get("accounts")
    if not isinstance(accounts, dict) or not accounts:
        raise SystemExit(f"{credentials_path} carries no accounts mapping")
    specs = seed.plan_sessions(accounts, host=host, project_id=new)
    log(f"minting {len(specs)} session(s) under project {new}")

    minted: dict[str, str] = {}

    def mint(spec, value):
        seed.write_context(
            args.compose_project, spec.ref, spec.account, host, value,
            role=spec.role, root_url=spec.root_url, auth_probe=spec.auth_probe,
        )
        minted[spec.account] = value

    results = seed.mint_planned_sessions(
        specs,
        mint=lambda spec: seed.mint_session(
            spec, base_url="http://127.0.0.1:80", host=host
        ),
        write=mint,
    )
    for spec, ok, error in results:
        row = accounts[spec.account]
        if ok:
            row["status"] = "valid"
            row["browser_context"] = {"ref": spec.ref}
            if spec.role:
                row["role"] = spec.role
            row["root_url"] = spec.root_path
            row["auth_probe"] = spec.auth_probe_path
            _stamp_snapshot(row, minted[spec.account])
        else:
            row["status"] = "not_valid"
            log(f"session {spec.account} failed: {error}")
    credentials_doc["accounts"] = accounts

    if not any(ok for _spec, ok, _error in results):
        raise SystemExit("no session minted; refusing to leave an unauthenticated hunt")
    admin = next((r for r in results if "admin" in r[0].account), None)
    if admin is not None and not admin[1]:
        raise SystemExit("the admin session failed; the default-credential hunt cannot run")

    credentials_bytes = seed.yaml.safe_dump(
        credentials_doc, sort_keys=False, allow_unicode=True
    ).encode("utf-8")
    api_multipart(base, f"/projects/{new}/data-dependencies/auth-overview",
                  "overview.yaml", overview_path.read_bytes())
    api_multipart(base, f"/projects/{new}/data-dependencies/auth-credentials",
                  "credentials.yaml", credentials_bytes)
    api_multipart(base, f"/projects/{new}/data-dependencies/authn-skill",
                  "authn.tar.gz", pack_skill(source_data_dir / "skills" / "authn"),
                  content_type="application/gzip")
    log(f"placed auth overview, credentials, and authn skill; "
        f"minted {sum(1 for _s, ok, _e in results if ok)}/{len(results)}")

    # 5. Assert the new project carries no hunting state. The data root is the
    # agent's `/srv/data/<new>` bind, which is the host path below. Project
    # creation scaffolds empty module directories, so the hunting directory may
    # exist but must hold no artifact; remove the empty scaffold so the new hunt
    # starts from a pristine root.
    import shutil

    new_dir = data_root / new
    hunting_dir = new_dir / "hunting"
    if hunting_dir.exists():
        artifacts = [path for path in hunting_dir.rglob("*") if path.is_file()]
        if artifacts:
            raise SystemExit(
                f"new project unexpectedly carries {len(artifacts)} hunting "
                f"artifact file(s) under {hunting_dir}; refusing a contaminated hunt"
            )
        shutil.rmtree(hunting_dir)
    runs = psql_count(
        postgres,
        f"SELECT count(*) FROM hunting_runs WHERE project_id = '{new}'",
    )
    if runs:
        raise SystemExit(f"new project {new} already has {runs} hunting run row(s)")
    # A hunt thread is keyed by the hunting run id, so an empty hunting_runs
    # table for the new project is the tracked-session-state guarantee.
    log("verified: no hunting dir, no hunting_runs, no tracked hunt session")

    summary = {
        "old_project": args.old_project,
        "new_project": new,
        "name": args.name,
        "host": host,
        "risk_threshold": hunting.get("risk_threshold"),
        "scope_chars": len(scope),
        "accounts": {
            name: {"status": row.get("status"),
                   "browser_context": (row.get("browser_context") or {}).get("ref")}
            for name, row in accounts.items()
        },
        "minted": {spec.account: ok for spec, ok, _error in results},
        "data_root": str(new_dir),
    }
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
