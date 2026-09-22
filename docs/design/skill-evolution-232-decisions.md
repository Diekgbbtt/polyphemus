# Skill evolution (#232) - grilled decisions

*Status: RATIFIED by the operator in the 2026-09-23 grilling session (two rounds: the design-doc open questions and the lesson-taxonomy adversarial review).*
*These decisions bind the implementation on `feat/232-skill-evolution` and AMEND `skill-evolution-232-design.md` (which stays the narrative spec) and `progressive-skill-lifecycle-adr.md` (Part B, where B6/B7/B9 are superseded as recorded below).*
*Recorded under `/grill-with-docs`: each decision states the ruling, the alternative(s) rejected, and the consequence; the glossary updates it forces land in `src/polymerhus/app/CONTEXT.md`.*

---

## D232-1 - The lesson layer is a new skill-scoped store; the hunting notes stores are untouched

**Ruling.** `record_skill_lesson` persists to a NEW store in the skills-access domain (`app/llm/skills.py`), never to a hunting notes surface.
Layout (operator ruling, overriding the design's single-file recommendation): per-skill shards at `data/<project_id>/skills/lessons/<skill>.yaml`.
The shard directory resolves through the ONE resolver - `app.data_root.project_dir(project_id, "skills")` - and `PROJECT_SCAFFOLD` gains exactly one entry, `"skills/lessons"`; no module-side `mkdir` for it.
A skill literally named `lessons` is refused by the store (`lesson_invalid`): the shard directory name is reserved by the scaffold.

**Rejected.** `skills/lessons.yaml` single file (design's recommendation): per-skill consumption and read amplification argued for shards.
Keeping the hunting note contracts as the lesson substrate (ADR B6): evidenced-wrong - all three notes surfaces require a hunt identity (`fault_key` grammar, `spec_id` + order, hunt `NoteProvenance`), and no recon/analysis bucket exists.

**Consequences.** The hunting notes contracts, stores, and tests are untouched (a validation line of this ticket).
Supersedes ADR B6's "no new store and no new typed schema" clause; B6's key-encoding `skill:<name>:<header>` grammar is replaced by D232-2.

## D232-2 - Lesson record shape: three types, free prose, store-stamped facts, key-encoded consumption

**Ruling.** The record is a minimal typed envelope with free-text values (operator: "much simpler typed surface on the parent level, and free text values"):

```yaml
- key: "skill:<skill>:<ordinal>"            # store-generated, monotonic per shard
  type: specification | extension | defect  # see D232-3
  lesson: "<free prose: the reusable lesson>"
  expected: "<the skill's stated expectation, extracted statically with minimum divergence>"
  evidence: ["<concrete identifier>", ...]  # e.g. http-artifact ids, run ids, request/response entries
  base_version: "<major.minor>"             # STORE-stamped from SkillStore.meta
  agent: {role_id: "<role>", session_id: "<thread id>"}  # TOOL-stamped (symbolic layer)
  written_at: "<ISO-8601>"                  # store-stamped
```

- The agent supplies only `skill`, `type`, `lesson`, `expected`, `evidence`.
- `skill` is not a record field: the shard path is structural; the TOOL contract still takes `skill` (operator ruling).
- `base_version` is store-stamped through the same `SkillStore.meta` seam the loader uses; the agent never supplies a version.
- `agent.role_id` is stamped by the tool from the `role_id` bound at `skill_agent_binding`; `agent.session_id` is the ambient session thread id when the invocation context carries it (the hunting pod runner's typed `PodSession` id), else `""`.
- No `lesson_header` argument; no `observed_vs_expected` field (the prose `lesson` plus `expected` carry the divergence).
- Consumption is enumerated in the KEY, not a field (operator ruling): once the controller loads a lesson for prompt pasting it rewrites that record's key with the reserved suffix code `:consumed` (`skill:ssrf:3` -> `skill:ssrf:3:consumed`); `read(unconsumed_only=True)` selects keys lacking the code.
  There is no `consumed_by` revision stamp and no high-water-mark cursor.
- A repeated `skill:<name>:<n>` is impossible by construction (ordinals are monotonic per shard); duplicate prose lessons append as new records.

**Rejected.** A four-type taxonomy first proposed (`specification`/`optimization`/`anti-pattern`/`correction`): superseded by D232-3.
`consumed_by: <revision id>` (design 1.5 Q3 recommendation): a second state to keep consistent; the key code is self-encoding.
Deriving consumption only from `source_note_ids`: still available as audit, but not the selection mechanism.

**Consequences.** `mark_consumed` is an atomic read-modify-write under the same per-project lock as the writes.
A pass that fails after selection has consumed its input (accepted trade; the operator can re-post lessons through the evolve endpoint, D232-10).

## D232-3 - The lesson types: `specification`, `extension`, `defect`; semantics stated very concisely in three places

**Ruling (operator).** Three types, each with a short semantics line to be cited verbatim-tight in the record tool's description, in the rewritten `meta-usage-skill` body, and in the evolver prompt:

- `specification` - knowledge specific to the target, an addition about its attack surface.
- `extension` - an extension of the procedure: new steps, an optimised grouping, an anti-pattern (steps that must not be done), or an extension of the technique's attack-surface scope.
- `defect` - a genuine error in the illustrated procedure.

**Adversarial review recorded (the operator's requested check, round 2).** Fabricated executions showed the four-type draft was not a partition: an embedded-hydration misclassification is simultaneously `correction`, `specification`, and `anti-pattern`; a `networkidle`-never-settles case is `correction`, `anti-pattern`, and `optimization`; an alias-query case is `optimization` and `specification`; a missing-CSRF-token case is a target fact (`specification`) whose reusable lesson is a procedure fix (`correction`).
The operator's three-type answer resolves this by making `extension` the umbrella (new steps / anti-pattern / scope extension) and `defect` the only contradiction type.
Recorded residual gaps, accepted with the operator's "extend more later" clause: pure positive `confirmation` (no type; the keep-test's positive side is not collected this round) and environment/precondition facts (fold into the nearest type, usually `extension`).

**Consequences.** The taxonomy is a small closed vocabulary with concise semantics; extending it later is a one-line edit to the shared constant plus the three prose sites.
The evolver reconciles anything the agent files under the wrong type - the types are intent hints, never a validation partition.

## D232-4 - Universal binding: `record_skill_lesson` rides the read-only pair; `write_skill` stays gated

**Ruling.** `build_skill_tools(project_id, with_write_skill=False, store=None, lesson_store=None, role_id=None)` returns `[load_skill, record_skill_lesson]`, appending `write_skill` only when `with_write_skill`.
One edit in `skill_agent_binding` therefore instruments every bound role; an exempt role still binds nothing.

**Rejected.** Binding the lesson tool only to the hunting pod runner: the operator named that runner as the only CURRENT producer, but the capability is safe and generic (append-only observation), and a future producer should not need a second wiring edit.

**Consequences.** The write trust boundary of #232 section 9 is preserved: an executor can record a lesson but cannot publish a revision without the evolver.

## D232-5 - The lesson tool contract is a verbatim constant, coded in-band, never a raise

**Ruling.** `RECORD_LESSON_CONTRACT` is the single verbatim tool description (the #197 `GRAPH_VIEW_CONTRACT` / #222 `SKILL_LOAD_CONTRACT` pattern), mirrored in `skills/README.md`; it carries the compact type semantics and the envelope vocabulary.
Returns `{ok: true, key, base_version}` or `{ok: false, error: lesson_invalid|skill_unknown|store_unavailable, detail}`; nothing raises into the turn.
The factory binds `project_id` (resolved tool-owned via `config.PROJECT_ID` when unset) and the `role_id` stamp.

**Rejected.** A raise-through interface; a non-coded free-text error.

**Consequences.** The description is pinned by test; the three error codes are the closed envelope vocabulary.

## D232-6 - `meta-usage-skill` migrates in THIS ticket to the lesson lifecycle

**Ruling (operator, over the design's defer-to-F).** The usage-protocol body is rewritten now: after using a skill, assess against the observables, then emit a lesson through `record_skill_lesson` using the D232-3 type semantics.
The direct `write_skill` direction leaves the usage protocol; authoring stays with the authoring meta-skills (`meta/meta-write-skill`, `meta/authn-skill-writing`).
Composition rules are untouched: the protocol is appended on every `load_skill` except meta-family skills, always read from the shared catalogue, byte-separated by `PROTOCOL_SEPARATOR`.

**Rejected.** Keeping the transitory "write directly via write_skill" text until the evolver lands (design 1.5 Q5 recommendation): the operator ruled the migration in-ticket.

**Consequences.** `test_skill_protocol.py` pins composition bytes from a fixture, not the real body, so it stays green; the real body's prose is rewritten by a specialised skill-writing subagent against the `writing-great-skills` bar (the D234-9 precedent).

## D232-7 - The SkillEvolver role is app-owned, dedicated, and session-mode

**Ruling.** There is no skills module and none is minted: skills logic lives in the app module (`app/llm/evolver.py`, beside `skills.py`).
Role record: `Role("skill_evolver", "LLM_SKILL_EVOLVER", "session", "high")` in the app-owned `ROLES`, so app boot (`validate_llm_config`) requires `LLM_SKILL_EVOLVER` like every registered role; the deployment key must be set (recorded in `STATE.md` High Priority).
Roster: `ROLE_SKILLS["skill_evolver"] = ("meta/meta-write-skill",)`; the pass arms its own binding with `with_write_skill=True`.
Role prompt: `src/polymerhus/app/llm/prompts/skill_evolver.md` (role prompts live with the owning module, never under `skills/`).

**Rejected.** A module-owned `SKILLS_ROLES` registry validated at a skills-module bootstrap: the operator ruled there is no such module.
An unregistered role resolved by the `LLM_{ID}` convention: hides the role from the roster sweep and loses the `agent_mode`/thinking declaration.

**Consequences.** `ROLE_SKILLS` gains a bound role; the roster test's pinned `BOUND_ROLES` gains `skill_evolver` deliberately.
The `test_every_tool_calling_role_declares_its_skill_set` sweep covers the new session role automatically once it is in `ROLES`.

## D232-8 - Lifecycle: one controller loop in the worker loop, armed when the hunting phase starts

**Ruling (operator).** A controller in the app skills surface runs as one async loop on the shared module runtime worker loop (no other agent awaits it).
It is armed only once the hunting phase starts; per tick it checks, for each skill with lessons, whether the unconsumed count reaches the cap (5) OR the period since the last pass elapsed (300 s) - either condition triggers one pass for that skill.
Defaults are config knobs (env-overridable): cap `SKILL_EVOLVER_LESSON_CAP=5`, period `SKILL_EVOLVER_PERIOD_S=300`, tick `SKILL_EVOLVER_TICK_S=60`.
The per-skill "last pass" timestamp lives in the controller's symbolic layer (in-memory); consumption itself is durable in the lesson keys.

**Rejected.** An app-boot-started permanent loop: the operator scoped triggering to the hunting phase.
An endpoint-only trigger: the operator explicitly asked for the cap/period controller.

**Consequences.** The controller is a per-hunting-run task (scheduled alongside the orchestrator pass and the surfer by the hunting bootstrap, cancelled with the run), so it never blocks module drain and never runs without a producer.
Lessons recorded after a run's controller stops wait for the next hunting run.

## D232-9 - The evolution pass: one stateful turn, lessons pasted, agent publishes, zero-skip default

**Ruling.** `arun_evolution_pass(project_id, skill, *, skill_store=None, lesson_store=None, model=None) -> EvolutionOutcome` runs one bounded pass:

1. **inspect** - resolve the skill (project bundle first, catalogue second) and its version; an unresolvable skill is `skill_unknown`, no write.
2. **select** - all unconsumed lessons for that skill; an empty selection is `zero_skip`, no model call, no write.
3. **mark** - rewrite the selected keys with the `:consumed` code (D232-2) as they are loaded for pasting.
4. **produce** - one stateful `arun_session_turn` on a per-`(project, skill)` thread; ALL selected lessons pasted into a single `HumanMessage` placeholder; the workflow (inspect -> decide create/update/no-write -> produce -> validate -> publish) plus the `writing-great-skills` guardrails live in the role prompt; the agent holds its bound skill surface (`load_skill`, `record_skill_lesson`) plus `write_skill`.
5. **publish** - the AGENT calls `write_skill` for its project bundle (operator ruling); the store re-validates structurally, bumps `metadata.version` one minor, and logs `source_note_ids` = the consumed lesson keys.
6. **outcome** - `EvolutionOutcome` carries the decision (`published | zero_skip | skill_unknown | degraded`), the new version (read back from `SkillStore.meta`), the consumed keys, and the thread id.

One revision per skill per pass (the design's bounded blast radius); re-running with no new lessons writes nothing.

**Rejected.** A judge-LLM evaluation gate chained to the write: the operator ruled it too complex now; quality is guaranteed STRUCTURALLY by the role prompt's workflow and verbatims citing `writing-great-skills` guardrails.
Harness-publishes-after-gates: moot once the judge gate is out; the agent publishing through the existing `write_skill` contract keeps the #234 store as the single writer.

**Consequences.** Functional/qualitative evaluation and the synthetic fabricated-lesson evaluation suite are DEFERRED to `/to-assertions` and the post-implementation e2e design (operator ruling).
Canonical-promotion admission remains out of scope; the pass writes the project bundle only.

## D232-10 - REST trigger: force a pass, optionally inject lessons

**Ruling.** `POST /projects/{project_id}/skills/{skill}/evolve` forces one immediate pass through the runtime (`schedule`, admission-refusal mapped to 503 like the other launches) and accepts an optional body `{lessons: [...]}`; posted lessons are appended to the shard (store-stamped) before the pass so an operator or e2e run can drive evolution without a hunting phase.
The response carries the `EvolutionOutcome`.

**Rejected.** A read-only status endpoint only: the operator asked for the posted-lessons injection surface.

**Consequences.** The endpoint is the testable manual path; the controller (D232-8) is the automatic path.

## D232-11 - Transcript access: the identifier is captured now, the read is designed-not-built

**Ruling.** Every lesson carries the writing agent's session identifier (`agent.role_id` + `agent.session_id`), which the symbolic layer already owns: a hunting pod's identity is name + thread id, and the pod's `HuntSession` thread is `PodSession(run_id, hunt_id, spec_id, role_id="pod_runner")`.
The trajectory + reasoning of that session ARE accessible: the session's persisted thread memory via `read_session_memory(checkpointer, thread)` (`app/llm/session.py`), readable by the captured thread id, plus the Langfuse session trace keyed by the same id.
The pod's on-disk `experiment-log/<order>.yaml` keeps observations/interpretations but NOT the followed trajectory or reasoning.
The evolver does not yet load transcripts (out of scope this build); the identifier is captured so the future wiring is a pure read.

**Rejected.** Doing nothing (operator: "record it as a gap ... or find where and how that can be accessed"): the surface was found and is recorded here.

**Consequences.** No schema change is needed later to enable transcript-grounded evolution; only an evolver-context change.
The mapping (session id -> persistent thread memory -> spec directory) is documented here for that change.

## D232-12 - The external corpus moves into the repo catalogue, losslessly, enriched to A3

**Ruling (operator).** `~/purple-swan/skills` (63 skills, no git) moves into the repo `skills/` catalogue.
Layout decision: the 63 skill directories land FLAT (`skills/<name>/SKILL.md`, the loader's index key), preserving their content; each header is enriched to the A3 dialect by adding `metadata.version: '1.0'` (`name` == directory and `description` are already present).
The corpus's group directories (`cloud/`, `frameworks/`, `protocols/`, `reconnaissance/`, `technologies/`, `tooling/`, `vulnerabilities/`) hold only stale `.md` duplicates of the flat skills - verified byte-identical except one unique SSTI bullet - so duplicates are dropped and the unique material is preserved as a reference in the owning bundle (`ssti/references/`).
The empty group dirs and `.gitkeep` files are dropped.

**Rejected.** A read-only secondary catalogue root with an env path: the operator chose the move.
Keeping the duplicate group tree: dead weight in the catalogue; the lossless rule preserves the one unique artifact.

**Consequences.** The conformance sweep now governs 68 skills; `list_skills()` grows; `ROLE_SKILLS` is unchanged (binding is a deliberate per-role edit, never the whole catalogue).
`SkillProvider` as a filesystem/REST abstraction remains future (issue section 2 untouched this round).

## D232-13 - Evaluation, admission, canonical promotion stay out of scope

**Ruling.** This build ships the lesson layer + the evolver pass that writes PROJECT bundles.
Structural validation is the store's; quality is the prompt's; there is no admission policy, no canonical `skills/` promotion, no rollback machinery, and no LLM-judge scoring in this ticket.
The operator's "quality evaluation with fabricated synthetic data" becomes the `/to-assertions` phase and the e2e test design, where the realistic lesson fixtures are fabricated from the moved corpus.

**Consequences.** A revision is reversible by the existing `metadata.version` history plus `source_note_ids`; canonical publication remains gated on the future evaluation/admission work (#232 sections 5-6).

## D232-14 - Unchanged contracts (the fence)

- The hunting notes contracts and their stores/tests are untouched.
- The #234 `write_skill` contract (typed target, store-owned frontmatter, one-minor version bump, coded envelopes) is untouched.
- The catalogue frontmatter contract (A3) and the meta-family exemption rule (`is_meta_skill`, path-keyed) are untouched.
- Role prompts never live under `skills/`; the recon `skills.py` shim is never imported.
- Fail-open reads, fail-loud writes, atomic writes under the per-project lock, no I/O at import; `src/polymerhus/recon/domain/skills.py` stays a deprecating shim.

---

## Build order (this ticket)

1. **A/B/C** - `LessonStore` + `record_skill_lesson` + universal binding (unit tier, TDD).
2. **D** - key-coded consumption + read filters (same store).
3. **E** - `app/llm/evolver.py` (pass + controller + role prompt + role record) and the REST endpoint.
4. **F** - `meta-usage-skill` body migration (specialised authoring subagent, D234-9 precedent).
5. **G** - scaffold entry + corpus move + header enrichment.
6. `/to-assertions` - integration/e2e assertion catalogue, including the fabricated-lesson evolver walkthrough (the operator's deferred evaluation step).

## Open items carried forward (not decision gaps)

- **`LLM_SKILL_EVOLVER` must be set on every deployment** (D232-7): recorded in `STATE.md` High Priority.
- **Transcript loading into the evolver** (D232-11): designed-not-built; the captured session id is the seam.
- **Type extension** (D232-3): `confirmation` and environment/precondition types are the likely first extensions.
- **Provider abstraction** (issue section 2): still future; the corpus is in-repo now.
