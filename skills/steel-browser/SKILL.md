---
name: steel-browser
description: >-
  Operate a real Steel cloud browser through the `steel_exec` gateway: named
  sessions, navigation, ref-based interaction, waiting, inline JS, cookie and
  storage reads, one-shot scraping, bounded spidering, and profile mounts.
  Use when a target needs JavaScript rendering, element-level interaction, a form
  or login flow driven end to end, session or token extraction, bot-gated
  navigation, or a live page read that plain HTTP cannot provide.
metadata:
  version: '1.6'
---

# Steel browser operation

Drive a real cloud browser through `steel_exec` - one `steel ...` command, or a whole `.sh`/`.py` script chaining several.
This skill carries operation mechanics, not a goal: no login procedure, no scraping recipe, only the framework any browser task composes.
Reach for it when a target needs JavaScript to render, an element driven, or client-side browser state read.

## The tool surface

`steel_exec` takes exactly one of `command` (a string carrying a `steel` token) or `script` with `script_lang` in `sh`/`py`.
Script text is not scanned, so a script owns its own timeout ordering, session-name uniqueness, and variadic boundary.
A refusal is typed and nothing runs (`returncode` 2): `refused:ambiguous-input`, `refused:not-steel-command`, `refused:steel-version-mismatch`, `refused:timeout-ordering`, `refused:unsupported-script-lang`, `refused:session-taken`, `refused:variadic-boundary`.
Fix the input and reissue; a refusal is not a transient to retry.
On a bare CLI you hold the same guards yourself.

## The path: survey, open, mount, operate, close

A spine with an open middle - pick the path the goal needs, not a fixed sequence.

```
survey -> open or reuse -> [mount a profile] -> OPERATE ... -> close
                                                    |
                       each operation takes a shape: single | batch | wait | script
```

**Survey.** `steel browser sessions --json` lists every live session this key owns as `{id, mode, name, status, viewerUrl}`, and `{"data":[]}` when none is live. `steel profile list --json` lists profiles as `{name, profileId}`. Read both before opening anything.

**Open, or reuse.** A live session's name is already addressable, so reuse one rather than start a twin. Otherwise `steel browser start --session <name> --session-timeout 600000 --json`, naming it `polymerhus-<flow>-<id>`.
`start` silently attaches to a live name, so check the catalogue first: `steel_exec` refuses a command-mode start on a catalogued name with `<name> is already used`, and a script holds its own check.
`remainingMs` on receipt sits below what you asked for - provisioning spends the session clock.

**Mount a profile (optional).** `start --profile <name>` mounts server-side identity and state; read-only by default, `--update-profile` accumulates it back on release. There is no state-poll primitive, so prove a mount with a settle pause then a navigation - an unverified mount never passes a verdict. One live session per profile holds the last writer.

**Operate.** Any web-interaction operation or client-side browser-state inspection: the command families below proxy to the CDP API, and they are the taught subset, not an allowlist - `steel_exec` routes on the `steel` token, so any `steel browser` subcommand runs. Choose each operation's shape:
- **single** - one atomic act whose result is the answer; no sequencing, no ref to discover.
- **batch** - several ops in one spawn to share state (a discovered ref, an entered value) or amortise spawn cost.
- **wait** - when the page, not you, is the unknown; synchronise on an observable before reading it.
- **script** - a whole flow with a lifecycle, a loop, or several operations; it owns its stop.

**Close.** Stop the session with `steel browser stop --session <name> --json` when you own it, or let the stop owner fire, then prove it gone against the catalogue (`sessions --json` back to `[]`). Where the mount was write-oriented, that stop is what backs the profile up.

## Rules a decision can violate

**Refs**
- Take every ref and accessible name from the `snapshot -i` you just read; never from what a field is called in the source.
- Give every variadic verb its `--` boundary: `steel browser <verb> [OPTIONS] <selector> -- <value>...` for `fill`, `type`, `setvalue`, `select`, and `upload` (each `[VALUE(S)]...`), and `steel browser batch [OPTIONS] -- "<cmd>" "<cmd>"...` for `batch` (`[COMMANDS]...`).
  The boundary sits where options end and positionals begin - never a trailing terminator: `[OPTIONS]` are `--flag[ value]` tokens, then the one required `<selector>` (where the verb has one), then the `--`, then the value(s) - taken verbatim, joined with spaces, and never reinterpreted as an option.
  The boundary is mandatory, not a nicety: these verbs are variadic, so clap swallows a flag that follows the first value token and folds it into the entered text behind `success:true` - a trailing `--session` folds the same way and drops the verb onto an auto-provisioned billable `default` session, answering `Unknown ref: eN` or `Element not found: <css>` that read as a resolution defect.
  `steel_exec` refuses a variadic command with no top-level `--` (`refused:variadic-boundary`) instead of guessing where the boundary is, so encode the boundary and the fold cannot happen.
  Worked forms: `steel browser fill --session S --json '#user-name' -- 'standard_user'`, `steel browser type --session S --json '#user-name' -- 'standard_user'`, `steel browser setvalue --session S --json '#user-name' -- 'standard_user'`.
  A flag-like value needs no special casing, only the boundary: `steel browser fill --session S --json '#user-name' -- '-x'` types `-x` verbatim.
  Inside a `batch`, each element is its own command over the same grammar and carries its own boundary: `steel browser batch --session S --json -- 'snapshot -i' 'fill @e6 -- 42'`.
  With the boundary declared, a ref and a CSS selector both resolve standalone, so `single` is valid - choose `batch` to share state or save a spawn, never as a workaround.
