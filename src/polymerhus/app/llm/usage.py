"""The app-side token-usage ledger (`app/llm/usage.py`).

Every stateful agent records each model call's native `usage_metadata` here,
attributed to the calling agent and scoped by project. The accumulator is
PROCESS-WIDE and in-memory (it dies with the app process); the app API exposes
it read-only at `GET /projects/{id}/usage`, and the eval harness bounds a trial
by reading that endpoint.

The surface is a two-axis typed decomposition, not a scalar: `context_tokens`
(input) splits into `cached` (cache_read) and `uncached` (fresh input), and
`generated_tokens` (output) splits into `reasoning`
(output_token_details.reasoning) and `visible` (output minus reasoning). On the
pinned path `input_tokens` is INCLUSIVE of cache_read (LiteLLM's `prompt_tokens`
folds in cache_read and cache_creation; langchain_openai sets
`input_tokens = prompt_tokens`), so `uncached = input_tokens - cache_read`.

Three scalars ride the surface: `total_tokens` = context + generated (the raw
total, cache included), and `capped_tokens` = generated + uncached =
`total_tokens - cached` (the new tokens a call produced - generated output plus
the fresh input it read, excluding cache reads). The trial token budget counts
`capped_tokens`, so a mostly-cache-read context cannot consume the budget it was
not responsible for (ticket F16 follow-up). The axes are recorded per call so a
mostly-cache-read context is visible rather than folded into one opaque input
number (ticket F16).

The ledger is keyed by `(project_id, agent)`. A missing/blank project id records
under the `"unscoped"` sentinel bucket, which a project snapshot never returns:
one-shot/role calls that run outside a project stay visible in aggregate but can
never be mistaken for a project's spend.

The tracking is decoupled from Langfuse `observe` (a turn is counted whether or
not it is traced) and FAIL-OPEN: a malformed usage payload is logged and
swallowed, never raised into the agent turn. Importing this module performs no
I/O (CODING_STANDARD section 6).
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Callable, Mapping

from langchain.agents.middleware import AgentMiddleware, ModelRequest
from langchain_core.messages import AIMessage

logger = logging.getLogger(__name__)

_UNSCOPED = "unscoped"
"""The bucket for a record with no project id (None/blank). Never returned by a
project snapshot."""


def _int_field(usage: Mapping, key: str) -> int:
    """A non-negative int from the usage mapping, or 0 when absent/malformed
    (a bool is rejected, never treated as 0/1)."""
    value = usage.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        return 0
    return max(0, value)


def _detail_int(usage: Mapping, detail_key: str, field: str) -> int:
    """A non-negative int from a nested `usage_metadata` detail mapping, or 0 when
    the detail is absent/malformed. `input_token_details` / `output_token_details`
    are the SDK's native cache/reasoning carriers."""
    details = usage.get(detail_key)
    if not isinstance(details, Mapping):
        return 0
    return _int_field(details, field)


def _axis_totals(usage: Mapping) -> dict[str, int]:
    """One call's two-axis token decomposition (the ratified representation).

    Context (input) = `cached` (cache_read) + `uncached` (fresh input); generated
    (output) = `reasoning` (output_token_details.reasoning) + `visible` (output
    minus reasoning). On the pinned LiteLLM/langchain-openai path `input_tokens`
    is INCLUSIVE of cache_read, so `uncached = input_tokens - cache_read`; no
    component is negative, and `total_tokens` (context + generated) stays the
    faithful raw total. `capped_tokens` = generated + uncached = total - cached is
    the new-token axis the trial budget counts.

    A provider whose `input_tokens` EXCLUDES cache_read (it is not a subset) is
    detected only in the unambiguous case `cache_read > input_tokens`; then the
    cache_read is kept separate rather than clamped away. The ambiguous exclusive
    case is a documented non-goal (see the spec's provider-normalization caveats)."""
    input_tokens = _int_field(usage, "input_tokens")
    output_tokens = _int_field(usage, "output_tokens")
    cache_read = _detail_int(usage, "input_token_details", "cache_read")
    reasoning = min(
        _detail_int(usage, "output_token_details", "reasoning"), output_tokens)
    visible = output_tokens - reasoning
    if cache_read > input_tokens:
        # Exclusive convention: cache_read is not part of input_tokens. The
        # pinned path never lands here (cache_read is a subset of prompt_tokens);
        # keeping both is the conservative, non-dropping read.
        cached = cache_read
        uncached = input_tokens
    else:
        # Inclusive convention (pinned): input_tokens already contains cache_read.
        cached = cache_read
        uncached = input_tokens - cache_read
    generated = reasoning + visible
    return {
        "cached": cached,
        "uncached": uncached,
        "reasoning": reasoning,
        "visible": visible,
        "total_tokens": cached + uncached + generated,
        "capped_tokens": generated + uncached,
    }


def _entry_surface(entry: Mapping) -> dict[str, Any]:
    """One ledger entry's public two-axis shape (nested context/generated plus the
    scalar raw total, the capped budget axis, and the call count)."""
    return {
        "context_tokens": {"cached": entry["cached"],
                           "uncached": entry["uncached"]},
        "generated_tokens": {"reasoning": entry["reasoning"],
                             "visible": entry["visible"]},
        "total_tokens": entry["total_tokens"],
        "capped_tokens": entry["capped_tokens"],
        "calls": entry["calls"],
    }


