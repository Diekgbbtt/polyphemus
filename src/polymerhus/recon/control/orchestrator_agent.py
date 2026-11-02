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

Fail-closed (D223-21): the gateway rides the harness failure suite; when that
is exhausted the turn returns a `failed` verdict and the pipeline stops
collection. The gateway-specific requirements live here: the await is bounded
in wall-clock time and drains rather than leaving a stale reply, wrong-schema
replies are logged loudly, and the missing-data gate discriminates
structurally before any turn (no-auth-surface skips the loop and records
itself; a declared surface with no accounts runs the loop so the orchestrator
can mint; a missing bootstrap prerequisite stops the run loudly via
`GatewayStop`).
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

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
        "No blocking defence recorded. Validate the loaded session with the "
        "authenticated-context oracle at `overview.auth_probe.url`: a browser "
        "request in the live session. 2xx passes; 401, 403, or any 3xx fails; "
        "anything else is indeterminate and stops the run. Then validate the "
        "request material with the recorded HTTP history replay "
        "(`search_http_history`, then `replay_http_request`); the in-process "
        "auth-store view is redacted, so never read or paste token values. "
        "The request material is applied server-side. Request phases stay "
        "released."),
    "browser_only": (
        "Browser-only target (the defence is not HTTP-replayable). Validate "
        "EXCLUSIVELY through the oracle in the Steel path. Reuse the "
        "operator-owned live session named by the authn skill. Do not start a "
        "replacement: a start on a live name is refused with session_taken, "
        "and a loss (session_missing) needs state-restoring recreation, not a "
        "blank session. A 2xx oracle passes; 401, 403, or 3xx fails. On a "
        "failure, sign in or mint a new account through the authn skill's "
        "sign-up procedure with synthetic identity data, then prove the oracle "
        "again. A failed or indeterminate oracle stops the run. Never use "
        "request tools. You never write a browser state reference; only the "
        "crawl provider captures state. Request phases will be pruned; only "
        "the Steel crawl runs."),
    "request_browser_first": (
        "Replayable defence. Validate the session with the oracle at "
        "`overview.auth_probe.url` first. Reuse the operator-owned live "
        "session; the request material is applied server-side by the "
        "pipeline. Do not read or compare token values. On a failed oracle, "
        "sign in or mint a new account through the authn skill's sign-up "
        "procedure with synthetic identity data, then prove the oracle again. "
        "Then release request collection."),
    "resolve_in_loop": (
        "Replayability UNKNOWN. Resolve it with the recorded HTTP history "
        "replay: replayable releases the request branch (record replayability "
        "true), not replayable prunes to browser-only (record false). If no "
        "captured artifact exists, do not read secrets and do not invent a "
        "result; record the fact as unresolved and loud. The oracle still "
        "decides whether the session is authenticated; an unresolved request "
        "fact never forces a fail-open. Persist any resolved fact to the "
        "overview with an auth_store write (your write merges; the operator "
        "stamp stays), and record it in the rationale and verdict."),
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
        "No usable account on record: mint one through the authn skill's "
        "sign-up procedure with synthetic identity data, write its "
        "credentials, then prove the oracle.")
    return HumanMessage(content=(
        f"Auth gateway for project {project_id}.\n\n"
        f"Branch directive: {directive}.\n{manner}\n\n"
        f"{selection}\n\n"
        "Ground (overview read + authn skill load), validate with the "
        "authenticated-context oracle before sign-in, sign in or mint on a "
        "failed oracle, assert the outcome in the store, run the outer "
        "skill-judging loop, then emit the GatewayVerdict. A failed or "
        "indeterminate oracle stops the run; never fail open."))


# --- the mailbox actor ------------------------------------------------------------

_GATEWAY_KIND = "gateway"
_REPLY_KIND = "gateway_verdict"
_REPLY_SOURCE = "recon-orchestrator"

# The wall-clock bound on the gateway await (D223-10, amended by D223-21): a
# hung turn returns a failed verdict (fail-closed, loudly) instead of stalling
# run start. Sized above any legitimate sign-in span - the turn's own harness
# bounds (recursion limit, escalating per-attempt budgets) own turn length;
# this only bounds the WAIT.
GATEWAY_AWAIT_TIMEOUT_S = 3600.0

# How long `run_gateway` waits, after receiving the turn's reply, for the
# pipeline's final checkpoint write to settle. The reply is posted at the end
# of the graph turn; the checkpoint write lands a moment later. A caller that
# closes its checkpointer on the reply must not race that write.
TURN_SETTLE_TIMEOUT_S = 30.0


