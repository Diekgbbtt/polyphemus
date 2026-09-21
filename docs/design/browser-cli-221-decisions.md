# Pluggable Browser Capability via Steel CLI (#221) - Architectural Decision Records

Decisions taken (self-grilled against the live CLI spike 2026-09-10, steel 0.4.4) for ticket #221: the lean pluggable browser capability any session agent can use, built on the `steel --json` exec surface.
No operator unknowns blocked design, so no questionnaire was issued; where the ticket pre-decided (eval in the surface, CLI in the images, no steel_crawl migration), the records below encode the ticket's ruling, not a new choice.
Companion precedent is the #220 auth-store tool contract (single implementation, contract rides the tool description, skill quotes verbatim).

## Spike matrix (the evidence every record below stands on)

Fixture target `https://the-internet.herokuapp.com/login` (canonical test login page), session `spike221a`, CLI-only, `--json` throughout.
Raw captures live under `/tmp/spike221_*.json` (host scratch, never committed); secret-bearing assertions below quote key names and presence booleans only, never values.
Historical capture (2026-09-10, pre-D2-amendment and pre-D18): the command shapes below are shown as observed, not as canonical encodings.
A variadic verb shown without its `--` boundary predates D18 and must not be copied.

| Command | Verdict | Latency | Evidence note |
|---|---|---|---|
| `start --session` | pass | 4 s | Raw stdout carries `data.connectUrl` (775 chars) embedding `apiKey=` + `sessionId=` over `wss://` - redaction mandatory (D4). `data` keys: `connectUrl, id, inactivityTimeoutMs, liveUrl, mode, name, remainingMs`. |
| `navigate` | pass | 1 s | Returns `{title, url}`; reached the login page. |
| `snapshot -i` | pass | 1 s | Accessibility tree with `@eN` refs; username `@e6`, password `@e8`, login `@e4`. |
| `fill @eN` standalone | FAIL | - | `Unknown ref: e6`, 4/4 across `fill`/`type`/`setvalue`, CSS selector also fails (`Element not found: #username`) while the element provably exists (`find input` returns 2, `eval` reads `id="username"`). CLI 0.4.4 ref-resolution defect in the single-command path; `focus @e6` + `click @e4` on the same refs succeed. **Amended 2026-09-16: the cause is flag order, not ref resolution - the invocation put `--session`/`--json` after the value, and the variadic verb swallowed them as VALUE, addressing a missing/`default` session. With options leading, all three verbs resolve a ref and a CSS selector standalone (ladder rounds 2-3, `a1_control.raw`).** |
| `fill` inside `batch` | pass | ~4 s for 3 ops | `batch "snapshot -i" "fill @e6 tomsmith"` returns `{filled: @e6}` and `eval` reads `#username.value == "tomsmith"` - the value provably landed. D2 prefers `batch` for multi-act text entry; the standalone form works with the `--` boundary (D2 amended). |
| `click` | pass | 1 s | `{clicked: @e4}`; empty-credential submit behaved as the page specifies. |
| `wait -t` | pass | ~1 s hit / 11 s timeout path | `wait -t "Secure Area" --timeout 10000` succeeds post-login; pre-login it times out with a typed error (no hang past the timeout). |
| full login | pass | - | `batch(snapshot, fill pw, click)` lands on `/secure` with `You logged into a secure area!` - the acceptance-criterion path works through CLI commands only. |
| `cookies --session` | pass | 0 s | 5 cookies incl. `rack.session` (the auth signal D9 consumes). |
| bare `cookies` (no `--session`) | empty by design | - | Returns `[]` - reproduces the ticket's scoping observation: every command MUST carry the session flag; the seam encodes this, never agent prompts. |
| `storage local` / `storage session` | pass | 1-2 s | `{}` shape on a target with no storage - shape, not content, is the assertion. |
| `eval` | pass | <1 s | Reads (`querySelectorAll` counts, `activeElement.id`, flash text, `location` reads) all succeed. |
| `batch` | pass | 4 s | Multi-op results envelope `{results: [{command, data|error, success}]}`; `--bail` available. |
| `stop --session` | pass | 1 s | `{stoppedSessions: [spike221a]}`; follow-up `sessions` lists only the pre-existing foreign `default` session - no orphan. |
| per-command latency | acceptable | - | 0-4 s per op; whole login flow ~15 s browser time. Login-scale (tens of calls) confirmed; crawl-scale loops stay out of scope per the ticket. |

