---
name: steel-browser
description: >-
  Operate a real browser through three tools bound to this conversation:
  `browser_start`, `browser_exec`, and `browser_end`. Named durable sessions,
  navigation, ref-based interaction, waiting, inline JS, cookie and storage
  reads, and bounded multi-step flows.
  Use when a target needs JavaScript rendering, element-level interaction, a form
  or login flow driven end to end, session or token extraction, bot-gated
  navigation, or a live page read that plain HTTP cannot provide.
metadata:
  version: '3.0.0'
---

# Steel browser operation

Drive a real browser through three tools: `browser_start`, `browser_exec`, and `browser_end`.
They are bound to this conversation, and the conversation supplies the browser session.
This skill carries operation mechanics, not a goal: no login procedure, no scraping recipe, only the framework any browser task composes.
Reach for it when a target needs JavaScript to render, an element driven, or client-side browser state read.

## The tool surface

`browser_start(name, url=None)`
- Mounts a durable named session and optionally opens `url` as the first page.
- The name is the durable handle. A later start with the same name restores its cookies and localStorage.
- The result carries the name, the runtime session id, and warnings.
- A start while the name is already mounted answers `session_in_use`; reuse the mounted name instead.

`browser_exec(command)`
- Runs one browser command on the mounted session.
- The grammar is the browser command grammar without the session: `navigate https://app.test`, `snapshot -i`, `get text body`, `fill '#user' -- value`, `wait --selector '#app'`, `eval 1+1`, `batch -- "snapshot -i" "click @e1"`.
- `start`, `stop`, `sessions`, `live`, and `scrape` are refused, and so is every session or runtime flag.
- The command string is split like a shell, but no shell runs. Quote a value that contains a space or a shell-significant character.

`browser_end()`
- Captures cookies, localStorage, sessionStorage, and indexedDB; saves them under the name; stops the browser; releases the session.
- It is idempotent. Call it when the flow is done.

There is no status or owner tool. Do not look for one.

Every result is one envelope.
A success carries `success: true` and the command's `data`.
A failure carries `success: false` and `error: {code, message, retryable, recovery?}`.
Read the error code; it is authoritative.
`references/contract.md` carries the code and recovery table.

The name is `[A-Za-z0-9][A-Za-z0-9_-]{0,127}`.
Name a flow `polymerhus-<purpose>-<id>`.
Reuse the name when the flow continues; do not twin it.

## The path: start, operate, end

```
start -> OPERATE ... -> end
           |
        each operation takes a shape: single | batch | wait
```

**Start.** `browser_start("polymerhus-<purpose>-<id>")`.
Reuse the mounted name: call `browser_exec` rather than starting a twin.
A name is durable. After `browser_end`, a dropped conversation, or a server restart, start it again to restore cookies and localStorage.
sessionStorage and indexedDB are captured as evidence, not restored.
A start on a new name is a fresh browser context. It is not a new identity claim.

**Operate.** Any web-interaction operation or client-side browser-state read: the command families below are the taught subset, not an allowlist.
Choose each operation's shape:
- **single** - one atomic act whose result is the answer; no sequencing, no ref to discover.
- **batch** - several ops in one call to share state (a discovered ref, an entered value) or to save a round trip.
- **wait** - when the page, not you, is the unknown; synchronise on an observable before reading it.
  Wait on the challenge's OWN marker (its iframe or selector) with a bounded `--timeout`, then escalate: an outcome gated by an out-of-band human action (a CAPTCHA solve, an operator click, a manual approval) cannot appear until the human acts, so a wait on it burns its whole timeout first.

**End.** `browser_end()` when the flow is done.
The conversation close, the server shutdown, and the idle TTL also end the session.
An unended session is not a lost session: the end path captures it.
Do not issue a command after `browser_end`; the next call answers `no_session`.

## Rules a decision can violate

