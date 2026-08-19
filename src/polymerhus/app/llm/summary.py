"""The running-summary engine (#95 slice C, realising ADR D5 + D6).

The D5 summarisation half of the context-window manager: ONE atomic call per
compact pass - no split/multi-call summarisation (operator ruling) - using the
session role's own model via the injectable model factory. The output is
structured (the running-summary contract: the narrative summary text preserving
decisions, evidence pointers, and open threads). An OUTPUT-QUALITY GATE applies:
an empty, unparseable, or degenerately short summary is a FAILED generation,
retried under the single retry layer and counted toward the consecutive-pass cap
(D6; the cap itself is slice D's concern - this module only exposes the
three-way status).

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

# The D5 output-quality floor: the narrative must be a non-empty string of at
# least this many characters (after stripping). 40 characters is roughly one
# substantive sentence - below it a summary cannot carry decisions, evidence
# pointers, and open threads, so it is a FAILED generation, never a silent pass.
SUMMARY_MIN_FLOOR_CHARS = 40

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
class RunningSummary:
    """The running-summary value: the narrative condensation plus the preserved
    decisions, evidence pointers, and open threads (ADR D5).

    `to_text()` renders the single compact narrative string the synthetic
    message content slice D persists into the trail."""

    summary_text: str
    decisions: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    open_threads: tuple[str, ...] = ()

    def to_text(self) -> str:
        parts = ["[running summary]", self.summary_text]
        if self.decisions:
            parts.append("DECISIONS: " + "; ".join(self.decisions))
        if self.evidence_refs:
            parts.append("EVIDENCE REFS: " + "; ".join(self.evidence_refs))
        if self.open_threads:
            parts.append("OPEN THREADS: " + "; ".join(self.open_threads))
        return "\n".join(parts)


class SummaryUpdate(BaseModel):
    """The structured-output schema for the atomic call - exactly the four
    running-summary fields, no invented content (D5)."""

    summary_text: str
    decisions: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    open_threads: list[str] = Field(default_factory=list)


@dataclass(frozen=True)
class SummaryOutcome:
    """The three-way pass outcome (D5/D6): `ok` with the summary, `failed` on
    retry exhaustion / quality-gate exhaustion, `terminal` on a window-cap."""

    summary: RunningSummary | None
    status: Literal["ok", "failed", "terminal"]


# --- message composition (the atomic call's input) ---------------------------

_SYSTEM_PROMPT = """You are the running-summary engine for a long-horizon agent session (#95 context compaction).
You condense reasoning and content into a single running summary that preserves decisions, evidence pointers, and open threads.
Produce structured output filling EXACTLY this template - the four fields, no others:

- summary_text: the narrative condensation - one non-empty string of at least 40 characters
- decisions: a list of strings - each a decision taken, with its reason
- evidence_refs: a list of strings - each a retained evidence pointer
- open_threads: a list of strings - each an unresolved thread that must remain actionable

Condense the prior running summary TOGETHER with the new session material; the running summary accumulates across passes.
Never invent material that is absent from the provided spans."""


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

    `summary_text` must be a non-empty string of at least the floor; the three
    list fields must be LISTs (empty lists are accepted - they are lists, not
    None). Empty, unparseable, or degenerately short -> False (a FAILED
    generation), never a raise (fail-open)."""
    if not isinstance(update, SummaryUpdate):
        return False
    text = update.summary_text
    if not isinstance(text, str) or len(text.strip()) < SUMMARY_MIN_FLOOR_CHARS:
        return False
    for name in ("decisions", "evidence_refs", "open_threads"):
        if not isinstance(getattr(update, name, None), list):
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
        summary_text=update.summary_text,
        decisions=tuple(update.decisions),
        evidence_refs=tuple(update.evidence_refs),
        open_threads=tuple(update.open_threads),
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
                "retrying under the escalating schedule", getattr(result, "summary_text", None))
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