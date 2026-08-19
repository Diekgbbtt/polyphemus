"""The context-window compaction manager (#95) - the shared, adaptive window keeper.

Long-horizon session agents accumulate reasoning turns and tool outputs until they
exceed the model's context window. This module owns the compaction logic: it
measures a session trail's occupancy from the provider's REAL per-step usage,
flags the session as over budget once occupancy crosses a configurable threshold
of the model's real window (read from the gateway capability surface, never a
hardcoded table), and - in later slices - runs the out-of-band compact pass
(summarise reasoning, offload tool bodies, preserve the replay tail) behind a
barrier. It augments the SESSION path only (`run_session_turn` /
`arun_session_turn` via the `middleware` seam); the one-shot path is untouched.

Slice A (this module's current surface) is the measurement half: the per-thread
usage ledger and the threshold trigger, wired as an `AgentMiddleware.after_model`
hook that updates the ledger and NEVER spawns compaction. The spawn, the barrier,
the compact pass, and the running summary land in later slices.

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

Importing this module performs no I/O and requires no env var (CODING_STANDARD
section 6). The `AgentMiddleware` base class is imported lazily inside the factory,
never at import (the `actor.py` precedent).
"""
from __future__ import annotations

import datetime as dt
import logging
import os
from dataclasses import dataclass, field
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage

logger = logging.getLogger(__name__)

# --- D2: the threshold + window surface --------------------------------------

# The threshold env override (D2); beats the 0.90 default only when a builder
# parameter is not given. Unusable values fail fast (LLMConfigError) - a config
# lie, mirroring the `LLM_ROLE_MODEL_CONTEXT_LIMIT` precedent (capability.py).
COMPACTION_THRESHOLD_ENV = "LLM_COMPACTION_THRESHOLD"
DEFAULT_THRESHOLD = 0.90

# The conservative window default (D6 of the gateway ADR, imported from the
# capability reader - the single source, never re-declared here).
from polymerhus.app.llm.capability import DEFAULT_CONTEXT_LIMIT  # noqa: E402


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
