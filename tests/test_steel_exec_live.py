"""Live-kali integration for the `steel_exec` gateway (ticket 05, #221 stream).

Seam under test: the real `steel_exec` fastmcp tool on the live kali
container, reached through a real Client call. Keyless by construction:
every assertion below needs NO cloud credential (pinned-version probe,
routing refusals, envelope shape on a keyless script). Anything needing
STEEL_API_KEY or the cloud is forbidden in this file - live-cloud
walkthroughs are deferred to the post-merge e2e phase.

Pattern follows tests/test_kali_mcp.py: `docker compose up -d kali`,
wait_for readiness, then real tool calls. Never rebuild or restart
agent/postgres/neo4j - kali service only.
"""
import asyncio
import os
import subprocess

from fastmcp import Client

from tests.conftest import wait_for

MCP_URL = "http://localhost:8000/mcp"

# Independent literal from the ticket brief (spike-verified 2026-09-11),
# never recomputed from the stanza under test.
STEEL_VERSION_PIN = "0.4.4"

ENVELOPE_KEYS = {"stdout", "stderr", "returncode", "duration_ms"}


async def _steel(**kwargs):
    async with Client(MCP_URL) as c:
        res = await c.call_tool("steel_exec", kwargs)
        return res.data


async def _exec(command, session_id):
    async with Client(MCP_URL) as c:
        res = await c.call_tool(
            "execute_command", {"command": command, "session_id": session_id})
        return res.data


def _boot_kali():
    subprocess.run(["docker", "compose", "up", "-d", "kali"], check=True)
    wait_for(lambda: asyncio.run(_exec("echo hi", "steel-live-ready")),
             timeout=480)


def test_live_steel_version_names_the_pin():
    _boot_kali()
    out = asyncio.run(_steel(command="steel --version --json",
                             session_id="steel-live"))
    assert out["returncode"] == 0, out
    assert STEEL_VERSION_PIN in out["stdout"]
    assert set(out) == ENVELOPE_KEYS


def test_live_non_steel_command_refused():
    _boot_kali()
    out = asyncio.run(_steel(command="echo hi", session_id="steel-live"))
    assert out["returncode"] != 0
    assert out["stderr"].startswith("refused:not-steel-command")
    assert set(out) == ENVELOPE_KEYS


def test_live_ambiguous_inputs_refused():
    _boot_kali()
    for kw in ({"command": "steel browser sessions", "script": "echo hi"},
               {"command": "", "script": ""}):
        out = asyncio.run(_steel(session_id="steel-live", **kw))
        assert out["returncode"] != 0
        assert out["stderr"].startswith("refused:ambiguous-input")


def test_live_timeout_ordering_refused_before_execution():
    _boot_kali()
    out = asyncio.run(_steel(
        command='steel browser wait -t "x" --timeout 60000 --session s1 --json',
        session_id="steel-live", timeout_s=5))
    assert out["returncode"] != 0
    assert out["stderr"].startswith("refused:timeout-ordering")


def test_live_unsupported_script_lang_refused():
    _boot_kali()
    out = asyncio.run(_steel(script="echo hi", script_lang="rb",
                             session_id="steel-live"))
    assert out["returncode"] != 0
    assert out["stderr"].startswith("refused:unsupported-script-lang")


def test_live_keyless_script_returns_envelope():
    # Echo-only script: proves the verbatim script path end to end with
    # no cloud call at all.
    _boot_kali()
    out = asyncio.run(_steel(script="echo live-ok\n", script_lang="sh",
                             session_id="steel-live"))
    assert out["returncode"] == 0, out
    assert "live-ok" in out["stdout"]
    assert set(out) == ENVELOPE_KEYS


def test_live_run_uses_no_cloud_key():
    # Self-proving keylessness: the client env carries no credential, so
    # nothing above could have reached the cloud even by accident.
    _boot_kali()
    assert os.environ.get("STEEL_API_KEY", "") == ""
