"""The context-window compaction manager (#95) - the shared, adaptive window keeper.

Long-horizon session agents accumulate reasoning turns and tool outputs until they
exceed the model's context window. This module owns the compaction logic: it
    measures a session trail's occupancy from the provider's REAL per-step usage,
    flags the session as over budget once occupancy crosses a configurable threshold
    of the model's real window (read from the gateway capability surface, never a
    hardcoded table), and - behind the spawn/barrier of later slices - runs the
    out-of-band compact pass (summarise reasoning, offload tool bodies, preserve
    the replay tail) that STAGES its result rather than writing the checkpointer
    (D1). It augments the SESSION path only (`run_session_turn` /
    `arun_session_turn` via the `middleware` seam); the one-shot path is untouched.

Slice A (the measurement half) is the per-thread usage ledger and the threshold
trigger, wired as an `AgentMiddleware.after_model` hook that updates the ledger
and NEVER spawns compaction. Slice D (this module's second surface) is the pure
compact pass - `compact_pass` - composing the tool-output offload (slice B) and
the running summary (slice C) into ONE staged result honouring the D7
replay-collision precedence. The spawn, the barrier, and the wiring land in
later slices.

The load-bearing principles (ADR `docs/design/context-compaction-95-decisions.md`):

- **Window (D2)**: `resolve_capability(provider, model).context_limit` (gateway ->
  env -> 150k conservative default), resolved once at client construction and held;
  the bound is `threshold * context_limit`; `output_limit` is not load-bearing.
- **Threshold (D2)**: a builder parameter reading the `LLM_COMPACTION_THRESHOLD`
  env override, default 0.90; an unusable value fails fast (LLMConfigError).
- **Occupancy (D3)**: the provider's own `usage_metadata`, per model step:
  `input_tokens + input_token_details.cache_read` (input alone under-counts once
  caching engages), plus what migrates into the next prompt - the step's output
  tokens (reasoning sits on the output side, a subset, recorded not double-counted)
  and any trailing tool payload (no usage record, but occupies the next prompt).
  `count_tokens_approximately` is the fail-open fallback when usage is absent.
- **Cache-track is observability, never a gate (D11 item 3)**: cache-read is
  recorded on the ledger, never load-bearing on its own.
- **Replay-collision precedence (D7)**: a reasoning-capable profile reserves a
  token-bounded byte-identical tail (default 30k, measured from the trail's end)
  that compaction neither summarises nor offloads; profile false/None means all
  reasoning-bearing content is summarisable - there is nothing byte-identical
  to preserve.

Importing this module performs no I/O and requires no env var (CODING_STANDARD
section 6). The `AgentMiddleware` base class is imported lazily inside the factory,
never at import (the `actor.py` precedent).
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Literal

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    SystemMessage,
    ToolMessage,
)

from polymerhus.app.llm.summary import RunningSummary, summarise
from polymerhus.app.llm.tool_output import ToolOutputStore, offload_tool_message

logger = logging.getLogger(__name__)

# --- D2: the threshold + window surface --------------------------------------

# The threshold env override (D2); beats the 0.90 default only when a builder
# parameter is not given. Unusable values fail fast (LLMConfigError) - a config
# lie, mirroring the `LLM_ROLE_MODEL_CONTEXT_LIMIT` precedent (capability.py).
COMPACTION_THRESHOLD_ENV = "LLM_COMPACTION_THRESHOLD"
DEFAULT_THRESHOLD = 0.90

# The conservative window default (D6 of the gateway ADR, imported from the
# capability reader - the single source, never re-declared here).
from polymerhus.app.llm.capability import (  # noqa: E402
    CapabilityProfile,
    DEFAULT_CONTEXT_LIMIT,
)


@dataclass(frozen=True)
class CompactionWindow:
    """The resolved window + threshold a compaction client is bound to (D2).

    Resolved once at client construction and held; `budget` is the input bound
    `threshold * context_limit` a session's occupancy is compared against."""

    context_limit: int
    threshold: float

    @property
    def budget(self) -> int:
        return int(self.context_limit * self.threshold)


def _threshold_from_env() -> float | None:
    raw = os.environ.get(COMPACTION_THRESHOLD_ENV)
    if raw is None or raw.strip() == "":
        return None
    try:
        value = float(raw.strip())
    except ValueError:
        raise _threshold_error(raw) from None
    if not (0.0 < value <= 1.0):
        raise _threshold_error(raw)
    return value


