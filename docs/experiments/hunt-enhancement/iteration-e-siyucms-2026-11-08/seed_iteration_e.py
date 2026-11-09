#!/usr/bin/env python3
"""Seed one iteration E trial: project, policy, and the designed browser context.

The auth gateway validates the recorded oracle in the one browser tool; it
never reads a stored credential. The siyucms admin sign-in is request-based,
so the operator bootstrap mints the admin session through the target front and
writes the durable browser context record under the deterministic
`steel-auth-<project>-<account>` reference.

The preflight runs after `orchestrator up` has brought the target up and
before `orchestrator trial --project-id`. The trial then places the auth data
dependencies and the L1 scaffold and launches recon with the same project id.

Read-only for the target; writes only the throwaway project/settings and the
pool session record.
"""
from __future__ import annotations

import argparse
import datetime as dt
from dataclasses import dataclass
import hashlib
import http.cookiejar
import json
import pathlib
import re
import subprocess
import sys
import urllib.parse
import urllib.request

import yaml

from orchestrator import routing
from orchestrator.setup import load_eval_setup

SESSION_MAX = 75
CONTEXT_PREFIX = "steel-auth"
STORE_ROOT = "/var/lib/steel/sessions"
ORACLE_FALLBACK = "/index.php/admin/Index/index.html"


def log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


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
        log(f"project {name} exists: {existing}")
        return existing
    body = api_call(base, "POST", "/projects", {"name": name})
    project_id = str(body.get("project_id") or body.get("id") or "")
    if not project_id:
        raise SystemExit(f"project create returned no id: {body!r}")
    log(f"project {name} created: {project_id}")
    return project_id


def put_settings(base: str, project_id: str, settings: dict) -> None:
    api_call(base, "PUT", f"/projects/{project_id}/settings", {"recon": settings})
    log("settings frozen")


def put_hunting(base: str, project_id: str, hunting: dict) -> None:
    api_call(base, "PUT", f"/projects/{project_id}/hunting/config", hunting)
    log(f"hunting policy frozen: {sorted(hunting)}")


def _slug(value: str, fallback: str) -> str:
    text = re.sub(r"[^A-Za-z0-9_-]+", "-", (value or "").strip()).strip("-_")
    text = re.sub(r"-{2,}", "-", text).lower()
    return text or fallback


def _bounded(prefix: str, parts: list[str]) -> str:
    name = "-".join([prefix, *[part for part in parts if part]])
    if len(name) <= SESSION_MAX:
        return name
    digest = hashlib.sha256(name.encode("utf-8")).hexdigest()[:12]
    head = name[: SESSION_MAX - len(digest) - 1].rstrip("-_")
    return f"{head}-{digest}"


def browser_context_ref(project_id: str, account: str) -> str:
    return _bounded(
        CONTEXT_PREFIX,
        [_slug(project_id, "project"), _slug(account, "account")],
    )


def _absolute_url(host: str, value: str) -> str:
    """Resolve a root-relative session URL against the synthetic target host."""
    parsed = urllib.parse.urlsplit(value)
    if parsed.scheme or parsed.netloc:
        return value
    return f"http://{host.rstrip('/')}/{value.lstrip('/')}"


@dataclass(frozen=True)
class SessionSpec:
    """One scaffolded account's mint input and its absolute pool record."""

    account: str
    role: str | None
    root_url: str
    auth_probe: str
    root_path: str
    auth_probe_path: str
    login_page: str
    username: str
    password: str
    procedure: str
    ref: str


def plan_sessions(
    accounts: dict,
    *,
    host: str,
    project_id: str,
) -> list[SessionSpec]:
    """One mint plan per credential-bearing account.

    The account is the session: its role/root/auth_probe describe the
    privilege surface. An absent root is `/`; an absent probe is the root.
    A stale `not_valid` account is included because this preflight is what
    refreshes it.
    """
    specs: list[SessionSpec] = []
    for account, row in accounts.items():
        if not isinstance(account, str) or not isinstance(row, dict):
            continue
        credentials = row.get("credentials")
        if not isinstance(credentials, dict):
            continue
        username = credentials.get("username")
        password = credentials.get("password")
        if not isinstance(username, str) or not username:
            continue
        if not isinstance(password, str) or not password:
            continue
        root_path = row.get("root_url")
        if not isinstance(root_path, str) or not root_path:
            root_path = "/"
        probe_path = row.get("auth_probe")
        if not isinstance(probe_path, str) or not probe_path:
            probe_path = root_path
        role = row.get("role") or row.get("default_role")
        if not isinstance(role, str) or not role:
            role = None
        login_page = credentials.get("login_url")
        if not isinstance(login_page, str) or not login_page:
            login_page = "/"
        procedure = row.get("procedure")
        if not isinstance(procedure, str):
            procedure = ""
        specs.append(
            SessionSpec(
                account=account,
                role=role,
                root_url=_absolute_url(host, root_path),
                auth_probe=_absolute_url(host, probe_path),
                root_path=root_path,
                auth_probe_path=probe_path,
                login_page=login_page,
                username=username,
                password=password,
                procedure=procedure,
                ref=browser_context_ref(project_id, account),
            )
        )
    return specs


