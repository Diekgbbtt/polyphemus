"""Unit tier: the recon triager's STATEFUL, per-pod session wiring (#94).

The triager is the recon pod's one LLM agent, and up to MAX_PODS pods run it
CONCURRENTLY. So it must run STATEFUL on a session addressed per concurrent pod
instance - never a shared key. The triager NODE sets that per-pod (thread_id,
checkpointer) on a ContextVar (leaving the injected `triage_fn` contract untouched), and
the live `default_triage_fn` reads it to run via `stateful_turn` (`ToolStrategy`, which
keeps the function_calling path `Observation.anchor` needs). These tests pin that
routing with a faked seam - the unit tier touches no live model (CODING_STANDARD 6, 10).
"""
from __future__ import annotations

import polymerhus.app.llm.session as S
from polymerhus.recon.domain import pod
from polymerhus.recon.domain.types import ExecResult, JobSpec

_JOB = JobSpec(tool="httpx", skill="http_probe", command_template="httpx -u {target}",
               produces=["BaseURL"], consumes="BaseURL")
_EXEC = ExecResult(stdout="out", stderr="", returncode=0, duration_ms=1)


def test_default_triage_fn_runs_stateful_on_the_per_pod_thread_when_ctx_set(monkeypatch):
    seen = {}

    def fake_stateful_turn(role, thread, messages, *, checkpointer, schema=None, **kw):
        # the seam passes the typed address; record its thread_id (as the real
        # stateful_turn would coerce it)
        seen.update(role=role, thread_id=getattr(thread, "thread_id", thread), schema=schema)
        return None  # None -> [] observations, the exhausted-generation signal

    from polymerhus.app.llm.session_address import PodSession, SessionContext

    monkeypatch.setattr(S, "stateful_turn", fake_stateful_turn)
    ctx = SessionContext(PodSession("run1", 2, "httpx", "hostA", "triager"), object())
    token = pod._pod_ctx().set(ctx)
    try:
        obs = pod.default_triage_fn(_EXEC, [], _JOB)
    finally:
        pod._pod_ctx().reset(token)
    assert seen["role"] == "triager"
    assert seen["thread_id"] == "run1:2:httpx:hostA:triager"   # the per-pod session
    assert obs == []


def test_default_triage_fn_falls_back_to_stateless_invoke_role_without_ctx(monkeypatch):
    """No pod context (a directly-invoked pod graph, or a pod with no run_id) -> the
    stateless #73-retry `invoke_role` path, unchanged."""
    called = {}

    def fake_invoke_role(role, messages, *, schema=None):
        called["role"] = role
        return None

    monkeypatch.setattr("polymerhus.app.llm.roles.invoke_role", fake_invoke_role)
    assert pod._pod_ctx().get() is None
    obs = pod.default_triage_fn(_EXEC, [], _JOB)
    assert called["role"] == "triager"
    assert obs == []


def test_triager_node_sets_per_pod_ctx_from_run_and_asset(monkeypatch):
    """The NODE addresses the session per concurrent pod: with `run_id`/`phase` on the
    state, the ContextVar the triage_fn sees carries a `PodSession` address; two pods on
    different assets get different threads (no collision), and a state without `run_id`
    leaves the triager stateless."""
    captured = {}

    def capturing_triage_fn(er, assets, job):
        ctx = pod._pod_ctx().get()
        captured.setdefault("threads", []).append(ctx.address.thread_id if ctx else None)
        return []

    def exec_fn(cmd, sid, t):
        return ExecResult(stdout="", stderr="", returncode=0, duration_ms=1)

    def curate_fn(a, o, p):
        return (len(a), len(o), a, o)

    g = pod.build_pod_graph(exec_fn=exec_fn, curate_fn=curate_fn, triage_fn=capturing_triage_fn)
    base = {"job": _JOB, "asset_context": "", "extra": {}, "session_id": "s",
            "iteration": 0, "project_id": "p"}
    g.invoke({**base, "input_asset": {"url": "https://a.example"}, "run_id": "run1", "phase": 2})
    g.invoke({**base, "input_asset": {"url": "https://b.example"}, "run_id": "run1", "phase": 2})
    g.invoke({**base, "input_asset": {"name": "x"}})  # no run_id -> stateless

    threads = captured["threads"]
    assert threads[0] and threads[0].endswith(":triager")
    assert threads[0] != threads[1]      # distinct pods -> distinct session threads
    assert threads[2] is None            # no run_id -> stateless (no context set)
