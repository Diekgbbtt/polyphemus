"""The ONE turn seam every analysis proposer goes through (#94, #187 converged).

The three chunk-fed proposers (`assigner`, `mechanism_typist`, `data_modeller`) are
structurally identical in how a turn is built: one per-run `AnalysisSession`
thread, the role's #95 compaction middleware, the run-correlation tag, the project
usage scope, and the role's OWN prompt. They therefore share one construction seam,
so they can never drift - the same reason #187 converged the hunting gate actor
onto `system_prompt=` and off the per-turn `SystemMessage` re-add.

The load-bearing decision: the role prompt is bound ONCE, ephemerally, through
`create_agent(system_prompt=...)`. The factory prepends it at each model
invocation and NEVER writes it into the checkpoint state, so the trail carries only
the per-call human task and the model's answers, and the request prefix is a
byte-identical leading block on every call. The pre-#187 shape re-added the prompt
as a `SystemMessage` TRAIL message on every call, which stacked a copy per call and
moved the prompt to a shifting position - the structure that produced the
`mechanism_typist` quadratic input growth (see
`docs/design/converged-agent-turn-adr.md`).

Two legs, one prompt:
- `session_invoke_fn` - the production leg. The prompt rides the `system_prompt=`
  binding; the caller's messages are forwarded verbatim.
- `prepend_prompt` - the one-shot legacy leg (the contract tier's
  `invoke_role` path). It heads the request list with the same prompt, exactly
  where the agent layer puts it, so a proposed move to the stateful leg changes
  nothing about the request the model sees.

Importing this module performs no I/O and reads no env var (CODING_STANDARD
section 6); the prompts and the checkpointer resolve on call.
"""
from __future__ import annotations

import contextlib
import contextvars
from typing import Any, Iterator, Sequence

from langchain_core.messages import BaseMessage, SystemMessage

# Distinguishes "the caller passed no schema" (use the role's own default) from
# "the caller passed schema=None" (a deliberate prose turn). Every analysis proposer
# now defaults to the one structured envelope `AnalysisTurn`, so a normal turn is
# always structured; the explicit-None prose path is retained for a caller that
# genuinely wants free text.
_NO_SCHEMA = object()

# The per-streamed-chunk memory scope (the per-batch discriminator). A proposer body
# opens it around its invoke chain, so every turn of ONE chunk addresses the same
# session (within-chunk memory is kept) while the next chunk addresses a FRESH thread
# (`AnalysisSession(run, role, batch=...)`). It is a ContextVar, the repo's established
# scoped-ambient pattern (`conversation_scope`, `module_context`), so the invoke
# contract `(messages, *, schema, system_prompt)` is unchanged.
_BATCH: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "proposer-batch", default=None)


@contextlib.contextmanager
def proposer_batch(batch_id: str | None) -> Iterator[None]:
    """Scope the turns of ONE streamed chunk as the session batch. A None batch is a
    no-op scope, so a caller that sets none keeps the `run:role` thread."""
    token = _BATCH.set(batch_id)
    try:
        yield
    finally:
        _BATCH.reset(token)


def current_batch() -> str | None:
    """The batch id of the innermost active `proposer_batch` scope, or None."""
    return _BATCH.get()


def _role_prompt(role_id: str) -> str:
    """The role's OWN stable prompt, resolved on call (no import-time I/O).

    The prompt is memoized in-process inside each proposer module (a missing
    prompt file is a defect, so each read is FAIL-CLOSED), which is what keeps it
    byte-identical across a run - the property the whole converged seam rests on.
    """
    if role_id == "assigner":
        from polymerhus.analysis.assigner import _system_prompt

        return _system_prompt()
    if role_id == "mechanism_typist":
        from polymerhus.analysis.mechanism_typist import _load_skill

        return _load_skill()
    if role_id == "data_modeller":
        from polymerhus.analysis.data_modeller import _system_prompt

        return _system_prompt()
    raise KeyError(f"no registered role prompt for {role_id!r}; the analysis "
                   f"proposers are assigner, mechanism_typist, data_modeller")


def _role_default_schema(role_id: str) -> Any:
    """The role's default structured-output schema. Every analysis proposer now speaks
    the ONE envelope `AnalysisTurn`: its reasoning sub-problems populate `claims` and
    its extraction sub-problems populate the delta lists, so a caller that passes no
    schema still gets the role's output contract."""
    if role_id in ("assigner", "mechanism_typist", "data_modeller"):
        from polymerhus.analysis.reasoning_workflow import AnalysisTurn

        return AnalysisTurn
    return None


