#!/usr/bin/env python3
"""Run the production auth gateway (E2) against the live Steel session.

The fixture, the account, and the live session already exist. This controller
runs `ReconOrchestratorActor.run_gateway` with the real role model, the real
Kali MCP tool surface, a Postgres checkpointer, and the project auth and skill
stores. It captures the verdict, the loop state, the status write, the skill
write, and the checkpoint trace. Cookie values never reach the evidence.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

from langchain_core.messages import BaseMessage
from langchain_mcp_adapters.client import MultiServerMCPClient
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from polymerhus.app.auth.records import select_recent_usable_account
from polymerhus.app.auth.store import AuthStore
from polymerhus.app.config import config
from polymerhus.app.llm.checkpoints import checkpoint_serde
from polymerhus.app.llm.skills import SkillStore
from polymerhus.recon.control.authn_loop import classify_gate, select_branch
from polymerhus.recon.control.orchestrator_agent import (
    GatewayStop,
    ReconOrchestratorActor,
)


def _redact(text: str, secrets: list[str]) -> str:
    out = text
    for secret in secrets:
        if secret:
            out = out.replace(secret, "<redacted>")
    return out


def _plain(value):
    """JSON-safe projection of LangGraph state (messages keep tool calls)."""
    if isinstance(value, BaseMessage):
        try:
            return value.model_dump()
        except Exception:
            return {"type": value.type, "content": str(value)}
    if hasattr(value, "model_dump"):
        try:
            return value.model_dump()
        except Exception:
            pass
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_plain(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return str(value)


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _read_account(store: AuthStore, project: str, account: str) -> dict:
    accounts = store.read(project, "accounts")
    record = (accounts or {}).get(account) if isinstance(accounts, dict) else {}
    if not isinstance(record, dict):
        record = {}
    token = ((record.get("tokens") or {}).get("JSESSIONID") or {}).get("value")
    cookies = ((record.get("snapshot") or {}).get("cookies") or [])
    return {
        "status": record.get("status"),
        "origin": record.get("origin"),
        "updated_at": record.get("updated_at"),
        "token_present": bool(token),
        "snapshot_cookie_names": sorted(
            c.get("name") for c in cookies if isinstance(c, dict)),
    }


def _read_overview(store: AuthStore, project: str) -> dict:
    overview = store.read(project, "overview") or {}
    if not isinstance(overview, dict):
        overview = {}
    return overview


def _trace_tools(trace: dict) -> dict:
    """Extract the model's tool calls from the checkpoint projection."""
    messages = trace.get("messages") or []
    names: list[str] = []
    browser: list[str] = []
    auth_writes: list[dict] = []
    skill_loads: list[str] = []
    skill_writes: list[dict] = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        for call in message.get("tool_calls") or []:
            if not isinstance(call, dict):
                continue
            name = str(call.get("name") or "")
            args = call.get("args") if isinstance(call.get("args"), dict) else {}
            if name:
                names.append(name)
            if name == "steel_exec":
                browser.append(str(args.get("command") or ""))
            elif name == "auth_store" and args.get("command") == "write":
                auth_writes.append({
                    "path": args.get("path"),
                    "value": args.get("value"),
                })
            elif name == "load_skill":
                skill_loads.append(str(args.get("name") or ""))
            elif name == "write_skill":
                skill_writes.append({
                    "skill": args.get("skill"),
                    "target": args.get("target"),
                    "content_chars": len(str(args.get("content") or "")),
                })
    return {
        "tool_names": names,
        "browser_commands": browser,
        "auth_store_writes": auth_writes,
        "skill_loads": skill_loads,
        "skill_writes": skill_writes,
    }

