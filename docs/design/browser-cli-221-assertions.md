# Assertions - browser capability via Steel CLI (#221)

**Source:** `docs/design/browser-cli-221-spec.md` (the just-exec design), per `docs/design/browser-cli-221-decisions.md` (D11-D19 binding; D1/D4/D5 retired, D2/D6/D10/D13 amended).
**Seams under assertion:** the `steel_exec` gateway tool (routing, guards, envelope), the eager kali delivery (postrun install plus compose credential wiring), the shared skill loader and the catalogue conformance sweep, and the `steel-browser` skill's operation references.
**Retired with the rulings:** the earlier redaction, eleven-tool-factory, always-present-session-flag, and stop-on-failure predicates asserted a seam design (allowlist plus redaction plus context-manager lifecycle) that D1/D4/D5/D11 replaced; no assertion below depends on it.

## Contract predicates (unit, host-side)

C1 - Command routing refusals.
Given `steel_exec` at the tool-function seam, exercising the routing semantic, the tool yields typed refusals (`returncode` 2, nothing executed) for a command carrying no `steel` token, for both-inputs and neither-input, and for an unsupported `script_lang`.
Yields `tests/test_steel_exec.py::test_non_steel_command_refused_never_executed`, `::test_ambiguous_inputs_refused_never_executed`, `::test_steel_substring_without_token_refused`, `::test_py_script_runs_and_bad_lang_refused`.

C2 - Pinned-CLI guard.
Given a `steel --version` probe that does not name the 0.4.4 pin, exercising the delivery-honesty semantic, the tool yields `refused:steel-version-mismatch` and runs nothing.
Yields `tests/test_steel_exec.py::test_stale_steel_version_refused_never_executed`.

C3 - Timeout ordering.
Given a command whose longest steel `--timeout` reaches or exceeds the tool `timeout_s` (default 600), exercising the D11 semantic (steel clock authoritative), the tool yields `refused:timeout-ordering`; a `--session-timeout` (a session lifetime) never triggers it.
Yields `tests/test_steel_exec.py::test_tool_timeout_defaults_to_600`, `::test_steel_wait_within_budget_proceeds`, `::test_steel_wait_exceeding_budget_refused_never_executed`, `::test_session_lifetime_is_not_a_wait`.

C4 - Session-name uniqueness.
Given a command-mode `browser start` on a name the live session catalogue reports, exercising the D13 semantic, the tool yields `refused:session-taken` carrying `<name> is already used` and never starts; on a free name it proceeds; an unreadable catalogue fails open.
Yields `tests/test_steel_exec.py::test_taken_session_name_refused_with_name`, `::test_free_session_name_proceeds_to_start`, `::test_guard_only_watches_command_mode_starts`, `::test_unreadable_catalogue_fails_open`.

C5 - Envelope shape is unchanged.
Given any run (success, shell error, malformed output), exercising the envelope semantic, the tool yields exactly `{stdout, stderr, returncode, duration_ms}` with ANSI stripped, and a script run writes its file verbatim into the session workdir.
Yields `tests/test_steel_exec.py::test_steel_command_passes_through_with_envelope`, `::test_sh_script_written_verbatim_then_run`, `::test_py_script_runs_and_bad_lang_refused`.

C6 - Eager kali delivery.
Given the repo at rest, exercising the delivery semantic, `kali/postrun.sh` pins v0.4.4 with both arch checksums and installs best-effort/idempotently, and the kali service is the only place `STEEL_API_KEY` is wired, with no key value in the repo.
Yields `tests/test_steel_cli_delivery.py` (five static pin/wiring assertions).

C7 - Skill data-section conformance.
Given `skills/steel-browser/SKILL.md`, exercising the catalogue semantic, `validate_skill` reports zero violations and the sweep over every `skills/*/SKILL.md` stays green.
Yields `tests/recon/test_skill_data_section.py::test_every_repo_skill_conforms_to_data_section`.

C8 - Skill resolves through the one loader.
Given `skill_for("steel-browser")` and `render_skill_index(["steel-browser"])`, exercising the single-loader semantic, the body returns non-empty with frontmatter stripped and the index renders the name-plus-description line.
Yields `tests/recon/test_skills.py` plus the runner one-liner recorded in the PR body.

