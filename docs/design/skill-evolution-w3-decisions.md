# Skill evolution (W3) - grilled decisions

*Status: RATIFIED by the operator in the W3 grilling round 1 (2026-10-18), with round 2 (the lesson-kind vocabulary, the corrections scope, the acceptance-gate wording) closed the same day in D-W3-6..D-W3-8. The implementation landed on `feat/w3-evolver-gate` (15 commits), passed its single adversarial review round (CLEAR: 0 blockers, 0 majors, 11 minors), and absorbed the one fix pass; the post-review amendments are recorded inline below.*
*Recorded under the `/grill-with-docs` procedure (see `/Users/diekgbbtt/.claude/skills/grill-with-docs/SKILL.md`): each decision states the ruling, the alternative(s) rejected, and the consequence.*
*The normative implementation input for the W3 workstream is this document plus the 232 decisions it amends.*

---

## D-W3-1 - Single revision per pass: workflow-enforced, no hard blocker (resolves open ruling 1)

**Ruling.** The write happens only at the END of the evolver's workflow, after it has: absorbed the notes, grounded on the current version, done the fundamental technical claim verification probes (falsification attempts over the read surfaces, D-W3-6), optionally read the HTTP-history database, optionally read the auth-store context or either of the two graphs, and loaded its authoring meta-skill.
The prompt's workflow discipline is the enforcement.
The symbolic layer does not block tool calls; the harness keeps settling `published` from the version delta.

**Rejected.** A hard structural blocker (a write-count audit or a multi-minor delta refusal as a gate): rejected, the workflow guarantee is accepted as the mechanism.

**Residual risk (orchestrator assessment, 2026-10-18).** Low, not significant: model compliance is probabilistic, but a double write leaves a visible trace (a two-step version jump) and the extra revision stays stored and auditable.
Optional and NOT ruled: flagging a multi-step delta as `degraded` in the result (a passive check that changes nothing for well-behaved passes).

**Consequence.** The prompt must state the write-at-the-end order and the grounding steps as binding workflow discipline.

## D-W3-2 - Versionability is a first-class principle of the system design (resolves open ruling 2)

**Ruling.** The previous version, and the notes in function of which any update was produced, must be seamlessly indexable from the domain model structure, with high reliability.
The revision store must, as close as possible to systematically, carry: the consumed note keys, the old and the new version.
The full notes must stay directly indexable without further data (they are: the lesson shard holds every record in full shape).
If these technical requirements are not respected, the W3 pass must improve them.

**Findings against the requirement (2026-10-18).**
- `source_note_ids` are log-only: recorded on the write log line, never consulted, not carried by any stored structure.
- The write path atomically OVERWRITES the skill's `SKILL.md`: the previous revision body is retained nowhere; no revisions directory exists in `PROJECT_SCAFFOLD`.
- A latent format defect: `_bump_version` accepts `major.minor` only and REFUSES a `major.minor.patch` version, while the ratified well-formed suite carries `1.0.0`. Before W4 mounts the suite, the bump must handle the suite's format (for example: read major and minor, ignore the patch, emit `major.(minor+1)`).

**Rejected.** Log-only provenance as sufficient; overwrite-in-place as acceptable.

**Consequence.** The W3 pass makes revisions retrievable and their provenance systematic, and fixes the version-format handling. The pass-record scaffold adds `skills/evolution` to the reserved skill names (`lessons` precedent); a skill literally named `evolution` is refused.

## D-W3-3 - The pass result's version field is the resolved version (resolves open ruling 3)

**Ruling.** Option (a): the resolved version whenever the skill resolved.
`published` carries the new version; `zero_skip`, `no_write`, and `degraded` carry the base version the pass read; `skill_unknown` carries None, because no skill exists, and so does a failure that precedes the base version resolving (a store failure at inspect): no version resolved, so none is carried.
One visible change to today's behavior: `zero_skip` stops returning None.

**Rejected.** Option (b), None for every non-published outcome: rejected, it loses the one version the pass actually considered and forces a second rule.

## D-W3-4 - The REST trigger becomes a launch + status pair (resolves open ruling 4)

**Ruling.** Two endpoints, per the app module's REST principles.
The launch endpoint starts one pass and returns a reliable identifier.
The status endpoint, given the identifier, returns the pass outcome or the update content with clear failure semantics (200 for a known pass, 404 for an unknown identifier, 503 for a refusal to start).

**Delivered surface (2026-10-18, post-review record).** The launch returns 202 with the identifier; the status is a pure durable read of the pass record (200 known, 404 unknown; no runtime, no DB). 503 covers no control plane and an unwritable record; 400 a coded lesson refusal. The identifier is the per-`(project, skill)` slot name `skills:evolve:<pid>:<skill>`; a relaunch supersedes the slot's record, so the slot serves one pass at a time (concurrent launches are last-writer-wins; documented caveat). The status serves the pass record; the update content (a revision body) is served by the store (`SkillStore.revision_content`, ordinal-indexed); a REST content route is deferred until an operator needs it.

**Rejected.** The wait-and-return single endpoint (option (a) in the grilling): rejected, waiting goes against the REST principles the app module adopts.
Also superseded: the older 202 testing-decision line; the identifier was suggested as the internal worker thread id, with the launcher's schedule name (`skills:evolve:<pid>:<skill>`) as a stable alternative.

