"""The running-summary engine (#95 slice C, realising ADR D5 + D6).

The D5 summarisation half of the context-window manager: ONE atomic call per
compact pass - no split/multi-call summarisation (operator ruling) - using the
session role's own model via the injectable model factory. The output is
structured (the running-summary contract: the eight core concepts - OBJECTIVE,
WORKFLOW, ENVIRONMENT STATE, TASK STATUS, DEAD BRANCHES PROBED, DECISIONS WITH
RATIONALE, DISCOVERED ARTIFACTS, and RESUME POINT - so the agent resumes exactly
where it left off, goal intact). An OUTPUT-QUALITY GATE applies: a summary
missing its mandatory objective or resume point, or carrying unparseable list
fields, is a FAILED generation, retried under the single retry layer and counted
toward the consecutive-pass cap (D6; the cap itself is slice D's concern - this
module only exposes the three-way status).

The D6 failure taxonomy, on top of the existing surfaces:

- The single retry layer is reused: `invoke_with_escalating_timeout` (#73
  discipline - escalating budgets, raised attempts and None results retried,
  exhaustion fails closed to None).
- A window-cap 4xx (the request itself exceeding `max_input_tokens`) is
  TERMINAL for the pass - never retried with identical input. The terminal
  signal is classified inside the attempt and translated to a BaseException
  sentinel (`_TerminalWindowError`) so the retry wrapper (which catches
  `Exception`) lets it ESCAPE untouched, and `summarise` maps it to status
  "terminal" immediately.
- Transient failures (transport/timeout/None/weak output) retry per the
  schedule; exhaustion maps to status "failed", the caller's established
  fail-closed signal.

The `SummaryLedger` here is the ADR D5 per-thread in-memory ledger (updated_at,
turn_count, tokens_reclaimed, last_compacted_at, spans, over-budget flag) the
barrier and observability read; slice D drives it, this slice only supplies the
object and its shape.

Importing this module performs no I/O and requires no env var (CODING_STANDARD
section 6): langchain_core at module level is the allowed exception (session.py
precedent); the #73 retry wrapper resolves lazily inside `summarise`.
"""
from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass, field
from typing import Any, Literal

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# The ideal length band for a running summary, in tokens (operator-ruled). It is
# stated in the prompt as a TARGET, not a hard gate: the quality gate does not
# token-count - it rejects only a summary missing its mandatory objective or
# resume point, or carrying unparseable fields. 200-500 tokens is dense enough to
# carry all eight concepts yet small enough that compaction still reclaims room.
SUMMARY_TARGET_TOKENS = (200, 500)

# The terminal window-cap markers (D6), matched case-insensitively against the
# exception's name/message/code/body - a superset of the openai BadRequestError
# `code="context_length_exceeded"` and its message phrasing.
_TERMINAL_MARKERS = (
    "context_length_exceeded",
    "maximum context length",
    "context length",
)


class _TerminalWindowError(BaseException):
    """Sentinel for a window-cap failure (D6).

    Deliberately a BaseException, NOT an Exception: the #73 retry wrapper
    catches `except Exception` and would otherwise RETRY the identical input a
    window-cap always fails - the exact self-containing loop the operator
    flagged. Deriving from BaseException lets the sentinel escape the wrapper
    untouched so `summarise` maps it to status "terminal" immediately, having
    invoked the summariser exactly once."""

    def __init__(self, cause: BaseException) -> None:
        super().__init__(str(cause))
        self.cause = cause


@dataclass(frozen=True)
class TaskStatus:
    """TASK STATUS: the three-way progress split - what is done, in progress,
    and what remains to be done. Empty tuples are honest (nothing in that bucket)."""

    done: tuple[str, ...] = ()
    in_progress: tuple[str, ...] = ()
    remaining: tuple[str, ...] = ()


