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
replay-collision precedence. Slice E (the concurrency half) is the
`CompactionManager` + the middleware's `after_agent`/`before_model` hooks: the
turn-end SPAWN runs the pass out-of-band and STAGES it, and the next call's
`before_model` is the strict barrier - it awaits the pending pass, applies the
staged compacted trail as a messages-channel state update the graph's own
reducer persists (D1), and runs the synchronous BACKSTOP when the ledger is over
budget with no pending task (D4). The pass compacts exactly the trail the ledger
last measured (its boundary - the ids recorded at `after_model`); the FRESH
delta - messages added since, most importantly the current turn's own input -
is preserved verbatim on top of the staged trail, so replacement can never wipe
input the pass never saw. A call never proceeds on an over-budget window; the
local consecutive-pass cap (D6) stops auto-spawning at 3 and escalates.

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
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Literal

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    RemoveMessage,
    SystemMessage,
    ToolMessage,
)

from polymerhus.app.llm.summary import RunningSummary, summarise
from polymerhus.app.llm.tool_output import (
    InMemoryToolOutputStore,
    ToolOutputStore,
    offload_tool_message,
)

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
    estimate; `cache_read` is observability, never load-bearing on its own;
    `escalated` is the D6 cap flag - set loudly when the local consecutive-pass
    cap fires, re-asserted after each ledger update until the thread recovers."""

    thread_id: str
    occupancy: int
    over_budget: bool
    approx: bool
    cache_read: int
    updated_at: dt.datetime = field(default_factory=lambda: dt.datetime.now(dt.timezone.utc))
    escalated: bool = False


class UsageLedger:
    """The per-thread usage ledger keyed by thread id (the trigger half of slice A).

    `_last_ids` records the exact message ids of the last measured trail - the
    compaction BOUNDARY. Everything the ledger measured (turn end, or the previous
    compacted trail) is what a pass compacts; anything added since is FRESH and
    rides on top untouched. Kept in the ledger so the barrier's delta logic reads
    one authoritative boundary whether the pass was spawned out-of-band or runs as
    the synchronous backstop."""

    def __init__(self, window: CompactionWindow):
        self.window = window
        self._entries: dict[str, LedgerEntry] = {}
        self._last_ids: dict[str, set[str]] = {}

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
        self._last_ids[thread_id] = _message_ids(messages)
        logger.info(
            "compaction ledger: thread=%s occupancy=%d budget=%d over_budget=%s "
            "approx=%s cache_read=%s",
            thread_id, occupancy, self.window.budget, entry.over_budget, approx, cache_read)
        return entry

    def entry(self, thread_id: str) -> LedgerEntry | None:
        return self._entries.get(thread_id)

    def last_ids(self, thread_id: str) -> set[str]:
        """The message ids of the trail the ledger last measured (the compaction
        boundary); empty when nothing has been measured yet."""
        return self._last_ids.get(thread_id, set())


def _message_ids(messages: list[BaseMessage]) -> set[str]:
    """The message ids of a trail, dropping messages without an id (freshly built
    trails round-trip through the graph channel which assigns ids; a manual trail
    degrades to an empty boundary - fail-safe)."""
    ids = set()
    for message in messages:
        message_id = getattr(message, "id", None)
        if message_id is not None:
            ids.add(message_id)
    return ids


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
    # Region human messages are folded into the running summary when one is
    # produced (the summary carries the user's directives - they never need to
    # stay byte-identical) but kept verbatim when no summary fires. Tracked as a
    # set of object ids so the ELSE branch preserves the original interleaving.
    region_humans: set[int] = set()
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
        if isinstance(message, HumanMessage):
            region_humans.add(id(message))
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
        staged = ([m for m in staged if id(m) not in region_humans]
                  + [SystemMessage(content=new_summary.to_text())] + tail)
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
    before the tail. When a summary IS produced, older turn inputs in the region
    before the tail fold into it too (the summary carries the user's directives);
    when no summary fires, every message stays verbatim. A failed or terminal
    summarisation returns the ORIGINAL trail unchanged (D6 fail-safe); a bad
    message shape degrades (kept or summarised safely), never raises."""
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


