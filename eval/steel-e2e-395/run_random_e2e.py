#!/usr/bin/env python3
"""Run the random browser explorer (E4) on a live Steel session.

The controller first sweeps the real history-mode routes deterministically, then
runs a real `create_agent` loop with `chat_model_for("crawler")` and the Kali
MCP tools. The session is prepared outside this script and stopped at the end.
Cookie values never reach the evidence.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import traceback
from pathlib import Path

from langchain.agents import create_agent
from langchain_core.messages import HumanMessage
from langchain_mcp_adapters.client import MultiServerMCPClient
from langgraph.checkpoint.memory import InMemorySaver

from polymerhus.app.llm.roles import chat_model_for


ROUTES = [
    "/",
    "/index",
    "/home",
    "/jotter",
    "/jotter/article",
    "/library",
    "/login",
    "/register",
    "/admin",
    "/admin/dashboard",
    "/admin/content/editor",
]
BASE = "http://t-1618c524.target"

SYSTEM = """You are a browser exploration agent for a live white-jotter instance.
A Steel session named {session} is already live and authenticated. NEVER start,
stop, restart, or replace it. The browser session name is always in the CLI
command via --session {session}.

Tool rules:
- Use the steel_exec tool for browser commands. Always pass session_id="{workspace}".
- Use execute_command only for shell-side checks; pass session_id="{workspace}".
- Use `steel browser navigate <url> --wait-until domcontentloaded --session {session} --json`.
- Use `steel browser snapshot -i --session {session} --json` for page content.
- Use `steel browser get url --session {session} --json` for the final URL.
- Do not run alert(), do not print cookie values, and do not submit destructive changes.

A deterministic route sweep already covered these routes:
{routes}

Do not repeat the full sweep. Focus on interactive features:
- /admin/dashboard: exercise the users, content, and system menu entries and one
  table search or filter control.
- /jotter: open an article link and read the article body.
- /library: use one category menu entry and the search box.
- /admin/content/editor: type a non-destructive title and body; do not publish.

