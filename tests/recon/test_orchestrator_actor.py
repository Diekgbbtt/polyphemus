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
from polymerhus.recon.control.rate_limit_runner import RateLimitHarness
from polymerhus.recon.domain.rate_limit import (
    ExperimentEvidence,
    RateLimitSafetyBudget,
    RateLoopVerdict,
    RateProfile,
)


class _ScriptFake(BaseChatModel):
    """A scripted model emitting one message per model STEP (the shape
    ToolStrategy consumes): each `_generate` pops the next scripted
    tool-call list, so a script walks [tool calls...] then the terminal
    `GatewayVerdict` call."""

    steps: list = []

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


def _rate_verdict_call(**fields):
    base = {"outcome": "no_limiter", "bypass_outcome": "no_bypass",
            "rationale": "no transition within the tested bounds"}
    return {"name": "RateLoopVerdict", "args": {**base, **fields}, "id": "rv"}


class _CountingSkillStore(SkillStore):
    """A `SkillStore` that records every skill name read, so "the rate turn
    loads the generic bypass procedure once" is asserted at the real loader
    seam rather than inferred from the scripted tool call."""

    def __init__(self, root_dir, seen: list):
        super().__init__(root_dir)
        self._seen = seen

    def read(self, name, *, project_id=None):
        self._seen.append(name)
        return super().read(name, project_id=project_id)


def _seeded_store(tmp_path, *, overview=None, accounts=None):
    store = AuthStore(tmp_path)
    store.replace_operator_state("p1", overview=overview or {},
                                 accounts=accounts or {})
    return store


def _actor(run_id="run1", *, store, model_factory, tmp_path, **kw):
    return ReconOrchestratorActor(
        run_id, project_id="p1", checkpointer=InMemorySaver(),
        model_factory=model_factory, observe=False, compaction=False,
        auth_store=store,
        skill_store=kw.pop("skill_store", None) or SkillStore(tmp_path),
        kali_tools=list(kw.pop("kali_tools", ())), **kw,
    )


def _rate_harness(*, url="https://app.example.com", budget=None):
    """A real Task-4 `RateLimitHarness` over a recording fake executor: the
    actor consumes the actual harness (never a stub), and the recorded specs
    are the "Vegeta executions" the browser-only path must never produce."""
    executions = []

    async def execute(spec):
        executions.append(spec)
        return ExperimentEvidence(
            experiment_id=spec.experiment_id, phase=spec.phase,
            offered_rate_per_s=spec.rate_per_s, requests=spec.requests,
            concurrent_workers=spec.concurrency, duration_s=spec.duration_s,
            status_counts={"200": spec.requests}, rejection_ratio=0.0,
        )

    harness = RateLimitHarness(
        target_key="app.example.com", url=url,
        budget=budget or RateLimitSafetyBudget(), execute=execute,
        project_id="p1", run_id="run1", profile_ttl_s=3600.0,
    )
    return harness, executions


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
    # the response-format tools ride the binding too (standard ToolStrategy
    # shape - one per union variant); the turn's own surface is the five armed
    # names plus the two #238 rate-limit tools (one actor, one fixed surface)
    assert [n for n in seen["bound"][0]
            if n not in ("GatewayVerdict", "RateLoopVerdict")] == [
        "auth_store", "execute_command", "load_skill", "map_rate_limit",
        "steel_exec", "test_rate_limit_variant", "write_skill"]


def test_gateway_binds_the_bypass_skill_beside_authn_without_double_binding(
    tmp_path, monkeypatch
):
    """#238 Task 2: with the roster no longer empty, the orchestrator takes the
    BOUND arm of the auth binding. Its surface must stay exactly one
    `load_skill` + one `write_skill` (+ `auth_store`) - the generic bypass
    procedure and the project `authn` procedure ride the bounded SET, never a
    duplicated tool - and that set is what the model is told it may load."""
    import polymerhus.app.llm.actor as _A

    seen = {}

    async def _fake_run(*args, **kwargs):
        seen.update(kwargs)
        return None

    monkeypatch.setattr(_A, "run_session_agent", _fake_run)
    make, _ = _script_model([_verdict_call()])
    actor = _actor("r1", store=_seeded_store(tmp_path, accounts=_account()),
                   model_factory=make, tmp_path=tmp_path, kali_tools=[])

    asyncio.run(actor._ensure_started())
    asyncio.run(actor.stop())

    names = [getattr(t, "name", None) for t in seen["tools"]]
    assert names.count("load_skill") == 1
    assert names.count("write_skill") == 1
    assert names.count("auth_store") == 1
    assert seen["context"]["skills"] == [
        "performing-api-rate-limiting-bypass", "authn"
    ]


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