def mint_planned_sessions(
    specs: list[SessionSpec],
    *,
    mint,
    write,
) -> list[tuple[SessionSpec, bool, str | None]]:
    """Mint and persist every session; one failure never stops the others."""
    results: list[tuple[SessionSpec, bool, str | None]] = []
    for spec in specs:
        try:
            value = mint(spec)
            write(spec, value)
        except Exception as exc:  # noqa: BLE001 - one session failure is contained
            log(f"session {spec.account} mint failed: {exc}")
            results.append((spec, False, str(exc)))
        else:
            log(f"session {spec.account} minted; oracle passed")
            results.append((spec, True, None))
    return results


def _request(url: str, host: str, *, data: bytes | None = None, headers=None):
    merged = {"Host": host, "User-Agent": "polymerhus-eval-preflight/1"}
    if headers:
        merged.update(headers)
    return urllib.request.Request(url, data=data, headers=merged)


def mint_admin_session(
    base_url: str,
    host: str,
    login_page: str,
    username: str,
    password: str,
    oracle_url: str = ORACLE_FALLBACK,
) -> str:
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    page = opener.open(_request(f"{base_url}{login_page}", host), timeout=30)
    html = page.read().decode("utf-8", "replace")
    if page.status != 200:
        raise SystemExit(f"login page answered {page.status}")
    match = re.search(
        r'name=["\']__token__["\'][^>]*value=["\']([^"\']+)', html
    ) or re.search(
        r'value=["\']([^"\']+)["\'][^>]*name=["\']__token__["\']', html
    )
    if match is None:
        raise SystemExit("login page carries no __token__")
    token = match.group(1)
    parent = login_page.rsplit("/", 1)[0]
    post_url = f"{base_url}{parent}/checkLogin.html"
    payload = urllib.parse.urlencode(
        {"username": username, "password": password, "__token__": token}
    ).encode("utf-8")
    response = opener.open(
        _request(
            post_url,
            host,
            data=payload,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        ),
        timeout=30,
    )
    body = response.read().decode("utf-8", "replace")
    try:
        result = json.loads(body)
    except json.JSONDecodeError:
        raise SystemExit(f"login POST returned non-JSON: {body[:200]!r}")
    if str(result.get("error")) != "0":
        raise SystemExit(f"login POST refused: {result!r}")
    value = None
    for cookie in jar:
        if cookie.name == "PHPSESSID":
            value = cookie.value
    if not value:
        raise SystemExit("login POST returned no PHPSESSID")
    oracle = opener.open(
        _request(f"{base_url}{oracle_url}", host), timeout=30
    )
    oracle_body = oracle.read().decode("utf-8", "replace")
    final = oracle.geturl()
    if oracle.status != 200 or "SIYUCMS | 控制台" not in oracle_body:
        raise SystemExit(
            f"oracle did not pass: status={oracle.status} final={final}"
        )
    log("admin session minted; oracle passed")
    return value


def mint_member_session(
    base_url: str,
    host: str,
    login_page: str,
    username: str,
    password: str,
    probe_path: str,
) -> str:
    """Mint one front-end member PHPSESSID and prove its landing."""
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    payload = urllib.parse.urlencode(
        {"username": username, "password": password}
    ).encode("utf-8")
    response = opener.open(
        _request(
            f"{base_url}{login_page}",
            host,
            data=payload,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        ),
        timeout=30,
    )
    response.read()
    value = None
    for cookie in jar:
        if cookie.name == "PHPSESSID":
            value = cookie.value
    if not value:
        raise SystemExit("member sign-in returned no PHPSESSID")
    oracle = opener.open(
        _request(f"{base_url}{probe_path}", host), timeout=30
    )
    oracle.read()
    if (
        oracle.status < 200
        or oracle.status >= 300
        or oracle.geturl() != f"{base_url}{probe_path}"
    ):
        raise SystemExit(
            f"member oracle did not pass: status={oracle.status} "
            f"final={oracle.geturl()}"
        )
    return value


def mint_session(spec: SessionSpec, *, base_url: str, host: str) -> str:
    """Dispatch one session to its target procedure."""
    probe_path = urllib.parse.urlsplit(spec.auth_probe).path or "/"
    if spec.procedure == "sign-in-admin-backend" or "/admin/" in spec.login_page:
        return mint_admin_session(
            base_url,
            host,
            spec.login_page,
            spec.username,
            spec.password,
            probe_path,
        )
    if spec.procedure == "sign-in-member" or "/index/user/" in spec.login_page:
        return mint_member_session(
            base_url,
            host,
            spec.login_page,
            spec.username,
            spec.password,
            probe_path,
        )
    raise SystemExit(
        f"no mint procedure for account {spec.account!r}: {spec.procedure!r}"
    )