@dataclass(frozen=True)
class RunningSummary:
    """The running-summary value (ADR D5): the eight core concepts, immutable.

    `to_text()` renders the static template slice D persists as the synthetic
    message content - a fixed, labelled layout so the agent (and the next pass's
    summariser) always finds each concept in the same place."""

    objective: str = ""
    workflow: str = ""
    environment_state: str = ""
    task_status: TaskStatus = field(default_factory=TaskStatus)
    dead_branches: tuple[str, ...] = ()
    decisions: tuple[str, ...] = ()
    artifacts: tuple[str, ...] = ()
    resume_point: str = ""

    def to_text(self) -> str:
        ts = self.task_status
        lines: list[str] = ["[running summary]"]
        # Objective, Workflow, Environment State are free-form paragraphs
        # but the markdown template uses a header per concept so the next
        # pass (and the agent) always finds each concept in the same place.
        lines.extend(["## Objective", self.objective or "none", ""])
        lines.extend(["## Workflow", self.workflow or "none", ""])
        lines.extend(["## Environment State", self.environment_state or "none", ""])
        # Task Status is the three-way split - rendered as a markdown list
        # with sub-lists so each bucket stays addressable.
        lines.append("## Task Status")
        lines.append("- Done:")
        if ts.done:
            lines.extend(f"  - {item}" for item in ts.done)
        else:
            lines.append("  - none")
        lines.append("- In Progress:")
        if ts.in_progress:
            lines.extend(f"  - {item}" for item in ts.in_progress)
        else:
            lines.append("  - none")
        lines.append("- Remaining:")
        if ts.remaining:
            lines.extend(f"  - {item}" for item in ts.remaining)
        else:
            lines.append("  - none")
        lines.append("")
        # Dead branches are a generic list - very generic entries and
        # contained samples are both legitimate (never invent, never drop).
        lines.append("## Dead Branches Probed")
        if self.dead_branches:
            lines.extend(f"- {item}" for item in self.dead_branches)
        else:
            lines.append("- none")
        lines.append("")
        # PREVIOUS DECISIONS WITH RATIONALE and DISCOVERED CRUCIAL ARTIFACTS
        # are explicitly lists - each entry carries its rationale / identifier.
        lines.append("## Previous Decisions with Rationale")
        if self.decisions:
            lines.extend(f"- {item}" for item in self.decisions)
        else:
            lines.append("- none")
        lines.append("")
        lines.append("## Discovered Crucial Artifacts")
        if self.artifacts:
            lines.extend(f"- {item}" for item in self.artifacts)
        else:
            lines.append("- none")
        lines.append("")
        lines.extend(["## Resume Point", self.resume_point or "none"])
        return "\n".join(lines)


class TaskStatusUpdate(BaseModel):
    """TASK STATUS: the structured-output three-way progress split."""

    done: list[str] = Field(default_factory=list)
    in_progress: list[str] = Field(default_factory=list)
    remaining: list[str] = Field(default_factory=list)


class SummaryUpdate(BaseModel):
    """The structured-output schema for the atomic call - exactly the eight core
    concepts, no others (D5). `objective` and `resume_point` are REQUIRED (no
    default): a summary without them is a failed generation."""

    objective: str
    workflow: str = ""
    environment_state: str = ""
    task_status: TaskStatusUpdate = Field(default_factory=TaskStatusUpdate)
    dead_branches: list[str] = Field(default_factory=list)
    decisions: list[str] = Field(default_factory=list)
    artifacts: list[str] = Field(default_factory=list)
    resume_point: str


@dataclass(frozen=True)
class SummaryOutcome:
    """The three-way pass outcome (D5/D6): `ok` with the summary, `failed` on
    retry exhaustion / quality-gate exhaustion, `terminal` on a window-cap."""

    summary: RunningSummary | None
    status: Literal["ok", "failed", "terminal"]


# --- message composition (the atomic call's input) ---------------------------

