"""Unit tier: the recon-orchestrator AUTH GATEWAY actor (#223, T3 #242).

`ReconOrchestratorActor` runs ONE gateway turn per recon run on the
`job_orchestrator` session role, armed with the full auth surface, closing
with the structured `GatewayVerdict`. These tests exercise the actor at the
public client seam (`run_gateway` / `stop`) with a FAKE tool-calling model
emitting scripted tool calls plus real tool collaborators over temp stores;
the unit tier touches no live model and no live database (CODING_STANDARD
sections 6, 10).
"""
from __future__ import annotations

import asyncio
import types

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.checkpoint.memory import InMemorySaver

from polymerhus.app.auth.store import AuthStore
from polymerhus.app.llm.skills import SkillStore
from polymerhus.recon.control.authn_loop import GatewayVerdict
from polymerhus.recon.control.orchestrator_agent import (
    GatewayStop,
    ReconOrchestratorActor,
)


class _ScriptFake(BaseChatModel):
    """A scripted model emitting one message per model STEP (the shape
    ToolStrategy consumes): each `_generate` pops the next scripted
    tool-call list, so a script walks [tool calls...] then the terminal
    `GatewayVerdict` call."""

    steps: list = []

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        calls = self.steps[min(len(self.steps) - 1, 0)] if False else None
        raise NotImplementedError  # replaced per-instance below

    @property
    def _llm_type(self) -> str:
        return "fake"

    def bind_tools(self, tools, **kwargs):
        bound = list(tools)
        names = [getattr(t, "name", None) for t in bound]
        object.__setattr__(self, "_bound_names", names)
        return self


def _script_model(*steps):
    """A `model_factory` yielding scripted fakes walking `steps` (one
    tool-call list per model step). Records every bound tool surface."""
    seen = {"bound": []}
    cursor = {"i": 0}

    def make(role_id):
        i = cursor["i"]

        class _Step(_ScriptFake):
            def _generate(self, messages, stop=None, run_manager=None, **kwargs):
                step = steps[min(cursor["i"], len(steps) - 1)]
                cursor["i"] += 1
                return ChatResult(generations=[ChatGeneration(message=AIMessage(
                    content="",
                    tool_calls=[{**c, "id": f"c{c['id']}", "type": "tool_call"}
                                for c in step],
                ))])

            async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
                return self._generate(messages, stop=stop, run_manager=run_manager, **kwargs)

            def bind_tools(self, tools, **kwargs):
                seen["bound"].append(sorted(getattr(t, "name", "?") for t in tools))
                return self

        return _Step()

    return make, seen


def _verdict_call(**fields):
    base = {"outcome": "authenticated", "account": "alice", "branch": "request",
            "rationale": "proven live"}
    return {"name": "GatewayVerdict", "args": {**base, **fields}, "id": "v"}


def _seeded_store(tmp_path, *, overview=None, accounts=None):
    store = AuthStore(tmp_path)
    store.replace_operator_state("p1", overview=overview or {},
                                 accounts=accounts or {})
    return store


def _actor(run_id="run1", *, store, model_factory, tmp_path, **kw):
    return ReconOrchestratorActor(
        run_id, project_id="p1", checkpointer=InMemorySaver(),
        model_factory=model_factory, observe=False, compaction=False,
        auth_store=store, skill_store=SkillStore(tmp_path),
        kali_tools=list(kw.pop("kali_tools", ())), **kw,
    )


def _account(name="alice", **extra):
    return {name: {"credentials": {"username": "u", "password": "p",
                                   "login_url": "https://x/login"}, **extra}}


# --- arming --------------------------------------------------------------------


def test_gateway_arming_binds_the_full_auth_surface(tmp_path):
    """The gateway turn binds the full D223-13 surface: `auth_store`,
    `load_skill`, `write_skill`, the Kali exec capability, and the Steel
    exec gateway - through the native seams, fixed at construction."""
    from langchain_core.tools import tool as _tool

    @_tool
    def execute_command(command: str) -> str:
        """Run a shell command on kali."""
        return "ok"

    @_tool
    def steel_exec(command: str = "") -> str:
        """Run a steel CLI command."""
        return "ok"

    make, seen = _script_model([_verdict_call()])
    store = _seeded_store(tmp_path, accounts=_account())
    actor = _actor("r1", store=store, model_factory=make, tmp_path=tmp_path,
                   kali_tools=[execute_command, steel_exec])

    verdict = asyncio.run(actor.run_gateway())
    asyncio.run(actor.stop())

    assert isinstance(verdict, GatewayVerdict)
    assert verdict.account == "alice"
    assert seen["bound"], "the model never saw a bound surface"
    # the response-format tool rides the binding too (standard ToolStrategy
    # shape); the turn's own surface is the five armed names
    assert [n for n in seen["bound"][0] if n != "GatewayVerdict"] == [
        "auth_store", "execute_command", "load_skill", "steel_exec", "write_skill"]


