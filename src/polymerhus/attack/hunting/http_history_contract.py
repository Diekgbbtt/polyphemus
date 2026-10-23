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

The baseline pointer is `provenance.baseline_ref` on the reduced D4 (T8, S5
8.5): the hunter names the recorded artifact in the spec provenance and the pod
replays it. The retired `payload_vector_space.request_ref` is gone from every
description, so a model can never re-learn the stale field.
"""
from __future__ import annotations

# The minimal domain model, shared VERBATIM by all three descriptions: the
# vocabulary a model needs to read a row, judge replayability and interpret a
# lineage. It is deliberately a summary of `kali/http_history`'s record plus
# its sanitized projections (`sanitize_summary` / `sanitize_artifact`), never a
# second schema: the store stays the single source of truth for the shape.
_ARTIFACT_MODEL: str = (
    "Domain model (http-artifact/v1): one immutable recorded transaction, "
    "addressed by `artifact_id` (prefix `http_`). It carries request, response, "
    "connection, timings, and a per-body `capture_state` "
    "(none|captured|empty|omitted|truncated); only `captured` is replayable. "
    "Lineage is `derived_from` + `replay_kind` (baseline|mutated); a replay is "
    "a NEW artifact, never a mutation. The model sees a sanitized projection: "
    "no body content, secrets `[redacted]`, `source_ip` excluded."
)

SEARCH_HTTP_HISTORY_DESCRIPTION: str = (
    "Search this project's recorded HTTP history. Filters are conjunctive "
    "{side, namespace, key, op, value}. side: request|response|connection|"
    "context|timing. namespace: core|header|cookie|query|form|body|tls. op: "
    "eq|contains|prefix|gte|lte|absent; `absent` means the transaction lacks "
    "the key, which builds the control group. `text` matches the URL and "
    "textual body markers. `side` and `namespace` are TWO DIFFERENT AXES; "
    "never put a namespace value in `side`. There is no `present` op; exclude "
    "`absent` instead. `value` is a string or number; `eq` does not accept "
    "booleans. A misspelled op, side, or namespace is `invalid_filter`, not an "
    "empty result. `limit` is 1..200; paging is deterministic on "
    "(created_at, artifact_id): pass `next_cursor` back. Inspect one with "
    "`get_http_artifact` and record its artifact_id in "
    "`provenance.baseline_ref`.\n"
    "Failures are in-band: `invalid_filter`, `not_found`, `corrupt_artifact`, "
    "`unavailable` or `http_history_failed` (missing evidence, never proof of an "
    "empty surface). Rows are candidate summaries: `artifact_id`, `method`, "
    "`url`, `status`, `request_size`, `response_size`, and non-null "
    "`derived_from`/`replay_kind`/`error`; `capture_state` is on "
    "`get_http_artifact`."
)

GET_HTTP_ARTIFACT_DESCRIPTION: str = (
    "Fetch ONE recorded transaction by `artifact_id`. Use it before naming a "
    "candidate as `provenance.baseline_ref`. Read "
    "`request.body.capture_state`: only `captured` is replayable; "
    "`omitted`/`truncated` means the bytes are not stored, and a bodyless "
    "replay is refused unless an explicit `body` override is declared. Lineage "
    "is `derived_from`/`replay_kind`. Header names and non-sensitive values are "
    "visible; secrets are `[redacted]` and body content is never shown. "
    "`capture_context` joins the run, spec, and variant. Missing or "
    "cross-project id -> `not_found`; unreadable record -> `corrupt_artifact`; "
    "failures are in-band."
)

REPLAY_HTTP_REQUEST_DESCRIPTION: str = (
    "Replay a recorded request by `artifact_id`, applying the declared "
    "deterministic overrides, and return the status observed for it. Use this "
    "when the spec's `provenance.baseline_ref` names a recorded baseline "
    "instead of authoring a curl by hand: a hand-written curl carries no "
    "lineage (its "
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
