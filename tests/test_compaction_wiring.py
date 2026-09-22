"""Unit tier: #95 H - compaction is wired onto every production stateful agent.

D9 named two consumers (the hunter + the mechanism-typist); H generalises the
consumer principle: every `checkpointer (create_agent)` agent across the modules -
the three analysis proposers, the two recon-pod roles, and the two orchestrator
actors - runs compacted. This module pins each wiring seam with a faked
`stateful_turn` / `run_session_agent`, asserting the compaction middleware reaches
the session construction. The compaction behaviour itself is covered by
`test_llm_compaction.py`; here we pin the consumer wiring.

Hermetic: no live model, no gateway, no database.
"""
from __future__ import annotations

import asyncio

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.checkpoint.memory import InMemorySaver
import pytest

from polymerhus.app.llm import compaction as C
from polymerhus.app.llm import session as S


class _TextFake(BaseChatModel):
    body: str = ""

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=self.body))])

    @property
    def _llm_type(self) -> str:
        return "fake"

    def bind_tools(self, tools, **kwargs):
        return self


def _assert_compaction_middleware(mw):
    assert mw is not None
    assert isinstance(mw.manager, C.CompactionManager)


# --- the three analysis proposers pass the middleware through stateful_turn -----

def test_all_three_proposers_pass_compaction_middleware(monkeypatch):
    seen = {}

    def fake_stateful_turn(role_id, thread, messages, *, checkpointer, schema=None,
                           middleware=(), **kw):
        seen.setdefault(role_id, list(middleware))
        return None

    monkeypatch.setattr(S, "stateful_turn", fake_stateful_turn)
    from polymerhus.analysis.assigner import stateful_invoke_fn as a
    from polymerhus.analysis.data_modeller import stateful_invoke_fn as d
    from polymerhus.analysis.mechanism_typist import stateful_invoke_fn as t

    a("run", object())([HumanMessage(content="m")])
    d("run", object())([HumanMessage(content="m")])
    t("run", object())([HumanMessage(content="m")], schema=None)

    assert set(seen) == {"assigner", "data_modeller", "mechanism_typist"}
    for role in seen:
        # Compaction is the WHOLE chain for an analysis proposer: it is
        # skill-exempt (ADR A9 exemption amendment), so no L1 index rides it.
        assert len(seen[role]) == 1
        _assert_compaction_middleware(seen[role][0])
        assert "_skill_index" not in {type(m).__name__ for m in seen[role]}


# --- the recon-pod triager passes its shared per-role middleware -----------------

def test_recon_pod_triager_passes_compaction_middleware(monkeypatch):
    from polymerhus.app.llm.session_address import PodSession, SessionContext
    from polymerhus.recon.domain import pod
    from polymerhus.recon.domain.types import ExecResult, JobSpec

    job = JobSpec(tool="httpx", skill="http_probe", command_template="httpx -u {target}",
                  produces=["BaseURL"], consumes="BaseURL")
    exec_result = ExecResult(stdout="out", stderr="", returncode=0, duration_ms=1)
    seen = {}

    def fake_stateful_turn(role, thread, messages, *, checkpointer, schema=None,
                           middleware=(), **kw):
        seen[role] = list(middleware)
        return None

    monkeypatch.setattr(S, "stateful_turn", fake_stateful_turn)
    ctx = SessionContext(PodSession("run1", 2, "httpx", "hostA", "triager"), object())
    token = pod._pod_ctx().set(ctx)
    try:
        pod.default_triage_fn(exec_result, [], job)
    finally:
        pod._pod_ctx().reset(token)

    # The per-pod throttle turn retired with the steering machinery (#243),
    # so only the triager's stateful turn remains - still carrying the
    # compaction middleware plus the L1 skill index (ADR A9: the triager is
    # BOUND - it reads delivered web artefacts).
    assert set(seen) == {"triager"}
    assert len(seen["triager"]) == 2
    _assert_compaction_middleware(seen["triager"][0])
    assert type(seen["triager"][1]).__name__ == "_skill_index"


def test_cached_role_middleware_is_shared_per_role():
    """The recon-pod pattern: ONE process-wide middleware per role, keyed internally
    by thread_id - a second fetch returns the SAME manager (cross-re-witness state)."""
    mw1 = C.cached_role_compaction_middleware("triager")
    mw2 = C.cached_role_compaction_middleware("triager")
    assert mw1 is mw2
    _assert_compaction_middleware(mw1)


# --- the two orchestrator actors wire compaction -------------------------------

def test_hunt_orchestrator_actor_wires_compaction():
    from polymerhus.attack.hunting.actors import HuntOrchestratorActor

    async def drive():
        actor = HuntOrchestratorActor(
            "run-h", checkpointer=InMemorySaver(),
            model_factory=lambda r: _TextFake(body=""), observe=False)
        await actor._ensure_started()
        await actor.stop()
        return actor

    actor = asyncio.run(drive())
    assert isinstance(actor.compaction_manager, C.CompactionManager)


def test_recon_orchestrator_actor_wires_compaction():
    from polymerhus.recon.control.orchestrator_agent import ReconOrchestratorActor

    async def drive():
        actor = ReconOrchestratorActor(
            "run-r", checkpointer=InMemorySaver(),
            model_factory=lambda r: _TextFake(body=""), observe=False)
        await actor._ensure_started()
        await actor.stop()
        return actor

    actor = asyncio.run(drive())
    assert isinstance(actor.compaction_manager, C.CompactionManager)