**Refs**
- Take every ref and accessible name from the `snapshot -i` you just read; never from what a field is called in the source.
- Give every variadic verb its `--` boundary: `<verb> [OPTIONS] <selector> -- <value>...` for `fill`, `type`, `setvalue`, `select`, and `upload` (each `[VALUE(S)]...`), and `batch [OPTIONS] -- "<cmd>" "<cmd>"...` for `batch` (`[COMMANDS]...`).
  The boundary sits where options end and positionals begin, never as a trailing terminator.
  The boundary is mandatory, not a nicety: these verbs are variadic, so the parser folds a flag that follows the first value token into the entered text behind `success:true`.
  Worked forms: `fill '#user-name' -- 'standard_user'`, `type '#user-name' -- 'standard_user'`, `setvalue '#user-name' -- 'standard_user'`.
  A flag-like value needs no special casing, only the boundary: `fill '#user-name' -- '-x'` types `-x` verbatim.
  Inside a `batch`, each element is its own command over the same grammar and carries its own boundary: `batch -- 'snapshot -i' 'fill @e6 -- 42'`.
  With the boundary declared, a ref and a CSS selector both resolve standalone, so `single` is valid; choose `batch` to share state or save a round trip, never as a workaround.
- `press` takes one key (a single character types, a multi-char string is a silent no-op behind `success:true`, and a modifier chord like `Control+a` does nothing), while the `selectall` verb is what selects.
- Re-snapshot after every `navigate`. Within one document the ref registry is append-only, so an earlier ref still resolves; after a `navigate` the old ref no longer names its element - it answers `Unknown ref` until the new document's refs exist, then silently resolves to whatever now carries it.
- Retry a `navigate` once on a transport failure (`ERR_HTTP_RESPONSE_CODE_FAILURE` with no flag involvement): it can fail transiently, and one retry is a sound default.

**Reads**
- Project every read before it returns - a count, a slice, a named field, or a boolean - since nothing caps a result for you (a 200000-character `eval` return arrives whole) and an unprojected `cookies`/`storage`/`snapshot`/`eval` dumps a whole jar, tree, or document into context.
- Print cookie and storage names and counts, never values, and never echo a text-entry command string; values are target secrets in flight.
- Prove a `select` by its read-back, never its echo, since a value matching no `<option>` still returns `{"selected":["zzz"]}` with `success:true` while the DOM lands on the first option (a `check`/`select` on a wrong-typed element likewise "succeeds" silently): read `get value` back and assert it equals the intended option, or pre-check the option with `eval`, and treat any mismatch as a failed select.

**Parsing**
- Quote every literal value that contains a space or a shell-significant character; the command string is split like a shell and never executed by one, so no expansion runs but a split still happens.
- `eval` takes one inline JS expression - JS source, not a file path (a path parses as a regex literal). A larger program is still one quoted expression or a `batch` of expressions.
- Drive a control from `eval` by setting each value with the events the page listens for (`input`, `change`), then invoking the control's own behaviour: `element.click()`, a dispatched pointer/mouse sequence, and `form.requestSubmit()` all honour submit handlers and native validation - prefer them (an empty `required` field under `requestSubmit()` fires exactly 2 `invalid` events, 0 `submit`, and no navigation, so the route is proven; while counting `invalid`, call `checkValidity()` in a separate measurement, since it fires its own) - while `form.submit()` and a framework `trigger("submit")` bypass both and are the last resort; a missing selector answers `{"data":null,"success":true}` (silent) and a thrown payload answers a typed evaluation error.
- Read `batch` line by line, because a failing batch has two shapes: an op-level failure writes the results envelope (line 1, carrying `data.results`) then a second `{"error":"One or more batch commands failed"}` line with exit 1, while a batch-level failure (a usage error) writes a single `{"error":...}` line with no results envelope and a usage error exits 2 with no stdout - so a whole-stdout parse dies on `Extra data`, line 1 carrying `data.results` is the structural discriminator, and `--bail` only decides how many ops run.
- Validate before parsing even a one-line success, which is not guaranteed strict JSON (an embedded tree can carry a control character), and re-read a bounded slice on a parse failure; no op-count ceiling appeared up to 100 ops (~22 s), so the browser clock is the bound.

