# ADR: progressive skill lifecycle and skill-writing primitives (session ledger)

*Status: ACCEPTED - living. Records every architectural decision taken across the #222 skill-loading session and the follow-on skill-writing design rounds (2026-09-11 -> 2026-09-15), plus the #221/#189 runtime-binding round (2026-09-17: A9, its exemption amendment, and the forward-wiring note), so the reasoning survives the conversation that produced it.*
*Scope: Part A covers the #222 skill-access surface (implemented, committed on `feat/222-skill-load-tool`) and the #221 per-role binding that made its L1 half live (`ROLE_SKILLS` + `skill_agent_binding`, in flight on `feat/221-browser-cli`). Part B covers the progressive skill lifecycle and the transitory skill-writing primitives (spec #234, not yet built).*
*Companions: `skills-typed-surface-spec.md` (the typed surface and its compiled contract), `skill-runtime-loading-222-decisions.md` (the #222 self-grill whose reversals are folded in below), `progressive-skill-lifecycle-system.md` (the high-level system description), `skill-writing-primitives-spec.md` (the transitory spec), and the tracker epic #189 with child #236 (artifact-declared skills at runtime).*

---

## Part A - the #222 skill-access surface

### A1 - Role prompts are not skills: they live in module `prompts/` dirs

**Decision.** A role's system prompt lives with its owning module in a `prompts/` directory as plain Markdown, read directly by its module (fail-closed, memoized). `skills/` holds only genuine progressive-disclosure skills: flat `skills/<name>/SKILL.md`.
**Context.** Role prompts (triager, crawler, hunting agent/orchestrator, analysis proposers) had lived as `SKILL.md` files under `skills/`, forcing cross-module imports of a recon-owned loader and blending "who the agent is" with "knowledge the agent loads".
**Alternatives rejected.** Keeping role prompts as skills behind a role-routing loader (the `skill_for(role, job)` model of `jobs-tools-skills-taxonomy.md` sections 4-5, now superseded). Module-routing subdirectories under `skills/`.
**Consequences.** Prompts were moved byte-identical and frontmatter-stripped; all `_FALLBACK` constants, the ghost `skill_for("analysis/analyser")`, and `writing-observations/BASELINE.md` were deleted. `skills/` flattened to the genuine five: `authorization-pyramid`, `lightrag-query`, `webpage-profile`, `webpage-analysis`, `webapp-clientside-semantic-model`. A missing prompt file crashes loudly rather than running an identity-less agent.

### A2 - Loader home: `app/llm/skills.py`, in the skills-access domain

**Decision.** The loader (and, later, the writer) lives in `app/llm/skills.py`, co-located with the session seam, its primary consumer. A deprecating re-export shim stays at `recon/domain/skills.py` for one cycle.
**Alternatives rejected.** Leaving the loader in `recon/domain/skills.py` (recon-owned, cross-module imports) and the earlier `D6` constant-in-`skills.py` placement.
**Consequences.** `git mv` performed; `anatomy.py` and four test files repointed; `CONTEXT-MAP.md` gained the shared-kernel line. The loader is one module and one domain, which the later owner rule (B1) relies on.

### A3 - Frontmatter is the Agent Skills spec subset

**Decision.** Every `skills/<name>/SKILL.md` carries `name` (non-empty, **equal to the directory**), `description` (non-empty: what + when), and `metadata` as a string map carrying non-empty `version`. No other top-level keys; no structured `inputs`.
**Context.** The repo-dialect frontmatter was unreadable by external consumers; `name == directory` is the loader's index key.
**Alternatives rejected.** Lenient shapes with `name` need-not-equal-path (`D1`, reversed). Structured `inputs` lists in frontmatter (dropped: the body describes invocation context better than a schema stub).
**Consequences.** `validate_skill` judges shape, presence, and the name==directory rule; the catalogue sweep fails on any offender. The five survivors were normalised to `metadata: {version}` with `inputs` dropped; 22 tests passed at the change.

### A4 - Two-tier loading: L1 index middleware + L2 `load_skill`

**Decision.** L1 discovery is the bounded skill set's frontmatters rendered into the system message by the shared `dynamic_prompt` skill-index middleware, bound per agent through the **native invocation context** (`agent.invoke(..., context={"skills": [...]})`). L2 activation is the agent-callable `load_skill` tool on every stateful agent. Non-`create_agent` loops keep direct reads through the same loader functions.
**Alternatives rejected.** Convention-only phase gating with deferred binding (`D3`, reversed). A custom context-forwarding mechanism instead of the native `context=`/`ModelRequest.runtime` seam.
**Consequences.** `SKILL_INDEX_HEADER`, `render_skill_index`, `skill_index_middleware`, and `skill_agent_seams()` were added; ten stateful sites wired (recon configurator/triager, orchestrator, assigner, mechanism-typist, data-modeller, hunting actors base, pod runner/triager, `llm.py:_hunter_turn`, `hunting_agent.py` dual-plane, `surfer.py` idle); 1660 tests passed. Per-agent bounded skill sets were deferred past #221 - closed by A9, which also retired `skill_agent_seams()` for the binding seam.

### A5 - The skill rides `system_prompt=`, not the first HumanMessage

**Decision.** The skill body (and the L1 index) ride the `system_prompt=` parameter on every turn, not the first HumanMessage of a composed prompt.
**Context.** `create_agent` holds the system prompt **ephemerally** (`messages = [system_message, *messages]`; only the persisted trail is checkpointed), so per-turn passing is cheap and required; the compactor is SystemMessage-oriented (`_dedup_system_messages`, `compaction.py:459`), which is exactly where the skill must survive.
**Alternatives rejected.** The original `_compose_first_step` parts-2-5-in-the-first-HumanMessage design (part 1 skill only). It placed the skill in a compaction-foldable position.
**Consequences.** Five new pinning tests; the hunter emits the skill on every turn; compaction retains non-synthetic SystemMessages, so the skill survives window passes without prompt-domain cooperation. This finding is the direct ancestor of the owner rule (B1) and the protocol-injection decision (B2).

### A6 - One verbatim contract, byte-identical across paths

**Decision.** The agent-facing contract text is a single constant (`SKILL_LOAD_CONTRACT`) rendered verbatim into the tool description at every binding; `skills/README.md` mirrors it; bake-time and runtime reads are byte-identical.
**Alternatives rejected.** A `{content, meta, error}` dict return (breaks the same-semantics-as-loader requirement and every call-site shape).
**Consequences.** Byte-identity is pinned by test with a mutation check. The `graph_view` single-contract precedent (#197) is the template.

### A7 - Integration discipline: one PR per ticket, no direct push

**Decision.** Every change reaches `main` through a PR; one PR per `workflow` ticket; a verifier APPROVAL authorises opening the PR; merging is a human action. A premature advance of `dev` was reverted rather than carried.
**Context.** A `dev` advance (`64cbfd8`) landed before its ticket was complete; `#225` was kept (zero file overlap) and the rest reverted as `894b1c6`.
**Consequences.** No push ever left the machine during the session; branches built on the contaminated base (`e2e/206-on-dev`, `fix/langfuse-generation-shells-225`) are flagged.

### A8 - #222 self-grill decisions that STAND

**Decision.** `D2` (string body, loader-identical, fail-open; `refresh=True` as the dev hot-reload path), `D4` (two-severity rejection: tolerant at runtime, strict in repo hygiene), and `D7` (#220 follows the factory shape #222 establishes: `build_<x>_tool`, contract constant, fail-open returns, injectable seams, no I/O at import) stand unchanged.
**Reversed/escalated.** `D1` reversed (A3), `D3` reversed (A4), `D5` superseded by the design-hole move (A1), `D6` relocated (A2).

### A9 - Skill bounding is a per-role declaration delivered through the native invocation context (#221)

**Decision.** Every tool-calling role is declared once in `ROLE_SKILLS` (`app/llm/skills.py`), keyed by `role_id`, with ONE of two states: a BOUNDED SKILL SET (the catalogue skills whose discipline bears on that role's turns) or an explicit EXEMPTION (an empty tuple: the role binds no skill surface at all).
A bounded set is delivered by ONE call, `skill_agent_binding(role_id)`, which returns the L1 index middleware, the L2 skill tools, and the invocation `context={"skills": [...]}` carrying the set; an exempt role's binding composes to nothing (no middleware, no tools, no context).
The index middleware stays policy-free and byte-identical at every agent; `role_id` - the identity the turn actually runs as, its `SessionAddress` or its role constant - is the only input. So which skills an agent may see is one auditable table, not a list per agent site, and the frontmatter `description` of each bound skill is rendered verbatim into that role's system message by the shared renderer.

**Context.** #222 built the whole mechanism (A4) but bound no sets: ten sites wired the middleware and the tool, none passed a `context`, so `render_skill_index` was never reached and every agent's L1 index was empty. The tool pattern in the same codebase already answers the shape question - a role's tool surface is a declared, BOUNDED set (`CRAWL_TOOL_NAMES` filtered against the MCP pool, `runner_react_tools`/`triager_react_tools`, `build_hunter_tools`, `build_orchestrator_tool_surface`), built by its owner and attached through one native construction seam, never the whole pool. Skill bounding is the same discipline; only the seam differs, because a skill is not a callable - it travels as context and is rendered into the system message, not bound as a JSON schema.

**Alternatives rejected.**
- Per-site skill lists (the literal mirror of the tool pattern): one place to read per agent site to answer "what can this fleet's agents see", and the same number of chances for a role's set to drift from its discipline.
- A `skills: tuple[str, ...]` field on the `Role` record in `providers.py`: that registry is the LLM-turn domain (model key, turn mode, thinking baseline), so a knowledge-surface declaration there puts skill policy in the model-transport module and contradicts B1 (the skills-access domain owns every skill-surface behaviour). `role_id` is the join key, not `Role`.
- Closing the middleware over the set (`skill_index_middleware(role_id)`) instead of passing the native `context=`: identical output, but it abandons the native seam A4 ratified, makes the middleware policy-bearing, and forecloses varying the set per invocation (a future narrower or wider turn).
- Declaring the whole catalogue for every role: violates the minimal-high-signal rule every tool surface follows, and dilutes the index the load decision is actually made from.

**Amendment (2026-09-17) - the exemption rule, on the operator's ruling.**
The analysis module's three proposers (`assigner`, `mechanism_typist`, `data_modeller`) lose the skill primitives: their turns interact with LOCAL context only - the published L0/L1 substrate, their own prompts, the steering signals - and never with an external environment, so no catalogue skill bears on them.
Generalised, the rule is capability minimalism: **a role with no bearing skill binds NOTHING - not an inert tool, not a middleware, not a context.**
This supersedes the earlier reading of an empty declaration ("the middleware passes the prompt through byte-identical"): a dead tool schema plus an index that can never render is context cost with zero capability, and the fleet should not pay it.
The roster therefore has three states, and `skill_agent_binding` distinguishes all three:
- a role with a bounded set - the surface is bound;
- a DECLARED role with an empty tuple (configurator, job_orchestrator, assigner, mechanism_typist, data_modeller, hunting_orchestrator) - exempt, and the binding composes to nothing;
- an UNDECLARED role id - refused with a `ValueError` at construction, because the roster is the considered decision for every tool-calling role, so an unlisted one is a wiring defect (usually a typo), not a silent no-op.
Two implementation consequences follow.
The binding's middleware field is a LIST, so an exempt binding composes harmlessly at a shared site with no branch - which is what lets the shared hunting actor base serve both a bound role (`hunting_hunter`) and an exempt one (`hunting_orchestrator`).
And a dedicated site for an exempt role carries no reference to the skills domain at all, so the exemption is visible where a reader looks.
The exempt set is pinned by test (`test_the_roster_is_exactly_the_bound_plus_the_exempt_roles`), so an exemption is a deliberate edit in two places, never a drift.
The analysis module's own ANATOMY readers keep reading their job skills directly through `skill_for` (webpage-profile, authorization-pyramid) as their system prompts: that is the bake-time role/job-skill pattern (A1), not the runtime primitives, and it is untouched by this ruling.

**Amendment (2026-09-17) - forward wiring.**
When #223 lands (the recon JOB-SPECIFIC agents refactored into stateful entities), those agents acquire the session seam and MUST be wired to the skill primitives the same way the hunting roles are: declare each one's bounded set in `ROLE_SKILLS` (or declare it exempt) and bind it through `skill_agent_binding`.
`skill-writing-primitives-234-decisions.md` already anticipated this as the #223/#224 consumer path for per-agent binding; the roster's "undeclared role refused" guard is what makes the obligation impossible to miss once an agent with a session role id exists.

**Consequences.** Four role ids carry a bounded set (triager: webpage-analysis + webpage-profile; hunting_hunter and pod_runner: lightrag-query + steel-browser; pod_triager: lightrag-query), six are declared exempt, and the bound surface is bound at seven call sites (pod runner, pod triager, the hunter's gate/`llm.py` turn, the hunter graph's per-step turn, the shared hunting actor base, the surfer's idle session, the recon pod triager).
`skill_agent_seams()` (the #222 pair) is retired rather than kept beside the new seam, so no second seam can drift.
Repo hygiene carries the strict half of the D4 split - a declared name that does not resolve in `skills/`, a session-mode role with no roster entry, an exemption that drifts, or a meta-skill advertised in an index fails the suite; at runtime an unknown name is still skipped fail-open by the renderer.
`crawler` is the one recorded gap: a session-mode role whose loop is a manual `bind_tools` ReAct loop (not `create_agent`), so it runs no `dynamic_prompt` middleware; its delivery (direct-read index + the tool in its bound set) is an open work item and the roster documents it in place.

**The mapping is policy, and it is the operator-ratifiable surface.** Each entry is grounded on the role's own discipline and on what its turn can act on - a skill is bound only where the role's tools or domain make it actionable, and a role is exempt only where no catalogue discipline bears:
- `triager` (recon pod): the two anatomy skills, because it reads delivered web artefacts into anchored observations.
- `hunting_hunter` and `pod_runner`: the KB retrieval guide (they hold the KB tool) plus the browser skill (they touch the live target through `exec`).
- `pod_triager`: the KB guide alone - it never touches the target, and its KB reads are context reads (D84-27).
- `configurator`, `job_orchestrator`, `hunting_orchestrator`: exempt - their turns are decisions over steering signals and candidate material, with no target contact and no KB tool.
- `assigner`, `mechanism_typist`, `data_modeller`: exempt - the analysis proposers' local-context interaction.
Correcting a binding, or moving a role between bound and exempt, is a one-line edit to `ROLE_SKILLS` plus the pinned exempt set in the seam test.

---

## Part B - progressive skill lifecycle and skill-writing primitives (#234)

### B1 - The skills-access controller domain owns all skill surface behaviour

**Decision.** The skills-access controller domain (loader surface, `load_skill`, the per-project skill store/writer, the reading-protocol injection) owns every behaviour that concerns skill access. The prompt/compaction domain owns none of it and must never be aware of skills.
**Context.** A marker-based protocol-injection design placed the injection logic in the prompt control domain (it needed the prompt/compaction machinery to know when context had been compacted). This coupled two domains that should not know each other.
**Alternatives rejected.** Protocol presence tracked by a SystemMessage marker whose re-injection is driven by compaction hooks; a cadence owned by the prompt middleware. Both put skill state in the prompt channel.
**Consequences.** No skill marker, flag, or counter lives in the prompt/compaction channel. The skills domain may read harness attributes (turn numbers, thread identity, tool-call results) but originates the behaviour itself. This is the load-bearing rule Part B is built on.

### B2 - The reading protocol is injected by `load_skill`, unconditionally

**Decision.** `meta-usage-skill` (the #232 section 5.5 usage protocol) is appended to **every** `load_skill` result, by the skills domain - either as an output extension inside the tool before serialization, or as a skills-domain `wrap_tool_call` interposer. Unconditional for now: no marker, no pause period.
**Context.** The user-visible goal is that an agent which loaded a skill is told to assess it and report divergence, without a separate instruction. Because the protocol rides the tool result (a foldable ToolMessage), compaction can eventually erode it - accepted for the draft; the phase-entry loading convention re-emits it on the next load.
**Alternatives rejected.** System-prompt-resident protocol gated by a trail marker (put skill logic in the prompt domain, B1). A numeric cadence re-injector (imprecise, still prompt-domain). "Pause period" optimization deferred, to be owned by the skills domain if ever built.
**Consequences.** The injection is testable at the tool seam; the two implementation options must produce identical output. `meta-usage-skill` is authored as a real skill under `skills/` so its text has one source of truth.

### B3 - Per-project skill bundles in the canonical layout

**Decision.** A project's skills live at `<codebase_root>/data/<project_id>/skills/<skill_name>/` with the canonical layout (`SKILL.md`, `references/`, `scripts/`, `assets/`). The loader resolves the per-project bundle first, then the shared repo `skills/` catalogue. The loader and the writer share one store.
**Alternatives rejected.** A flat `<data_dir>/<project_id>/skills/<name>.md` file. Mirroring the canonical layout only for shared skills and a bespoke shape per-project. A per-submodule fixed data root (see B10).
**Consequences.** One layout rule for shared and project skills; `references/` carries bulky target material so `SKILL.md` stays compact; project skills shadow shared skills without copying.

### B4 - There is no canonical `auth_workflow` skill

**Decision.** The authentication-procedure skill is bootstrapped per project; its per-project file is the original, not a clone of a shared abstract procedure.
**Alternatives rejected.** A shared canonical `auth_workflow` procedure cloned into each project and progressively specialised (the earlier "clone-on-first-write" design).
**Consequences.** The loader must handle a skill that exists only in the project root; there is no shared fallback for it. `write_skill` creates the bundle lazily on first use.

### B5 - `write_skill` has a simplified contract

**Decision.** `write_skill(skill, target, content, source_note_ids=[])`. `target` is a typed surface over the bundle (`procedure` -> `SKILL.md`; `references/<name>`; later `scripts/<name>`, `assets/<name>`). No section granularity, no operation verbs, no `rationale` field. `source_note_ids` is log-only provenance. The factory binds `project_id` alone; there is NO per-skill writable set (D234-12 corrected the earlier bound-set + `skill_read_only` design: the future `SkillEvolver` must write any skill, and whether an agent may write at all is decided at the seam - an agent that executes no evolving procedure is simply not given the tool, `build_skill_tools`).
**Alternatives rejected.** The first draft's `update_project_skill(skill, operation, section, content, rationale, source_note_ids)` with section surgery and a rationale field (rejected: section surgery fragments a skill that must stay compact and single-sourced; `rationale` was shaved off).
**Consequences.** Writes are whole-target, re-validate frontmatter, enforce size caps, refuse secret-shaped content, and are atomic under a per-project lock; failures are coded in-band envelopes. Widening to further skills is a binding change, never a tool change.

### B6 - The notes store is the skill-lessons store; lessons are key-encoded

**Decision.** Usage lessons ride the existing notes store; no new store and no new typed schema. A lesson note is identified by its **key**, encoded `skill:<skill_name>:<lesson_header>` (the store's `notation_key` pattern). The note tool **description** gains verbatim teaching on how to type a skill-lesson key and what to include (evidence, observed-vs-expected, outcome). Note bodies stay free text and structurally indexable.
**Context.** The hunting notes store already has exactly this conception: agents persist remarkable observations, keyed for later consumption by themselves, sibling agents, or the future evolver.
**Alternatives rejected.** A dedicated `skill_lessons` store (rejected: duplicates the notes store). A typed lesson schema in frontmatter or note attributes (rejected: keeps the surface type-free, the key carries semantics). An appended "amendments" section on the skill body (rejected: the skill must stay compact and well-structured per `writing-great-skills`).
**Consequences.** The evolver consumes lessons with one read filter (`key_keyword = "skill:"`). Secrets are excluded by shape (redirect to the #220 auth store); the note carries procedure knowledge only.

### B7 - Coverage without a cursor

**Decision.** The control plane triggers `SkillEvolver` systematically; the evolver's symbolic layer tracks which lesson notes it has consumed and deterministically injects the not-yet-consumed lessons into the following HumanMessage. No high-water-mark store and no consumption-tracking algorithm.
**Context.** An earlier design proposed a per-(project, skill) coverage cursor with an exhaustive sweep. The systematic trigger plus a symbolic set-difference already guarantees each lesson is seen at least once, and previously consumed lessons re-surface in the carried context.
**Alternatives rejected.** The cursor store/coverage algorithm (unnecessary, and a second state to keep consistent).
**Consequences.** Coverage is a property of the control plane and the evolver's symbolic layer, not of a persisted cursor.

### B8 - Feedback is optional; no harness gate or nudge

**Decision.** Emitting a lesson after using a skill is optional. There is no strict post-procedure requirement, no harness usage nudge, and no gate.
**Alternatives rejected.** A mandatory post-procedure feedback step, an in-skill report-back obligation with a checkable criterion, and a harness nudge that fires when a run loaded a skill but appended no tagged note (all rejected as too strict).
**Consequences.** Discipline is carried structurally instead: the reading protocol is delivered by the read path the agent already uses (B2); procedure steps state expected observables so divergence is recognizable; the lesson note is one cheap call.

### B9 - The two meta-skills have different lifetimes

**Decision.** `meta-write-skill` (authoring instructions) is content-stable and reusable as-is by the future `SkillEvolver`. `meta-usage-skill` (usage protocol) is transitory: in this phase it instructs the executor to write directly through `write_skill`; after the #232 migration only its body changes, to emit usage lessons through the note tool.
**Consequences.** The migration boundary is exactly two skill bodies plus one executor write path; the store, tool contract, layout, scaffold ownership, and revision provenance carry over. Writing these two skills is a high-intensity authoring task and warrants specialised skill-writing subagents.

### B10 - One shared app-layer data-root module owns the scaffold

**Decision.** A single shared app-layer module owns the data root and every scaffold directory, exposing `ensure_data_root()` (called at system bootstrap) and `ensure_project(project_id)` (called at project creation, creating the whole per-project scaffold). Both are fail-safe (create if absent) and idempotent. **No module scaffolds its own directories**: module stores write only files they own. The hunting stores drop their `mkdir`-on-write.
**Context.** The hunting module currently owns its own data root (`attack/hunting/data`) and each store creates its directory lazily on write (`hunt_store.py:224`, `pod_memory.py:237`, `hunter_memory.py:355`). With two modules now needing per-project storage (hunting and skills), directory ownership must be centralised.
**Alternatives rejected.** Keeping per-submodule fixed data roots and lazy per-store `mkdir`. The first draft's lazy bundle creation by the writer (superseded: scaffold is app-owned).
**Consequences.** The data directory's lifecycle moves from lazy to eager at two trigger points (bootstrap creates the root; project creation creates the per-project tree). Lazy `mkdir` may remain only as a safety net, never as the owning mechanism. Eager creation must not break temp-rooted tests or fail-open reads of never-written projects.

### B11 - Data layout: one module directory per project

**Decision.** The data root is `<codebase_root>/data/`, with one directory per module per project: `<codebase_root>/data/<project_id>/{skills,hunting,recon,analysis,...}`. The hunting buckets (`orchestration/`, `hunter/`, `test-executor-pod/`) nest under `hunting/`. The existing hunting data is migrated to this layout, adjusting the on-disk distribution seamlessly.
**Context.** Today the three hunting buckets sit directly under `<...>/data/<project_id>/`; the project-scoped layout must generalise beyond hunting.
**Alternatives rejected.** Per-submodule roots. A top-level `data/` outside the codebase root (chosen `data/` at the codebase root instead; the roots today live under `src/`).
**Consequences.** A migration must map old paths to new without loss; a single `data_dir` concept replaces the three fixed roots.

### B12 - Executor direct-write is transitional; canonical promotion stays gated

**Decision.** In this phase the executing agent writes its own project's bundle directly (through `write_skill`, driven by `meta-usage-skill`). Canonical shared `skills/` is promoted only through the future `SkillEvolver` plus evaluation/admission. After the `auth_workflow` migration, direct executor writes retire and the tool narrows to the evolver.
**Context.** #232 section 9 forbids the executing agent from deploying to canonical skills; the transitional direct-write confines blast radius to one project and is reversible via revision provenance.
**Alternatives rejected.** Executor edits to canonical `skills/` (leaks one project's discoveries into every project; violates #232 section 9). Waiting for the full evolver before unblocking #220/#221/#223/#224.
**Consequences.** Revisions carry `base_version`, `revision`, run/session provenance, and the motivating `source_note_ids`, so the eventual evolver can audit and roll back. #232's SkillCommit pattern (instance-specific patches first, generalisation after cross-instance validation) is honoured from the start.

---

## Retired and rejected designs (recorded so they are not re-proposed)

- **Skill-lessons overlay appended to a skill body.** Rejected: it duplicates the notes store and lets a skill sprawl instead of staying compact.
- **A dedicated `skill_lessons` store.** Rejected: the notes store already is it (B6).
- **Section-granular `update_project_skill` with an operation verb and `rationale`.** Rejected in favour of the whole-target `write_skill` (B5).
- **Protocol injection owned by the prompt/compaction domain** (marker, compaction hook, or cadence). Rejected (B1, B2).
- **A coverage cursor / high-water-mark store for lesson consumption.** Rejected (B7).
- **Mandatory post-procedure feedback and a harness usage nudge.** Rejected (B8).
- **A canonical `auth_workflow` cloned per project.** Rejected (B4).
- **Per-submodule fixed data roots with lazy per-store `mkdir`.** Rejected (B10, B11).

---

## Open questions carried forward

1. Name of the reading-protocol skill (`meta-usage-skill` vs `skill-usage-protocol` vs `skill-reading-protocol`).
2. Exact lesson key shape against the store's existing notation key (`skill:<name>:<header>`).
3. Protocol injection as a tool-internal output extension or a `wrap_tool_call` interposer (both permitted; must be output-identical).
4. Whether the evolver's consumed-set lives only in its symbolic layer or is also mirrored as a note.
5. Whether expected observables per procedure step are mandatory authoring or a convention.
6. Eager scaffold failure semantics (loud vs fail-open) and the old-path migration mechanics.
