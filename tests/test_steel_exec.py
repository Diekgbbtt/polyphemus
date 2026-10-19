"""Host-side unit tests for the kali `steel_exec` gateway tool.

Seam under test: the tool function itself (`mcp_server.steel_exec.fn`),
with a stubbed `steel` binary on PATH. No docker, no network, no cloud key.
Workdir root redirects via KALI_WORKDIR (call-time read) because /work is
not writable outside the kali container; in-container default is unchanged.

The tool body is `async def` (mcp-exec-nonblocking-decisions.md), so the
tests drive it through `_steel_exec`, which awaits the real body via
`asyncio.run` exactly as FastMCP does - the host suite stays sync.
"""
import asyncio
import json
import os
import stat

import pytest

import kali.mcp_server as m

STEEL_EXEC = m.steel_exec.fn


def _steel_exec(**kwargs):
    return asyncio.run(STEEL_EXEC(**kwargs))


@pytest.fixture()
def workroot(tmp_path, monkeypatch):
    root = tmp_path / "work"
    root.mkdir()
    monkeypatch.setenv("KALI_WORKDIR", str(root))
    return root


@pytest.fixture()
def steel_stub(tmp_path, monkeypatch):
    """A stubbed `steel` binary: echoes argv as JSON, records each call.

    Emulates the two probes the tool shells out to: `--version` reports the
    pinned CLI, and the session catalogue (`browser sessions --json`) reports
    one live session named `taken-sess` in the live-observed shape
    ({id, mode, name, status, viewerUrl}, data [] when none is live).
    """
    bindir = tmp_path / "bin"
    bindir.mkdir()
    calls = tmp_path / "calls.log"
    _write_steel_stub(bindir, calls, "steel version 0.4.4")
    monkeypatch.setenv("PATH", str(bindir) + os.pathsep + os.environ.get("PATH", ""))
    return calls