def _role_structured_schema(role_id: str) -> Any:
    """The schema a role's structured turns use, or None for a role with no structured
    contract. `AnalysisTurn` is the single structured tool every analysis proposer
    binds, so the request shape never toggles across its sub-problems (ADR D26)."""
    if role_id in ("assigner", "mechanism_typist", "data_modeller"):
        from polymerhus.analysis.reasoning_workflow import AnalysisTurn

        return AnalysisTurn
    return None


def _analysis_notes_tool(project_id: str | None):
    """The analysis `notes` tool, bound on every proposer turn through the session
    `tools=` seam - NEVER the skills seam (`skill_agent_binding` would raise for an
    undeclared role; ADR D33). The store is per-project; the Service slug is a
    request field, so a later unit reads earlier units' notes. Fail-open: an
    unbuildable notes tool binds nothing (the session always starts)."""
    try:
        from polymerhus.analysis.memory import AnalysisMemoryStore, notes_tool_for

        return notes_tool_for(
            store=AnalysisMemoryStore(), project_id=project_id or "")
    except Exception:  # noqa: BLE001 - fail-open: an unbuildable notes tool binds nothing
        return None


# The roles whose harvest needs the recorded request shapes, so they bind the
# HTTP-history pair on every turn (the constant-tool-set rule). All three analysis
# proposers harvest a surface now: the data-modeller always did, and the assigner /
# mechanism-typist discovery phases query paths the history can confirm.
_HTTP_TOOL_ROLES = frozenset({"assigner", "mechanism_typist", "data_modeller"})


def _surface_tools(role_id: str, project_id: str | None) -> tuple:
    """The L0-grounding tools every proposer binds (analysis-unit-first v2): the
    read-only `graph_view` (broad L0 query) plus the HTTP-history read pair (recorded
    request shapes) for the roles that harvest a surface. All three proposers harvest
    now - the assigner and the mechanism-typist discover their surface too - so they
    all bind the pair, and it is present on every turn (the cache rule). Fail-open:
    an unbuildable surface binds nothing. The set is constant across the role's
    turns."""
    try:
        from polymerhus.analysis.graph_tools import build_surface_tools

        return build_surface_tools(
            role_id, project_id=project_id, with_http=role_id in _HTTP_TOOL_ROLES)
    except Exception:  # noqa: BLE001 - fail-open: no surface tools bound
        return ()


def _prose_tools(role_id: str, *, project_id: str | None = None) -> tuple:
    """The tools bound on a PROSE turn, so the tool set is constant across the
    role's calls (the cache-shape rule): the shared `notes` tool, the
    L0-grounding surface tools, plus the role's structured-output tool.

    The structured turn supplies the structured tool through `response_format`
    (which `create_agent` appends AFTER the passed tools), so a prose turn binds
    `(notes, AnalysisTurn)` in that exact order to reproduce the same final bound
    list. The structured tool is the EXACT tool the ToolStrategy path builds - the
    agent factory's own `OutputToolBinding.from_schema_spec` derivation, not a
    hand-built look-alike - so the serialized `tools=` payload is byte-identical
    between the prose and structured turns. Fail-open: an unbuildable shape binds
    nothing (the session always starts)."""
    schema = _role_structured_schema(role_id)
    if schema is None:
        return ()
    tools: list = []
    notes = _analysis_notes_tool(project_id)
    if notes is not None:
        tools.append(notes)
    tools.extend(_surface_tools(role_id, project_id))
    try:
        from langchain.agents.structured_output import OutputToolBinding, ToolStrategy

        from polymerhus.app.llm.session import structured_response_format

        # The notes tool is a per-project memory sidecar, NOT the structured-output
        # carrier: the negotiation axis stays the NO-TOOLS axis (as before the notes
        # binding), so adding `notes` never flips the negotiated method or the
        # request shape (ADR D34). The structured turn supplies the structured tool
        # through `response_format`.
        fmt = structured_response_format(role_id, schema, tools_bound=False)
        if not isinstance(fmt, ToolStrategy):
            return tuple(tools)
        # The SAME derivation `create_agent` runs for the structured turn
        # (`OutputToolBinding.from_schema_spec`), so the two turns cannot drift.
        tools.append(OutputToolBinding.from_schema_spec(fmt.schema_specs[0]).tool)
    except Exception:  # noqa: BLE001 - fail-open: an unbuildable tool binds nothing
        return tuple(tools)
    return tuple(tools)


