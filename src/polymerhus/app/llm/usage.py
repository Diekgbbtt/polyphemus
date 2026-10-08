"""The app-side token-usage ledger (`app/llm/usage.py`).

Every stateful agent records each model call's native `usage_metadata` here,
attributed to the calling agent and scoped by project. The accumulator is
PROCESS-WIDE and in-memory, backed by a DURABLE per-project record: each
`record` write-throughs the project's cumulative entries to `UsageStore`, and
the first use of a project in a process read-throughs that record back in, so a
project's spend survives a restart, a stop, or a drain (#326). The app API
exposes it read-only at `GET /projects/{id}/usage`, and the eval harness bounds
a trial by reading that endpoint.

The surface is a two-axis typed decomposition, not a scalar: `context_tokens`
(input) splits into `cached` (cache_read) and `uncached` (fresh input), and
`generated_tokens` (output) splits into `reasoning`
(output_token_details.reasoning) and `visible` (output minus reasoning). On the
pinned path `input_tokens` is INCLUSIVE of cache_read (LiteLLM's `prompt_tokens`
folds in cache_read and cache_creation; langchain_openai sets
`input_tokens = prompt_tokens`), so `uncached = input_tokens - cache_read`.

Two scalars ride the surface: `total_tokens` = context + generated (the raw
total, cache included), and `capped_tokens` = generated + uncached =
`total_tokens - cached` (generated output plus the fresh input it read,
excluding cache reads). The trial token budget counts `capped_tokens`
(generated + uncached input) - the real compute - and never cached input the
model re-read (#347), so cache reuse does not consume the budget. The axes are
recorded per call so a mostly-cache-read context is visible rather than folded
into one opaque input number (ticket F16).

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
from pathlib import Path
from typing import Any, Callable, Mapping

import yaml
from langchain.agents.middleware import AgentMiddleware, ModelRequest
from langchain_core.messages import AIMessage

from polymerhus.app.atomic_write import write_text_atomic
from polymerhus.app.data_root import DATA_ROOT, project_dir

logger = logging.getLogger(__name__)

_UNSCOPED = "unscoped"
"""The bucket for a record with no project id (None/blank). Never returned by a
project snapshot."""

_ENTRY_FIELDS = ("cached", "uncached", "reasoning", "visible", "total_tokens",
                 "capped_tokens", "calls")
"""Every field of one ledger entry. `calls` is the count; the rest accumulate."""

_AXIS_FIELDS = _ENTRY_FIELDS[:-1]
"""The accumulated (non-count) fields of one ledger entry."""


def _empty_entry() -> dict[str, int]:
    """A zeroed entry with every `_ENTRY_FIELDS` key."""
    return {field: 0 for field in _ENTRY_FIELDS}


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
    the trial budget axis (new output plus fresh input, excluding cache reads,
    #347); it is not the generated-only output axis.

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


class UsageStore:
    """The durable per-project usage record (#326).

    One YAML file per project under the app-owned data root, resolved through
    the one layout owner (`app.data_root.project_dir`):

        <data_root>/<project_id>/usage/usage.yaml

    The record holds the project's CUMULATIVE per-agent entry set and is
    rewritten wholesale (atomically, through `app.atomic_write`) on every
    persist - never appended to - so a resumed project cannot double-count.
    Reads are fail-open: a missing, unreadable, or non-mapping file degrades to
    `{}` (warned), never a raise. A write raises on I/O failure; the ledger
    swallows that (a persist never breaks an agent turn).
    """

    _BUCKET = "usage"
    _FILE = "usage.yaml"

    def __init__(self, root: str | Path | None = None) -> None:
        """Rooted under `root` (default: the app-owned `DATA_ROOT`,
        `<repo>/data/`); the explicit root is the tests' temp store."""
        self._root = Path(root) if root is not None else DATA_ROOT

    def _path(self, project_id: str) -> Path:
        return project_dir(project_id, self._BUCKET, root=self._root) / self._FILE

    def read(self, project_id: str) -> dict[str, dict[str, int]]:
        """The project's per-agent entries; a missing/unreadable/non-mapping
        record degrades to `{}` (warned, fail-open)."""
        path = self._path(project_id)
        if not path.exists():
            return {}
        try:
            body = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            logger.warning("usage store: unreadable record %s (%s)", path, exc)
            return {}
        if not isinstance(body, dict):
            logger.warning("usage store: non-mapping record %s degrades to empty", path)
            return {}
        agents = body.get("agents")
        if not isinstance(agents, dict):
            return {}
        entries: dict[str, dict[str, int]] = {}
        for agent, entry in agents.items():
            if isinstance(agent, str) and isinstance(entry, dict):
                entries[agent] = {field: _int_field(entry, field)
                                  for field in _ENTRY_FIELDS}
        return entries

    def write(self, project_id: str, entries: Mapping[str, Mapping[str, int]]) -> None:
        """Replace the project's record wholesale with `entries`, atomically."""
        body = {
            "project_id": project_id,
            "agents": {
                agent: {field: _int_field(entry, field) for field in _ENTRY_FIELDS}
                for agent, entry in entries.items()
            },
        }
        write_text_atomic(
            self._path(project_id), yaml.safe_dump(body, sort_keys=False))


class UsageLedger:
    """A process-wide, thread-safe token accumulator keyed by `(project_id, agent)`.

    Each entry holds the two-axis surface - `context_tokens` (`cached` +
    `uncached`) and `generated_tokens` (`reasoning` + `visible`) - plus the raw
    `total_tokens`, the `capped_tokens` budget axis, and `calls`. `record` is
    fail-open and a None/empty usage is a no-op; `snapshot` returns the project's
    aggregated surface plus the per-agent breakdown, excluding the `"unscoped"`
    bucket; `reset` clears all state (tests).

    With a `UsageStore` attached the ledger is DURABLE (#326): each `record`
    write-throughs the project's cumulative entries, the first use of a project
    read-throughs the durable floor into memory, and `flush`/`flush_all` persist
    on demand at a stop/drain/terminate boundary. A ledger with no store is pure
    in-memory.
    """

    def __init__(self, store: "UsageStore | None" = None) -> None:
        self._lock = threading.Lock()
        self._entries: dict[tuple[str, str], dict[str, int]] = {}
        self._loaded: set[str] = set()
        self._store = store

    def attach_store(self, store: "UsageStore | None") -> None:
        """Wire (or clear) the durable store.

        Production attaches the file store at app startup, before any turn.
        Attaching after records exists is safe: each already-recorded project
        read-throughs its durable floor ADDITIVELY, so the live records are
        never lost and a later persist cannot shrink the durable total."""
        with self._lock:
            self._store = store
            if store is None:
                return
            for project_id in {pid for (pid, _agent) in self._entries}:
                self._load_into_memory(project_id)

    def _load_into_memory(self, project_id: str) -> None:
        """Merge the durable floor for `project_id` into memory, once per
        process. Additive, so an attach after records cannot lose live records;
        normally memory is empty for the project and this is a plain seed. The
        caller holds `self._lock`."""
        if (self._store is None or not project_id
                or project_id == _UNSCOPED or project_id in self._loaded):
            return
        self._loaded.add(project_id)
        try:
            durable = self._store.read(project_id)
        except Exception:  # noqa: BLE001 - fail-open read
            logger.warning("usage ledger: durable read failed for %s (fail-open)",
                           project_id, exc_info=True)
            return
        for agent, entry in durable.items():
            key = (project_id, agent)
            current = self._entries.get(key)
            if current is None:
                self._entries[key] = dict(entry)
            else:
                for field in _ENTRY_FIELDS:
                    current[field] += entry[field]

    def _project_entries(self, project_id: str) -> dict[str, dict[str, int]]:
        """The project's in-memory entries, copied. The caller holds `self._lock`."""
        return {agent: dict(entry)
                for (pid, agent), entry in self._entries.items()
                if pid == project_id}

    def _persist(self, project_id: str) -> None:
        """Write-through the project's cumulative entries, fail-open. The caller
        holds `self._lock`."""
        if self._store is None:
            return
        try:
            self._store.write(project_id, self._project_entries(project_id))
        except Exception:  # noqa: BLE001 - fail-open: never break the turn
            logger.warning("usage ledger: persist failed for project %s (fail-open)",
                           project_id, exc_info=True)

    def record(self, project_id: str | None, agent: str,
               usage: Mapping | None) -> None:
        """Add one model call's usage. Fail-open: any malformed payload is logged
        and swallowed, never raised into the turn. A None/empty usage is a
        no-op (not even a call is counted). With a store attached, the touched
        project is write-through persisted (also fail-open)."""
        try:
            if not usage:
                return
            totals = _axis_totals(usage)
            key = (project_id or _UNSCOPED, agent)
            with self._lock:
                if project_id:
                    self._load_into_memory(project_id)
                entry = self._entries.get(key)
                if entry is None:
                    entry = _empty_entry()
                    self._entries[key] = entry
                for field in _AXIS_FIELDS:
                    entry[field] += totals[field]
                entry["calls"] += 1
                if project_id:
                    self._persist(project_id)
        except Exception:  # noqa: BLE001 - fail-open: never break the turn
            logger.warning("usage record failed; call left unaccounted",
                           exc_info=True)

    def snapshot(self, project_id: str) -> dict[str, Any]:
        """The project's aggregated two-axis surface plus its per-agent breakdown.
        The `"unscoped"` bucket is never included; an unknown project returns
        zeros/empty. With a store attached, the durable floor is read through on
        first use."""
        totals = {"cached": 0, "uncached": 0, "reasoning": 0, "visible": 0}
        total_tokens = 0
        capped_tokens = 0
        calls = 0
        by_agent: dict[str, dict[str, Any]] = {}
        with self._lock:
            self._load_into_memory(project_id)
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

    def flush(self, project_id: str) -> None:
        """Persist one project's cumulative entries (a stop/terminate boundary),
        fail-open. Loads the durable floor first, so a flush for a project this
        process never recorded re-persists its record rather than erasing it."""
        with self._lock:
            if not project_id or self._store is None:
                return
            self._load_into_memory(project_id)
            self._persist(project_id)

    def flush_all(self) -> None:
        """Persist every project this process holds in memory (a drain/shutdown
        boundary), fail-open."""
        with self._lock:
            if self._store is None:
                return
            for project_id in {pid for (pid, _agent) in self._entries
                               if pid != _UNSCOPED}:
                self._load_into_memory(project_id)
                self._persist(project_id)

    def reset(self) -> None:
        """Clear all state (tests), including a previously attached store, so a
        unit test that follows an app-startup wiring test starts memory-only."""
        with self._lock:
            self._entries.clear()
            self._loaded.clear()
            self._store = None


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


__all__ = ["UsageLedger", "UsageStore", "TokenUsageMiddleware", "usage_ledger",
           "usage_middleware"]