**Synchronisation**
- A wait's `--timeout` (milliseconds) governs the wait; keep it below the caller's tool timeout so the outer clock never cuts a wait short.
- Submit once, then wait on the condition: a blind resubmit is an `AUTOMATION`-shaped bot signal, so read the outcome and escalate on the marker instead of clicking again.
- The session outlives a single call: a name started earlier is still mounted on the next call, and its cookies and localStorage survive an end on a later start.

**State and gates**
- Clear a consent, region, or guest gate before snapshotting for refs; the gate's own click changes cookie and storage state, so take any pre-state baseline after it settles.
- Decide a state change on a UI signal plus a pre/post baseline, never on cookie names alone: `PHPSESSID` and `PrestaShop-<hash>` exist pre-login, and login changes their values, not their names. Read the pre/post signal as a `get count` of the selector - presence and how many match, which a hidden twin cannot fool; reserve `is visible` for the distinct question of whether a specific first-matching element is shown. A surprising read is in-flight absence, not a stale value (a session whose start has not returned is legitimately missing), so re-read once before believing it.
- Pass `get count` a CSS selector, never a ref: it does not resolve refs and returns `count 0` for a ref or a missing selector alike, so a 0 means no CSS match.
- The authenticated-context oracle is a browser request to the recorded probe (`overview.auth_probe`): 2xx with no followed redirect passes, 401/403/3xx fails, anything else is indeterminate and never passes.
  A login redirect is a 3xx: it never passes, even when the browser follows it to a 200 page.
  A failed oracle is reduced coverage, never a silent authenticated flow.

**Evidence**
- `snapshot`, `screenshot`, and `diff` are the session record.
  The `browser_start` result carries the runtime session id; the `browser_end` result carries `captured`, `saved`, and `stopped`.
- There is no catalogue, status, live-view, logs, traces, or recording tool. Do not look for one.
  The stack keeps the records; this skill reads the page.

## Command families

Every command runs through `browser_exec`.

- Navigation: `navigate <url> [--wait-until load|domcontentloaded|networkidle]` (aliases `open`, `goto`), `back`, `forward`, `reload`. Settle on a condition (`wait --url`/`wait --text`) for a login or SPA page: `networkidle` never arrives on a continuously-active page and burns the whole timeout.
- Page reading: `snapshot [-i] [-c] [-s css] [-d n] [-u]`, `get text|html|value|attr|url|title|count|box|styles`, `find <css>`, `content`, `is visible|enabled|checked`.
- DOM family selection: `find <css>` returns `{elements:[{index,tagName,text,visible}], selector}`; for attributes or a larger projection, use `eval` with `querySelectorAll` and a bounded projection.
- Evidence: `screenshot [-o path] [--full-page] [--selector css]`, `diff snapshot --baseline <text|file>`, `diff screenshot --baseline <image>`.
- Interaction: `click`, `dblclick`, `press`, `hover`, `focus`, `check`, `uncheck`, `clear`, `selectall`, `scroll`, `scrollintoview`, `drag`.
- Variadic verbs (boundary mandatory, options before the `--`): text entry `fill`, `type`, `setvalue`; `select`; `upload`.
- Waiting: `wait -t <text> | --selector <css> | -u <substr> | -f <js> | -l <load-state>` with `--timeout <ms>`.
- JS: `eval <js>`.
- Cookies and storage: `cookies [set|clear]`, `storage local|session [key] [set|clear]`.
- Batch: `batch [OPTIONS] -- "cmd" "cmd" ...` (options such as `--bail` precede the `--`; each element carries its own boundary when variadic).
- Spidering: enumerate links with `eval`, `navigate` per link, both capped.

## References

- `references/contract.md` - the envelope, the error and recovery table, the durable state fields, and the auth oracle.
