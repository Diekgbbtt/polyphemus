"""Unit tier: T5 (#155) - wire the #95 compaction middleware seam onto the pod.

The pod's two roles (`pod_runner` / `pod_triager`) get LAZY role-scoped
compaction-middleware factories (`agents.py`), and `arun_pod` threads an
injectable per-role middleware set through the graph into the pod-session
bindings (D84-7) - the point T7's stateful default seams will read when they
call `stateful_turn`. This tier proves, with no live LLM/gateway/env: the
factories resolve each pod role lazily and fail-open without env; an injected
middleware rides the binding to the seam (the spy seams read `pod_middleware()`
exactly like the T7 default seam will); and with compaction disabled (the
default - nothing injected) the pod runs identically green. Hermetic by
construction (CODING_STANDARD sections 6, 10).
"""
from __future__ import annotations

import asyncio

import pytest

from polymerhus.attack.hunting.pod import arun_pod
from polymerhus.attack.hunting.pod.agents import (
    runner_compaction_middleware,
    symbolic_runner_step_fn,
    triager_compaction_middleware,
)
from polymerhus.attack.hunting.pod.llm import (
    POD_RUNNER_ROLE,
    POD_TRIAGER_ROLE,
    pod_middleware,
)
from polymerhus.recon.domain.types import ExecResult

VALID_SPEC = {
    "target_identity": "service:web:soupmarket",
    "verification_symptoms": ["HTTP 200 with a non-empty body on GET /"],
    "testing_pattern": "blind-boolean",
    "assumptions": ["network egress allowed"],
    "payload_vector_space": {"method": "GET", "path": "/"},
    "rationale": "reachability",
    "interpretation_guidance": "a 200 with a body confirms reachability",
}

# A symptom the symbolic recogniser cannot decide, so the triager seam runs.
SEMANTIC_SPEC = {**VALID_SPEC, "verification_symptoms": ["reflects the injected marker"]}


@pytest.fixture
def clean_llm_env(monkeypatch):
    """Drop the LLM env vars so the fail-open window/profile resolution stays
    deterministic and never touches a gateway (hermetic unit tier)."""
    monkeypatch.delenv("LLM_GATEWAY_URL", raising=False)
    monkeypatch.delenv("LLM_MODEL_POD_RUNNER", raising=False)
    monkeypatch.delenv("LLM_MODEL_POD_TRIAGER", raising=False)
    monkeypatch.delenv("LLM_ROLE_MODEL_CONTEXT_LIMIT", raising=False)
    monkeypatch.delenv("LLM_ATTEMPT_TIMEOUTS_S", raising=False)


def _exec(stdout="", returncode=0):
    def fake(command, timeout_s):
        return ExecResult(stdout=stdout, stderr="", returncode=returncode, duration_ms=1)
    return fake


_OK = "<html>market</html>\n__POD_HTTP_STATUS__:200\n__POD_HTTP_TIME__:0.05"
_ABSENT = "not found\n__POD_HTTP_STATUS__:404\n__POD_HTTP_TIME__:0.02"


def _no_trace(_run_id):
    return []


def _run(coro):
    """Drive the pod's async entry to completion (repo convention: no
    pytest-asyncio; sync tests `asyncio.run` the coroutine)."""
    return asyncio.run(coro)


# --- (a) the factories resolve each pod role lazily ----------------------------

def test_runner_compaction_middleware_builds_pod_runner_role(monkeypatch):
    """The runner factory maps to the `pod_runner` role of the shared builder -
    the single point of truth never hard-codes a role string."""
    from polymerhus.app.llm import compaction as C

    seen = {}
    sentinel = object()

    def spy(role_id, **_kw):
        seen["role_id"] = role_id
        return sentinel

    monkeypatch.setattr(C, "build_role_compaction_middleware", spy)
    assert runner_compaction_middleware() is sentinel
    assert seen["role_id"] == POD_RUNNER_ROLE


def test_triager_compaction_middleware_builds_pod_triager_role(monkeypatch):
    """The triager factory maps to the `pod_triager` role of the shared builder."""
    from polymerhus.app.llm import compaction as C

    seen = {}
    sentinel = object()

    def spy(role_id, **_kw):
        seen["role_id"] = role_id
        return sentinel

    monkeypatch.setattr(C, "build_role_compaction_middleware", spy)
    assert triager_compaction_middleware() is sentinel
    assert seen["role_id"] == POD_TRIAGER_ROLE