_SYSTEM_PROMPT = """You are the running-summary engine for a long-horizon agent session (#95 context compaction).

Your job is to condense the session material into a single running summary from which the agent can resume its work exactly where it left off, without losing the goal it is executing toward.

## Intention-keeping (highest priority)

Preserve the agent's OBJECTIVE - the goal the execution is driving toward. If the objective is stated in the session material, carry it forward essentially verbatim; otherwise restate it as precisely as the material allows. The objective is the reason the session exists and must survive every compaction unchanged.

## Core concepts (fill EXACTLY these, no others)

- OBJECTIVE: the goal the agent is executing toward.
- WORKFLOW: how the agent is going about it - the method, stages, or loop it follows.
- ENVIRONMENT STATE: the relevant current state of the tools, resources, targets, and context the agent depends on.
- TASK STATUS: what is done, in progress, and what remains to be done.
- DEAD BRANCHES PROBED: errors, failures, and falsified hypotheses already eliminated - so they are not re-probed.
- PREVIOUS DECISIONS WITH RATIONALE: each decision taken, with the reason it was taken.
- DISCOVERED CRUCIAL ARTIFACTS: important tool-call outputs, each with its specific identifier (file/record/id) - list none when there are none.
- SPECIFIC RESUME POINT: the exact next action the agent should take.

## Output template (markdown - fill EXACTLY this structure, no others)

The structured output you produce is rendered into the trail as markdown
with headers and sub-lists - the agent (and the next pass's summariser)
finds each concept under the same header. Use this template verbatim:

[running summary]
## Objective
<objective paragraph>

## Workflow
<workflow paragraph>

## Environment State
<environment state paragraph>

## Task Status
- Done:
  - <done item>
- In Progress:
  - <in-progress item>
- Remaining:
  - <remaining item>

## Dead Branches Probed
- <dead branch>  (generic entries allowed - e.g. "probe X returned 404" - keep verbatim)

## Previous Decisions with Rationale
- <decision> - <rationale>

## Discovered Crucial Artifacts
- <artifact with its specific identifier - file/record/id>

## Resume Point
<exact next action>

Lists under each paragraph may be very generic and may contain sample
entries - preserve them as lists. PREVIOUS DECISIONS WITH RATIONALE and
DISCOVERED CRUCIAL ARTIFACTS are always lists - never prose paragraphs.

## Length

Aim for 200-500 tokens total. Be dense: preserve meaning, not verbosity.

## Rules

Never invent material that is absent from the provided spans. Condense the prior running summary TOGETHER with the new session material; the summary accumulates across passes. Every field must be grounded in the spans or the prior summary.

Tool results older than the retention window are folded into this summary instead of staying in the trail (#187): capture each under DISCOVERED CRUCIAL ARTIFACTS with its specific identifier (file/record/id) when it is load-bearing, so the condensed artifact is not lost."""


