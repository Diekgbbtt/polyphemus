"""The hunting actors: the threat modeller and the hunting-hunter as MAILBOX
actors (feat/async-actor-agents).

The hunting effort is driven by the same actor-with-inbox architecture the
recon-orchestrator uses (`recon/control/orchestrator_agent.ReconOrchestratorActor`):

- `ThreatModellerActor` - ONE persistent `run_session_agent` per hunting run on
  the `hunting_threat_modeller` session role (`ThreatModellerSession(run_id)`
  thread). Its client (`threat_modeller.arun_modeller_pass`) posts one turn per
  gate state and awaits the turn, all on the SAME thread, so the checkpointer
  carries the run's reasoning across units. The bound tool surface is the
  modeller's (`threat_modeller_tools.build_modeller_tool_surface`, S1 5).
- `HuntingHunterActor` - one per hunt on the `hunting_hunter` session role
  (`HuntSession(run_id, hunt_id)` thread), fed the spec-authoring (D4) and
  continuation-judgment (D5) prompts via its inbox. `HuntingActorRegistry`
  hands per-hunt author/judge closures bound to these actors. AS OF #164 W5 the
  hunting-agent harness (`hunting_agent.build_hunting_agent`) is the turn-by-turn
  ReAct host and drives `arun_session_turn` DIRECTLY on the per-hunt thread, so
  this actor remains the SYNC/lazy rollback lane (and is kept as tested
  infrastructure), no longer the harness's production mechanism.

Both use the same mechanics as `ReconOrchestratorActor`: an inbox that routes
message kinds to the next on-thread turn, a post-call middleware that delivers
the turn's content into a reply inbox, a client await that races the reply
against the actor task (fail-open on a dead actor), and an idempotent `stop`.

This module imports no driver and performs no I/O at import (CODING_STANDARD
section 6): `__init__` performs NO imports at all - the heavy `polymerhus.app.llm`
import chain is deferred to `_ensure_started`, exactly as the recon actor does.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence

logger = logging.getLogger(__name__)

# The modeller's per-state reasoning turn kind.
_MODELLER_TURN_KIND = "modeller_turn"
# The hunter actor's author / judge turn kinds.
_AUTHOR_KIND = "author"
_JUDGE_KIND = "judge"

_REPLY_KIND = "hunting_turn"
_REPLY_SOURCE = "hunting-actor"


class _TurnActor:
    """Shared mailbox-actor machinery for the hunting actors.

    Subclasses declare the on-thread message handling (`_on_message`) and the
    lazily-resolved session address. Construction performs NO imports; every
    heavy touch is deferred to `_ensure_started`."""

    _base_kind = ""
    _role_id = ""
    # The site-declared arming of an EXEMPT role's skill+auth surface (S1 5.5;
    # a bound role gets its surface from the roster and ignores this).
    _arm_exempt_surface = False

    def __init__(self, checkpointer=None, model_factory=None, observe: bool = True,
                 tools: Sequence = ()):
        self._checkpointer = checkpointer
        self._model_factory = model_factory
        self._observe = observe
        self._tools = list(tools)
        self._address = None
        self._inbox = None
        self._replies = None
        self._task = None
        # #329: the exception a degraded turn died on, recorded by the wrapped
        # `on_turn_degraded` hook and cleared per request - so the pass can
        # classify a no-decision turn as provider-caused and pause the run
        # instead of failing it.
        self._degrade_cause: Exception | None = None

    @property
    def role_id(self) -> str:
        return self._role_id

    @property
    def thread_id(self) -> str:
        if self._address is None:
            self._address = self._make_address()
        return self._address.thread_id

    def _make_address(self):
        raise NotImplementedError

    @property
    def _extra_tags(self) -> list | None:
        """Run-join tags for this actor's turns (convergence: the run tag
        replaces the deleted hand-written agent spans). The generic base knows
        no run; run-scoped subclasses override with their run id."""
        return None

    @property
    def _usage_scope(self) -> str | None:
        """The project the actor's turns attribute their token usage to. The
        generic base knows none; a project-scoped subclass overrides it."""
        return None

    async def _ensure_started(self, response_format=None, system_prompt=None,
                              middleware_extra: list = None, tools=None) -> None:
        """Spawn the actor task on first use (lazy: a pass with no turns never
        pays for an actor), wiring the reply middleware into its turns."""
        if self._task is not None:
            return
        from polymerhus.app.llm.actor import (  # noqa: PLC0415
            AgentInbox,
            build_inbox_delivery,
            run_session_agent,
        )
        if self._checkpointer is None:
            from polymerhus.app.llm.checkpoints import get_session_checkpointer  # noqa: PLC0415
            self._checkpointer = get_session_checkpointer()

        if self._inbox is None:
            self._inbox = AgentInbox()
        self._address = self._address or self._make_address()
        replies = AgentInbox()
        self._replies = replies
        # The delivery pair (#186): the middleware posts the turn's REAL result;
        # the degraded_hook posts a no-decision reply when the turn exhausts its
        # retry budget, so the caller's fail-open fires per-turn (never through
        # the dead-task race) and the actor survives for the next turn.
        middleware, degraded_hook = build_inbox_delivery(
            replies, kind=_REPLY_KIND, source=_REPLY_SOURCE
        )

        def _record_degrade(thread_id, exc, _hook=degraded_hook):
            # #329: record the cause so the pass can classify a provider-caused
            # abort, then delegate to the delivery hook.
            self._degrade_cause = exc
            if _hook is not None:
                _hook(thread_id, exc)

        middleware = [middleware] if middleware else []
        if middleware_extra:
            middleware = middleware + list(middleware_extra)
        from polymerhus.app.auth.seams import auth_capable_binding  # noqa: PLC0415

        binding = auth_capable_binding(
            self._address.role_id, arm_exempt_surface=self._arm_exempt_surface,
            project_id=getattr(self, "project_id", "") or None)
        middleware = middleware + binding.middleware
        kwargs = {
            "checkpointer": self._checkpointer,
            "inbox": self._inbox,
            "on_message": self._on_message,
            "middleware": middleware,
            "context": binding.context,
            "on_turn_degraded": _record_degrade,
            "model_factory": self._model_factory,
            "observe": self._observe,
            "extra_tags": self._extra_tags,
            "usage_scope": self._usage_scope,
        }
        if tools:
            kwargs["tools"] = list(tools)
        if response_format is not None:
            kwargs["response_format"] = response_format
        if system_prompt is not None:
            kwargs["system_prompt"] = system_prompt
        if self._tools:
            kwargs["tools"] = self._tools
        kwargs["tools"] = list(kwargs.get("tools", ())) + binding.tools
        self._task = asyncio.ensure_future(
            run_session_agent(
                self._address.role_id,
                self._address.thread_id,
                None,  # pure listener: turns arrive as inbox messages
                **kwargs,
            )
        )

    def _on_message(self, message, last_turn):  # pragma: no cover - subclass
        raise NotImplementedError

    async def _post_and_await(self, message) -> "object | None":
        """Post one request message into the actor's inbox and await the reply.
        Races the reply against the actor task: a dead actor returns None
        (fail-open) instead of hanging."""
        await self._ensure_started()
        self._degrade_cause = None  # #329: the cause is per request, never stale
        from polymerhus.app.llm.actor import AgentMessage  # noqa: PLC0415
        await self._inbox.post(message)
        return await self._await_reply()

    def last_degrade_cause(self) -> Exception | None:
        """The exception the MOST RECENT request's degraded turn died on, or
        None when the request did not degrade (#329). Read by the pass to
        classify a no-decision turn as provider-caused."""
        return self._degrade_cause

    async def _await_reply(self) -> "object | None":
        from polymerhus.app.llm.actor import AgentMessage  # noqa: PLC0415
        reply_task = asyncio.ensure_future(self._replies.get())
        try:
            done, _pending = await asyncio.wait(
                {reply_task, self._task}, return_when=asyncio.FIRST_COMPLETED
            )
            if reply_task not in done:
                return None  # the actor task finished first: dead actor, fail-open
            message = reply_task.result()
            if not isinstance(message, AgentMessage):
                return None
            payload = message.payload if isinstance(message.payload, dict) else {}
            return payload.get("content")
        finally:
            if not reply_task.done():
                reply_task.cancel()

    async def _stop(self) -> None:
        """Post the terminal message and reap the actor task (idempotent; safe
        when the actor never spawned or already died)."""
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
            try:
                self._task.exception()
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass


class ThreatModellerActor(_TurnActor):
    """The threat modeller as a persistent MAILBOX actor (S1 4.4).

    ONE actor per hunting run: the modeller pass constructs it (or an injected
    `actor_factory` does) and it spawns a `run_session_agent` on the
    `hunting_threat_modeller` session role under the run's
    `ThreatModellerSession` thread the first time a turn is needed, so its
    checkpointed memory carries the run's reasoning across units. `turn` posts
    one reasoning turn per gate state and awaits the tool-driven turn; the gate
    writes land through the bound `hunts_store` tool (the model is the sole
    writer of the model document).

    The surface is EXACTLY the modeller's (S1 5): `hunts_store`, `notes`, the
    HTTP-history read pair, `exec`, and the web-vulnerability suite pair, plus
    the role's read-only skill + auth binding (`load_skill`, `auth_store`). The
    unit identity follows the pass's retargetable `ModellerUnit` cell, so one
    run-scoped actor serves every unit without stranding its captured tools.

    Fail-open: a dead/crashed actor maps to `None` for every call - the pass's
    breaker counts it and the run pauses rather than fabricating a model.
    `stop` posts the terminal message and reaps the task; safe when never
    spawned."""

    _role_id = "hunting_threat_modeller"
    # The site-declared arming (S1 5.5): the roster declares the role exempt (no
    # catalogue skill bears - the class material is the web-vulnerability suite),
    # so the actor arms the read-only skill surface + `auth_store` here.
    _arm_exempt_surface = True

    def __init__(self, run_id: str, *, checkpointer=None, model_factory=None,
                 observe: bool = True, compaction=None, tools=None,
                 project_id: str | None = None):
        super().__init__(checkpointer=checkpointer, model_factory=model_factory,
                         observe=observe)
        self._run_id = run_id
        self._compaction = compaction  # #95 D9/H: None auto-wires, False disables
        self.tools = tools
        self.project_id = project_id

    @property
    def compaction_manager(self):
        """The wired compaction middleware's manager (#95 D9), or None when
        compaction is disabled or the actor has not taken its first turn."""
        return getattr(self._compaction, "manager", None)

    def _make_address(self):
        from polymerhus.app.llm.session_address import ThreatModellerSession  # noqa: PLC0415
        return ThreatModellerSession(run_id=self._run_id)

    @property
    def _extra_tags(self) -> list | None:
        # Convergence join: the modeller's turns carry the run tag.
        return [self._run_id]

    @property
    def _usage_scope(self) -> str | None:
        return self.project_id

    async def _ensure_started(self) -> None:
        from polymerhus.attack.hunting.llm import _modeller_skill  # noqa: PLC0415
        from polymerhus.attack.hunting.threat_modeller_tools import (  # noqa: PLC0415
            build_modeller_tool_surface,
        )
        if self._compaction is None:
            from polymerhus.app.llm import compaction as C  # noqa: PLC0415
            self._compaction = C.build_role_compaction_middleware(
                "hunting_threat_modeller")
        middleware_extra = None
        if self._compaction is not False:
            middleware_extra = [self._compaction]
        surface: list = []
        if self.tools is not None:
            cell = getattr(self.tools, "unit_cell", None)
            surface = list(build_modeller_tool_surface(
                self.project_id or getattr(self.tools, "project_id", "") or "",
                getattr(cell, "unit_id", "") if cell is not None else "",
                self.tools,
            ).values())
        # No structured response format: the modeller's output IS its gate
        # writes through the bound tools, never a parsed structured decision.
        await super()._ensure_started(
            tools=surface or None,
            middleware_extra=middleware_extra,
            system_prompt=_modeller_skill(),
        )

    def _on_message(self, message, last_turn):
        # The static modeller prompt rides the thread's ONE system message (set
        # at `_ensure_started`), so this returns ONLY the turn's HumanMessage.
        if message.kind == _MODELLER_TURN_KIND:
            payload = message.payload if isinstance(message.payload, dict) else {}
            from polymerhus.attack.hunting.llm import (  # noqa: PLC0415
                _compose_modeller_prompt,
            )
            from langchain_core.messages import HumanMessage  # noqa: PLC0415
            return [HumanMessage(content=_compose_modeller_prompt(payload.get("turn")))]
        if message.kind == "stop":
            from polymerhus.app.llm.actor import STOP  # noqa: PLC0415
            return STOP
        return None

    async def turn(self, turn_input) -> "object | None":
        """Feed one gate-state turn to the actor and await it. The reply carries
        no decision (the gate writes are the output); a None reply is the
        no-decision signal the pass's breaker counts. Fail-open to None."""
        if turn_input is None:
            return None
        try:
            from polymerhus.app.llm.actor import AgentMessage  # noqa: PLC0415
            return await self._post_and_await(
                AgentMessage(kind=_MODELLER_TURN_KIND, payload={"turn": turn_input})
            )
        except Exception:  # noqa: BLE001 - the pass counts a no-decision
            logger.warning("threat modeller actor turn failed", exc_info=True)
            return None

    async def stop(self) -> None:
        await self._stop()


class HuntingHunterActor(_TurnActor):
    """The hunting-hunter as a per-hunt MAILBOX actor (feat/async-actor-agents).

    ONE actor per hunt on the `hunting_hunter` session role (`HuntSession(run_id,
    hunt_id)` thread), spawned lazily by the first author/judge turn. The legacy
    harness (`hunting_agent`) was its client: it posted the composed D4 authoring
    prompt (stable skill already embedded) and awaited the parsed spec, and
    posted the D5 judgment prompt and awaited the parsed judgment; the judge
    resumed the SAME thread, so it saw the author's reasoning (replacing the
    `hunt_session` ContextVar + `stateful_turn` seam, which remains the sync
    rollback lane). AS OF #164 W5 the harness drives `arun_session_turn` directly
    and no longer posts author/judge prompts here - this actor stays as the
    tested rollback lane.

    Turns are free-text-then-parse (the D4 typed base is #83/#84's to ratify), so
    no `response_format` is bound; a None reply is the degraded signal the
    harness already handles. Fail-open: a dead actor yields None.

    Context-window compaction (#95 D9): the actor's turns run COMPACTED on the
    production async lane - the hunting-side compaction middleware
    (`build_hunter_compaction_middleware`) is wired as an extra turn middleware,
    so an over-budget thread spawns out-of-band running-summary passes that the
    next turn's barrier awaits. `compaction=None` auto-wires the middleware from
    the actor's own model (the default), `False` disables it (a plain session,
    identical to the pre-wiring behaviour), and a middleware instance is used
    as-is (tests inject one). `compaction_manager` exposes the wired manager
    (`None` when disabled or before the first turn)."""

    _role_id = "hunting_hunter"

    def __init__(self, run_id: str, hunt_id: str, *, checkpointer=None,
                 model_factory=None, observe: bool = True, compaction=None,
                 author_tools: Sequence = (), project_id: str | None = None):
        super().__init__(checkpointer=checkpointer, model_factory=model_factory,
                         observe=observe, tools=author_tools)
        self._run_id = run_id
        self._hunt_id = hunt_id
        self._compaction = compaction
        self._project_id = project_id

    @property
    def compaction_manager(self):
        """The wired hunting-side compaction middleware's manager (#95 D9), or None
        when compaction is disabled or the actor has not taken its first turn."""
        return getattr(self._compaction, "manager", None)

    async def _ensure_started(self) -> None:
        if self._compaction is None:
            from polymerhus.attack.hunting.llm import (  # noqa: PLC0415
                build_hunter_compaction_middleware,
            )
            self._compaction = build_hunter_compaction_middleware()
        middleware_extra = None
        if self._compaction is not False:
            middleware_extra = [self._compaction]
        await super()._ensure_started(middleware_extra=middleware_extra)

    def _make_address(self):
        from polymerhus.app.llm.session_address import HuntSession  # noqa: PLC0415
        return HuntSession(run_id=self._run_id, hunt_id=self._hunt_id)

    @property
    def _extra_tags(self) -> list | None:
        # Convergence join: the hunter's turns carry the run tag now that the
        # hand-written agent span is gone.
        return [self._run_id]

    @property
    def _usage_scope(self) -> str | None:
        # The hunter's tokens are scoped to the run's project when known.
        return self._project_id

    def _on_message(self, message, last_turn):
        if message.kind in (_AUTHOR_KIND, _JUDGE_KIND):
            payload = message.payload if isinstance(message.payload, dict) else {}
            from langchain_core.messages import HumanMessage  # noqa: PLC0415
            return [HumanMessage(content=payload.get("text") or "")]
        if message.kind == "stop":
            from polymerhus.app.llm.actor import STOP  # noqa: PLC0415
            return STOP
        return None

    async def _turn(self, kind: str, text: str) -> "dict | None":
        from polymerhus.attack.hunting.llm import _parse_json_object  # noqa: PLC0415
        try:
            from polymerhus.app.llm.actor import AgentMessage  # noqa: PLC0415
            content = await self._post_and_await(
                AgentMessage(kind=kind, payload={"text": text})
            )
            return _parse_json_object(content)
        except Exception:  # noqa: BLE001
            logger.warning("hunting-hunter actor %s turn failed", kind, exc_info=True)
            return None

    async def author(self, text: str) -> "dict | None":
        """One D4 spec-authoring turn on the per-hunt thread; None = degraded."""
        return await self._turn(_AUTHOR_KIND, text)

    async def judge(self, text: str) -> "dict | None":
        """One D5 continuation-judgment turn on the per-hunt thread; None = degraded."""
        return await self._turn(_JUDGE_KIND, text)

    async def stop(self) -> None:
        await self._stop()


def _lightrag_author_tools() -> list:
    """Build the LightRAG query tool list for the author lane (lazy). Always
    attempted as of #197 - the `HUNTING_LIGHTRAG_TOOL` opt-in gate is REMOVED.
    Fail-open to `[]` when the lightrag tool is unavailable (the author lane
    then grounds on the threat payload alone)."""
    try:
        from lightrag.tool import build_lightrag_tool  # noqa: PLC0415
        return [build_lightrag_tool()]
    except Exception:  # noqa: BLE001 - fail-open to no KB tool
        return []


class HuntingActorRegistry:
    """Per-run registry of `HuntingHunterActor`s, keyed by hunt_id.

    The run bootstrap hands the harness per-hunt author/judge closures bound to
    these actors: ONE registry serves the run; the harness's `dispatch_fn`
    looks its actor up (or lazily spawns it) by `config.hunt_id`, so concurrent
    hunts never collide and back-edge re-entries resume the same per-hunt
    thread. `stop_all` reaps every spawned actor (idempotent)."""

    def __init__(self, run_id: str, *, checkpointer=None, model_factory=None,
                 observe: bool = True, author_tools: Sequence = (),
                 project_id: str | None = None):
        self._run_id = run_id
        self._checkpointer = checkpointer
        self._model_factory = model_factory
        self._observe = observe
        self._project_id = project_id
        self._author_tools = (
            list(author_tools) if author_tools else _lightrag_author_tools()
        )
        self._actors: dict[str, HuntingHunterActor] = {}

    def actor_for(self, hunt_id: str) -> HuntingHunterActor:
        actor = self._actors.get(hunt_id)
        if actor is None:
            actor = HuntingHunterActor(
                self._run_id, hunt_id,
                checkpointer=self._checkpointer,
                model_factory=self._model_factory,
                observe=self._observe,
                author_tools=self._author_tools,
                project_id=self._project_id,
            )
            self._actors[hunt_id] = actor
        return actor

    def author_fn(self, hunt_id: str):
        """The async `author(text)` seam for `hunt_id`, bound to its actor."""

        async def author(text: str) -> "dict | None":
            return await self.actor_for(hunt_id).author(text)

        return author

    def judge_fn(self, hunt_id: str):
        """The async `judge(text)` seam for `hunt_id`, bound to its actor."""

        async def judge(text: str) -> "dict | None":
            return await self.actor_for(hunt_id).judge(text)

        return judge

    async def stop_all(self) -> None:
        for actor in self._actors.values():
            await actor.stop()
        self._actors.clear()