- `press` takes one key (a single character types, a multi-char string is a silent no-op behind `success:true`, and a modifier chord like `Control+a` does nothing), while the `selectall` verb is what selects.
- Re-snapshot after every `navigate`. Within one document the ref registry is append-only, so an earlier ref still resolves; after a `navigate` the old ref no longer names its element - it answers `Unknown ref` until the new document's refs exist, then silently resolves to whatever now carries it.
- Retry a `navigate` once on a transport failure (`ERR_HTTP_RESPONSE_CODE_FAILURE` with no flag involvement): it can fail transiently, and one retry is a sound default.

**Reads**
- Project every read before it returns - a count, a slice, a named field, or a boolean - since nothing caps a result for you (a 200000-character `eval` return arrives whole) and an unprojected `cookies`/`storage`/`snapshot`/`eval` dumps a whole jar, tree, or document into context.
- Print cookie and storage names and counts, never values, and never echo a text-entry command string; values are target secrets in flight.
- Prove a `select` by its read-back, never its echo, since a value matching no `<option>` still returns `{"selected":["zzz"]}` with `success:true` while the DOM lands on the first option (a `check`/`select` on a wrong-typed element likewise "succeeds" silently): read `get value` back and assert it equals the intended option, or pre-check the option with `eval`, and treat any mismatch as a failed select.

**Shell**
- Single-quote every literal value fed through the shell; a trailing `$` or a backtick inside double quotes expands silently and submits the wrong value with no error; a runtime value rides a variable, interpolated as `"${VALUE}"`, which never re-expands its contents; a single-quoted `eval` payload obeys the same rule, and its `success:true` is no proof of arrival - a shell-mangled payload still reports success with a wrong result, so read the returned data, not the envelope.
- `eval` takes one inline JS expression - JS source, not a file path (a path parses as a regex literal). A proven snippet graduates to a script, which feeds it back through shell substitution.
- Drive a control from `eval` by setting each value with the events the page listens for (`input`, `change`), then invoking the control's own behaviour: `element.click()`, a dispatched pointer/mouse sequence, and `form.requestSubmit()` all honour submit handlers and native validation - prefer them (an empty `required` field under `requestSubmit()` fires exactly 2 `invalid` events, 0 `submit`, and no navigation, so the route is proven; while counting `invalid`, call `checkValidity()` in a separate measurement, since it fires its own) - while `form.submit()` and a framework `trigger("submit")` bypass both and are the last resort; a missing selector answers `{"data":null,"success":true}` (silent) and a thrown payload answers a typed evaluation error.
- Read `batch ... --json` line by line, because a failing batch has two shapes: an op-level failure writes the results envelope (line 1, carrying `data.results`) then a second `{"error":"One or more batch commands failed"}` line with exit 1, while a batch-level failure (a usage error, an empty session name) writes a single `{"error":...}` line with no results envelope and a clap usage error exits 2 with no stdout - so a whole-stdout parse dies on `Extra data`, line 1 carrying `data.results` is the structural discriminator, and `--bail` only decides how many ops run.
- Validate before parsing even a one-line success, which is not guaranteed strict JSON (an embedded tree can carry a control character), and re-read a bounded slice on a parse failure; no op-count ceiling appeared up to 100 ops (~22 s), so the session clock is the bound.

**Synchronisation**
- Steel's `--timeout` (milliseconds) governs a wait; keep the tool `timeout_s` above it so the outer clock never cuts a wait short. `steel_exec` refuses a wait that reaches `timeout_s` (`refused:timeout-ordering`); on a bare CLI you enforce it.

