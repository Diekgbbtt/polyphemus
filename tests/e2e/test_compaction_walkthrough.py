"""E2E walkthrough (#95 D9): compaction fires in BOTH production consumer state machines.

Two consumers are wired (ADR D9): the hunting hunter's async actor lane
(`HuntingHunterActor` -> `run_session_agent`) and the analysis mechanism-typist's
CHAINED session lane (`stateful_invoke_fn` -> `stateful_turn` -> `run_session_turn`).
This file drives BOTH through their REAL consumer entry points - no faked
`stateful_turn`, no inlined middleware - against the real session loop and a
realistic model, asserting the observable outcome (a running-summary message on the
thread / the manager's last report with reclaimed tokens).

Why a scripted model rather than a live provider call: the runtime condition
compaction READS is per-step occupancy (the provider's `input_tokens` + `cache_read`
usage metadata), not the model's text. A scripted ChatOpenAI-shaped fake emitting
realistic usage metadata therefore reproduces the runtime condition exactly, while a
live provider call adds only latency and a free-tier rate limit - never a different
code path. Everything else is the real deployed wiring: the consumer entry points,
the role middleware builder, and the `create_agent` loop.

The mechanism-typist lane is exercised the way the agent actually runs: the real
3-call `type_mechanisms` chain (reflection -> systems extraction -> services
linking) over TWO realistic `service` chunks, all on ONE growing session thread - so
this is a genuinely multi-step session whose context crosses the budget repeatedly
and compacts MULTIPLE times into progressively richer running summaries.

The hunting hunter lane still runs its one author+judge turn pair (the lane's
tool-calling reasoning chains await the parallel tool-support work; once tool
support lands, the hunter test here grows its own multi-step tool chains).

Runs in-network (the sanctioned e2e runner, `docker compose run --rm tests`) against
the real checkpointer resolution; the compaction component is checkpointer-agnostic,
so the in-process saver the consumers resolve is the honest seam.
"""
from __future__ import annotations

import asyncio
import json

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.checkpoint.memory import InMemorySaver

from polymerhus.app.llm import compaction as C
from polymerhus.app.llm.session import read_session_memory
from polymerhus.attack.hunting import llm as HL
from polymerhus.attack.hunting.actors import HuntingHunterActor

from polymerhus.analysis.analyser_types import L1DeltaBatch, SystemEdgeProposal, SystemProposal
from polymerhus.analysis.chunking import Chunk
from polymerhus.analysis.mechanism_typist import stateful_invoke_fn, type_mechanisms
from polymerhus.recon.domain.types import AssetDelta, Observation

GOOD_SUMMARY_TEXT = (
    "The hunter enumerated three auth endpoints and patched two; the login "
    "flow still exposes the third path to close."
)
RESUME_POINT = "resume from the login-flow patch on endpoint three"

AUTHOR_BODY = json.dumps({
    "target_identity": {"url": "http://a/", "unit_id": "Service:slug:a"},
    "rationale": "spec " + ("long-reasoning-trail " * 400),
})
JUDGE_BODY = json.dumps({"meaningful_insight": False, "next_step": "end", "rationale": "r"})


def _usage(input_tokens, output_tokens=0, cache_read=0):
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
        "input_token_details": {"cache_read": cache_read},
    }


# --- the hunting hunter lane (author + judge; tool chains await tool support) ---

class _RealisticModel(BaseChatModel):
    """A ChatOpenAI-shaped fake emitting REAL per-step usage metadata.

    Turn calls return a long answer carrying the occupancy the ledger reads; the
    compaction summariser's structured call (whose composed user message opens with
    the running-summary preamble) returns a `SummaryUpdate` tool call."""

    body: str = ""
    objective: str = GOOD_SUMMARY_TEXT
    resume_point: str = RESUME_POINT
    usage: dict | None = None

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        if any(isinstance(m, HumanMessage)
               and str(m.content or "").startswith("Prior running summary:")
               for m in messages):
            return ChatResult(generations=[ChatGeneration(message=AIMessage(
                content="",
                tool_calls=[{"name": "SummaryUpdate", "args": {
                    "objective": self.objective, "resume_point": self.resume_point,
                    "decisions": ["keep it"]},
                    "id": "sum", "type": "tool_call"}]))])
        return ChatResult(generations=[ChatGeneration(message=AIMessage(
            content=self.body, usage_metadata=self.usage))])

    @property
    def _llm_type(self) -> str:
        return "fake"

    def bind_tools(self, tools, **kwargs):
        return self