async def _session_live(mcp_url: str, session: str) -> bool:
    """Ask the Steel runtime whether the prepared session still exists."""
    try:
        client = MultiServerMCPClient(
            {"kali": {"url": mcp_url, "transport": "streamable_http"}})
        tools = {tool.name: tool for tool in await client.get_tools()}
        result = await asyncio.wait_for(
            tools["steel_exec"].ainvoke({
                "command": "steel browser sessions --json",
                "session_id": "gateway-post",
                "timeout_s": 60,
            }),
            timeout=90,
        )
        text = result[0]["text"] if isinstance(result, list) else str(result)
        envelope = json.loads(text)
        stdout = envelope.get("stdout") or ""
        inner = json.loads(stdout) if stdout.strip() else {}
        data = inner.get("data") or []
        names = {str(item.get("name")) for item in data
                 if isinstance(item, dict)}
        return session in names
    except Exception:  # noqa: BLE001 - liveness is evidence, not control flow
        return False


def _loop_fields(state: dict) -> dict:
    return {
        "loop_phase": state.get("phase"),
        "loop_observed": state.get("observed"),
        "loop_skill": state.get("skill"),
        "loop_retrieve": state.get("retrieve"),
        "loop_probe": state.get("probe"),
        "loop_validate": state.get("validate"),
        "loop_history": state.get("history"),
        "loop_state": state,
    }