def test_gateway_hint_attaches_to_list_content():
    """A list-shaped tool result gains the hint as a text block (not
    silently dropped); an unshaped response passes through with a loud
    line."""
    from polymerhus.recon.control.authn_loop import GROUNDED_HINT, wrap_hint
    from polymerhus.recon.control.orchestrator_agent import build_authn_loop_middleware

    mw = build_authn_loop_middleware()
    skill_request = types.SimpleNamespace(
        tool_call={"name": "load_skill", "args": {"name": "authn"},
                   "id": "s", "type": "tool_call"})
    mw.wrap_tool_call(
        skill_request, lambda req: ToolMessage(content="the procedure", tool_call_id="s",
                                               name="load_skill"))
    request = types.SimpleNamespace(
        tool_call={"name": "auth_store", "args": {"command": "read", "path": "overview"},
                   "id": "c", "type": "tool_call"})
    out = mw.wrap_tool_call(
        request, lambda req: ToolMessage(
            content=[{"type": "text", "text": "the overview"}],
            tool_call_id="c", name="auth_store"))
    assert out.content[-1] == {"type": "text", "text": wrap_hint(GROUNDED_HINT)}


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


def test_gateway_null_replayability_is_logged_loudly_harness_writes_nothing(tmp_path, caplog):
    """The null-replayability resolution is loud: the gateway logs it before
    the loop and the verdict carries it; the harness itself never writes, so
    the overview on disk is untouched by this turn - persistence is the loop
    model's in-turn `auth_store` write (D223-11 as amended by D220-12)."""
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
    assert store.read("p1", "overview") == {"anti-bot": "waf:x"}  # harness writes nothing; the loop model persists


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
    from polymerhus.recon.control.orchestrator_agent import GATEWAY_AWAIT_TIMEOUT_S

    actor = _actor("r1", store=_seeded_store(tmp_path, accounts=_account()),
                   model_factory=_script_model([_verdict_call()])[0],
                   tmp_path=tmp_path)

    async def _drive():
        await actor._ensure_started()
        await actor._replies.post(AgentMessage(
            kind="orchestrator_reply",
            payload={"content": {"not": "a verdict"}, "messages": [],
                     "thread_id": actor.thread_id},
            source="test",
        ))
        with caplog.at_level("WARNING"):
            out = await actor._await_reply(
                GatewayVerdict, GATEWAY_AWAIT_TIMEOUT_S, "auth gateway")
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


# --- A6: the gateway verdict strategy is negotiated, not pinned -----------------

import pytest as _pytest


@_pytest.fixture(autouse=True)
def _a6_negotiated_tool_strategy(monkeypatch):
    """A6: the actor's `structured_response_format` negotiation resolves to
    `ToolStrategy` in this scripted-model suite (the fakes emit the
    ToolStrategy tool-call shape), while production negotiates per profile."""
    from langchain.agents.structured_output import ToolStrategy
    import polymerhus.app.llm.session as _S

    def _fake(role_id, schema, *, tools_bound):
        return ToolStrategy(schema)

    monkeypatch.setattr(_S, "structured_response_format", _fake)


def test_a6_gateway_verdict_uses_the_negotiated_strategy(monkeypatch, tmp_path):
    """A6 + #238: the actor computes `response_format` AFTER the tool binding
    via `structured_response_format("job_orchestrator", GatewayVerdict |
    RateLoopVerdict, tools_bound=True)` - one negotiation for both sequential
    turns on the same session - and passes its result through to the session
    agent (no raw pin)."""
    import polymerhus.app.llm.actor as _A
    import polymerhus.app.llm.session as _S

    calls = {}
    from langchain.agents.structured_output import ToolStrategy
    sentinel = ToolStrategy(GatewayVerdict | RateLoopVerdict)

    def _fake_format(role_id, schema, *, tools_bound):
        calls.update(role_id=role_id, schema=schema, tools_bound=tools_bound)
        return sentinel

    monkeypatch.setattr(_S, "structured_response_format", _fake_format)
    seen = {}

    async def _fake_run(*args, **kwargs):
        seen.update(kwargs)
        return None

    monkeypatch.setattr(_A, "run_session_agent", _fake_run)
    make, _ = _script_model([_verdict_call()])
    store = _seeded_store(tmp_path, accounts=_account())
    actor = _actor("r1", store=store, model_factory=make, tmp_path=tmp_path,
                   kali_tools=[])
    asyncio.run(actor._ensure_started())
    asyncio.run(actor.stop())
    assert calls == {"role_id": "job_orchestrator",
                     "schema": GatewayVerdict | RateLoopVerdict,
                     "tools_bound": True}
    assert seen["response_format"] is sentinel


