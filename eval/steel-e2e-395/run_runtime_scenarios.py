#!/usr/bin/env python3
"""Repeatable runtime-state scenarios for the Steel tool stack.

The runner drives the live Kali MCP server from the agent container. It covers
the failure families found in the runtime stress campaign:

* shell composition that hides a Steel invocation from the MCP string gate;
* a masked Steel failure behind ``2>/dev/null || true`` and a pipe;
* a second-command failure in a multi-command shell;
* a known live session that disappears (session loss vs typo);
* a timed-out command that leaves a background child in the Kali container.

The session-loss scenario stops the session named by ``--loss-session``.
Prepare that session before the run and re-prepare it afterwards. Every other
scenario uses unique names and cleans any stray it creates.

The output is one JSON document. Cookie values never reach it.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

from langchain_mcp_adapters.client import MultiServerMCPClient


def _parse(result) -> dict:
    text = result[0]["text"] if isinstance(result, list) else str(result)
    try:
        value = json.loads(text)
    except ValueError:
        return {"raw": text[:1000]}
    return value if isinstance(value, dict) else {"raw": text[:1000]}


async def _sessions(tools) -> set[str]:
    result = await tools["steel_exec"].ainvoke({
        "command": "steel browser sessions --json",
        "session_id": "scenario-sessions",
        "timeout_s": 30,
    })
    envelope = _parse(result)
    try:
        data = json.loads(envelope.get("stdout") or "{}").get("data") or []
    except ValueError:
        return set()
    return {
        str(item.get("name")) for item in data if isinstance(item, dict)
    }


async def _call(tools, name: str, args: dict) -> dict:
    return _parse(await tools[name].ainvoke(args))


def _record(name: str, passed: bool, expected: str, observed: dict) -> dict:
    return {
        "scenario": name,
        "pass": passed,
        "expected": expected,
        "observed": observed,
    }


async def _composition_scenarios(tools) -> list[dict]:
    cases = [
        ("script", "steel_exec", "wj-scenario-script", {
            "script": 'steel browser eval "1" --session wj-scenario-script --json',
            "script_lang": "sh",
        }),
        ("bash_c", "execute_command", "wj-scenario-bash", {
            "command": "bash -c 'steel browser eval \"1\" --session wj-scenario-bash --json'",
        }),
        ("env", "execute_command", "wj-scenario-env", {
            "command": 'env steel browser eval "1" --session wj-scenario-env --json',
        }),
        ("command", "execute_command", "wj-scenario-command", {
            "command": 'command steel browser eval "1" --session wj-scenario-command --json',
        }),
        ("sh_c", "execute_command", "wj-scenario-sh", {
            "command": "sh -c 'steel browser eval \"1\" --session wj-scenario-sh --json'",
        }),
        ("path_prefix", "execute_command", "wj-scenario-path", {
            "command": 'PATH=/opt/localbin:$PATH steel browser eval "1" --session wj-scenario-path --json',
        }),
        ("absolute", "execute_command", "wj-scenario-abs", {
            "command": '/opt/localbin/steel browser eval "1" --session wj-scenario-abs --json',
        }),
        ("xargs", "execute_command", "wj-scenario-xargs", {
            "command": "printf wj-scenario-xargs | xargs -I{} steel browser eval \"1\" --session {} --json",
        }),
        ("shell_continue", "execute_command", "wj-scenario-cont", {
            "command": 'echo pre; steel browser eval "1" --session wj-scenario-cont --json; echo post',
        }),
    ]
    records = []
    for label, tool, case_session, args in cases:
        args = dict(args)
        args["session_id"] = f"scenario-{label}"
        args["timeout_s"] = 60
        out = await _call(tools, tool, args)
        live = await _sessions(tools)
        # Scope the assertion to THIS case's session. A separately prepared
        # loss fixture is live on purpose and is not a stray.
        strays = [case_session] if case_session in live else []
        error = (out.get("error") or {}).get("code")
        passed = not strays and error in {"unknown_session", "session_missing"}
        records.append(_record(
            f"composition/{label}",
            passed,
            "no execution without a live session; no stray session",
            {"error": error, "returncode": out.get("returncode"),
             "strays": strays,
             "events": len(out.get("steel_events") or [])},
        ))
        for name in strays:
            await _call(tools, "steel_exec", {
                "command": f"steel browser stop --session {name} --json",
                "session_id": "scenario-cleanup",
                "timeout_s": 30,
            })
    return records


async def _masked_scenarios(tools, session: str | None) -> list[dict]:
    if not session:
        return [_record("masked/skipped", True, "a live session was provided",
                        {"skipped": "no --session"})]
    live = await _sessions(tools)
    if session not in live:
        return [_record(
            "masked/precondition",
            False,
            f"{session} is live before the masked-failure scenarios",
            {"sessions": sorted(live)},
        )]
    masked = await _call(tools, "execute_command", {
        "command": (f"steel browser get text --session {session} --json "
                    "2>/dev/null || true"),
        "session_id": "scenario-masked",
        "timeout_s": 60,
    })
    masked_error = (masked.get("error") or {}).get("code")
    masked_ok = masked_error in {"invalid_command", "cli_error"}
    multiple = await _call(tools, "execute_command", {
        "command": (f"echo pre; steel browser get text --session {session} "
                    "--json; echo post"),
        "session_id": "scenario-multi",
        "timeout_s": 60,
    })
    multiple_error = (multiple.get("error") or {}).get("code")
    multiple_ok = multiple_error in {"invalid_command", "cli_error"}
    return [
        _record(
            "masked/output_suppression",
            masked_ok,
            "the guard trace reports the hidden CLI failure",
            {"error": masked_error, "returncode": masked.get("returncode"),
             "stderr": str(masked.get("stderr") or "")[:160]},
        ),
        _record(
            "masked/second_command",
            multiple_ok,
            "the guard trace reports the second command's failure",
            {"error": multiple_error, "returncode": multiple.get("returncode"),
             "stdout": str(multiple.get("stdout") or "")[:160]},
        ),
    ]


async def _session_loss_scenarios(tools, session: str | None) -> list[dict]:
    if not session:
        return [_record("session_loss/skipped", True,
                        "a prepared --loss-session was provided",
                        {"skipped": "no --loss-session"})]
    live_before = await _sessions(tools)
    if session not in live_before:
        return [_record("session_loss/precondition", False,
                        f"{session} is live before the scenario",
                        {"sessions": sorted(live_before)})]
    live_cmd = await _call(tools, "steel_exec", {
        "command": f"steel browser get url --session {session} --json",
        "session_id": "scenario-loss",
        "timeout_s": 30,
    })
    stop = await _call(tools, "steel_exec", {
        "command": f"steel browser stop --session {session} --json",
        "session_id": "scenario-loss",
        "timeout_s": 30,
    })
    gone = await _call(tools, "steel_exec", {
        "command": f'steel browser eval "1" --session {session} --json',
        "session_id": "scenario-loss",
        "timeout_s": 30,
    })
    error = gone.get("error") or {}
    passed = (
        live_cmd.get("returncode") == 0
        and stop.get("returncode") == 0
        and error.get("code") == "session_missing"
        and error.get("fatal") is True
        and (error.get("recovery") or {}).get("action") == "recreate_session"
    )
    return [_record(
        "session_loss/known_session_disappears",
        passed,
        "known live -> stopped -> session_missing + recreate_session",
        {"live_returncode": live_cmd.get("returncode"),
         "stop_returncode": stop.get("returncode"),
         "error": error.get("code"), "fatal": error.get("fatal"),
         "recovery": (error.get("recovery") or {}).get("action")},
    )]


async def _timeout_scenarios(tools) -> list[dict]:
    marker = "311"
    started = await _call(tools, "execute_command", {
        "command": f"bash -c 'sleep {marker} & wait'",
        "session_id": "scenario-timeout",
        "timeout_s": 2,
    })
    scan = await _call(tools, "execute_command", {
        "command": (
            "for p in /proc/[0-9]*; do "
            "if [ \"$(cat $p/comm 2>/dev/null)\" = sleep ] && "
            f"tr '\\0' ' ' < $p/cmdline 2>/dev/null | grep -q '^sleep {marker} '; "
            "then echo LEAK; fi; done"
        ),
        "session_id": "scenario-timeout",
        "timeout_s": 30,
    })
    leaked = "LEAK" in str(scan.get("stdout") or "")
    passed = started.get("returncode") == 124 and not leaked
    return [_record(
        "timeout/background_child_cleanup",
        passed,
        "timeout is 124 and the background child is gone",
        {"returncode": started.get("returncode"),
         "stderr": str(started.get("stderr") or "")[:120],
         "leaked": leaked},
    )]


async def run(args: argparse.Namespace) -> int:
    client = MultiServerMCPClient(
        {"kali": {"url": args.mcp_url, "transport": "streamable_http"}})
    tools = {tool.name: tool for tool in await client.get_tools()}

    records: list[dict] = []
    records.extend(await _composition_scenarios(tools))
    records.extend(await _masked_scenarios(tools, args.session))
    records.extend(await _session_loss_scenarios(tools, args.loss_session))
    records.extend(await _timeout_scenarios(tools))

    passed = all(record["pass"] for record in records)
    summary = {
        "mcp_url": args.mcp_url,
        "session": args.session,
        "loss_session": args.loss_session,
        "passed": passed,
        "scenarios": records,
    }
    args.evidence_dir.mkdir(parents=True, exist_ok=True)
    (args.evidence_dir / "runtime-scenarios.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if passed else 1


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--session", default="wj-gateway-e2e",
                        help="live session for the masked-failure scenarios")
    parser.add_argument("--loss-session", default=None,
                        help="prepared session the loss scenario may stop")
    parser.add_argument("--evidence-dir", type=Path,
                        default=Path("/tmp/polymerhus-e2e/evidence"))
    parser.add_argument("--mcp-url", default=os.environ.get(
        "KALI_MCP_URL", "http://kali:8001/mcp"))
    return parser


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run(_parser().parse_args())))