def write_context(
    compose_project: str,
    ref: str,
    account: str,
    host: str,
    value: str,
    *,
    role: str | None = None,
    root_url: str | None = None,
    auth_probe: str | None = None,
) -> None:
    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()
    record = {
        "name": ref,
        "account": account,
        "role": role,
        "root_url": root_url,
        "auth_probe": auth_probe,
        "cookies": [
            {
                "name": "PHPSESSID",
                "value": value,
                "domain": host,
                "path": "/",
            }
        ],
        "localStorage": {},
        "sessionStorage": {},
        "indexedDB": {},
        "createdAt": now,
        "updatedAt": now,
    }
    payload = json.dumps(record, ensure_ascii=False).encode("utf-8")
    container = f"{compose_project}-kali-1"
    command = [
        "docker", "exec", "-i", container, "sh", "-lc",
        f"umask 077; cat > {STORE_ROOT}/{ref}.json",
    ]
    result = subprocess.run(command, input=payload, capture_output=True, check=False)
    if result.returncode != 0:
        raise SystemExit(
            f"context write failed: {result.stderr.decode('utf-8', 'replace')}"
        )
    verify = subprocess.run(
        [
            "docker", "exec", container, "sh", "-lc",
            "cd /opt/kali && python -c "
            "\"from steel_pool.store import SessionStore; "
            f"s=SessionStore('{STORE_ROOT}'); r=s.load('{ref}'); "
            'print(r is not None, len(r.cookies) if r else 0)"',
        ],
        capture_output=True, text=True, check=False,
    )
    log(f"context {ref} written; verify={verify.stdout.strip()!r}")
    if verify.returncode != 0 or not verify.stdout.strip().endswith(" 1"):
        raise SystemExit(f"context verify failed: {verify.stderr.strip()}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--setup", required=True)
    parser.add_argument("--api", default="http://127.0.0.1:8080")
    parser.add_argument("--compose-project", required=True)
    parser.add_argument("--instance", default="eval-server-2")
    parser.add_argument("--target", default="siyucms-web")
    parser.add_argument(
        "--account",
        default=None,
        help="mint only this account; the default mints every scaffolded account",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    setup = load_eval_setup(pathlib.Path(args.setup))
    instance = next(i for i in setup.instances if i.instance_id == args.instance)
    run = next(t for t in instance.targets if t.target_id == args.target)
    host = routing.synthetic_host(f"{args.instance}/{args.target}")
    project_name = f"eval-{args.target}"
    data_dir = pathlib.Path(run.target_config.data_dir or "")
    operator_kb = pathlib.Path(run.target_config.operator_kb or "")
    credentials_path = data_dir / "auth" / "credentials.yaml"
    overview_path = data_dir / "auth" / "overview.yaml"
    if not credentials_path.is_file() or not overview_path.is_file():
        raise SystemExit(f"missing auth data dependencies under {data_dir}")

    credentials_doc = yaml.safe_load(
        credentials_path.read_text(encoding="utf-8")
    ) or {}
    accounts = credentials_doc.get("accounts")
    if not isinstance(accounts, dict):
        raise SystemExit(f"{credentials_path} carries no accounts mapping")
    if args.account is not None and args.account not in accounts:
        raise SystemExit(f"account {args.account!r} is not in {credentials_path}")

    log(
        f"host={host} project={project_name} "
        f"accounts={args.account or 'all'}"
    )
    if args.dry_run:
        print(project_name)
        return 0

    project_id = ensure_project(args.api, project_name)
    settings = {
        "target_seed": host,
        "operator_kb": operator_kb.read_text(encoding="utf-8"),
        "streaming_analysis": True,
    }
    put_settings(args.api, project_id, settings)
    put_hunting(args.api, project_id, run.hunting.payload())

    specs = plan_sessions(accounts, host=host, project_id=project_id)
    if args.account is not None:
        specs = [spec for spec in specs if spec.account == args.account]
    results = mint_planned_sessions(
        specs,
        mint=lambda spec: mint_session(
            spec, base_url="http://127.0.0.1:80", host=host
        ),
        write=lambda spec, value: write_context(
            args.compose_project,
            spec.ref,
            spec.account,
            host,
            value,
            role=spec.role,
            root_url=spec.root_url,
            auth_probe=spec.auth_probe,
        ),
    )
    for spec, minted, _error in results:
        row = accounts[spec.account]
        if minted:
            row["status"] = "valid"
            row["browser_context"] = {"ref": spec.ref}
            if spec.role:
                row["role"] = spec.role
            row["root_url"] = spec.root_path
            row["auth_probe"] = spec.auth_probe_path
        else:
            row["status"] = "not_valid"
    credentials_doc["accounts"] = accounts
    temporary = credentials_path.with_suffix(".yaml.tmp")
    temporary.write_text(
        yaml.safe_dump(credentials_doc, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    temporary.replace(credentials_path)
    minted = sum(1 for _spec, ok, _error in results if ok)
    log(f"minted {minted}/{len(results)} sessions")
    print(project_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
