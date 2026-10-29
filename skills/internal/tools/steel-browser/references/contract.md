# Steel tool contract and platform records

This reference is the lookup table behind the `steel-browser` skill.
It describes the envelope the tools return, the session lifecycle rules, and the records the platform leaves behind.
It is not a runtime branch; every `steel` command keeps the same grammar.

## Tool envelope

`steel_exec` and `execute_command` return the legacy fields plus the contract fields:

| Field | Meaning |
|---|---|
| `stdout` / `stderr` | The command's real output, ANSI-stripped. |
| `returncode` | The authoritative result. When the guard reports an error, this is the error's rc. |
| `shell_returncode` | The composition's own rc when it differs from `returncode` (`xargs` 123, `|| true` 0). |
| `duration_ms` | Wall-clock duration. |
| `error` | The typed error object. It is authoritative over the rc and the text. |
| `warning` | A non-fatal classification, such as `empty_target`. |
| `steel_events` | One compact event per real Steel invocation the guard observed. |
| `exec_id` / `http_artifact_refs` / `capture_warning` | The HTTP-history capture provenance on `execute_command`. |

A `steel_events` entry carries:

- `verb`, `session`, `session_id`, `remaining_ms`;
- `decision` (`allow`, `deny`, `error`);
- `returncode`, `duration_ms`;
- `error` or `warning`;
- `catalogue` (`live`, `unavailable`, `not-required`).

The guard event is the reliable channel behind nested shells, scripts, pipes, and `|| true`.

## Error and recovery

| Code | Meaning | Fatal | Recovery |
|---|---|---|---|
| `unknown_session` | The name was never seen live. | No | `use_live`: choose a live name or start an owned session. |
| `session_missing` | The name was live and is now gone. | Yes | `recreate_session` with `requires_state_restore: true`. |
| `session_taken` | A `start` named a live session. | No | `use_live`: reuse it. |
| `target_lost` | The CDP target disappeared. | No | `tab_new`, then retry the read. |
| `browser_stuck` | The command exceeded its browser budget. | Yes | `recreate_session`. |
| `invalid_command` | The CLI rejected the grammar. | No | `fix_command`: fix the request; do not retry blindly. |
| `command_failed` | The execution surface raised before returning. | No | `inspect`. |
| `guard_error` | The guard itself failed. | Yes | `inspect`; surface it, do not patch in place. |

A known loss is not a typo.
A typo is not a loss.
Never auto-create a session to recover from either.
An operator-owned or pre-authenticated session cannot be recreated without restoring its state.

## Session lifecycle

- A session is a name, a runtime id, a clock, and browser state.
- `steel browser start` is create-time for the clock:
  - `--session-timeout` is the session window;
  - `--inactivity-timeout` is the idle window.
- Use a finite inactivity window such as `300000` (5 minutes) below a longer session window, or `86400000` below a longer session window for a 24-hour flow.
  A zero window was observed to release a session after the daemon's default idle period, despite the flag.
- The session timeout is the outer bound.
  An inactivity window at or above it has no effect and the CLI warns.
- The guard records a successful start immediately, with the runtime `session_id` and `remaining_ms`.
  A loss before the next catalogue query is therefore `session_missing`, not a typo.
- A `start` on a catalogued live name is refused before execution with `session_taken`.
  Do not rely on silent attach.
- The catalogue is `steel browser sessions --json`.
  `{"data":[]}` means no live session for this key.
- Every owned session gets a stop owner.
  Stop by name, then prove the catalogue clean.
  A foreign `default` session is untouchable.

## Platform records and replay

### What the runtime exposes

- Session metadata: `steel sessions list --json` and `steel sessions get --session <name> --json`.
  The record carries `id`, `status`, `createdAt`, `duration`, `eventCount`, `timeout`, viewer and debugger URLs, dimensions, and the user agent.
- Live viewer: `steel browser live --session <name> --json`.
  It returns the viewer URL. It is a live view, not a recording.
