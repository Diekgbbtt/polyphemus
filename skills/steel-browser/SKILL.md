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
  version: '1.0'
---

# Steel browser operation

Drive a real cloud browser through the `steel_exec` tool: one `steel ...` command, or a whole `.sh` automation script chaining several commands.
This skill owns the operation mechanics - session lifecycle, the ref flow, batch-routed text entry, waiting, JS evaluation, extraction, scraping, spidering, and profiles.
The canonical login procedures written in these mechanics belong to the auth skill; this skill carries the mechanics alone.

## The tool contract

`steel_exec` accepts exactly one of two inputs:

- `command`: a `steel ...` command string, routed on a `steel` token.
- `script` plus `script_lang` in `{"sh", "py"}`: a whole automation script, written verbatim to a unique file under `/work/{session_id}` and run there.

The tool's own contract, quoted verbatim:

```
Run a steel CLI command or automation script in /work/{session_id} and
return the unchanged {stdout, stderr, returncode, duration_ms} envelope.
Exactly one of command/script; commands must carry the steel token.
Guards, in order: pinned steel version re-check; longest steel --timeout
must sit below timeout_s (default 600, steel clock authoritative); a
command-mode start on a live name is refused with `<name> is already
used`. Scripts carry timeout ordering and unique names by skill
construction and are never scanned.
```

Every call returns the unchanged `{stdout, stderr, returncode, duration_ms}` envelope with ANSI stripped, run with `cwd` `/work/{session_id}`.
Typed refusals (`returncode` 2, nothing executed): `refused:ambiguous-input`, `refused:not-steel-command`, `refused:steel-version-mismatch`, `refused:timeout-ordering`, `refused:unsupported-script-lang`, `refused:session-taken` (`<name> is already used`).
Two duties this contract leaves to the script: because script text is not scanned, the script's own timeout ordering and its session-name uniqueness are the skill's to hold.

## Workflow

1. Prove a session name free, then open it.
Name sessions semantically: `polymerhus-<flow>-<id>`.
`steel browser live --session <name> --json` reports `success: true` iff the name is TAKEN; the typed `No running session` error means free (the tool reads that same `success` field before it lets a command-mode `start` through).
Open with `steel browser start --session <name> --session-timeout 600000 --json`.
Observable: the oracle reads free before `start`; the start JSON carries your chosen name.

2. Arm the trap on every multi-op script.
The script owns its stop: `trap release EXIT INT TERM`, where `release` runs `steel browser stop --session <name> --json` iff the script started it.
Observable: `steel browser live --session <name>` reports free after the run, on the success, error, and signal paths alike.

3. Navigate, then confirm where you are.
`steel browser navigate <url> --wait-until domcontentloaded --json` returns `{title, url}`.
Observable: the returned `url` is the target you asked for.

4. Snapshot for refs, then act in one batch.
`steel browser snapshot -i --json` returns element refs (`@eN`).
Route all text entry (`fill`, `type`, `setvalue`) through a `batch` whose first element is `snapshot -i`; a standalone `fill` returns `Unknown ref: eN` on CLI 0.4.4.
Refs hold for the act that immediately follows and never across a `navigate`.
Observable: the batch result carries `success:true` for the act; read the value back to confirm the entry landed.

5. Wait on the observable with steel's clock.
`steel browser wait -t "<text>" --timeout <ms>` (also `--selector`, `-u`, `-f`, `-l`).
Steel's `--timeout` governs the wait; keep the tool `timeout_s` above it (default 600 s) and the agent call budget above that.
Observable: `wait` succeeds, or returns the typed timeout error - never a hang past `--timeout`.

6. Bound every read.
`cookies`, `storage local|session`, `get url`, and `eval` are the extraction reads.
Project before return: aim every read at a count, a slice, a targeted selector, or a boolean.
`eval` runs inline, with the escaping patterns and the bounding rule in `references/eval-inline.sh`; a proven snippet graduates into `/work/<session_id>/js/` and is fed back through shell substitution inside a script.
Observable: each read returns a count, a slice, a boolean, or a named field.

7. Close and prove it.
The script trap is the stop; a session opened by direct command stops with `steel browser stop --session <name>`.
`steel browser sessions` reads empty while a session is provably live, so prove liveness with the `live` oracle and stop by name only - `stop --all` would kill foreign sessions (a foreign `default` may be live).
Observable: `steel browser live --session <name>` reports free after the flow.

8. Mount profiles with settle-then-verify.
`steel browser start --session <name> --profile <profile> --json` mounts read-only; add `--update-profile` to accumulate state.
No CLI state poll exists (`steel profile list` returns name plus id only), so settle, then prove the mount by a navigation.
Release (`stop`) is the persistence call, and one live session per profile holds the last writer.
Observable: a post-mount navigation succeeds before any verdict; the release runs on every path.

## Command families

Every command takes `--session <name>`; pass `--json` on every call.

- Session: `start [--session-timeout ms] [--stealth] [--proxy url]`, `stop`, `sessions`, `live`.
- Navigation: `navigate <url> [--wait-until load|domcontentloaded|networkidle]` (aliases `open`, `goto`), `back`, `forward`, `reload`.
- Page reading: `snapshot [-i] [-c] [-d n] [-s css]`, `get text|html|value|attr|url|title|count|box|styles`, `find <css>`, `content`, `is visible|enabled|checked`.
- Interaction: `click`, `dblclick`, `press`, `hover`, `focus`, `check`, `uncheck`, `select`, `clear`, `selectall`, `scroll`, `scrollintoview`, `drag`, `upload`.
- Text entry (batch-routed): `fill`, `type`, `setvalue`.
- Waiting: `wait -t <text> | --selector <css> | -u <substr> | -f <js> | -l <load-state: load|domcontentloaded|networkidle>` with `--timeout <ms>`.
- JS: `eval <js>`.
- Cookies and storage: `cookies [set|clear]`, `storage local|session [get|set|clear]`.
- Batch: `batch "cmd" "cmd" ... [--bail]`.
- One-shot scraping: `steel scrape <url> [--format markdown|html|readability|cleaned_html] [--screenshot] [--pdf] [--use-proxy]`.
- Spidering: `eval` to enumerate links, `navigate` per link, both bounded.
- Profiles: `steel profile list`; mount via `start --profile <name> [--update-profile]`.

## References

Runnable operation scripts beside this skill, each self-guarding (name oracle, exit trap, bounded output) and runnable verbatim through `steel_exec(script, script_lang="sh")` or `bash <file>`.

- `references/session-lifecycle.sh` - open, use, and release a session with the oracle and the trap.
- `references/navigate-read.sh` - navigate, then read title, URL, and a compact tree slice.
- `references/interact-batch.sh` - snapshot-then-act text entry inside one batch, with an explicit wait.
- `references/extract-reads.sh` - bounded cookie, storage, URL, and eval reads.
- `references/eval-inline.sh` - the inline-JS escaping patterns and the result-bounding rule.
- `references/scrape-page.sh` - one-shot `steel scrape` with a bounded slice.
- `references/spider-bounded.sh` - enumerate links, then fetch and parse a capped same-host set.
- `references/profile-mount.sh` - mount a profile, settle, and verify by navigation.

## Traps that cost a flow

- `Unknown ref: eN`: the ref expired; take a fresh `snapshot -i` and act in the same batch.
- `No running session`: the oracle's free verdict, or a session that died; open a fresh semantic name.
- Target secrets (cookie values, tokens, password values) stay out of stdout; print cookie and storage names and counts.
- `steel --timeout` is the authoritative wait clock; keep the tool `timeout_s` above it so the tool clock never cuts a wait short.
