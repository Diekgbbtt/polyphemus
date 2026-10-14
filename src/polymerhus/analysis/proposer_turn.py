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
import logging
from typing import Any, Iterator, Sequence

from langchain_core.messages import BaseMessage, SystemMessage

logger = logging.getLogger(__name__)

# Distinguishes "the caller passed no schema" (use the role's own default) from
# "the caller passed schema=None" (a deliberate prose turn). The analysis role's
# schema is part of its output contract: the assigner is permanently structured,
# while the reflection-driven proposers alternate prose and structured turns.
_NO_SCHEMA = object()

# The per-streamed-chunk boundary signal (the per-batch discriminator). A proposer
# body opens it around its invoke chain, so the seam sees where ONE chunk's turns
# end and the next begins. It is a ContextVar, the repo's established scoped-ambient
# pattern (`conversation_scope`, `module_context`), so the invoke contract
# `(messages, *, schema, system_prompt)` is unchanged. The scope does NOT rename the
# thread: every chunk runs on the SAME `run:role` session, which the seam resets at
# each new batch (the reset-per-chunk lifecycle), keeping the stable identity the
# provider prefix cache and the observability/runtime contract key on.
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

        return _system_prompt("create")
    if role_id == "mechanism_typist":
        from polymerhus.analysis.mechanism_typist import _load_skill

        return _load_skill()
    if role_id == "data_modeller":
        from polymerhus.analysis.data_modeller import _system_prompt

        return _system_prompt()
    raise KeyError(f"no registered role prompt for {role_id!r}; the analysis "
                   f"proposers are assigner, mechanism_typist, data_modeller")


def _role_default_schema(role_id: str) -> Any:
    """The role's default structured-output schema, or None for a role that takes
    prose turns. Part of the role's output contract, not a per-call decision."""
    if role_id == "assigner":
        from polymerhus.analysis.analyser_types import L1DeltaBatch

        return L1DeltaBatch
    return None


def _role_structured_schema(role_id: str) -> Any:
    """The schema a role's STRUCTURED turns use, or None for a role with no structured
    contract. Distinct from `_role_default_schema`, which is None for the
    reflection-driven proposers: their prose turns are deliberate, but they still
    share this one structured tool so the request shape never toggles."""
    if role_id in ("assigner", "mechanism_typist", "data_modeller"):
        from polymerhus.analysis.analyser_types import L1DeltaBatch

        return L1DeltaBatch
    return None


def _surface_tools(role_id: str, project_id: str | None) -> tuple:
    """D-A2 (extended past assigner-only): the adjacent-surface read/probe tools.

    The assigner's turn binds the read-only `graph_view` plus the HTTP-history
    pair, so its bounded BaseURL-neighbourhood phase has a read seam. The
    mechanism-typist's turn binds the same pair PLUS the bounded `exec` term, so
    its ORIENT / VERIFY phases can witness a mechanism in the target's real
    response. The data-modeller's turn binds none - adjacent-surface reading and
    probing are not its ownership. Fail-open: an unbuildable surface, or no
    project scope, binds nothing (the session always starts)."""
    if role_id not in ("assigner", "mechanism_typist") or not project_id:
        return ()
    try:
        from polymerhus.analysis.graph_tools import build_surface_tools

        return build_surface_tools(
            role_id, project_id=project_id, with_http=True,
            with_exec=(role_id == "mechanism_typist"),
        )
    except Exception:  # noqa: BLE001 - fail-open: no surface tools bound
        logger.warning("proposer_turn: surface tools unbuildable; binding none",
                       exc_info=True)
        return ()


def _prose_tools(role_id: str, *, tools_bound: bool = False) -> tuple:
    """The role's structured tool, bound on a PROSE turn so the tool set is constant
    across the role's calls (the cache-shape rule).

    The structured turn supplies the SAME tool through `response_format`; binding it
    again there would duplicate it, so only a prose turn (`schema is None`) gets it
    here. `tools_bound` is the negotiation axis the STRUCTURED turn will read (it is
    True whenever this role's turn binds a surface tool set), so the tool this prose
    turn must carry is the one the structured turn's `response_format` will produce:
    on the tool axis that is always the `ToolStrategy` structured tool. The tool is
    the exact tool the ToolStrategy path builds (the A6 voluntary rung); a no-tools
    role on a `json_schema` profile carries no tool on either turn, so the set stays
    constant. The tool is made inert - the reflection prompt forbids a structured
    emission, and a stray call then costs one benign tool message instead of a
    ToolNode error. Fail-open: an unbuildable shape binds nothing (the session
    always starts)."""
    schema = _role_structured_schema(role_id)
    if schema is None:
        return ()
    try:
        from langchain.agents.structured_output import ToolStrategy
        from langchain_core.tools import StructuredTool

        from polymerhus.app.llm.session import structured_response_format

        fmt = structured_response_format(role_id, schema, tools_bound=tools_bound)
        if not isinstance(fmt, ToolStrategy):
            return ()
        spec = fmt.schema_specs[0]
        return (StructuredTool(
            name=spec.name,
            description=spec.description,
            args_schema=spec.json_schema,
            func=lambda **_: "structured output is only produced on the extraction turn",
        ),)
    except Exception:  # noqa: BLE001 - fail-open: an unbuildable tool binds nothing
        return ()