# --- #238 Task 5: the SECOND turn (post-auth rate mapping) on the same actor -------


def test_rate_turn_runs_second_on_the_same_actor_thread(tmp_path, monkeypatch):
    """#238: rate mapping is a second turn on the SAME actor session/thread -
    gateway first, rate brief second, one actor task, one `thread_id`, the
    union negotiated once, and the generic bypass procedure loaded once."""
    import polymerhus.app.llm.actor as _A

    harness, executions = _rate_harness()
    make, _ = _script_model(
        [_verdict_call()],
        [{"name": "load_skill",
          "args": {"name": "performing-api-rate-limiting-bypass"}, "id": "s"},
         {"name": "map_rate_limit", "args": {}, "id": "m"}],
        [_rate_verdict_call()],
    )
    loaded: list[str] = []
    actor = _actor("run1", store=_seeded_store(tmp_path, accounts=_account()),
                   model_factory=make, tmp_path=tmp_path,
                   skill_store=_CountingSkillStore(tmp_path, loaded),
                   rate_harness=harness)

    spawns: list[str] = []
    real_spawn = _A.run_session_agent

    async def _spy_spawn(role_id, thread_id, *args, **kwargs):
        spawns.append(thread_id)
        return await real_spawn(role_id, thread_id, *args, **kwargs)

    monkeypatch.setattr(_A, "run_session_agent", _spy_spawn)
    kinds: list[str] = []
    real_on_message = actor._on_message

    def _spy_on_message(message, last_turn):
        kinds.append(message.kind)
        return real_on_message(message, last_turn)

    actor._on_message = _spy_on_message

    async def _drive():
        verdict = await actor.run_gateway()
        profile = await actor.run_rate_limit(
            target_key="app.example.com", url="https://app.example.com")
        task = actor._task
        await actor.stop()
        await actor.stop()  # idempotent
        assert actor._task is task
        return verdict, profile

    verdict, profile = asyncio.run(_drive())

    assert isinstance(verdict, GatewayVerdict)
    assert isinstance(profile, RateProfile)
    assert profile.outcome == "no_limiter"
    assert kinds[:2] == ["gateway", "rate_limit"]  # gateway FIRST, rate second
    assert spawns == [actor.thread_id]  # ONE actor task, ONE thread
    assert loaded.count("performing-api-rate-limiting-bypass") == 1
    assert executions, "the deterministic mapping never ran"
    assert actor._replies.try_get_nowait() is None  # no stale reply


def test_rate_turn_prompt_pins_the_second_turn_discipline():
    """Step 4: the rate prompt carries the whole discipline - the generic
    skill, the mapping call, budget-admitted variants, the evidence gate, the
    never-applied rule, and the no-invented-measurements rule."""
    from pathlib import Path

    import polymerhus.recon.control.orchestrator_agent as OA

    text = (
        Path(OA.__file__).resolve().parent
        / "prompts" / "rate-limit-gateway.md"
    ).read_text(encoding="utf-8").lower()
    for needle in (
        "performing-api-rate-limiting-bypass",
        "map_rate_limit",
        "test_rate_limit_variant",
        "evidence gate",
        "never applied",
        "budget",
        "rateloopverdict",
    ):
        assert needle in text, f"the rate prompt never names {needle!r}"


def _drive_rate_only(actor, caplog, **run_kwargs):
    """Drive ONLY the rate turn (no gateway turn) and return the profile."""
    import logging

    async def _drive():
        with caplog.at_level(logging.WARNING):
            return await actor.run_rate_limit(**run_kwargs)

    return asyncio.run(_drive())


