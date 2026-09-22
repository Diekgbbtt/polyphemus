"""Host-side unit tests for the kali `steel_exec` gateway tool.

Seam under test: the tool function itself (`mcp_server.steel_exec.fn`),
with a stubbed `steel` binary on PATH. No docker, no network, no cloud key.
Workdir root redirects via KALI_WORKDIR (call-time read) because /work is
not writable outside the kali container; in-container default is unchanged.
"""
import json
import os
import stat

import pytest

import kali.mcp_server as m

STEEL_EXEC = m.steel_exec.fn


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
    out = STEEL_EXEC(command="echo hi", session_id="s1")
    assert out["returncode"] != 0
    assert "refused" in out["stderr"] and "steel" in out["stderr"]
    assert _calls(steel_stub) == []
    # Refusal carries the unchanged envelope shape.
    assert set(out) == {"stdout", "stderr", "returncode", "duration_ms"}


def test_ambiguous_inputs_refused_never_executed(workroot, steel_stub):
    for kw in ({"command": "steel browser sessions", "script": "echo hi"},
               {"command": "", "script": ""}):
        out = STEEL_EXEC(session_id="s1", **kw)
        assert out["returncode"] != 0
        assert out["stderr"].startswith("refused:ambiguous-input")
    assert _calls(steel_stub) == []


def test_steel_substring_without_token_refused(workroot, steel_stub):
    out = STEEL_EXEC(command="echo nosteel", session_id="s1")
    assert out["returncode"] != 0
    assert out["stderr"].startswith("refused:not-steel-command")
    assert _calls(steel_stub) == []


def test_sh_script_written_verbatim_then_run(workroot, steel_stub):
    # Tricky chars ride in a comment (shell would expand them in code); the
    # byte-exact file read is the verbatim proof, stdout proves execution.
    script = ('# it\'s $100 `quoted`\n'
              'steel browser eval "document.title" --session s3 --json\n'
              'echo script-done\n')
    out = STEEL_EXEC(script=script, script_lang="sh", session_id="s3")
    assert out["returncode"] == 0, out
    assert '{"stub": true}' in out["stdout"]  # stub ran inside the script
    assert "script-done" in out["stdout"]
    written = list((workroot / "s3").glob("steel_exec_*.sh"))
    assert len(written) == 1
    assert written[0].read_text() == script  # byte-exact, no templating
    assert set(out) == {"stdout", "stderr", "returncode", "duration_ms"}


def test_py_script_runs_and_bad_lang_refused(workroot, steel_stub):
    out = STEEL_EXEC(script="print('py-ok')\n", script_lang="py", session_id="s4")
    assert out["returncode"] == 0, out
    assert out["stdout"].strip() == "py-ok"
    assert list((workroot / "s4").glob("steel_exec_*.py")) != []
    out = STEEL_EXEC(script="echo hi", script_lang="rb", session_id="s4")
    assert out["returncode"] != 0
    assert out["stderr"].startswith("refused:unsupported-script-lang")


def test_steel_command_passes_through_with_envelope(workroot, steel_stub):
    out = STEEL_EXEC(command="steel browser cookies --json", session_id="s1")
    assert out["returncode"] == 0
    assert json.loads(out["stdout"]) == {"stub": True}
    assert set(out) == {"stdout", "stderr", "returncode", "duration_ms"}
    # The pinned-version probe runs first, then the command itself.
    assert _calls(steel_stub) == ["--version", "browser cookies --json"]


def test_taken_session_name_refused_with_name(workroot, steel_stub):
    # The session catalogue reports taken-sess live; the start must never run.
    out = STEEL_EXEC(command="steel browser start --session taken-sess --json",
                     session_id="s1")
    assert out["returncode"] != 0
    assert out["stderr"].startswith("refused:session-taken")
    assert "taken-sess is already used" in out["stderr"]
    assert set(out) == {"stdout", "stderr", "returncode", "duration_ms"}
    calls = _calls(steel_stub)
    assert any("browser sessions" in c for c in calls)
    assert not any("start" in c for c in calls)


def test_free_session_name_proceeds_to_start(workroot, steel_stub):
    out = STEEL_EXEC(command="steel browser start --session fresh-sess --json",
                     session_id="s1")
    assert out["returncode"] == 0, out
    calls = _calls(steel_stub)
    assert any("browser sessions" in c for c in calls)
    assert any("start" in c and "fresh-sess" in c for c in calls)


def test_guard_only_watches_command_mode_starts(workroot, steel_stub):
    # A non-start command carrying --session never reads the catalogue.
    out = STEEL_EXEC(command="steel browser navigate https://x --session taken-sess --json",
                     session_id="s1")
    assert out["returncode"] == 0, out
    assert not any("browser sessions" in c for c in _calls(steel_stub))
    # Script text is never scanned: skill-constructed names bypass the guard.
    script = "steel browser start --session taken-sess --json\necho done\n"
    out = STEEL_EXEC(script=script, script_lang="sh", session_id="s2")
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
    out = STEEL_EXEC(command="steel browser start --session taken-sess --json",
                     session_id="s1")
    assert out["returncode"] == 0, out


