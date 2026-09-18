"""Recon-orchestrator agent: the run's auth gateway (#223, T3 #242).

The orchestrator is the SOLE auth-gateway decider (D223-8): on run start,
before phase 0, it runs ONE stateful gateway turn - the authn loop - that
establishes or validates the run's auth state against the shared auth store
and the project's `authn` skill, then closes with the structured
`GatewayVerdict`. The pipeline obeys the verdict (prunes what it excludes,
binds the account identifier); no second decision point exists downstream.

The actor is a MAILBOX ACTOR (#94, feat/async-actor-agents): one persistent
`run_session_agent` on the `job_orchestrator` session role per recon run
(`OrchestratorSession(run_id)` thread), fed the single gateway brief via its
inbox, replying the verdict on the SAME thread. `run_pipeline` drives it
through `run_gateway` (production default); `stop` reaps it.

Arming (D223-13): the roster exemption is lifted through the write-capable
auth binding - the shared `auth_store` tool, the project's `authn` skill,
`load_skill`, `write_skill`, the Kali exec capability, and the Steel exec
gateway - attached through the native `tools=` / `middleware=` / `context=`
seams. The tool set is fixed at construction; no per-turn surface exists.

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
from typing import Any

from pydantic import BaseModel, Field

from polymerhus.recon.control.authn_loop import (
    BRANCH_DIRECTIVES,
    GatewayVerdict,
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


# --- the retired routing schema (removal belongs to #243, T4) -------------------

# #243 (T4, removal): the routing schema and the exclusion map retire with the
# mid-run steering machinery (D223-12). T3 (#242) only retires the per-phase
# routing TURNS - the actor's `response_format` is now the gateway verdict and
# the pipeline no longer calls per phase. Left in place, dead, until T4.


class _JobExclusion(BaseModel):
    job: str
    exclude_urls: list[str] = Field(default_factory=list)


class RoutingDecision(BaseModel):
    exclusions: list[_JobExclusion] = Field(default_factory=list)
    rationale: str = ""


def _exclusions_map(decision: "RoutingDecision | None", phase_jobs: list[str]) -> dict[str, list[str]]:
    """Map a parsed `RoutingDecision` to {job_name: [urls]} filtered to the phase's
    jobs. A `None` decision (parse failure, dead actor) maps to {} - the neutral
    fail-open decision."""
    if decision is None:
        return {}
    return {e.job: e.exclude_urls for e in decision.exclusions if e.job in phase_jobs}


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
            """Append the hint to the triggering response, when the shape
            allows; any other shape passes through (the tracker still moved)."""
            if not hint:
                return response
            try:
                from langchain_core.messages import ToolMessage  # noqa: PLC0415
                if isinstance(response, ToolMessage) and isinstance(response.content, str):
                    return response.model_copy(update={
                        "content": f"{response.content}\n\n{wrap_hint(hint)}"})
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
        "browser-only (record false). Record the resolution loudly in the "
        "rationale and verdict; NEVER write it to the overview "
        "(operator-owned)."),
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


# --- the mailbox actor ------------------------------------------------------------

_GATEWAY_KIND = "gateway"
_REPLY_KIND = "gateway_verdict"
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
    """Fetch the Kali exec surface (`execute_command`, `steel_exec`) from the
    Kali MCP gateway (the `pod.default_exec_fn` precedent: lazily built per
    use, never at import). Fail-open to [] - the gateway still runs its
    store/skill span and the verdict carries the degradation loudly."""
    try:
        from langchain_mcp_adapters.client import MultiServerMCPClient  # noqa: PLC0415
        from polymerhus.app.config import config  # noqa: PLC0415

        client = MultiServerMCPClient(
            {"kali": {"url": config.KALI_MCP_URL, "transport": "streamable_http"}})
        tools = await client.get_tools()
        return [t for t in tools if t.name in ("execute_command", "steel_exec")]
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
        from langchain.agents.structured_output import ToolStrategy  # noqa: PLC0415
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
        loop_middleware = build_authn_loop_middleware()
        self._loop_middleware = loop_middleware
        middleware_list = (middleware_list + binding.middleware + [loop_middleware])
        self._task = asyncio.ensure_future(
            run_session_agent(
                self._address.role_id,
                self._address.thread_id,
                None,  # pure listener: the gateway brief arrives as an inbox message
                checkpointer=self._checkpointer,
                inbox=self._inbox,
                on_message=self._on_message,
                tools=[*binding.tools, *kali_tools],
                response_format=ToolStrategy(GatewayVerdict),
                middleware=middleware_list,
                context=binding.context,
                on_turn_degraded=degraded_hook,
                system_prompt=_load_gateway_prompt(),
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
            # D223-11: run-scoped and loud, never persisted (the overview is
            # operator-owned - disagreement is recorded, never patched).
            logger.warning(
                "auth gateway: project %s overview replayability unknown; "
                "the loop resolves it in-loop (run-scoped, never persisted)",
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
            verdict = await self._await_reply()
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
                "(run-scoped, never persisted; operator to re-seed)",
                pid, verdict.replayability)
        return verdict

    async def _await_reply(self) -> "GatewayVerdict | None":
        """Await the gateway turn's verdict, bounded in wall-clock time (D223-10).

        Races the reply against the actor task: a dead actor maps to None
        (fail-open) rather than hanging; a live-but-hung turn maps to None at
        the bound WITHOUT cancelling the turn (its harness bounds own turn
        length) and WITHOUT leaving a stale reply (the inbox drains
        best-effort; the actor is per-run, so no later consumer exists). A
        reply whose content parses to the wrong schema is logged LOUDLY."""
        reply_task = asyncio.ensure_future(self._replies.get())
        try:
            done, _pending = await asyncio.wait(
                {reply_task, self._task},
                timeout=GATEWAY_AWAIT_TIMEOUT_S,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if reply_task in done:
                message = reply_task.result()
                payload = message.payload if isinstance(message.payload, dict) else {}
                content = payload.get("content")
                if isinstance(content, GatewayVerdict):
                    return content
                if content is None:
                    return None  # the degraded no-decision reply: fail-open
                logger.warning(
                    "auth gateway wrong-schema reply (expected GatewayVerdict, "
                    "got %s): %r; fail-open to no verdict",
                    type(content).__name__, str(content)[:500])
                return None
            if self._task.done():
                return None  # the actor task finished first: dead actor, fail-open
            logger.warning(
                "auth gateway await timed out after %.0fs with a live turn; "
                "fail-open to no verdict (the turn continues under its harness "
                "bounds; no stale reply is left behind)",
                GATEWAY_AWAIT_TIMEOUT_S)
            return None
        finally:
            if not reply_task.done():
                reply_task.cancel()
            self._drain_replies()

    def _drain_replies(self) -> None:
        """Best-effort drain of the reply inbox: a timed-out await must not
        leave a stale reply for a later consumer."""
        try:
            while not self._replies.empty():
                self._replies._q.get_nowait()
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
    "RoutingDecision",
    "build_authn_loop_middleware",
]