Overall spike verdict: PASS with one encoded constraint (D2). The single-shape `fill` failure does not trigger the §4 stop rule: every login capability is proven through CLI-only commands, and the working shape (`batch`) is the ticket-anticipated path (`batch` amortises spawn cost), not an SDK-shaped escape. A same-surface resolution is not a pivot.

## D1 - The allowlist is exactly the ticket's eleven, no `get`

*Superseded 2026-09-11: there is no per-subcommand allowlist - `steel_exec` routes on the `steel` token, so the eleven-command list and the `get url` exclusion below are historical, not enforced.*

`start, navigate, fill, click, wait, snapshot, cookies, storage, eval, batch, stop`.
`get url` (used in the spike to read the current URL) is NOT admitted: the login-verification predicate (D9) reads the URL through `eval` (`window.location.href`), so no twelfth command is needed.
Anything outside the eleven (tabs, screenshots, PDFs, file upload, drag, `set headers/useragent/geo`, profiles, credentials injection) is refused by the seam: the capability targets login-scale interaction, and each admitted command must earn its place against a login/extraction need.

**Rationale.**
A small allowlist is the safety bound the ticket's eval question is really asking for: the risk is not one command but an open-ended browser remote-control surface. Eleven spike-proven commands, each mapped to login or extraction, keep the surface reviewable in one screen.

## D2 - Batch is the preferred text-entry shape, not a defect workaround; refs never cross a navigation

*Amended 2026-09-16 (ladder rounds 2-3): the single-command defect this record stood on is falsified - see below.*

`batch` remains the preferred shape for a multi-act sequence: one spawn per sequence, the snapshot's refs shared across the acts, and the submitting act where the flow calls for one.
Refs from a returned snapshot are valid for the immediately following call only, and never across a `navigate`: a fresh snapshot opens every post-navigation sequence.
The 2026-09-16 re-probe sharpens what "never across a navigate" means in both directions: within one document the ref registry is append-only (an earlier ref still resolves), but after a `navigate` the same id silently re-binds to a different element instead of erroring, so a stale ref clicks the wrong thing behind `success:true`.

**Amendment rationale.**
The spike's "CLI 0.4.4 single-command ref-resolution defect" was a flag-order artifact: `fill`/`type`/`setvalue` are variadic (`fill [OPTIONS] <SELECTOR> [VALUE]...`), so options trailing the value are swallowed as more VALUE tokens and the command addresses a missing or `default` session - which is what produced `Unknown ref` / `Element not found` while the element provably existed. With options before the first value token, all three verbs resolve a ref and a CSS selector standalone (live control pair, ladder rounds 2-3). The batch shape therefore survives as the latency/state choice, no longer as the only way to enter text. The `default` session such a mistake may auto-provision is a billable leak, not a harmless error, and the skill carries the attribution rule that stops it.

## D3 - `eval` is permitted, purpose-bounded by skill discipline, audit-logged