def test_tool_timeout_defaults_to_600():
    # D11 literal: the steel clock governs, the tool budget sits above it.
    import inspect
    assert inspect.signature(STEEL_EXEC).parameters["timeout_s"].default == 600


def test_steel_wait_within_budget_proceeds(workroot, steel_stub):
    out = STEEL_EXEC(
        command='steel browser wait -t "Secure Area" --timeout 10000 --session s1 --json',
        session_id="s1")
    assert out["returncode"] == 0, out
    # The shell strips the quotes before the stub logs argv; the --timeout
    # value surviving verbatim is the plumbing proof.
    assert _calls(steel_stub) == [
        "--version", "browser wait -t Secure Area --timeout 10000 --session s1 --json"]


def test_steel_wait_exceeding_budget_refused_never_executed(workroot, steel_stub):
    out = STEEL_EXEC(
        command='steel browser wait -t "x" --timeout 10000 --session s1 --json',
        session_id="s1", timeout_s=5)
    assert out["returncode"] != 0
    assert out["stderr"].startswith("refused:timeout-ordering")
    # Only the version probe ran; the refused command itself never executed.
    assert _calls(steel_stub) == ["--version"]


def test_session_lifetime_is_not_a_wait(workroot, steel_stub):
    # --session-timeout bounds the session life, not the call; it must not
    # trip the steel-wait < tool-timeout ordering even at 600000ms == 600s.
    out = STEEL_EXEC(
        command="steel browser start --session fresh-sess --session-timeout 600000 --json",
        session_id="s1")
    assert out["returncode"] == 0, out


def test_stale_steel_version_refused_never_executed(workroot, steel_stub_stale):
    out = STEEL_EXEC(command="steel browser sessions --json", session_id="s1")
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
        out = STEEL_EXEC(command=command, session_id="s1")
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
        out = STEEL_EXEC(command=command, session_id="s1")
        assert out["returncode"] == 0, out
        # `steel` is the program; the stub logs the argv verbatim, so an exact
        # match proves the tool inserted nothing and reordered nothing.
        assert _calls(steel_stub)[-1] == expected, command


def test_flaglike_value_under_sentinel_preserved_verbatim(workroot, steel_stub):
    # A value after the boundary is data, never an option: a flag-like value
    # rides through untouched, which is the case the boundary exists for.
    for value in ("--json", "-x"):
        out = STEEL_EXEC(
            command=f"steel browser fill --session s1 --json '#user-name' -- '{value}'",
            session_id="s1")
        assert out["returncode"] == 0, out
        assert _calls(steel_stub)[-1] == \
            f"browser fill --session s1 --json #user-name -- {value}"


def test_batch_boundary_required_at_both_levels(workroot, steel_stub):
    # Outer: `batch` is `[COMMANDS]...` variadic, so a trailing option would fold
    # into the last command string.
    out = STEEL_EXEC(
        command="steel browser batch 'snapshot -i' 'click @e4' --session s1 --json",
        session_id="s1")
    assert out["stderr"].startswith("refused:variadic-boundary"), out
    assert "batch" in out["stderr"]
    # Inner: an element that is itself variadic carries its own boundary.
    out = STEEL_EXEC(
        command="steel browser batch --session s1 --json -- 'snapshot -i' 'fill @e6 42'",
        session_id="s1")
    assert out["stderr"].startswith("refused:variadic-boundary"), out
    assert "fill" in out["stderr"]
    # Canonical at both levels passes byte-identical.
    command = "steel browser batch --session s1 --json -- 'snapshot -i' 'fill @e6 -- 42'"
    out = STEEL_EXEC(command=command, session_id="s1")
    assert out["returncode"] == 0, out
    assert _calls(steel_stub)[-1] == \
        "browser batch --session s1 --json -- snapshot -i fill @e6 -- 42"


def test_quoted_double_dash_value_is_not_the_boundary(workroot, steel_stub):
    # Tokenization is shell-aware: a `--` inside a quoted value is data, so the
    # command still lacks the boundary and is refused, not mistaken as canonical.
    out = STEEL_EXEC(
        command="steel browser fill --session s1 --json '#x' 'a -- b'",
        session_id="s1")
    assert out["stderr"].startswith("refused:variadic-boundary"), out


def test_non_variadic_verbs_accept_trailing_flags(workroot, steel_stub):
    out = STEEL_EXEC(
        command="steel browser press Enter --session s1 --json", session_id="s1")
    assert out["returncode"] == 0, out
    assert _calls(steel_stub)[-1] == "browser press Enter --session s1 --json"


def test_script_text_not_scanned_for_boundary(workroot, steel_stub):
    # The boundary guard is command-mode only; a script owns its own encoding
    # (D13: script text is never scanned).
    script = "steel browser fill --session s1 '#x' 'v' --json\necho done\n"
    out = STEEL_EXEC(script=script, script_lang="sh", session_id="s2")
    assert out["returncode"] == 0, out
    assert "done" in out["stdout"]
