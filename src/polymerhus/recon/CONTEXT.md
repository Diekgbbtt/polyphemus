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
Request headers come only from the operator's `auth_context` (pod `_auth_header`, injected solely for `use_auth` jobs); no code path reads `:Header` nodes to build a request, so a `Set-Cookie` value can never become a request `Cookie`.

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
The role that resolves a Job's command for a target; a `deterministic` template by default, or an `agent` mode.
STATEFUL as of feat/async-actor-agents: the pod graph's configurator node consults a per-concurrent-pod `configurator` session (`PodSession`, keyed like the triager) over the orchestration steering signals (`extra["steering"]`), decides the pod's `rate_profile` (throttling moved HERE from the job-level `decide_pod_selection`), and merges it before the command template is filled; fail-open (never a pod failure) and consulted once per pod even across gate retries.
_Status_: registered `session` (`LLM_MODEL_CONFIGURATOR`).
_Avoid_: planner.

**Job orchestrator**:
A resumable `session`-mode role (`role_id=job_orchestrator`) validated at app boot.
Since feat/async-actor-agents it runs as a per-run MAILBOX actor
(`orchestrator_agent.py::ReconOrchestratorActor`): one `run_session_agent` on the
run's `OrchestratorSession` thread, fed each phase's steering signals and replying a
structured `RoutingDecision` per phase, so its checkpointed memory carries the
steering reasoning across the run's phases. `run_pipeline` also accepts an
injected `decide_routing` seam for tests, but the production routing path is the
actor.
As of #186 its turns run PER-TURN ISOLATED on the shared actor runtime: a raising
phase turn (transport/timeout/5xx/429 retried under the bounded escalating budget,
then degraded) posts a NO-DECISION reply - the parent's fail-open fires per-turn
(`{}` = no routing adaptation for THAT phase) and the actor task SURVIVES, so the
run's later phases still get real routing (the pre-#186 dead-task race made every
later phase silently routeless).
_Avoid_: planner.

**Operator**:
The only human, and the source of intent the system is blind to by design: supplies the target, scope, `operator_kb` framing, and settings.
Deliberately kept blind to the target's true identity (it analyses `soupmarket.shop` without being told it is Juice Shop).

## Skills, the loader, and runtime loading

**Skill**:
A Markdown reasoning discipline (`skills/<path>/SKILL.md`) loaded as an LLM role's system prompt - the triager's writing-observations, the crawler's steel-crawl, the analysis proposers' skills, the hunting skills.
_Avoid_: tool (a tool is called; a skill is read).

**Skill loader (single loader)**:
The one module (`src/polymerhus/recon/domain/skills.py::skill_for`, FR-SKILLIF) authorised to read skills: it strips the YAML frontmatter, caches the body, and degrades to a fallback on a missing mount.
Every per-role reader retro-points here; no reader does its own file I/O.
_Avoid_: a second skill system.

**Data section**:
The machine-readable YAML frontmatter contract every skill carries (`name`, `description`, `version`, `inputs`), so a runtime consumer can index, validate, and report what was loaded.
_Avoid_: prose header (human-only, unvalidatable).

**Runtime loading**:
Loading a skill mid-run through the agent-callable `load_skill(name)` tool, which returns the loader-identical body.
It decouples skill evolution from prompt bake-time; bake-time mounts and runtime loads can never diverge because both call the single loader.
_Avoid_: bake-time mount (the prompt-composed path, still the default for static disciplines).

**Phase-gating (convention)**:
The rule that bounds runtime loading: load at phase entry, once per thread, never speculatively mid-reasoning.
Bake-time mounts follow the same rule (the hunting gate skill mounts once per thread as the run's one system message; the crawl loop loads once at loop start).
_Avoid_: enforcement (there is no mechanical gate; the convention is demonstrated by the reference flows, not compiled in).

**Per-project skill bundle**:
The project-owned skill directory (`<data_root>/<project_id>/skills/<skill>/`: `SKILL.md`, `references/`, `scripts/`, `assets/`) where an executing agent records what it learned using a procedure - a blocking condition, a new role, a privilege-escalation path - so sibling and later agents start from accumulated ground truth.
There is no canonical shared original; a project's copy is its original, created lazily on first write.
_Avoid_: editing the shared catalogue (a live run never mutates `skills/`).

**Skill store**:
The one authority that reads and writes bundle artifacts (`src/polymerhus/recon/domain/skills.py::SkillStore`, #234), sharing the loader's seam: reads resolve the per-project bundle first, then the shared catalogue, so a project skill shadows a shared one without copying.
_Avoid_: a second skill system.

**Skill writer (`write_skill`)**:
The agent-callable write tool (`write_skill(skill, target, content, source_note_ids)`): `procedure` rewrites the whole `SKILL.md`, `references/<name>` writes one bulky reference file.
The factory binds the project and the writable skill set, so an agent can only write its own project's bundle; every write re-validates frontmatter, enforces size caps, refuses secret-shaped content, and lands atomically under a per-project lock.
Failures arrive as coded in-band envelopes (`skill_read_only`, `skill_invalid`, `secret_refused`, `size_exceeded`, `skill_target`, `store_unavailable`); nothing raises into the turn.
_Avoid_: section edits, operation verbs (no revise/add/correct - whole files only).

**Reading protocol (`meta-usage-skill`)**:
The compact usage-protocol skill appended to every `load_skill` result by the read path itself: assess the procedure against its stated observables during and after execution, separate a skill defect from an execution miss, and record reusable improvements through `write_skill`.
_Avoid_: prompt injection (the protocol rides the tool result, never the system prompt or compaction state).

**Authoring rules (`meta-write-skill`)**:
The content-stable authoring instructions for writing a well-structured procedure rather than a note-dump: ordered steps closed by expected observables, frontmatter plus a revision block (`base_version`, `revision`, provenance, `source_note_ids`), bulky material behind `references/` pointers.
The future `SkillEvolver` reuses it unchanged.
_Avoid_: the note-dump (prose without steps, observables, or pointers).

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
