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

from typing import Any, Sequence

from langchain_core.messages import BaseMessage, SystemMessage

# Distinguishes "the caller passed no schema" (use the role's own default) from
# "the caller passed schema=None" (a deliberate prose turn). The analysis role's
# schema is part of its output contract: the assigner is permanently structured,
# while the reflection-driven proposers alternate prose and structured turns.
_NO_SCHEMA = object()


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


def session_invoke_fn(role_id: str, run_id: str, checkpointer, project_id: str | None = None):
    """The stateful production seam: a callable `(messages, *, schema)` that runs
    one turn of `role_id` on its own per-run session, resuming from its checkpoint.

    `role_id` also selects the prompt, the thread identity and the compaction
    middleware, so a proposer cannot be built with another proposer's prompt. The
    returned callable keeps the exact `(messages, *, schema)` shape the old
    per-module `stateful_invoke_fn`s returned, so every proposer body and its
    contract tier are unchanged.

    Structurally sync: the supervisor dispatches the proposers sequentially under
    `ANALYSER_PASS_SEMAPHORE`, so a turn never needs an async entry point."""
    from polymerhus.app.llm import compaction as C  # noqa: PLC0415
    from polymerhus.app.llm.session import stateful_turn  # noqa: PLC0415
    from polymerhus.app.llm.session_address import AnalysisSession  # noqa: PLC0415

    address = AnalysisSession(run_id, role_id)
    middleware = [C.build_role_compaction_middleware(role_id)]

    def invoke(messages: Sequence[BaseMessage], *, schema: Any = _NO_SCHEMA,
              system_prompt: str | None = None):
        # The caller's prompt wins (the pod-agent pattern: the call site owns its
        # skill), so a role whose prompt varies by mode still gets the right one.
        # Absent one, the role's OWN default prompt applies - a proposer therefore
        # can never be built with another proposer's prompt by accident.
        return stateful_turn(role_id, address, messages,
                             checkpointer=checkpointer,
                             schema=(_role_default_schema(role_id)
                                     if schema is _NO_SCHEMA else schema),
                             system_prompt=system_prompt or _role_prompt(role_id),
                             middleware=middleware, extra_tags=[run_id],
                             usage_scope=project_id)

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
