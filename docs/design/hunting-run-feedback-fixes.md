# Hunting run feedback fixes

*Status: implemented on `fix/hunt-spec-contract-realign`.
Source run: white-jotter batched, 2026-10-24.*

## Skill evolver usage

The evolver called `arun_session_turn` without a `usage_scope`, so its spend landed in the unscoped bucket and bypassed the 7M cap.
`_default_turn_fn` now accepts `usage_scope`, and `arun_evolution_pass` passes the project id when the production turn is used.
The evolver's calls land under the `skill_evolver` role in `GET /projects/{id}/usage` with the same two-axis surface as every other agent.
An injected test turn keeps its own signature.

The 2026-10-24 run spent 122 evolver calls, 6.4M input, and about 1.07M capped tokens.
The output was five project-specific skill versions plus `authn`; the output stays, the spend is now metered.

## Notes and note: one tool

The pod's `note` tool and the hunter's `notes` tool were two names and two contracts.
The pod now binds the same `tool_contract.StoreNotesTool` implementation under the name `notes`.
The pod's typed fields (`order`, `kind`, `classification`, `symptom_status`, `parent_key`, `kb_primitives_used`, `exhaustion_evidence`) ride the shared field map.
The hunter and the modeller keep their own maps; the read/write algorithm is one.

The 128,813-character `note` response was a triager read with no filter: the old pod read returned every matching note body verbatim.
The unified read keeps the verbatim body but scopes it to the bound spec and exposes the typed filters.
A hard per-response cap on the notes read is the next step if a large note recurs.

## Auth store narrowing

The run made 44 `auth_store` reads.
Twenty-three were `view: full`, and they produced 1,509,358 of the 1,845,000 auth response characters (81.8%).
The full view dominated the 15.43M-token auth occupancy.

The fix:

- The read-only binding retires `view: full` with the coded `auth_full_view_retired`.
  The error teaches `fields` and the narrow paths.
- The default `summary` projects the overview to `login_endpoint`, `required_headers`, `mechanism`, `defences`, and a bounded note.
- A read over 12,000 characters returns its keys and a narrowing hint instead of the payload.
- The canonical minimal set is `overview.login_endpoint`, `overview.required_headers`, `overview.mechanism`, `accounts.<name>.credentials`, `accounts.<name>.tokens`, and `accounts.<name>.status`.

The writable binding keeps `full` for the operator and gateway paths; the response cap still applies.

## LightRAG fallback: a validator false positive

The run made 42 `query_lightrag` calls; 19 fell back.

| Gap | Calls |
|---|---:|
| `tool_or_stage4_request_present` | 18 |
| `not_json` | 1 |

The provider answered.
The old admission marker `\b(use|invoke|call|run|execute)\b.{0,32}\b(tool|function|command|agent)\b` rejected ordinary methodology prose such as "use the function to compare the ids".
The marker is now a protocol shape: `tool_call`, `function_call`, a JSON `name` of a real tool, "call the <name> tool", "stage 4".
A real tool request still fails; a legitimate answer is no longer laundered into the deterministic checklist.
The `not_json` case is a generation-format miss, not a provider outage.

## Tool mining

The four remaining feedback items are recorded in
`docs/experiments/white-jotter-batched-2026-10-24/TOKEN-USAGE-AND-CONTEXT-OCCUPANCY.md` section 11:

- `search_http_history`: 70 of 153 calls had no filter; the rest filter on the request URL/path, the method, the response status, `set-cookie`, `location`, and the session cookie.
- `exec`: 389 of 587 calls are curl, 82 are inline Python; the median response is 444 characters; one batched inline Python probe is the concise convention.
- `graph_view`: 132 of 135 calls are narrow, 3 are broad, 5 returned no rows; the query shape is healthy.
- `query_lightrag`: the fallback root cause is the validator, not the provider.

The raw mining scripts and JSON are in the same directory:
`mine_run_feedback.py`, `run_feedback.json`, `mine_auth_store.py`, `auth_store_usage.json`.
