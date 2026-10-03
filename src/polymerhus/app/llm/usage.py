"""The app-side token-usage ledger (`app/llm/usage.py`).

Every stateful agent records each model call's native `usage_metadata` here,
attributed to the calling agent and scoped by project. The accumulator is
PROCESS-WIDE and in-memory (it dies with the app process); the app API exposes
it read-only at `GET /projects/{id}/usage`, and the eval harness bounds a trial
by reading that endpoint.

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
    value = usage.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        return 0
    return value


class UsageLedger:
    """A process-wide, thread-safe token accumulator keyed by `(project_id, agent)`.

    Each entry holds `input_tokens`, `output_tokens`, `total_tokens`, and `calls`
    (all int). `record` is fail-open and a None/empty usage is a no-op; `snapshot`
    returns the project total plus the per-agent breakdown, excluding the
    `"unscoped"` bucket; `reset` clears all state (tests)."""

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
            input_tokens = _int_field(usage, "input_tokens")
            output_tokens = _int_field(usage, "output_tokens")
            total_tokens = (input_tokens + output_tokens
                            if "total_tokens" not in usage
                            else _int_field(usage, "total_tokens"))
            key = (project_id or _UNSCOPED, agent)
            with self._lock:
                entry = self._entries.get(key)
                if entry is None:
                    entry = {"input_tokens": 0, "output_tokens": 0,
                             "total_tokens": 0, "calls": 0}
                    self._entries[key] = entry
                entry["input_tokens"] += input_tokens
                entry["output_tokens"] += output_tokens
                entry["total_tokens"] += total_tokens
                entry["calls"] += 1
        except Exception:  # noqa: BLE001 - fail-open: never break the turn
            logger.warning("usage record failed; call left unaccounted",
                           exc_info=True)

    def snapshot(self, project_id: str) -> dict[str, Any]:
        """The project's cumulative total plus its per-agent breakdown. The
        `"unscoped"` bucket is never included; an unknown project returns
        zeros/empty."""
        total_tokens = 0
        calls = 0
        by_agent: dict[str, dict[str, int]] = {}
        with self._lock:
            for (pid, agent), entry in self._entries.items():
                if pid != project_id or pid == _UNSCOPED:
                    continue
                by_agent[agent] = dict(entry)
                total_tokens += entry["total_tokens"]
                calls += entry["calls"]
        return {"project_id": project_id, "total_tokens": total_tokens,
                "calls": calls, "by_agent": by_agent}

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
