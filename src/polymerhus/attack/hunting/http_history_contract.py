"""The ONE model-facing contract of the HTTP-history tool family (#196).

The `http-artifact/v1` filigree is bound at THREE agent seams, and each verb is
deliberately in the hands of the agent that can honour it:

  * `search_http_history` / `get_http_artifact` - the READ pair, bound on the
    hunter (`hunter_tools.build_hunter_tools`): inspection only, no execution.
  * `replay` - the EXECUTING verb, bound on the test-executor pod's runner
    (`pod/agents.runner_react_tools`): replaying a baseline is a pod act,
    because the pod is the only agent whose execution carries the lineage
    (`derived_from` / `replay_kind`) into the capture plane.

The hunter's orchestrator surface deliberately carries NONE of them (spec 3.4,
G3: exactly `hunts_store` / `notes` / `graph_view`) and the pod's triager
carries none either (D84-27: the critic never touches the target) - the split is
the design, not a missing binding.

Each verb's description is a CONTRACT the model can hold the tool to, and each
one rides the same minimal domain model, so the three views cannot describe
different worlds. The texts live HERE and are imported verbatim by both binders
(the #207 `QUERY_LIGHTRAG_DESCRIPTION` / #197 `graph_view` discipline): one
canonical source, no drift between the hunter's request tools body and the
pod's runner turn.

This module is pure text plus constants - it imports nothing and performs no
I/O (CODING_STANDARD section 6).
"""
from __future__ import annotations

# The minimal domain model, shared VERBATIM by all three descriptions: the
# vocabulary a model needs to read a row, judge replayability and interpret a
# lineage. It is deliberately a summary of `kali/http_history`'s record plus
# its sanitized projections (`sanitize_summary` / `sanitize_artifact`), never a
# second schema: the store stays the single source of truth for the shape.
_ARTIFACT_MODEL: str = (
    "Domain model (http-artifact/v1): one artifact is ONE immutable recorded "
    "transaction of this project, addressed by `artifact_id` (prefix `http_`). "
    "It carries `request` {method, url, headers, cookies, query, form}, "
    "`response` {status, reason, headers, cookies} or null when the exchange "
    "never completed, `connection` {tls, sni, alpn, protocol}, `timings`, and a "
    "per-body `capture_state` in none|captured|empty|omitted|truncated - only "
    "`captured` bytes are in the store and therefore replayable, and any other "
    "state carries the original size plus a `capture_reason`. The replay lineage "
    "is `derived_from` (the baseline's artifact_id) + `replay_kind` "
    "(baseline|mutated): a replayed exchange is a NEW artifact pointing at its "
    "baseline, never a mutation of it. Everything a model sees is a SANITIZED "
    "projection of that record: no body content ever, cookies and "
    "secret-bearing values are `[redacted]`, `source_ip` is excluded."
)

SEARCH_HTTP_HISTORY_DESCRIPTION: str = (
    "Search this project's recorded HTTP history. Filters are conjunctive "
    "{side, namespace, key, op, value}: side in request|response|connection|"
    "context|timing, namespace in core|header|cookie|query|form|body|tls, op in "
    "eq|contains|prefix|gte|lte|absent (`absent` = the transaction does NOT "
    "carry that key - it is how you build the control group). `text` is a "
    "free-text phrase match over the URL and textual body markers. `limit` is "
    "1..200 and paging is deterministic on (created_at, artifact_id): pass the "
    "returned `next_cursor` back to read the next page. Rows are sanitized "
    "summaries - artifact_id, project_id, created_at, method, url, host, status, "
    "status_class, http_version, request_size, response_size, timing_ms, tls, "
    "error_type, derived_from, replay_kind - and they are candidates, never a "
    "verification. Inspect one with `get_http_artifact`, then hand its "
    "artifact_id to the pod as `payload_vector_space.request_ref`: replay is the "
    "pod's job, never this tool's. A missing seam, an unavailable store or a "
    "rejected filter degrades to a denoted error object, never a raise. "
    + _ARTIFACT_MODEL
)

GET_HTTP_ARTIFACT_DESCRIPTION: str = (
    "Fetch ONE recorded transaction of this project by `artifact_id` - the "
    "inspection step of the chain. Use it before committing a candidate as "
    "`payload_vector_space.request_ref`, and read `request.body.capture_state` "
    "to decide whether the pod can replay it: only `captured` is replayable, "
    "while `omitted`/`truncated` means the bytes are not in the store (a "
    "baseline replay would have to send a bodyless request and is refused - "
    "declare an explicit `body` override to send a bodyless variant on purpose). "
    "You also get the lineage: `derived_from`/`replay_kind` say whether this is "
    "original target traffic or a replay. Header NAMES and non-sensitive header "
    "values are visible (sensitive ones are `[redacted]`); body content never "
    "is. The record carries `capture_context` {session_id, run_id, spec_id, "
    "variant_ref, exec_id, derived_from, replay_kind} - the join back to the "
    "run, spec and variant that captured it. A missing or cross-project id is "
    "`not_found` (never leaked), and a failure degrades to a denoted error, "
    "never a raise. " + _ARTIFACT_MODEL
)

REPLAY_HTTP_REQUEST_DESCRIPTION: str = (
    "Replay a recorded request by `artifact_id`, applying the declared "
    "deterministic overrides, and return the status observed for it. Use this "
    "when the spec's `payload_vector_space` carries `request_ref` instead of "
    "authoring a curl by hand: a hand-written curl carries no lineage (its "
    "`derived_from`/`replay_kind` stay null and the exchange looks like original "
    "target traffic). Overrides are a CLOSED data vocabulary - never a shell "
    "command, never an expression: `method`, `url`, `path`, `query` {name: "
    "value}, `header`/`headers` {name: value}, `remove_header`/`remove_headers` "
    "[name, ...], `cookie`/`cookies` {name: value}, `body`, `form` {name: value} "
    "(sets content-type form-urlencoded) and `json` (sets "
    "content-type application/json). A key outside that set is refused. The "
    "result is a NEW immutable artifact whose `derived_from` is the baseline and "
    "whose `replay_kind` is `baseline` (no overrides) or `mutated`. With no "
    "overrides you get the recorded baseline's status; with overrides you also "
    "get the new `artifact_id`. Fail-closed: a baseline whose recorded body is "
    "unavailable is refused (a replay never silently sends a bodyless request), "
    "and a reference that cannot be resolved returns a null status rather than a "
    "fabricated one. " + _ARTIFACT_MODEL
)

__all__ = [
    "GET_HTTP_ARTIFACT_DESCRIPTION",
    "REPLAY_HTTP_REQUEST_DESCRIPTION",
    "SEARCH_HTTP_HISTORY_DESCRIPTION",
]
