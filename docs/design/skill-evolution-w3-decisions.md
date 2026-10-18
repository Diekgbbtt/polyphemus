# Skill evolution (W3) - grilled decisions

*Status: RATIFIED by the operator in the W3 grilling round 1 (2026-10-18). It resolves the four open adversarial rulings carried in `skill-evolution-232-decisions.md` ("Adversarial review - findings and open rulings"). Round 2 (the lesson-kind vocabulary, the corrections scope, the acceptance-gate wording) is still open; this document grows with it.*
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

**Consequence.** The W3 pass makes revisions retrievable and their provenance systematic, and fixes the version-format handling.

## D-W3-3 - The pass result's version field is the resolved version (resolves open ruling 3)

**Ruling.** Option (a): the resolved version whenever the skill resolved.
`published` carries the new version; `zero_skip`, `no_write`, and `degraded` carry the base version the pass read; only `skill_unknown` carries None, because no skill exists.
One visible change to today's behavior: `zero_skip` stops returning None.

**Rejected.** Option (b), None for every non-published outcome: rejected, it loses the one version the pass actually considered and forces a second rule.

## D-W3-4 - The REST trigger becomes a launch + status pair (resolves open ruling 4)

**Ruling.** Two endpoints, per the app module's REST principles.
The launch endpoint starts one pass and returns a reliable identifier.
The status endpoint, given the identifier, returns the pass outcome or the update content with clear failure semantics (200 for a known pass, 404 for an unknown identifier, 503 for a refusal to start).

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

## Open - the lesson validity gate, reframed (round 2 re-ask)

**Grounding (found 2026-10-18, session `ses_f35794155ffeYYGr0eO9LYPn51`).** The original C3 rationale is a semantic gate with per-kind acceptance conditions: specification (no payload literals, concrete payload vectors observed, encodings/body shapes/communication protocol, introspected technology-stack configuration, observed backend data relationships); optimization (executed defence-bypass or proxy techniques); anti-pattern (blocking states and structural dead-ends); corrections (only against already target-specified details). The gate transforms-or-rejects the lesson and applies a critical-thinking/bias assessment; it supersedes the prompt's "lesson types are intent hints, never enforced" stance.

**The round-2 claim (2026-10-18).** No heuristics-based semantic control on lesson content; a loose data-structure check instead, placed upstream at the note-tool write layer.

**Status.** The claim does not fulfil the original's per-kind conditions and its supersession of the intent-hints stance; the reconciliation is re-asked before this decision is recorded.

## What this forces next

- The W3 pass: prompt surgery (the workflow order, the read-only grounding discipline, the write-at-the-end rule), the read-surface grants, the revision store with systematic provenance, the version-format fix, the version-field pin, and the launch + status endpoints.
- Round 2 of the grilling: the lesson-kind vocabulary versus the acceptance conditions, the corrections scope, and the acceptance-gate wording.
- W4: the nested loader; its scope is unaffected, but the suite's version format must keep working through the bump fix above.

## Provenance

The rulings were given by the operator in the W3 grilling round 1 on 2026-10-18 (the questions were reframed in primitive language at the operator's request).
The access check and the store findings were re-derived from the trunk (`feat/skills-system`) on the same day by the orchestrator.
