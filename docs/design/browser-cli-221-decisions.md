# Pluggable Browser Capability via Steel CLI (#221) - Architectural Decision Records

Decisions taken (self-grilled against the live CLI spike 2026-09-10, steel 0.4.4) for ticket #221: the lean pluggable browser capability any session agent can use, built on the `steel --json` exec surface.
No operator unknowns blocked design, so no questionnaire was issued; where the ticket pre-decided (eval in the surface, CLI in the images, no steel_crawl migration), the records below encode the ticket's ruling, not a new choice.
Companion precedent is the #220 auth-store tool contract (single implementation, contract rides the tool description, skill quotes verbatim).

## Spike matrix (the evidence every record below stands on)

Fixture target `https://the-internet.herokuapp.com/login` (canonical test login page), session `spike221a`, CLI-only, `--json` throughout.
Raw captures live under `/tmp/spike221_*.json` (host scratch, never committed); secret-bearing assertions below quote key names and presence booleans only, never values.

| Command | Verdict | Latency | Evidence note |
|---|---|---|---|
| `start --session` | pass | 4 s | Raw stdout carries `data.connectUrl` (775 chars) embedding `apiKey=` + `sessionId=` over `wss://` - redaction mandatory (D4). `data` keys: `connectUrl, id, inactivityTimeoutMs, liveUrl, mode, name, remainingMs`. |
| `navigate` | pass | 1 s | Returns `{title, url}`; reached the login page. |
| `snapshot -i` | pass | 1 s | Accessibility tree with `@eN` refs; username `@e6`, password `@e8`, login `@e4`. |
| `fill @eN` standalone | FAIL | - | `Unknown ref: e6`, 4/4 across `fill`/`type`/`setvalue`, CSS selector also fails (`Element not found: #username`) while the element provably exists (`find input` returns 2, `eval` reads `id="username"`). CLI 0.4.4 ref-resolution defect in the single-command path; `focus @e6` + `click @e4` on the same refs succeed. |
| `fill` inside `batch` | pass | ~4 s for 3 ops | `batch "snapshot -i" "fill @e6 tomsmith"` returns `{filled: @e6}` and `eval` reads `#username.value == "tomsmith"` - the value provably landed. D2 routes all text entry through `batch`. |
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

`start, navigate, fill, click, wait, snapshot, cookies, storage, eval, batch, stop`.
`get url` (used in the spike to read the current URL) is NOT admitted: the login-verification predicate (D9) reads the URL through `eval` (`window.location.href`), so no twelfth command is needed.
Anything outside the eleven (tabs, screenshots, PDFs, file upload, drag, `set headers/useragent/geo`, profiles, credentials injection) is refused by the seam: the capability targets login-scale interaction, and each admitted command must earn its place against a login/extraction need.

**Rationale.**
A small allowlist is the safety bound the ticket's eval question is really asking for: the risk is not one command but an open-ended browser remote-control surface. Eleven spike-proven commands, each mapped to login or extraction, keep the surface reviewable in one screen.

## D2 - All text entry rides `batch`; refs never cross a navigation

`fill`, `type`, `setvalue` are never invoked standalone: the seam executes every text-entry act inside a `batch` whose FIRST element is `snapshot -i`, followed by the entry commands against that snapshot's refs, followed by the submitting act where the flow calls for it.
Refs from a returned snapshot are valid for the immediately following call only, and never across a `navigate`: a fresh snapshot opens every post-navigation sequence (the vendor's own discipline - element refs expire).
The spike's stale-ref curiosity (a previous batch's `@e6` still resolving after a renumbering snapshot) is therefore never depended upon: same-batch snapshot-then-act is the only sanctioned ref flow.

**Rationale.**
The CLI 0.4.4 single-command ref-resolution defect (spike matrix) makes standalone text entry a guaranteed failure; `batch` is the proven shape AND the ticket's latency answer (one spawn per sequence). Encoding it in the seam, not in agent prompts, keeps agents from rediscovering the defect one failure at a time.

## D3 - `eval` is permitted, purpose-bounded by skill discipline, audit-logged

