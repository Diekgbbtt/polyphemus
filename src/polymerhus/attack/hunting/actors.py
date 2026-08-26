"""The hunting actors: hunt-orchestrator and hunting-hunter as MAILBOX actors
(feat/async-actor-agents).

The hunting effort is now driven by the same actor-with-inbox architecture the
recon-orchestrator uses (`recon/control/orchestrator_agent.ReconOrchestratorActor`):

- `HuntOrchestratorActor` - ONE persistent `run_session_agent` per hunting run on
  the `hunting_orchestrator` session role (`HuntingOrchestratorSession(run_id)`
  thread). Its client (`hunt_orchestrator.arun_orchestration`) posts one message
  per LLM turn of the pass - the hypothesise (Q8 elicitation), ratify, and note
  phase turns (the node-per-phase REASON body, #167), plus the D2 re-match judge
  retained for the runtime plane's dispatch ownership (G12) - and awaits the
  structured reply, all on the SAME thread, so the checkpointer carries the
  pass's reasoning. This makes the hunting_orchestrator PURELY stateful,
  exactly like the recon-orchestrator. The bound tool surface is EXACTLY the
  three tools `hunts_store`, `notes`, `graph_view` (G3).
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

# Message kinds the orchestrator/inbox handler routes on.
_GATE_KIND = "gate"
_RATIFY_KIND = "ratify"
_NOTE_KIND = "note"
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
        middleware = [middleware] if middleware else []
        if middleware_extra:
            middleware = middleware + list(middleware_extra)
        kwargs = {
            "checkpointer": self._checkpointer,
            "inbox": self._inbox,
            "on_message": self._on_message,
            "middleware": middleware,
            "on_turn_degraded": degraded_hook,
            "model_factory": self._model_factory,
            "observe": self._observe,
        }
        if tools:
            kwargs["tools"] = list(tools)
        if response_format is not None:
            kwargs["response_format"] = response_format
        if system_prompt is not None:
            kwargs["system_prompt"] = system_prompt
        if self._tools:
            kwargs["tools"] = self._tools
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
    agent (spec 3.4, amended by #167/G3): EXACTLY the three tools `hunts_store`,
    `notes`, `graph_view` - no back-edge-to-recon tool (the back_edge request to
    recon is out of the agent's surface, operator ruling 2026-08-22; the
    target-knowledge loop rides `graph_view`), no budget tool (G7). The old
    five-tool surface (`read_memory_hunts` / `read_memory_notes` /
    `mint_hunt_config` / `record_note`) is REPLACED.

    `hunts_store` - read/write cmds over the produced/consumed config files.
      `read` needs the config identifier (a revival key `<unit>::<fault>` or a
      full semantic key `<unit>::<CWE>::<class>`) and accepts optionally
      specific `attributes`; the WHOLE projected surface context is NEVER
      readable through it - only the service keys (which may later be inspected
      with `graph_view`, G3). `write` takes the hunt config object (any
      attribute specification is optional; schema validation never rejects on
      missing attributes); the `status` attribute rides the config object
      itself and drives the write: `hypothesised` creates the draft (a
      duplicate identity FAILS with the G4 deduplication signal), `ratified`
      upserts the config in place, `dropped` marks the orphan on disk (G6,
      never deleted). The response injects the phase-transition verbatim from
      the constants (hypothesised -> NEXT_RATIFY_HINT; ratified -> ONLY
      NEXT_NOTE_HINT - G1).
    `notes` - read/write cmds over `memory.yaml`, the SAME data contract as
      `hunts_store`; write options `append` / `update` / `delete`. The append
      response carries the next pair's data + the NEXT_PAIR_HINT constant (the
      pair end, G1).
    `graph_view` - unchanged (read-only L0/L1 view; write-shaped cypher
      surfaces `ReadOnlyGraphViewError` and never executes the write).

    Each tool is bound to its seam body when present; a missing seam body
    degrades to a fail-open stub returning a denoted error object (C18) -
    never raising into the turn. The seam bodies are constructed lazily (this
    module imports no driver at import); the tools are JSON-serialisable
    callables a structured-output session turn can bind."""
    from langchain_core.tools import tool

    from polymerhus.attack.hunting.hunt_orchestrator import (  # noqa: PLC0415
        DuplicateConfigError,
        NEXT_NOTE_HINT,
        NEXT_PAIR_HINT,
        NEXT_RATIFY_HINT,
        ReadOnlyGraphViewError,
    )

    graph_view_seam = getattr(tools, "graph_view", None)
    store_seam = getattr(tools, "store_reads", None)
    phase_context = getattr(tools, "phase_context", None)
    surface: list = []

    # The service keys of a config: the ONLY always-readable projection (G3).
    # The whole projected surface context is never readable through the store
    # tools - surface inspection defers to `graph_view`.
    _SERVICE_KEYS = ("unit_id", "fault_class", "vulnerability_class",
                     "status", "hunt_id")

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
    def hunts_store(cmd: str, *, hunt_config: dict | None = None,
                    key: str | None = None,
                    attributes: list[str] | None = None) -> dict:
        """Read or write hunt configs through the per-project store (G3).
        cmd='read': pass the config identifier `key` (a revival key
        '<unit>::<fault>' or a full semantic key '<unit>::<CWE>::<class>') and
        optionally the specific `attributes` you want; the service keys are
        always returned - the projected surface context is NEVER readable
        through this tool (inspect it with graph_view). cmd='write': pass the
        `hunt_config` object; its `status` attribute ('hypothesised' |
        'ratified' | 'dropped') drives the write - hypothesised creates the
        draft (a duplicate identity FAILS as the deduplication signal, G4),
        ratified / dropped upsert the config in place (dropped stays on disk,
        G6)."""
        if cmd == "read":
            if not key:
                return {"error": "hunts_store read needs the config identifier (key)"}
            if store_seam is None:
                return {"error": "no hunt store configured; configs unavailable",
                        "key": key}
            try:
                read_fn = getattr(store_seam, "read_configs_by_key", None)
                if not callable(read_fn):
                    return {"error": "no hunt store configured; configs unavailable",
                            "key": key}
                configs = list(read_fn(project_id, key))
            except Exception as exc:  # noqa: BLE001 - fail-open (O4)
                logger.warning("hunts_store read degraded for %s (%s)", key, exc)
                return {"error": f"hunts_store read degraded: {exc}", "key": key}
            requested = list(attributes or [])
            out: list[dict] = []
            for cfg in configs:
                projected = {k: cfg.get(k) for k in _SERVICE_KEYS
                             if cfg.get(k) is not None}
                for attr in requested:
                    if attr == "surface_context":
                        # the whole projected surface context is NEVER
                        # readable through the store tools (G3)
                        continue
                    if attr in cfg:
                        projected[attr] = cfg[attr]
                out.append(projected)
            return {"key": key, "configs": out}
        if cmd == "write":
            if not isinstance(hunt_config, dict) or not hunt_config:
                return {"error": "hunts_store write needs the hunt_config object"}
            status = str(hunt_config.get("status") or "hypothesised")
            if status not in ("hypothesised", "ratified", "dropped"):
                return {"error": f"unknown config status {status!r}; known: "
                                 "hypothesised, ratified, dropped"}
            if store_seam is None:
                return {"error": "no hunt store configured; config not written",
                        "status": status}
            try:
                if status == "hypothesised":
                    write_fn = getattr(store_seam, "write_config", None)
                    if not callable(write_fn):
                        return {"error": "no hunt store configured; config not written",
                                "status": status}
                    key = write_fn(project_id, hunt_config)
                    return {"acknowledged": True, "status": status, "key": key,
                            "hint": NEXT_RATIFY_HINT}
                update_fn = getattr(store_seam, "update_config", None)
                if not callable(update_fn):
                    return {"error": "no hunt store configured; config not written",
                            "status": status}
                key = update_fn(project_id, hunt_config)
                if status == "ratified":
                    # G1 correction: the ratification response carries ONLY the
                    # strongly-take-notes verbatim - the next pair is NOT fed
                    # here.
                    return {"acknowledged": True, "status": status, "key": key,
                            "hint": NEXT_NOTE_HINT}
                # a dropped write is ratification-internal (G6): the model
                # keeps ratifying the surviving configs.
                return {"acknowledged": True, "status": status, "key": key,
                        "hint": NEXT_RATIFY_HINT}
            except DuplicateConfigError as exc:
                # G4: the storage-layer deduplication signal - the model
                # interprets it (merges or refreshes instead of duplicating).
                logger.warning("hunts_store write blocked by the novelty gate (%s)",
                               exc)
                return {"error": str(exc), "duplicate": True, "status": status}
            except Exception as exc:  # noqa: BLE001 - fail-open, never into the turn
                logger.warning("hunts_store write degraded (%s)", exc)
                return {"error": f"hunts_store write degraded: {exc}",
                        "status": status}
        return {"error": f"unknown cmd {cmd!r}; known: read, write"}

    @tool
    def notes(cmd: str, *, option: str | None = None, key: str | None = None,
              note: str | None = None, note_id: str | None = None,
              attributes: list[str] | None = None) -> dict:
        """Read or write the project's notes (`memory.yaml`) through the
        per-project store, the SAME data contract as hunts_store (G3).
        cmd='read': pass `key` (a config identifier) and optionally the
        specific `attributes`. cmd='write': pass ONE of the options - 'append'
        (a new note for `key`; the response carries the NEXT pair's data plus
        the restart verbatim - the pair end, G1), 'update' (amend the note with
        `note_id`), or 'delete' (remove the note with `note_id`)."""
        if cmd == "read":
            if not key:
                return {"error": "notes read needs the config identifier (key)"}
            if store_seam is None:
                return {"error": "no notes seam configured; notes unavailable",
                        "key": key}
            try:
                read_fn = getattr(store_seam, "read_notes", None)
                if not callable(read_fn):
                    return {"error": "no notes seam configured; notes unavailable",
                            "key": key}
                notes_list = list(read_fn(project_id, key))
            except Exception as exc:  # noqa: BLE001 - fail-open
                logger.warning("notes read degraded for %s (%s)", key, exc)
                return {"error": f"notes read degraded: {exc}", "key": key}
            requested = list(attributes or [])
            out = []
            for record in notes_list:
                projected = {"note_id": record.get("note_id"),
                             "revival_key": record.get("revival_key"),
                             "note": record.get("note")}
                for attr in requested:
                    if attr in record:
                        projected[attr] = record[attr]
                out.append({k: v for k, v in projected.items()
                            if v is not None})
            return {"key": key, "notes": out}
        if cmd == "write":
            if option not in ("append", "update", "delete"):
                return {"error": "notes write needs an option: "
                                 "append, update, or delete"}
            if store_seam is None:
                return {"error": "no notes seam configured; note not written",
                        "option": option}
            try:
                if option == "append":
                    if not key or not note:
                        return {"error": "notes append needs key and note"}
                    append = getattr(store_seam, "append_note", None)
                    if not callable(append):
                        return {"error": "no notes seam configured; note not written",
                                "option": option}
                    record = append(project_id, key, note)
                    next_pair = None
                    if phase_context is not None:
                        next_pair = getattr(phase_context, "next_pair", None)
                    return {"recorded": True, "key": key,
                            "note_id": record.get("note_id"),
                            "next_pair": next_pair,
                            "hint": NEXT_PAIR_HINT}
                if option == "update":
                    if not note_id or note is None:
                        return {"error": "notes update needs note_id and note"}
                    update = getattr(store_seam, "update_note", None)
                    if not callable(update):
                        return {"error": "no notes seam configured; note not written",
                                "option": option}
                    ok = update(project_id, note_id, note)
                    return {"updated": ok, "note_id": note_id}
                if not note_id:
                    return {"error": "notes delete needs note_id"}
                delete = getattr(store_seam, "delete_note", None)
                if not callable(delete):
                    return {"error": "no notes seam configured; note not written",
                            "option": option}
                ok = delete(project_id, note_id)
                return {"deleted": ok, "note_id": note_id}
            except Exception as exc:  # noqa: BLE001 - fail-open, never into the turn
                logger.warning("notes %s degraded (%s)", option, exc)
                return {"error": f"notes {option} degraded: {exc}"}
        return {"error": f"unknown cmd {cmd!r}; known: read, write"}

    surface.extend([hunts_store, notes, graph_view])
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
        from polymerhus.app.llm.session_address import HuntingOrchestratorSession  # noqa: PLC0415
        return HuntingOrchestratorSession(run_id=self._run_id)

    async def _ensure_started(self) -> None:
        from polymerhus.attack.hunting.hunt_orchestrator import (  # noqa: PLC0415
            GateDecision,
            MatchVerdict,
            NoteDecision,
            RatifyDecision,
        )
        from polymerhus.attack.hunting.llm import _gate_skill  # noqa: PLC0415
        from langchain.agents.structured_output import ToolStrategy  # noqa: PLC0415
        if self._compaction is None:
            from polymerhus.app.llm import compaction as C  # noqa: PLC0415
            self._compaction = C.build_role_compaction_middleware(
                "hunting_orchestrator")
        middleware_extra = None
        if self._compaction is not False:
            middleware_extra = [self._compaction]
        surface = ()
        if (getattr(self.tools, "back_edge", None) is not None
                or getattr(self.tools, "graph_view", None) is not None
                or getattr(self.tools, "store_reads", None) is not None):
            surface = build_orchestrator_tool_surface(
                self.tools,
                run_id=self._run_id,
                project_id=self.project_id,
            )
        # The static gate skill is the run's ONE system message on this thread
        # (#187): passed ONCE via `system_prompt`, never re-added per phase turn
        # (the per-turn re-add used to stack a byte-identical copy on every
        # gate/ratify/note turn - the ~145K of ~14 stale copies behind the
        # timeout). The phase-transition verbatims stay in the tool-call
        # responses (G1/G3), never here.
        await super()._ensure_started(
            response_format=ToolStrategy(
                GateDecision | RatifyDecision | NoteDecision | MatchVerdict),
            tools=list(surface) or None,
            middleware_extra=middleware_extra,
            system_prompt=_gate_skill(),
        )

    def _on_message(self, message, last_turn):
        # The static gate skill rides the thread's ONE system message (set once
        # at `_ensure_started` as `system_prompt`), so the phase branches return
        # ONLY the phase's HumanMessage - never a per-turn SystemMessage copy
        # (#187: the old per-turn `SystemMessage(content=_gate_skill())` stacked
        # a byte-identical copy on every gate/ratify/note turn).
        if message.kind == _GATE_KIND:
            payload = message.payload if isinstance(message.payload, dict) else {}
            from polymerhus.attack.hunting.llm import _compose_gate_prompt  # noqa: PLC0415
            from langchain_core.messages import HumanMessage  # noqa: PLC0415
            return [
                HumanMessage(content=_compose_gate_prompt(payload.get("input"))),
            ]
        if message.kind == _RATIFY_KIND:
            payload = message.payload if isinstance(message.payload, dict) else {}
            from polymerhus.attack.hunting.llm import _compose_ratify_prompt  # noqa: PLC0415
            from langchain_core.messages import HumanMessage  # noqa: PLC0415
            return [
                HumanMessage(content=_compose_ratify_prompt(payload.get("input"))),
            ]
        if message.kind == _NOTE_KIND:
            payload = message.payload if isinstance(message.payload, dict) else {}
            from polymerhus.attack.hunting.llm import _compose_note_prompt  # noqa: PLC0415
            from langchain_core.messages import HumanMessage  # noqa: PLC0415
            return [
                HumanMessage(content=_compose_note_prompt(payload.get("input"))),
            ]
        if message.kind == _REMATCH_KIND:
            # The rematch skill is a RARE turn: a single per-turn SystemMessage
            # on rematch is acceptable (it does not accumulate across the run's
            # gate/ratify/note cadence), so it stays here rather than joining the
            # gate skill's system message (#187).
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

    async def hypothesise(self, gate_input) -> "GateDecision | None":
        """Feed the HYPOTHESISE-phase input to the actor and await its
        `GateDecision` (the elicitation the mint fans out at this phase).
        Fail-open to None (the pass then carries the pair bare)."""
        if gate_input is None or not getattr(gate_input, "candidates", None):
            return None
        try:
            from polymerhus.app.llm.actor import AgentMessage  # noqa: PLC0415
            content = await self._post_and_await(
                AgentMessage(kind=_GATE_KIND, payload={"input": gate_input})
            )
            from polymerhus.attack.hunting.hunt_orchestrator import GateDecision  # noqa: PLC0415
            if not isinstance(content, GateDecision):
                logger.warning(
                    "hunt-orchestrator hypothesise turn returned a non-GateDecision "
                    "member (%s); treating it as no-decision",
                    type(content).__name__ if content is not None else "None")
                return None
            return content
        except Exception:  # noqa: BLE001
            logger.warning("hunt-orchestrator actor hypothesise turn failed; carrying the pair bare",
                           exc_info=True)
            return None

    async def ratify(self, phase_input) -> "RatifyDecision | None":
        """Feed the RATIFY-phase input to the actor and await its
        `RatifyDecision` (the configs at their final status).
        Fail-open to None (the drafts stay hypothesised)."""
        try:
            from polymerhus.app.llm.actor import AgentMessage  # noqa: PLC0415
            content = await self._post_and_await(
                AgentMessage(kind=_RATIFY_KIND, payload={"input": phase_input})
            )
            from polymerhus.attack.hunting.hunt_orchestrator import RatifyDecision  # noqa: PLC0415
            if not isinstance(content, RatifyDecision):
                logger.warning(
                    "hunt-orchestrator ratify turn returned a non-RatifyDecision "
                    "member (%s); treating it as no-decision",
                    type(content).__name__ if content is not None else "None")
                return None
            return content
        except Exception:  # noqa: BLE001
            logger.warning("hunt-orchestrator actor ratify turn failed",
                           exc_info=True)
            return None

    async def note(self, phase_input) -> "NoteDecision | None":
        """Feed the NOTE-phase input to the actor and await its `NoteDecision`
        (the notes the pair writes). Fail-open to None (no note is written)."""
        try:
            from polymerhus.app.llm.actor import AgentMessage  # noqa: PLC0415
            content = await self._post_and_await(
                AgentMessage(kind=_NOTE_KIND, payload={"input": phase_input})
            )
            from polymerhus.attack.hunting.hunt_orchestrator import NoteDecision  # noqa: PLC0415
            if not isinstance(content, NoteDecision):
                logger.warning(
                    "hunt-orchestrator note turn returned a non-NoteDecision "
                    "member (%s); treating it as no-decision",
                    type(content).__name__ if content is not None else "None")
                return None
            return content
        except Exception:  # noqa: BLE001
            logger.warning("hunt-orchestrator actor note turn failed",
                           exc_info=True)
            return None

    async def reason(self, gate_input) -> "GateDecision | None":
        """Feed the Q8 gate input to the actor and await its `GateDecision`.
        Fail-open to None (the pass then carries every candidate). Retained as
        the legacy alias of the hypothesise turn (the sync rollback lane)."""
        return await self.hypothesise(gate_input)

    async def rematch(
        self, unit_id: str, fault_class: str, result
    ) -> "MatchVerdict | None":
        """Feed the D2 re-match request to the actor and await its `MatchVerdict`
        on the SAME thread. Fail-open to None (the caller lands unresolved).
        Retained for the runtime plane's dispatch ownership (G12) - the graph
        no longer routes dispatch."""
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
                 author_tools: Sequence = ()):
        super().__init__(checkpointer=checkpointer, model_factory=model_factory,
                         observe=observe, tools=author_tools)
        self._run_id = run_id
        self._hunt_id = hunt_id
        self._compaction = compaction

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
    """Build the optional LightRAG query tool list for the author lane (lazy)."""
    from polymerhus.app.config import config
    from lightrag.tool import build_lightrag_tool

    if not config.HUNTING_LIGHTRAG_TOOL:
        return []
    return [build_lightrag_tool()]


class HuntingActorRegistry:
    """Per-run registry of `HuntingHunterActor`s, keyed by hunt_id.

    The production composition point hands the harness per-hunt author/judge
    closures bound to these actors: `asyncio.run(arun_orchestration(...))`
    (or a future live entry point) owns ONE registry for the run; the harness's
    `dispatch_fn` looks its actor up (or lazily spawns it) by `config.hunt_id`,
    so concurrent hunts never collide and back-edge re-entries resume the same
    per-hunt thread. `stop_all` reaps every spawned actor (idempotent)."""

    def __init__(self, run_id: str, *, checkpointer=None, model_factory=None,
                 observe: bool = True, author_tools: Sequence = ()):
        self._run_id = run_id
        self._checkpointer = checkpointer
        self._model_factory = model_factory
        self._observe = observe
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
