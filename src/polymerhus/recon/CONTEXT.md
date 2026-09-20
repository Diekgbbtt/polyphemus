# Recon

Layer-0 descriptive attack-surface discovery.
This context observes a target from the outside and records what tools witnessed as a graph of typed L0 nodes; it never judges what any of it means (that is [Analysis](../analysis/CONTEXT.md)).
It also owns the pipeline that orchestrates discovery - Run, Job, Phase, Pod - which by operator ruling are elements of the recon pipeline and live here, not in a separate context.

Vocabulary derived from `docs/design/domain-model.md` (esp. §2.1-2.2, §5, §7); see also `docs/design/recon-pipeline-design.md`.

## The surface and its atoms

**Attack surface**:
The total set of loci at which a tester can present input to the target and observe a consequence.
Its irreducible atom is a locus where externally-controllable input crosses into the system - an Endpoint together with the Parameter or Header that carries the input - not "the application" and not a lone Endpoint.

**Layer 0 (L0)**:
The observed store: a claim here is descriptive, and its truth condition is "a tool witnessed this feature of the surface at a moment in time".
_Avoid_: L1, the judged store (that is Analysis).

**L0 node**:
A typed node in the observed store, drawn from a small fixed label set: `Domain, Subdomain, IP, Port, Service, DNSRecord, BaseURL, Endpoint, Parameter, Header, Certificate, Technology, Secret, Traceroute, ExternalDomain`.
Each exists only because a tool witnessed it.
_Avoid_: asset (loose synonym; prefer the specific label).

**Endpoint**:
A reachability fact - a path that responded.
Input-carrying capability is not on the Endpoint itself but on the Parameter and Header nodes that hang off it.