def _threshold_error(raw) -> Exception:
    from polymerhus.app.llm.providers import LLMConfigError

    return LLMConfigError(
        f"{COMPACTION_THRESHOLD_ENV} must be a number in (0, 1] "
        f"(got {raw!r})"
    )


def resolve_window(
    role_id: str | None,
    *,
    threshold: float | None = None,
) -> CompactionWindow:
    """Resolve the compaction window for a role - resolve-and-hold (D2).

    The context limit comes from the capability reader (`resolve_capability`),
    resolved once here and held by the client; ANY failure (unset role env vars,
    a degraded reader) falls back to the conservative 150k default, logged - the
    session must always start. The threshold is the builder param, else the env
    override, else the 0.90 default; an unusable env value fails fast."""
    limit = DEFAULT_CONTEXT_LIMIT
    if role_id is not None:
        try:
            from polymerhus.app.llm.capability import resolve_capability
            from polymerhus.app.llm.providers import resolve_role

            provider, model = resolve_role(role_id)
            limit = resolve_capability(provider, model).context_limit or DEFAULT_CONTEXT_LIMIT
        except Exception as exc:  # noqa: BLE001 - fail-open, never into construction
            logger.warning(
                "compaction window resolution failed for role %r: %s; "
                "using the conservative default (%d)",
                role_id, exc, DEFAULT_CONTEXT_LIMIT)
            limit = DEFAULT_CONTEXT_LIMIT
    threshold = threshold if threshold is not None else _threshold_from_env() or DEFAULT_THRESHOLD
    return CompactionWindow(context_limit=limit, threshold=threshold)


# --- D3: occupancy accounting -------------------------------------------------

@dataclass(frozen=True)
class UsageSnapshot:
    """One model step's occupancy, read from its real usage metadata (D3).

    `base_input` = input_tokens + cache_read (what the model actually saw);
    `migrating_output` = the response's output tokens (what moves into the next
    prompt); `reasoning_tokens` is a SUBSET of output - recorded for observability,
    never added again. `occupancy` is the step's occupied window."""

    base_input: int
    cache_read: int
    migrating_output: int
    reasoning_tokens: int | None = None

    @property
    def occupancy(self) -> int:
        return self.base_input + self.migrating_output


def occupancy_from_message(message: BaseMessage) -> UsageSnapshot | None:
    """The per-step occupancy from one assistant message's real usage; None when
    the message carries no usage metadata (the ledger then falls back to
    approximate counting - never a guessed zero)."""
    if not isinstance(message, AIMessage):
        return None
    usage = getattr(message, "usage_metadata", None)
    if not isinstance(usage, dict):
        return None
    input_tokens = usage.get("input_tokens")
    if not isinstance(input_tokens, int):
        return None
    details = usage.get("input_token_details")
    cache_read = details.get("cache_read") if isinstance(details, dict) else None
    cache_read = cache_read if isinstance(cache_read, int) else 0
    output_tokens = usage.get("output_tokens")
    output_tokens = output_tokens if isinstance(output_tokens, int) else 0
    odt = usage.get("output_token_details")
    reasoning = odt.get("reasoning_tokens") if isinstance(odt, dict) else None
    reasoning = reasoning if isinstance(reasoning, int) else None
    return UsageSnapshot(
        base_input=input_tokens + cache_read,
        cache_read=cache_read,
        migrating_output=output_tokens,
        reasoning_tokens=reasoning,
    )


def approx_tokens(messages: list[BaseMessage]) -> int:
    """The approximate token count of a message slice - the fail-open fallback when
    no real usage is available. Resolved lazily so the module stays import-light."""
    from langchain_core.messages.utils import count_tokens_approximately

    return count_tokens_approximately(list(messages))


def compute_occupancy(messages: list[BaseMessage]) -> tuple[int, bool]:
    """The occupancy of a trail: the last usage-bearing step's real accounting, plus
    any trailing tool payloads no later step has yet consumed (approximate-counted),
    else an approximate count of the whole trail. Returns `(occupancy, approx)`
    where `approx` marks a full fallback (no real usage anywhere)."""
    snapshot: UsageSnapshot | None = None
    last_ai_index = -1
    for i, message in enumerate(messages):
        snap = occupancy_from_message(message)
        if snap is not None:
            snapshot = snap
            last_ai_index = i
    if snapshot is None:
        return approx_tokens(messages), True
    trailing = 0
    for message in messages[last_ai_index + 1:]:
        trailing += approx_tokens([message])
    return snapshot.occupancy + trailing, False