def test_rate_turn_wrong_schema_reply_is_conservative_and_loud(tmp_path, caplog):
    """A rate reply carrying the OTHER union variant is a wrong-schema reply:
    drained, logged with a rate-limit-specific reason, and answered with the
    conservative fallback (never unthrottled traffic)."""
    harness, executions = _rate_harness()
    make, _ = _script_model([_verdict_call()])  # a GatewayVerdict, not the rate verdict
    actor = _actor("run1", store=_seeded_store(tmp_path, accounts=_account()),
                   model_factory=make, tmp_path=tmp_path, rate_harness=harness)

    profile = _drive_rate_only(
        actor, caplog, target_key="app.example.com", url="https://app.example.com")

    assert profile.outcome == "failed"
    assert profile.traffic_policy.rate_per_s <= 1.0
    assert "rate-limit" in caplog.text.lower()
    assert "wrong-schema" in caplog.text.lower()
    assert executions == []
    assert actor._replies.try_get_nowait() is None


def test_rate_turn_dead_actor_is_conservative_and_loud(tmp_path, monkeypatch, caplog):
    """A dead actor task is raced, not awaited forever: the rate turn answers
    with the conservative fallback and leaves no stale reply."""
    import polymerhus.app.llm.actor as _A

    harness, executions = _rate_harness()

    async def _dead_actor(*args, **kwargs):
        return None  # the actor task never takes a turn and finishes at once

    monkeypatch.setattr(_A, "run_session_agent", _dead_actor)
    actor = _actor("run1", store=_seeded_store(tmp_path, accounts=_account()),
                   model_factory=_script_model([[]])[0], tmp_path=tmp_path,
                   rate_harness=harness)

    profile = _drive_rate_only(
        actor, caplog, target_key="app.example.com", url="https://app.example.com")

    assert profile.outcome == "failed"
    assert profile.traffic_policy.rate_per_s <= 1.0
    assert "rate-limit" in caplog.text.lower()
    assert executions == []
    assert actor._replies.try_get_nowait() is None


def test_rate_turn_degraded_hook_is_conservative_and_loud(tmp_path, caplog):
    """A raising turn degrades through the delivery hook (a no-decision reply):
    the rate turn answers conservatively and drains."""
    from langchain_core.language_models import BaseChatModel

    harness, executions = _rate_harness()

    class _Boom(BaseChatModel):
        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            raise RuntimeError("rate turn down")

        @property
        def _llm_type(self) -> str:
            return "fake"

    actor = _actor("run1", store=_seeded_store(tmp_path, accounts=_account()),
                   model_factory=lambda role: _Boom(), tmp_path=tmp_path,
                   rate_harness=harness)

    profile = _drive_rate_only(
        actor, caplog, target_key="app.example.com", url="https://app.example.com")

    assert profile.outcome == "failed"
    assert profile.traffic_policy.rate_per_s <= 1.0
    assert "rate-limit" in caplog.text.lower()
    assert executions == []
    assert actor._replies.try_get_nowait() is None


def test_rate_turn_timeout_is_bounded_and_conservative(tmp_path, caplog):
    """The rate await is bounded in wall-clock time: a hung turn returns the
    conservative fallback instead of stalling the run, with no stale reply."""
    from langchain_core.language_models import BaseChatModel

    harness, executions = _rate_harness()

    class _Hung(BaseChatModel):
        async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
            await asyncio.sleep(30)
            return ChatResult(generations=[ChatGeneration(
                message=AIMessage(content="late", tool_calls=[]))])

        @property
        def _llm_type(self) -> str:
            return "fake"

        def bind_tools(self, tools, **kwargs):
            return self

    actor = _actor("run1", store=_seeded_store(tmp_path, accounts=_account()),
                   model_factory=lambda role: _Hung(), tmp_path=tmp_path,
                   rate_harness=harness)

    async def _drive():
        import time
        t0 = time.monotonic()
        with caplog.at_level("WARNING"):
            profile = await actor.run_rate_limit(
                target_key="app.example.com", url="https://app.example.com",
                timeout_s=0.05)
        elapsed = time.monotonic() - t0
        if actor._task is not None and not actor._task.done():
            actor._task.cancel()
        await actor.stop()
        return profile, elapsed

    profile, elapsed = asyncio.run(_drive())

    assert profile.outcome == "failed"
    assert profile.traffic_policy.rate_per_s <= 1.0
    assert elapsed < 5
    assert "rate-limit" in caplog.text.lower()
    assert executions == []
    assert actor._replies.try_get_nowait() is None