def _turn_tools(role_id: str, project_id: str | None, *,
                structured_bound: bool) -> tuple:
    """The constant per-role tool set for ONE turn.

    A structured turn passes only `notes` and lets `response_format` append
    `AnalysisTurn`; a prose turn passes `(notes, AnalysisTurn)` directly. Both
    final bound lists are `(notes, AnalysisTurn)`, so the request shape never
    toggles between a role's reflection and extraction turns (the shape that
    defeated the provider prefix cache; ADR D26/D34)."""
    if _role_structured_schema(role_id) is None:
        return ()
    if structured_bound:
        tools: list = []
        notes = _analysis_notes_tool(project_id)
        if notes is not None:
            tools.append(notes)
        tools.extend(_surface_tools(role_id, project_id))
        return tuple(tools)
    return _prose_tools(role_id, project_id=project_id)


def session_invoke_fn(role_id: str, run_id: str, checkpointer, project_id: str | None = None):
    """The stateful production seam: a callable `(messages, *, schema)` that runs
    one turn of `role_id` on its own per-run session, resuming from its checkpoint.

    `role_id` also selects the prompt, the thread identity and the compaction
    middleware, so a proposer cannot be built with another proposer's prompt. The
    returned callable keeps the exact `(messages, *, schema)` shape the old
    per-module `stateful_invoke_fn`s returned, so every proposer body and its
    contract tier are unchanged.

    Two cross-call invariants ride this ONE seam:

    - **Constant request shape**: every turn binds the analysis `notes` tool, and a
      prose turn ALSO binds the role's structured tool via `tools=`, so the tool set
      never toggles between a role's reflection and extraction turns (the shape that
      defeated the provider prefix cache; ADR D26/D34).
    - **Per-batch memory**: the thread is `AnalysisSession(run, role, batch)` where
      `batch` is the innermost `proposer_batch` scope the body opened (the streamed
      chunk id) - or None (the `run:role` thread) when none is set.

    Structurally sync: the supervisor dispatches the proposers sequentially under
    `ANALYSER_PASS_SEMAPHORE`, so a turn never needs an async entry point."""
    from polymerhus.app.llm import compaction as C  # noqa: PLC0415
    from polymerhus.app.llm.session import stateful_turn  # noqa: PLC0415
    from polymerhus.app.llm.session_address import AnalysisSession  # noqa: PLC0415

    middleware = [C.build_role_compaction_middleware(role_id)]

    def invoke(messages: Sequence[BaseMessage], *, schema: Any = _NO_SCHEMA,
              system_prompt: str | None = None):
        # The caller's prompt wins (the pod-agent pattern: the call site owns its
        # skill), so a role whose prompt varies by mode still gets the right one.
        # Absent one, the role's OWN default prompt applies - a proposer therefore
        # can never be built with another proposer's prompt by accident.
        resolved_schema = (_role_default_schema(role_id)
                           if schema is _NO_SCHEMA else schema)
        # Constant shape: every turn binds the analysis `notes` tool, and a prose
        # turn ALSO binds the structured tool the structured turn gets through
        # `response_format`, so the tool set never toggles. Only a non-empty set is
        # forwarded, so the structured calls stay byte-identical to the pre-change
        # requests.
        tools = _turn_tools(
            role_id, project_id, structured_bound=resolved_schema is not None)
        address = AnalysisSession(run_id, role_id, batch=current_batch())
        kwargs: dict[str, Any] = {}
        if tools:
            kwargs["tools"] = tools
        return stateful_turn(role_id, address, messages,
                             checkpointer=checkpointer,
                             schema=resolved_schema,
                             system_prompt=system_prompt or _role_prompt(role_id),
                             middleware=middleware, extra_tags=[run_id],
                             usage_scope=project_id,
                             **kwargs)

    return invoke


def prepend_prompt(messages: Sequence[BaseMessage],
                   system_prompt: str | None) -> list[BaseMessage]:
    """The one-shot leg: head `messages` with `system_prompt` as a `SystemMessage`.

    Used by the legacy stateless seam a proposer falls back to when no `invoke_fn`
    is injected (the contract tier). It reproduces, in one message list, the
    position `create_agent` gives the prompt in the stateful leg, so the request
    the model sees does not depend on which leg is in play. No prompt (None or
    empty) returns the list unchanged - never a synthetic empty system message."""
    if not system_prompt:
        return list(messages)
    return [SystemMessage(content=system_prompt), *messages]