def session_invoke_fn(role_id: str, run_id: str, checkpointer, project_id: str | None = None):
    """The stateful production seam: a callable `(messages, *, schema)` that runs
    one turn of `role_id` on its own per-run session, resuming from its checkpoint.

    `role_id` also selects the prompt, the thread identity and the compaction
    middleware, so a proposer cannot be built with another proposer's prompt. The
    returned callable keeps the exact `(messages, *, schema)` shape the old
    per-module `stateful_invoke_fn`s returned, so every proposer body and its
    contract tier are unchanged.

    Two cross-call invariants ride this ONE seam:

    - **Constant request shape**: a prose turn still binds the role's structured tool
      via `tools=`, so the tool set never toggles between a role's reflection and
      extraction turns (the shape that defeated the provider prefix cache). The
      Assigner and mechanism-typist turns additionally bind their adjacent-surface
      read tools (D-A2) on EVERY turn, the typist's bounded `exec` included; the
      assigner is permanently structured, and the typist's reflection turn carries
      the same surface set as its structured turns, so neither set toggles.
    - **Per-chunk reset on one session**: the thread is always
      `AnalysisSession(run_id, role_id)` - the documented `run:role` the
      observability/runtime contract expects. The first turn that arrives under a
      NEW `proposer_batch` scope resets that session to empty (fail-open), so the
      chunk starts from the initial system prompt + its fixed human messages
      instead of resuming the previous chunk's trail, while the turns WITHIN one
      chunk still share the session (the reflection is the extraction's context).

    Structurally sync: the supervisor dispatches the proposers sequentially under
    `ANALYSER_PASS_SEMAPHORE`, so a turn never needs an async entry point."""
    from polymerhus.app.llm import compaction as C  # noqa: PLC0415
    from polymerhus.app.llm.session import reset_session_thread, stateful_turn  # noqa: PLC0415
    from polymerhus.app.llm.session_address import AnalysisSession  # noqa: PLC0415

    middleware = [C.build_role_compaction_middleware(role_id)]
    # The chunk-boundary reset cell: the last batch this invoke saw. A turn
    # arriving under a NEW non-None batch resets the ONE session first, so the
    # chunk starts from the initial system prompt + its fixed human messages.
    # Unscoped turns never reset (the back-compat callers keep their trail).
    last_batch: list[str | None] = [None]

    def invoke(messages: Sequence[BaseMessage], *, schema: Any = _NO_SCHEMA,
               system_prompt: str | None = None):
        # The caller's prompt wins (the pod-agent pattern: the call site owns its
        # skill), so a role whose prompt varies by mode still gets the right one.
        # Absent one, the role's OWN default prompt applies - a proposer therefore
        # can never be built with another proposer's prompt by accident.
        resolved_schema = (_role_default_schema(role_id)
                           if schema is _NO_SCHEMA else schema)
        # Constant shape: a prose turn binds the role's structured tool so the tool
        # set never toggles; the structured turn supplies it via `response_format`.
        # The role's adjacent-surface read/probe tools (D-A2) ride EVERY turn - the
        # prose reflection turn included - so the reflection can call them (its tool
        # calls are the evidence phase) and the P->S request shape still shares one
        # tool set. `bool(surface)` is the negotiation axis the structured turn will
        # read, so the prose turn carries exactly the structured tool that turn's
        # `response_format` will produce. Only a non-empty set is forwarded, so a
        # role with no surface tools stays byte-identical to the pre-change requests.
        surface = _surface_tools(role_id, project_id)
        tools = (surface if resolved_schema is not None
                 else surface + _prose_tools(role_id, tools_bound=bool(surface)))
        address = AnalysisSession(run_id, role_id)
        batch = current_batch()
        if batch is not None and batch != last_batch[0]:
            # A new chunk on the one session: reset it to empty first, so this
            # chunk's turns start from the initial system prompt + the fixed
            # human messages. BOTH halves are reset, fail-open: the checkpointer
            # trail (`reset_session_thread`) AND the compaction manager's
            # per-thread state (its running-summary pointer and ledger - without
            # this the new chunk would inherit the old chunk's summary and its
            # occupancy). A refused reset keeps the trail.
            reset_session_thread(checkpointer, address)
            for mw in middleware:
                manager = getattr(mw, "manager", None)
                reset = getattr(manager, "reset_thread", None)
                if callable(reset):
                    try:
                        reset(address.thread_id)
                    except Exception:  # noqa: BLE001 - fail-open, keeping state
                        logger.warning(
                            "reset of compaction state for %s failed "
                            "(fail-open, keeping state)", address.thread_id)
        last_batch[0] = batch
        kwargs: dict[str, Any] = {}
        if tools:
            kwargs["tools"] = tools
        return stateful_turn(role_id, address, messages,
                             checkpointer=checkpointer,
                             schema=resolved_schema,
                             system_prompt=system_prompt or _role_prompt(role_id),
                             middleware=middleware, extra_tags=[run_id],
                             usage_scope=project_id, **kwargs)

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
