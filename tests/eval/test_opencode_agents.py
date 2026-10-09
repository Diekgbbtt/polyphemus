"""The eval harness's opencode agents, driver config, and dispatch contract.

The subagent commands (OPERATOR.md 2.9/2.10/2.12/2.13, E2E-SCAFFOLD.md step 3,
`run-webexploitbench-8.sh`) run `opencode run --agent <role> --dir <checkout>`
and pass every path in the message. Two things must hold for a copied command to
actually dispatch:

1. Each role the harness selects ships as an opencode agent under
   `.opencode/agent/<role>.md` that names its `eval/prompts/*.md` contract and
   pins the eval model. The agent source is tracked, never gitignored: the
   installed `opencode run --agent <role> --dir <dir>` resolves a project agent
   at `<dir>/.opencode/agent/<role>.md`, so an ignored agent is a missing one.
2. Every documented `opencode run` invocation uses only flags the real CLI has
   (`--agent`, `--dir`, ...). The pre-#297 examples used `--prompt`, `--trial`,
   `--out` and friends, which `opencode run` rejects, so the dispatch died on the
   first line.

The primary `eval-orchestrator` agent, the project config that loads its
instructions, and the `eval-monitor.ts` plugin that defines its `eval_monitor`
and `next_target` tools are the same kind of tracked eval-harness source (#342,
D56): `.opencode/opencode.json` names the orchestrator prompt and the plugin by
relative path inside the checkout, so the driver only loads when the source is
committed. `eval/prompts/orchestrator.md` describes an `eval_monitor` tool with no
definition unless the plugin ships.
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
AGENT_DIR = REPO_ROOT / ".opencode" / "agent"

# role agent id -> the contract prompt it must reference.
ROLES = {
    "eval-assessor": "eval/prompts/assessment.md",
    "eval-diagnoser": "eval/prompts/diagnoser.md",
    "eval-aligner": "eval/prompts/alignment.md",
    "eval-surfer": "eval/prompts/surfer.md",
}

EVAL_MODEL = "opencode-go/deepseek-v4.1-flash"

# The driver side of the harness: the primary orchestrator agent, the project
# config that loads its instructions, and the plugin that defines its tools.
DRIVER_AGENT = AGENT_DIR / "eval-orchestrator.md"
OPENCODE_CONFIG = REPO_ROOT / ".opencode" / "opencode.json"
MONITOR_PLUGIN = REPO_ROOT / ".opencode" / "plugin" / "eval-monitor.ts"
ORCHESTRATOR_PROMPT = REPO_ROOT / "eval" / "prompts" / "orchestrator.md"

# The custom tool `eval/prompts/orchestrator.md` names; the plugin must define it.
MONITOR_TOOL = "eval_monitor"

# The flags the installed `opencode run` accepts (`opencode run --help`, 1.18.x).
REAL_RUN_FLAGS = frozenset(
    {
        "--agent",
        "--dir",
        "--model",
        "-m",
        "--format",
        "--file",
        "-f",
        "--continue",
        "-c",
        "--session",
        "-s",
        "--fork",
        "--share",
        "--title",
        "--attach",
        "-p",
        "--password",
        "-u",
        "--username",
        "--port",
        "--variant",
        "--thinking",
        "-i",
        "--interactive",
        "--auto",
        "--command",
        "--print-logs",
        "--log-level",
        "--pure",
        "-h",
        "--help",
    }
)

# The documented dispatch examples: every line that selects a role agent.
DISPATCH_DOCS = (
    REPO_ROOT / "eval" / "OPERATOR.md",
    REPO_ROOT / "eval" / "E2E-SCAFFOLD.md",
    REPO_ROOT / "eval" / "run-webexploitbench-8.sh",
)

_FLAG = re.compile(r"(?<![\w-])(--[a-z][a-z-]*)")
_AGENT = re.compile(r"--agent\s+([\w.-]+)")


def _agent_text(role: str) -> str:
    path = AGENT_DIR / f"{role}.md"
    assert path.is_file(), f"role agent missing: {path}"
    return path.read_text(encoding="utf-8")


def test_role_agent_names_its_contract_prompt() -> None:
    for role, prompt in ROLES.items():
        text = _agent_text(role)
        assert prompt in text, f"{role} must reference {prompt}"


def test_role_agent_pins_the_eval_model_and_mode() -> None:
    for role in ROLES:
        text = _agent_text(role)
        assert "mode: all" in text, role
        assert f"model: {EVAL_MODEL}" in text, role


def test_every_role_contract_prompt_exists() -> None:
    for role, prompt in ROLES.items():
        assert (REPO_ROOT / prompt).is_file(), f"{role} names a missing prompt {prompt}"


def test_role_agent_source_is_not_gitignored() -> None:
    for role in ROLES:
        rel = f".opencode/agent/{role}.md"
        result = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "check-ignore", "--no-index", "-q", rel],
            capture_output=True,
        )
        assert result.returncode == 1, f"{rel} must not be gitignored"


def test_driver_agent_ships_as_primary_and_names_its_contract_prompt() -> None:
    text = DRIVER_AGENT.read_text(encoding="utf-8")
    assert "mode: primary" in text
    assert f"model: {EVAL_MODEL}" in text
    assert "eval/prompts/orchestrator.md" in text
    assert MONITOR_TOOL in text


def test_opencode_config_loads_the_orchestrator_prompt_and_the_monitor_plugin() -> None:
    config = json.loads(OPENCODE_CONFIG.read_text(encoding="utf-8"))
    assert "eval/prompts/orchestrator.md" in config["instructions"]
    assert "./plugin/eval-monitor.ts" in config["plugin"]


def test_monitor_plugin_defines_the_eval_monitor_tool() -> None:
    text = MONITOR_PLUGIN.read_text(encoding="utf-8")
    assert MONITOR_TOOL in text, "the plugin must define the eval_monitor tool"
    assert "next_target" in text, "the plugin must define the next_target tool"
    assert "orchestrator" in text and "monitor" in text, "the tool must shell the CLI tick"


def test_monitor_plugin_dispatches_awaited_native_child_sessions() -> None:
    """#350: the monitor dispatches role agents as bounded, awaited opencode
    child sessions via the injected SDK client - never a detached process."""
    text = MONITOR_PLUGIN.read_text(encoding="utf-8")
    assert "session.create" in text, "the child session must be created"
    assert "session.prompt" in text, "the child must be prompted and awaited"
    assert "session.abort" in text, "a timed-out or prior child must be aborted"
    assert "activeChildren" in text, "a re-dispatch must kill the prior child"
    assert "Popen" not in text, "no detached process may remain"
    assert "start_new_session" not in text, "no detached process group may remain"
    # The plan/apply protocol with the Python plan engine.
    assert "--plan" in text
    assert "--results" in text


def test_monitor_plugin_serializes_errors_without_losing_the_message() -> None:
    """#350 follow-up: `JSON.stringify(new Error(...))` is "{}", which would hide
    the provider-quota phrase (e.g. `Go usage limit exceeded`) and defeat the
    backoff. The plugin must render an Error as `name: message`."""
    text = MONITOR_PLUGIN.read_text(encoding="utf-8")
    assert "serializeError" in text
    assert "instanceof Error" in text
    assert "JSON.stringify(info.error)" not in text
    assert "JSON.stringify(response.error)" not in text
    assert "readFileSync" not in text


def test_role_agents_signal_a_terminal() -> None:
    for role, token in (("eval-assessor", "ASSESSMENT"), ("eval-diagnoser", "DIAGNOSIS")):
        text = _agent_text(role)
        assert f"{token} COMPLETE" in text, f"{role} must signal success"
        assert f"{token} FAILED" in text, f"{role} must signal failure"


def test_the_orchestrator_prompt_names_a_definition_that_exists() -> None:
    assert ORCHESTRATOR_PROMPT.is_file(), "driver contract prompt missing"
    assert MONITOR_TOOL in ORCHESTRATOR_PROMPT.read_text(encoding="utf-8")


def test_driver_source_is_not_gitignored() -> None:
    for path in (DRIVER_AGENT, OPENCODE_CONFIG, MONITOR_PLUGIN):
        rel = path.relative_to(REPO_ROOT).as_posix()
        result = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "check-ignore", "--no-index", "-q", rel],
            capture_output=True,
        )
        assert result.returncode == 1, f"{rel} must not be gitignored"


def test_documented_dispatch_commands_use_only_real_flags() -> None:
    seen = 0
    for doc in DISPATCH_DOCS:
        text = doc.read_text(encoding="utf-8")
        for line in text.splitlines():
            if "--agent eval-" not in line:
                continue
            seen += 1
            flags = _FLAG.findall(line)
            unknown = [flag for flag in flags if flag not in REAL_RUN_FLAGS]
            assert not unknown, f"{doc.name}: phantom opencode flags {unknown}"
            match = _AGENT.search(line)
            assert match is not None, f"{doc.name}: no --agent named: {line}"
            assert match.group(1) in ROLES, f"{doc.name}: unknown role {match.group(1)}"
    assert seen >= len(ROLES), "expected every documented dispatch command"
