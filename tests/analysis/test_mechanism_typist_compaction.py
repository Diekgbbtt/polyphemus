"""Unit tier: slice F of #95 - the mechanism-typist's chained text-generator lane runs compacted.

D9's second consumer is the analysis mechanism-typist - a CHAINED TEXT GENERATOR
(the reflection -> extraction -> linking 3-call chain over one growing session
thread), contrasting the hunter's tool-calling mailbox actor, so both state
machines are covered. This module pins the consumer wiring: `stateful_invoke_fn`
builds the analysis-side compaction middleware ONCE per run and passes it through
`stateful_turn` (the ubiquitous stateful-agent seam), so an over-budget thread
spawns out-of-band passes that the next turn's barrier awaits. The `stateful_turn`
seam is faked here - the session-seam compaction behaviour itself is covered by
`tests/test_llm_compaction.py`; this file pins the wiring and the seam's
middleware forwarding.

Hermetic: no live model, no gateway, no database.
"""
from __future__ import annotations

from langchain_core.messages import HumanMessage

import polymerhus.app.llm.session as S
from polymerhus.app.llm import compaction as C


def test_typist_turns_run_compacted(monkeypatch):
    """#95 D9: the mechanism-typist's stateful turns run COMPACTED - the run's
    `stateful_invoke_fn` builds the analysis-side compaction middleware (fail-open
    to the default window without env) and passes it through `stateful_turn`."""
    seen = {}

    def fake_stateful_turn(role_id, thread, messages, *, checkpointer, schema=None,
                           middleware=(), **kw):
        seen["middleware"] = list(middleware)
        seen["role_id"] = role_id
        return None

    monkeypatch.setattr(S, "stateful_turn", fake_stateful_turn)
    from polymerhus.analysis.mechanism_typist import stateful_invoke_fn

    invoke = stateful_invoke_fn("runX", object())
    invoke([HumanMessage(content="reflect")], schema=None)
    assert seen["role_id"] == "mechanism_typist"
    assert len(seen["middleware"]) == 1
    mw = seen["middleware"][0]
    assert isinstance(mw.manager, C.CompactionManager)
    assert mw.manager.summariser is not None
    assert mw.manager.window.context_limit == C.DEFAULT_CONTEXT_LIMIT  # fail-open, no env


def test_typist_compaction_middleware_is_shared_across_the_chain(monkeypatch):
    """One middleware per run: the run's session is one thread, so the 3-call
    chain shares ONE manager (and one ledger) - the growing context compacts as a
    whole, never per-call."""
    seen = []

    def fake_stateful_turn(role_id, thread, messages, *, checkpointer, schema=None,
                           middleware=(), **kw):
        seen.append(list(middleware))
        return None

    monkeypatch.setattr(S, "stateful_turn", fake_stateful_turn)
    from polymerhus.analysis.mechanism_typist import stateful_invoke_fn

    invoke = stateful_invoke_fn("runX", object())
    invoke([HumanMessage(content="reflect")], schema=None)
    invoke([HumanMessage(content="extract")], schema=None)
    assert len(seen) == 2
    assert seen[0][0] is seen[1][0]  # the same manager across the chain


def test_stateful_turn_forwards_middleware_to_the_real_loop(monkeypatch):
    """The ubiquitous `stateful_turn` seam threads `middleware` through to
    `run_session_turn`, so a chained text-generator consumer (the mechanism-typist)
    actually reaches the real agent loop - not merely builds the middleware."""
    from polymerhus.app.llm.session_address import AnalysisSession

    seen = {}

    def fake_run_session_turn(role_id, thread_id, messages, *, middleware=(), **kw):
        seen["middleware"] = list(middleware)
        seen["thread_id"] = thread_id
        return S.SessionTurn(content=None, messages=[], thread_id=thread_id)

    monkeypatch.setattr(S, "run_session_turn", fake_run_session_turn)
    sentinel = object()
    S.stateful_turn("mechanism_typist", AnalysisSession("runX", "mechanism_typist"),
                    [HumanMessage(content="m")], checkpointer=object(),
                    middleware=[sentinel])
    assert seen["middleware"] == [sentinel]
    assert seen["thread_id"] == "runX:mechanism_typist"
