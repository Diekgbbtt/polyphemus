# Progressive skill lifecycle - high-level system description

*Status: design spec DRAFT, to be refined with `/to-spec` before it becomes an implementation contract.
Purpose: one coherent description of how procedural knowledge is consumed, produced, and progressively evolved in polymerhus, converging on the target described by issue #232.
Companions: `skills-typed-surface-spec.md` (the #222 typed surface and authoring rules), `skill-runtime-loading-222-decisions.md` (the #222 grilled decisions), `evolution-paradigm.md` (paradigm layer).
This draft integrates the operator feedback rounds of 2026-09-15; where it contradicts an earlier round, this document wins.*

---

## 0. Problem statement

Agents consume procedural knowledge from a filesystem-backed skill catalogue, but they cannot produce it.
The one narrow write path that exists (the per-project authentication-workflow skill) is specialized and must stay specialized, yet the general capability it gestures at - an executing agent participating in the improvement of the procedure it just used - is exactly what #232 asks for.

The gap has two sides:

- Consumption: skills are loaded, but nothing obliges or even prompts the agent to notice where reality diverged from the procedure.
- Production: agents hold the richest local context (intent, plan, observations, failures, outcomes) but have no sanctioned, narrow way to turn that into reusable procedural knowledge without polluting canonical skills.

The design must close the gap while preserving #232's trust boundary: the executing agent contributes local interpretation, never unconditional authority over canonical procedural knowledge.

### Success criteria

1. An executing agent can emit a reusable lesson about a skill it used without a new typed schema and without choosing storage.
2. A skill-learning signal is retrievable by the future `SkillEvolver` with a single read filter, and no lesson is silently lost.
3. A per-project skill bundle can be created and progressively updated in the canonical skill layout.
4. Canonical `skills/` is never mutated by a live run.
5. The skill-access controller domain owns all skill read/write surface behaviour; the prompt/compaction domain owns none of it.
6. The reading protocol that asks agents to report divergences is delivered by the skill read path itself.

---

## 1. Domain ownership and the anti-coupling rule

The single most important structural decision:

> The **skills access controller domain** (the loader surface, the `load_skill` tool, the per-project skill writer) owns every behaviour that concerns skill access. The **prompt control domain** (compaction, window management, prompt assembly) owns none of it and must never be aware of skills.

Consequences:

- No marker, flag, or counter for skills lives in the prompt/compaction channel.
- No skills middleware reads or writes compaction state, and no compaction hook reads or writes skill state.
- Any skill-domain behaviour that needs harness attributes (turn numbers, thread identity, tool-call results, usage) may consume them, but must originate from the skills domain.
- The reading protocol (section 5) is an output of the `load_skill` tool, not a system-prompt injection and not a compaction invariant.

### 1.1 The reading-protocol injection seam

The reading protocol is appended by the skill read path itself, with unconditional injection on every `load_skill` call for now.
Two implementation options, both inside the skills domain:

| Option | Where the extension lives | Notes |
|---|---|---|
| Output extension (recommended) | inside `build_load_skill_tool`'s returned tool, before serialization: `body + "\n\n" + SKILL_USAGE_PROTOCOL` | simplest; ownership unambiguous; testable through the public tool seam |
| Tool-call middleware | a `wrap_tool_call`-style interposer bound at the agent seam that extends the `load_skill` result | keeps the tool object "pure"; still skills-domain-owned; more machinery |

Both satisfy the anti-coupling rule.
The default is **unconditional injection on every skill-load usage**; a future "pause period" (to avoid repeating the protocol across a thread) is a skills-domain optimization, never a prompt-domain one.

### 1.2 Consequence for compaction survival

Because the protocol rides the `load_skill` tool result (a `ToolMessage`), compaction may eventually fold or offload it - that is accepted for the draft.
The mitigation is already in the loading convention: skills load at phase entry, so re-loading re-emits the protocol.
Guaranteeing protocol presence after compaction without prompt-domain coupling is deferred; if needed, the skills domain can track loads per thread using harness attributes it is allowed to read.

---

## 2. Two artifact classes, two stores

Trajectory is not knowledge, and knowledge is not skill (#232 section 7).
The system keeps them in distinct stores.

| | Notes store (exists) | Per-project skill bundle (new) |
|---|---|---|
| Layer | experience / knowledge | curated procedure |
| Shape | free-text records, key-encoded, append-ordered | canonical skill layout, whole-file rewrites |
| Writer | executing agents (all) | executor direct-write (transitional) / `SkillEvolver` (target) |
| Reader | agents and `SkillEvolver` | agents (through the loader), `SkillEvolver` |
| Home | `<codebase_root>/data/<project_id>/hunting/` | `<codebase_root>/data/<project_id>/skills/<skill_name>/` |

The bridge between them is provenance: a skill revision cites the lesson notes it was derived from, so the chain experience -> knowledge -> skill stays auditable.

---

## 3. Skill content layout (canonical, per-project)

The per-project data root is `<codebase_root>/data/`, module-scoped per project:

```text
<codebase_root>/data/<project_id>/
├── skills/                 # the skills module owns this
│   └── <skill_name>/
│       ├── SKILL.md
│       ├── references/
│       ├── scripts/
│       └── assets/
├── hunting/                # the hunting module owns this
│   ├── orchestration/      # HuntStore (configs.yaml, hunt_configs/, memory.yaml)
│   ├── hunter/             # HunterMemoryStore (test-specs/, notes.yaml)
│   └── test-executor-pod/  # PodMemoryStore
└── ...                     # recon/, analysis/ and later modules, same one-dir-per-module rule
```

### 3.1 Data-root ownership and scaffold lifecycle

A single shared app-layer module owns the data root and every scaffold directory.

- `ensure_data_root()` runs at **system bootstrap** (`app.main` startup): creates `<codebase_root>/data/` if absent.
- `ensure_project(project_id)` runs at **project creation** (`project_management` create path): creates the whole `<project_id>/` scaffold - `skills/`, `hunting/orchestration/`, `hunting/hunter/`, `hunting/test-executor-pod/`, and every later module dir - in one place.
- Both are **fail-safe** (create if not present) and **idempotent**.
- **No module scaffolds its own directories.** After the app-owned scaffold, a module writes only the files it owns inside its already-created directory. The hunting stores therefore stop doing `mkdir` on write; the skill writer does not create directories either.
- The `<codebase_root>/data/` tree is migrated from the current hunting-owned root (`attack/hunting/data`) to this layout, adjusting the on-disk distribution seamlessly.

- There is **no general/canonical `auth_workflow` procedure**. The per-project file is the original, created lazily on first write; it is not a clone of a shared skill.
- The loader resolves `skills/<name>` across two source roots: repo `skills/` (shared skills) and `<codebase_root>/data/<project_id>/skills/` (project skills). For `auth_workflow` only the project root holds it.
- `SKILL.md` stays compact and well-structured per `writing-great-skills`: single source of truth, no sediment, no sprawl. Bulky target-specific material (endpoint snapshots, header dumps, role matrices) lives under `references/`; the body carries only a context pointer.
- Every `SKILL.md` carries spec frontmatter: `name` == directory, `description` (what + when), `metadata` string map with `version`.
- A revision block records lineage: `base_version`, `revision`, run/session provenance, `source_note_ids`.

---

## 4. Consumption

- **L1 discovery**: the bounded skill set's frontmatters are rendered into the system message by the shared skill-index middleware, bound per agent through the invocation context (the #222 mechanics).
- **L2 activation**: `load_skill(name)` returns the skill body; resolution prefers the per-project bundle when present, else the repo catalogue.
- **Reading protocol**: appended by `load_skill` on every call (section 1.1, section 5).
- **Bounded sets**: each agent binds the skills relevant to its discipline; the set travels per invocation.

The loading convention stays: load at phase entry, once per thread, never speculatively mid-reasoning.

---

## 5. The reading protocol (issue #232 section 5.5)

A very short, compact meta-skill that instructs the agent to treat a skill as a procedure to be assessed during and after execution.

Content (paraphrase of the #232 5.5 sample, to be authored tightly):

```text
After completing the skill:
1. Decide whether the skill materially contributed to the outcome.
2. Identify unexpected cases, missing steps, ineffective instructions,
   or newly discovered reusable procedures.
3. Distinguish a defect in the skill from a failure to execute an
   otherwise valid procedure.
4. If a reusable improvement exists, emit a skill-learning signal
   through the note taking tool, following the lesson-writing instructions.
```

Properties:

- Authored as a real skill (`skill-usage-protocol`, or similar) under `skills/`, loaded through the same loader, so it has one source of truth.
- Appended to every `load_skill` result by the skill read path (section 1.1).
- Optional in effect: feedback is not required, and no harness gate or nudge enforces it.
- The precondition that makes it work is that procedure steps state their **expected observables**, so an agent can recognize divergence at all.

---

## 6. Production - notes as the skill-lessons store

Lesson notes ride the **existing notes store**; no new store, no new typed schema.

### 6.1 Key semantics

The notes store already encodes semantics in the note key.
Lesson notes use the same mechanism:

```text
key = skill:<skill_name>:<lesson_header>
```

- Queryable by the notes read operation with a key filter (`key_keyword = "skill:"`).
- The note body stays free text; no typed lesson attributes are introduced.
- The note tool **description** is extended with verbatim teaching: how to type a skill-lesson key, and what to include (evidence, observed-vs-expected, outcome), coherent with the existing description verbatim.
- All notes remain structurally indexable through their keys.

### 6.2 What a lesson note should carry

Conveyed by the tool description, not by a schema: the observed divergence or extension, the evidence, the expected-vs-observed distinction, and the outcome.
This keeps the note cheap to write and the signal reusable by the evolver.

### 6.3 Transitional direct write

`update_project_skill` (section 7) is the transitional executor write path.
It exists only for the per-project authentication-workflow skill; once that skill migrates onto the `SkillEvolver`, direct executor writes retire and the tool narrows to the evolver.

---

## 7. `update_project_skill` (simplified contract)

```text
update_project_skill(skill, target, content, source_note_ids=[])
```

- `target` is a typed surface over the bundle, not an operation and not a section:
  - `procedure` -> `SKILL.md` (whole file)
  - `references/<name>` -> `references/<name>.md`
  - later: `scripts/<name>`, `assets/<name>`
- No section granularity. No `revise`/`add`/`correct` verbs. No `rationale`.
- `source_note_ids` is log-only provenance for later debugging; never consulted at write time.
- Lazy bundle creation with a valid frontmatter skeleton on first write.
- Every write re-validates frontmatter, enforces size caps, and refuses secret-shaped content (redirecting to the #220 auth store).
- Whole-file atomic rewrite under a per-project lock, following the notes-store discipline.
- Scope is factory-bound: `project_id` plus a writable skill set, currently `{auth_workflow}`. Widening is a binding change, never a tool change.
- The tool description teaches the contract and the boundary; failures return coded in-band envelopes, never raises into the turn.

---

## 8. Coverage and the `SkillEvolver`

Coverage is a property of the control plane plus the evolver's symbolic layer, not of a cursor store.

- The control plane triggers `SkillEvolver` systematically.
- The evolver's symbolic layer tracks which lesson notes it has already consumed.
- On each turn it deterministically injects the **not-yet-consumed** lessons into the following `HumanMessage`.
- Previously consumed lessons re-surface naturally through the context the request already carries.
- There is no high-water-mark store and no consumption-tracking algorithm.

The evolver consumes the #232 section 1 learning signal (of which the lesson note is the minimal viable subset), inspects existing skills, and produces candidate revisions that cite the base version and their provenance.
Publication to canonical skills waits for the future evaluation/admission gate.

---

## 9. Risk posture

### 9.1 Risk 1 - lesson notes never covered

Root cause: unqueryable notes, and no checkable intake.
Mitigation: key-encoded lesson notes (section 6.1) make them queryable; the evolver filters by key; the symbolic diff (section 8) ensures each lesson is seen at least once.
Structural, not disciplinary.

### 9.2 Risk 2 - undisciplined producers

Root cause: agents may not notice divergence, or may not bother to record it.
Mitigation:

- Feedback stays optional - no strict post-procedure requirement, no harness nudge.
- The reading protocol (section 5) is delivered by the read path the agent already uses.
- Procedure steps state expected observables, so divergence is recognizable.
- The lesson note is one cheap call with a small body and a coded success envelope.

### 9.3 Trust boundary (#232 section 9)

Executors write notes, and transitionally their own project's bundle.
Canonical `skills/` is promoted only through the future evolver plus evaluation/admission.

---

## 10. What #232 says, and what we extract

The draft maps to #232 as follows:

| #232 | This design |
|---|---|
| section 1 learning signal | lesson note fields conveyed by the notes tool description (section 6.2) |
| section 2 `SkillProvider` | loader two-source resolution (repo + per-project) is the proto-provider |
| section 3 progressive disclosure | canonical bundle layout plus `references/` pointers (section 3) |
| section 4 `SkillEvolver` | consumes lesson notes; inspect/retrieve becomes the systematic sweep (section 8) |
| section 5 meta-writing skill | future; the reading protocol (section 5) is its consumption-side counterpart |
| section 5.5 skill usage protocol | the reading protocol, skill-domain-owned (section 1.1, section 5) |
| section 6 evaluation/admission | future; narrow-phase policy is project-scoped, marked unverified |
| section 7 trajectory/knowledge/skill split | two-store separation (section 2) |
| section 8 versioning/provenance | revision block plus `source_note_ids` (section 3, section 7) |
| section 9 trust boundary | executors write notes; canonical promotion gated (section 9.3) |

Risks 9.1 and 9.2 are not named explicitly in #232; the raw material comes from section 1 (structured signal), section 4 (inspect/retrieve), section 5 (meta-skill gate), and section 7 (corroboration and the trajectory/knowledge/skill split).

---

## 11. Structural properties the system must have

1. Two planes: typed structure (keys, bundle targets, frontmatter) versus natural-language insight (note bodies, skill prose).
2. Key-encoded lesson indexing; no parallel lesson schema.
3. Single writer per artifact (notes by executors; bundle by one owner at a time).
4. Progressive disclosure inside skill bundles (pointers, not inline sprawl).
5. Provenance on every note and every revision.
6. Control-plane-triggered evolution, never opportunistic.
7. Domain ownership: all skill-access behaviour in the skills domain; prompt/compaction domain unaffected.

---

## 12. Further primitives in skill content

Drafted for the `/to-spec` pass:

- **Expected observables per procedure step** - the precondition for divergence recognition.
- **Reading protocol** - the compact meta-skill (section 5).
- **Pointer discipline** - context pointers to `references/` in the body.
- **Revision block** - `base_version`, `revision`, provenance, `source_note_ids`.
- **Authoring convention update** - `skills/README.md` gains the per-project layout and the lesson-key convention.

---

## 13. Out of scope

- Building the `SkillEvolver`, `SkillProvider`, evaluation/admission, and the meta-writing skill (future #232 work).
- Migrating `auth_workflow` onto the evolver (follows the migration).
- The #220 auth store itself (accounts, tokens, seed API); this design only cites it as the secret boundary.
- Canonical promotion of project skill revisions.
- The "pause period" optimization for protocol injection (deferred; skills-domain-owned).

---

## 14. Open decisions

1. Name of the reading-protocol skill (`skill-usage-protocol` vs `skill-reading-protocol`).
2. Exact note key shape vs the store's existing notation key (`skill:<name>:<header>`).
3. Whether the protocol injection is a tool-internal output extension or a `wrap_tool_call` interposer.
4. Whether the evolver's consumed-set lives only in its symbolic layer for now, or is also mirrored to the notes store as a note.
5. Whether procedure steps' expected observables are mandatory authoring or a convention.