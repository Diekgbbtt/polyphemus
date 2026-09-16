# Assertions - browser capability via Steel CLI (#221)

**Source:** `docs/design/browser-cli-221-spec.md` (realising #221, per `docs/design/browser-cli-221-decisions.md` D1-D10).
**Seams under assertion:** the exec seam (CLI runner plus redaction plus session lifecycle), the tool factory (`get_browser_tools` over `BROWSER_TOOL_NAMES`), the skill loader (`skill_for` for the browser skill).

## Contract predicates (integration)

C1 - Redaction at the seam.
Given start-shaped stdout carrying token-shaped values (synthetic `apiKey=`/`sessionId=` in the live-observed key layout) at the exec seam, exercising the secret-leak semantic, the contract yields tool results, context, and logs containing zero token-shaped values.
Yields `tests/integration/test_browser_cli_redaction.py::test_start_secrets_stripped` (failing-first).

C2 - Stop on failure.
Given a mid-flow command failure at the session-lifecycle seam, exercising the failure-path semantic, the contract yields exactly one stop for the flow's named session and the error surfaced (never swallowed).
Yields `tests/integration/test_browser_cli_lifecycle.py::test_stop_on_failure`.

C3 - Batch-routed text entry.
Given a fill act at the exec seam, exercising the CLI-defect semantic (standalone text entry fails on the pinned CLI), the contract yields an argv where the fill travels inside a batch opened by a snapshot (never a standalone fill/type/setvalue invocation).
Yields `tests/integration/test_browser_cli_interaction.py::test_fill_rides_batch`.

C4 - Tool contract shape.
Given `get_browser_tools()` at the tool-factory seam, exercising the success semantic, the contract yields exactly the `BROWSER_TOOL_NAMES` set (eleven tools), each with a non-empty description carrying its contract.
Yields `tests/integration/test_browser_cli_tools.py::test_contract_names_and_descriptions`.

C5 - Malformed CLI output degrades.
Given non-JSON stdout (and given an error-envelope JSON) at the parse seam, exercising the malformed semantic, the contract yields a typed error result (never a raise, never a hang).
Yields `tests/integration/test_browser_cli_parsing.py::test_malformed_degrades`.

C6 - Session flag always present.
Given any allowlisted command at the argv seam, exercising the scoping semantic (bare commands address nothing), the contract yields an argv always carrying the flow's `--session` value.
Yields `tests/integration/test_browser_cli_lifecycle.py::test_session_flag_always_present`.

C7 - Skill loads through the shared loader.
Given `skill_for("recon/browser/login")` at the loader seam, exercising the success semantic, the contract yields the skill body quoting the tool descriptions verbatim (no paraphrase drift).
Yields `tests/integration/test_browser_cli_skill.py::test_skill_loads_and_quotes_contract`.

## Walkthrough predicates (end-to-end)

E1 - Fixture login end to end.
Grounds spec stories 1-8 and 10.
Input entering at the tool surface: navigate `https://the-internet.herokuapp.com/login`, fill username `tomsmith`, fill password `SuperSecretPassword!` (public fixture credentials), click login, wait text `Secure Area` (timeout 10000 ms).
Live edge: the public fixture target plus the Steel cloud (mode: live session under a `polymerhus-e2e-*` name).
Path: start creates the named session (branch: credential present), batch snapshot/fill/click submits the form (branch: batch-routed text entry), wait synchronises on the success text (branch: hit, not timeout), cookies/storage/URL reads capture the post-login state, stop releases the session (branch: success path).
Terminal: current URL is the `/secure` page exactly once, flash text is `You logged into a secure area!`, cookies include `rack.session` (count at least 1 session-like cookie), zero live `polymerhus-e2e-*` sessions afterwards.
Observed: the tool results of each act plus a sessions listing before and after, read back through the seam.
Yields `tests/e2e/test_browser_cli_login.py::test_fixture_login`.

E2 - Live redaction.
Grounds spec story 12.
Input entering at the exec seam: a real `start` for a `polymerhus-e2e-*` session.
Live edge: the Steel cloud (mode: live session create plus stop).
Path: start returns raw stdout (branch: platform secrets present in the raw envelope), the seam builds the tool result, stop releases the session.
Terminal: the tool result carries `id`, `name`, `mode`, timeouts (4 fields, values literal from the live envelope minus secrets) and zero token-shaped values; zero live `polymerhus-e2e-*` sessions afterwards.
Observed: the tool result plus the redaction scan over it, read back through the seam.
Yields `tests/e2e/test_browser_cli_login.py::test_live_start_redacted`.

E3 - steel_crawl non-regression.
Grounds spec story 15.
Input entering at the crawl seam: the unchanged crawl contract (`get_crawl_tools` names, steel parser on a fixture manifest).
Live edge: none (self-contained).
Path: the crawl tool factory returns the seven tools (branch: credential-gated as before), the steel parser maps a fixture manifest to deltas (branch: unchanged shape).
Terminal: `CRAWL_TOOL_NAMES` membership exact, parser delta counts identical to the pre-change baseline, zero diff hunks under `crawl/` and `parsers/`.
Observed: the existing crawl suites green plus a diff-boundary assertion.
Yields the crawl unit/integration suites plus `tests/e2e/test_browser_cli_login.py::test_crawl_boundary_untouched`.