C9 - Variadic boundary.
Given a command-mode invocation of a variadic verb (`fill`, `type`, `setvalue`, `select`, `upload`, `batch`) without a top-level `--` boundary, exercising the D19 semantic, the tool yields `refused:variadic-boundary` with nothing executed; a canonical command passes through byte-identical, a flag-like value after the boundary is preserved verbatim, a `--` quoted inside a value is not treated as the boundary, a non-variadic verb keeps accepting trailing flags, and a script is never scanned.
Yields `tests/test_steel_exec.py::test_misordered_variadic_refused_never_executed`, `::test_canonical_text_entry_passes_through_byte_identical`, `::test_flaglike_value_under_sentinel_preserved_verbatim`, `::test_batch_boundary_required_at_both_levels`, `::test_quoted_double_dash_value_is_not_the_boundary`, `::test_non_variadic_verbs_accept_trailing_flags`, `::test_script_text_not_scanned_for_boundary`.

## Walkthrough predicates

The same five contract predicates also run against a live kali with no cloud key at all (`tests/test_steel_exec_live.py`, seven assertions: version pin, the routing refusals, timeout ordering, envelope shape on a keyless script, and the key-absence guard), so the gateway is proven on the real transport without spending a Steel session.

E1 - Fixture login end to end (live tier, deferred past this PR).
Grounds spec stories 1-8 and 10.
Input entering at the tool surface: navigate `https://the-internet.herokuapp.com/login`, batch snapshot/fill/click, wait text `Secure Area` (timeout 10000 ms).
Live edge: the Steel cloud under a `polymerhus-e2e-*` name.
Terminal: the current URL is `/secure`, the flash text is `You logged into a secure area!`, cookies include `rack.session`, and the session is released on every path.
Observed: the tool envelopes of each act plus the session catalogue before and after.
Status: deferred to the post-merge live run (this PR's tests are keyless; no cloud session is created by the suite).

E2 - steel_crawl non-regression.
Grounds spec story 16.
Input entering at the crawl seam: the unchanged crawl contract and the crawler role prompt.
Live edge: none (self-contained).
Terminal: the crawl suites stay green and the diff shows zero hunks under `recon/crawl/`; the duplicate readers are already one role-prompt each (#222), so this stream touches no crawl content.
Yields the existing `tests/recon/crawl/` suites.

E3 - Skill live validation (the writer's evidence, recorded here for PR review).
Input entering at the shell with the pinned CLI: every `skills/steel-browser/references/*.sh` run end to end against public fixtures.
Live edge: the Steel cloud, 2026-09-16, CLI 0.4.4, `steel doctor` pass.
Terminal: each script exits 0 with the expected envelope shapes, and afterwards `steel doctor` reports 0 active sessions with `steel browser sessions --json` empty; no `polymerhus-*` session survives.
Observed: the commands and outputs recorded below; the verbatim script text was also driven through `kali.mcp_server.steel_exec.fn(script=..., script_lang="sh")` to prove the tool path (returncode 0, the unchanged envelope keys).

### E3 evidence (2026-09-16, host CLI `/Users/diekgbbtt/.steel/bin/steel`)

Command shapes below are the 2026-09-16 captures: where a variadic verb appears without its `--`, the capture predates D19 and is evidence, not a canonical encoding.

- `steel --version` -> `steel 0.4.4`; `steel doctor` -> `overall pass`.
- Session catalogue before/after: `steel browser sessions --json` -> `{"data":[{id,mode,name,status,viewerUrl}],"success":true}` while live, `{"data":[],"success":true}` once stopped; `steel sessions list --status live --json` agrees on the id but carries no name; a `default` session appears when a start omits `--session`.
- Oracle taken (after start): -> `{"data":"https://app.steel.dev/sessions/<id>","success":true}`.
- `start --session <name> --session-timeout 600000 --json` -> `data` keys `connectUrl, id, inactivityTimeoutMs, liveUrl, mode, name, remainingMs` (the `connectUrl` embeds `apiKey=` and a JWT, so start stdout is sensitive - the reference scripts print `name`/`mode` only).
- Standalone `fill @e6` -> `{"error":"Unknown ref: e6",...,"success":false}` (a spike capture from before the `--` boundary was understood; the failure was flag-order swallowing, not a CLI defect - D2 amended 2026-09-16).
- `batch "snapshot -i" "fill @e6 tomsmith" "fill @e8 ..." "click @e4" --json` -> per-op `data` with the fill echoing `{"filled":"@e6"}`.
- `wait -t "Secure Area" --timeout 10000 --json` -> hit; `cookies --json` -> 5 cookies incl. `rack.session`; `eval "window.location.href"` -> the `/secure` URL; `stop` -> `{"stoppedSessions":["<name>"]}`, the catalogue then empty.
- `steel scrape https://example.com --format markdown --json` -> `{content.markdown, links, metadata}`.
- All eight references run via `bash <file>`: exit 0 each; the post-run orphan proof is the live session catalogue (`steel browser sessions --json` empty) plus `steel doctor` active-count 0.
- Third-party source-skill claims corrected against the live CLI: no `snapshot -C` (0.4.4 has `-u/--urls`) and no `sessions --raw`.
- Re-probed 2026-09-16: `steel browser sessions --json` is a reliable live-session catalogue (named start, unnamed `default` start, post-`stop` read, and a cross-process read all behave), so it is both the tool's uniqueness guard and the skill's list-sessions step (D13 amended).

### Skill live-validation campaign (2026-09-16, three ladder rounds + three writer/critic pod iterations)

Grounds the skill's rules (all PASS at every critic gate; evidence traces under `.../opencode/moodique/{trace.md,trace2.md,ladder1..3/}`).

- Surfaces exercised live on real logins: fully sequential (one process per operation), batched (3-100 ops), scripted (`.sh` and `.py`, summary line, trap-owned stop proven on SIGTERM), and eval-driven submit (all five routes: `element.click()`, dispatched pointer/mouse, `form.requestSubmit()`, `form.submit()`, framework trigger).
- Rule reversals the campaign produced (all folded, D2/D13/D14 amended): standalone text entry is not broken - the spike's failures were flag-order swallowing by the variadic `fill`/`type`/`setvalue`; `batch` is a choice for latency/state, not a defect workaround; a swallowed `--session` can auto-provision a billable `default` session; a failing batch has two envelope shapes (op-level two lines, batch-level one); count answers presence while `is visible` answers showness; `form.submit()` and framework triggers bypass handlers and native validation; there is no automatic eval-result bounding.
- Reproducible failure modes recorded for the PR: stale-ref silent re-bind after `navigate` (deterministic, 3/3), `select` with a no-match value silently landing on the first option (3/3), a `default`-session leak from the bad flag shape (2/2), and a trap that marks its name after `start` orphaning on a signal inside the start window (1/5 versus 0/5 with the rule).

### Integration note - the variadic fold, live red/green (defect report, 2026-09-18)

Recorded from the external authn-bootstrapper e2e (Steel session `fc26ae1f-d483-4fb1-81de-3a0f9f13c870`, read back with `steel sessions traces <id> --json`); the entered value is redacted as `<value>` (25 characters).

- RED: `steel browser fill --session <s> '<selector>' '<value>' --json` -> `get value` reads `<value> --json`, and the recorded `input#field-password` value length moved 22 -> 15 across the fill and a corrected fill - exactly `len(value) + 7` for `" --json"`, behind `success:true`.
- GREEN control: `steel browser fill --session <s> --json '<selector>' '<value>'` -> `get value` reads `<value>`.
- Tool loop with no live session: before D19 the same mis-ordered command executed byte-identical through `steel_exec` (stubbed binary, no argument normalization); after D19 it is `refused:variadic-boundary` with nothing executed.
- The sentinel live control (`fill [OPTIONS] '<selector>' -- '<value>'`, and the flag-like value `'-x'`) is covered by C9 at the host seam; the live tier confirms it end to end in E1, whose ground truth now includes the canonical encoding.

### Ungrounded skill rules to re-verify (named, not faked)

Two rules in `skills/steel-browser/SKILL.md` are not corroborated by any record in this repo, and the campaign traces that would have carried them are no longer available.
The next live tier (E1) must re-verify or delete them rather than leave them asserted:

- `press` takes one key: a single character types, a multi-character string is a silent no-op behind `success:true`, and a modifier chord such as `Control+a` does nothing.
  The pinned CLI documents `Control+a` as a key example, so the negative half of this claim either needs a fresh live capture or should be dropped.
- A `navigate` can fail transiently with `ERR_HTTP_RESPONSE_CODE_FAILURE`, so one retry is a sound default.