# --- the gateway turn ------------------------------------------------------------


def test_gateway_turn_grounds_retrieves_and_verdicts(tmp_path):
    """One gateway turn over the real tool collaborators: the model grounds
    (overview read + skill load), the tracker observes the documented
    transitions, and the turn closes with the structured verdict."""
    make, _ = _script_model(
        [{"name": "auth_store", "args": {"command": "read", "path": ""}, "id": "1"},
         {"name": "load_skill", "args": {"name": "authn"}, "id": "2"}],
        [_verdict_call()],
    )
    store = _seeded_store(
        tmp_path, overview={"login_endpoint": "https://x/login"},
        accounts=_account())
    actor = _actor("r1", store=store, model_factory=make, tmp_path=tmp_path)

    verdict = asyncio.run(actor.run_gateway())
    asyncio.run(actor.stop())

    assert verdict == GatewayVerdict(outcome="authenticated", account="alice",
                                     branch="request", rationale="proven live")
    tracker = actor.loop_state
    assert tracker["overview_seen"] is True
    assert tracker["skill_seen"] is True
    assert tracker["phase"] == "RETRIEVED"
    assert tracker["usable_accounts"] == ("alice",)


def test_gateway_missing_skill_marks_self_service_in_loop(tmp_path):
    """With credentials but no `authn` bundle (the temp skill store carries
    none), the loop flags self-service: the load observes absent and the
    empty accounts read resolves to the self-service hint."""
    from polymerhus.recon.control.orchestrator_agent import build_authn_loop_middleware

    mw = build_authn_loop_middleware()

    def _run(tool, args, content):
        request = types.SimpleNamespace(
            tool_call={"name": tool, "args": args, "id": "c", "type": "tool_call"})
        return mw.wrap_tool_call(
            request, lambda req: ToolMessage(content=content, tool_call_id="c", name=tool))

    out = _run("load_skill", {"name": "authn"}, "")
    assert out.content == ""  # grounding still open: silent
    assert mw.tracker["skill_missing"] is True
    out = _run("auth_store", {"command": "read", "path": ""},
               '{"ok": true, "command": "read", "path": "", "value": {"overview": {}, "accounts": {}}}')
    from polymerhus.recon.control.authn_loop import SELF_SERVICE_HINT, wrap_hint
    assert out.content.endswith(wrap_hint(SELF_SERVICE_HINT))
    assert mw.tracker["phase"] == "GENERATION"


def test_gateway_hint_rides_only_the_triggering_result(tmp_path):
    """The injected hint is consumed per response: it rides the transition's
    own tool result and never leaks onto a later, unrelated one."""
    from polymerhus.recon.control.authn_loop import RETRIEVED_HINT, wrap_hint
    from polymerhus.recon.control.orchestrator_agent import build_authn_loop_middleware

    mw = build_authn_loop_middleware()

    def _run(tool, args, content):
        request = types.SimpleNamespace(
            tool_call={"name": tool, "args": args, "id": "c", "type": "tool_call"})
        return mw.wrap_tool_call(
            request, lambda req: ToolMessage(content=content, tool_call_id="c", name=tool))

    _run("auth_store", {"command": "read", "path": "overview"},
         '{"ok": true, "value": {}}')
    _run("load_skill", {"name": "authn"}, "the procedure")
    out = _run("auth_store", {"command": "read", "path": "accounts"},
               '{"ok": true, "value": {"alice": {"credentials": {}}}}')
    assert wrap_hint(RETRIEVED_HINT) in out.content
    # the next, unrelated result carries no stale hint
    later = _run("auth_store", {"command": "read", "path": "overview.notes"},
                 '{"ok": true, "value": "n"}')
    assert "authn-loop-hint" not in later.content


# --- missing-data paths ----------------------------------------------------------


def test_gateway_skips_the_loop_on_no_auth_surface(tmp_path):
    """An empty store is the expected no-surface shape: no turn is taken
    (the actor never spawns), the pipeline runs anonymously, and the verdict
    records the finding."""
    make, seen = _script_model([_verdict_call()])
    actor = _actor("r1", store=_seeded_store(tmp_path), model_factory=make,
                   tmp_path=tmp_path)

    verdict = asyncio.run(actor.run_gateway())

    assert verdict.outcome == "anonymous"
    assert verdict.account is None
    assert "no authenticated surface" in verdict.rationale.lower()
    assert actor._task is None  # the loop was skipped, nothing spawned
    assert seen["bound"] == []
    asyncio.run(actor.stop())  # safe when never spawned