# --- the middleware + manager (slice A ledger, slice E spawn/barrier) ----------

# D6: the local consecutive-pass cap - at 3 consecutive failed/terminal passes,
# auto-spawn STOPS and the barrier escalates loudly (log + ledger flag) and
# releases on last-known-good. A later successful pass or a recovery trigger
# resets the streak.
CONSECUTIVE_PASS_CAP = 3

# The barrier's bound on awaiting a pending pass (D1/D4): "generous" - the compact
# pass runs under the #73 escalating schedule whose default sum is 4500s, so the
# barrier must exceed that or it would guillotine a legitimately slow summary.
# On timeout the barrier releases on last-known-good (fail-open, D6).
BARRIER_PENDING_TIMEOUT_S = 90.0 * 60.0

# The out-of-band pass pool's worker count (D4 spawn - one pass per thread at a
# time, so a handful of workers covers concurrent session threads).
DEFAULT_MAX_WORKERS = 4

_middleware_cls = None


def _compaction_middleware_cls():
    """The `AgentMiddleware` subclass, defined lazily so importing this module stays
    light (the `actor.py` precedent: the middleware base class is imported inside
    the factory, never at import)."""
    global _middleware_cls
    if _middleware_cls is None:
        from langchain.agents.middleware import AgentMiddleware

        class _CompactionMiddleware(AgentMiddleware):
            def __init__(self, window, ledger, *, store, summariser, profile,
                         replay_keep_tokens, pending_timeout_s, consecutive_pass_cap):
                self.window = window
                self.ledger = ledger
                self.manager = CompactionManager(
                    window, ledger, store=store, summariser=summariser, profile=profile,
                    replay_keep_tokens=replay_keep_tokens,
                    pending_timeout_s=pending_timeout_s,
                    consecutive_pass_cap=consecutive_pass_cap)

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
                    entry = self.ledger.update(thread_id, list(messages))
                    if self.manager.is_escalated(thread_id):
                        entry.escalated = True
                except Exception:  # noqa: BLE001 - fail-open, never into the turn
                    logger.debug("compaction ledger update failed; ignoring", exc_info=True)
                return None

            def after_agent(self, state, runtime):
                """The turn-end SPAWN (D4): when the ledger for the thread is over budget
                and auto-spawn is not capped, start the out-of-band compaction pass on
                the turn's final trail and STAGE its result. Never blocks the turn's
                return; fail-open (no thread id / malformed state / a dead pool) is a
                no-op - the barrier's BACKSTOP covers a lost or never-spawned pass."""
                try:
                    thread_id = _thread_id()
                    if thread_id is None:
                        return None
                    messages = state.get("messages") if isinstance(state, dict) else None
                    if not isinstance(messages, list):
                        return None
                    self.manager.spawn(thread_id, list(messages))
                except Exception:  # noqa: BLE001 - fail-open, never into the turn
                    logger.debug("compaction spawn failed; the backstop covers it",
                                 exc_info=True)
                return None

            def before_model(self, state, runtime):
                """The strict BARRIER (D1/D4): await any pending pass for the thread,
                apply the staged compacted trail as a messages state update the graph's
                own reducer persists, and - as a BACKSTOP - compact synchronously when
                the ledger is over budget with no pending task. A call never proceeds on
                an over-budget window while compaction is possible; on any surprise
                (timeout, exception, malformed state) it releases on last-known-good,
                never raising into the turn."""
                try:
                    thread_id = _thread_id()
                    if thread_id is None:
                        return None
                    messages = state.get("messages") if isinstance(state, dict) else None
                    if not isinstance(messages, list):
                        return None
                    return self.manager.ensure_under_budget(thread_id, list(messages))
                except Exception:  # noqa: BLE001 - fail-open, never into the turn
                    logger.warning(
                        "compaction barrier failed for %r; releasing on last-known-good",
                        _thread_id(), exc_info=True)
                    return None

        _middleware_cls = _CompactionMiddleware
    return _middleware_cls


