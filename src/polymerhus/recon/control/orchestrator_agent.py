"""Recon-orchestrator agent: macro pipeline management.

The orchestrator's steering responsibility is CROSS-JOB routing - given the WAF
signals the pipeline has already observed, decide which downstream job should
not receive which flagged host (route WAF-flagged hosts away from request-based
crawlers, toward the agentic crawler). `run_pipeline` is the driver; the
reasoning lives here, with the agent that owns it, not bolted onto the driver
function.

The routing logic lives on the `ReconOrchestratorActor` - the MAILBOX ACTOR
(#94, feat/async-actor-agents): one persistent `run_session_agent` on the
`job_orchestrator` session role per recon run (`OrchestratorSession(run_id)`
thread), fed each phase's steering via its inbox, replying a structured
`RoutingDecision` per phase on the SAME thread, so the checkpointer carries the
steering reasoning across the run. This is `run_pipeline`'s PRODUCTION default
(decide_routing=None); the client methods (`decide_routing`, `stop`) are the
async seams the pipeline drives. `run_pipeline` also accepts an INJECTED
`decide_routing` seam for tests.

Fail-open: any LLM/parse error returns the neutral decision ({} = no
exclusions), so a steering blip degrades adaptivity, never the run. Only invoked
with a non-empty signal list.

The `ORCHESTRATOR_STEERING` prompt is the TEMPORARY inline home for this agent's
thought process; it is slated to move into a dedicated recon-pipeline-agent
skill (forward-decision D22). It frames the shared `STEERING_PRIMITIVES` for the
orchestrator's macro-routing scope.
"""
from __future__ import annotations

import asyncio
import logging

from pydantic import BaseModel, Field

from polymerhus.recon.control.steering import (
    STEERING_PRIMITIVES,
    describe_job_kind,
    format_signals,
)

logger = logging.getLogger(__name__)

ORCHESTRATOR_STEERING = (
    "## STEERING DECISIONS (recon-orchestrator agent)\n\n"
    "You are the recon-orchestrator agent managing the macro reconnaissance\n"
    "pipeline. Given the signals the pipeline has already observed and the jobs\n"
    "about to run in the next phase, decide cross-job routing: which downstream\n"
    "job should NOT receive which flagged host. Reason about the signals; do not\n"
    "restate them.\n\n"
    + STEERING_PRIMITIVES
    + "\nRoute WAF-flagged hosts away from request-based crawlers and toward the\n"
    "agentic crawler; leave un-flagged hosts alone. Return the minimal set of\n"
    "exclusions needed.\n"
)


class _JobExclusion(BaseModel):
    job: str
    exclude_urls: list[str] = Field(default_factory=list)


class RoutingDecision(BaseModel):
    exclusions: list[_JobExclusion] = Field(default_factory=list)
    rationale: str = ""


# --- shared routing logic (the mailbox actor) -------------------------------


def _steering_human(signals: list[dict], phase_jobs: list[str]):
    """The per-phase steering brief handed to the model: the live signals and
    the upcoming phase's jobs, with the routing instruction. `phase_jobs` names
    are already plan-gated, so the model cannot be asked about a job outside the
    plan."""
    from langchain_core.messages import HumanMessage  # noqa: PLC0415
    jobs_desc = "\n".join(f"- {j}: {describe_job_kind(j)}" for j in phase_jobs)
    return HumanMessage(
        content=(
            f"Signals (flagged BaseURLs):\n{format_signals(signals)}\n\n"
            f"Upcoming phase jobs:\n{jobs_desc}\n\n"
            "Return, per job that should NOT receive a flagged host, the urls to exclude."
        )
    )


def _exclusions_map(decision: "RoutingDecision | None", phase_jobs: list[str]) -> dict[str, list[str]]:
    """Map a parsed `RoutingDecision` to {job_name: [urls]} filtered to the phase's
    jobs. A `None` decision (parse failure, dead actor) maps to {} - the neutral
    fail-open decision."""
    if decision is None:
        return {}
    return {e.job: e.exclude_urls for e in decision.exclusions if e.job in phase_jobs}


# --- the mailbox actor (#94, feat/async-actor-agents) --------------------------

_PHASE_KIND = "phase_steering"
_REPLY_KIND = "routing_decision"
_REPLY_SOURCE = "recon-orchestrator"