def test_gateway_stops_loudly_without_credentials(tmp_path, caplog):
    """A declared surface with no accounts is a missing prerequisite, not a
    gateway failure: the run stops loudly (fail-close, D223-2 does not
    apply)."""
    make, _ = _script_model([_verdict_call()])
    actor = _actor(
        "r1", store=_seeded_store(
            tmp_path, overview={"login_endpoint": "https://x/login"},
            accounts={}), model_factory=make, tmp_path=tmp_path)

    with caplog.at_level("ERROR"):
        with pytest.raises(GatewayStop):
            asyncio.run(actor.run_gateway())
    assert "no credentials" in caplog.text.lower()
    asyncio.run(actor.stop())


def test_gateway_null_replayability_is_logged_loudly_never_persisted(tmp_path, caplog):
    """The null-replayability resolution is run-scoped and loud: the gateway
    logs it before the loop, the verdict carries it, and the overview file
    on disk is untouched."""
    make, _ = _script_model([_verdict_call(branch="browser_only",
                                           replayability_resolved=True,
                                           replayability=False,
                                           rationale="fingerprint replay failed")])
    store = _seeded_store(
        tmp_path, overview={"anti-bot": "waf:x"}, accounts=_account())
    actor = _actor("r1", store=store, model_factory=make, tmp_path=tmp_path)

    with caplog.at_level("WARNING"):
        verdict = asyncio.run(actor.run_gateway())
    asyncio.run(actor.stop())

    assert verdict.branch == "browser_only"
    assert verdict.replayability_resolved is True
    assert "replayability" in caplog.text.lower()
    assert store.read("p1", "overview") == {"anti-bot": "waf:x"}  # never persisted


# --- failure posture ---------------------------------------------------------------


def test_gateway_fail_open_when_the_model_raises(tmp_path, caplog):
    class _Boom(BaseChatModel):
        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            raise RuntimeError("llm down")

        @property
        def _llm_type(self) -> str:
            return "fake"

    actor = _actor("r1", store=_seeded_store(tmp_path, accounts=_account()),
                   model_factory=lambda role: _Boom(), tmp_path=tmp_path)
    with caplog.at_level("WARNING"):
        assert asyncio.run(actor.run_gateway()) is None
    assert "fail-open" in caplog.text.lower()
    asyncio.run(actor.stop())


def test_gateway_bounded_await_leaves_no_stale_reply(tmp_path, monkeypatch):
    """D223-10: the gateway await is bounded in wall-clock time - a hung turn
    returns None instead of stalling run start, and no stale reply survives
    for a later consumer."""
    import polymerhus.recon.control.orchestrator_agent as OA

    monkeypatch.setattr(OA, "GATEWAY_AWAIT_TIMEOUT_S", 0.05)

    class _Slow(BaseChatModel):
        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            import time
            time.sleep(0.5)
            return ChatResult(generations=[ChatGeneration(
                message=AIMessage(content="late", tool_calls=[]))])

        async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
            return self._generate(messages, stop=stop, run_manager=run_manager, **kwargs)

        @property
        def _llm_type(self) -> str:
            return "fake"

        def bind_tools(self, tools, **kwargs):
            return self

    actor = _actor("r1", store=_seeded_store(tmp_path, accounts=_account()),
                   model_factory=lambda role: _Slow(), tmp_path=tmp_path)
    import time
    t0 = time.monotonic()
    assert asyncio.run(actor.run_gateway()) is None
    assert time.monotonic() - t0 < 5  # bounded, never the slow turn's tail
    asyncio.run(actor.stop())


def test_gateway_wrong_schema_reply_is_loud(tmp_path, caplog):
    """D223-10: a reply whose content parses to the wrong schema is logged
    loudly (never a silent None)."""
    from polymerhus.app.llm.actor import AgentMessage

    actor = _actor("r1", store=_seeded_store(tmp_path, accounts=_account()),
                   model_factory=_script_model([_verdict_call()])[0],
                   tmp_path=tmp_path)

    async def _drive():
        await actor._ensure_started()
        await actor._replies.post(AgentMessage(
            kind="gateway_verdict",
            payload={"content": {"not": "a verdict"}, "messages": [],
                     "thread_id": actor.thread_id},
            source="test",
        ))
        with caplog.at_level("WARNING"):
            out = await actor._await_reply()
        assert out is None
        await actor.stop()

    asyncio.run(_drive())
    assert "wrong-schema" in caplog.text.lower()


def test_gateway_stop_is_idempotent_without_spawn(tmp_path):
    async def _drive():
        actor = _actor("r1", store=_seeded_store(tmp_path),
                       model_factory=_script_model([_verdict_call()])[0],
                       tmp_path=tmp_path)
        await actor.stop()  # never spawned: no-op
        await actor.stop()  # idempotent

    asyncio.run(_drive())  # must not raise