@dataclass
class LedgerEntry:
    """One session thread's current occupancy record (the trigger's input).

    `over_budget` is the threshold-trigger decision; `approx` marks a full-fallback
    estimate; `cache_read` is observability, never load-bearing on its own."""

    thread_id: str
    occupancy: int
    over_budget: bool
    approx: bool
    cache_read: int
    updated_at: dt.datetime = field(default_factory=lambda: dt.datetime.now(dt.timezone.utc))


class UsageLedger:
    """The per-thread usage ledger keyed by thread id (the trigger half of slice A).

    Later slices extend this object with the summary ledger fields (turn count,
    reclaimed tokens, last compacted at, spans, over-budget flag) per ADR D5."""

    def __init__(self, window: CompactionWindow):
        self.window = window
        self._entries: dict[str, LedgerEntry] = {}

    def update(self, thread_id: str, messages: list[BaseMessage]) -> LedgerEntry:
        occupancy, approx = compute_occupancy(messages)
        cache_read = 0
        for message in reversed(list(messages)):
            snap = occupancy_from_message(message)
            if snap is not None:
                cache_read = snap.cache_read
                break
        if approx:
            logger.warning(
                "compaction ledger: thread %s has no real usage metadata; "
                "occupancy is approximate (%d tokens) - fail-open, logged",
                thread_id, occupancy)
        entry = LedgerEntry(
            thread_id=thread_id,
            occupancy=occupancy,
            over_budget=is_over_budget(occupancy, self.window),
            approx=approx,
            cache_read=cache_read,
        )
        self._entries[thread_id] = entry
        logger.info(
            "compaction ledger: thread=%s occupancy=%d budget=%d over_budget=%s "
            "approx=%s cache_read=%s",
            thread_id, occupancy, self.window.budget, entry.over_budget, approx, cache_read)
        return entry

    def entry(self, thread_id: str) -> LedgerEntry | None:
        return self._entries.get(thread_id)


def is_over_budget(occupancy: int, window: CompactionWindow) -> bool:
    """The threshold trigger (D2): inclusive at the boundary - a call never proceeds
    on an over-budget window."""
    return occupancy >= window.budget


# --- D7/D8: the compact pass (pure assembly: offload + running summary) --------

# D7: the reserved byte-identical tail budget (operator-ruled default), measured
# from the trail's end in approximate tokens.
DEFAULT_REPLAY_KEEP_TOKENS = 30_000

# The prefix marking a synthetic running-summary message in the trail (D5) - kept
# in lockstep with `RunningSummary.to_text()`.
_SUMMARY_MESSAGE_PREFIX = "[running summary]"

# The readability signal of a compact pass (D7/D11) - "compacted"/"unchanged" in
# the spirit of the reasoning pipeline's "replayed"/"absent" vocabulary.
READABILITY_COMPACTED = "compacted"
READABILITY_UNCHANGED = "unchanged"

# The pairing fallback when no preceding tool call matches a tool result (D8).
_TOOL_FALLBACK_NAME = "tool"
_TOOL_FALLBACK_ARGS = ""


@dataclass(frozen=True)
class CompactReport:
    """The report of ONE compact pass (D7/D11).

    `exempted_spans` is the reserved byte-identical tail's size, `summarised_spans`
    the AIMessage spans folded into the running summary, `offloaded_bodies` the
    tool bodies written to the module store, `reclaimed_tokens` the before-minus-
    after occupancy (floored at 0), `readability` the "compacted"/"unchanged"
    signal, `summary_status` the pass outcome, and `new_summary` the summary the
    pass produced (None on failed/terminal/no-call)."""

    exempted_spans: int
    summarised_spans: int
    offloaded_bodies: int
    reclaimed_tokens: int
    readability: str
    summary_status: Literal["ok", "failed", "terminal"]
    new_summary: RunningSummary | None


@dataclass(frozen=True)
class CompactResult:
    """The compact pass's output (D1 staging).

    `messages` is the STAGED compacted trail, or the ORIGINAL trail unchanged when
    the summarisation failed or was terminal; `report` carries the pass's report."""

    messages: list
    report: CompactReport


