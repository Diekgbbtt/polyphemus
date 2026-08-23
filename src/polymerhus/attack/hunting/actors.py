"""The hunting actors: hunt-orchestrator and hunting-hunter as MAILBOX actors
(feat/async-actor-agents).

The hunting effort is now driven by the same actor-with-inbox architecture the
recon-orchestrator uses (`recon/control/orchestrator_agent.ReconOrchestratorActor`):

- `HuntOrchestratorActor` - ONE persistent `run_session_agent` per hunting run on
  the `hunting_orchestrator` session role (`HuntingOrchestratorSession(run_id)`
  thread). Its client (`hunt_orchestrator.arun_orchestration`) posts one message
  per LLM turn of the pass - the Q8 gate reasoning and the D2 re-match judge -
  and awaits the structured reply, all on the SAME thread, so the checkpointer
  carries the pass's reasoning. This makes the hunting_orchestrator PURELY
  stateful, exactly like the recon-orchestrator.
- `HuntingHunterActor` - one per hunt on the `hunting_hunter` session role
  (`HuntSession(run_id, hunt_id)` thread), fed the spec-authoring (D4) and
  continuation-judgment (D5) prompts via its inbox. `HuntingActorRegistry`
  hands the async hunting-agent harness (`hunting_agent.build_hunting_agent`)
  per-hunt author/judge closures bound to these actors.

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

logger = logging.getLogger(__name__)

# Message kinds the orchestrator/inbox handler routes on.
_GATE_KIND = "gate"
_REMATCH_KIND = "rematch"
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

    def __init__(self, checkpointer=None, model_factory=None, observe: bool = True):
        self._checkpointer = checkpointer
        self._model_factory = model_factory
        self._observe = observe
        self._address = None
        self._inbox = None
        self._replies = None
        self._task = None

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

    async def _ensure_started(self, response_format=None, system_prompt=None,
                              middleware_extra: list = None, tools=None) -> None:
        """Spawn the actor task on first use (lazy: a pass with no turns never
        pays for an actor), wiring the reply middleware into its turns."""
        if self._task is not None:
            return
        from langchain.agents.structured_output import ToolStrategy  # noqa: PLC0415
        from polymerhus.app.llm.actor import (  # noqa: PLC0415
            AgentInbox,
            build_inbox_middleware,
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
        middleware = [build_inbox_middleware(
            replies, kind=_REPLY_KIND, source=_REPLY_SOURCE
        )]
        if middleware_extra:
            middleware = middleware + list(middleware_extra)
        kwargs = {
            "checkpointer": self._checkpointer,
            "inbox": self._inbox,
            "on_message": self._on_message,
            "middleware": middleware,
            "model_factory": self._model_factory,
            "observe": self._observe,
        }
        if tools:
            kwargs["tools"] = list(tools)
        if response_format is not None:
            kwargs["response_format"] = response_format
        if system_prompt is not None:
            kwargs["system_prompt"] = system_prompt
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
        from polymerhus.app.llm.actor import AgentMessage  # noqa: PLC0415
        await self._inbox.post(message)
        return await self._await_reply()

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


def build_orchestrator_tool_surface(tools, *, run_id: str, project_id: str | None):
    """The model-facing tool surface bound onto the orchestrator's session
    agent (spec 3.4, the candidates-rewrite Q14/Q15 correction): EXACTLY the
    five tools `read_memory_hunts`, `read_memory_notes`, `graph_view`,
    `mint_hunt_config`, `record_note` - no back-edge-to-recon tool (the back_edge
    request to recon is out of the agent's surface, operator ruling 2026-08-22;
    the target-knowledge loop rides `graph_view`), no HuntConfig-writing tool
    (the mint stays deterministic at dispatch) and no budget-consume tool (Q7).
    `store_reads` is SPLIT into the two memory reads (`read_memory_hunts`
    returns prior dispatched config content by revival key, `read_memory_notes`
    returns the notes on the same key); `mint_hunt_config` carries the model's
    emitted candidate set onto the run-local emission bucket for the
    deterministic mint (T4 consumes the bucket), never writing a config object;
    `record_note` persists a note to the keyed notes seam. `graph_view` rides
    `ReadOnlyGraphView`, so a write-shaped cypher surfaces
    `ReadOnlyGraphViewError` and never executes the write (C19/C5).

    Each READ/WRITE-side tool is bound to its seam body when present; a missing
    seam body degrades to a fail-open stub returning a denoted error object
    (C18) - never raising into the turn. The `mint_hunt_config` seam is the
    `tools.mint_emissions` bucket; the note/hunt-read seams are the hunt store
    (`tools.store_reads`, its `config` / `notes` kinds), absent when the store
    is absent (#70 owns the real notes seam body).

    The seam bodies themselves are constructed lazily (this module imports no
    driver at import); the tools are JSON-serialisable callables a
    structured-output session turn can bind."""
    from langchain_core.tools import tool

    from polymerhus.attack.hunting.hunt_orchestrator import (  # noqa: PLC0415
        ReadOnlyGraphViewError,
    )

    graph_view_seam = getattr(tools, "graph_view", None)
    store_seam = getattr(tools, "store_reads", None)
    mint_seam = getattr(tools, "mint_emissions", None)
    surface: list = []

    @tool
    def graph_view(cypher: str, params: dict | None = None) -> dict:
        """Read the live L0/L1 graph through the run's read-only view (D67-04):
        read index cards / typed facets with read-only cypher. Write-shaped
        cypher is rejected (surfaces ReadOnlyGraphViewError, never writes); a
        read failure degrades to an empty denoted-error result (O5)."""
        if graph_view_seam is None:
            return {"error": "no graph view configured; reading degraded"}
        read_fn = getattr(graph_view_seam, "read", None)
        if not callable(read_fn):
            return {"error": "graph view misconfigured; reading degraded"}
        try:
            rows = read_fn(cypher, params or {})
            if not isinstance(rows, list):
                return {"rows": [rows] if rows is not None else []}
            return {"rows": rows}
        except ReadOnlyGraphViewError:
            raise  # surfaced to the model by the tool runtime - never a write
        except Exception as exc:  # noqa: BLE001 - fail-open (O5)
            logger.warning("graph_view tool degraded (%s)", exc)
            return {"error": f"graph_view degraded: {exc}"}

    @tool
    def read_memory_hunts(revival_key: str) -> dict:
        """Read the prior dispatched `HuntConfig` content for a revival key
        ('<unit_id>::<fault_class>') from the run's hunt store (O4/Q14): the
        prior configs the Q11 novelty reflection inspects. A missing or failing
        store degrades to a denoted error, never into the turn."""
        if store_seam is None:
            return {"error": "no hunt store configured; prior configs unavailable",
                    "revival_key": revival_key}
        try:
            read_fn = getattr(store_seam, "read_configs_by_key", None)
            if callable(read_fn):
                return {"revival_key": revival_key,
                        "configs": list(read_fn(run_id, revival_key))}
            return {"revival_key": revival_key, "configs": []}
        except Exception as exc:  # noqa: BLE001 - fail-open (O4)
            logger.warning("read_memory_hunts tool degraded for %s (%s)",
                           revival_key, exc)
            return {"error": f"read_memory_hunts degraded: {exc}",
                    "revival_key": revival_key}

    @tool
    def read_memory_notes(revival_key: str) -> dict:
        """Read the notes for a revival key from the run's hunt store (Q14),
        keyed identically to the hunts ('keys of huntconfigs and respective
        notes are the same'). The real notes seam body is the memory workstream
        (#70); a missing or failing seam degrades to a denoted error, never
        into the turn."""
        if store_seam is None:
            return {"error": "no notes seam configured; notes unavailable",
                    "revival_key": revival_key}
        try:
            read_fn = getattr(store_seam, "read_notes", None)
            if callable(read_fn):
                return {"revival_key": revival_key,
                        "notes": list(read_fn(run_id, revival_key))}
            return {"revival_key": revival_key, "notes": []}
        except Exception as exc:  # noqa: BLE001 - fail-open
            logger.warning("read_memory_notes tool degraded for %s (%s)",
                           revival_key, exc)
            return {"error": f"read_memory_notes degraded: {exc}",
                    "revival_key": revival_key}

    @tool
    def mint_hunt_config(unit_id: str, vulnerability_classes: list,
                         research_direction: str | None = None) -> dict:
        """Submit the unit's elicited vulnerability classes ONCE at its end
        (Q8/Q12/Q15): carries the model's choice (research_direction plus the
        vulnerability classes); the MODULE mints the N `HuntConfig`s
        deterministically from the emitted set afterwards - one hypothesised
        draft per distinct class. NO config object is written here. The
        emission is recorded onto the run-local seam for the deterministic mint
        to fan out from; a missing seam degrades to a denoted error, never into
        the turn."""
        if mint_seam is None:
            return {"error": "no mint emissions seam configured; emission "
                             "not recorded", "unit_id": unit_id}
        try:
            emission = {
                "unit_id": unit_id,
                "research_direction": research_direction or "",
                "vulnerability_classes": [
                    str(c) for c in (vulnerability_classes or [])],
            }
            mint_seam.append(emission)
            return {"acknowledged": True, "unit_id": unit_id,
                    "recorded_classes": len(emission["vulnerability_classes"])}
        except Exception as exc:  # noqa: BLE001 - fail-open, never into the turn
            logger.warning("mint_hunt_config tool degraded for %s (%s)",
                           unit_id, exc)
            return {"error": f"mint_hunt_config degraded: {exc}", "unit_id": unit_id}

    @tool
    def record_note(revival_key: str, note: str) -> dict:
        """Record a note for a revival key at the unit boundary, deterministically
        (Q10), immediately after `mint_hunt_config`: persists to the keyed notes
        seam. The parallel memory workstream (#70) owns the real seam body; a
        missing or failing seam degrades to a denoted error, never into the
        turn."""
        if store_seam is None:
            return {"error": "no notes seam configured; note not recorded",
                    "revival_key": revival_key}
        try:
            store_seam.append(run_id, "notes",
                              {"revival_key": revival_key, "note": note})
            return {"recorded": True, "revival_key": revival_key}
        except Exception as exc:  # noqa: BLE001 - fail-open, never into the turn
            logger.warning("record_note tool degraded for %s (%s)",
                           revival_key, exc)
            return {"error": f"record_note degraded: {exc}",
                    "revival_key": revival_key}

    surface.extend([
        graph_view, read_memory_hunts, read_memory_notes,
        mint_hunt_config, record_note,
    ])
    return surface


class HuntOrchestratorActor(_TurnActor):
    """The hunt-orchestrator as a persistent MAILBOX actor (feat/async-actor-agents).

    ONE actor per hunting run: `arun_orchestration` (or an injected
    `orchestrator_factory`) constructs it, and it spawns a `run_session_agent`
    on the `hunting_orchestrator` session role under the run's
    `HuntingOrchestratorSession` thread the first time a turn is needed. `reason`
    posts a Q8 gate-reasoning request and awaits the structured `GateDecision`;
    `rematch` posts a D2 re-match request and awaits the structured `MatchVerdict`
    - both on the SAME thread, so the checkpointed memory carries the pass's
    reasoning (purely stateful, exactly like the recon-orchestrator).

    The agent's structured-output surface is the UNION
    `GateDecision | MatchVerdict` (a `ToolStrategy` accepts a union schema): the
    model emits whichever schema the turn's prompt asks for, and the client
    classifies the reply by the requested kind.

    Fail-open: a dead/crashed actor maps to `None` for both calls - the caller's
    fail-open canon degrades (carry every candidate / insufficient-evidence).
    `stop` posts the terminal message and reaps the task; safe when never spawned."""

    _role_id = "hunting_orchestrator"

    def __init__(self, run_id: str, *, checkpointer=None, model_factory=None,
                 observe: bool = True, tools=None, project_id: str | None = None):
        super().__init__(checkpointer=checkpointer, model_factory=model_factory,
                         observe=observe)
        self._run_id = run_id
        self.tools = tools
        self.project_id = project_id

    def _make_address(self):
        from polymerhus.app.llm.session_address import HuntingOrchestratorSession  # noqa: PLC0415
        return HuntingOrchestratorSession(run_id=self._run_id)

    async def _ensure_started(self) -> None:
        from polymerhus.attack.hunting.hunt_orchestrator import (  # noqa: PLC0415
            GateDecision,
            MatchVerdict,
        )
        from langchain.agents.structured_output import ToolStrategy  # noqa: PLC0415
        surface = ()
        if (getattr(self.tools, "back_edge", None) is not None
                or getattr(self.tools, "graph_view", None) is not None
                or getattr(self.tools, "store_reads", None) is not None
                or getattr(self.tools, "mint_emissions", None) is not None):
            surface = build_orchestrator_tool_surface(
                self.tools,
                run_id=self._run_id,
                project_id=self.project_id,
            )
        await super()._ensure_started(
            response_format=ToolStrategy(GateDecision | MatchVerdict),
            tools=list(surface) or None,
        )

    def _on_message(self, message, last_turn):
        if message.kind == _GATE_KIND:
            payload = message.payload if isinstance(message.payload, dict) else {}
            from polymerhus.attack.hunting.llm import _compose_gate_prompt, _gate_skill  # noqa: PLC0415
            from langchain_core.messages import HumanMessage, SystemMessage  # noqa: PLC0415
            return [
                SystemMessage(content=_gate_skill()),
                HumanMessage(content=_compose_gate_prompt(payload.get("input"))),
            ]
        if message.kind == _REMATCH_KIND:
            payload = message.payload if isinstance(message.payload, dict) else {}
            from polymerhus.attack.hunting.llm import _compose_rematch_prompt, _rematch_skill  # noqa: PLC0415
            from langchain_core.messages import HumanMessage, SystemMessage  # noqa: PLC0415
            return [
                SystemMessage(content=_rematch_skill()),
                HumanMessage(content=_compose_rematch_prompt(
                    payload.get("unit_id"), payload.get("fault_class"),
                    payload.get("result"))),
            ]
        if message.kind == "stop":
            from polymerhus.app.llm.actor import STOP  # noqa: PLC0415
            return STOP
        return None

    async def reason(self, gate_input) -> "GateDecision | None":
        """Feed the Q8 gate input to the actor and await its `GateDecision`.
        Fail-open to None (the pass then carries every candidate)."""
        if gate_input is None or not getattr(gate_input, "candidates", None):
            return None
        try:
            from polymerhus.app.llm.actor import AgentMessage  # noqa: PLC0415
            content = await self._post_and_await(
                AgentMessage(kind=_GATE_KIND, payload={"input": gate_input})
            )
            from polymerhus.attack.hunting.hunt_orchestrator import GateDecision  # noqa: PLC0415
            return content if isinstance(content, GateDecision) else None
        except Exception:  # noqa: BLE001
            logger.warning("hunt-orchestrator actor gate turn failed; carrying all candidates",
                           exc_info=True)
            return None

    async def rematch(
        self, unit_id: str, fault_class: str, result
    ) -> "MatchVerdict | None":
        """Feed the D2 re-match request to the actor and await its `MatchVerdict`
        on the SAME thread. Fail-open to None (the caller lands unresolved)."""
        try:
            from polymerhus.app.llm.actor import AgentMessage  # noqa: PLC0415
            content = await self._post_and_await(
                AgentMessage(kind=_REMATCH_KIND, payload={
                    "unit_id": unit_id, "fault_class": fault_class, "result": result,
                })
            )
            from polymerhus.attack.hunting.hunt_orchestrator import MatchVerdict  # noqa: PLC0415
            return content if isinstance(content, MatchVerdict) else None
        except Exception:  # noqa: BLE001
            logger.warning("hunt-orchestrator actor rematch turn failed",
                           exc_info=True)
            return None

    async def stop(self) -> None:
        await self._stop()


class HuntingHunterActor(_TurnActor):
    """The hunting-hunter as a per-hunt MAILBOX actor (feat/async-actor-agents).

    ONE actor per hunt on the `hunting_hunter` session role (`HuntSession(run_id,
    hunt_id)` thread), spawned lazily by the first author/judge turn. The harness
    (`hunting_agent`) is the client: it posts the composed D4 authoring prompt
    (stable skill already embedded) and awaits the parsed spec, and posts the D5
    judgment prompt and awaits the parsed judgment; re-entries after a routed
    back-edge resume the SAME thread, so the judge sees the author's reasoning
    (replacing the `hunt_session` ContextVar + `stateful_turn` seam, which
    remains the sync rollback lane).

    Turns are free-text-then-parse (the D4 typed base is #83/#84's to ratify), so
    no `response_format` is bound; a None reply is the degraded signal the
    harness already handles. Fail-open: a dead actor yields None."""

    _role_id = "hunting_hunter"

    def __init__(self, run_id: str, hunt_id: str, *, checkpointer=None,
                 model_factory=None, observe: bool = True):
        super().__init__(checkpointer=checkpointer, model_factory=model_factory,
                         observe=observe)
        self._run_id = run_id
        self._hunt_id = hunt_id

    def _make_address(self):
        from polymerhus.app.llm.session_address import HuntSession  # noqa: PLC0415
        return HuntSession(run_id=self._run_id, hunt_id=self._hunt_id)

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


class HuntingActorRegistry:
    """Per-run registry of `HuntingHunterActor`s, keyed by hunt_id.

    The production composition point hands the harness per-hunt author/judge
    closures bound to these actors: `asyncio.run(arun_orchestration(...))`
    (or a future live entry point) owns ONE registry for the run; the harness's
    `dispatch_fn` looks its actor up (or lazily spawns it) by `config.hunt_id`,
    so concurrent hunts never collide and back-edge re-entries resume the same
    per-hunt thread. `stop_all` reaps every spawned actor (idempotent)."""

    def __init__(self, run_id: str, *, checkpointer=None, model_factory=None,
                 observe: bool = True):
        self._run_id = run_id
        self._checkpointer = checkpointer
        self._model_factory = model_factory
        self._observe = observe
        self._actors: dict[str, HuntingHunterActor] = {}

    def actor_for(self, hunt_id: str) -> HuntingHunterActor:
        actor = self._actors.get(hunt_id)
        if actor is None:
            actor = HuntingHunterActor(
                self._run_id, hunt_id,
                checkpointer=self._checkpointer,
                model_factory=self._model_factory,
                observe=self._observe,
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