def test_await_reply_bounds_each_turn_by_the_timeout_it_is_handed(
    tmp_path, monkeypatch
):
    """Task 5 Interface: `_await_reply(expected_type, timeout_s, label)` bounds
    EACH sequential turn by the timeout it is HANDED - the rate turn rides
    `RATE_LIMIT_AWAIT_TIMEOUT_S` (the operator knob), never the gateway's
    constant. The wait bound is spied on directly so the pin is exact and
    deterministic (a wall-clock lower bound would be flaky under load)."""
    import polymerhus.recon.control.orchestrator_agent as OA
    from polymerhus.app.llm.actor import AgentInbox

    seen: list = []

    async def _spy_wait(tasks, *, timeout=None, return_when=None):
        seen.append(timeout)
        return set(), set()  # neither the reply nor the actor completed

    monkeypatch.setattr(OA.asyncio, "wait", _spy_wait)
    actor = _actor("run1", store=_seeded_store(tmp_path, accounts=_account()),
                   model_factory=_script_model([_rate_verdict_call()])[0],
                   tmp_path=tmp_path)

    async def _drive():
        actor._replies = AgentInbox()
        actor._task = asyncio.ensure_future(asyncio.sleep(30))
        try:
            rate = await actor._await_reply(RateLoopVerdict, 0.8, "rate-limit turn")
            gateway = await actor._await_reply(GatewayVerdict, 12.5, "auth gateway")
        finally:
            actor._task.cancel()
            try:
                await actor._task
            except asyncio.CancelledError:
                pass
        return rate, gateway

    rate, gateway = asyncio.run(_drive())

    assert (rate, gateway) == (None, None)   # a live turn that never replies
    assert seen == [0.8, 12.5], (
        "_await_reply ignored the timeout it was handed for a turn")


def test_rate_turn_browser_only_is_inconclusive_with_zero_executions(tmp_path, caplog):
    """Review Focus: a browser-only target is NOT HTTP-replayable - the rate
    turn reports `inconclusive` and runs ZERO Vegeta experiments (no turn is
    even taken), leaving the conservative pacing policy in force."""
    harness, executions = _rate_harness()
    make, seen = _script_model([_rate_verdict_call()])
    actor = _actor("run1", store=_seeded_store(tmp_path, accounts=_account()),
                   model_factory=make, tmp_path=tmp_path, rate_harness=harness)

    profile = _drive_rate_only(
        actor, caplog, target_key="app.example.com", url="https://app.example.com",
        browser_only=True)

    assert profile.outcome == "inconclusive"
    assert "browser-only" in profile.reason.lower()
    assert profile.traffic_policy.rate_per_s <= 1.0
    assert executions == []           # ZERO Vegeta executions
    assert seen["bound"] == []        # no actor turn was taken at all
    assert actor._task is None


def test_rate_profile_merges_controller_truth_over_the_model_claim(tmp_path):
    """Step 5: the model interprets; it cannot overwrite a measurement or mint
    a bypass finding. A claim naming an experiment that never ran is dropped,
    and the numbers stay the controller's."""
    harness, _ = _rate_harness()
    make, _ = _script_model(
        [{"name": "map_rate_limit", "args": {}, "id": "m"}],
        [_rate_verdict_call(outcome="mapped", bypass_outcome="confirmed",
                            confirmed_variant_ids=["never-ran"],
                            interpretation="I bypassed the limiter")],
    )
    actor = _actor("run1", store=_seeded_store(tmp_path, accounts=_account()),
                   model_factory=make, tmp_path=tmp_path, rate_harness=harness)

    async def _drive():
        profile = await actor.run_rate_limit(
            target_key="app.example.com", url="https://app.example.com")
        await actor.stop()
        return profile

    profile = asyncio.run(_drive())

    assert profile.outcome == "no_limiter"          # the controller's truth
    assert profile.bypass_outcome != "confirmed"    # the claim is not a finding
    assert profile.bypass_findings == []
    assert profile.traffic_policy.rate_per_s == 20.0  # the tested ceiling, not a claim
