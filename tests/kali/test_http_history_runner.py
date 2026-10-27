"""The exec runner behind the MCP `execute_command` tool for #196.

The runner is the only place where the *shape* of the process launch is
decided, and that shape is load-bearing: a login shell re-derives ``PATH``
from ``/etc/profile`` and DISCARDS the tools path the kali entrypoint exports,
so ``httpx`` resolves to the Python ``httpx`` CLI and ``katana``/``naabu``/...
are not found at all (observed live 2026-09-16: a real recon run came back
``httpx: degraded`` with 0 assets and ``katana: skipped``). The base image's
``/etc/profile.d/zz-redamon-motd.sh`` also prints a banner on every login
shell, including non-interactive ones, prefixed to the stdout of every tool
command. Both regressions are pinned here without spawning a process.
"""
from __future__ import annotations

import pytest

from kali.http_history import service as service_module
from kali.http_history.service import ExecOutcome, default_runner
from kali.process_group import ProcessOutcome


@pytest.fixture(autouse=True)
def _no_workdir_io(monkeypatch):
    """The runner mkdir's its per-session workdir under /work (container-only)."""
    created: list[str] = []
    monkeypatch.setattr(
        service_module.os, "makedirs", lambda path, **kwargs: created.append(path)
    )
    return created


def _fake_run(
    monkeypatch,
    *,
    stdout="",
    stderr="",
    returncode=0,
    duration_ms=1,
):
    """Capture the launch shape and return the process-group outcome."""
    seen: dict[str, object] = {}

    def fake_run(argv, **kwargs):
        seen["argv"] = argv
        seen["kwargs"] = kwargs
        return ProcessOutcome(
            stdout=stdout,
            stderr=stderr,
            returncode=returncode,
            duration_ms=duration_ms,
        )

    monkeypatch.setattr(service_module, "run_in_process_group", fake_run)
    return seen


def test_default_runner_uses_a_non_login_shell(monkeypatch, _no_workdir_io):
    """`bash -lc` is the defect: the login profile resets PATH and prints a banner."""
    seen = _fake_run(monkeypatch, stdout="ok\n")

    outcome = default_runner("echo ok", session_id="s1", timeout_s=30)

    assert seen["argv"] == ["bash", "-c", "echo ok"]
    # Belt: a bare `-l`/`-lc`/`--login` anywhere in the argv is the regression.
    assert "-lc" not in seen["argv"]
    assert not [a for a in seen["argv"] if a.startswith("-") and "l" in a.lstrip("-")]
    assert outcome.stdout == "ok\n"
    assert outcome.stderr == ""
    assert outcome.returncode == 0
    assert outcome.duration_ms >= 0


def test_default_runner_keeps_the_namespace_prefix(monkeypatch, _no_workdir_io):
    """Every pod runs inside a leased netns: `ip netns exec` stays outermost."""
    seen = _fake_run(monkeypatch)

    default_runner("echo hi", session_id="s2", timeout_s=30, namespace="kali-ns-abc")

    assert seen["argv"] == [
        "ip",
        "netns",
        "exec",
        "kali-ns-abc",
        "bash",
        "-c",
        "echo hi",
    ]


def test_default_runner_returns_stdout_and_returncode(monkeypatch, _no_workdir_io):
    seen = _fake_run(
        monkeypatch, stdout='{"url":"http://t/"}\n', stderr="warn\n", returncode=3
    )

    outcome = default_runner("httpx -u t", session_id="s3", timeout_s=30)

    assert outcome == ExecOutcome(
        stdout='{"url":"http://t/"}\n',
        stderr="warn\n",
        returncode=3,
        duration_ms=1,
    )
    assert seen["kwargs"]["cwd"] == "/work/s3"
    assert seen["kwargs"]["timeout_s"] == 30
    assert seen["kwargs"]["shell"] is False
    assert seen["kwargs"]["text"] is True


def test_default_runner_maps_timeout_to_124(monkeypatch, _no_workdir_io):
    _fake_run(
        monkeypatch,
        stdout="partial\n",
        stderr="timeout after 7s",
        returncode=124,
    )

    outcome = default_runner("katana -u t", session_id="s4", timeout_s=7)

    assert outcome.returncode == 124
    assert outcome.stderr == "timeout after 7s"
    assert outcome.stdout == "partial\n"