async def run(args: argparse.Namespace) -> int:
    project = args.project
    account = args.account
    payload = json.loads(args.session_json.read_text(encoding="utf-8"))
    secrets = [
        str(payload.get("JSESSIONID") or "").strip(),
        str(payload.get("rememberMe") or "").strip(),
    ]
    secrets = [s for s in secrets if s]

    store = AuthStore(root_dir=args.data_root)
    skill_store = SkillStore(root_dir=args.skills_root)
    skill_before = skill_store.read("authn", project_id=project)
    overview = _read_overview(store, project)
    accounts = store.read(project, "accounts")
    gate = classify_gate(overview, accounts)
    directive = select_branch(overview)
    candidate = select_recent_usable_account(
        accounts if isinstance(accounts, dict) else {})
    expected = {
        "gate": gate,
        "directive": directive,
        "candidate": candidate,
        "account": account,
        "branch": "browser_only",
    }

    run_id = ("steel-e2e-395-gateway-"
              + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    args.evidence_dir.mkdir(parents=True, exist_ok=True)

    actor = None
    verdict = None
    verdict_data = None
    error = None
    loop_state: dict = {}
    thread_id = ""
    raw_trace: dict = {}
    trace_tuple = None
    stop_error = None

    try:
        async with AsyncPostgresSaver.from_conn_string(
                config.POSTGRES_DSN, serde=checkpoint_serde()) as saver:
            await saver.setup()
            actor = ReconOrchestratorActor(
                run_id=run_id,
                project_id=project,
                checkpointer=saver,
                model_factory=None,
                observe=False,
                compaction=False,
                auth_store=store,
                skill_store=skill_store,
                kali_tools=None,
            )
            try:
                verdict = await asyncio.wait_for(
                    actor.run_gateway(project_id=project),
                    timeout=args.timeout,
                )
            except GatewayStop as exc:
                error = f"GatewayStop: {exc}"
            except asyncio.TimeoutError:
                error = f"gateway timeout after {args.timeout}s"
            except Exception:
                error = traceback.format_exc()

            try:
                loop_state = actor.loop_state
            except Exception:
                loop_state = {}
            try:
                thread_id = actor.thread_id
            except Exception:
                thread_id = ""

            if thread_id:
                try:
                    trace_tuple = await saver.aget_tuple(
                        {"configurable": {"thread_id": thread_id}})
                except Exception:
                    trace_tuple = None

            if verdict is not None and hasattr(verdict, "model_dump"):
                verdict_data = verdict.model_dump()
            elif isinstance(verdict, dict):
                verdict_data = verdict

            checkpoint = getattr(trace_tuple, "checkpoint", None) or {}
            if isinstance(checkpoint, dict):
                channel_values = checkpoint.get("channel_values") or {}
                raw_trace = {
                    "thread_id": thread_id,
                    "checkpoint_id": checkpoint.get("id"),
                    "channel_values": _plain(channel_values),
                    "metadata": _plain(getattr(trace_tuple, "metadata", None)),
                }
            else:
                raw_trace = {"thread_id": thread_id, "channel_values": {}}
    finally:
        if actor is not None:
            try:
                await asyncio.wait_for(actor.stop(), timeout=120)
            except Exception as exc:  # noqa: BLE001 - teardown best-effort
                stop_error = f"{type(exc).__name__}: {exc}"

    trace_tools = _trace_tools(raw_trace.get("channel_values") or {})
    messages = (raw_trace.get("channel_values") or {}).get("messages") or []
    trace_json = json.dumps(raw_trace, ensure_ascii=False, default=str)
    trace_secret_leak = any(secret in trace_json for secret in secrets)
    trace_redacted = _redact(trace_json, secrets)

    verdict_json = json.dumps(verdict_data, ensure_ascii=False, default=str)
    verdict_secret_leak = any(secret in verdict_json for secret in secrets)
    verdict_redacted = _redact(verdict_json, secrets)
    verdict_clean = json.loads(verdict_redacted) if verdict_data else None

    account_after = _read_account(store, project, account)
    skill_after = skill_store.read("authn", project_id=project)
    skill_modified = skill_after != skill_before
    session_live = await asyncio.wait_for(
        _session_live(args.mcp_url, args.session), timeout=120)

    expected_status = (
        "valid" if isinstance(verdict_clean, dict)
        and verdict_clean.get("outcome") == "authenticated" else "not_valid"
    )
    status_write_ok = account_after.get("status") == expected_status
    verdict_ok = bool(
        isinstance(verdict_clean, dict)
        and verdict_clean.get("outcome") == "authenticated"
        and verdict_clean.get("account") == account
        and verdict_clean.get("branch") == "browser_only"
        and verdict_clean.get("replayability_resolved") is False
    )
    ok = bool(
        verdict_ok
        and status_write_ok
        and len(messages) > 0
        and session_live
        and error is None
    )

    summary = {
        "run_id": run_id,
        "thread_id": thread_id,
        "project": project,
        "account": account,
        "session": args.session,
        "expected": expected,
        "verdict": verdict_clean,
        "verdict_ok": verdict_ok,
        "verdict_secret_leak": verdict_secret_leak,
        **_loop_fields(loop_state),
        "account_after": account_after,
        "status_write_ok": status_write_ok,
        "overview": {
            "anti_bot": overview.get("anti-bot"),
            "http_client_replayability": overview.get("http-client-replayability"),
            "defences": _plain(overview.get("defences")),
        },
        "skill": {
            "before_chars": len(skill_before),
            "after_chars": len(skill_after),
            "before_hash": _hash(skill_before),
            "after_hash": _hash(skill_after),
            "modified": skill_modified,
        },
        "trace": {
            "messages": len(messages),
            "chars": len(trace_json),
            "secret_leak": trace_secret_leak,
            "redacted": trace_secret_leak,
        },
        "tools": trace_tools,
        "session_live": session_live,
        "stop_error": stop_error,
        "error": _redact(error, secrets) if error else None,
        "ok": ok,
    }

    evidence_trace = args.evidence_dir / "gateway-trace.json"
    evidence_verdict = args.evidence_dir / "gateway-verdict.json"
    evidence_summary = args.evidence_dir / "gateway-summary.json"
    evidence_trace.write_text(trace_redacted, encoding="utf-8")
    evidence_verdict.write_text(verdict_redacted, encoding="utf-8")
    evidence_summary.write_text(
        _redact(json.dumps(summary, ensure_ascii=False, indent=2), secrets),
        encoding="utf-8")

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if ok else 1


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", default="steel-e2e-395")
    parser.add_argument("--account", default="admin-sessiononly-e2e")
    parser.add_argument("--session", default="wj-gateway-e2e")
    parser.add_argument("--session-json", required=True, type=Path)
    parser.add_argument("--data-root", default="/srv/data")
    parser.add_argument("--skills-root", default="/tmp/polymerhus-e2e/skills")
    parser.add_argument("--evidence-dir", type=Path,
                        default=Path("/tmp/polymerhus-e2e/evidence"))
    parser.add_argument("--mcp-url", default=os.environ.get(
        "KALI_MCP_URL", "http://kali:8001/mcp"))
    parser.add_argument("--timeout", type=int, default=1200)
    return parser


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run(_parser().parse_args())))