`eval` stays in the surface (the ticket lists it as login-relevant, and D1's URL-read plus D9's extraction reads depend on it).
No mechanical JavaScript subset is enforced: a read-only-JS allowlist is unenforceable at the seam (any expression can mutate), and claiming one would be false closure (`CODING_STANDARD.md` §12).
The real bounds are three: the SKILL restricts `eval` to login/extraction purposes (reads plus the D2 interaction fallback); every evaluated expression is recorded verbatim in the tool result (audit, so a reviewer sees exactly what ran); the eleven-command allowlist (D1) keeps `eval` from becoming a general compute escape - it runs in the page, against the target, for the flow.

**Rationale.**
The ticket pre-decided inclusion; the grill's job was the scope question. Purpose-discipline plus audit is the strongest HONEST bound: it admits what cannot be mechanically prevented and makes it reviewable instead.

## D4 - Redaction sits at the seam, ahead of results, context, and logs

The seam strips Steel platform secrets from raw CLI stdout BEFORE constructing tool results: `data.connectUrl` (bearing `apiKey=` + `sessionId=`, proven present in the spike's raw `start` output) and viewer URLs (`liveUrl`, the `viewerUrl` in `sessions` output) are dropped wholesale.
The tool result for `start` carries only `{id, name, mode, timeouts}` - everything the flow needs to name its session, nothing that authenticates as the operator.
Token-shaped is defined as: a `wss://connect.steel.dev` URL, an `apiKey=` query-param value, a `sessionId=` value outside the seam's own session-name bookkeeping, or the literal `STEEL_API_KEY` value.
The acceptance test is failing-first: raw `start`-shaped stdout (synthetic secrets in the live-observed shape, fixture committed from the spike's key layout) enters the seam, and the test asserts no token-shaped value reaches tool results, context, or logs.
`STEEL_API_KEY` itself never leaves the environment: the CLI resolves auth from the environment, so the key is never interpolated into an argv the seam builds.

**Rationale.**
Tool results flow into agent context and Langfuse traces; redacting only at the logger leaves the context exposed. The seam is the single chokepoint every browser act funnels through (`CODING_STANDARD.md` §8), so it is the only locus where the guarantee can be total rather than per-caller.

## D5 - Two secret classes: platform secrets are stripped, target-secret values are withheld from logs

The spike's audit-logging answer (D3) collides with credential hygiene: `fill` arguments carry TARGET secrets (operator-supplied test passwords), and echoing them into results/logs would trade one leak for another.
The seam therefore keeps two classes apart: platform secrets (D4 - stripped everywhere, never executed-with except by the CLI's own env resolution) and target-secret command values (`fill`/`type`/`setvalue` text, `storage set` values, `cookies set` values), which ARE executed (the page needs them) but are withheld from tool results and logs - results echo `{filled: @eN}` (the CLI's own shape, which never echoes values) and logs record command names plus refs, never values.
The auth store (#220) remains the home of target credentials at rest; the seam only ever holds them in flight.

**Rationale.**
Not distinguishing the classes fails both ways: treating passwords like API keys breaks login, treating API keys like passwords leaks platform access. The CLI's value-never-echoed result shape makes the distinction cheap to hold.

## D6 - Stop is unconditional; the seam owns the whole named-session lifecycle

Sessions are named `polymerhus-<flow>-<id8>` (never the `default` session - the spike showed a foreign `default` session live, which the seam must neither use nor stop).
The seam creates the session at flow start and stops it in a `finally` (context-manager shape): success, failure, and timeout paths all stop - stop-on-failure is enforced, never advisory, per the ticket.
Timeouts: `--session-timeout 600000` (10 min, generous against the measured ~15 s login flow) at `start`; the CLI's `--inactivity-timeout` default (120000 ms, observed as `inactivityTimeoutMs` in the spike's `start` output) stays as the orphan backstop.
Orphan detection is a seam helper, not agent duty: `reap_orphans(prefix)` lists live sessions under our prefix for harness/operator use, and the e2e assertion is "no live `polymerhus-*` session after the flow".

**Rationale.**
Whoever names a session must bury it; splitting creation from cleanup across caller and seam is how orphans happen. The finally-shape plus the inactivity backstop gives two independent guards (deterministic stop + self-release), either sufficient alone.

## D7 - One tool factory mirrors `get_crawl_tools`; the contract rides the tool description

`get_browser_tools(*, exec_fn=None)` returns the browser tools filtered to `BROWSER_TOOL_NAMES`, injectable `exec_fn` defaulting to the real CLI runner - the exact shape of `steel_client.get_crawl_tools` (`src/polymerhus/recon/crawl/steel_client.py:105-125`) with subprocess in place of the in-process provider.
Per #220, the tool description IS the contract (single implementation, no per-consumer paraphrase), and the repo skill quotes it verbatim.
`steel_configured()` (credential-present check, `steel_client.py:59-64`) is reused, not reimplemented: the seam refuses to run unauthenticated with the same error shape.

**Rationale.**
`CODING_STANDARD.md` §8 (one behaviour, one implementation) plus the #220 precedent: the second capability surface reuses the first's proven contract shape instead of inventing one, so a reader who understands `get_crawl_tools` already understands `get_browser_tools`.

## D8 - The skill is a flat repo skill on the shared loader; duplicate readers are already gone

*Amended 2026-09-16 on rebase onto #222 (`5064ecd`): the role-routed skill path this record first named is stale - the catalogue went flat.*

The skill is `skills/steel-browser/SKILL.md`, with its operation references beside it as `references/*.sh` (#222/#234 catalogue: flat, `name` == directory, no role-routing layers; role prompts are NOT skills and live in module `prompts/` dirs).
It loads through the shared loader `skill_for` (`src/polymerhus/app/llm/skills.py`) and, on demand, through the agent-callable `load_skill(name)` tool that calls that same loader internally - so bake-time mounts and runtime loads return byte-identical bodies.
The skill body quotes the `steel_exec` contract verbatim and carries only the discipline the tool description cannot: the snapshot-then-act ref flow, the batch-routed text entry, the inline-`eval` escaping and result bounding (D14), the trap-owned stop on every path (D13), and the timeout ordering (D11).
Per-agent binding of the skill into the L1 index (`context={"skills": [...]}`) is deferred past #221: the #222 D3 reversal wires `load_skill` and the index middleware on every stateful agent but leaves per-agent skill-set configuration open, so this stream ships catalogue content plus the operation references and records the gap.
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

## D13 - Semantic session names with a uniqueness oracle

Names encode flow semantics (`polymerhus-<flow>-<id>`), chosen by the agent per skill - never uuid-opaque, never seam-invented. Uniqueness is checked at creation: `steel browser start` silently ATTACHES to an existing name (proven live 2026-09-11: second start returns success, same shape), so start alone cannot detect collision; `steel browser sessions` is unusable as the oracle (proven live: lists empty while a session is demonstrably live and addressable). The oracle is `steel browser live --session <name>`: success means TAKEN (refuse with `<name> is already used`), the typed `No running session` error means free. The check-then-start race (TOCTOU) is documented and accepted at login scale; consequence of a lost race is a shared session, bounded by the semantic-name discipline. This is the tool's sole special-case of session lifecycle - a namespace guard, not a capability allowlist - so loose coupling on operations is preserved.

## D14 - Inline eval by default, skill-carried escaping, files for promotion only (amended: file-first retired)

Supersedes the file-first rule below it. Rationale for the reversal: agents develop JS probe-then-persist (REPL-style inline iteration, then keep what works) - file-first inverts the loop, forcing a write round-trip per probe and assuming first-try success. And the dominant in-browser use beyond auth is vulnerability-test execution, an unbounded-read primitive: the design risk is data explosion, not quoting, so the guardrail belongs on result shape.

The discipline, owned by the skill: eval runs INLINE, with the skill carrying steel CLI usage verbatim plus a dedicated eval section citing the snippet format and the common writing pitfalls (single/double/backtick nesting through the JSON-arg and shell layers; `$` expansion; the IIFE-returns-plain-data format; the two live-proven traps - a path argument parses as a regex literal, a bare `-` evaluates as source). Result bounding is a hard rule: project before return (counts, slices, targeted selectors over whole-document dumps), chunk large extractions, prefer booleans for checks. Files are the promotion path, not the default: a proven snippet graduates into `/work/<session_id>/js/` for reuse inside `.sh`/`.py` automation scripts (which chain multiple steel cmds, EVALs included) and as audit trail - fed then via `"$(cat …)"`, which stands as the mechanism, demoted from the discipline.

## D14 (original, superseded) - JS executes from files, fed via substitution

`steel browser eval` accepts an inline expression ONLY: no `--file` flag (`eval --help`), no stdin (`eval -` evaluates the literal `-`; proven live), a path argument evaluates as JS source (proven live: the path parses as a regex literal and fails). Kali-side `.sh`/`.py` scripts are automation scripts, never browser JS. The discipline, owned by the skill: every non-trivial JS snippet lives in a file under `/work/<session_id>/` and is fed as `steel browser eval "$(cat <file>)" --session <name> --json`. Proven live 2026-09-11: multi-line JS carrying single quotes, `$`, and backticks round-trips byte-exact (`Example Domain | it's $100 \`quoted\``) - double-quoted substitution output is literal, never re-expanded, so the file rule deletes the quoting class for JS entirely. Inline expressions remain only for trivially safe reads (`document.title`, `location.href`).

## D15 - Transcript lives in Langfuse, not in a file

No `steel.log` file. The execution transcript (tool args, stdout JSON, returncode, duration) reaches the observability platform as MCP tool spans through the established callback pattern (`get_langfuse_callbacks` passed at invocation, inert `[]` when unconfigured - the `execute_command` precedent, which the trace viewer already renders as command-plus-output spans). Nothing new runs on kali and no exporter is added there. Per-command granularity inside scripts comes from progress markers echoed to stdout, which the envelope carries into the trace. Rationale: one observability path for all tool calls (the doc already notes the crawl tools' spans as the unwired exception - steel_exec is wired from day one by riding the mechanised path).

## D16 - Steel skill data: operation references under skills/, coupled to #220 on the data plane

Reusable browsing-operation scripts live as `references/` beside the steel CLI skill under repo-root `skills/` (one script per reusable operation; no exploitation PoCs, no vulnerability-testing payloads - that boundary is absolute). Session workdirs hold a run's copies and evidence only; the canonical login scripts are AUTH-SKILL-1's (`#220`, which owns login procedures and per-method references authored with the auth skill). The data-plane split, so neither stream authors twice: the auth store holds WHAT (accounts, credentials, tokens, profile refs, snapshots, technical conditions, the `procedure` label hook); the auth skill holds the login PROCEDURES; this steel skill holds the operation MECHANICS the procedures are written in (session lifecycle, snapshot-ref handling, inline-eval escaping and bounding, trap-stop, timeout ordering). Arrows: `procedure` labels resolve to procedures composing steel operations; extraction reads (cookies/storage/eval) produce the material agents write as concrete request snapshots (the #220 bootstrap-capture future); technical-condition checks execute through steel reads. Joint out-of-scope on both sides: Steel profile lifecycle administration.

## D17 - Server-side profiles replace session-context shuttling

Operator decision from the #220 stream: durable browser identity lives in Steel profiles (long-lived named server-side state), not in client-side session-context JSON. What the skill procedures and references must encode, concisely: mint on first login (`start --profile <name> --update-profile`, profile id recorded to the auth store steel reference); mount by id with an explicit write discipline (`--update-profile` present accumulates, absent mounts read-only - recon-style browsing defaults read-only, write-back only past the verify gate); settle-then-verify on every mount (the API's poll-READY has NO CLI equivalent - `profile list` returns name plus id only, verified live - so settle pause plus verify-by-navigation is the procedure, and an unverified mount never passes a verdict); explicit release on every path (release is the persistence call; timed-out sessions still write, Failed ones skip it, so any abnormal end forces re-verify); one live session per profile (last-writer-wins, no merge - skill rule plus the #220 per-project locks); hard timeout at create plus inactivity backstop. Tool side impacts: none on the tool contract (profile flags ride in command strings; the uniqueness oracle is orthogonal); two honest constraints - no state-poll primitive exists to offer, concurrent-mount guarding stays out of the tool (would couple it to flag parsing), and `stop --all` is unusable for reaping (kills foreign sessions) while prefix-scoped reaping is blocked by the unreliable `sessions` listing, so platform inactivity is the primary orphan defense with best-effort reaping over skill-tracked names.

## What was deliberately NOT decided here

- `domain-model.md` is unchanged by this ticket: the seam introduces capability infrastructure inside Recon, not a new primitive, relationship, or open question in the reasoned ontology. Per `CONTEXT-MAP.md`'s helper-modules ruling, capability vocabulary lives in the owning context's glossary (`recon/CONTEXT.md`: exec gateway, named session, the #220-owned profile split; the redaction-boundary entry retired with D4/D5), never as ontology.
- The exact Dockerfile install stanza (binary download URL, checksum) is fixed at implementation with a built-image `steel --version` proof, not guessed here.
- The consuming login flow (ticket 5) and the fallback leg (ticket 4) are out of scope; this ticket ends at proven primitives plus the skill.