@pytest.fixture()
def steel_stub_stale(tmp_path, monkeypatch):
    """Same stub but reporting a stale CLI, for the version re-check."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    calls = tmp_path / "calls.log"
    _write_steel_stub(bindir, calls, "steel version 0.4.3")
    monkeypatch.setenv("PATH", str(bindir) + os.pathsep + os.environ.get("PATH", ""))
    return calls


def _write_steel_stub(bindir, calls, version_line):
    stub = bindir / "steel"
    stub.write_text(
        "#!/bin/sh\n"
        f'echo "$@" >> "{calls}"\n'
        'case "$*" in\n'
        f'  *--version*) echo "{version_line}" ;;\n'
        '  *"browser sessions"*)\n'
        '    echo \'{"success":true,"data":[{"id":"uuid-1","mode":"cloud",'
        '"name":"taken-sess","status":"live",'
        '"viewerUrl":"https://app.steel.dev/sessions/uuid-1"}]}\' ;;\n'
        '  *) echo "{\\"stub\\": true}" ;;\n'
        "esac\n"
    )
    stub.chmod(stub.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _calls(calls_file):
    if not calls_file.exists():
        return []
    return calls_file.read_text().splitlines()


def test_non_steel_command_refused_never_executed(workroot, steel_stub):
    out = _steel_exec(command="echo hi", session_id="s1")
    assert out["returncode"] != 0
    assert "refused" in out["stderr"] and "steel" in out["stderr"]
    assert _calls(steel_stub) == []
    # Refusal carries the unchanged envelope shape.
    assert set(out) == {"stdout", "stderr", "returncode", "duration_ms"}


def test_ambiguous_inputs_refused_never_executed(workroot, steel_stub):
    for kw in ({"command": "steel browser sessions", "script": "echo hi"},
               {"command": "", "script": ""}):
        out = _steel_exec(session_id="s1", **kw)
        assert out["returncode"] != 0
        assert out["stderr"].startswith("refused:ambiguous-input")
    assert _calls(steel_stub) == []


def test_steel_substring_without_token_refused(workroot, steel_stub):
    out = _steel_exec(command="echo nosteel", session_id="s1")
    assert out["returncode"] != 0
    assert out["stderr"].startswith("refused:not-steel-command")
    assert _calls(steel_stub) == []


def test_sh_script_written_verbatim_then_run(workroot, steel_stub):
    # Tricky chars ride in a comment (shell would expand them in code); the
    # byte-exact file read is the verbatim proof, stdout proves execution.
    script = ('# it\'s $100 `quoted`\n'
              'steel browser eval "document.title" --session s3 --json\n'
              'echo script-done\n')
    out = _steel_exec(script=script, script_lang="sh", session_id="s3")
    assert out["returncode"] == 0, out
    assert '{"stub": true}' in out["stdout"]  # stub ran inside the script
    assert "script-done" in out["stdout"]
    written = list((workroot / "s3").glob("steel_exec_*.sh"))
    assert len(written) == 1
    assert written[0].read_text() == script  # byte-exact, no templating
    assert set(out) == {"stdout", "stderr", "returncode", "duration_ms"}


def test_py_script_runs_and_bad_lang_refused(workroot, steel_stub):
    out = _steel_exec(script="print('py-ok')\n", script_lang="py", session_id="s4")
    assert out["returncode"] == 0, out
    assert out["stdout"].strip() == "py-ok"
    assert list((workroot / "s4").glob("steel_exec_*.py")) != []
    out = _steel_exec(script="echo hi", script_lang="rb", session_id="s4")
    assert out["returncode"] != 0
    assert out["stderr"].startswith("refused:unsupported-script-lang")


def test_steel_command_passes_through_with_envelope(workroot, steel_stub):
    out = _steel_exec(command="steel browser cookies --json", session_id="s1")
    assert out["returncode"] == 0
    assert json.loads(out["stdout"]) == {"stub": True}
    assert set(out) == {"stdout", "stderr", "returncode", "duration_ms"}
    # The pinned-version probe runs first, then the command itself.
    assert _calls(steel_stub) == ["--version", "browser cookies --json"]


def test_taken_session_name_refused_with_name(workroot, steel_stub):
    # The session catalogue reports taken-sess live; the start must never run.
    out = _steel_exec(command="steel browser start --session taken-sess --json",
                     session_id="s1")
    assert out["returncode"] != 0
    assert out["stderr"].startswith("refused:session-taken")
    assert "taken-sess is already used" in out["stderr"]
    assert set(out) == {"stdout", "stderr", "returncode", "duration_ms"}
    calls = _calls(steel_stub)
    assert any("browser sessions" in c for c in calls)
    assert not any("start" in c for c in calls)


def test_free_session_name_proceeds_to_start(workroot, steel_stub):
    out = _steel_exec(command="steel browser start --session fresh-sess --json",
                     session_id="s1")
    assert out["returncode"] == 0, out
    calls = _calls(steel_stub)
    assert any("browser sessions" in c for c in calls)
    assert any("start" in c and "fresh-sess" in c for c in calls)


def test_guard_only_watches_command_mode_starts(workroot, steel_stub):
    # A non-start command carrying --session never reads the catalogue.
    out = _steel_exec(command="steel browser navigate https://x --session taken-sess --json",
                     session_id="s1")
    assert out["returncode"] == 0, out
    assert not any("browser sessions" in c for c in _calls(steel_stub))
    # Script text is never scanned: skill-constructed names bypass the guard.
    script = "steel browser start --session taken-sess --json\necho done\n"
    out = _steel_exec(script=script, script_lang="sh", session_id="s2")
    assert out["returncode"] == 0, out
    assert "done" in out["stdout"]
    assert not any("browser sessions" in c for c in _calls(steel_stub))


def test_unreadable_catalogue_fails_open(workroot, tmp_path, monkeypatch):
    # A catalogue that errors or does not parse must never block a start:
    # the guard reads "cannot verify" and the run proceeds.
    bindir = tmp_path / "bin2"
    bindir.mkdir()
    stub = bindir / "steel"
    stub.write_text(
        "#!/bin/sh\n"
        'case "$*" in\n'
        '  *--version*) echo "steel version 0.4.4" ;;\n'
        '  *"browser sessions"*) echo "not json" ;;\n'
        '  *) echo "{\\"stub\\": true}" ;;\n'
        "esac\n"
    )
    stub.chmod(stub.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    monkeypatch.setenv("PATH", str(bindir) + os.pathsep + os.environ.get("PATH", ""))
    out = _steel_exec(command="steel browser start --session taken-sess --json",
                     session_id="s1")
    assert out["returncode"] == 0, out


def test_tool_timeout_defaults_to_600():
    # D11 literal: the steel clock governs, the tool budget sits above it.
    import inspect
    assert inspect.signature(STEEL_EXEC).parameters["timeout_s"].default == 600


def test_steel_wait_within_budget_proceeds(workroot, steel_stub):
    out = _steel_exec(
        command='steel browser wait -t "Secure Area" --timeout 10000 --session s1 --json',
        session_id="s1")
    assert out["returncode"] == 0, out
    # The shell strips the quotes before the stub logs argv; the --timeout
    # value surviving verbatim is the plumbing proof.
    assert _calls(steel_stub) == [
        "--version", "browser wait -t Secure Area --timeout 10000 --session s1 --json"]


def test_steel_wait_exceeding_budget_refused_never_executed(workroot, steel_stub):
    out = _steel_exec(
        command='steel browser wait -t "x" --timeout 10000 --session s1 --json',
        session_id="s1", timeout_s=5)
    assert out["returncode"] != 0
    assert out["stderr"].startswith("refused:timeout-ordering")
    # Only the version probe ran; the refused command itself never executed.
    assert _calls(steel_stub) == ["--version"]


def test_session_lifetime_is_not_a_wait(workroot, steel_stub):
    # --session-timeout bounds the session life, not the call; it must not
    # trip the steel-wait < tool-timeout ordering even at 600000ms == 600s.
    out = _steel_exec(
        command="steel browser start --session fresh-sess --session-timeout 600000 --json",
        session_id="s1")
    assert out["returncode"] == 0, out


def test_stale_steel_version_refused_never_executed(workroot, steel_stub_stale):
    out = _steel_exec(command="steel browser sessions --json", session_id="s1")
    assert out["returncode"] != 0
    assert out["stderr"].startswith("refused:steel-version-mismatch")
    assert "0.4.4" in out["stderr"]
    assert set(out) == {"stdout", "stderr", "returncode", "duration_ms"}
    assert _calls(steel_stub_stale) == ["--version"]


def test_misordered_variadic_refused_never_executed(workroot, steel_stub):
    # The reported defect: a flag after the first value token folds into the
    # value silently. Every variadic verb without the `--` boundary is refused,
    # so the encoded-boundary rule never has to guess where the value ends.
    for command in (
        "steel browser fill '#user-name' 'standard_user' --json",
        "steel browser fill '#user-name' 'standard_user' --session taken-sess --json",
        "steel browser type --session s1 '#user-name' 'standard_user' --json",
        "steel browser setvalue --session s1 '#user-name' 'standard_user'",
        "steel browser select --session s1 '#drop' 'opt2' --json",
        "steel browser upload --session s1 '#file' '/tmp/a' --json",
    ):
        out = _steel_exec(command=command, session_id="s1")
        assert out["returncode"] != 0, command
        assert out["stderr"].startswith("refused:variadic-boundary"), (command, out)
        assert set(out) == {"stdout", "stderr", "returncode", "duration_ms"}
    # Only the version probe ran; no refused command reached the steel binary.
    calls = _calls(steel_stub)
    assert calls and set(calls) == {"--version"}


def test_canonical_text_entry_passes_through_byte_identical(workroot, steel_stub):
    cases = {
        "steel browser fill --session s1 --json '#user-name' -- 'standard_user'":
            "browser fill --session s1 --json #user-name -- standard_user",
        "steel browser type --session s1 --json '#user-name' -- 'standard_user'":
            "browser type --session s1 --json #user-name -- standard_user",
        "steel browser setvalue --session s1 --json '#user-name' -- 'standard_user'":
            "browser setvalue --session s1 --json #user-name -- standard_user",
    }
    for command, expected in cases.items():
        out = _steel_exec(command=command, session_id="s1")
        assert out["returncode"] == 0, out
        # `steel` is the program; the stub logs the argv verbatim, so an exact
        # match proves the tool inserted nothing and reordered nothing.
        assert _calls(steel_stub)[-1] == expected, command


def test_flaglike_value_under_sentinel_preserved_verbatim(workroot, steel_stub):
    # A value after the boundary is data, never an option: a flag-like value
    # rides through untouched, which is the case the boundary exists for.
    for value in ("--json", "-x"):
        out = _steel_exec(
            command=f"steel browser fill --session s1 --json '#user-name' -- '{value}'",
            session_id="s1")
        assert out["returncode"] == 0, out
        assert _calls(steel_stub)[-1] == \
            f"browser fill --session s1 --json #user-name -- {value}"


def test_batch_boundary_required_at_both_levels(workroot, steel_stub):
    # Outer: `batch` is `[COMMANDS]...` variadic, so a trailing option would fold
    # into the last command string.
    out = _steel_exec(
        command="steel browser batch 'snapshot -i' 'click @e4' --session s1 --json",
        session_id="s1")
    assert out["stderr"].startswith("refused:variadic-boundary"), out
    assert "batch" in out["stderr"]
    # Inner: an element that is itself variadic carries its own boundary.
    out = _steel_exec(
        command="steel browser batch --session s1 --json -- 'snapshot -i' 'fill @e6 42'",
        session_id="s1")
    assert out["stderr"].startswith("refused:variadic-boundary"), out
    assert "fill" in out["stderr"]
    # Canonical at both levels passes byte-identical.
    command = "steel browser batch --session s1 --json -- 'snapshot -i' 'fill @e6 -- 42'"
    out = _steel_exec(command=command, session_id="s1")
    assert out["returncode"] == 0, out
    assert _calls(steel_stub)[-1] == \
        "browser batch --session s1 --json -- snapshot -i fill @e6 -- 42"


def test_quoted_double_dash_value_is_not_the_boundary(workroot, steel_stub):
    # Tokenization is shell-aware: a `--` inside a quoted value is data, so the
    # command still lacks the boundary and is refused, not mistaken as canonical.
    out = _steel_exec(
        command="steel browser fill --session s1 --json '#x' 'a -- b'",
        session_id="s1")
    assert out["stderr"].startswith("refused:variadic-boundary"), out


def test_non_variadic_verbs_accept_trailing_flags(workroot, steel_stub):
    out = _steel_exec(
        command="steel browser press Enter --session s1 --json", session_id="s1")
    assert out["returncode"] == 0, out
    assert _calls(steel_stub)[-1] == "browser press Enter --session s1 --json"


def test_script_text_not_scanned_for_boundary(workroot, steel_stub):
    # The boundary guard is command-mode only; a script owns its own encoding
    # (D13: script text is never scanned).
    script = "steel browser fill --session s1 '#x' 'v' --json\necho done\n"
    out = _steel_exec(script=script, script_lang="sh", session_id="s2")
    assert out["returncode"] == 0, out
    assert "done" in out["stdout"]


# ---------------------------------------------------------------------------
# Local-mode injection (#390, D359-4)
#
# `STEEL_BROWSER_API_URL` set means the self-hosted runtime. The CLI selects
# local mode only through the global `--local` flag, so the gateway injects it
# into a command-mode invocation. The CLI reads the value itself (its native
# precedence step 2); the gateway never rewrites the URL.
# ---------------------------------------------------------------------------


def test_local_mode_injected_when_endpoint_set(workroot, steel_stub, monkeypatch):
    monkeypatch.setenv("STEEL_BROWSER_API_URL", "http://192.33.91.87:3000/v1")
    out = _steel_exec(command="steel browser cookies --json", session_id="s1")
    assert out["returncode"] == 0, out
    assert _calls(steel_stub)[-1] == "--local browser cookies --json"


def test_no_injection_when_endpoint_unset(workroot, steel_stub, monkeypatch):
    monkeypatch.delenv("STEEL_BROWSER_API_URL", raising=False)
    out = _steel_exec(command="steel browser cookies --json", session_id="s1")
    assert out["returncode"] == 0, out
    assert _calls(steel_stub)[-1] == "browser cookies --json"


def test_injection_skipped_when_command_already_chooses_mode_or_url(
        workroot, steel_stub, monkeypatch):
    monkeypatch.setenv("STEEL_BROWSER_API_URL", "http://192.33.91.87:3000/v1")
    cases = [
        ("steel --local browser cookies --json", "--local browser cookies --json"),
        ("steel browser cookies --json --api-url http://192.33.91.87:3000/v1",
         "browser cookies --json --api-url http://192.33.91.87:3000/v1"),
    ]
    for command, expected in cases:
        out = _steel_exec(command=command, session_id="s1")
        assert out["returncode"] == 0, out
        assert _calls(steel_stub)[-1] == expected


def test_injection_lands_after_the_steel_token_not_at_the_front(
        workroot, steel_stub, monkeypatch):
    # A command may carry a prefix (`cd /work/s1 && steel ...`). The flag is a
    # global and must follow the binary token, never lead the whole line.
    monkeypatch.setenv("STEEL_BROWSER_API_URL", "http://192.33.91.87:3000/v1")
    out = _steel_exec(command="cd /tmp && steel browser cookies --json", session_id="s1")
    assert out["returncode"] == 0, out
    assert _calls(steel_stub)[-1] == "--local browser cookies --json"


def test_injection_ignores_the_word_steel_inside_a_path(
        workroot, steel_stub, monkeypatch):
    # Regression: a bare `\bsteel\b` anchor matched the word inside a path
    # (`/opt/steel`, `steel-cli`) and corrupted the prefix. The anchor must be
    # the `steel` token in command position.
    monkeypatch.setenv("STEEL_BROWSER_API_URL", "http://192.33.91.87:3000/v1")
    (workroot / "steel").mkdir()
    (workroot / "steel-cli").mkdir()
    for command in (
        f"cd {workroot}/steel && steel browser cookies --json",
        f"cd {workroot}/steel-cli && steel browser cookies --json",
        f"STEEL_DIR={workroot}/steel steel browser cookies --json",
    ):
        out = _steel_exec(command=command, session_id="s1")
        assert out["returncode"] == 0, out
        assert _calls(steel_stub)[-1] == "--local browser cookies --json", command


def test_script_mode_never_rewritten(workroot, steel_stub, monkeypatch):
    # Script text is verbatim by contract (D13); the skill tells the caller to
    # pass `--local` itself. With the endpoint set, the script's own steel call
    # must run without an injected flag.
    monkeypatch.setenv("STEEL_BROWSER_API_URL", "http://192.33.91.87:3000/v1")
    script = "steel browser cookies --json\necho done\n"
    out = _steel_exec(script=script, script_lang="sh", session_id="s2")
    assert out["returncode"] == 0, out
    assert "done" in out["stdout"]
    # The version probe runs first, then the script's unmodified steel call.
    assert _calls(steel_stub)[-1] == "browser cookies --json"
    assert not any("--local" in c for c in _calls(steel_stub))


def test_gateway_env_name_matches_the_shared_resolver():
    # One name, two readers: the gateway's own copy and the app resolver must
    # never drift apart (#390, D359-4).
    from polymerhus.app.steel_endpoint import ENV_VAR
    assert m._STEEL_ENDPOINT_ENV == ENV_VAR


def test_gateway_module_imports_no_polymerhus():
    # The kali image does not carry the polymerhus package, so the gateway must
    # read the variable name directly (C3).
    import inspect
    import kali.mcp_server as mm
    src = inspect.getsource(mm)
    assert "from polymerhus" not in src
    assert "import polymerhus" not in src