Use at most 16 tool calls in total. After the interactive checks, stop calling
tools and return the concise final report: one line per exercised page with its
final URL, title, the feature you exercised, and any failure. Then list the
distinct UI features you triggered."""


def _redact(text: str, secrets: list[str]) -> str:
    out = text
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
        return {"success": False, "data": None, "raw": stdout[:400]}


def _plain(value):
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if hasattr(value, "model_dump"):
        try:
            return _plain(value.model_dump())
        except Exception:
            pass
    return str(value)


def _tool_calls(messages) -> list[dict]:
    out = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        for call in message.get("tool_calls") or []:
            if not isinstance(call, dict):
                continue
            args = call.get("args")
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except ValueError:
                    args = {}
            if not isinstance(args, dict):
                args = {}
            out.append({"name": call.get("name"), "args": _plain(args)})
    return out


async def _sweep(tools, args, secrets):
    records = []
    for route in ROUTES:
        url = BASE + route
        nav_cmd = (f"steel browser navigate {url} --wait-until domcontentloaded "
                   f"--session {args.session} --json")
        try:
            result = await asyncio.wait_for(
                tools["steel_exec"].ainvoke({
                    "command": nav_cmd, "session_id": "random",
                    "timeout_s": 120}),
                timeout=150)
            text = result[0]["text"] if isinstance(result, list) else str(result)
            env = _envelope(text)
            data = (_inner(env).get("data") or {})
        except Exception as exc:
            records.append({"route": route, "url": url, "error": f"{type(exc).__name__}: {exc}"})
            continue
        snap_cmd = (f"steel browser snapshot -i --session {args.session} --json")
        try:
            snap = await asyncio.wait_for(
                tools["steel_exec"].ainvoke({
                    "command": snap_cmd, "session_id": "random",
                    "timeout_s": 120}),
                timeout=150)
            snap_text = snap[0]["text"] if isinstance(snap, list) else str(snap)
            snap_env = _envelope(snap_text)
            snap_data = _inner(snap_env).get("data") or ""
            snap_str = snap_data if isinstance(snap_data, str) else json.dumps(snap_data, ensure_ascii=False)
        except Exception:
            snap_str = ""
        records.append({
            "route": route,
            "requested_url": url,
            "final_url": data.get("url") if isinstance(data, dict) else None,
            "title": data.get("title") if isinstance(data, dict) else None,
            "snapshot_chars": len(snap_str),
            "snapshot_preview": _redact(snap_str[:500], secrets),
        })
    return records

async def _sessions(tools, workspace: str) -> list[str]:
    result = await asyncio.wait_for(
        tools["steel_exec"].ainvoke({
            "command": "steel browser sessions --json",
            "session_id": workspace,
            "timeout_s": 60,
        }),
        timeout=90)
    text = result[0]["text"] if isinstance(result, list) else str(result)
    data = (_inner(_envelope(text)).get("data") or [])
    return [str(item.get("name")) for item in data if isinstance(item, dict)]


async def run(args: argparse.Namespace) -> int:
    payload = json.loads(args.session_json.read_text(encoding="utf-8"))
    secrets = [
        str(payload.get("JSESSIONID") or "").strip(),
        str(payload.get("rememberMe") or "").strip(),
    ]
    secrets = [s for s in secrets if s]

    client = MultiServerMCPClient(
        {"kali": {"url": args.mcp_url, "transport": "streamable_http"}})
    mcp_tools = {tool.name: tool for tool in await client.get_tools()}
    tools = [mcp_tools["steel_exec"], mcp_tools["execute_command"]]

    live_before = await _sessions(mcp_tools, "random")
    if args.session not in live_before:
        print(json.dumps({"error": f"session {args.session} is not live",
                          "sessions": live_before}, ensure_ascii=False))
        return 1

    sweep = await _sweep(mcp_tools, args, secrets)

    model = chat_model_for("crawler")
    agent = create_agent(
        model,
        tools=tools,
        system_prompt=SYSTEM.format(
            session=args.session,
            workspace="random",
            routes="\n".join(f"- {route}" for route in ROUTES),
        ),
        checkpointer=InMemorySaver(),
    )
    thread_id = "steel-e2e-395-random"
    task = (
        "Exercise the interactive features on the prepared white-jotter "
        "session: the admin dashboard menus and a table filter, an article on "
        "/jotter, the library category filter and search box, and a "
        "non-destructive title/body in /admin/content/editor. The route sweep "
        "is already done, so do not repeat it. Use at most 16 tool calls, then "
        "stop and return the concise report. Do not start or stop the session."
    )
    result = None
    error = None
    try:
        result = await asyncio.wait_for(
            agent.ainvoke(
                {"messages": [HumanMessage(content=task)]},
                config={
                    "recursion_limit": 120,
                    "configurable": {"thread_id": thread_id},
                },
            ),
            timeout=args.timeout,
        )
    except Exception:
        error = traceback.format_exc()

    if result is None:
        try:
            state = await agent.aget_state(
                {"configurable": {"thread_id": thread_id}})
            values = getattr(state, "values", None) or {}
            result = {"messages": values.get("messages") or []}
        except Exception:
            result = None

    messages = _plain((result or {}).get("messages") or [])
    calls = _tool_calls(messages)
    tool_names = [str(call.get("name")) for call in calls]
    steel_commands = [
        str((call.get("args") or {}).get("command")
            or (call.get("args") or {}).get("script") or "")
        for call in calls
        if call.get("name") == "steel_exec"
    ]
    final_text = ""
    for message in reversed(messages):
        if isinstance(message, dict) and message.get("type") == "ai":
            content = message.get("content")
            if isinstance(content, str) and content.strip():
                final_text = content
                break
    result_json = json.dumps(result, ensure_ascii=False, default=str)
    secret_leak = any(secret in result_json for secret in secrets)
    result_redacted = _redact(result_json, secrets)

    stop_env = None
    try:
        stop_res = await asyncio.wait_for(
            mcp_tools["steel_exec"].ainvoke({
                "command": f"steel browser stop --session {args.session} --json",
                "session_id": "random",
                "timeout_s": 60,
            }),
            timeout=90)
        stop_text = stop_res[0]["text"] if isinstance(stop_res, list) else str(stop_res)
        stop_env = _envelope(stop_text)
    except Exception as exc:
        stop_env = {"success": False, "error": f"{type(exc).__name__}: {exc}"}
    live_after = await _sessions(mcp_tools, "random")
    session_stopped = args.session not in live_after

    args.evidence_dir.mkdir(parents=True, exist_ok=True)
    (args.evidence_dir / "random-sweep.json").write_text(
        _redact(json.dumps(sweep, ensure_ascii=False, indent=2), secrets),
        encoding="utf-8")
    (args.evidence_dir / "random-result.json").write_text(
        result_redacted, encoding="utf-8")

    summary = {
        "session": args.session,
        "model": os.environ.get("LLM_CRAWLER"),
        "routes": ROUTES,
        "sweep_count": len(sweep),
        "sweep": sweep,
        "sweep_titles": {
            record.get("route"): record.get("title")
            for record in sweep if record.get("title")
        },
        "sweep_redirects": {
            record.get("route"): record.get("final_url")
            for record in sweep
            if record.get("final_url")
            and record.get("final_url") != record.get("requested_url")
        },
        "agent_tool_calls": len(calls),
        "agent_tool_names": tool_names,
        "agent_steel_commands": steel_commands,
        "agent_final_chars": len(final_text),
        "agent_final_preview": _redact(final_text[:2000], secrets),
        "agent_error": _redact(error, secrets) if error else None,
        "secret_leak": secret_leak,
        "session_live_before": args.session in live_before,
        "session_stopped": session_stopped,
        "session_live_after": args.session in live_after,
        "stop_returncode": (stop_env or {}).get("returncode"),
        "ok": bool(
            error is None
            and len(sweep) == len(ROUTES)
            and calls
            and final_text.strip()
            and session_stopped
        ),
    }
    (args.evidence_dir / "random-summary.json").write_text(
        _redact(json.dumps(summary, ensure_ascii=False, indent=2), secrets),
        encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["ok"] else 1


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--session", default="wj-random-e2e")
    parser.add_argument("--session-json", required=True, type=Path)
    parser.add_argument("--evidence-dir", type=Path,
                        default=Path("/tmp/polymerhus-e2e/evidence"))
    parser.add_argument("--mcp-url", default=os.environ.get(
        "KALI_MCP_URL", "http://kali:8001/mcp"))
    parser.add_argument("--timeout", type=int, default=900)
    return parser


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run(_parser().parse_args())))