def _exempt_tail_size(
    messages: list[BaseMessage],
    profile: CapabilityProfile | None,
    replay_keep_tokens: int,
) -> int:
    """The number of trailing messages reserved byte-identical (D7).

    Walked FROM the end, accumulating approximate tokens per message until the
    replay budget is reached; that suffix is exempt - neither summarised nor
    offloaded. When the profile is None or its reasoning surface is falsy, the tail
    is empty (no replay surface, everything summarisable)."""
    if profile is None or not getattr(profile, "reasoning_in_response", None):
        return 0
    if replay_keep_tokens <= 0:
        return 0
    acc = 0
    size = 0
    for message in reversed(messages):
        try:
            acc += approx_tokens([message])
        except Exception:  # noqa: BLE001 - an unmeasurable message degrades, never raises
            acc += 1
        size += 1
        if acc >= replay_keep_tokens:
            break
    return size


def _args_text(args: Any) -> str:
    """Render a tool call's args to the D8 outline string: a str passes through,
    anything else JSON-renders; an unrenderable value degrades to the empty string."""
    if args is None:
        return ""
    if isinstance(args, str):
        return args
    try:
        return json.dumps(args)
    except Exception:  # noqa: BLE001 - fail-open: an unrenderable outline degrades
        return ""


def _tool_pairing(ai_message: Any, tool_call_id: str) -> tuple[str, str]:
    """The (name, args) outline for one tool result, from the PRECEDING AIMessage's
    tool_calls matched by tool-call id (D8); name="tool" and args="" when no
    pairing is found - the pass's documented fallback."""
    if isinstance(ai_message, AIMessage):
        for call in getattr(ai_message, "tool_calls", None) or []:
            call_id = call.get("id") if isinstance(call, dict) else getattr(call, "id", None)
            if call_id == tool_call_id:
                name = call.get("name") if isinstance(call, dict) else getattr(call, "name", None)
                args = call.get("args") if isinstance(call, dict) else getattr(call, "args", None)
                name = name if isinstance(name, str) and name else _TOOL_FALLBACK_NAME
                return name, _args_text(args)
    return _TOOL_FALLBACK_NAME, _TOOL_FALLBACK_ARGS


def _is_synthetic_summary(message: BaseMessage) -> bool:
    """Whether a message is the prior synthetic running-summary message (D5): a
    SystemMessage whose content starts with the summary prefix. Replaced each pass,
    never duplicated."""
    if not isinstance(message, SystemMessage):
        return False
    content = message.content
    return isinstance(content, str) and content.startswith(_SUMMARY_MESSAGE_PREFIX)


def _compact_pass(
    messages: list[BaseMessage],
    *,
    thread_id: str,
    profile: CapabilityProfile | None,
    store: ToolOutputStore,
    summariser: Any,
    existing: RunningSummary | None,
    replay_keep_tokens: int,
) -> CompactResult:
    """The compact pass's assembly, wrapped by `compact_pass` for fail-open."""
    original = list(messages)
    tail_size = _exempt_tail_size(original, profile, replay_keep_tokens)
    tail = original[len(original) - tail_size:] if tail_size else []
    region = original[:len(original) - tail_size] if tail_size else original

    staged: list[BaseMessage] = []
    spans: list[AIMessage] = []
    offloaded_bodies = 0
    preceding_ai: AIMessage | None = None
    for message in region:
        if isinstance(message, AIMessage):
            preceding_ai = message
            spans.append(message)
            continue
        if isinstance(message, ToolMessage):
            name, args = _tool_pairing(preceding_ai, message.tool_call_id)
            try:
                result = offload_tool_message(
                    store, thread_id, message, name=name, args=args)
            except Exception:  # noqa: BLE001 - a failing offload keeps the body full
                logger.debug("compact pass: tool offload failed; keeping the body full",
                             exc_info=True)
                result = message
            if result is not message:
                offloaded_bodies += 1
            staged.append(result)
            continue
        if _is_synthetic_summary(message):
            continue
        staged.append(message)

    new_summary: RunningSummary | None = None
    if spans or existing is not None:
        outcome = summarise(summariser, existing=existing, spans=spans)
        if outcome.status in ("failed", "terminal") or outcome.summary is None:
            # An "ok" without a summary is a degenerate pass - degrade the same
            # way as a failed one, never stage it (fail-open).
            return CompactResult(
                messages=original,
                report=CompactReport(
                    exempted_spans=tail_size,
                    summarised_spans=len(spans),
                    offloaded_bodies=offloaded_bodies,
                    reclaimed_tokens=0,
                    readability=READABILITY_UNCHANGED,
                    summary_status=outcome.status,
                    new_summary=None,
                ),
            )
        new_summary = outcome.summary
        staged = staged + [SystemMessage(content=new_summary.to_text())] + tail
    else:
        staged = staged + tail

    reclaimed = max(0, approx_tokens(original) - approx_tokens(staged))
    return CompactResult(
        messages=staged,
        report=CompactReport(
            exempted_spans=tail_size,
            summarised_spans=len(spans),
            offloaded_bodies=offloaded_bodies,
            reclaimed_tokens=reclaimed,
            readability=(
                READABILITY_COMPACTED if new_summary is not None
                else READABILITY_UNCHANGED
            ),
            summary_status="ok",
            new_summary=new_summary,
        ),
    )


