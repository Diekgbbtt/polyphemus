#!/usr/bin/env python3
"""Seed the Steel E2E browser-only fixture into a project auth bucket.

The target itself is request-replayable. This seed writes a deliberate
browser-only overlay so the live run exercises the Steel path. The session
JSON is supplied by the operator and must contain a fresh JSESSIONID and,
optionally, a rememberMe value. The script never prints either value.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

from polymerhus.app.auth.records import select_recent_usable_account
from polymerhus.app.auth.store import AuthStore
from polymerhus.app.llm.skills import SkillStore
from polymerhus.recon.control.authn_loop import classify_gate, select_branch

HERE = Path(__file__).resolve().parent


def _session_payload(path: Path) -> tuple[str, str | None, str]:
    body = json.loads(path.read_text(encoding="utf-8"))
    jsession = str(body.get("JSESSIONID") or "").strip()
    if not jsession:
        raise SystemExit("session JSON carries no JSESSIONID")
    remember = str(body.get("rememberMe") or "").strip() or None
    captured = str(body.get("captured_at") or "").strip()
    if not captured:
        captured = datetime.now(timezone.utc).isoformat()
    return jsession, remember, captured


def _account(jsession: str, remember: str | None, captured: str) -> dict:
    cookies = [{"name": "JSESSIONID", "value": jsession}]
    if remember:
        cookies.append({"name": "rememberMe", "value": remember})
    return {
        "procedure": "browser-session-reuse",
        "tokens": {
            "JSESSIONID": {
                "value": jsession,
                "location": "cookie",
                "target": "/",
            }
        },
        "snapshot": {
            "captured_at": captured,
            "cookies": cookies,
            "headers": {},
            "params": {},
        },
        "notes": (
            "Session-only browser context for the Steel E2E fixture. "
            "The JSESSIONID token is the live Shiro session. "
            "No credentials are stored. "
            "Reuse the pre-authenticated Steel session wj-gateway-e2e. "
            "Never print the token. "
            "The overview is a deliberate browser-only overlay; the target is "
            "actually request-replayable."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--session-json", required=True, type=Path)
    parser.add_argument("--project", default="steel-e2e-395")
    parser.add_argument("--account", default="admin-sessiononly-e2e")
    parser.add_argument("--data-root", default="/srv/data")
    parser.add_argument("--skills-root", default="/tmp/polymerhus-e2e/skills")
    parser.add_argument("--overview", type=Path,
                        default=HERE / "overview.browser-only.yaml")
    parser.add_argument("--skill", type=Path,
                        default=HERE / "skills" / "authn" / "SKILL.md")
    args = parser.parse_args()

    overview = yaml.safe_load(args.overview.read_text(encoding="utf-8"))
    if not isinstance(overview, dict):
        raise SystemExit("overview fixture is not a mapping")
    jsession, remember, captured = _session_payload(args.session_json)
    account = _account(jsession, remember, captured)

    skill_dst = (Path(args.skills_root) / "target-specific-procedure"
                 / args.project / "authn" / "SKILL.md")
    skill_dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(args.skill, skill_dst)
    skill_dst.chmod(0o644)

    store = AuthStore(root_dir=args.data_root)
    store.replace_operator_state(
        args.project,
        overview=overview,
        accounts={args.account: account},
    )

    saved_overview = store.read(args.project, "overview")
    accounts = store.read(args.project, "accounts")
    gate = classify_gate(saved_overview, accounts)
    directive = select_branch(saved_overview)
    candidate = select_recent_usable_account(accounts)
    stored = (accounts or {}).get(args.account) or {}
    token = ((stored.get("tokens") or {}).get("JSESSIONID") or {}).get("value")
    cookie_names = sorted(
        c.get("name") for c in (stored.get("snapshot") or {}).get("cookies") or []
        if isinstance(c, dict)
    )
    skill_text = SkillStore(root_dir=args.skills_root).read(
        "authn", project_id=args.project)
    skill_session = "wj-gateway-e2e" in skill_text
    skill_history = "history mode" in skill_text

    print("seed_project", args.project)
    print("seed_account", args.account)
    print("seed_skill", skill_dst)
    print("gate", gate)
    print("directive", directive)
    print("candidate", candidate)
    print("account_status", stored.get("status"))
    print("token_present", bool(token))
    print("snapshot_cookie_names", ",".join(cookie_names))
    print("snapshot_captured_at", (stored.get("snapshot") or {}).get("captured_at"))
    print("skill_loaded_chars", len(skill_text))
    print("skill_has_live_session", skill_session)
    print("skill_has_history_route_note", skill_history)

    if gate != "run_loop":
        print("FAIL: expected gate run_loop", file=sys.stderr)
        return 1
    if directive != "browser_only":
        print("FAIL: expected directive browser_only", file=sys.stderr)
        return 1
    if candidate != args.account:
        print("FAIL: expected the seeded account as candidate", file=sys.stderr)
        return 1
    if not token:
        print("FAIL: token was not stored", file=sys.stderr)
        return 1
    if not skill_session or not skill_history:
        print("FAIL: project skill did not load as the browser fixture", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