class CompactionManager:
    """The concurrency half of the compaction component (slice E, ADR D1/D4/D6).

    Owns, per thread: the pending out-of-band pass Future, the staged compacted
    trail, the local consecutive-pass count, and the running-summary pointer. The
    turn-end SPAWN (`spawn`) submits the pass to a background pool; the strict
    BARRIER (`ensure_under_budget`) awaits it, applies the staged trail through the
    messages channel's reducer, or runs the synchronous BACKSTOP - a call never
    proceeds on an over-budget window while compaction is possible. Fail-open
    throughout: a lost task, a timeout, or a malformed result releases on
    last-known-good and never raises into the caller."""

    def __init__(
        self,
        window: CompactionWindow,
        ledger: UsageLedger | None = None,
        *,
        store: ToolOutputStore | None = None,
        summariser=None,
        profile: CapabilityProfile | None = None,
        replay_keep_tokens: int = DEFAULT_REPLAY_KEEP_TOKENS,
        pending_timeout_s: float = BARRIER_PENDING_TIMEOUT_S,
        consecutive_pass_cap: int = CONSECUTIVE_PASS_CAP,
    ):
        self.window = window
        self.ledger = ledger or UsageLedger(window)
        self.store = store if store is not None else InMemoryToolOutputStore()
        self.summariser = summariser
        self.profile = profile
        self.replay_keep_tokens = replay_keep_tokens
        self.pending_timeout_s = pending_timeout_s
        self.consecutive_pass_cap = consecutive_pass_cap
        self._pending: dict[str, Future] = {}
        self._existing: dict[str, Any] = {}
        self._streak: dict[str, int] = {}
        self._last_reports: dict[str, CompactReport] = {}
        self._escalated: dict[str, bool] = {}
        self._executor: ThreadPoolExecutor | None = None
        self._lock = threading.RLock()

    # -- the observable surface ------------------------------------------------

    def streak(self, thread_id: str) -> int:
        """The thread's current consecutive failed/terminal pass count (D6)."""
        with self._lock:
            return self._streak.get(thread_id, 0)

    def is_escalated(self, thread_id: str) -> bool:
        """Whether the thread hit the consecutive-pass cap and escalated loudly (D6)."""
        with self._lock:
            return self._escalated.get(thread_id, False)

    def pending(self, thread_id: str) -> Future | None:
        """The pending pass Future for the thread, or None when nothing is in flight."""
        with self._lock:
            return self._pending.get(thread_id)

    def last_report(self, thread_id: str) -> "CompactReport | None":
        """The last COMPLETED pass's report for the thread (D11 observability), or
        None when no pass has settled yet - whether it applied, failed, or was
        terminal; the caller reads `summary_status` / `readability` to distinguish."""
        with self._lock:
            return self._last_reports.get(thread_id)

    # -- the D4 spawn ----------------------------------------------------------

    def spawn(self, thread_id: str, messages: list) -> Future | None:
        """Start ONE out-of-band compaction pass for the thread's trail (D4).

        Spawns only when the ledger is over budget, no pass is already in flight,
        auto-spawn is not at the consecutive-pass cap, and a summariser is wired.
        The pass runs on a background pool and STAGES its `CompactResult` - it never
        writes the checkpointer (D1). Returns the Future, or None when no spawn is
        warranted - the barrier's BACKSTOP then covers the thread (D4)."""
        with self._lock:
            entry = self.ledger.entry(thread_id)
            if entry is None:
                return None
            self._maybe_recover(thread_id)
            if not entry.over_budget:
                return None
            if self.summariser is None:
                return None
            if self._streak.get(thread_id, 0) >= self.consecutive_pass_cap:
                return None
            if thread_id in self._pending:
                return None
            existing = self._existing.get(thread_id)
            executor = self._executor_pool()
            future = executor.submit(
                self._run_pass, thread_id, list(messages), existing)
            self._pending[thread_id] = future
        logger.info("compaction: spawned out-of-band pass for thread %s", thread_id)
        return future

    # -- the D1/D4 barrier + backstop ------------------------------------------

    def ensure_under_budget(self, thread_id: str, messages: list) -> dict | None:
        """The strict barrier: a call never proceeds on an over-budget window.

        If a pass is pending, AWAIT it (the sanctioned block point) and apply the
        staged compacted trail; a failed/terminal pass releases on last-known-good
        and counts toward the cap. If the ledger is over budget with NO pending task
        (a lost or restarted pass), run the BACKSTOP synchronously right here. In
        both paths the pass compacts ONLY the trail the ledger last measured - its
        boundary - and the fresh delta (messages added since, e.g. this turn's own
        input) rides on top untouched, so `RemoveMessage(remove_all)` can never
        wipe a message the pass never saw. Returns a `messages` state update for
        the graph's own reducer to apply, or None for no change. Fail-open: a
        timeout, an exception, or a malformed result degrades to last-known-good and
        never raises into the caller."""
        with self._lock:
            future = self._pending.pop(thread_id, None)
        if future is not None:
            result = self._await(thread_id, future)
            return self._settle(
                thread_id, result, self._fresh_delta(thread_id, messages))
        with self._lock:
            self._maybe_recover(thread_id)
        if not self._triggered(thread_id):
            return None
        base = self._backstop_base(thread_id, messages)
        delta = self._fresh_delta(thread_id, messages)
        try:
            result = self._run_pass(
                thread_id, base, self._existing.get(thread_id))
        except Exception:  # noqa: BLE001 - a raising backstop degrades to last-known-good
            logger.warning("compaction backstop raised for %s; releasing on last-known-good",
                           thread_id, exc_info=True)
            result = None
        return self._settle(thread_id, result, delta)

    # -- the fresh-delta split (boundary preservation) --------------------------

    def _fresh_delta(self, thread_id: str, messages: list) -> list:
        """The messages added since the ledger's last measurement (the compaction
        boundary): this turn's own input and anything the pending pass's input did
        not contain. Never compacted; preserved verbatim on top of the staged
        trail. A message without an id is treated as fresh (unmatchable - fail-safe)."""
        base = self.ledger.last_ids(thread_id)
        return [m for m in messages if getattr(m, "id", None) not in base]

    def _backstop_base(self, thread_id: str, messages: list) -> list:
        """The trail the synchronous backstop compacts: exactly the messages the
        ledger last measured (its boundary), in current order. Falls back to the
        full list only when nothing is measurable (no boundary) so the backstop
        still runs in every malformed case - fail-open."""
        base = self.ledger.last_ids(thread_id)
        if not base:
            return list(messages)
        bounded = [m for m in messages if getattr(m, "id", None) in base]
        return bounded or list(messages)

    # -- applying the staged trail (slice E core) -------------------------------

    def apply_staged(self, thread_id: str, result: CompactResult,
                     delta: list | None = None) -> dict:
        """Record a successful pass and return the messages state update.

        The update is `RemoveMessage(id=REMOVE_ALL_MESSAGES)` followed by the staged
        trail plus any fresh delta: through the `messages` channel's `add_messages`
        reducer this removes the summarised spans and the prior synthetic summary,
        replaces offloaded tool bodies with their headers, adds the new synthetic
        summary, and re-appends anything the pass never saw (this turn's own input) -
        in one atomic, race-free state update the graph persists (D1). The thread's
        running summary pointer advances, the consecutive-pass streak resets, and the
        ledger is re-measured from the applied trail so the mid-turn loop does not
        re-trigger a redundant pass."""
        staged = list(result.messages) + list(delta or ())
        self._existing[thread_id] = result.report.new_summary
        with self._lock:
            self._streak[thread_id] = 0
            was_escalated = self._escalated.pop(thread_id, False)
            entry = self.ledger.entry(thread_id)
            if entry is not None:
                entry.escalated = False
        if was_escalated:
            logger.info("compaction: thread %s recovered after a successful pass", thread_id)
        try:
            self.ledger.update(thread_id, staged)
        except Exception:  # noqa: BLE001 - the barrier applies even if re-measurement fails
            logger.debug("compaction ledger re-measurement failed; ignoring", exc_info=True)
        logger.info(
            "compaction: thread %s applied a compacted trail (reclaimed %d tokens)",
            thread_id, result.report.reclaimed_tokens)
        from langgraph.graph.message import REMOVE_ALL_MESSAGES

        return {"messages": [RemoveMessage(id=REMOVE_ALL_MESSAGES), *staged]}

    # -- internals --------------------------------------------------------------

    def _triggered(self, thread_id: str) -> bool:
        """Whether a pass is warranted right now: over budget, not at the cap, and a
        summariser is wired. `_maybe_recover` must have run first."""
        entry = self.ledger.entry(thread_id)
        if entry is None or not entry.over_budget:
            return False
        if self.summariser is None:
            return False
        with self._lock:
            return self._streak.get(thread_id, 0) < self.consecutive_pass_cap

    def _maybe_recover(self, thread_id: str) -> None:
        """A recovery TRIGGER (D6): when the ledger reports the thread UNDER budget,
        the streak and the escalation flag reset - a later over-budget episode is a
        fresh start, never a continuation of the capped run."""
        entry = self.ledger.entry(thread_id)
        if entry is None or entry.over_budget:
            return
        if self._streak.get(thread_id, 0) or self._escalated.get(thread_id, False):
            logger.info("compaction: thread %s is under budget again; resetting the "
                        "consecutive-pass streak", thread_id)
            self._streak[thread_id] = 0
            self._escalated.pop(thread_id, None)
            entry.escalated = False

    def _executor_pool(self) -> ThreadPoolExecutor:
        with self._lock:
            if self._executor is None:
                self._executor = ThreadPoolExecutor(
                    max_workers=DEFAULT_MAX_WORKERS,
                    thread_name_prefix="compaction",
                )
            return self._executor

    def _run_pass(self, thread_id: str, messages: list, existing: Any) -> CompactResult:
        """Run the pass out-of-band; the runner is fail-open so a raising pass is a
        failed pass, never a bare exception escaping into the Future."""
        try:
            return compact_pass(
                messages, thread_id=thread_id, profile=self.profile, store=self.store,
                summariser=self.summariser, existing=existing,
                replay_keep_tokens=self.replay_keep_tokens)
        except Exception:  # noqa: BLE001 - a pass never raises into the barrier
            logger.warning("compaction: out-of-band pass raised; treating it as failed",
                           exc_info=True)
            return CompactResult(
                messages=list(messages),
                report=CompactReport(
                    exempted_spans=0, summarised_spans=0, offloaded_bodies=0,
                    reclaimed_tokens=0, readability=READABILITY_UNCHANGED,
                    summary_status="failed", new_summary=None,
                ),
            )

    def _await(self, thread_id: str, future: Future) -> CompactResult | None:
        """The barrier's sanctioned block point: await the pending pass under the
        generous bound; a timeout or a task exception releases on last-known-good."""
        try:
            return future.result(timeout=self.pending_timeout_s)
        except Exception:  # noqa: BLE001 - TimeoutError / a cancelled or failing task
            logger.warning(
                "compaction: barrier could not collect the pending pass for %s; "
                "releasing on last-known-good", thread_id, exc_info=True)
            return None

    def _settle(self, thread_id: str, result: CompactResult | None,
                delta: list | None = None) -> dict | None:
        """Route one pass's outcome: apply a successful staged trail, count a failed or
        terminal pass toward the cap (escalating loudly at it), and otherwise release
        on last-known-good - never raising into the turn. `delta` carries the fresh
        messages that ride untouched on top of the staged trail."""
        if isinstance(result, CompactResult):
            with self._lock:
                self._last_reports[thread_id] = result.report
        if isinstance(result, CompactResult) and result.report.summary_status == "ok":
            if self._is_applyable(result):
                return self.apply_staged(thread_id, result, delta=delta)
            return None
        self._note_failure(thread_id)
        return None

    @staticmethod
    def _is_applyable(result: CompactResult) -> bool:
        """Whether the staged trail actually differs from the input: a summary was
        produced or a tool body was offloaded. An 'ok' pass with nothing to apply is
        a no-op, never a failure and never a pointless re-emit."""
        return (result.report.new_summary is not None
                or result.report.offloaded_bodies > 0)

    def _note_failure(self, thread_id: str) -> None:
        """Count a failed/terminal pass toward the D6 cap; crossing it escalates
        loudly (log + ledger flag) exactly once, and the over-budget flag is
        retained so a later successful pass or recovery trigger resets the streak."""
        with self._lock:
            self._streak[thread_id] = self._streak.get(thread_id, 0) + 1
            if (self._streak[thread_id] >= self.consecutive_pass_cap
                    and not self._escalated.get(thread_id, False)):
                self._escalated[thread_id] = True
                entry = self.ledger.entry(thread_id)
                if entry is not None:
                    entry.escalated = True
                logger.warning(
                    "compaction: thread %s hit the consecutive-pass cap (%d); "
                    "auto-spawn stopped, the barrier releases on last-known-good, "
                    "and the over-budget flag is retained",
                    thread_id, self.consecutive_pass_cap)


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
    store: ToolOutputStore | None = None,
    summariser=None,
    profile: CapabilityProfile | None = None,
    replay_keep_tokens: int = DEFAULT_REPLAY_KEEP_TOKENS,
    pending_timeout_s: float = BARRIER_PENDING_TIMEOUT_S,
    consecutive_pass_cap: int = CONSECUTIVE_PASS_CAP,
) -> Any:
    """Build the compaction middleware (slices A + E: ledger, spawn, barrier).

    `window` is explicit for tests; the default resolves it from the role's
    capability profile once and holds it (D2). `ledger` is injectable (tests and
    sessions share one per middleware). `store`, `summariser`, and `profile` are
    the slice-E collaborators: the module-owned tool-body store (D8), the session
    role's own structured-output summariser (D5), and the capability profile whose
    `reasoning_in_response` decides the D7 replay tail. With no `summariser` wired
    the middleware measures the ledger but never spawns - fail-open."""

    resolved = window or resolve_window(role_id, threshold=threshold)
    return _compaction_middleware_cls()(
        resolved,
        ledger or UsageLedger(resolved),
        store=store,
        summariser=summariser,
        profile=profile,
        replay_keep_tokens=replay_keep_tokens,
        pending_timeout_s=pending_timeout_s,
        consecutive_pass_cap=consecutive_pass_cap,
    )