**Consequence.** The pass result needs a durable record addressable by the identifier; the design picks the identifier and the record shape in the W3 pass.

## D-W3-5 - The evolver's grounding surface expands to read-only target context

**Ruling.** The evolver's workflow includes optional reads from the HTTP-history database, the auth-store context, and either of the two graphs, plus loading its authoring meta-skill.
These reads ground the technical claim verification; they are read-only, and the evolver never writes to them.

**Access check (2026-10-18).**

| Workflow step | Tool | Exists | Bound to the evolver |
|---|---|---|---|
| Read the notes | the aggregate is pasted; `LessonStore` | yes | yes (by construction) |
| Ground on the current version | `load_skill` plus the pasted base version | yes | yes |
| Read the authoring meta-skill | `meta/meta-write-skill` via `load_skill` | yes | yes (`ROLE_SKILLS["skill_evolver"]`) |
| Read HTTP history | `search_http_history` / `get_http_artifact` (hunting) | yes | no |
| Read the auth-store context | `build_auth_store_tool` (`app/auth/tool.py`) | yes | no |
| Read either graph | `graph_view` (`attack/hunting/graph_view_tool.py`) | yes | no |

The current prompt additionally FORBIDS these reads ("You never touch a live target, the graph, the auth records, or the hunt stores"); that discipline must be replaced by a bounded read-only one.

**Gaps to close in W3.** Bind the three read surfaces read-only for the evolver; rewrite the prompt discipline; keep the never-write rule.

**Open reading (not assumed).** "Fundamental technical claim verification probes" is recorded as (i): checking the lessons' evidence identifiers against the read surfaces.
If it means (ii), activating test-executor-pod probes against the target, that is a much larger change and needs its own ruling.

---

## D-W3-6 - Verification is falsification-based, over the read-only surfaces (round 2; resolves the "verification probes" clarification)

**Ruling.** The evolver's technical claim verification uses the tools that interact with the environment and the persistence stores to actively try to FALSIFY each lesson's claim: the probes look for technical evidence that contradicts the claim, and the lesson is confirmed only when falsification cannot be proved.
This is the sense of "fundamental technical claim verification probes": falsification attempts over the read surfaces, not live test-executor pod probes.

**Consequence.** The verification step sits in the workflow before any revision (D-W3-1, D-W3-5); its discipline is falsification, never confirmation-seeking.

## D-W3-7 - The corrections scope: both readings, one structural and one semantic (round 2)

**Ruling.** Both readings of "corrections only to already target-specified skills" hold.
(b) Structural: the enforcement is the schema validation implementing the data contracts and the classes that parse the data; a genuinely new name is refused structurally.
(a) Semantic: a defect-type lesson that yields a correction cannot be produced from the skill's base version alone; corrections regard mainly target-specific details, so they are anchored to the target-specified skill.
The original phrasing (reset session, 2026-09-28): "corrections can only be made only to already target-specified skills, as corrections regard mainly target-specific details".

**Consequence.** The W3 pass states both: the structural gate stays in the code; the semantic rule lands in the evolver's adjudication text.

## D-W3-8 - The lesson validity gate, reconciled (round 2, option (a) refined)

**Ruling.** The three stored lesson types stay (`specification | extension | defect`) and the lesson record keeps its shape: NO RDF-notion field is added at the note-tool write layer, because lesson RDF would overlap the other note types of the general episodic-memory stores.
The per-kind acceptance conditions (from the original C3 rationale, reset session 2026-09-28) become the evolver's falsification checklist (D-W3-6), applied inside the pass.
The transform-or-reject discipline is NOT dropped: it moves to a layer internal to the SkillEvolver's chain of thought, and the stored lessons remain as they are.
The RDF notion scoping surfaces in the `meta/meta-usage-skill` reading protocol, which `load_skill` appends to every non-meta skill (`skills.py:699`, `PROTOCOL_SEPARATOR`); never in the `record_skill_lesson` tool description.

**Rejected.** The stored notion scope field; the RDF in the record tool's description; dropping transform-or-reject entirely; any heuristics-based rewriting of stored lesson content.

**Supersedes.** The 2026-09-28 transform-semantics ruling ("a transformed lesson is a revision audit: the lesson content is replaced"): the transform is now internal and the stored lesson is never rewritten.

**Consequence.** The W3 pass updates the usage protocol with the notion-scoping discipline, and the evolver prompt with the per-kind falsification checklist plus the internal transform-or-reject; the lesson schema and the record tool description stay untouched for the RDF part.

## What this forces next

- The W3 pass: prompt surgery (the workflow order, the read-only grounding discipline, the write-at-the-end rule), the read-surface grants, the revision store with systematic provenance, the version-format fix, the version-field pin, and the launch + status endpoints.
- Round 2 is closed: the stored lesson types stay the three ratified ones; the acceptance conditions become the falsification checklist; the gate is internal to the evolver (D-W3-6..D-W3-8).
- W4: the nested loader; its scope is unaffected, but the suite's version format must keep working through the bump fix above.

## Provenance

The rulings were given by the operator in the W3 grilling round 1 on 2026-10-18 (the questions were reframed in primitive language at the operator's request).
The access check and the store findings were re-derived from the trunk (`feat/skills-system`) on the same day by the orchestrator.