- Static evidence: `steel browser snapshot`, `steel browser screenshot`, and `steel browser diff snapshot|screenshot`.
  A screenshot is a file path. A diff carries `changed`, `additions`, and a unified diff.
- Multi-step results: `steel browser batch --session <name> --json -- "cmd" "cmd"`.
  The result is `{"data":{"results":[{"command","data","success"}]}}`.

### Live-view addressability

`viewerUrl` and `sessionViewerUrl` are resource attributes, not values to reconstruct.
A cloud viewer URL can name the session directly (`https://app.steel.dev/sessions/<id>`).
The self-hosted base can be shared and may not serve a page at all.
The working player is `debugUrl` (`/v1/sessions/debug`); it is shared and follows the active session.
Its cast WebSocket is `/v1/sessions/cast` and has no session id.

A view is addressable only when its URL carries the session id in a path segment or a query value.
Do not append `?sessionId=` or any other selector unless the runtime documents it.
`polymerhus.app.steel_session.SteelSession.live_view` makes this decision.
`SteelSessionRegistry` tracks the name, id, status, and view across start, catalogue, API, and stop observations.
The crawl provider returns the same object as `live_view`, next to the backward-compatible `viewer_url`.
Publish the session id next to the URL, and mark the shared player as active, not session-addressable.

### What the runtime does not expose here

`steel sessions logs`, `steel sessions agent-logs`, and `steel sessions traces` are advertised for cloud sessions.
Against the self-hosted runtime in this stack:

- `logs` and `agent-logs` return HTTP 404 for `/v1/sessions/<id>/logs` and `/agent-logs`;
- `traces` returns 404 for `/v1/sessions/<id>/agent-traces`;
- `traces` also rejects its advertised `--limit` flag.

Treat these as `not_found`, not as a session failure.
There is no video recording or recording-replay command in the pinned CLI.
Use metadata, the snapshot, the screenshot, and the diff as the session record.

### The stack's own traces

These are independent of the Langfuse exporter:

- Guard trace: one JSON event per Steel invocation, merged into `steel_events`.
  It records the true rc, the decision, the session, the catalogue fact, the start id, and the remaining lifetime.
- Session registry: a TTL-bounded name registry used to distinguish a typo from a known loss.
- HTTP history: `search_http_history`, `get_http_artifact`, `replay_http_request`, and `proxy_status`.
  It records project-scoped requests with `exec_id`, `run_id`, `spec_id`, `variant_ref`, `derived_from`, and `replay_kind`, and supports deterministic baseline or mutated replay.
- Checkpoints: LangGraph thread state in the configured checkpointer, including the message trail and structured responses.
- E2 evidence: the gateway summary, verdict, and checkpoint trace; the runtime scenario JSON.

Langfuse is one observability exporter.
It is not the only record and it is not the authoritative one for the tool contract.

## The binary boundary

The public command is `steel`.
The real CLI is private and must never be called by name or path.
The public `steel-real` name is a compatibility shim to the same wrapper.
A deliberate absolute path to the private core remains outside name-based enforcement; the supported surface is the public name.

## Canonical scripts

- `load-eval.py`: load a URL, wait, evaluate one JS expression or file, return bounded JSON.
- `select-elements.py`: select a DOM family, project tag, text, attributes, and visibility, return bounded JSON.
- `session-records.py`: fetch metadata, snapshot, screenshot, and the record probes that the runtime supports.
- `session-lifecycle.sh`: survey, open an owned name, use it, release under a trap.
- `catalogue.sh`, `navigate-read.sh`, `extract-reads.sh`, `eval-inline.sh`, `eval-interact.sh`, `interact-batch.sh`, `spider-bounded.sh`, `scrape-page.sh`, `stop-owner.sh`: the existing operation families.

The three canonical read scripts require a live session and never start or stop one.

A script that intentionally probes an optional endpoint may scope the trace for that one call by removing `KALI_STEEL_TRACE` from the child environment.
The guard still enforces the invocation, but the handled 404 does not override the script's own successful result in the outer tool envelope.
The script must report the handled error in its own JSON; `session-records.py` does this in `records`.