class GatewayStop(Exception):
    """The fail-close stop for a missing bootstrap prerequisite.

    A declared auth surface with no usable account and no mint/sign-in data
    dependency is not a gateway failure; the pipeline catches this, marks the
    run failed loudly, and runs nothing. Authentication failure always stops
    collection (D223-21); it never fails open."""


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
    scope). Fail-closed (D223-21): a dead/crashed actor (LLM error, parse
    error, harness error, bounded-await timeout) maps to None and then to a
    `failed` verdict, so the pipeline stops collection; a missing bootstrap
    prerequisite stops the run via `GatewayStop`."""

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
        self._turn_settled: "asyncio.Event | None" = None
        self._reply_seen = False

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
        # turn exhausts its retry budget, so the gateway returns `failed` and
        # the pipeline stops collection; a dead turn never hangs the await.
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
        # A6: the structured verdict is negotiated, not pinned - the gateway
        # always binds tools, so tools_bound=True; a forced-choice-constrained
        # profile lands on ToolStrategy over the relaxed model (voluntary).
        from polymerhus.app.llm.session import structured_response_format  # noqa: PLC0415
        response_format = structured_response_format(
            "job_orchestrator", GatewayVerdict, tools_bound=True)
        self._turn_settled = asyncio.Event()
        self._task = asyncio.ensure_future(
            run_session_agent(
                self._address.role_id,
                self._address.thread_id,
                None,  # pure listener: the gateway brief arrives as an inbox message
                checkpointer=self._checkpointer,
                inbox=self._inbox,
                on_message=self._on_message,
                tools=[*binding.tools, *kali_tools],
                response_format=response_format,
                middleware=middleware_list,
                context=binding.context,
                on_turn_degraded=degraded_hook,
                on_turn_complete=self._on_turn_complete,
                system_prompt=_load_gateway_prompt(),
                model_factory=self._model_factory,
                observe=self._observe,
                usage_scope=project_id,
            )
        )

    def _on_turn_complete(self, turn_id: str | None) -> None:
        """Signal that the turn that produced a reply has fully returned.

        The delivery middleware can post the reply before the graph writes its
        final checkpoint. `run_gateway` waits on this event before returning,
        so a caller may close the checkpointer without racing that write."""
        if self._turn_settled is not None:
            self._turn_settled.set()

    async def _await_turn_settled(self) -> None:
        if self._turn_settled is None:
            return
        try:
            await asyncio.wait_for(
                self._turn_settled.wait(), timeout=TURN_SETTLE_TIMEOUT_S
            )
        except asyncio.TimeoutError:
            logger.warning(
                "auth gateway: the turn did not settle within %.0fs after its "
                "reply; a caller may close the checkpointer while the final "
                "write is pending", TURN_SETTLE_TIMEOUT_S)

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

    async def run_gateway(self, *, project_id: str | None = None) -> "GatewayVerdict":
        """Run the gateway: gate on the store state, take at most one turn,
        return the typed verdict. A turn failure returns a `failed` verdict:
        authentication failures stop collection (D223-21), never fail open.
        `GatewayStop` remains the explicit fail-close stop for a caller that
        proves a missing bootstrap prerequisite before the turn."""
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
            self._reply_seen = False
            if self._turn_settled is not None:
                self._turn_settled.clear()
            await self._inbox.post(
                AgentMessage(
                    kind=_GATEWAY_KIND,
                    payload={"project_id": pid, "directive": directive,
                             "candidate": candidate},
                )
            )
            verdict = await self._await_reply()
            if self._reply_seen:
                # The reply can precede the graph's final checkpoint write.
                # Return only after the turn that produced it has settled.
                await self._await_turn_settled()
        except GatewayStop:
            raise
        except Exception:
            logger.error("auth gateway turn failed for project %s; "
                         "fail-closed: collection will not run", pid, exc_info=True)
            return GatewayVerdict(
                outcome="failed",
                rationale="Gateway turn failed before producing a verdict; "
                          "collection stops (fail-closed).")
        if verdict is None:
            logger.error("auth gateway: no verdict for project %s; "
                         "fail-closed: collection will not run", pid)
            return GatewayVerdict(
                outcome="failed",
                rationale="Gateway produced no verdict; collection stops "
                          "(fail-closed).")
        if verdict.replayability_resolved:
            logger.warning(
                "auth gateway: project %s in-loop replayability resolved to %s "
                "(persisted to the overview by the loop; logged loudly for the "
                "operator)",
                pid, verdict.replayability)
        return verdict

    async def _await_reply(self) -> "GatewayVerdict | None":
        """Await the gateway turn's verdict, bounded in wall-clock time (D223-10).

        Races the reply against the actor task: a dead actor maps to None
        (the caller returns `failed`) rather than hanging; a live-but-hung
        turn maps to None at the bound WITHOUT cancelling the turn (its
        harness bounds own turn length) and WITHOUT leaving a stale reply
        (the inbox drains best-effort; the actor is per-run, so no later
        consumer exists). A reply whose content parses to the wrong schema is
        logged LOUDLY."""
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
                timeout=GATEWAY_AWAIT_TIMEOUT_S,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if reply_task in done:
                self._reply_seen = True
                message = reply_task.result()
                payload = message.payload if isinstance(message.payload, dict) else {}
                content = payload.get("content")
                if isinstance(content, GatewayVerdict):
                    return content
                if content is None:
                    return None  # the degraded no-decision reply; the caller fails closed
                logger.warning(
                    "auth gateway wrong-schema reply (expected GatewayVerdict, "
                    "got %s): %r; no verdict, the caller fails closed",
                    type(content).__name__, str(content)[:500])
                return None
            if self._task.done():
                return None  # the actor task finished first: dead actor; the caller fails closed
            logger.warning(
                "auth gateway await timed out after %.0fs with a live turn; "
                "no verdict, fail-closed (the turn continues under its harness "
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

    async def cancel(self) -> None:
        """Force-retire a stuck actor task.

        ``stop`` is graceful: it posts the terminal message and waits for the
        current turn. A harness hard deadline cannot wait forever for a model
        call that ignores cancellation. The caller invokes this only after the
        graceful stop has itself timed out.
        """
        if self._task is None or self._task.done():
            return
        self._task.cancel()
        try:
            await self._task
        except (asyncio.CancelledError, Exception):  # noqa: BLE001
            pass


__all__ = [
    "GatewayStop",
    "GATEWAY_AWAIT_TIMEOUT_S",
    "TURN_SETTLE_TIMEOUT_S",
    "ReconOrchestratorActor",
    "build_authn_loop_middleware",
]
