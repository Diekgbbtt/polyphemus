#!/usr/bin/env python3
"""Repeatable runtime-state scenarios for the Steel tool stack.

The runner drives the live Kali MCP server from the agent container. It covers
the failure families found in the runtime stress campaigns:

* shell composition that hides a Steel invocation from the MCP string gate;
* the compatibility ``steel-real`` name, which must route through the wrapper;
* a masked Steel failure behind ``2>/dev/null || true`` and a pipe;
* a second-command failure in a multi-command shell;
* a known live session that disappears (session loss vs typo);
* a timed-out command that leaves a background child in the Kali container;
* the catalogue fact recorded in the guard trace.

Acceptance is exact. Every composition must return the declared error code and
the policy return code 2, create no session, and leave the catalogue unchanged.
A masked failure must carry the same code, message, and stderr as the unmasked
command, with the composition's own rc preserved separately.

The session-loss scenario stops the session named by ``--loss-session``.
Prepare that session before the run and re-prepare it afterwards.
Every other scenario uses names unique to this run, so a persisted session
registry cannot turn a typo into a false session-loss.

The output is one JSON document. Cookie values never reach it.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from pathlib import Path

from langchain_mcp_adapters.client import MultiServerMCPClient

RUN_ID = f"{int(time.time())}-{os.getpid()}"


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


def _typo(label: str) -> str:
    return f"wj-sc-{RUN_ID}-{label}"


async def _composition_scenarios(tools) -> list[dict]:
    # (label, tool, session, arguments, expected error code, expected shell rc,
    #  expected gate). "mcp_precheck" means the whole command was refused
    #  before the shell ran; "binary_guard" means the shell ran and the guard
    #  refused the embedded Steel invocation.
    cases = [
        ("script", "steel_exec", _typo("script"), {
            "script": f'steel browser eval "1" --session {_typo("script")} --json',
            "script_lang": "sh",
        }, "unknown_session", 2, "binary_guard"),
        ("bash_c", "execute_command", _typo("bash"), {
            "command": (
                "bash -c 'steel browser eval \"1\" --session "
                f"{_typo('bash')} --json'"
            ),
        }, "unknown_session", 2, "binary_guard"),
        ("env", "execute_command", _typo("env"), {
            "command": (
                f'env steel browser eval "1" --session {_typo("env")} --json'
            ),
        }, "unknown_session", 2, "binary_guard"),
        ("command", "execute_command", _typo("command"), {
            "command": (
                f'command steel browser eval "1" --session '
                f'{_typo("command")} --json'
            ),
        }, "unknown_session", 2, "binary_guard"),
        ("sh_c", "execute_command", _typo("sh"), {
            "command": (
                "sh -c 'steel browser eval \"1\" --session "
                f"{_typo('sh')} --json'"
            ),
        }, "unknown_session", 2, "binary_guard"),
        ("path_prefix", "execute_command", _typo("path"), {
            "command": (
                f'PATH=/opt/localbin:$PATH steel browser eval "1" '
                f'--session {_typo("path")} --json'
            ),
        }, "unknown_session", 2, "binary_guard"),
        ("absolute", "execute_command", _typo("abs"), {
            "command": (
                f'/opt/localbin/steel browser eval "1" --session '
                f'{_typo("abs")} --json'
            ),
        }, "unknown_session", 2, "mcp_precheck"),
        ("xargs", "execute_command", _typo("xargs"), {
            "command": (
                f"printf {_typo('xargs')} | xargs -I{{}} steel browser "
                'eval "1" --session {} --json'
            ),
        }, "unknown_session", 123, "binary_guard"),
        ("shell_continue", "execute_command", _typo("cont"), {
            "command": (
                f'echo pre; steel browser eval "1" --session '
                f'{_typo("cont")} --json; echo post'
            ),
        }, "unknown_session", 2, "mcp_precheck"),
        # The public compatibility name must route through the wrapper. A
        # nested shell is the shape that bypassed the old string gate.
        ("steel_real_direct", "execute_command", _typo("reald"), {
            "command": (
                f'steel-real browser eval "1" --session '
                f'{_typo("reald")} --json'
            ),
        }, "unknown_session", 2, "mcp_precheck"),
        ("steel_real_bash", "execute_command", _typo("realb"), {
            "command": (
                "bash -c 'steel-real browser eval \"1\" --session "
                f"{_typo('realb')} --json'"
            ),
        }, "unknown_session", 2, "binary_guard"),
        ("steel_real_absolute", "execute_command", _typo("reala"), {
            "command": (
                f'/opt/localbin/steel-real browser eval "1" --session '
                f'{_typo("reala")} --json'
            ),
        }, "unknown_session", 2, "mcp_precheck"),
    ]
    records = []
    for label, tool, case_session, args, expected, shell_expected, gate in cases:
        args = dict(args)
        args["session_id"] = f"scenario-{label}"
        args["timeout_s"] = 60
        out = await _call(tools, tool, args)
        live = await _sessions(tools)
        # Scope the assertion to THIS case's session. A separately prepared
        # loss fixture is live on purpose and is not a stray.
        strays = [case_session] if case_session in live else []
        error = out.get("error") or {}
        events = out.get("steel_events") or []
        observed = {
            "error": error.get("code"),
            "returncode": out.get("returncode"),
            "shell_returncode": out.get("shell_returncode"),
            "strays": strays,
            "events": len(events),
            "gate": "mcp_precheck" if not events else "binary_guard",
            "stdout": str(out.get("stdout") or "")[:80],
            "expected_shell_returncode": shell_expected,
            "expected_gate": gate,
        }
        passed = (
            error.get("code") == expected
            and out.get("returncode") == 2
            and out.get("shell_returncode", out.get("returncode"))
            == shell_expected
            and observed["gate"] == gate
            and not strays
            and (gate == "binary_guard" or not observed["stdout"])
        )
        records.append(_record(
            f"composition/{label}",
            passed,
            f"{expected} with policy rc 2 and shell rc {shell_expected}, "
            f"caught by {gate}, and no stray session",
            observed,
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
    command = f"steel browser get text --session {session} --json"
    direct = await _call(tools, "steel_exec", {
        "command": command,
        "session_id": "scenario-direct",
        "timeout_s": 60,
    })
    masked = await _call(tools, "execute_command", {
        "command": f"{command} 2>/dev/null || true",
        "session_id": "scenario-masked",
        "timeout_s": 60,
    })
    multiple = await _call(tools, "execute_command", {
        "command": f"echo pre; {command}; echo post",
        "session_id": "scenario-multi",
        "timeout_s": 60,
    })
    direct_error = direct.get("error") or {}
    masked_error = masked.get("error") or {}
    multiple_error = multiple.get("error") or {}
    same_error = (
        direct_error.get("code")
        and direct_error.get("code") == masked_error.get("code")
        and direct_error.get("message") == masked_error.get("message")
        and str(direct.get("stderr") or "").strip()
        == str(masked.get("stderr") or "").strip()
    )
    records = [
        _record(
            "masked/output_suppression",
            bool(same_error)
            and masked.get("returncode") == direct.get("returncode") == 2
            and masked.get("shell_returncode") == 0,
            "same code, message, stderr, and rc as the unmasked failure; "
            "the masked shell rc is preserved separately",
            {
                "direct": {
                    "error": direct_error.get("code"),
                    "returncode": direct.get("returncode"),
                    "shell_returncode": direct.get("shell_returncode"),
                },
                "masked": {
                    "error": masked_error.get("code"),
                    "returncode": masked.get("returncode"),
                    "shell_returncode": masked.get("shell_returncode"),
                },
                "same_error": bool(same_error),
            },
        ),
        _record(
            "masked/second_command",
            multiple_error.get("code") == direct_error.get("code")
            and multiple.get("returncode") == 2
            and multiple.get("shell_returncode") == 0
            and "pre" in str(multiple.get("stdout") or "")
            and "post" in str(multiple.get("stdout") or ""),
            "the second command's failure is reported with rc 2 while both "
            "printable commands still ran",
            {
                "error": multiple_error.get("code"),
                "returncode": multiple.get("returncode"),
                "shell_returncode": multiple.get("shell_returncode"),
                "stdout": str(multiple.get("stdout") or "")[:120],
            },
        ),
    ]
    return records


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
        and gone.get("returncode") == 2
    )
    return [_record(
        "session_loss/known_session_disappears",
        passed,
        "known live -> stopped -> session_missing + recreate_session + rc 2",
        {"live_returncode": live_cmd.get("returncode"),
         "stop_returncode": stop.get("returncode"),
         "error": error.get("code"), "fatal": error.get("fatal"),
         "recovery": (error.get("recovery") or {}).get("action"),
         "returncode": gone.get("returncode")},
    )]


async def _start_loss_scenario(tools, core: str | None) -> list[dict]:
    """A session created through the tool, then stopped without a catalogue
    query. The creation record must make the loss a session_missing, not a
    typo."""
    if not core:
        return [_record(
            "session_lifecycle/start_then_loss",
            True,
            "a private core path was provided",
            {"skipped": "no --private-core"},
        )]
    name = _typo("startloss")
    start = await _call(tools, "steel_exec", {
        "command": (
            f"steel browser start --session {name} "
            "--session-timeout 60000 --inactivity-timeout 86400000 --json"
        ),
        "session_id": "scenario-startloss",
        "timeout_s": 60,
    })
    stop = await _call(tools, "execute_command", {
        "command": (
            f"bash -c '{core} --local browser stop --session {name} --json'"
        ),
        "session_id": "scenario-startloss",
        "timeout_s": 60,
    })
    lost = await _call(tools, "steel_exec", {
        "command": f'steel browser eval "1" --session {name} --json',
        "session_id": "scenario-startloss",
        "timeout_s": 30,
    })
    error = lost.get("error") or {}
    passed = (
        start.get("returncode") == 0
        and start.get("steel_events")
        and stop.get("returncode") == 0
        and error.get("code") == "session_missing"
        and error.get("fatal") is True
        and (error.get("recovery") or {}).get("action") == "recreate_session"
        and (error.get("recovery") or {}).get("requires_state_restore") is True
    )
    return [_record(
        "session_lifecycle/start_then_loss",
        passed,
        "start recorded -> catalogue-invisible stop -> session_missing "
        "with state restore",
        {
            "start_returncode": start.get("returncode"),
            "start_events": len(start.get("steel_events") or []),
            "stop_returncode": stop.get("returncode"),
            "error": error.get("code"),
            "fatal": error.get("fatal"),
            "recovery": (error.get("recovery") or {}).get("action"),
            "requires_state_restore": (
                (error.get("recovery") or {}).get("requires_state_restore")
            ),
        },
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


async def _catalogue_scenario(tools) -> list[dict]:
    out = await _call(tools, "steel_exec", {
        "command": "steel browser sessions --json",
        "session_id": "scenario-catalogue",
        "timeout_s": 30,
    })
    events = out.get("steel_events") or []
    catalogue = events[0].get("catalogue") if events else None
    return [_record(
        "trace/catalogue_fact",
        catalogue == "not-required",
        "a sessions command that needs no catalogue records not-required, "
        "never unavailable",
        {"catalogue": catalogue, "returncode": out.get("returncode")},
    )]


async def _private_core_probe(tools, core: str | None) -> dict | None:
    """Record, do not hide, the residual filesystem-level bypass.

    A deliberate absolute path to the private real CLI is outside the
    name-resolution boundary this stack can enforce without OS isolation. The
    probe proves whether the limit is still present and cleans any session it
    created.
    """
    if not core:
        return None
    name = _typo("private")
    before = await _sessions(tools)
    out = await _call(tools, "execute_command", {
        "command": (
            f"bash -c '{core} browser eval \"1\" --session {name} --json'"
        ),
        "session_id": "scenario-private",
        "timeout_s": 60,
    })
    after = await _sessions(tools)
    created = sorted(after - before)
    for stray in created:
        await _call(tools, "steel_exec", {
            "command": f"steel browser stop --session {stray} --json",
            "session_id": "scenario-cleanup",
            "timeout_s": 30,
        })
    return {
        "limit": "private-core absolute path",
        "path": core,
        "error": (out.get("error") or {}).get("code"),
        "returncode": out.get("returncode"),
        "created": created,
        "cleaned": bool(created),
        "scope": "requires knowing the private path; not reachable by any "
                 "public name or PATH lookup",
    }


async def run(args: argparse.Namespace) -> int:
    client = MultiServerMCPClient(
        {"kali": {"url": args.mcp_url, "transport": "streamable_http"}})
    tools = {tool.name: tool for tool in await client.get_tools()}

    records: list[dict] = []
    records.extend(await _composition_scenarios(tools))
    records.extend(await _masked_scenarios(tools, args.session))
    records.extend(await _session_loss_scenarios(tools, args.loss_session))
    records.extend(await _start_loss_scenario(tools, args.private_core))
    records.extend(await _timeout_scenarios(tools))
    records.extend(await _catalogue_scenario(tools))
    limit = await _private_core_probe(tools, args.private_core)

    passed = all(record["pass"] for record in records)
    summary = {
        "run_id": RUN_ID,
        "mcp_url": args.mcp_url,
        "session": args.session,
        "loss_session": args.loss_session,
        "passed": passed,
        "scenarios": records,
        "known_limits": [limit] if limit else [],
    }
    args.evidence_dir.mkdir(parents=True, exist_ok=True)
    (args.evidence_dir / "runtime-scenarios.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if passed else 1


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--session", default=None,
                        help="live session for the masked-failure scenarios")
    parser.add_argument("--loss-session", default=None,
                        help="prepared session the loss scenario may stop")
    parser.add_argument("--private-core", default=None,
                        help="private real CLI path, for the residual-limit probe")
    parser.add_argument("--evidence-dir", type=Path,
                        default=Path("/tmp/polymerhus-e2e/evidence"))
    parser.add_argument("--mcp-url", default=os.environ.get(
        "KALI_MCP_URL", "http://kali:8001/mcp"))
    return parser


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run(_parser().parse_args())))
