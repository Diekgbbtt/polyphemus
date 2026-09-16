# Browser Capability via Steel CLI (#221) - Specification

Parent ticket: #221 (auth-context: pluggable browser capability via steel CLI).
Companion decisions: `docs/design/browser-cli-221-decisions.md` (D1-D10 as amended 2026-09-11, plus binding D11-D16).
Glossary: `src/polymerhus/recon/CONTEXT.md` (exec gateway, named session; profiles split per D16/D17).
Prior spec version (seam/tool-factory design) superseded in full by the operator-ruled just-exec design below.

## Problem Statement

Only the steel_crawl ReAct loop can drive a browser today, through an in-process provider no other agent can use.
Every new browser need - login and sign-up through client-side JS and anti-bot controls, session and token extraction, vulnerability-test execution in the page - re-solves session handling, command quoting, and result parsing from scratch.

## Solution

Steel CLI deployed eagerly in the kali container beside every other recon utility; one loosely-coupled `steel_exec` gateway tool accepting either a steel command or a `.sh`/`.py` automation script; all operation knowledge carried by a repo skill (with operation-script references) through the shared loader.
Agents browse by calling the tool; multi-op flows chain steel commands in scripts with trap-owned cleanup; the execution transcript lands in Langfuse as tool spans through the established callback path.

## User Stories

1. As a session agent facing a login or sign-up form, I want to start a semantically-named browser session, so that my flow owns an addressable cloud browser.
2. As a session agent, I want a clear `<name> is already used` error when my chosen name is taken, so that I never silently share a stranger's session.
3. As a session agent, I want to navigate and read back title and URL, so that I confirm where the flow stands.
4. As a session agent, I want snapshot refs for inputs and buttons, so that I target elements without brittle selectors.
5. As a session agent, I want to fill credentials and click submit through one batch, so that the CLI's single-command ref defect never bites me.
6. As a session agent, I want to wait on success text with the steel timeout governing and my tool budget above it, so that synchronisation is explicit and never cut short by an outer clock.
7. As a session agent, I want to run JS inline with the skill's verbatim escaping patterns, so that probing is immediate and correct.
8. As a session agent, I want eval results bounded by construction (project, slice, chunk), so that vulnerability-test reads never explode my context.
9. As a session agent, I want to promote a proven snippet into a script's EVAL step, so that working JS becomes reusable automation and audit trail.
10. As a session agent, I want the whole login as one script with trap-owned stop, so that cleanup holds on every exit path without my further attention.
11. As a session agent, I want cookies and storage reads after login, so that the ticket-5 verdict and the auth-store snapshot have their primitives.
12. As a session agent, I want every steel result as `--json` in the unchanged exec envelope, so that parsing is uniform with every other tool.
13. As a session agent, I want my steel calls visible in Langfuse as tool spans with args and results, so that flows are auditable without log files.
14. As the platform operator, I want the steel binary installed at kali boot, pinned and checksummed like other recon utilities, so that delivery needs no new image and pays no cold-start tax.
15. As the platform operator, I want configuration lazy (keys, session bootstrap), so that nothing browser-specific slows or risks kali boot.
16. As the steel_crawl owner, I want provider, tools, parsers, and skill content untouched, so that crawl behaviour is provably unchanged.
17. As the ticket-5 consumer, I want cookie/storage/URL reads plus the uniqueness and stop conventions, so that the login verdict builds on settled primitives.
18. As the auth-skill author (#220 follow-up), I want the operation mechanics and reference scripts owned here, so that login procedures compose them instead of rederiving them.

## Implementation Decisions

- Delivery: eager postrun-shaped install of the pinned CLI into the persisted kali binary dir at boot; lazy configuration only (credential env, per-flow sessions). No agent-image change (D12).
- Tool: one `steel_exec` gateway beside `execute_command`, sharing its runner and envelope; dual input (steel-token-routed command, verbatim-written script in `sh`/`py`); per-session workdir isolation; default tool timeout 600; thin contract, no operation knowledge; no per-subcommand allowlist and no redaction stage, by ruling.
- Session namespace: semantic agent-chosen names; uniqueness via the `live` oracle at creation in command mode (script mode by skill construction); `start` attach semantics and `sessions` unreliability recorded as the reasons (D13).
- Timeouts: steel authoritative, tool budget (600 default) above it, agent budget above that, all explicit per call (D11).
- Eval: inline default with skill-carried escaping verbatim and pitfall specimens; file promotion for reuse; result bounding as hard rule (D14).
- Transcript: Langfuse tool spans via the established callback pattern; per-command granularity through script stdout markers; no log files (D15).
- Skill data: reusable operation scripts as `references/` beside the steel CLI skill under repo-root `skills/` (one per operation; never exploitation PoCs or testing payloads); canonical login scripts owned by AUTH-SKILL-1; session workdirs hold run copies and evidence only (D16).
- Data-plane split with #220: the auth store holds WHAT (accounts, credentials, tokens, profile refs, snapshots, technical conditions, the `procedure` hook); the auth skill holds login PROCEDURES; this steel skill holds the operation MECHANICS. Extraction reads feed concrete-snapshot writes; technical-condition checks execute through steel reads; profile lifecycle administration is jointly out of scope.
- Profiles: server-side profile identity replaces session-context shuttling (D17) - mint-with-persist, mount-by-id with read-only default, settle-plus-verify (no CLI state poll exists), explicit release as the persistence call, one live session per profile, bearer-id handling per #220.
- The crawl duplicate readers migrate to the shared loader with a byte-identity check; the skill loads through `skill_for` under the #222 runtime convention when it lands.
- D2's batch-routing survives as skill knowledge (spike-proven CLI defect), not code.

## Testing Decisions

- A good test asserts external behaviour at the tool function (args in, envelope out, refusal reasons), never steel internals or live cloud state.
- Tool function with stubbed steel binary: routing refusals, uniqueness guard with faked oracle, timeout plumbing, envelope shape on success/malformed/error.
- Crawl boundary: existing crawl suites green plus the skill byte-identity check.
- Live tier only: fixture-login script end to end, stop proof via the oracle, orphan check.
- Prior art: the pod/exec unit tests with injected fakes; the skill-loader tests; the YAML store tests with explicit temp roots.

## Out of Scope

- steel_crawl migration; manifest/network-capture collection; the consuming login verdict and fallback legs (tickets 4/5); anything outside steel-flavoured commands; model-invoked skill triggering (phase-gated loading per #222); Steel profile lifecycle administration (jointly with #220); exploitation PoCs and vulnerability-testing payloads in references.

## Further Notes

- This spec travels with the change and links from #221 at PR time (recorded deviation from tracker publication - #221 already carries the problem/solution/acceptance).
- CLI pin is the spike-tested 0.4.4; bumps are skill-review events.
- The #221 acceptance criteria on redaction and always-stopped sessions are restated by the D4/D5 retirement and the trap-plus-backstop lifecycle; the criteria text itself needs its amendment at implementation time.
- ADRs live in the companion decisions file (D1/D4/D5/D6/D7/D10 superseded or retired as marked; D11-D16 binding).