def resolve_compaction_profile(role_id: str):
    """The role's T3 capability profile for the compaction replay tail (D7),
    fail-open to None (no reasoning surface, empty replay tail) - a raising
    capability reader degrades the profile, never the middleware's construction."""
    try:
        from polymerhus.app.llm.capability import resolve_capability
        from polymerhus.app.llm.providers import resolve_role

        provider, model = resolve_role(role_id)
        return resolve_capability(provider, model)
    except Exception:  # noqa: BLE001 - fail-open, never into the consumer
        return None


def build_role_compaction_middleware(
    role_id: str,
    *,
    window: CompactionWindow | None = None,
    threshold: float | None = None,
    store: ToolOutputStore | None = None,
) -> Any:
    """Build the compaction middleware for a session role (D9): the role's own
    budgeted structured summariser (D5) and its fail-open capability profile (D7),
    bound to the role's resolved window. `window` is explicit for tests; `store` is
    the module-owned tool-body store (defaults in-memory). Fully fail-open at build
    time - a missing role config degrades the profile/window, never raises."""
    from polymerhus.app.llm.summary import build_summariser

    return create_compaction_middleware(
        role_id,
        window=window,
        threshold=threshold,
        store=store,
        summariser=build_summariser(role_id),
        profile=resolve_compaction_profile(role_id),
    )