def _text_of(content: Any) -> str:
    """Render a message's content to a plain string, tolerating the content-block
    shapes langchain carries (str, block dicts, block objects) - fail-open."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                for key in ("text", "reasoning"):
                    value = block.get(key)
                    if isinstance(value, str):
                        parts.append(value)
            else:
                text = getattr(block, "text", None)
                if isinstance(text, str):
                    parts.append(text)
        return "\n".join(parts)
    return str(content)


def _span_text(span: Any) -> str:
    content = getattr(span, "content", None)
    if content is None:
        return str(span)
    try:
        return _text_of(content)
    except Exception:  # noqa: BLE001 - a bad span degrades, never raises
        logger.debug("span text render failed; falling back to repr", exc_info=True)
        return str(span)


def _prior_text(existing: RunningSummary | None) -> str:
    if existing is None:
        return "none yet"
    try:
        text = existing.to_text()
    except Exception:  # noqa: BLE001 - a malformed prior degrades, never raises
        logger.debug("prior running summary render failed; falling back to repr",
                     exc_info=True)
        text = str(existing)
    return text


def build_summary_messages(existing: RunningSummary | None, spans: list) -> list:
    """Compose the ONE atomic call's messages (D5).

    A SYSTEM prompt states the job and presents the output template - exactly the
    four fields; a USER message carries the prior running summary (honestly
    "none yet" on the first pass) plus the spans being condensed. The composite
    input of this call is bounded by the material being compacted (D6)."""
    prior = _prior_text(existing)
    rendered = "\n\n".join(_span_text(span) for span in spans) if spans else ""
    user = HumanMessage(
        content=(
            f"Prior running summary:\n{prior}\n\n"
            f"Session material to condense:\n{rendered}"
        )
    )
    return [SystemMessage(content=_SYSTEM_PROMPT), user]


# --- the output-quality gate (D5) --------------------------------------------

def is_quality_summary(update: Any) -> bool:
    """The D5 OUTPUT-QUALITY GATE.

    `objective` and `resume_point` must be non-empty strings (the two concepts a
    resume cannot do without); every list field - and the three task-status
    sub-fields - must be LISTs (empty lists are accepted - they are lists, not
    None). Anything else is a FAILED generation, never a raise (fail-open). The
    200-500 token band is a prompt TARGET, not a hard gate - this gate never
    token-counts."""
    if not isinstance(update, SummaryUpdate):
        return False
    if not isinstance(update.objective, str) or not update.objective.strip():
        return False
    if not isinstance(update.resume_point, str) or not update.resume_point.strip():
        return False
    for name in ("dead_branches", "decisions", "artifacts"):
        if not isinstance(getattr(update, name, None), list):
            return False
    ts = update.task_status
    if not isinstance(ts, TaskStatusUpdate):
        return False
    for name in ("done", "in_progress", "remaining"):
        if not isinstance(getattr(ts, name, None), list):
            return False
    return True


# --- terminal classification (D6) --------------------------------------------

def classify_terminal(exc: Any) -> bool:
    """Detect a provider context-length / window-cap error (D6).

    Inspects the exception type name, message, `code`, and body, case-insensitively
    scanning the three ratified markers; the openai `BadRequestError` shape
    (`code` / `message` / `body["error"]`) is covered by each scan surface.
    Fail-open: anything unrecognised - or unclassifiable - is NOT terminal, never
    a raise."""
    try:
        if exc is None:
            return False
        haystack: list[str] = []
        type_name = type(exc).__name__
        if type_name:
            haystack.append(type_name)
        message = str(exc)
        if message:
            haystack.append(message)
        for attr in ("code", "message"):
            value = getattr(exc, attr, None)
            if isinstance(value, str):
                haystack.append(value)
        body = getattr(exc, "body", None)
        if isinstance(body, dict):
            error = body.get("error")
            if isinstance(error, dict):
                for key in ("message", "code", "type"):
                    value = error.get(key)
                    if isinstance(value, str):
                        haystack.append(value)
        exploded = " ".join(haystack).lower()
        return any(marker in exploded for marker in _TERMINAL_MARKERS)
    except Exception:  # noqa: BLE001 - classification is fail-open by contract
        return False


# --- the atomic call ----------------------------------------------------------

def _to_running_summary(update: SummaryUpdate) -> RunningSummary:
    return RunningSummary(
        objective=update.objective,
        workflow=update.workflow,
        environment_state=update.environment_state,
        task_status=TaskStatus(
            done=tuple(update.task_status.done),
            in_progress=tuple(update.task_status.in_progress),
            remaining=tuple(update.task_status.remaining),
        ),
        dead_branches=tuple(update.dead_branches),
        decisions=tuple(update.decisions),
        artifacts=tuple(update.artifacts),
        resume_point=update.resume_point,
    )


def summarise(
    summariser,
    *,
    existing: RunningSummary | None,
    spans: list,
) -> SummaryOutcome:
    """Run the ONE atomic summarisation call under the #73 retry layer (D5/D6).

    `summariser` is injectable: `Callable[[list, float], SummaryUpdate | None]` -
    (messages, read_timeout_s) - the production caller builds it from the session
    role's model with structured output; the unit tier injects a fake. The
    messages are composed, then the call runs through
    `invoke_with_escalating_timeout`: a window-cap error (D6) is classified and
    translated to the terminal sentinel OUTSIDE the retry axis (invoked exactly
    once, status "terminal"); a None result or a quality-gate failure is
    translated to None so the schedule retries it; exhaustion returns status
    "failed" with no summary; a quality pass returns status "ok" with the
    `RunningSummary`. The consecutive-pass cap (3) is slice D's concern, never
    this function."""
    from polymerhus.app.llm.providers import invoke_with_escalating_timeout

    messages = build_summary_messages(existing, spans)

    def _attempt(budget: float):
        try:
            result = summariser(messages, budget)
        except Exception as exc:  # noqa: BLE001 - classify, then retry or terminate
            if classify_terminal(exc):
                raise _TerminalWindowError(exc) from None
            raise
        if result is None:
            return None
        if not is_quality_summary(result):
            logger.warning(
                "running-summary pass returned a weak summary (%r); "
                "retrying under the escalating schedule", getattr(result, "objective", None))
            return None
        return result

    try:
        result = invoke_with_escalating_timeout(_attempt)
    except _TerminalWindowError as exc:  # escaped the retry wrapper by construction
        logger.warning(
            "running-summary pass is TERMINAL (window-cap): %s - never retried "
            "with identical input (D6)", exc.cause)
        return SummaryOutcome(summary=None, status="terminal")
    if result is None:
        return SummaryOutcome(summary=None, status="failed")
    return SummaryOutcome(summary=_to_running_summary(result), status="ok")


def build_summariser(role_id: str):
    """Build the role's running-summary summariser (D5): a single-shot structured
    `SummaryUpdate` call on the role's OWN model, budgeted per attempt under the
    #73 escalating read budget - exactly `invoke_role`'s shape (a FRESH client per
    attempt, `read_timeout=budget`, `max_retries=0`), so the pass and the role's
    turns share one retry discipline. The provider/model resolves lazily inside the
    summariser (at pass time, not build time), so building the summariser never
    reads env; a missing config raises at pass time and `summarise` degrades the
    pass. Returns the `(messages, read_timeout_s) -> SummaryUpdate | None`
    contract `summarise` invokes."""
    def summariser(messages, read_timeout_s: float) -> "SummaryUpdate | None":
        from polymerhus.app.llm.providers import (
            build_chat_model,
            resolve_role,
            thinking_for,
        )

        provider, model = resolve_role(role_id)
        llm = build_chat_model(provider, model, temperature=0,
                               read_timeout=read_timeout_s, max_retries=0,
                               thinking=thinking_for(role_id))
        result = llm.with_structured_output(
            SummaryUpdate, method="function_calling").invoke(messages)
        return result if isinstance(result, SummaryUpdate) else None

    return summariser


# --- the per-thread summary ledger (D5/D6) -------------------------------------

@dataclass
class SummaryLedgerEntry:
    """One session thread's compaction record (ADR D5) - the barrier's and
    observability's input. Exactly the six ratified fields."""

    updated_at: dt.datetime = field(default_factory=lambda: dt.datetime.now(dt.timezone.utc))
    turn_count: int = 1
    reclaimed_tokens: int = 0
    last_compacted_at: dt.datetime | None = None
    spans: int = 0
    over_budget: bool = False


class SummaryLedger:
    """The per-thread summary ledger keyed by the session thread id.

    Slice C only supplies the object and its shape; slice D drives it - the
    barrier reads `entry()` (never advancing past an over-budget thread without
    a pending pass), the consecutive-pass cap counts locally off `turn_count`
    and `spans` (D6)."""

    def __init__(self) -> None:
        self._entries: dict[str, SummaryLedgerEntry] = {}

    def record(self, thread_id: str, **fields) -> SummaryLedgerEntry:
        entry = SummaryLedgerEntry(**fields)
        self._entries[thread_id] = entry
        return entry

    def entry(self, thread_id: str) -> SummaryLedgerEntry | None:
        return self._entries.get(thread_id)