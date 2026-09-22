"""Unit tier: the analysis proposers' STATEFUL session seams (#94).

`assigner`/`mechanism_typist`/`data_modeller` no longer make stateless `invoke_role`
calls - each runs as a session that resumes from its OWN per-run checkpoint, so its
context progresses across the run's chunks. These tests pin that each `stateful_invoke_fn`
keys its session by its `AnalysisSession(run_id, <its own role>)` (distinct per
agent, so no cross-agent collision) and routes structured output through the schema. The
`stateful_turn` seam is faked - the unit tier touches no live model (CODING_STANDARD
sections 6, 10).
"""
from __future__ import annotations

from langchain_core.messages import HumanMessage

import polymerhus.app.llm.session as S


def _capture(monkeypatch):
    seen = {}

    def fake_stateful_turn(role_id, thread, messages, *, checkpointer, schema=None, **kw):
        seen.update(role_id=role_id, thread_id=getattr(thread, "thread_id", thread),
                    schema=schema, cp=checkpointer, extra_tags=kw.get("extra_tags"))
        seen.update(tools=kw.get("tools"), middleware=kw.get("middleware"),
                    context=kw.get("context"))
        return None

    monkeypatch.setattr(S, "stateful_turn", fake_stateful_turn)
    return seen


def test_assigner_session_keys_per_run_and_carries_its_schema(monkeypatch):
    from polymerhus.analysis.analyser_types import L1DeltaBatch
    from polymerhus.analysis.assigner import stateful_invoke_fn

    seen = _capture(monkeypatch)
    cp = object()
    stateful_invoke_fn("runX", cp)([HumanMessage(content="m")])
    assert seen["role_id"] == "assigner"
    assert seen["thread_id"] == "runX:assigner"     # distinct, per-run thread
    assert seen["schema"] is L1DeltaBatch
    assert seen["cp"] is cp


def test_typist_session_keys_per_run_and_passes_the_call_schema(monkeypatch):
    from polymerhus.analysis.mechanism_typist import stateful_invoke_fn

    seen = _capture(monkeypatch)
    invoke = stateful_invoke_fn("runX", object())
    invoke([HumanMessage(content="reflect")], schema=None)     # the prose reflection turn
    assert seen["role_id"] == "mechanism_typist"
    assert seen["thread_id"] == "runX:mechanism_typist"
    assert seen["schema"] is None
    from polymerhus.analysis.analyser_types import L1DeltaBatch
    invoke([HumanMessage(content="extract")], schema=L1DeltaBatch)  # a structured turn
    assert seen["schema"] is L1DeltaBatch


def test_data_modeller_session_keys_per_run(monkeypatch):
    from polymerhus.analysis.data_modeller import stateful_invoke_fn

    seen = _capture(monkeypatch)
    stateful_invoke_fn("runX", object())([HumanMessage(content="m")], schema=None)
    assert seen["role_id"] == "data_modeller"
    assert seen["thread_id"] == "runX:data_modeller"


def test_the_three_proposers_never_share_a_thread(monkeypatch):
    """The collision-free guarantee at the analysis layer: the three proposers of one
    run hold three DISTINCT checkpoints, so none resumes another's memory."""
    from polymerhus.analysis.assigner import stateful_invoke_fn as a
    from polymerhus.analysis.data_modeller import stateful_invoke_fn as d
    from polymerhus.analysis.mechanism_typist import stateful_invoke_fn as t

    threads = set()
    for build, call in ((a, lambda f: f([HumanMessage(content="m")])),
                        (t, lambda f: f([HumanMessage(content="m")], schema=None)),
                        (d, lambda f: f([HumanMessage(content="m")], schema=None))):
        seen = _capture(monkeypatch)
        call(build("runX", object()))
        threads.add(seen["thread_id"])
    assert threads == {"runX:assigner", "runX:mechanism_typist", "runX:data_modeller"}


def test_all_three_proposers_tag_turns_with_the_run_id(monkeypatch):
    """Convergence join: each proposer turn carries the bare run id as an extra
    tag, so session-scoped turn traces stay run-joinable after the hand-written
    agent-span wrappers go away."""
    from polymerhus.analysis.assigner import stateful_invoke_fn as a
    from polymerhus.analysis.data_modeller import stateful_invoke_fn as d
    from polymerhus.analysis.mechanism_typist import stateful_invoke_fn as t

    for build, call in ((a, lambda f: f([HumanMessage(content="m")])),
                        (t, lambda f: f([HumanMessage(content="m")], schema=None)),
                        (d, lambda f: f([HumanMessage(content="m")], schema=None))):
        seen = _capture(monkeypatch)
        call(build("runX", object()))
        assert seen["extra_tags"] == ["runX"]


def test_the_proposers_carry_no_skill_surface(monkeypatch):
    """Operator ruling (2026-09-17): the analysis proposers interact with LOCAL
    context only (the published L0/L1 substrate), never with an external
    environment, so they bind neither the `load_skill` tool nor the L1 index
    middleware nor a skill context - their turns carry structure, not skills."""
    from polymerhus.analysis.assigner import stateful_invoke_fn as a
    from polymerhus.analysis.data_modeller import stateful_invoke_fn as d
    from polymerhus.analysis.mechanism_typist import stateful_invoke_fn as t

    for role, build, call in (
        ("assigner", a, lambda f: f([HumanMessage(content="m")])),
        ("mechanism_typist", t, lambda f: f([HumanMessage(content="m")], schema=None)),
        ("data_modeller", d, lambda f: f([HumanMessage(content="m")], schema=None)),
    ):
        seen = _capture(monkeypatch)
        call(build("runX", object()))

        assert seen["role_id"] == role
        # Complete by construction: no skill tool to call, no context for an index
        # to render from, and no index middleware on the chain at all.
        assert seen["tools"] is None, f"{role} must bind no skill tool"
        assert seen["context"] is None, f"{role} must carry no skill context"
        assert "_skill_index" not in {
            type(mw).__name__ for mw in seen["middleware"] or ()
        }, f"{role} must carry no L1 skill index middleware"
