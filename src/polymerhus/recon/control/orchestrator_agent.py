"""Recon-orchestrator agent: the run's auth gateway and rate mapper (#223, #238).

The orchestrator is the SOLE auth-gateway decider (D223-8): on run start,
before phase 0, it runs ONE stateful gateway turn - the authn loop - that
establishes or validates the run's auth state against the shared auth store
and the project's `authn` skill, then closes with the structured
`GatewayVerdict`. The pipeline obeys the verdict (prunes what it excludes,
binds the account identifier); no second decision point exists downstream.

Since #238 the SAME actor then takes a SECOND turn on the same session/thread:
the rate-limit turn (`run_rate_limit`) measures the target's limiter under the
authenticated context the gateway just selected and closes with the structured
`RateLoopVerdict`. The deterministic controller (Task 4's `RateLimitHarness`)
owns every traffic number; the model only picks bounded bypass variants and
interprets the evidence. Both turns negotiate ONE response format over the
fixed union `GatewayVerdict | RateLoopVerdict`, and one generic reply kind
delivers whichever variant the current turn produced.

The actor is a MAILBOX ACTOR (#94, feat/async-actor-agents): one persistent
`run_session_agent` on the `job_orchestrator` session role per recon run
(`OrchestratorSession(run_id)` thread), fed the gateway brief and then the
rate brief via its inbox, replying each verdict on the SAME thread.
`run_pipeline` drives it through `run_gateway` and `run_rate_limit`
(production defaults); `stop` reaps it.

Arming (D223-13): the roster exemption is lifted through the write-capable
auth binding - the shared `auth_store` tool, the project's `authn` skill,
`load_skill`, `write_skill`, the Kali exec capability, and the Steel exec
gateway - attached through the native `tools=` / `middleware=` / `context=`
seams, plus (#238) the two deterministic rate-limit tools `map_rate_limit`
and `test_rate_limit_variant`. The tool set is fixed at construction; no
per-turn surface exists.

The loop (D223-15) is one ReAct turn tracked by a hunting-style passive
state machine (`authn_loop.py`): the `build_authn_loop_middleware`
observes the turn's own tool calls, detection is a pure function of each
call, pushes never gate or reject (the no-block invariant), and each
transition hint rides its TRIGGERING tool result only.

Fail-open (D223-10): the gateway rides the harness failure suite; when that
is exhausted the run proceeds unauthenticated with all phases, loudly. The
gateway-specific requirements live here: the await is bounded in wall-clock
time and drains rather than leaving a stale reply, wrong-schema replies are
logged loudly, and the missing-data gate discriminates structurally before
any turn (no-auth-surface skips the loop and records itself; missing
credentials stop the run loudly via `GatewayStop`, outside D223-2 fail-open).
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Mapping, Sequence

from polymerhus.recon.control.authn_loop import (
    GatewayVerdict,
    PROBE_TOOLS,
    classify_gate,
    detect_transition,
    initial_state,
    push_transition,
    select_branch,
    wrap_hint,
)

logger = logging.getLogger(__name__)

# --- the gateway prompt (module-owned, role-prompt convention) ----------------

_GATEWAY_PROMPT: str | None = None
_RATE_LIMIT_PROMPT: str | None = None
_ORCHESTRATOR_PROMPT: str | None = None


def _load_gateway_prompt() -> str:
    """The gateway system prompt, read directly from this module's `prompts/`
    dir. Memoized on first call (no import-time I/O); FAIL-CLOSED - a missing
    prompt file raises instead of degrading, so the gateway never reasons
    without its discipline."""
    global _GATEWAY_PROMPT
    if _GATEWAY_PROMPT is None:
        from pathlib import Path  # noqa: PLC0415 - lazy, mirrors the reader convention
        _GATEWAY_PROMPT = (
            Path(__file__).resolve().parent / "prompts" / "auth-gateway.md"
        ).read_text(encoding="utf-8")
    return _GATEWAY_PROMPT


def _load_rate_limit_prompt() -> str:
    """The rate-limit turn's static discipline (#238), read from this module's
    `prompts/` dir. Memoized on first call (no import-time I/O); FAIL-CLOSED,
    like the gateway prompt: a missing file raises rather than letting the rate
    turn reason without its budget/variant/evidence-gate discipline."""
    global _RATE_LIMIT_PROMPT
    if _RATE_LIMIT_PROMPT is None:
        from pathlib import Path  # noqa: PLC0415 - lazy, mirrors the reader convention
        _RATE_LIMIT_PROMPT = (
            Path(__file__).resolve().parent / "prompts" / "rate-limit-gateway.md"
        ).read_text(encoding="utf-8")
    return _RATE_LIMIT_PROMPT


def _load_orchestrator_prompt() -> str:
    """The actor's ONE system prompt: the gateway discipline followed by the
    rate-limit discipline (#238).

    The two turns ride one session/thread, so the session seam carries one
    system message. Both static disciplines live there and each turn's brief
    selects which applies - the alternative (a per-turn system prompt) is not
    expressible on one `run_session_agent`. Memoized, fail-closed."""
    global _ORCHESTRATOR_PROMPT
    if _ORCHESTRATOR_PROMPT is None:
        _ORCHESTRATOR_PROMPT = (
            f"{_load_gateway_prompt()}\n\n---\n\n{_load_rate_limit_prompt()}"
        )
    return _ORCHESTRATOR_PROMPT


def _rate_limit_budget():
    """The operator's typed safety budget, resolved LAZILY from the recon
    config (construction reads no configuration)."""
    from polymerhus.recon.config import rate_limit_safety_budget  # noqa: PLC0415
    return rate_limit_safety_budget()


def _rate_turn_timeout_s() -> float:
    """The wall-clock bound on the rate turn's await: the operator knob
    `RATE_LIMIT_AWAIT_TIMEOUT_S` (default 1800s), resolved lazily."""
    from polymerhus.recon.config import RATE_LIMIT_AWAIT_TIMEOUT_S  # noqa: PLC0415
    return float(RATE_LIMIT_AWAIT_TIMEOUT_S)


class _RateHarnessSlot:
    """A stable handle for the actor's rate-limit tools (#238).

    The actor's tool surface is FIXED when its session agent starts - and the
    gateway is its first turn - while the concrete `RateLimitHarness` cannot
    exist before the gateway has selected the authenticated context and the
    pipeline has resolved the run's canonical target. The slot is what the
    bound `map_rate_limit` / `test_rate_limit_variant` tools close over:
    `run_rate_limit` binds the concrete harness BEFORE it delivers the rate
    brief, so a tool call always meets one. A call arriving before any bind
    (which neither brief ever issues) raises loudly instead of measuring an
    unconfigured target.
    """

    def __init__(self, harness=None):
        self._harness = harness

    @property
    def bound(self) -> bool:
        return self._harness is not None

    def bind(self, harness):
        self._harness = harness
        return harness

    def _require(self):
        if self._harness is None:
            raise RuntimeError(
                "rate-limit harness is not bound: the rate turn binds it before "
                "delivering the rate brief"
            )
        return self._harness

    async def map(self):
        return await self._require().map()

    async def judge_variant(self, mutation):
        return await self._require().judge_variant(mutation)


# --- the authn-loop harness middleware (the hunting pod-harness precedent) ------


def build_authn_loop_middleware():
    """Build the gateway turn's loop tracker: a `wrap_tool_call` middleware
    over the turn's own tool surface that observes each call, pushes the
    passive state machine, and appends the transition hint to the TRIGGERING
    result only (consumed immediately, never leaked). Fresh instance per
    gateway turn; the harness is the sole writer of the tracker. Fail-open
    throughout: an unobservable call passes through untouched, never raises
    into the loop."""
    from langchain.agents.middleware import AgentMiddleware  # noqa: PLC0415

    class _AuthnLoopMiddleware(AgentMiddleware):
        """One gateway turn's tracker: the passive detect/push machine plus
        the hint injection onto the triggering result."""

        def __init__(self):
            self.tracker = initial_state()

        @property
        def phase(self):
            return self.tracker["phase"]

        def _observe(self, tool_name: str, args: Any, result: Any) -> str | None:
            """Push one observed call through the machine; return the hint
            for the triggering result (None when this call carries none)."""
            try:
                observation = {"tool": tool_name, "args": args or {}, "result": result}
                transition = detect_transition(observation)
                self.tracker = push_transition(self.tracker, transition, observation)
                return self.tracker.get("injected_hint")
            except Exception:  # noqa: BLE001 - tracking never breaks the turn
                logger.warning("authn loop tracking degraded on %r", tool_name)
                return None

        def _attach(self, response: Any, hint: str | None) -> Any:
            """Append the hint to the triggering response: string content
            grows the wrapped hint inline; list content gains a text block.
            Any other shape passes through with a loud line (the tracker still
            moved - injection is advisory, tracking is authoritative)."""
            if not hint:
                return response
            try:
                from langchain_core.messages import ToolMessage  # noqa: PLC0415
                if isinstance(response, ToolMessage):
                    if isinstance(response.content, str):
                        return response.model_copy(update={
                            "content": f"{response.content}\n\n{wrap_hint(hint)}"})
                    if isinstance(response.content, list):
                        return response.model_copy(update={
                            "content": [*response.content,
                                        {"type": "text", "text": wrap_hint(hint)}]})
                logger.warning(
                    "authn loop hint unattachable (response shape %s); "
                    "tracker moved, hint dropped", type(response).__name__)
            except Exception:  # noqa: BLE001 - injection never breaks the turn
                logger.warning("authn loop hint injection degraded")
            return response

        def _run(self, tool_call: Any, response: Any) -> Any:
            name = tool_call.get("name") if isinstance(tool_call, dict) else None
            args = tool_call.get("args") if isinstance(tool_call, dict) else {}
            return self._attach(response, self._observe(name, args, response))

        def wrap_tool_call(self, request, handler):
            return self._run(request.tool_call, handler(request))

        async def awrap_tool_call(self, request, handler):
            return self._run(request.tool_call, await handler(request))

    return _AuthnLoopMiddleware()


# --- the gateway brief ----------------------------------------------------------

# The per-directive manner instruction riding the turn's HumanMessage (the
# static discipline lives in the prompt file; only the run facts vary here).
_BRANCH_MANNER = {
    "request": (
        "No blocking defence recorded. Validate by replaying the account's "
        "stored request state (snapshot headers/cookies, tokens) with the "
        "Kali exec capability. Request phases stay released."),
    "browser_only": (
        "Browser-only target (the defence is not HTTP-replayable). Validate "
        "EXCLUSIVELY through the Steel path: mount the persisted profile (or "
        "mint under the project-scoped key with --update-profile), navigate, "
        "verify the session. Never validate with request tools. Request "
        "phases will be pruned; only the Steel crawl runs."),
    "request_browser_first": (
        "Replayable defence. Validate browser-first: mount the account "
        "profile, verify the session, compare against the stored tokens and "
        "persist what changed, then release request collection."),
    "resolve_in_loop": (
        "Replayability UNKNOWN. Attempt the fingerprint replay from the "
        "browser state per the authn skill: replayable releases the request "
        "branch (record replayability true), not replayable prunes to "
        "browser-only (record false). Persist the resolved fact to the "
        "overview with an auth_store write (your write merges; the operator "
        "stamp stays), and record the resolution loudly in the rationale "
        "and verdict."),
}


def _gateway_human(*, project_id: str, directive: str, candidate: str | None) -> Any:
    """The gateway brief handed to the model: the run facts (project, branch
    manner, deterministic candidate) with the verdict instruction. The brief
    carries NO store contents - the model grounds itself through its own
    reads, which is what the loop tracker observes."""
    from langchain_core.messages import HumanMessage  # noqa: PLC0415
    manner = _BRANCH_MANNER.get(directive, _BRANCH_MANNER["request"])
    selection = (
        f"Candidate account (most recently updated usable): {candidate}."
        if candidate else
        "No usable account on record: mint one through the sign-in procedure.")
    return HumanMessage(content=(
        f"Auth gateway for project {project_id}.\n\n"
        f"Branch directive: {directive}.\n{manner}\n\n"
        f"{selection}\n\n"
        "Ground (overview read + authn skill load), validate before sign-in, "
        "assert the outcome in the store, run the outer skill-judging loop, "
        "then emit the GatewayVerdict."))


def _rate_human(*, project_id: str, target_key: str, url: str) -> Any:
    """The rate turn's brief: the run facts plus the per-turn instruction.

    The STATIC discipline lives in the prompt file; only the run facts and the
    turn's ordered obligation vary here. The brief carries no store contents,
    no credentials and no measurements - the model grounds itself through the
    two deterministic tools."""
    from langchain_core.messages import HumanMessage  # noqa: PLC0415
    return HumanMessage(content=(
        f"Rate-limit mapping for project {project_id}, target {target_key} "
        f"({url}).\n\n"
        "This is the post-authentication rate-limit turn on the same session "
        "as the auth gateway.\n"
        "1. Load the generic `performing-api-rate-limiting-bypass` procedure.\n"
        "2. Call `map_rate_limit` EXACTLY ONCE. The controller owns every "
        "count, rate, duration, concurrency and the overall budget - never "
        "propose a traffic number.\n"
        "3. If the mapping shows a limiter, probe the bounded variants the "
        "budget admits with `test_rate_limit_variant`, one call per variant; "
        "identity-header mutations are refused unless the operator opted in.\n"
        "4. Apply the evidence gate: a variant is a `confirmed` finding only "
        "when every gate passes. A finding is EVIDENCE ONLY - it is never "
        "applied to the run's traffic.\n"
        "5. Emit the `RateLoopVerdict`: name the experiment ids you used and "
        "interpret them. Never invent a measurement you did not receive, and "
        "never repeat credentials, request bodies or raw responses."))


# --- the mailbox actor ------------------------------------------------------------

_GATEWAY_KIND = "gateway"
_RATE_KIND = "rate_limit"
# ONE generic reply kind for BOTH sequential turns (#238): the delivery
# middleware forwards whichever union variant the current turn produced, and
# each turn's waiter validates the type it expects.
_REPLY_KIND = "orchestrator_reply"
_REPLY_SOURCE = "recon-orchestrator"

# The wall-clock bound on the gateway await (D223-10): a hung turn returns
# None (fail-open, loudly) instead of stalling run start. Sized above any
# legitimate sign-in span - the turn's own harness bounds (recursion limit,
# escalating per-attempt budgets) own turn length; this only bounds the WAIT.
GATEWAY_AWAIT_TIMEOUT_S = 3600.0


class GatewayStop(Exception):
    """The fail-close stop: the project declares an auth surface but stores
    no credentials at all - a missing bootstrap prerequisite, not a gateway
    failure, so D223-2 fail-open collection does not apply. The pipeline
    catches this, marks the run failed loudly, and runs nothing."""


async def _fetch_kali_tools() -> list:
    """Fetch the Kali exec surface from the Kali MCP gateway (the
    `pod.default_exec_fn` precedent: lazily built per use, never at import).
    The names are the shared `PROBE_TOOLS` the detector matches, so a rename
    cannot drift the filter apart from the state machine. Fail-open to [] -
    the gateway still runs its store/skill span and the verdict carries the
    degradation loudly."""
    try:
        from langchain_mcp_adapters.client import MultiServerMCPClient  # noqa: PLC0415
        from polymerhus.app.config import config  # noqa: PLC0415

        client = MultiServerMCPClient(
            {"kali": {"url": config.KALI_MCP_URL, "transport": "streamable_http"}})
        tools = await client.get_tools()
        return [t for t in tools if t.name in PROBE_TOOLS]
    except Exception:  # noqa: BLE001 - fail-open, loudly
        logger.warning(
            "auth gateway: kali exec tools unavailable; gateway proceeds "
            "store+skill only (fail-open, loudly)", exc_info=True)
        return []


class ReconOrchestratorActor:
    """The recon-orchestrator as the auth gateway: a persistent MAILBOX actor (#94).

    ONE actor per recon run: `run_pipeline` constructs it (production default)
    and drives exactly ONE gateway turn via `run_gateway` before phase 0 - the
    authn loop over the armed surface, closing with the structured
    `GatewayVerdict` on the run's `OrchestratorSession` thread. `stop` reaps
    the task; safe to call when the actor never spawned (the loop-skipped
    no-surface path never spawns it).

    Seams (CODING_STANDARD 6): `checkpointer` / `model_factory` /
    `auth_store` / `skill_store` / `kali_tools` inject fakes (tests); None
    resolves the production collaborator lazily in `_ensure_started` (MCP
    fetch for the Kali tools) or at the gateway pre-read (tool-owned project
    scope). Fail-open: a dead/crashed actor (LLM error, parse error, harness
    error, bounded-await timeout) maps to a None verdict - the pipeline runs
    every phase unauthenticated, loudly - except the missing-credentials
    prerequisite, which stops the run via `GatewayStop`."""

    def __init__(
        self,
        run_id: str,
        *,
        project_id: str | None = None,
        checkpointer=None,
        model_factory=None,
        observe: bool = True,
        compaction=None,
        auth_store=None,
        skill_store=None,
        kali_tools: list | None = None,
        rate_harness=None,
    ):
        # Construction must perform NO imports (CODING_STANDARD 6): the actor is
        # built at run_pipeline START on the event loop, and importing
        # `polymerhus.app.llm` (`.__init__` pulls providers+session, the langchain
        # chain - ~1s) would stall the run before its first phase. Every heavy
        # touch is deferred to `_ensure_started`, which only the gateway turn
        # reaches (never on the loop-skipped no-surface path).
        self._run_id = run_id
        self._project_id = project_id
        self._gateway_project: str | None = None
        self._address = None  # resolved lazily by `thread_id`
        self._checkpointer = checkpointer
        self._model_factory = model_factory
        self._observe = observe
        self._compaction = compaction  # #95 D9/H: None auto-wires, False disables
        self._auth_store = auth_store
        self._skill_store = skill_store
        self._kali_tools = kali_tools  # None = fetch production MCP at start
        # The #238 deterministic controller (Task 4). Injected in tests; the
        # rate turn builds the production one lazily from the canonical target
        # and the gateway-selected auth when the caller passes none.
        self._rate_harness = rate_harness
        self._rate_slot = _RateHarnessSlot(rate_harness)
        self._loop_middleware = None  # the turn's tracker (observability)
        self._inbox = None
        self._replies: "AgentInbox | None" = None
        self._task: "asyncio.Task | None" = None

    @property
    def compaction_manager(self):
        """The wired compaction middleware's manager (#95 D9), or None when
        compaction is disabled or the actor has not taken its first turn."""
        return getattr(self._compaction, "manager", None)

    @property
    def loop_state(self) -> dict:
        """The gateway turn's loop tracker (a copy): the observed phase path
        and grounding evidence - the machine-observable loop progress (D223-15).
        Before the turn, the initial state."""
        if self._loop_middleware is None:
            return initial_state()
        return dict(self._loop_middleware.tracker)

    @property
    def thread_id(self) -> str:
        if self._address is None:
            from polymerhus.app.llm.session_address import OrchestratorSession  # noqa: PLC0415
            self._address = OrchestratorSession(run_id=self._run_id)
        return self._address.thread_id

    def _resolve_project(self) -> str:
        """The gateway's project scope: the run's project (constructor or
        `run_gateway` override), else the tool-owned control-plane project -
        resolved LAZILY here, so construction never touches config/env."""
        if self._gateway_project:
            return self._gateway_project
        if self._project_id:
            return self._project_id
        from polymerhus.app.config import config  # noqa: PLC0415 - lazy, no env at import
        return config.PROJECT_ID

    async def _ensure_started(self) -> None:
        """Spawn the actor task for the gateway turn (deterministic: the run
        ALWAYS reaches here except on the loop-skipped paths), wiring the
        armed tool surface, the loop tracker, and the reply delivery."""
        if self._task is not None:
            return
        from polymerhus.app.auth.seams import auth_capable_binding  # noqa: PLC0415
        from polymerhus.app.llm.actor import (  # noqa: PLC0415
            AgentInbox,
            AgentMessage,
            build_inbox_delivery,
            run_session_agent,
        )
        from polymerhus.app.llm.session_address import OrchestratorSession  # noqa: PLC0415
        if self._checkpointer is None:
            from polymerhus.app.llm.checkpoints import get_session_checkpointer  # noqa: PLC0415
            self._checkpointer = get_session_checkpointer()

        if self._inbox is None:
            self._inbox = AgentInbox()
        self._address = self._address or OrchestratorSession(run_id=self._run_id)
        replies = AgentInbox()
        self._replies = replies
        # The delivery pair (#186): the middleware posts the turn's REAL
        # `GatewayVerdict`; the degraded_hook posts a no-decision reply when the
        # turn exhausts its retry budget, so the pipeline's fail-open fires
        # per-turn and a dead turn never hangs the gateway await.
        middleware, degraded_hook = build_inbox_delivery(
            replies, kind=_REPLY_KIND, source=_REPLY_SOURCE
        )
        if self._compaction is None:
            from polymerhus.app.llm import compaction as C  # noqa: PLC0415
            self._compaction = C.build_role_compaction_middleware("job_orchestrator")
        middleware_list = [middleware] if middleware else []
        if self._compaction is not False:
            middleware_list.append(self._compaction)
        # The D223-13 arming, through the native seams: auth store + authn
        # skill + skill tools with the write capability, then the Kali exec
        # surface beside them. Fixed at construction: no per-turn surface.
        project_id = self._resolve_project()
        binding = auth_capable_binding(
            "job_orchestrator", store=self._auth_store, skill_store=self._skill_store,
            project_id=project_id, with_write_skill=True,
        )
        kali_tools = (self._kali_tools if self._kali_tools is not None
                      else await _fetch_kali_tools())
        # The #238 rate-limit surface: the two deterministic tools, bound once
        # to the harness slot (the concrete harness is bound by the rate turn).
        from polymerhus.recon.control.rate_limit_runner import (  # noqa: PLC0415
            build_rate_limit_tools,
        )
        rate_tools = build_rate_limit_tools(self._rate_slot)
        loop_middleware = build_authn_loop_middleware()
        self._loop_middleware = loop_middleware
        middleware_list = (middleware_list + binding.middleware + [loop_middleware])
        # A6 + #238: ONE structured format is negotiated for BOTH sequential
        # turns, over the fixed union - the actor always binds tools, so
        # tools_bound=True; a forced-choice-constrained profile lands on
        # ToolStrategy over the relaxed model (voluntary). Each turn validates
        # the variant it expects.
        from polymerhus.app.llm.session import structured_response_format  # noqa: PLC0415
        from polymerhus.recon.domain.rate_limit import RateLoopVerdict  # noqa: PLC0415
        response_format = structured_response_format(
            "job_orchestrator", GatewayVerdict | RateLoopVerdict, tools_bound=True)
        self._task = asyncio.ensure_future(
            run_session_agent(
                self._address.role_id,
                self._address.thread_id,
                None,  # pure listener: the gateway brief arrives as an inbox message
                checkpointer=self._checkpointer,
                inbox=self._inbox,
                on_message=self._on_message,
                tools=[*binding.tools, *kali_tools, *rate_tools],
                response_format=response_format,
                middleware=middleware_list,
                context=binding.context,
                on_turn_degraded=degraded_hook,
                system_prompt=_load_orchestrator_prompt(),
                model_factory=self._model_factory,
                observe=self._observe,
            )
        )

    def _on_message(self, message, last_turn):
        """Route inbox messages: the gateway brief triggers the ONE gateway
        turn (its HumanMessage carries the run facts, never store contents);
        `stop` ends the actor."""
        if message.kind == _GATEWAY_KIND:
            payload = message.payload or {}
            return [
                _gateway_human(
                    project_id=payload.get("project_id") or "?",
                    directive=payload.get("directive") or "request",
                    candidate=payload.get("candidate"),
                )
            ]
        if message.kind == _RATE_KIND:
            payload = message.payload or {}
            return [
                _rate_human(
                    project_id=payload.get("project_id") or "?",
                    target_key=payload.get("target_key") or "?",
                    url=payload.get("url") or "?",
                )
            ]
        if message.kind == "stop":
            from polymerhus.app.llm.actor import STOP  # noqa: PLC0415
            return STOP
        return None

    async def run_gateway(self, *, project_id: str | None = None) -> "GatewayVerdict | None":
        """Run the gateway: gate on the store state, take at most one turn,
        return the typed verdict. Fail-open to None on any turn failure (the
        pipeline runs every phase unauthenticated, loudly); fail-CLOSED via
        `GatewayStop` only on the missing-credentials prerequisite."""
        from polymerhus.app.auth.store import AuthStore  # noqa: PLC0415
        from polymerhus.app.auth.records import select_recent_usable_account  # noqa: PLC0415

        if project_id is not None:
            self._gateway_project = project_id
        pid = self._resolve_project()
        store = self._auth_store if self._auth_store is not None else AuthStore()
        # Blocking store reads offloaded: the gateway runs on the API event loop.
        overview = await asyncio.to_thread(store.read, pid, "overview")
        accounts = await asyncio.to_thread(store.read, pid, "accounts")
        gate = classify_gate(overview, accounts)
        if gate == "no_auth_surface":
            # D223-17: the expected shape, not a bootstrap failure - the loop
            # is skipped, the pipeline runs anonymously, the verdict records it.
            logger.warning(
                "auth gateway: project %s has no authenticated surface "
                "(empty store is the expected shape); skipping the loop, "
                "pipeline runs anonymously", pid)
            return GatewayVerdict(
                outcome="anonymous",
                rationale="No authenticated surface on record (empty store); "
                          "pipeline runs anonymously.")
        if gate == "missing_credentials":
            # D223-17: a missing prerequisite, not a gateway failure - D223-2
            # fail-open does not apply. Stop the run loudly.
            logger.error(
                "auth gateway: project %s declares an auth surface but stores "
                "no credentials; stopping the run (fail-close: seed accounts via "
                "PUT /projects/%s/auth)", pid, pid)
            raise GatewayStop(
                f"auth gateway: project {pid!r} declares an auth surface but "
                "stores no credentials; seed accounts via "
                f"PUT /projects/{pid}/auth and re-run")
        directive = select_branch(overview)
        if directive == "resolve_in_loop":
            # D223-11 as amended by D220-12: the loop resolves the unknown
            # fact and persists it to the overview (agent writes merge); the
            # warning stays loud for the operator's next seed.
            logger.warning(
                "auth gateway: project %s overview replayability unknown; "
                "the loop resolves and persists it in-loop",
                pid)
        candidate = select_recent_usable_account(
            accounts if isinstance(accounts, dict) else {})
        try:
            await self._ensure_started()
            from polymerhus.app.llm.actor import AgentMessage  # noqa: PLC0415
            await self._inbox.post(
                AgentMessage(
                    kind=_GATEWAY_KIND,
                    payload={"project_id": pid, "directive": directive,
                             "candidate": candidate},
                )
            )
            verdict = await self._await_reply(
                GatewayVerdict, GATEWAY_AWAIT_TIMEOUT_S, "auth gateway")
        except GatewayStop:
            raise
        except Exception:
            logger.warning("auth gateway turn failed for project %s; "
                           "fail-open: pipeline runs unauthenticated", pid, exc_info=True)
            return None
        if verdict is None:
            logger.warning("auth gateway: no verdict for project %s; fail-open: "
                           "pipeline runs every phase unauthenticated", pid)
            return None
        if verdict.replayability_resolved:
            logger.warning(
                "auth gateway: project %s in-loop replayability resolved to %s "
                "(persisted to the overview by the loop; logged loudly for the "
                "operator)",
                pid, verdict.replayability)
        return verdict

    async def run_rate_limit(
        self,
        *,
        target_key: str,
        url: str,
        headers: Mapping[str, str] | None = None,
        host_patterns: Sequence[str] | None = None,
        method: str = "GET",
        browser_only: bool = False,
        harness=None,
        timeout_s: float | None = None,
    ):
        """Take the #238 rate-limit turn on this actor's existing session/thread
        and return the public `RateProfile`.

        The DETERMINISTIC controller owns the mapping: `harness` (Task 4's
        `RateLimitHarness`, injected or built here) drives the state machine
        within the operator budget, and `harness.build_profile(verdict)` merges
        the model's interpretation into the controller's measurements - the
        verdict carries no rate, burst, budget or policy, so the model cannot
        overwrite a measurement or enlarge the budget.

        Failure posture (spec, "Persistenza e failure posture"): a browser-only
        target is NOT HTTP-replayable and yields an `inconclusive` profile with
        ZERO experiments; a wrong-schema, dead, degraded or timed-out turn
        yields the loud conservative fallback - never unthrottled traffic."""
        from polymerhus.recon.control.rate_limit_runner import (  # noqa: PLC0415
            RateLimitHarness,
            build_kali_execute,
            default_host_patterns,
        )
        from polymerhus.recon.domain.rate_limit import (  # noqa: PLC0415
            RateLoopVerdict,
            RateProfile,
        )

        patterns = (
            list(host_patterns) if host_patterns is not None
            else default_host_patterns(url)
        )
        active = harness if harness is not None else self._rate_harness
        if browser_only:
            # Review Focus: a browser-only target must never be reported as
            # quantitatively mapped, and it must cost ZERO Vegeta executions.
            # No turn is taken at all - there is nothing an HTTP replay could
            # measure, and the generic procedure must not be recycled into a
            # fake mapping.
            budget = getattr(active, "budget", None) or _rate_limit_budget()
            logger.warning(
                "rate-limit turn: %s is browser-only (not HTTP-replayable); no "
                "Vegeta experiment is run and the run continues under the "
                "conservative pacing profile", target_key)
            return RateProfile.conservative(
                target_key, patterns, budget,
                "browser-only target: no semantically equivalent HTTP request "
                "could be replayed, so the traffic surface is not quantitatively "
                "mapped; conservative Steel pacing applies",
                outcome="inconclusive")
        try:
            if active is None:
                project_id = self._resolve_project()
                active = RateLimitHarness(
                    target_key=target_key, url=url,
                    budget=_rate_limit_budget(),
                    execute=build_kali_execute(
                        project_id=project_id, run_id=self._run_id),
                    project_id=project_id, run_id=self._run_id, method=method,
                    headers=headers or {}, host_patterns=host_patterns,
                )
            self._rate_slot.bind(active)
            await self._ensure_started()
            from polymerhus.app.llm.actor import AgentMessage  # noqa: PLC0415
            await self._inbox.post(
                AgentMessage(
                    kind=_RATE_KIND,
                    payload={
                        "project_id": self._resolve_project(),
                        "target_key": target_key,
                        "url": url,
                    },
                )
            )
            bound = (
                _rate_turn_timeout_s() if timeout_s is None else float(timeout_s)
            )
            verdict = await self._await_reply(
                RateLoopVerdict, bound, "rate-limit turn")
            if verdict is None:
                logger.warning(
                    "rate-limit turn produced no usable verdict for %s "
                    "(dead, degraded or timed out); continuing under the "
                    "conservative fallback profile", target_key)
                return RateProfile.conservative(
                    target_key, patterns, active.budget,
                    "rate-limit turn produced no usable verdict (dead, degraded "
                    "or timed out): conservative fallback, never unthrottled "
                    "traffic",
                    outcome="failed")
            return active.build_profile(verdict)
        except Exception as exc:  # noqa: BLE001 - fail-LOUD, conservative
            logger.warning(
                "rate-limit turn failed for %s (%s: %s); continuing under the "
                "conservative fallback profile",
                target_key, type(exc).__name__, exc, exc_info=True)
            budget = getattr(active, "budget", None) or _rate_limit_budget()
            return RateProfile.conservative(
                target_key, patterns, budget,
                f"rate-limit turn failed ({type(exc).__name__}): conservative "
                "fallback, never unthrottled traffic",
                outcome="failed")

    async def _await_reply(self, expected_type, timeout_s: float, label: str):
        """Await ONE sequential turn's structured reply, bounded in wall-clock
        time (D223-10).

        Generalized over both turns (#238): `expected_type` is the union
        variant this turn must produce and `label` names the turn in the logs.
        Races the reply against the actor task: a dead actor maps to None
        (fail-open) rather than hanging; a live-but-hung turn maps to None at
        the bound WITHOUT cancelling the turn (its harness bounds own turn
        length) and WITHOUT leaving a stale reply (the inbox drains
        best-effort; the actor is per-run, so no later consumer exists). A
        reply whose content parses to the OTHER variant - or to no schema - is
        logged LOUDLY and treated as no reply."""
        reply_task = asyncio.ensure_future(self._replies.get())
        try:
            # `asyncio.wait` (not `wait_for`) is the precise primitive here:
            # FIRST_COMPLETED over exactly the reply and the actor task races
            # "verdict arrived" against "actor died" with neither cancelled -
            # the actor task must NEVER be cancelled by the waiter (its
            # harness bounds own turn length); only the reply waiter is
            # cancelled below, and the inbox drains best-effort.
            done, _pending = await asyncio.wait(
                {reply_task, self._task},
                timeout=timeout_s,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if reply_task in done:
                message = reply_task.result()
                payload = message.payload if isinstance(message.payload, dict) else {}
                content = payload.get("content")
                if isinstance(content, expected_type):
                    return content
                if content is None:
                    return None  # the degraded no-decision reply: fail-open
                logger.warning(
                    "%s wrong-schema reply (expected %s, got %s): %r; fail-open "
                    "to no verdict",
                    label, getattr(expected_type, "__name__", expected_type),
                    type(content).__name__, str(content)[:500])
                return None
            if self._task.done():
                return None  # the actor task finished first: dead actor, fail-open
            logger.warning(
                "%s await timed out after %.0fs with a live turn; fail-open to "
                "no verdict (the turn continues under its harness bounds; no "
                "stale reply is left behind)",
                label, timeout_s)
            return None
        finally:
            if not reply_task.done():
                reply_task.cancel()
            self._drain_replies()

    def _drain_replies(self) -> None:
        """Best-effort drain of the reply inbox: a timed-out await must not
        leave a stale reply for a later consumer."""
        try:
            if self._replies is None:
                return
            while self._replies.try_get_nowait() is not None:
                pass
        except Exception:  # noqa: BLE001 - teardown best-effort, never raises
            pass

    async def stop(self) -> None:
        """Post the terminal message and reap the actor task (idempotent; safe when
        the actor never spawned or already died)."""
        if self._task is None:
            return
        try:
            from polymerhus.app.llm.actor import AgentMessage  # noqa: PLC0415
            await self._inbox.post(AgentMessage(kind="stop"))
        except Exception:  # noqa: BLE001 - teardown must never raise
            pass
        if not self._task.done():
            try:
                await self._task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        else:
            # the task already died: reap its exception so it is not logged as
            # unretrieved ("Task exception was never retrieved")
            try:
                self._task.exception()
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass


__all__ = [
    "GatewayStop",
    "GATEWAY_AWAIT_TIMEOUT_S",
    "ReconOrchestratorActor",
    "build_authn_loop_middleware",
]