def _turn_factory(bodies, usage):
    cursor = {"i": 0}

    def make(role_id):
        i = cursor["i"]
        cursor["i"] = i + 1
        return _RealisticModel(body=bodies[min(i, len(bodies) - 1)], usage=usage)

    return make


def test_hunter_tool_calling_lane_compacts_e2e(monkeypatch):
    """D9 consumer 1 (async actor): an over-budget author turn on the per-hunt
    `HuntingHunterActor` spawns the out-of-band pass, the judge's barrier awaits and
    applies it, and BOTH turns still parse - the actor lane runs compacted, observable
    through the manager's last report (D11)."""
    import polymerhus.app.llm.providers as P

    monkeypatch.setenv("LLM_MODEL_HUNTING_HUNTER", "opencode:gpt-test")
    monkeypatch.delenv("LLM_GATEWAY_URL", raising=False)

    def spy(provider, model, **kw):
        return _RealisticModel(body="", objective=GOOD_SUMMARY_TEXT)

    monkeypatch.setattr(P, "build_chat_model", spy)

    window = C.CompactionWindow(context_limit=1000, threshold=0.9)
    mw = HL.build_hunter_compaction_middleware(
        window=window, store=C.InMemoryToolOutputStore())

    async def drive():
        actor = HuntingHunterActor(
            "run-e2e-hunter", "hunt-x", checkpointer=InMemorySaver(),
            model_factory=_turn_factory([AUTHOR_BODY, JUDGE_BODY], _usage(1000, output_tokens=10)),
            observe=False, compaction=mw)
        spec = await actor.author("compose the spec")
        verdict = await actor.judge("judge the result")
        await actor.stop()
        return actor, spec, verdict

    actor, spec, verdict = asyncio.run(drive())
    assert spec == json.loads(AUTHOR_BODY)
    assert verdict == json.loads(JUDGE_BODY)
    report = mw.manager.last_report(actor.thread_id)
    assert report is not None
    assert report.readability == C.READABILITY_COMPACTED
    assert report.summary_status == "ok"
    assert report.reclaimed_tokens > 0


# --- the mechanism-typist lane (the real 3-call chain over two realistic chunks) --

_BASEURL = "https://soupmarket.shop"

# A realistic account/auth + checkout surface: real endpoints, parameters, headers,
# a session cookie, and adversarial observations - the material the running summary
# genuinely condenses (never placeholder noise).
_SURFACE_ACCOUNT = tuple([
    AssetDelta(type="Endpoint",
               identity={"path": "/rest/user/login", "method": "POST", "baseurl": _BASEURL},
               props={"content_type": "application/json", "server": "nginx", "status_code": 200}),
    AssetDelta(type="Endpoint",
               identity={"path": "/rest/user/register", "method": "POST", "baseurl": _BASEURL},
               props={"content_type": "application/json", "server": "nginx", "status_code": 200}),
    AssetDelta(type="Endpoint",
               identity={"path": "/rest/user/whoami", "method": "GET", "baseurl": _BASEURL},
               props={"content_type": "application/json", "server": "nginx", "status_code": 200}),
    AssetDelta(type="Parameter",
               identity={"name": "email", "position": "body", "endpoint_path": "/rest/user/login", "baseurl": _BASEURL}),
    AssetDelta(type="Parameter",
               identity={"name": "password", "position": "body", "endpoint_path": "/rest/user/login", "baseurl": _BASEURL}),
    AssetDelta(type="Header",
               identity={"name": "Cookie", "value": "session=<opaque>", "baseurl": _BASEURL}),
    AssetDelta(type="Header",
               identity={"name": "X-Requested-With", "value": "XMLHttpRequest", "baseurl": _BASEURL}),
])

