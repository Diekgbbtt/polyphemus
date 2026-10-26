#!/usr/bin/env python3
"""Prepare a pre-authenticated Steel session for the E2E scenarios.

The harness starts a named session when it is absent, sets the httpOnly
JSESSIONID and rememberMe cookies from the operator session JSON, and proves
the authenticated surface through the browser. It never prints a cookie value.
It writes a redacted evidence summary and leaves the session live for the agent
under test.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path

from langchain_mcp_adapters.client import MultiServerMCPClient

TARGET = "http://t-1618c524.target"
DOMAIN = "t-1618c524.target"


def _redact(value: str, secrets: list[str]) -> str:
    out = value
    for secret in secrets:
        if secret:
            out = out.replace(secret, "<redacted>")
    return out


def _envelope(text: str) -> dict:
    return json.loads(text)


def _inner(envelope: dict) -> dict:
    stdout = envelope.get("stdout") or ""
    if not stdout.strip():
        return {"success": False, "data": None}
    try:
        return json.loads(stdout)
    except Exception:
        return {"success": False, "data": None, "raw": stdout[:500]}


def _role_names(value: object) -> list[str]:
    if isinstance(value, dict):
        return [str(k) for k in value]
    if isinstance(value, list):
        names = []
        for item in value:
            if isinstance(item, dict):
                name = item.get("name") or item.get("role")
                if name:
                    names.append(str(name))
            elif item is not None:
                names.append(str(item))
        return names
    return []


def _admin_summary(body: str) -> dict:
    try:
        parsed = json.loads(body) if body else {}
    except Exception:
        parsed = {}
    result = parsed.get("result") if isinstance(parsed, dict) else None
    entries = result if isinstance(result, list) else ([result] if isinstance(result, dict) else [])
    username = None
    roles: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        if str(entry.get("username") or "") == "admin":
            username = "admin"
            roles = _role_names(entry.get("roles"))
            break
    return {
        "code": parsed.get("code") if isinstance(parsed, dict) else None,
        "username_admin": username == "admin",
        "roles": sorted(set(roles)),
        "sysadmin": "sysAdmin" in body,
        "password_field_present": isinstance(parsed, dict)
        and "password" in body
        and any(isinstance(e, dict) and "password" in e for e in entries),
        "result_count": len(entries),
    }


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--session", default="wj-gateway-e2e")
    parser.add_argument("--session-json", required=True, type=Path)
    parser.add_argument("--session-id", default="session-prep")
    parser.add_argument("--mcp-url", default=os.environ.get(
        "KALI_MCP_URL", "http://kali:8001/mcp"))
    parser.add_argument("--evidence", type=Path, default=Path(
        "/tmp/polymerhus-e2e/evidence/session-prep.json"))
    args = parser.parse_args()

    payload = json.loads(args.session_json.read_text(encoding="utf-8"))
    jsession = str(payload.get("JSESSIONID") or "").strip()
    remember = str(payload.get("rememberMe") or "").strip()
    if not jsession:
        raise SystemExit("session JSON carries no JSESSIONID")
    secrets = [jsession, remember]

    client = MultiServerMCPClient(
        {"kali": {"url": args.mcp_url, "transport": "streamable_http"}})
    tools = {tool.name: tool for tool in await client.get_tools()}

    async def steel(command: str, timeout_s: int = 120) -> dict:
        result = await asyncio.wait_for(
            tools["steel_exec"].ainvoke(
                {"command": command, "session_id": args.session_id,
                 "timeout_s": timeout_s}),
            timeout=timeout_s + 30,
        )
        text = result[0]["text"] if isinstance(result, list) else str(result)
        envelope = _envelope(text)
        envelope["inner"] = _inner(envelope)
        return envelope

    commands: list[dict] = []

    def record(name: str, command: str, envelope: dict) -> None:
        commands.append({
            "name": name,
            "command": _redact(command, secrets),
            "returncode": envelope.get("returncode"),
            "duration_ms": envelope.get("duration_ms"),
            "inner_success": bool((envelope.get("inner") or {}).get("success")),
            "data": _redact_data((envelope.get("inner") or {}).get("data"), secrets),
        })

    def _redact_data(value, secrets: list[str]):
        if isinstance(value, str):
            return _redact(value, secrets)
        if isinstance(value, dict):
            return {k: _redact_data(v, secrets) for k, v in value.items()}
        if isinstance(value, list):
            return [_redact_data(v, secrets) for v in value]
        return value

    sessions_cmd = "steel browser sessions --json"
    sessions_env = await steel(sessions_cmd)
    sessions_data = (sessions_env.get("inner") or {}).get("data") or []
    live = {str(item.get("name")) for item in sessions_data if isinstance(item, dict)}
    record("sessions-before", sessions_cmd, sessions_env)

    created = False
    session_id = None
    if args.session not in live:
        start_cmd = (f"steel browser start --session {args.session} "
                     f"--session-timeout 86400000 --inactivity-timeout 0 --json")
        start_env = await steel(start_cmd)
        record("start", start_cmd, start_env)
        start_data = (start_env.get("inner") or {}).get("data") or {}
        session_id = start_data.get("id")
        created = start_env.get("returncode") == 0
    else:
        for item in sessions_data:
            if isinstance(item, dict) and item.get("name") == args.session:
                session_id = item.get("id")

    cookie_defs = [("JSESSIONID", jsession)]
    if remember:
        cookie_defs.append(("rememberMe", remember))
    cookie_set_ok = {}
    for name, value in cookie_defs:
        set_cmd = (f"steel browser cookies set --session {args.session} "
                   f"--domain {DOMAIN} --path / --http-only --json {name} {value}")
        set_env = await steel(set_cmd, timeout_s=60)
        record(f"cookie-set-{name}", set_cmd, set_env)
        cookie_set_ok[name] = set_env.get("returncode") == 0

    nav_dashboard = (f"steel browser navigate {TARGET}/admin/dashboard "
                     f"--wait-until domcontentloaded --session {args.session} --json")
    dash_env = await steel(nav_dashboard)
    record("navigate-dashboard", nav_dashboard, dash_env)
    snap_cmd = f"steel browser snapshot -i --session {args.session} --json"
    snap_env = await steel(snap_cmd)
    record("snapshot-dashboard", snap_cmd, snap_env)
    snapshot = ((snap_env.get("inner") or {}).get("data") or "")
    if not isinstance(snapshot, str):
        snapshot = str(snapshot)

    nav_authn = (f"steel browser navigate {TARGET}/api/authentication "
                 f"--wait-until domcontentloaded --session {args.session} --json")
    authn_env = await steel(nav_authn)
    record("navigate-authentication", nav_authn, authn_env)
    authn_url = ((authn_env.get("inner") or {}).get("data") or {}).get("url")
    eval_authn = (f'steel browser eval "document.body.innerText" '
                  f"--session {args.session} --json")
    authn_body_env = await steel(eval_authn)
    record("eval-authentication", eval_authn, authn_body_env)
    authn_body = ((authn_body_env.get("inner") or {}).get("data") or "")
    if not isinstance(authn_body, str):
        authn_body = str(authn_body)
    authn_marker = "身份认证成功" in authn_body

    nav_admin = (f"steel browser navigate {TARGET}/api/admin/user "
                 f"--wait-until domcontentloaded --session {args.session} --json")
    admin_nav_env = await steel(nav_admin)
    record("navigate-admin-user", nav_admin, admin_nav_env)
    admin_url = ((admin_nav_env.get("inner") or {}).get("data") or {}).get("url")
    eval_admin = (f'steel browser eval "document.body.innerText" '
                  f"--session {args.session} --json")
    admin_body_env = await steel(eval_admin)
    record("eval-admin-user", eval_admin, admin_body_env)
    admin_body = ((admin_body_env.get("inner") or {}).get("data") or "")
    if not isinstance(admin_body, str):
        admin_body = str(admin_body)
    admin = _admin_summary(admin_body)
    # The privileged probe can echo account records. Keep the raw body out of
    # the evidence bundle; the redacted summary carries the proof.
    commands[-1]["data"] = {"body_chars": len(admin_body), **admin}
    commands[-1]["body_withheld"] = True

    eval_cookie = (f'steel browser eval "document.cookie" '
                   f"--session {args.session} --json")
    cookie_env = await steel(eval_cookie)
    record("eval-document-cookie", eval_cookie, cookie_env)
    document_cookie = ((cookie_env.get("inner") or {}).get("data") or "")
    if not isinstance(document_cookie, str):
        document_cookie = str(document_cookie)

    cookies_cmd = f"steel browser cookies --session {args.session} --json"
    cookies_env = await steel(cookies_cmd)
    record("cookies", cookies_cmd, cookies_env)
    cookie_data = (cookies_env.get("inner") or {}).get("data") or []
    cookie_flags = {
        str(item.get("name")): {
            "domain": item.get("domain"),
            "path": item.get("path"),
            "httpOnly": item.get("httpOnly"),
            "secure": item.get("secure"),
        }
        for item in cookie_data if isinstance(item, dict)
    }

    after_env = await steel(sessions_cmd)
    after_data = (after_env.get("inner") or {}).get("data") or []
    live_after = {str(item.get("name")) for item in after_data if isinstance(item, dict)}
    session_live = args.session in live_after

    summary = {
        "session": args.session,
        "session_id": session_id,
        "created": created,
        "session_live": session_live,
        "cookie_set_ok": cookie_set_ok,
        "authn": {
            "url": authn_url,
            "marker": authn_marker,
            "body_chars": len(authn_body),
        },
        "admin": {
            **admin,
            "url": admin_url,
            "body_chars": len(admin_body),
        },
        "document_cookie_len": len(document_cookie),
        "cookie_flags": cookie_flags,
        "snapshot_chars": len(snapshot),
        "snapshot_preview": snapshot[:1200],
        "commands": commands,
    }
    args.evidence.parent.mkdir(parents=True, exist_ok=True)
    args.evidence.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "session": args.session,
        "session_live": session_live,
        "created": created,
        "cookie_set_ok": cookie_set_ok,
        "authn_marker": authn_marker,
        "admin_code": admin.get("code"),
        "admin_sysadmin": admin.get("sysadmin"),
        "admin_password_field_present": admin.get("password_field_present"),
        "document_cookie_len": len(document_cookie),
        "cookie_flags": cookie_flags,
        "evidence": str(args.evidence),
    }, ensure_ascii=False))

    required = (
        session_live
        and all(cookie_set_ok.values())
        and authn_marker
        and admin.get("code") == 200
        and admin.get("sysadmin")
        and len(document_cookie) == 0
        and all(flags.get("httpOnly") for flags in cookie_flags.values())
    )
    return 0 if required else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