def test_role_middleware_factories_resolve_lazily_without_env(clean_llm_env):
    """The factories BUILD the real middleware with no env and no gateway: the
    window falls back to the conservative default, the D7 profile is None, and
    the role's lazy summariser is wired - the D9 fail-open construction, never
    a boot-gate at import."""
    from polymerhus.app.llm import compaction as C

    for mw in (runner_compaction_middleware(), triager_compaction_middleware()):
        assert mw.manager is not None
        assert mw.manager.window.context_limit == C.DEFAULT_CONTEXT_LIMIT
        assert mw.manager.profile is None
        assert mw.manager.summariser is not None


# --- (b) injected middleware rides the binding to the seam ---------------------

def test_injected_runner_middleware_reaches_the_runner_seam():
    """A fake middleware injected via `runner_middleware` rides the D84-7
    pod-session binding to the runner seam (the spy reads `pod_middleware()`
    exactly like the T7 default seam will); the binding is scoped to the seam
    call, so nothing leaks to the caller's context."""
    fake = object()
    seen = []

    def runner(spec, messages, tool_calls):
        seen.append(pod_middleware())
        return symbolic_runner_step_fn(spec, messages, tool_calls)

    env = _run(arun_pod(VALID_SPEC, exec_fn=_exec(_OK), runner_step_fn=runner,
                        triager_fn=None, trace_fn=_no_trace,
                        runner_middleware=[fake]))
    assert env["verdict"] == "successful"
    assert seen and seen[0] == (fake,)
    assert pod_middleware() == ()          # outside any binding: nothing


def test_injected_triager_middleware_reaches_the_triager_seam():
    fake = object()
    seen = []

    def triager(spec, obs, messages, log):
        seen.append(pod_middleware())
        return {"action": "terminate", "verdict": "unsuccessful",
                "terminal_reason": "space-exhausted", "clean": True}

    env = _run(arun_pod(SEMANTIC_SPEC, exec_fn=_exec(_ABSENT),
                        runner_step_fn=symbolic_runner_step_fn,
                        triager_fn=triager, trace_fn=_no_trace,
                        triager_middleware=[fake]))
    assert env["verdict"] == "unsuccessful"
    assert seen and seen[0] == (fake,)
    assert pod_middleware() == ()


def test_per_role_middleware_stays_per_role():
    """The injection surface is per-role: the runner's middleware never
    reaches the triager's seam and vice versa."""
    runner_fake, triager_fake = object(), object()
    runner_seen, triager_seen = [], []

    def runner(spec, messages, tool_calls):
        runner_seen.append(pod_middleware())
        return symbolic_runner_step_fn(spec, messages, tool_calls)

    def triager(spec, obs, messages, log):
        triager_seen.append(pod_middleware())
        return {"action": "terminate", "verdict": "unsuccessful",
                "terminal_reason": "space-exhausted", "clean": True}

    _run(arun_pod(SEMANTIC_SPEC, exec_fn=_exec(_ABSENT), runner_step_fn=runner,
                  triager_fn=triager, trace_fn=_no_trace,
                  runner_middleware=[runner_fake],
                  triager_middleware=[triager_fake]))
    assert runner_seen and runner_seen[0] == (runner_fake,)
    assert triager_seen and triager_seen[0] == (triager_fake,)


# --- (c) compaction disabled: the pod stays identical --------------------------

def test_disabled_compaction_default_runs_identical_and_unchanged():
    """With compaction NOT injected (the default), the pod runs identically:
    the same successful envelope, and the seam sees an empty middleware set -
    nothing breaks."""
    seen = []

    def runner(spec, messages, tool_calls):
        seen.append(pod_middleware())
        return symbolic_runner_step_fn(spec, messages, tool_calls)

    env = _run(arun_pod(VALID_SPEC, exec_fn=_exec(_OK), runner_step_fn=runner,
                        triager_fn=None, trace_fn=_no_trace))
    assert env["verdict"] == "successful"
    assert env["evidence"]["terminal_reason"] == "symptom-confirmed"
    assert seen and seen[0] == ()