**Lifecycle**
- Every session gets a stop owner. One script invocation owns it with `trap ... EXIT INT TERM`; a flow spanning separate calls arms a dead-man watchdog (`references/stop-owner.sh`) or wraps the calls in a stopping script.
- Mark the session name before `start` (after the catalogue guard, so a foreign name is never addressed) and let the trap attempt the named stop whenever that mark is set, never on a flag set only after `start` returns: a signal landing inside the `start` window otherwise skips the stop and orphans the session, while a stop on a name that never started is a harmless no-op.
- A command that resolves `--session` to an empty or missing name auto-provisions a live `default` session that persists and bills until its session or idle clock expires; a `default` present before your call is foreign and untouchable, while one that appeared because of your call is yours and must be stopped by name, so compare the pre-call catalogue.
- Stop by the name you own, which leaves a foreign `default` alive (`stop --all` kills it). `stop --json` returns only `stoppedSessions`; the catalogue is the liveness proof.

**State and gates**
- Clear a consent, region, or guest gate before snapshotting for refs; the gate's own click changes cookie and storage state, so take any pre-state baseline after it settles.
- Decide a state change on a UI signal plus a pre/post baseline, never on cookie names alone: `PHPSESSID` and `PrestaShop-<hash>` exist pre-login, and login changes their values, not their names. Read the pre/post signal as a `get count` of the selector - presence and how many match, which a hidden twin cannot fool; reserve `is visible` for the distinct question of whether a specific first-matching element is shown. A surprising read is in-flight absence, not a stale value (a session whose `start` has not returned is legitimately missing), so re-read once before believing it.
- Pass `get count` a CSS selector, never a ref: it does not resolve refs and returns `count 0` for a ref or a missing selector alike, so a 0 means no CSS match.

## Command families

Every `steel browser` command carries `--session <name>`; every command in this skill carries `--json`.
The `steel scrape` and `steel profile` families are sessionless and carry only `--json`.

- Session: `start [--session-timeout ms] [--inactivity-timeout ms] [--stealth] [--proxy url] [--profile name] [--update-profile]`, `stop [-a]`, `sessions`, `live` (viewer).
- Navigation: `navigate <url> [--wait-until load|domcontentloaded|networkidle]` (aliases `open`, `goto`), `back`, `forward`, `reload`.
- Page reading: `snapshot [-i] [-c] [-s css] [-d n] [-u]`, `get text|html|value|attr|url|title|count|box|styles`, `find <css>`, `content`, `is visible|enabled|checked`.
- Interaction: `click`, `dblclick`, `press`, `hover`, `focus`, `check`, `uncheck`, `clear`, `selectall`, `scroll`, `scrollintoview`, `drag`.
- Variadic verbs (boundary mandatory, options before the `--`): text entry `fill`, `type`, `setvalue`; `select`; `upload`.
- Waiting: `wait -t <text> | --selector <css> | -u <substr> | -f <js> | -l <load-state>` with `--timeout <ms>`.
- JS: `eval <js>`.
- Cookies and storage: `cookies [set|clear]`, `storage local|session [key] [set|clear]`.
- Batch: `batch -- "cmd" "cmd" ... [--bail]` (options before the `--`; each element carries its own boundary when variadic).
- One-shot scraping (no session): `steel scrape <url> [--format html|readability|cleaned_html|markdown] [--pdf] [--screenshot] [--use-proxy]`.
- Spidering: enumerate links with `eval`, `navigate` per link, both capped.
- Profiles: `steel profile list|import|sync|delete`; mount through `start --profile`.

## References

Runnable scripts beside this skill; each is self-guarding, `--json`, bounded output, and runs verbatim through `steel_exec(script, script_lang="sh")` or `bash <file>`.

- `references/catalogue.sh` - list live sessions and profiles; the survey read.
- `references/session-lifecycle.sh` - survey, open a free name, use it, release under a trap, prove the catalogue clean.
- `references/stop-owner.sh` - arm or defuse a dead-man watchdog for a flow that spans separate calls.
- `references/navigate-read.sh` - navigate, then read title, URL, and a compact tree slice.
- `references/interact-batch.sh` - snapshot-then-act text entry in one batch, with a boolean read-back.
- `references/extract-reads.sh` - bounded cookie, storage, and eval reads.
- `references/eval-inline.sh` - inline-JS escaping patterns and the projection rule.
- `references/eval-interact.sh` - one form submission from `eval` (values plus events, then a chosen JS route), with a boolean read-back and one summary line.
- `references/scrape-page.sh` - one-shot `steel scrape` with a bounded slice.
- `references/spider-bounded.sh` - enumerate links, then fetch a capped same-host set.
- `references/profile-mount.sh` - mount a profile, settle, verify by navigation, persist on release.