_SURFACE_CHECKOUT = tuple([
    AssetDelta(type="Endpoint",
               identity={"path": "/api/orders", "method": "POST", "baseurl": _BASEURL},
               props={"content_type": "application/x-www-form-urlencoded", "server": "nginx", "status_code": 200}),
    AssetDelta(type="Endpoint",
               identity={"path": "/api/BasketItems", "method": "POST", "baseurl": _BASEURL},
               props={"content_type": "application/json", "server": "nginx", "status_code": 200}),
    AssetDelta(type="Parameter",
               identity={"name": "items", "position": "body", "endpoint_path": "/api/BasketItems", "baseurl": _BASEURL}),
    AssetDelta(type="Parameter",
               identity={"name": "addressId", "position": "body", "endpoint_path": "/api/orders", "baseurl": _BASEURL}),
    AssetDelta(type="Header",
               identity={"name": "Cookie", "value": "session=<opaque>", "baseurl": _BASEURL}),
])

_OBS_ACCOUNT = Observation(
    macro_kind="authentication", severity="medium",
    evidence="response sets session=<opaque> without HttpOnly",
    rationale="login/register/whoami share one session-cookie identity raft.",
    anchor={"type": "BaseURL", "identity": {"url": _BASEURL}},
    source_job="katana", source_tool="httpx",
)

_OBS_CHECKOUT = Observation(
    macro_kind="access-control", severity="high",
    evidence="orders accept a client-supplied addressId and item set",
    rationale="checkout reads basket via a client-supplied items parameter on one shared identity.",
    anchor={"type": "BaseURL", "identity": {"url": _BASEURL}},
    source_job="katana", source_tool="httpx",
)

# The services 'account' + 'checkout' aggregate these enpoints (via the Assigner's
# prior AGGREGATES); the typist links Systems onto them.
_AGGREGATIONS = [
    {"slug": "account", "labels": ["Endpoint"], "props": {"path": "/rest/user/login", "baseurl": _BASEURL}},
    {"slug": "account", "labels": ["Endpoint"], "props": {"path": "/rest/user/register", "baseurl": _BASEURL}},
    {"slug": "account", "labels": ["Endpoint"], "props": {"path": "/rest/user/whoami", "baseurl": _BASEURL}},
    {"slug": "checkout", "labels": ["Endpoint"], "props": {"path": "/api/orders", "baseurl": _BASEURL}},
    {"slug": "checkout", "labels": ["Endpoint"], "props": {"path": "/api/BasketItems", "baseurl": _BASEURL}},
]
_INVENTORY = {"services": ["account", "checkout"], "systems": [], "system_descriptions": {}}


