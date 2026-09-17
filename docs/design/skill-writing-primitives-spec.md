# Skill-writing primitives - spec (the transitory system)

*Status: accepted, published as tracker issue #234 (`ready-for-agent`). This is the persisted repo copy of that specification; the tracker issue remains the work authority.*
*Scope: the temporary transitional system that unblocks #220/#221/#223/#224 while converging on #232. The target system and its decision ledger live in `progressive-skill-lifecycle-system.md`; the session's ADRs live in `progressive-skill-lifecycle-adr.md`; the #222 loader surface and authoring rules live in `skills-typed-surface-spec.md` and `skill-runtime-loading-222-decisions.md`.*

## Problem Statement

Agents can load skills (#222) but cannot write them. Skill knowledge is read-only at runtime: a skill is baked into the image or read from a mount, and no executing agent can record what it discovered while using a procedure.

The authentication workstreams need exactly that capability. #220 (shared auth store), #221 (browser capability), #223 (stateful recon job agents with an auth phase) and #224 (auth bootstrap flow) all depend on a per-project authentication-procedure skill that is progressively enriched as agents execute sign-in/sign-up and encounter blocking conditions, discover new roles, or find privilege-escalation paths. Without a sanctioned write primitive, those workstreams either block or each improvise a different mechanism, and the improvisations diverge from the intended final system.

#232 defines that final system: executing agents emit structured learning signals, a `SkillEvolver` aggregates and validates them, and publishable skills are versioned and reversible. The primitive built now must therefore be the on-ramp to #232, not a throwaway that later needs replacing.

## Solution

Deliver the minimal set of skill-writing primitives that unblocks #220/#221/#223/#224 while converging on #232:

- A per-project skill bundle under a shared, app-owned data root, in the canonical skill layout.
- One `write_skill` tool that creates and updates bundle artifacts through a typed target surface, bound only where authentication operations execute.
- A `meta-write-skill` skill carrying the authoring instructions; content-stable so the future `SkillEvolver` reuses it as-is.
- A `meta-usage-skill` skill carrying the usage protocol, appended by every `load_skill` call; in this transitory phase it instructs the executor to write directly to the skill through `write_skill`, and after the #232 migration only its body changes (emit usage lessons through the note tool instead).
- A shared app-layer data-root module that owns all per-project scaffold, so no module scaffolds its own directories.

The system is transitory only in the sense that the two skills' bodies and the executor write path later migrate to the evolver. The stores, the tool contract, the layout, and the scaffold ownership are the ones #232 will keep.

## User Stories

1. As an executing agent in a recon or hunting run, I want to read the project's authentication-procedure skill, so that I start from the accumulated ground truth of this project rather than from scratch.
2. As an executing agent that discovers a blocking condition, I want to write it into the project's skill, so that sibling and later agents do not rediscover it.
3. As an executing agent that discovers a new role, I want to record it in the skill, so that the procedure reflects the target's real role set.
4. As an executing agent that finds a privilege-escalation path, I want to record it in the skill, so that later agents can follow it.
5. As an executing agent, I want to write only the project's own skill bundle, so that I cannot corrupt a shared or another project's skill.
6. As an executing agent, I want a coded in-band refusal when I try to write a read-only skill, so that I learn the boundary from the tool instead of guessing.
7. As an executing agent, I want a coded in-band refusal when my content is malformed or carries secrets, so that the turn continues and I self-correct.
8. As an executing agent, I want to write bulky target material into the bundle's reference files rather than into `SKILL.md`, so that the procedure stays compact.
9. As an executing agent, I want the tool to create the project's skill bundle on first write, so that I do not need to know where it lives.
10. As an executing agent, I want every write to re-validate the skill's frontmatter, so that a malformed skill cannot be persisted.
11. As an executing agent, I want the authoring rules delivered as a loadable skill, so that I write a well-structured procedure rather than a note-dump.
12. As an executing agent, I want the usage protocol delivered with every skill I load, so that I know to assess the procedure and report divergence without being separately instructed.
13. As a skill author, I want the usage protocol to be a first-class skill in the catalogue, so that its text has a single source of truth.
14. As a skill author, I want the write instructions to be a first-class skill in the catalogue, so that an executor and later the evolver read the same rules.
15. As a maintainer, I want the skill store to resolve the per-project bundle first and the shared catalogue second, so that a project skill shadows a shared one without copying.
16. As a maintainer, I want the loader and the writer to share one store, so that bake-time and runtime reads can never diverge from what was written.
17. As a maintainer, I want one shared app-layer module owning the data root and project scaffold, so that no module creates directories and the layout is defined once.
18. As a maintainer, I want the data root created at system bootstrap and the per-project scaffold created at project creation, so that a module only ever writes files it owns.
19. As a maintainer, I want scaffold creation to be fail-safe and idempotent, so that repeated bootstrap or project creation is harmless.
20. As a maintainer, I want existing hunting data migrated to the new layout seamlessly, so that no run loses its accumulated memory.
21. As a maintainer, I want the hunting stores to stop creating their own directories, so that directory ownership is unambiguous.
22. As an operator, I want the skill-write surface bound only on agents that execute authentication operations, so that the blast radius of a write is understood.
23. As an operator, I want canonical shared `skills/` never mutated by a live run, so that one project's discoveries cannot leak into another.
24. As a future `SkillEvolver`, I want the write instructions to be content-stable, so that I reuse them unchanged when I take over skill production.
25. As a future `SkillEvolver`, I want skill revisions to carry `base_version`, `revision`, provenance, and the source note ids that motivated them, so that I can audit and roll back.
26. As a reviewer, I want the divergence from the final system confined to two skill bodies and one executor write path, so that the migration is small and bounded.
27. As a reviewer, I want the tool's failure semantics expressed as coded envelopes, so that agent behaviour on failure is testable.

## Implementation Decisions

- **Data root and layout.** The per-project data root is `<codebase_root>/data/`, with one directory per module per project: `<codebase_root>/data/<project_id>/{skills,hunting,recon,analysis,...}`. The hunting buckets (`orchestration/`, `hunter/`, `test-executor-pod/`) nest under `hunting/`. The current hunting-owned root (`attack/hunting/data`) is migrated to this layout, adjusting the on-disk distribution seamlessly.
- **Scaffold ownership.** One shared app-layer module owns the data root and every scaffold directory, exposing `ensure_data_root()` and `ensure_project(project_id)`. `ensure_data_root()` runs at system bootstrap; `ensure_project()` runs at project creation and creates the entire project scaffold (`skills/`, `hunting/orchestration/`, `hunting/hunter/`, `hunting/test-executor-pod/`, and later module dirs). Both are fail-safe (create if absent) and idempotent. No module scaffolds its own directories; module stores write only files they own. The hunting stores therefore drop their `mkdir`-on-write and depend on the app-owned scaffold.
- **Store code home.** The skill store lives in the existing skills-access module alongside the loader and the `load_skill` tool, so loader, store, writer, and protocol injection are one domain and cannot drift.
- **Catalogue.** Shared skills stay flat under the repo's top-level `skills/`; both meta-skills are flat entries there. The per-project bundle is `<codebase_root>/data/<project_id>/skills/<skill_name>/` in the canonical layout (`SKILL.md`, `references/`, `scripts/`, `assets/`). There is no canonical `auth_workflow` skill; a project's copy is its original.
- **Loader resolution.** `load_skill`/the loader resolve the per-project bundle first, then the shared repo catalogue. The loader and the writer share the same store.
- **`write_skill` contract.** Signature `write_skill(skill, target, content, source_note_ids=[])`. `target` is a typed surface over the bundle (`procedure` for `SKILL.md`, `references/<name>`, later `scripts/<name>` and `assets/<name>`) - no section granularity, no operation verbs, no rationale field. `source_note_ids` is log-only provenance. The factory binds `project_id` alone - there is no per-skill writable set (D234-12: any skill in the project's bundle is writable; the future `SkillEvolver` writes any skill) - and agents never pass identity. Writes create the bundle on first use, re-validate frontmatter, enforce size caps, refuse secret-shaped content, and are atomic (temp file plus replace) under a per-project lock. Failures return coded in-band envelopes and never raise into the turn.
- **Protocol injection.** `meta-usage-skill` is appended to every `load_skill` result. The injection logic belongs to the skills-access domain and is implemented either as an output extension inside the tool before serialization or as a skills-domain tool-call interposer. It is unconditional on every load for now; no marker, no pause mechanism, and no coupling to the prompt or compaction domain.
- **Binding.** `write_skill` is bound on all agents that execute authentication operations, hunting included. The shared agent-seam helper returns the index middleware plus `load_skill` for every agent that BINDS the skill surface, and additionally `write_skill` when the caller asks for it (`with_write_skill`), so non-auth agents keep the read-only pair. (Rostered by ADR A9: a role with no bearing skill is exempt and binds nothing at all - no `load_skill`, no index middleware - rather than carrying a read-only surface it cannot use.)
- **Meta-skills.** `meta-write-skill` carries the authoring instructions and is content-stable for the future evolver. `meta-usage-skill` carries the usage protocol; in this transitory phase it directs the executor to write directly through `write_skill`, and after migration only its body changes to emit usage lessons through the note tool.

## Testing Decisions

- **What makes a good test here.** Tests cross public seams only: the skill store, the `write_skill` tool invocation, the loader, the agent-seam binding, and the scaffold functions. They assert external behaviour - persisted files, returned envelopes, resolved bodies, created directories - and never internals. Every failure path (read-only skill, malformed content, secret-shaped content, size-cap overflow, degraded store) has a test.
- **Primary seam.** The skill store with an explicit root pointed at a temp directory, exactly as the #220 auth store and the existing notes stores are tested. No live infrastructure in the unit tier.
- **Tool seam.** Real `write_skill` invocation against a temp-rooted store: assert the coded envelopes and the on-disk result, including first-write bundle creation and frontmatter re-validation.
- **Loader seam.** Byte-identity between the loader's read and the tool-visible body; project bundle shadows the shared catalogue; a project with no bundle reads the shared skill unchanged.
- **Protocol seam.** The `meta-usage-skill` body is present in every `load_skill` result, and the two implementations (tool-internal extension or interposer) produce identical output.
- **Catalogue seam.** The #222 conformance sweep covers both meta-skills; the catalogue must remain non-empty or the pass is vacuous.
- **Binding seam.** The tool collector returns the read-only pair, or the three-member surface when the caller passes `with_write_skill`; auth-capable agents bind `write_skill`, others do not. Which roles bind the surface at all is the ADR A9 roster (`skill_agent_binding`).
- **Scaffold seam.** `ensure_data_root()` and `ensure_project()` are fail-safe and idempotent; after scaffold, the hunting stores persist their files without creating directories; the migration maps old paths to the new layout without loss.
- **Prior art.** The #220 auth-store unit tests (explicit-root temp store, coded envelopes), the hunting notes-store tests (atomic writes, per-project isolation, concurrent writers), and the `graph_view` single-contract tests (one verbatim contract at every binding).

## Out of Scope

- The `SkillEvolver`, `SkillProvider`, structural/triggering/behavioural evaluation, admission policy, version publication and rollback (#232).
- The meta-writing skill of #232 (this spec delivers the write instructions only, not the evolution procedure).
- Migrating `auth_workflow` onto the evolver; this spec delivers the direct executor write path that migration later replaces.
- The #220 auth store itself (accounts, tokens, seed API); it is referenced only as the secret boundary.
- Canonical promotion of project skill revisions into the shared `skills/` catalogue.
- The "pause period" optimization for protocol injection.
- Recon/analysis module dirs beyond establishing the one-dir-per-module scaffold rule.

## Further Notes

- **Authoring workload caveat.** Writing `meta-write-skill` and `meta-usage-skill` is a high-intensity authoring task against the `writing-great-skills` bar (compact, no sediment, no no-ops, disclosure ladder). The implementation plan must dispatch specialized skill-writing subagents for these two artifacts rather than folding them into the general implementation pass.
- **Migration boundary.** The only parts of this system that change at the #232 migration are the two meta-skill bodies and the executor write path; the store, tool contract, layout, scaffold ownership, and revision provenance carry over unchanged. This is the divergence-minimisation test the implementation should be held to.
- **Workstream impact.** Unblocks #220/#221/#223/#224; each consumer binds `write_skill` where its auth operations execute.