class UsageLedger:
    """A process-wide, thread-safe token accumulator keyed by `(project_id, agent)`.

    Each entry holds the two-axis surface - `context_tokens` (`cached` +
    `uncached`) and `generated_tokens` (`reasoning` + `visible`) - plus the raw
    `total_tokens`, the `capped_tokens` budget axis, and `calls`. `record` is
    fail-open and a None/empty usage is a no-op; `snapshot` returns the project's
    aggregated surface plus the per-agent breakdown, excluding the `"unscoped"`
    bucket; `reset` clears all state (tests)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._entries: dict[tuple[str, str], dict[str, int]] = {}

    def record(self, project_id: str | None, agent: str,
               usage: Mapping | None) -> None:
        """Add one model call's usage. Fail-open: any malformed payload is logged
        and swallowed, never raised into the turn. A None/empty usage is a
        no-op (not even a call is counted)."""
        try:
            if not usage:
                return
            totals = _axis_totals(usage)
            key = (project_id or _UNSCOPED, agent)
            with self._lock:
                entry = self._entries.get(key)
                if entry is None:
                    entry = {"cached": 0, "uncached": 0, "reasoning": 0,
                             "visible": 0, "total_tokens": 0, "capped_tokens": 0,
                             "calls": 0}
                    self._entries[key] = entry
                for field in ("cached", "uncached", "reasoning", "visible",
                              "total_tokens", "capped_tokens"):
                    entry[field] += totals[field]
                entry["calls"] += 1
        except Exception:  # noqa: BLE001 - fail-open: never break the turn
            logger.warning("usage record failed; call left unaccounted",
                           exc_info=True)

    def snapshot(self, project_id: str) -> dict[str, Any]:
        """The project's aggregated two-axis surface plus its per-agent breakdown.
        The `"unscoped"` bucket is never included; an unknown project returns
        zeros/empty."""
        totals = {"cached": 0, "uncached": 0, "reasoning": 0, "visible": 0}
        total_tokens = 0
        capped_tokens = 0
        calls = 0
        by_agent: dict[str, dict[str, Any]] = {}
        with self._lock:
            for (pid, agent), entry in self._entries.items():
                if pid != project_id or pid == _UNSCOPED:
                    continue
                by_agent[agent] = _entry_surface(entry)
                for axis in totals:
                    totals[axis] += entry[axis]
                total_tokens += entry["total_tokens"]
                capped_tokens += entry["capped_tokens"]
                calls += entry["calls"]
        return {
            "project_id": project_id,
            "context_tokens": {"cached": totals["cached"],
                               "uncached": totals["uncached"]},
            "generated_tokens": {"reasoning": totals["reasoning"],
                                 "visible": totals["visible"]},
            "total_tokens": total_tokens,
            "capped_tokens": capped_tokens,
            "calls": calls,
            "by_agent": by_agent,
        }

    def reset(self) -> None:
        """Clear all state (tests)."""
        with self._lock:
            self._entries.clear()


def _response_usage(response: Any) -> Mapping | None:
    """The first `AIMessage` carrying non-empty `usage_metadata` in a model
    response's `result` list, or None. A response with no token data (e.g. a
    cached result) is a no-op, not an error."""
    result = getattr(response, "result", None)
    if not isinstance(result, list):
        return None
    for message in result:
        if not isinstance(message, AIMessage):
            continue
        usage = getattr(message, "usage_metadata", None)
        if usage:
            return usage
    return None


class TokenUsageMiddleware(AgentMiddleware):
    """Records each model call's native `usage_metadata` into the process-wide
    ledger, attributed by the run config's `usage_scope` (the project) and
    `role_id` (the agent).

    `wrap_model_call`/`awrap_model_call` are the hooks: the handler returns the
    real `ModelResponse`, so the usage lands on the ledger whichever streaming
    mode drives the turn. Reads identity from `langgraph.config.get_config()` and
    is FAIL-OPEN: any read/record error is logged and swallowed, never raised
    into the turn. A raising handler propagates untouched (no usage to read)."""

    def wrap_model_call(self, request: ModelRequest,
                        handler: Callable[..., Any]) -> Any:
        response = handler(request)
        self._record(response)
        return response

    async def awrap_model_call(self, request: ModelRequest,
                               handler: Callable[..., Any]) -> Any:
        response = await handler(request)
        self._record(response)
        return response

    @staticmethod
    def _record(response: Any) -> None:
        try:
            usage = _response_usage(response)
            if usage is None:
                return
            from langgraph.config import get_config

            metadata = (get_config() or {}).get("metadata") or {}
            usage_ledger().record(metadata.get("usage_scope"),
                                  metadata.get("role_id") or "unknown", usage)
        except Exception:  # noqa: BLE001 - fail-open: never break the turn
            logger.warning("token usage tracking failed; call left unaccounted",
                           exc_info=True)


def usage_middleware() -> AgentMiddleware:
    """A fresh `TokenUsageMiddleware` for one agent build (the session seam
    appends it to every stateful agent's middleware list)."""
    return TokenUsageMiddleware()


_LEDGER = UsageLedger()


def usage_ledger() -> UsageLedger:
    """The process-wide ledger singleton every agent records into."""
    return _LEDGER


__all__ = ["UsageLedger", "TokenUsageMiddleware", "usage_ledger",
           "usage_middleware"]