def _scripted_typing_model(summarise_state):
    """The mechanism-typist lane's scripted model. Routes on the composed prompt:
    - the SUMMARISER's structured call (user message opens with the running-summary
      preamble) -> ONE rich, realistic `SummaryUpdate` per pass (its content derives
      from the session material, so the running summary is a genuine condensation);
    - the typist's REFLECTION turn (free prose) -> a realistic mechanism hypothesis;
    - the EXTRACTION (`L1DeltaBatch`) and LINKING (`L1DeltaBatch`) structured turns
      -> tool calls holding real systems / system_edges.
    Realistic per-call usage metadata advances a shared cursor, so the accumulated
    context crosses the budget on repeated turns and compaction fires more than once.
    """
    usage_plan = [_usage(1900, output_tokens=320), _usage(2100, output_tokens=280),
                  _usage(2300, output_tokens=300), _usage(2600, output_tokens=340),
                  _usage(2400, output_tokens=290), _usage(2800, output_tokens=310)]

    def summarise_args():
        return {
            "objective": (
                "Type the soupmarket shared mechanisms across the account/auth and checkout "
                "surfaces: keep the JSON REST API overlay (RESTApi), the session-cookie "
                "IdentificationSystem and the credential AuthenticationMechanism shared, plus "
                "the login page-cluster WebPresentation for the account service."),
            "resume_point": "Link checkout to RESTApi (EXPOSED_VIA); keep auth off checkout.",
            "workflow": "reflection -> systems extraction -> services linking",
            "environment_state": "account/auth REST surface + checkout order/basket surface typed",
            "task_status": {"done": ["session-cookie identification named"],
                            "in_progress": ["linking checkout to RESTApi"],
                            "remaining": ["reconcile WebPresentation cluster"]},
            "dead_branches": [], "decisions": ["shared identity across surfaces"],
            "artifacts": ["RESTApi", "IdentificationSystem", "AuthenticationMechanism"],
        }

    class _TypistModel(BaseChatModel):
        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            humans = [str(m.content or "") for m in messages if isinstance(m, HumanMessage)]
            joined = " ".join(humans)
            if any(h.startswith("Prior running summary:") for h in humans):
                summarise_state["passes"] = summarise_state.get("passes", 0) + 1
                args = summarise_args()
                return ChatResult(generations=[ChatGeneration(message=AIMessage(
                    content="",
                    tool_calls=[{"name": "SummaryUpdate", "args": args,
                                 "id": "sum", "type": "tool_call"}]))])
            if "TASK - EXTRACT SYSTEMS" in joined:
                # #99 negotiation: a no-tools structured session turn on the
                # unknown profile resolves ProviderStrategy (json_schema), so the
                # fake must return content-JSON, NOT tool_calls - the Provider
                # strategy branch parses `output.content` and never looks at
                # tool_calls (langchain create_agent `_handle_model_output`).
                systems_json = json.dumps({"systems": [
                    {"kind": "RESTApi", "props": {"description": "JSON REST paradigm the app exposes through."}},
                    {"kind": "IdentificationSystem", "props": {"description": "Cookie/session identity raft."}},
                    {"kind": "AuthenticationMechanism", "props": {"description": "Credential mint + validate."}},
                    {"kind": "WebPresentation", "discriminator": "account::login",
                     "props": {"pages": ["/rest/user/login", "/rest/user/register"]}},
                ]})
                return ChatResult(generations=[ChatGeneration(
                    message=AIMessage(content=systems_json))])
            if "TASK - LINK SERVICES" in joined:
                edges_json = json.dumps({"system_edges": [
                    {"service_slug": "account", "kind": "RESTApi", "rel": "EXPOSED_VIA"},
                    {"service_slug": "account", "kind": "IdentificationSystem", "rel": "IDENTIFIED_BY"},
                    {"service_slug": "account", "kind": "AuthenticationMechanism", "rel": "AUTHENTICATED_BY"},
                    {"service_slug": "checkout", "kind": "RESTApi", "rel": "EXPOSED_VIA"},
                    {"service_slug": "account", "kind": "WebPresentation", "discriminator": "account::login",
                     "rel": "EXPOSED_VIA"},
                ]})
                return ChatResult(generations=[ChatGeneration(
                    message=AIMessage(content=edges_json))])
            i = summarise_state.get("turn", 0)
            summarise_state["turn"] = i + 1
            usage = usage_plan[i % len(usage_plan)]
            return ChatResult(generations=[ChatGeneration(message=AIMessage(
                content=(
                    "The login/register/whoami trio with a shared session cookie evidence a RESTApi "
                    "overlay carrying an IdentificationSystem identity raft, minted through an "
                    "AuthenticationMechanism on credential exchange; the orders/basket API shares the "
                    "same identity but owns no auth of its own. No WAF is evidenced on the surface."
                ),
                usage_metadata=usage))])

        @property
        def _llm_type(self) -> str:
            return "fake"

        def bind_tools(self, tools, **kwargs):
            return self

    return _TypistModel


# The filter `drop_unknown_vocabulary` at the end of `type_mechanisms` already gates
# every emitted kind/rel to the controlled vocabularies, so the scripted systems and
# edges above are exactly the typed, vocabulary-valid set the sole-writer accepts.