**profile** (`webapp` / `restapi` / `graphql_api`):
A per-Endpoint classification of the surface an Endpoint exposes, derived from its own httpx-observed content-type (+ host-label / GraphQL-path signals) by `noise_filter.classify_profile`.
Every produced Endpoint is profiled by the `httpx_reprofile` pass (#208: the pass is ONE pod over the dedup'd probe set - `prepare_endpoint_profile_assets`' dynamic-route collapse + root `/` materialisation - paying O(1) triager turns per job, superseding the D16 per-endpoint pod fan-out; the iteration set is unchanged), not just BaseURL roots - so an API mounted under a `webapp` root is visible.
`BaseURL.profile` is the backward-compatible mirror of its root `/` Endpoint's profile.
The profiling pass is enrichment only: it fills gaps (methods/parameters/headers/response shapes) on already-collected endpoints, never re-discovers; production (the profile stamps) and consumption (the triager's Observations) are structurally decoupled, so a triager failure never loses the parsed profiles.

**API scope** (kiterunner):
The evidence-derived API-root prefix a fuzzer is scoped to, computed by `api_scope.derive_scan_targets` from a host's `restapi` Endpoint paths (last api-noun cut, versions left as fuzz-space, parent-dir fallback). Not a naming classifier - the gate is the content-type `profile`; the noun set only picks the cut depth.

**Parameter / Header**:
Parameter nodes are the input-carrying atoms that hang off an Endpoint; they, not the Endpoint, express that a user-controllable input reaches a sink.
Header nodes as minted today are RESPONSE headers (httpx `-irh` / katana `response.headers`), hung off their BaseURL via `HAS_HEADER` with `direction="response"` - observed surface, never replayed into requests.
Request headers come only from the auth feed (the store-resolved account projection, serialised per tool into the `{auth_flags}` command slot solely for `use_auth` jobs); since #223 the material resolves lazily from the auth store via the account identifier bound into the pipeline state by the orchestrator (never the retired settings blob, D223-4 / D223-19); no code path reads `:Header` nodes to build a request, so a `Set-Cookie` value can never become a request `Cookie`.

**Service (L0)**:
A network service discovered on a Port (the descriptive node label).
_Not to be confused with_: the L1 `Service` (a reconstructed business target), which is an entirely separate concept owned by Analysis.

**Secret**:
An L0 node for credential-like material witnessed on the surface (e.g. read out of a JS bundle).
_Not to be confused with_: a DataItem (Analysis), which is a judged logical data record, not a raw witnessed string.

**Observation**:
An adversarial natural-language insight the triager reads out of tool output - deliberately NOT a restatement of a witnessed primitive (an HTTP status or an SSL cert is a primitive, not an Observation).
Despite the name it is a *low inference*, not a pure observation in the epistemic sense; genuine directly-witnessed facts are the typed L0 nodes themselves.
_Avoid_: finding, primitive, restatement.

## The pipeline

**Project**:
The operator-scoped unit of work: a target, its scope, the free-text `operator_kb` business framing, and settings.
It is the boundary at which identity and idempotency currently hold.
_Avoid_: engagement, target (target is the thing under test, not the record).

**Seed** (`target_seed`):
The single string that names what a Project probes, seed-type-agnostic (D-HS): a domain (`example.com`, `*.example.com`) or a bare IPv4 (`93.184.216.34`).
`resolve_seed` reads it, falling back to the deprecated `target_domain` alias so already-persisted projects still launch.
_Avoid_: target_domain (the legacy, domain-only name).

**Scope mode**:
The shape `parse_scope` gives a seed, driving which jobs run: `wildcard` (a zone, discovery runs), `exact` (one host, discovery suppressed), or `host` (a bare IP - discovery and the passive harvesters suppressed, the IP probed directly).
An IP's engagement root is an `IP` node, never a `Domain`; the whole web-discovery chain then unfolds from httpx's `BaseURL`s exactly as for a domain (D-HS).
_Avoid_: treating a mode as an asset type (it is a routing decision, not an L0 label).

**Run**:
One execution of the pipeline over a Project's phase plan, keyed by `run_id`.
Re-running re-derives the graph rather than duplicating it.
_Avoid_: scan, session.

**Phase**:
An ordered stage of the phase plan whose jobs run before the next stage begins; each phase seeds the next from the assets the prior phase produced.
_Avoid_: stage, round.

**Phase barrier**:
The hard boundary between phases: every Job in a phase (and all its pods) completes before any Job in the next phase starts, bounding peak concurrency to a single job's pods.
_Avoid_: sync point, gate.

**Job**:
A single tool-execution specification (`JobSpec`: a tool, a skill, a command template, what it consumes and produces) run within a phase, fanned out over its input population into pods.
_Avoid_: task, step.

**Pod**:
The per-input-asset execution unit that runs one Job against one input asset, invokes the tool, and emits asset deltas and Observations.
_Avoid_: worker, container (a Pod is the graph-runtime unit, not a k8s pod).

**Asset delta**:
The unit of L0 write a pod emits: a typed node with identity, props, and edges, proposed for the curator to merge.
_Avoid_: patch, diff.

## Actors and authority

**Curator (L0 sole-writer)**:
The single module (`src/polymerhus/recon/domain/curator.py`) authorised to write the L0 store: it enforces identity, stamps provenance, validates every label and edge against a fixed allowlist, and is the boundary between "proposed" and "true in the graph".
_Avoid_: writer, persister.

**Sole-writer**:
The principle that each store has exactly one authority that turns a proposal into a fact; it is what lets provenance-on-write and idempotent identity be guarantees rather than hopes.
The L1 counterpart is the `l1_curator` (Analysis).

**Triager**:
The LLM proposer role that reads raw L0 tool output into adversarial Observations; it holds judgment but no write authority.
STATEFUL as of #94: it runs on a per-concurrent-pod session (`PodSession`, `recon/domain/pod.py::pod_session`), keyed by the pod's `(phase, tool, input-asset)` discriminator so several pods of one run never share context; the triager node binds the session on a ContextVar (`app/llm/session.py::stateful_turn`).
_Avoid_: analyst, classifier.

**Configurator**:
The role that resolves a Job's command for a target; a `deterministic` template fill by default, or an `agent` mode (the Steel crawl).
The per-pod steering-fed throttle turn retired with the mid-run steering machinery (#243, D223-12): the configurator node fills the command deterministically and no `rate_profile` input exists - request phases run unthrottled in the interim until the #238 rate-limit work lands its profile-driven configuration, which the still-registered `configurator` session role (`LLM_CONFIGURATOR`) is reserved for.
_Status_: registered `session` (`LLM_CONFIGURATOR`).
_Avoid_: planner; mid-run routing.

**Job orchestrator**:
A resumable `session`-mode role (`role_id=job_orchestrator`) validated at app boot.
Since #223 (T3 #242) it runs as the per-run AUTH GATEWAY
(`orchestrator_agent.py::ReconOrchestratorActor`): one `run_session_agent` on the
run's `OrchestratorSession` thread taking exactly ONE gateway turn before phase 0 -
the authn loop over the armed surface - closing with the structured
`GatewayVerdict`. `run_pipeline` constructs the actor deterministically on run start
(never lazily, never behind a signal gate), awaits the verdict under heartbeat and a
wall-clock bound, then configures from it: browser-only prunes the plan to the Steel
crawl, and the selected account's identifier rides the pipeline state (`extra`
`auth_account` on `use_auth` jobs, never the material) for the feed to resolve.
Mid-run steering is removed entirely (#243, D223-12); a degraded
gateway fails open (every phase, unauthenticated, loudly); missing credentials stop the
run loudly (`GatewayStop`, fail-close).
_Status_: registered `session` (`LLM_JOB_ORCHESTRATOR`).
_Avoid_: planner; mid-run routing.

**Operator**:
The only human, and the source of intent the system is blind to by design: supplies the target, scope, `operator_kb` framing, and settings.
Deliberately kept blind to the target's true identity (it analyses `soupmarket.shop` without being told it is Juice Shop).

## Auth store (#220)

**Auth store**:
The per-project shared auth bucket served by `AuthStore` (`app/auth/store.py`) over `data/<project_id>/auth/` under the app-owned data root (`app.data_root.DATA_ROOT`, `<repo>/data/`, resolved through the one layout owner `project_dir`): `credentials.yaml` (the `{accounts: ...}` map) plus the operator-owned `overview.yaml` header, lazily created at the first write.
Reads are `read(project_id, path)` dotted projections (empty path returns the full `{"overview": ..., "accounts": ...}` state; a missing path is a valid empty); writes are `write(project_id, path, value, origin=...)` single-field merges, every file write atomic (temp file + `os.replace`) under a per-project `threading.Lock`.
_Avoid_: the retired settings blob (`AuthContext`; #223 D223-4 removes its footprint, the store is the agents' shared runtime state).

**Account record**:
One named bundle validated by `validate_account` (`app/auth/records.py`, mirrored never imported upward): `origin` (stamped server-side, `operator` or `agent`), optional `procedure` label, `credentials`, `tokens` (each `{value, location: cookie | header | storage, target?, expiry?}`), `steel`, `snapshot`, `notes`, plus FR-AUTH `roles` / `default_role`, the #223 validity fact (settled key `status`: `valid` | `not_valid`, absent until asserted, anything else a loud `auth_invalid` refusal, D223-14) and the server-stamped recency fact (settled key `updated_at`: stamped on every write and seed, a client-supplied value overwritten never trusted; selection via `select_recent_usable_account` is most-recent first, ties to list position newest-last, `not_valid` records skipped as unusable, D223-18).
Record identity is the account name, which carries the credential identity: name an account `<email>-<minting_context>` (the credential username plus the run or flow that minted it, never the procedure), so two procedures serving one credential identity share one name and the second write fails with `DuplicateAuthError` (`duplicate_auth`) instead of forking.
The store also gates the credential identity itself (D220-11): a create or seed whose username (default `credentials.username` or any `roles.*.username`) already belongs to another account fails with `DuplicateIdentityError` (`duplicate_identity`), because access for a known identity is a new ROLE on the existing account, never a second account.
_Avoid_: forking a record (first writer wins; reflect, merge, or refresh), and naming by role or procedure (`primary`, `sign-up`) instead of by the credential identity.

**Operator section vs agent section**:
The provenance split inside the bucket (D220-12 retires the trust-boundary refusal): the operator section (the `overview.yaml` header plus `operator`-stamped accounts) is the operator's ground truth and is WRITABLE by agents, who merge into it (tokens, status, snapshot, steel, notes) while the stored `origin: operator` stamp is preserved as provenance; the agent section (`agent`-stamped accounts) is what the `auth_store` tool mints.
_Avoid_: treating `origin` as a permission (it is a provenance label; the only refusals are `duplicate_auth`, `duplicate_identity`, `auth_invalid`, `store_unavailable`).

**Technical condition** (`overview.technical_conditions`):
An optional overview-level list of `{name, check}` entries (absent by default), validated by `validate_overview`: the assertable procedure conditions to verify when a login fails unexpectedly while following the procedure in the overview.
_Avoid_: replay-manner (the deleted enum; conditions are data, not a manner).

**Anti-bot defence type** (`overview.anti-bot`), #237:
The optional typed fact naming the target's WAF or anti-bot defence - a vendor, product, challenge, or `waf:<name>` string, or null when none - validated by `validate_overview`; the external authn bootstrapper establishes it by probing and response-shape inspection.
It is a different axis from the blocking-signal classification (`waf_protected` / `waf_detection` / `rate_limited`): the signal says a block fired, the type names the defence behind it.
_Avoid_: a closed vendor enum (the vendor space is open; research the block pattern before naming it).

**HTTP-client replayability** (`overview.http-client-replayability`), #237:
The optional typed fact stating whether the browser-trusted authenticated context replays through a plain HTTP client: `true` (replayable, its static/dynamic continuation facts carried in the authn skill) or `false` (browser-only), validated by `validate_overview`; unset means UNKNOWN and is deliberately distinct from `false`.
_Avoid_: reading absence as false (unknown is a third state).

**Continuation facts** (static vs dynamic shape elements), #237:
The replay procedure content - which headers, cookies, parameters, and token locations are replayable as-is versus must be re-minted or are browser-bound - authored into the per-project `authn` skill rather than stored; the store keeps the concrete values (`snapshot`, `tokens`) and the two typed facts.
_Avoid_: procedural prose in the store (steps live in the skill, facts live in the store).

**Browser-profile reference** (`steel: {profile}`):
The minimal durable Steel profile key on an account record: the next agent rebinds the same profile through its browser tool, secrets never touching the store.
Since #223 the key is project-scoped (`<project_id>-<account>`, D223-14); the browser path mints through `steel start --profile <key> --update-profile` and persists the key plus extracted tokens back to the record; a missing or unauthenticated mount fail-opens into sign-in with the account asserted `not_valid`, never a silent anonymous turn.
_Avoid_: storing browser state itself (only the key lives here).

**Concrete snapshot** (`snapshot: {headers, cookies, params, captured_at}`):
Point-in-time captured request state on an account record, validated by `_check_snapshot`: the exact state request-based followers replay, never a stored graph query.
_Avoid_: graph queries (no `cypher` lives in the store; static queries against a changing surface fail silently open).

**Operator seed** (`PUT /projects/{project_id}/auth` -> `seed_project_auth` -> `AuthStore.replace_operator_state`):
The operator's wholesale replace of the operator section: each present section (`overview`, `accounts`) replaces wholesale (absent sections untouched), seeded accounts stamped `operator` server-side, `agent`-stamped accounts never modified or removed, both sections validated before anything lands; an agent's edits inside a seeded account are replaced by the seed (D220-12).
A seeded operator name colliding with a live agent record warn-drops the operator entry, preserving the agent record; there is no conflict path (replace, never 409).
_Avoid_: extending the settings blob (the seed is a separate face over a separate bucket).

**Procedure label** (`procedure`):
The store-to-skill coupling name on an account record (optional non-empty string): it names the skill procedure that minted or serves the account; all procedural knowledge itself lives in the one future auth skill, not in the store.
_Avoid_: procedural knowledge in the store (the store carries only the label).

**Auth-store tool** (`auth_store`, built by `build_auth_store_tool`):
The one shared read/write agent tool over the store, bound to its project id at build time; the id defaults to the control-plane project (`config.PROJECT_ID`) resolved lazily inside the factory, so no agent harness threads identity; its usage contract (`AUTH_STORE_CONTRACT`) rides the tool description verbatim.
Origin through this tool is always agent; every failure arrives as an in-band coded envelope (`duplicate_auth`, `duplicate_identity`, `auth_invalid`, `store_unavailable`) - nothing raises into the turn.
_Avoid_: a second tool face (one implementation, bound per project).

**Auth-capable binding** (`auth_capable_binding`, `app/auth/seams.py`):
The auth-capable extension of `skill_agent_binding`: the same L1 index middleware, skill tools, and invocation context, plus the `auth_store` tool and the per-project `authn` procedure in the bounded skill set.
The analysis-domain agents never bind it; since #223 it arms the recon orchestrator write-capable in one step (the roster still declares it exempt - no catalogue skill bears - so the arming rides `with_write_skill`, never the roster: `auth_store`, `authn`, `load_skill`, `write_skill`, kali `exec`, `steel_exec`, D223-13) - and the recon job-specialised agents deliberately never take it (D223-5).
_Avoid_: a per-site auth binding (one seam, attached through `tools=` / `middleware=` / `context=` like every other capability).

**`authn` (per-project authentication procedure)**:
The project-authored skill (no canonical catalogue copy) that the meta skill `meta/authn-skill-writing` produces; it is collected into an auth-capable agent's L1 index only when its bundle exists at `<data_root>/<project_id>/skills/authn/SKILL.md`.
_Avoid_: a canonical `authn` skill (a project's copy is its original).

**Auth feed** (#223 T4 #243, D223-19):
How authenticated jobs receive their material: the gateway verdict binds only the selected account's IDENTIFIER into the pipeline state (`extra["auth_account"]` on `use_auth` jobs, never the material); each phase's tool configuration resolves that account from the auth store at assembly and projects only the subset its tools need - the flat request material (snapshot headers plus header-located tokens, snapshot cookies plus cookie-located tokens) through the existing `extra["auth_context"]` transport, serialised per tool into the `{auth_flags}` command slot at fill time; the persisted Steel profile key (`extra["steel_profile"]`, mounted read-only at Steel session creation via the SDK `profile_id`) plus the cookie subset seeding the browser context for the agent-driven crawl; nothing for non-auth jobs. Role/default-role selection resolves over the account record. The settings-blob auth path, the interactive crawl auth, and mid-run steering are removed with their footprints (D223-4 / D223-12).
_Avoid_: threading material through the pipeline state (the identifier rides; the projection resolves per phase).

**Authn loop** (the auth gateway, #223):
The recon orchestrator's pre-pipeline stateful turn - used by that role only - that establishes or validates the run's auth state against the auth store BEFORE the pipeline is configured: one ReAct turn with a hunting-style passive state machine over its own tool calls (`recon/control/authn_loop.py`: GROUNDED -> RETRIEVED -> VALIDATION -> GENERATION -> DEBUG -> FINISH; detection pure of the observed call, pushes never gating, hints riding the triggering tool result only inside `<authn-loop-hint>`), closing with the structured gateway verdict.
The verdict (`GatewayVerdict`: `outcome` authenticated | anonymous | failed, `account` identifier-only, `branch` request | browser_only, run-scoped `replayability_resolved` / `replayability`, `rationale`) carries the selected account identifier, the no-auth-surface finding, or the failure mode; the orchestrator alone prunes phases and configures the pipeline from it (mid-run steering is retired, D223-12), and the account identifier - never its material - rides the pipeline state for lazy per-phase resolution by each phase's tool configuration (D223-19).
The pre-loop branch directive follows the four-way overview contract (`request` | `browser_only` | `request_browser_first` | `resolve_in_loop`, D223-11); the null case resolves in-loop and is logged loudly, never persisted.
An empty store with no authenticated surface is the expected shape with its own path - loop skipped, pipeline run anonymously, verdict records it; the structural marker is `overview.notes` carrying "no authenticated surface" (D223-17, settled #242); a declared surface with no accounts fail-closes by stopping.
_Avoid_: a per-job auth loop (the job-specialised agents never authenticate, D223-5); a "coverage exhausted" verdict state (exhaustion is a failed authentication, D223-3); re-adding mid-run auth steering.

## Prompts, skills, and the loader

**Role prompt**:
A role's system prompt, living with its owning module in a `prompts/` directory as plain Markdown (no frontmatter) and read directly by its module - fail-closed (a missing file raises), memoized, no cross-module imports.
_Avoid_: skill (on-demand knowledge, never role identity).

**Skill**:
A Markdown reasoning discipline (`skills/<name>/SKILL.md`, `name` == directory) loaded on demand through the shared loader - never as a role prompt.
_Avoid_: tool (a tool is called; a skill is read).

**Skill loader (single loader)**:
The one module (`src/polymerhus/app/llm/skills.py::skill_for`, FR-SKILLIF) authorised to read skills: it strips the YAML frontmatter, caches the body, and degrades to a fallback on a missing mount.
Only on-demand skill readers call it; no role prompt loads through here.
_Avoid_: a second skill system.

**Data section**:
The spec frontmatter contract every skill carries (`name` == directory, `description` = what + when, `metadata` string map carrying `version`), so a runtime consumer can index, validate, and report what was loaded.
_Avoid_: prose header (human-only, unvalidatable).

**Runtime loading**:
Two tiers. L1 discovery: an agent's bounded skill set rendered as name + description lines into its system message by the shared skill-index middleware (bound per agent through the native invocation context). L2 activation: loading a skill mid-run through the agent-callable `load_skill(name)` tool, which returns the loader-identical body. It decouples skill evolution from prompt bake-time; bake-time reads and runtime loads can never diverge because both call the single loader.
_Avoid_: convention-only gating (the index is composed by middleware, no model cooperation needed).

**Skill binding (bounded skill set)**:
The per-role roster of which catalogue skills a tool-calling agent may load (`ROLE_SKILLS`, keyed by `role_id`) and the one call every bound agent site makes to bind it (`skill_agent_binding(role_id)`: index middleware + skill tools + the invocation context carrying the set).
The skill-domain analogue of the tool-bounding pattern - a declared, minimal set the owner attaches through one native seam, never the whole catalogue.
A role with no bearing skill is declared EXEMPT (an empty tuple) and binds nothing at all (no `load_skill` tool, no index middleware, no context), and an UNDECLARED role id is refused at construction; the frontmatter `description` of every bound skill is rendered verbatim.
_Avoid_: per-site skill lists (drift), a `skills` field on the `Role` record (skill policy in the model-transport module), an empty index on a role that cannot use one.

**Per-project skill bundle**:
The project-owned skill directory (`<data_root>/<project_id>/skills/<skill>/`: `SKILL.md`, `references/`, `scripts/`, `assets/`) where an executing agent records what it learned using a procedure - a blocking condition, a new role, a privilege-escalation path - so sibling and later agents start from accumulated ground truth.
There is no canonical shared original; a project's copy is its original, created lazily on first write.
_Avoid_: editing the shared catalogue (a live run never mutates `skills/`).

**Skill store**:
The one authority that reads and writes bundle artifacts (`src/polymerhus/app/llm/skills.py::SkillStore`, #234), sharing the loader's seam: reads resolve the per-project bundle first, then the shared catalogue, so a project skill shadows a shared one without copying.
_Avoid_: a second skill system.

**Skill writer (`write_skill`)**:
The agent-callable write tool (`write_skill(skill, target, content)`): `procedure` carries the `SKILL.md` body alone, `references/<name>` writes one bulky reference file.
The store owns the frontmatter - `name`, `description`, and `metadata.version` bumped one minor per write, carried from the project's own metadata or copied over from the shared catalogue on the first update (bootstrap is operator-authorised; nothing synthesises metadata).
The factory binds the project, so an agent writes through its own project's bundle; any skill in it is writable (no per-skill writable set - the future `SkillEvolver` writes any skill).
Every write lands atomically under a per-project lock.
Failures arrive as coded in-band envelopes (`skill_invalid`, `skill_target`, `store_unavailable`); nothing raises into the turn.
_Avoid_: section edits, operation verbs (no revise/add/correct - whole files only), authoring frontmatter.

**Reading protocol (`meta/meta-usage-skill`)**:
The compact usage-protocol skill appended to every `load_skill` result by the read path itself, except meta-family skills (any loader path under `skills/meta/`, matched by `is_meta_skill`): assess the procedure against its stated observables during and after execution, separate a skill defect from an execution miss, and record reusable improvements through `write_skill`.
_Avoid_: prompt injection (the protocol rides the tool result, never the system prompt or compaction state).

**Authoring rules (`meta/meta-write-skill`)**:
The content-stable authoring instructions for writing a well-structured procedure rather than a note-dump: ordered steps closed by expected observables, valid frontmatter shape, bulky material behind `references/` pointers.
The future `SkillEvolver` reuses it unchanged.
_Avoid_: the note-dump (prose without steps, observables, or pointers).

## Browser capability

**Exec gateway**:
The single loosely-coupled `steel_exec` tool beside `execute_command`, accepting either a `steel`-token-routed command or a `.sh`/`.py` automation script, carrying no operation knowledge (that lives in the skill).
_Avoid_: per-subcommand allowlist, in-process driver.

**Named session**:
A cloud-browser session under an agent-chosen semantic `polymerhus-<flow>-<id>` name whose uniqueness is checked at creation against the live session catalogue (`steel browser sessions --json`: one read lists every live session with its name), stopped by script-trap on every path with platform inactivity as the backstop.
_Avoid_: the default session, an unchecked name, an orphaned session.

**Browser profiles**:
Durable browser identity lives in Steel profiles owned by the #220 stream; this stream mounts them by id only and defines no profile terms here.
_Avoid_: duplicating #220's profile vocabulary.
## Invariants owned here

**Fail-open**:
One bad delta never aborts a batch and a missing collaborator degrades rather than crashes; the accepted cost is that a dropped item is silently lost with only a log line.
The stateful triager (and every `session`-mode structured turn) holds this invariant at the LLM seam: a structured-output PARSE failure (`StructuredOutputValidationError`, e.g. a reasoning model returning a bare `[]` / empty / prose instead of the wrapped batch object) degrades to "no observations" (`stateful_turn` returns `None`), never fails the pod - so the already-parsed assets are still curated instead of silently dropped. The triager's `_ObservationBatch` also accepts those coherent empty-artifact shapes via a pydantic `model_validator(mode="before")`.
The MAILBOX actors hold the invariant at the turn seam as of #186: one raising LLM turn is contained per-turn (retry the retryable class under the bounded escalating budget, then degrade to a no-decision reply) and NEVER kills the actor - so the fail-open fires PER TURN, and every later phase/pair still rides a live actor (the pre-#186 actor death made each later turn fail-open through the dead-task race).
_Avoid_: fail-safe, fail-closed.

**Reasoning-token budget**:
Every LLM construction (`app/llm/providers.py::build_chat_model`) sends a generous `max_completion_tokens` (default 32768, override `LLM_MAX_COMPLETION_TOKENS`) - the reasoning-INCLUSIVE output budget. Reasoning models burn output tokens on `reasoning_content` before the answer; a tight `max_tokens` exhausts on thinking alone and the model returns `content: null` (`finish_reason: stop`) with no answer. The generous ceiling keeps a thinking-heavy turn (observed bursts ~9k tokens) able to emit its result.

**asset_context**:
The context string threaded end-to-end into every pod for the designed-not-built context-memory scaffold; today always the empty string.
_Status_: scaffolded, not built.