`eval` stays in the surface (the ticket lists it as login-relevant, and D9's extraction reads plus the URL read depend on it).
No mechanical JavaScript subset is enforced: a read-only-JS allowlist is unenforceable at the seam (any expression can mutate), and claiming one would be false closure (`CODING_STANDARD.md` §12).
The real bounds are two since `D1`'s allowlist was retired (the third bound below is historical): the SKILL restricts `eval` to login/extraction purposes (reads plus the D2 interaction fallback); every evaluated expression is recorded verbatim in the tool result (audit, so a reviewer sees exactly what ran).
The retired third bound, for the record: the eleven-command allowlist (D1) kept `eval` from becoming a general compute escape - it runs in the page, against the target, for the flow.

**Rationale.**
The ticket pre-decided inclusion; the grill's job was the scope question. Purpose-discipline plus audit is the strongest HONEST bound: it admits what cannot be mechanically prevented and makes it reviewable instead.

## D4 - Redaction sits at the seam, ahead of results, context, and logs

*Retired 2026-09-11: no redaction boundary - outputs pass through.
Secret hygiene is skill discipline (name/count reads, no value echoes), not a seam guarantee.*

The seam strips Steel platform secrets from raw CLI stdout BEFORE constructing tool results: `data.connectUrl` (bearing `apiKey=` + `sessionId=`, proven present in the spike's raw `start` output) and viewer URLs (`liveUrl`, the `viewerUrl` in `sessions` output) are dropped wholesale.
The tool result for `start` carries only `{id, name, mode, timeouts}` - everything the flow needs to name its session, nothing that authenticates as the operator.
Token-shaped is defined as: a `wss://connect.steel.dev` URL, an `apiKey=` query-param value, a `sessionId=` value outside the seam's own session-name bookkeeping, or the literal `STEEL_API_KEY` value.
The acceptance test is failing-first: raw `start`-shaped stdout (synthetic secrets in the live-observed shape, fixture committed from the spike's key layout) enters the seam, and the test asserts no token-shaped value reaches tool results, context, or logs.
`STEEL_API_KEY` itself never leaves the environment: the CLI resolves auth from the environment, so the key is never interpolated into an argv the seam builds.

**Rationale.**
Tool results flow into agent context and Langfuse traces; redacting only at the logger leaves the context exposed. The seam is the single chokepoint every browser act funnels through (`CODING_STANDARD.md` §8), so it is the only locus where the guarantee can be total rather than per-caller.

## D5 - Two secret classes: platform secrets are stripped, target-secret values are withheld from logs

*Retired 2026-09-11 with D4: no seam value-withholding stage.
The two-secret-class discipline survives in the skill, which reads names and counts and never echoes a text-entry command string or a value.*

The spike's audit-logging answer (D3) collides with credential hygiene: `fill` arguments carry TARGET secrets (operator-supplied test passwords), and echoing them into results/logs would trade one leak for another.
The seam therefore keeps two classes apart: platform secrets (D4 - stripped everywhere, never executed-with except by the CLI's own env resolution) and target-secret command values (`fill`/`type`/`setvalue` text, `storage set` values, `cookies set` values), which ARE executed (the page needs them) but are withheld from tool results and logs - results echo `{filled: @eN}` (the CLI's own shape, which never echoes values) and logs record command names plus refs, never values.
The auth store (#220) remains the home of target credentials at rest; the seam only ever holds them in flight.

**Rationale.**
Not distinguishing the classes fails both ways: treating passwords like API keys breaks login, treating API keys like passwords leaks platform access. The CLI's value-never-echoed result shape makes the distinction cheap to hold.

## D6 - Stop is unconditional; the seam owns the whole named-session lifecycle

*Amended 2026-09-11 (substrate ruling): the context-manager/`finally` shape is retired with the just-exec design - the stop owner is the script trap plus the D13 watchdog, names are the agent-chosen `polymerhus-<flow>-<id>` (never `<id8>`), and "unconditional" is enforced by the skill and the reference scripts, not by a seam context manager.*

Sessions are named `polymerhus-<flow>-<id8>` (never the `default` session - the spike showed a foreign `default` session live, which the seam must neither use nor stop).
The seam creates the session at flow start and stops it in a `finally` (context-manager shape): success, failure, and timeout paths all stop - stop-on-failure is enforced, never advisory, per the ticket.
Timeouts: `--session-timeout 600000` (10 min, generous against the measured ~15 s login flow) at `start`; the CLI's `--inactivity-timeout` default (120000 ms, observed as `inactivityTimeoutMs` in the spike's `start` output) stays as the orphan backstop.
Orphan detection is a seam helper, not agent duty: `reap_orphans(prefix)` lists live sessions under our prefix for harness/operator use, and the e2e assertion is "no live `polymerhus-*` session after the flow".

**Rationale.**
Whoever names a session must bury it; splitting creation from cleanup across caller and seam is how orphans happen. The finally-shape plus the inactivity backstop gives two independent guards (deterministic stop + self-release), either sufficient alone.

## D7 - One tool factory mirrors `get_crawl_tools`; the contract rides the tool description

*Superseded 2026-09-11 (substrate ruling): there is no `get_browser_tools` factory - the tool is the `steel_exec` fastmcp gateway with dual command/script input.
The surviving principle is D7's second half: the contract rides the tool description, and the skill restates it.*

`get_browser_tools(*, exec_fn=None)` returns the browser tools filtered to `BROWSER_TOOL_NAMES`, injectable `exec_fn` defaulting to the real CLI runner - the exact shape of `steel_client.get_crawl_tools` (`src/polymerhus/recon/crawl/steel_client.py:105-125`) with subprocess in place of the in-process provider.
Per #220, the tool description IS the contract (single implementation, no per-consumer paraphrase), and the repo skill quotes it verbatim.
`steel_configured()` (credential-present check, `steel_client.py:59-64`) is reused, not reimplemented: the seam refuses to run unauthenticated with the same error shape.

**Rationale.**
`CODING_STANDARD.md` §8 (one behaviour, one implementation) plus the #220 precedent: the second capability surface reuses the first's proven contract shape instead of inventing one, so a reader who understands `get_crawl_tools` already understands `get_browser_tools`.

## D8 - The skill is a flat repo skill on the shared loader; duplicate readers are already gone

*Amended 2026-09-16 on rebase onto #222 (`5064ecd`): the role-routed skill path this record first named is stale - the catalogue went flat.*

The skill is `skills/steel-browser/SKILL.md`, with its operation references beside it as `references/*.sh` (#222/#234 catalogue: flat, `name` == directory, no role-routing layers; role prompts are NOT skills and live in module `prompts/` dirs).
It loads through the shared loader `skill_for` (`src/polymerhus/app/llm/skills.py`) and, on demand, through the agent-callable `load_skill(name)` tool that calls that same loader internally - so bake-time mounts and runtime loads return byte-identical bodies.
The skill body restates the `steel_exec` contract (the tool description stays the single source; the skill carries no byte-for-byte copy) and carries only the discipline it cannot: the snapshot-then-act ref flow, the boundary-mandated text entry, the inline-`eval` escaping and result bounding (D14), the trap-owned stop on every path (D13), and the timeout ordering (D11).
Per-agent binding of the skill into the L1 index (`context={"skills": [...]}`) is no longer deferred: A9 (2026-09-17) rosters every tool-calling role in `ROLE_SKILLS`, and each bound site attaches the whole surface through `skill_agent_binding` (index middleware + skill tools + the invocation context).
A role with no bearing skill is declared EXEMPT and binds nothing.
The earlier deferral, and the #222 D3 note that per-agent skill-set configuration was open, is closed by A9.
The ticket's "duplicate skill readers" concern is already resolved upstream: `crawl_agent._load_skill` and `crawl_agentic._load_steel_crawl_skill` both serve the crawler role prompt `recon/crawl/prompts/steel-crawl.md`, so this stream touches no crawl content and `steel-crawl`'s own text is untouched (D10).

**Rationale.**
The loader exists precisely so every role's discipline hardens together; a browser capability with its own private reader would re-fork the behaviour the ticket charges us to unify.

## D9 - Verification is a `login_succeeded`-shaped predicate over cookies + URL; no request history

The consuming flow (ticket 5) decides "logged in" exactly like `steel_provider.login_succeeded` (`src/polymerhus/recon/crawl/steel_provider.py:127-135`): a NEW in-scope session-like cookie vs the pre-login baseline (spike: `rack.session` appears post-login) AND an in-scope non-login URL (spike: `/secure`).
This ticket exposes the primitives (baseline + current cookie reads, URL read via `eval`), not the verdict: the verdict belongs to the consuming flow.
The CLI has no network-capture command (confirmed across the full `browser --help` surface), so manifest collection stays in `steel_crawl` by construction, and login verification never needs it - the request-history gap is a confirmed non-requirement, not a risk.

**Rationale.**
Reusing the hardened predicate shape (cookie AND url, neither alone - `steel_provider.py:128-135`) inherits the false-positive analysis the crawl path already paid for (CSRF-cookie-on-login-page, off-login bounce without session) instead of re-learning it.

## D10 - steel_crawl is untouched; the seam is a new module; the CLI is pinned

*Amended 2026-09-11 (substrate ruling): there is no agent-side `recon/browser/` module and no added Dockerfile layer - the CLI is installed eagerly by `kali/postrun.sh` into the persisted `/opt/localbin` volume (D12).
The crawl non-regression boundary, the CLI pin, and the "no edits under `crawl/`, `parsers/`, `skills.py`, or the curators" rule below stand; read the `recon/browser/` and Dockerfile sentences as historical.*

Non-regression boundary: NO edits under `crawl/` (`steel_client.py`, `steel_provider.py`), `parsers/` (no `PARSERS` registration - browser outputs are parsed by pure `parse(stdout)`-shaped functions in the new module, same signature discipline per `parsers/__init__.py:17`, without touching the registry), `skills.py`, or the curators.
New code lives in `src/polymerhus/recon/browser/` (seam + tools + redaction + session lifecycle).
`steel_crawl`'s suite staying green IS the non-regression proof, plus a dedicated assertion that no shared module's behaviour changed.
Image change: a pinned steel CLI binary layer is ADDED in the `Dockerfile` next to the crawl layer (`Dockerfile:34-37`); the `steel-sdk` + `playwright` pins in `requirements-crawl.txt` are KEPT (the in-process provider still needs them); `STEEL_API_KEY` wiring is UNCHANGED (env to `recon/config.py:19`, which the seam reuses via D7).
CLI pin is 0.4.4 (the spike-tested version, including the D2 defect); any bump re-runs the spike matrix before adoption.

**Rationale.**
The ticket is explicit (no migration, no shared-code breakage); the boundary above makes "untouched" mechanically checkable in review (the diff must show zero hunks under `crawl/` and `parsers/`). Keeping the SDK pins is forced by the same ruling: the provider they serve still ships.

## Amendments 2026-09-11 (operator rulings, supersede where noted)

- **Substrate:** steel CLI on kali behind a distinct loosely-coupled `steel_exec` fastmcp tool (dual input: any `steel`-containing cmd, or a `.sh`/`.py` script automating several operations). No agent-side module (`recon/browser/` deleted from the plan); any shared glue lives in `app/` (layout ruling).
- **D1 superseded:** no per-subcommand allowlist. The tool routes on the `steel` token only; operation knowledge lives in the skill.
- **D4/D5 retired:** no redaction boundary. Outputs pass through; `--json`/compact discipline lives in the skill as token hygiene, not a guarantee.
- **D6 amended:** session names are agent-chosen and semantic (D13); stop discipline is skill + script-trap (D13).
- **D10 amended:** eager kali deploy, lazy configuration only (D12).

## D11 - Steel timeout is authoritative

Timeout ordering across the three clocks is fixed: the steel CLI's own timeout (`wait --timeout`, navigate timeouts) governs the operation; the tool's `timeout_s` (default 600) MUST exceed the longest steel wait in the invocation; the agent-side MCP call budget exceeds that in turn. All three are set explicitly per call - never defaults-on-defaults. Rationale: if the tool's clock fires first, a script dies before its `trap stop`, producing exactly the orphan the lifecycle exists to prevent.

## D12 - Eager binary deploy in kali, lazy configuration only

The steel binary ships the way every other recon utility ships: `kali/postrun.sh` gap-fill into the persisted `/opt/localbin` volume at kali boot (the `whois` / `graphql-cop` / `massdns` / `puredns` precedent), pinned with checksum. No agent-image change, no lazy binary download, no cold-volume first-use latency. Lazy at first use is configuration only: environment keys (`STEEL_API_KEY` via kali `env_file`) and per-flow session bootstrap. Rationale: boot-time install is the mechanised pattern; laziness is kept where it pays (credentials, sessions), removed where it taxes (binary delivery).

## D13 - Semantic session names with a catalogue-read uniqueness guard

Names encode flow semantics (`polymerhus-<flow>-<id>`), chosen by the agent per skill - never uuid-opaque, never seam-invented. Uniqueness is checked at creation: `steel browser start` silently ATTACHES to an existing name (proven live 2026-09-11: second start returns success, same shape), so start alone cannot detect collision; the guard is required. The check-then-start race (TOCTOU) is documented and accepted at login scale; consequence of a lost race is a shared session, bounded by the semantic-name discipline. This is the tool's sole special-case of session lifecycle - a namespace guard, not a capability allowlist - so loose coupling on operations is preserved.

**Amended 2026-09-16 (catalogue read replaces the per-name `live` probe).**
The guard reads the live session catalogue: `steel browser sessions --json` returns every live session this key owns as `{id, mode, name, status, viewerUrl}`, and `data: []` once none is live; a command-mode `start` whose name appears there is refused with `<name> is already used`. One read answers every name question and is visible across processes and workdirs (proven by starting a session through the tool and listing it from a separate host shell, then confirming `data: []` after `stop`), which is what the skill surfaces as its list-sessions step.
The first ruling's premise is superseded, not merely refined: `steel browser sessions` was recorded as unusable because it "lists empty while a session is demonstrably live", and a re-probe on the same 0.4.4 pin (named start, unnamed `default` start, post-`stop` read, cross-process read) shows it listing correctly in every case and agreeing with the platform's `steel sessions list --status live`. The per-name `steel browser live --session <name>` oracle is therefore retired; `live` remains a viewer-open command in the skill's command families, not the guard. The catalogue call fails open (`None` = cannot verify) exactly as the probe did, so a broken catalogue never blocks a start.
A catalogue read is authoritative but not instantaneous: a session whose `start` has not returned is legitimately absent (in-flight, not stale), so a surprising read is re-read once rather than believed; and a `default` that appears because a bad flag shape addressed it is the caller's own leak to stop by name (a `default` already live before the call stays foreign and untouchable).

## D14 - Inline eval by default, skill-carried escaping, files for promotion only (amended: file-first retired)

Supersedes the file-first rule below it. Rationale for the reversal: agents develop JS probe-then-persist (REPL-style inline iteration, then keep what works) - file-first inverts the loop, forcing a write round-trip per probe and assuming first-try success. And the dominant in-browser use beyond auth is vulnerability-test execution, an unbounded-read primitive: the design risk is data explosion, not quoting, so the guardrail belongs on result shape.

The discipline, owned by the skill: eval runs INLINE, with the skill carrying steel CLI usage verbatim plus a dedicated eval section citing the snippet format and the common writing pitfalls (single/double/backtick nesting through the JSON-arg and shell layers; `$` expansion; the IIFE-returns-plain-data format; the two live-proven traps - a path argument parses as a regex literal, a bare `-` evaluates as source). Result bounding is a hard rule: project before return (counts, slices, targeted selectors over whole-document dumps), chunk large extractions, prefer booleans for checks. Files are the promotion path, not the default: a proven snippet graduates into `/work/<session_id>/js/` for reuse inside `.sh`/`.py` automation scripts (which chain multiple steel cmds, EVALs included) and as audit trail - fed then via `"$(cat …)"`, which stands as the mechanism, demoted from the discipline.

**Amended 2026-09-16 (ladder evidence).** The skill now carries the route preference for driving a control from `eval`: `element.click()`, a dispatched pointer/mouse sequence and `form.requestSubmit()` honour submit handlers and native validation (an empty `required` field fires exactly 2 `invalid` events, 0 `submit`, no navigation), while `form.submit()` and a framework `trigger("submit")` bypass both and are the last resort; counting `invalid` events takes its own measurement, since `checkValidity()` fires its own. And there is no automatic result bounding - a 200000-character return arrives whole - so projection before return is the operator's hard rule, not a platform guarantee. A missing selector returns `{"data":null,"success":true}`, so a null read is not an error signal.

## D14 (original, superseded) - JS executes from files, fed via substitution

`steel browser eval` accepts an inline expression ONLY: no `--file` flag (`eval --help`), no stdin (`eval -` evaluates the literal `-`; proven live), a path argument evaluates as JS source (proven live: the path parses as a regex literal and fails). Kali-side `.sh`/`.py` scripts are automation scripts, never browser JS. The discipline, owned by the skill: every non-trivial JS snippet lives in a file under `/work/<session_id>/` and is fed as `steel browser eval "$(cat <file>)" --session <name> --json`. Proven live 2026-09-11: multi-line JS carrying single quotes, `$`, and backticks round-trips byte-exact (`Example Domain | it's $100 \`quoted\``) - double-quoted substitution output is literal, never re-expanded, so the file rule deletes the quoting class for JS entirely. Inline expressions remain only for trivially safe reads (`document.title`, `location.href`).

## D15 - Transcript lives in Langfuse, not in a file

No `steel.log` file. The execution transcript (tool args, stdout JSON, returncode, duration) reaches the observability platform as MCP tool spans through the established callback pattern (`get_langfuse_callbacks` passed at invocation, inert `[]` when unconfigured - the `execute_command` precedent, which the trace viewer already renders as command-plus-output spans). Nothing new runs on kali and no exporter is added there. Per-command granularity inside scripts comes from progress markers echoed to stdout, which the envelope carries into the trace. Rationale: one observability path for all tool calls (the doc already notes the crawl tools' spans as the unwired exception - steel_exec is wired from day one by riding the mechanised path).

## D16 - Steel skill data: operation references under skills/, coupled to #220 on the data plane

Reusable browsing-operation scripts live as `references/` beside the steel CLI skill under repo-root `skills/` (one script per reusable operation; no exploitation PoCs, no vulnerability-testing payloads - that boundary is absolute). Session workdirs hold a run's copies and evidence only; the canonical login scripts are AUTH-SKILL-1's (`#220`, which owns login procedures and per-method references authored with the auth skill). The data-plane split, so neither stream authors twice: the auth store holds WHAT (accounts, credentials, tokens, profile refs, snapshots, technical conditions, the `procedure` label hook); the auth skill holds the login PROCEDURES; this steel skill holds the operation MECHANICS the procedures are written in (session lifecycle, snapshot-ref handling, inline-eval escaping and bounding, trap-stop, timeout ordering). Arrows: `procedure` labels resolve to procedures composing steel operations; extraction reads (cookies/storage/eval) produce the material agents write as concrete request snapshots (the #220 bootstrap-capture future); technical-condition checks execute through steel reads. Joint out-of-scope on both sides: Steel profile lifecycle administration.

## D17 - Server-side profiles replace session-context shuttling

Operator decision from the #220 stream: durable browser identity lives in Steel profiles (long-lived named server-side state), not in client-side session-context JSON. What the skill procedures and references must encode, concisely: mint on first login (`start --profile <name> --update-profile`, profile id recorded to the auth store steel reference); mount by id with an explicit write discipline (`--update-profile` present accumulates, absent mounts read-only - recon-style browsing defaults read-only, write-back only past the verify gate); settle-then-verify on every mount (the API's poll-READY has NO CLI equivalent - `profile list` returns name plus id only, verified live - so settle pause plus verify-by-navigation is the procedure, and an unverified mount never passes a verdict); explicit release on every path (release is the persistence call; timed-out sessions still write, Failed ones skip it, so any abnormal end forces re-verify); one live session per profile (last-writer-wins, no merge - skill rule plus the #220 per-project locks); hard timeout at create plus inactivity backstop. Tool side impacts: none on the tool contract (profile flags ride in command strings; the uniqueness oracle is orthogonal); two honest constraints - no state-poll primitive exists to offer, concurrent-mount guarding stays out of the tool (would couple it to flag parsing), and `stop --all` is unusable for reaping (kills foreign sessions) while prefix-scoped reaping is blocked by the unreliable `sessions` listing, so platform inactivity is the primary orphan defense with best-effort reaping over skill-tracked names.

## D18 - The variadic `--` boundary is mandatory; the tool refuses a command without it

*Added 2026-09-18, on the external-authn-bootstrapper defect report.*

The CLI's variadic verbs take `[VALUE]...` (or `[COMMANDS]...` for `batch`) after their required positional: `fill`, `type`, `setvalue`, `select`, `upload`, `batch`, enumerated from `browser <verb> --help` on the pinned 0.4.4.
The report named the first three; the help surface shows `select` and `upload` carry the same variadic shape, so the guard covers them too, which also corrects the skill's earlier note that `select` accepts trailing flags.
clap's variadic greedily consumes a flag that follows the first positional, folding it into the value silently: the observed `steel browser fill '<selector>' '<value>' --json` wrote `<value> --json` into the field behind `success:true`, and a trailing `--session` folds the same way, resolving the verb to an auto-provisioned billable `default` session - worse than the wrong value, since it leaks a live session rather than failing a login.
This is D2's amended flag-order finding turned into a guard rather than a caution.
The earlier proposal (hoist a denylist of known flags ahead of the first value) is rejected: it re-implements clap's grammar with a hand-maintained flag list, breaks on unknown flags, cannot tell a flag-like value from a flag, and silently reorders instead of surfacing the ambiguity.

**Decision.** Every variadic command must declare the CLI's own end-of-options boundary `--`; `steel_exec` refuses a variadic command without a top-level `--` (`refused:variadic-boundary`) and never reorders or guesses.

**Canonical encoding (the three roles).**
`steel browser <verb> [OPTIONS] <selector> -- <value>...` for the value verbs, and `steel browser batch [OPTIONS] -- "<cmd>" "<cmd>"...` for `batch`.
`[OPTIONS]` are `--flag[ value]` tokens, all before the `--`; the selector is the one required positional immediately before it; everything after the `--` is the value, taken verbatim, joined with spaces, and never reinterpreted as an option.
A value that begins with `-` needs no special casing beyond the boundary: `-- '-x'` types `-x` verbatim, and `-- '--json'` types `--json`.
Quoting follows the existing shell rules (single-quote literals, runtime values via `"${VALUE}"`); the boundary is a distinct argv token, not a shell escape.
Inside a `batch`, each element is its own command over the same grammar and carries its own boundary, so `batch --session S --json -- 'snapshot -i' 'fill @e6 -- 42'` is canonical at both levels.

**Enforcement is fail-closed and static.**
`_boundary_gap` tokenizes with shlex (so a `--` inside a quoted value is data, not the boundary), identifies the dispatched verb, and refuses when a variadic verb lacks the marker, including the outer `batch` and each variadic `batch` element.
The refusal names the verb and quotes its canonical form, so re-encoding is mechanical.
The command is never reshaped and never executed on refusal, and the guard runs last, after the routing, version, timeout-ordering, and session-name checks, as a pure shape check.
Script text stays unscanned (D13): a script owns its own encoding, and the reference scripts are canonical by construction.

**Why reliable, not heuristic.** The check does not decide where the boundary is; it requires the caller to declare it with the CLI's documented token, and a canonical command then cannot fold, because no option sits in the value region - clap only folds a flag that follows the first value, and the first value now follows `--`.
It is one token-presence predicate over the command, not a re-implementation of the flag grammar, and it never reorders.

**Ranked alternatives (by reliability, with failure modes).**
1. Enforced `--` boundary at the tool (chosen): total over command mode, `batch` and unmodeled future flags included; failure modes are a loud re-encode requirement and a verb set that a pin bump's skill review must extend (bounded by D10). Enforceable in the tool, taught by the skill.
2. Typed/structured tool surface (the tool builds argv): structurally unambiguous for the verbs it models, but it cannot cover `script`, `batch` element strings, or unmodeled verbs, so it is opt-in and bypassable; it also changes the just-exec contract of D2/D8 (thin gateway, no operation knowledge, the skill restates the contract). Enforceable in the tool; rejected as the primary seam.
3. Known-option-after-selector refusal (denylist): rejected above - re-implements clap, breaks on new flags, cannot distinguish flag-like values, and over-refuses.
4. Upstream CLI fix (error or auto-insert when a flag follows the first value): structurally best, but unavailable at the pinned 0.4.4 and unenforceable from the tool; filed as the long-term fix, never a dependency. Only upstream.

**Chosen seam and justification.** The tool is the single chokepoint every browser act funnels through (the D4 rationale), so it is the one place the guarantee can be total; the sentinel is the CLI's own boundary, so the tool constrains the encoding without owning the grammar.
The skill carries the same rule for a bare CLI (no `steel_exec`) and for the reference scripts, and the refusal message quotes the canonical form so the tool and the skill teach one encoding.

**Accepted failure modes, named not papered over.** A caller who writes a stray positional before the boundary (a value before `--`) can still fold; that is not the habitual options-last encoding and is not detectable without flag parsing, so it is recorded here rather than guessed at.
An unparseable command (unbalanced quotes) is passed through, since the shell rejects it itself and the guard does not guess.
The live red/green repro is recorded in the assertions file.

**Sibling-branch convergence.** The auth-context branches (220, 223, 237, meta) branched off this branch at `8e3d1b3`, before D18 landed, and one of them re-applied the same fix as its own `D19` (`c332329`).
A rebase of those branches onto the D18 tip must drop the duplicate so the fix carries one number.

## What was deliberately NOT decided here

- `domain-model.md` is unchanged by this ticket: the seam introduces capability infrastructure inside Recon, not a new primitive, relationship, or open question in the reasoned ontology. Per `CONTEXT-MAP.md`'s helper-modules ruling, capability vocabulary lives in the owning context's glossary (`recon/CONTEXT.md`: exec gateway, named session, variadic boundary, skill binding; the #220-owned profile split; the redaction-boundary entry retired with D4/D5), never as ontology.
- The exact Dockerfile install stanza (binary download URL, checksum) is fixed at implementation with a built-image `steel --version` proof, not guessed here.
- The consuming login flow (ticket 5) and the fallback leg (ticket 4) are out of scope; this ticket ends at proven primitives plus the skill.