def test_mechanism_typist_chained_lane_compacts_e2e(monkeypatch):
    """D9 consumer 2 (chained session): the REAL 3-call mechanism-typist chain
    (`type_mechanisms`) runs over TWO realistic `service` chunks on ONE growing
    session thread - SIX prompts on the same thread, multiple over-budget turns,
    MULTIPLE out-of-band running-summary passes. The chain survives every
    compaction (both chunks still type real Systems + edges), the compacted thread
    carries the synthetic running-summary message, and the passes are observable
    both on the manager's last report and in the number of summariser calls."""
    import polymerhus.app.llm.providers as P
    import polymerhus.app.llm.roles as R

    monkeypatch.setenv("LLM_MODEL_ANALYSER", "opencode:gpt-test")
    monkeypatch.delenv("LLM_GATEWAY_URL", raising=False)
    # The default analyser window is a production context budget; a tiny threshold
    # makes the scripted (realistic-but-small) usages cross it reliably so the pass
    # fires on repeated turns without building megabyte prompts.
    monkeypatch.setenv("LLM_COMPACTION_THRESHOLD", "0.01")

    summarise_state: dict = {}
    model_cls = _scripted_typing_model(summarise_state)

    def spy(provider, model, **kw):
        return model_cls()

    # The turn model resolves through `chat_model_for` (which holds a module-level
    # `build_chat_model` reference) while the summariser resolves the provider's
    # `build_chat_model` lazily - patch both so the chained lane is fully faked.
    monkeypatch.setattr(P, "build_chat_model", spy)
    monkeypatch.setattr(R, "build_chat_model", spy)

    saver = InMemorySaver()
    invoke = stateful_invoke_fn("run-e2e-typist", saver)

    chunk1 = Chunk(chunk_id="katana:service:0", source_job="katana",
                   assets=_SURFACE_ACCOUNT, observations=(_OBS_ACCOUNT,))
    chunk2 = Chunk(chunk_id="katana:service:1", source_job="katana",
                   assets=_SURFACE_CHECKOUT, observations=(_OBS_CHECKOUT,))

    batch1 = type_mechanisms(chunk1, invoke_fn=invoke,
                             inventory=_INVENTORY, aggregations=_AGGREGATIONS)
    batch2 = type_mechanisms(chunk2, invoke_fn=invoke,
                             inventory=_INVENTORY, aggregations=_AGGREGATIONS)

    # The chain survived every compaction: both chunks still typed REAL systems and
    # edges (this is the observable correctness under compaction).
    kinds1 = {s.kind for s in batch1.systems}
    kinds2 = {s.kind for s in batch2.systems}
    assert "RESTApi" in kinds1 and kinds2
    assert "IdentificationSystem" in kinds1
    assert batch1.system_edges and batch2.system_edges
    assert any(e.rel == "EXPOSED_VIA" and e.service_slug == "checkout"
               for e in batch2.system_edges)

    # The ledger really observed per-turn occupancy (the compact trigger).
    thread_id = "run-e2e-typist:mechanism_typist"
    mem = read_session_memory(saver, thread_id)
    assert mem is not None
    contents = [str(m.content) for m in mem.messages]
    assert any(c.startswith("[running summary]") for c in contents), \
        "the compacted thread must carry the synthetic running-summary message"
    # The produced summary is the REALISTIC condensation of the session material
    # rendered as markdown with headers and sub-lists.
    joined = "".join(contents)
    assert "## Objective" in joined
    assert "## Previous Decisions with Rationale" in joined
    assert "## Discovered Crucial Artifacts" in joined
    assert "- " in joined  # markdown list elements
    assert "RESTApi" in joined

    # MULTIPLE passes: the summariser was called more than once (each call = one
    # out-of-band running-summary pass), so the multi-turn context compacted more
    # than a single time.
    assert summarise_state.get("passes", 0) >= 2, \
        f"expected multiple compaction passes, saw {summarise_state.get('passes', 0)}"