def compact_pass(
    messages: list[BaseMessage],
    *,
    thread_id: str,
    profile: CapabilityProfile | None,
    store: ToolOutputStore,
    summariser: Any,
    existing: RunningSummary | None = None,
    replay_keep_tokens: int = DEFAULT_REPLAY_KEEP_TOKENS,
) -> CompactResult:
    """Run ONE compact pass (D7/D8, D1-staging): compose the tool-output offload
    and the running summary into a single STAGED result.

    `thread_id` keys the offload into the module store (D8). The pass never writes
    the checkpointer (D1) - it stages. A reasoning-capable profile reserves a
    token-bounded byte-identical tail that is neither summarised nor offloaded;
    everything older is summarisable, tool bodies over the cut offload to the
    module store (D8), and the ONE atomic running-summary call (D5) folds the prior
    summary and new spans into a single synthetic message inserted immediately
    before the tail. A failed or terminal summarisation returns the ORIGINAL trail
    unchanged (D6 fail-safe); a bad message shape degrades (kept or summarised
    safely), never raises."""
    try:
        return _compact_pass(
            messages, thread_id=thread_id, profile=profile, store=store,
            summariser=summariser, existing=existing,
            replay_keep_tokens=replay_keep_tokens)
    except Exception:  # noqa: BLE001 - fail-open: never into the caller
        logger.warning("compact pass failed; returning the original trail unchanged",
                       exc_info=True)
        return CompactResult(
            messages=list(messages),
            report=CompactReport(
                exempted_spans=0, summarised_spans=0, offloaded_bodies=0,
                reclaimed_tokens=0, readability=READABILITY_UNCHANGED,
                summary_status="failed", new_summary=None,
            ),
        )


# --- the middleware (slice A: ledger update only) -----------------------------

_middleware_cls = None


def _compaction_middleware_cls():
    """The `AgentMiddleware` subclass, defined lazily so importing this module stays
    light (the `actor.py` precedent: the middleware base class is imported inside
    the factory, never at import)."""
    global _middleware_cls
    if _middleware_cls is None:
        from langchain.agents.middleware import AgentMiddleware

        class _CompactionMiddleware(AgentMiddleware):
            def __init__(self, window, ledger):
                self.window = window
                self.ledger = ledger

            def after_model(self, state, runtime):  # noqa: D401 - slice A: ledger only
                """Update the ledger from the real trail. Non-blocking, never spawns,
                never raises: a state without a usable trail, or a hook call outside a
                graph context (no thread id), degrades to a no-op (fail-open)."""
                try:
                    thread_id = _thread_id()
                    if thread_id is None:
                        return None
                    messages = state.get("messages") if isinstance(state, dict) else None
                    if not isinstance(messages, list):
                        return None
                    self.ledger.update(thread_id, list(messages))
                except Exception:  # noqa: BLE001 - fail-open, never into the turn
                    logger.debug("compaction ledger update failed; ignoring", exc_info=True)
                return None

        _middleware_cls = _CompactionMiddleware
    return _middleware_cls


def _thread_id() -> str | None:
    from langgraph.config import get_config

    configurable = get_config().get("configurable")
    if not isinstance(configurable, dict):
        return None
    value = configurable.get("thread_id")
    return value if isinstance(value, str) else None


def create_compaction_middleware(
    role_id: str | None = None,
    *,
    threshold: float | None = None,
    window: CompactionWindow | None = None,
    ledger: UsageLedger | None = None,
) -> Any:
    """Build the compaction middleware (slice A: the measurement half).

    `window` is explicit for tests; the default resolves it from the role's
    capability profile once and holds it (D2). `ledger` is injectable (tests and
    later slices share one per session)."""
    resolved = window or resolve_window(role_id, threshold=threshold)
    return _compaction_middleware_cls()(resolved, ledger or UsageLedger(resolved))
