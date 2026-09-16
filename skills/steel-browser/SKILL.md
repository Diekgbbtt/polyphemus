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
  version: '1.2'
---

# Steel browser operation

Drive a real cloud browser through `steel_exec` - one `steel ...` command, or a whole `.sh`/`.py` script chaining several.
This skill carries operation mechanics, not a goal: no login procedure, no scraping recipe, only the framework any browser task composes.
Reach for it when a target needs JavaScript to render, an element driven, or client-side browser state read.

## The tool surface

`steel_exec` takes exactly one of `command` (a string carrying a `steel` token) or `script` with `script_lang` in `sh`/`py`.
Script text is not scanned, so a script owns its own timeout ordering and session-name uniqueness.
A refusal is typed and nothing runs (`returncode` 2): `refused:ambiguous-input`, `refused:not-steel-command`, `refused:steel-version-mismatch`, `refused:timeout-ordering`, `refused:unsupported-script-lang`, `refused:session-taken`.
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

**Operate.** Any web-interaction operation or client-side browser-state inspection: the command families below proxy to the CDP API. Choose each operation's shape:
- **single** - one atomic act whose result is the answer; no sequencing, no ref to discover.
- **batch** - several ops in one spawn that must share state (a discovered ref, an entered value).
- **wait** - when the page, not you, is the unknown; synchronise on an observable before reading it.
- **script** - a whole flow with a lifecycle, a loop, or several operations; it owns its stop.

**Close.** Stop the session with `steel browser stop --session <name> --json` when you own it, or let the stop owner fire, then prove it gone against the catalogue (`sessions --json` back to `[]`). Where the mount was write-oriented, that stop is what backs the profile up.

## Rules a decision can violate

**Refs**
- Take every ref and accessible name from the `snapshot -i` you just read; never from what a field is called in the source (a password field here is named `"Password input"`, not `"Password"`).
- Text entry (`fill`, `type`, `setvalue`) rides a `batch` whose first element is `snapshot -i`; standalone, CLI 0.4.4 answers `Unknown ref: eN`.
- Re-snapshot after every `navigate`. Within one document the ref registry is append-only, so an earlier ref still resolves; after a `navigate` the old ref no longer names its element - it answers `Unknown ref` until the new document's refs exist, then silently resolves to whatever now carries it.

**Reads**
- Project every read before it returns: a count, a slice, a named field, or a boolean. An unprojected `cookies`/`storage`/`snapshot`/`eval` dumps a whole jar, tree, or document into context.
- Print cookie and storage names and counts, never values, and never echo a text-entry command string; values are target secrets in flight.

**Shell**
- Single-quote every literal value fed through the shell; a trailing `$` or a backtick inside double quotes expands silently and submits the wrong value with no error. A runtime value rides a variable, interpolated as `"${VALUE}"` - expansion does not re-expand the contents, so only literals need the quotes.
- `eval` takes one inline JS expression - JS source, not a file path (a path parses as a regex literal). A proven snippet graduates to a script, which feeds it back through shell substitution.
- Validate before parsing `batch ... --json`; it is not guaranteed strict JSON (an embedded tree can carry a control character). On a parse failure, re-read a bounded slice rather than trust the frame.

**Synchronisation**
- Steel's `--timeout` (milliseconds) governs a wait; keep the tool `timeout_s` above it so the outer clock never cuts a wait short. `steel_exec` refuses a wait that reaches `timeout_s` (`refused:timeout-ordering`); on a bare CLI you enforce it.

**Lifecycle**
- Every session gets a stop owner. One script invocation owns it with `trap ... EXIT INT TERM`; a flow spanning separate calls arms a dead-man watchdog (`references/stop-owner.sh`) or wraps the calls in a stopping script.
- Stop by the name you own; never `stop --all`, which kills a foreign session (a foreign `default` may be live). `stop --json` returns only `stoppedSessions`; the catalogue is the liveness proof.

**State and gates**
- Clear a consent, region, or guest gate before snapshotting for refs; the gate's own click changes cookie and storage state, so take any pre-state baseline after it settles.
- Decide a state change on a UI signal plus a pre/post baseline, never on cookie names alone: `PHPSESSID` and `PrestaShop-<hash>` exist pre-login, and login changes their values, not their names.

## Command families

Every command carries `--session <name>` and `--json`.

- Session: `start [--session-timeout ms] [--stealth] [--proxy url] [--profile name] [--update-profile]`, `stop [-a]`, `sessions`, `live` (viewer).
- Navigation: `navigate <url> [--wait-until load|domcontentloaded|networkidle]` (aliases `open`, `goto`), `back`, `forward`, `reload`.
- Page reading: `snapshot [-i] [-c] [-s css] [-d n] [-u]`, `get text|html|value|attr|url|title|count|box|styles`, `find <css>`, `content`, `is visible|enabled|checked`.
- Interaction: `click`, `dblclick`, `press`, `hover`, `focus`, `check`, `uncheck`, `select`, `clear`, `selectall`, `scroll`, `scrollintoview`, `drag`, `upload`.
- Text entry (batch-routed): `fill`, `type`, `setvalue`.
- Waiting: `wait -t <text> | --selector <css> | -u <substr> | -f <js> | -l <load-state>` with `--timeout <ms>`.
- JS: `eval <js>`.
- Cookies and storage: `cookies [set|clear]`, `storage local|session [key] [set|clear]`.
- Batch: `batch "cmd" "cmd" ... [--bail]`.
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
- `references/scrape-page.sh` - one-shot `steel scrape` with a bounded slice.
- `references/spider-bounded.sh` - enumerate links, then fetch a capped same-host set.
- `references/profile-mount.sh` - mount a profile, settle, verify by navigation, persist on release.
