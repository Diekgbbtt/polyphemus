# Steel tool contract and recovery

This reference is the lookup table behind the `steel-browser` skill.
It describes the envelope the three tools return, the error codes, the durable
state, and the authenticated-context oracle.
It is not a runtime branch; every browser command keeps the same grammar.

## Tool envelope

### `browser_start`

Success:

```json
{"success": true, "session": {"name": "polymerhus-flow-1", "session_id": "<runtime id>"}, "warnings": []}
```

The name is the durable handle.
The runtime id is informational and never a command argument.
A start on a name with a saved record restores its cookies and localStorage.
A start on a mounted name answers `session_in_use`.

### `browser_exec`

Success is the browser command's own envelope: `{"success": true, "data": ...}`.
`batch` returns the results envelope described below.
A command that ran and failed keeps its own failure envelope.
A command the tool refused, or a session-level failure, returns the error envelope.

### `browser_end`

Success:

```json
{"success": true, "ended": true, "reason": "explicit", "captured": true, "saved": true, "stopped": true, "released": null, "warnings": []}
```

- `ended` is false when no session was mounted; the call still succeeds.
- `reason` is `explicit`, `mcp_close`, `ttl`, or `shutdown`.
- `released` is `null` when the stop was enough, `true` when the stop failed and the API release fallback ran, and `false` when that fallback failed.
- `captured` and `saved` state whether the durable record was written.
- A failed capture or store save is a warning; it never blocks the stop.

## Error and recovery

A failure is one envelope:

```json
{"success": false, "error": {"code": "...", "message": "...", "retryable": true, "recovery": "..."}}
```

| Code | Meaning | Retryable | Recovery |
|---|---|---|---|
| `pool_exhausted` | No browser slot is free. | Yes | Wait for another flow to end, then retry. |
| `session_in_use` | The name is mounted by this conversation. | No | Use `browser_exec` on it, or `browser_end` and start again. |
| `no_session` | No session is mounted. | No | Call `browser_start` first. |
| `invalid_command` | The command grammar is wrong, or it names a refused verb or flag. | No | Fix the command; do not retry blindly. |
| `invalid_argument` | A start value is invalid, such as a name outside the rule. | No | Fix the name or the URL. |
| `browser_error` | The browser command raised. | Yes | Retry once, then end and start again; the end captures the state. |
| `capture_failed` | A state capture failed. | Yes | Retry the command, then end; the stop still runs. |
| `restore_failed` | The saved state could not be restored, so the session did not start. | No | Use a new name, or surface the defect; never claim the state was restored. |
| `store_error` | The durable store is unreadable or malformed. | No | Surface it; the operator fixes the store. |
| `pool_unavailable` | The browser service cannot reach a browser. | Yes | Retry later; surface a persistent failure. |
| `lease_error` | The session state machine rejected the call. | No | Surface it; do not patch around it. |
| `internal_error` | An unexpected failure. | Yes | Retry once, then surface it. |

A refusal is not a transient.
A typo is not a lost session.
Never start a replacement session to recover from a refusal.
Never stop a session this conversation did not mount.

## Durable state

- A session is a name, a runtime id, a clock, and browser state.
- Cookies and localStorage are restored by a later start with the same name.
- sessionStorage and indexedDB are captured as evidence and are not restored.
  Do not claim that a new start restored them.
- The store is written at the end and read at the next start.
  Never read, print, or paste a state file.
- The name is the access key. The state of one name is not visible to another.
- The idle TTL is the backstop when a conversation disappears without an end.

## Tool results and platform records

- `browser_start` returns the name, the runtime id, and warnings.
- `browser_end` returns the capture, save, stop, and release flags.
- `snapshot`, `screenshot`, and `diff` are the page evidence the tools return.
  A screenshot is a file path. A diff carries `changed`, `additions`, and a unified diff.
- Multi-step results: `batch -- "cmd" "cmd"` returns `{"data":{"results":[{"command","data","success"}]}}`.
- The stack separately records HTTP history, checkpoints, and run evidence.
  Those records outlive the call. They are not browser-session status.
- There is no status, catalogue, stop, live-view, logs, traces, recording, or scrape tool.
  A request for one is answered by the tool surface, not by this reference.

### Batch shape

A failing batch has two shapes:

- an op-level failure writes the results envelope on line 1 (carrying `data.results`) and a second line `{"error":"One or more batch commands failed"}` with exit 1;
- a batch-level failure writes a single `{"error":...}` line and no results envelope.

Line 1 carrying `data.results` is the structural discriminator.
`--bail` only decides how many ops run.

## The authenticated-context oracle

The auth store records one oracle: `overview.auth_probe.url`.
It is a deployment-neutral path such as `/api/authentication`; resolve it against the project's canonical origin.
A browser request to the resolved URL is the only authentication verdict:

- 2xx with no followed redirect: authenticated;
- 401, 403, or any 3xx: not authenticated;
- anything else: indeterminate, never a pass.

A navigation envelope is not the oracle: `navigate` follows a 302 and reports `success: true` with the final 200 URL, so a stale session looks alive.
Run the fetch from a page on the probe's origin; a cross-origin fetch without CORS is indeterminate, never a pass.
The oracle is a proof, not a cookie-name check and not a landing-page check.