class ReconOrchestratorActor:
    """The recon-orchestrator as a persistent MAILBOX actor (#94).

    ONE actor per recon run: `run_pipeline` constructs it (production default),
    and it spawns a `run_session_agent` on the `job_orchestrator` session role
    under the run's `OrchestratorSession` thread the first time a phase actually
    needs steering. `decide_routing` posts the phase's signals/jobs into the
    actor's inbox; the handler turns the message into the next session turn on
    the SAME thread (so checkpointed memory carries the steering reasoning across
    the run's phases); the post-call middleware delivers the parsed
    `RoutingDecision` back into the reply inbox, which the client awaits.

    Fail-open: a dead/crashed actor (LLM error, parse error, harness error) maps
    to the neutral decision {} - a steering blip degrades adaptivity, never the
    run. `stop` posts the terminal message and reaps the task; safe to call when
    the actor never spawned."""

    def __init__(
        self,
        run_id: str,
        *,
        checkpointer=None,
        model_factory=None,
        observe: bool = True,
        compaction=None,
    ):
        # Construction must perform NO imports (CODING_STANDARD 6): the actor is
        # built at run_pipeline START on the event loop, and importing
        # `polymerhus.app.llm` (`.__init__` pulls providers+session, the langchain
        # chain - ~1s) would stall the run before its first phase. Every heavy
        # touch is deferred to `_ensure_started`, which only the first real
        # signal-carrying phase reaches.
        self._run_id = run_id
        self._address = None  # resolved lazily by `thread_id`
        self._checkpointer = checkpointer
        self._model_factory = model_factory
        self._observe = observe
        self._compaction = compaction  # #95 D9/H: None auto-wires, False disables
        self._inbox = None
        self._replies: "AgentInbox | None" = None
        self._task: "asyncio.Task | None" = None

    @property
    def compaction_manager(self):
        """The wired compaction middleware's manager (#95 D9), or None when
        compaction is disabled or the actor has not taken its first turn."""
        return getattr(self._compaction, "manager", None)

    @property
    def thread_id(self) -> str:
        if self._address is None:
            from polymerhus.app.llm.session_address import OrchestratorSession  # noqa: PLC0415
            self._address = OrchestratorSession(run_id=self._run_id)
        return self._address.thread_id

    async def _ensure_started(self) -> None:
        """Spawn the actor task on first use (lazy: a run with no signals never
        pays for an actor), wiring the reply middleware into its turns."""
        if self._task is not None:
            return
        from langchain.agents.structured_output import ToolStrategy  # noqa: PLC0415
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
        # The delivery pair (#186): the middleware posts the phase's REAL
        # `RoutingDecision`; the degraded_hook posts a no-decision reply when the
        # turn exhausts its retry budget, so the parent's fail-open fires per-turn
        # and the actor survives for the run's next phase.
        middleware, degraded_hook = build_inbox_delivery(
            replies, kind=_REPLY_KIND, source=_REPLY_SOURCE
        )
        if self._compaction is None:
            from polymerhus.app.llm import compaction as C  # noqa: PLC0415
            self._compaction = C.build_role_compaction_middleware("job_orchestrator")
        middleware_list = [middleware] if middleware else []
        if self._compaction is not False:
            middleware_list.append(self._compaction)
        self._task = asyncio.ensure_future(
            run_session_agent(
                self._address.role_id,
                self._address.thread_id,
                None,  # pure listener: phases arrive as inbox messages
                checkpointer=self._checkpointer,
                inbox=self._inbox,
                on_message=self._on_message,
                response_format=ToolStrategy(RoutingDecision),
                middleware=middleware_list,
                on_turn_degraded=degraded_hook,
                system_prompt=ORCHESTRATOR_STEERING,
                model_factory=self._model_factory,
                observe=self._observe,
            )
        )

    def _on_message(self, message, last_turn):
        """Route inbox messages: a phase-steering message triggers the next routing
        turn (on the SAME thread, so memory carries); `stop` ends the actor."""
        if message.kind == _PHASE_KIND:
            payload = message.payload or {}
            return [
                _steering_human(
                    payload.get("signals") or [], payload.get("phase_jobs") or []
                )
            ]
        if message.kind == "stop":
            from polymerhus.app.llm.actor import STOP  # noqa: PLC0415
            return STOP
        return None

    async def decide_routing(
        self, signals: list[dict], phase_jobs: list[str]
    ) -> dict[str, list[str]]:
        """Feed one phase's steering to the actor and await its `RoutingDecision`,
        mapped to {job_name: [urls]}. Fail-open to {} on a dead actor or empty
        input - the caller (run_pipeline) keeps the run going either way."""
        if not signals or not phase_jobs:
            return {}
        try:
            await self._ensure_started()
            from polymerhus.app.llm.actor import AgentMessage  # noqa: PLC0415
            await self._inbox.post(
                AgentMessage(
                    kind=_PHASE_KIND,
                    payload={"signals": list(signals), "phase_jobs": list(phase_jobs)},
                )
            )
            decision = await self._await_reply()
            return _exclusions_map(decision, phase_jobs)
        except Exception:
            logger.warning("recon-orchestrator actor decide failed; no routing adaptation", exc_info=True)
            return {}

    async def _await_reply(self) -> "RoutingDecision | None":
        """Await the actor's reply for the phase just fed. Races the reply against
        the actor task itself: if the actor died mid-turn (LLM error), the task
        completes without a reply - return None (fail-open) rather than hang."""
        reply_task = asyncio.ensure_future(self._replies.get())
        try:
            done, _pending = await asyncio.wait(
                {reply_task, self._task}, return_when=asyncio.FIRST_COMPLETED
            )
            if reply_task not in done:
                return None  # the actor task finished first: dead actor, fail-open
            message = reply_task.result()
            payload = message.payload if isinstance(message.payload, dict) else {}
            content = payload.get("content")
            return content if isinstance(content, RoutingDecision) else None
        finally:
            if not reply_task.done():
                reply_task.cancel()

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
