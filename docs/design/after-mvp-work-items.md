# After-MVP Work Items — persistent registry

*A durable backlog of work deliberately deferred past the Layer-1 MVP (`service-system-model-L1-implementation-bridge.md`, `L1-MVP-plan.md`).
Items here are **out of scope for the MVP fence** and are recorded so the shape is not lost; each is picked up only after the MVP FR areas are done and verified.
This is distinct from the spec's `NM-n` / `L1OP-n` deferrals (which live in `service-system-model-design_1.md` §11–§12) — those are design-level; this file holds concrete, actionable engineering items raised during implementation.*

Status legend: `proposed` (captured, not scheduled) · `scheduled` (assigned to a post-MVP phase) · `done`.

---

## AMV-1 — Service-dissection / enrichment meta-reasoning skill for the analyser

**Status:** proposed.
**Raised:** 2026-07-16, alongside wiring the general `overthink` + `critical-thinking-logical-reasoning` disciplines into the analyser (`skills/analysis/analyser/SKILL.md`).
**Relates to:** FR-SKILLIF (skill interface), FR-ELICIT (bootstrap/assignment reasoning), FR-ENRICH (Systems/DataItems/trust reasoning); spec §1.1 (adversarial-analysis rationale), §4.4 (tiered trust), §7.6 (system-anatomy skills), §7.5 (interface B backward recon).

### Intent

The MVP analyser reasons under two *general* meta-reasoning disciplines (deliberate staged reasoning + critical-thinking rigour).
What it lacks is a *domain-specific* meta-reasoning procedure for the actual craft of **dissecting and enriching the services of an application solution** — the reverse-engineering method a senior analyst uses to reconstruct what an application is, what it trusts, and where its impactful faults hide.
This item specifies that skill as a cohesive synthesis of three sources, to be authored as a first-class anatomy-style skill once the skill interface (`skill_for`) and the enrichment reasoning are in place.

### Sources to merge (cohesively, not concatenated)

1. **`architecting-solutions` — the solution-design lens, run in reverse.**
   Architecting builds a solution from requirements; the analyser *recovers* the solution from the surface. Reuse its rigour, inverted:
   - **Multiple readings before committing** (its "always present multiple options: minimal → medium → comprehensive"): for an ambiguous element, hold several candidate owners/mechanisms before deciding by evidence.
   - **Find the existing mechanism first** (its "is there an existing mechanism that does 80% of this?"): before positing a new Service/System, check whether an already-modelled one accounts for the element (avoids the duplicate-tree hazard, `L1R-5`).
   - **Trace the complete call chain** (its "trigger → … → effect, every link must work, no empty callbacks"): a proposed data-flow/trust edge must have every hop represented (`A —CONSUMES→ D ←PRODUCES— B`), not a plausible gap filled by narrative.
   - **Precise technical terms, no assumptions-as-facts** (its accuracy checklist): "shared cookie" ≠ "shared service"; "framework fingerprint present" ≠ "rendering model is X". Name the exact observed signal.
   - **Anti-over-engineering**: prefer the simplest model that explains the surface; reify a `SystemAspect`/new Service only when the evidence forces it (mirrors `L1D-16` lazy promotion).

2. **`define-hypothesis` — turn each adversarial read into a falsifiable, verifiable claim.**
   The analyser's insights are hypotheses about a black box. Give them the hypothesis discipline:
   - **Structured belief:** "We believe that *[this service]* trusts *[this data/system]* to *[hold property P]*, and that *[target/role]* can *[violate P]*." Specific intervention, specific target.
   - **Success/refutation criteria:** what observation would confirm or *invalidate* the hypothesis (a good hypothesis "doesn't assume the solution works" — here, doesn't assume the fault exists).
   - **Validation approach:** how the hypothesis is tested — which maps directly onto **interface B backward-recon requests** (§7.5): the analyser emits an `AnalyserReconRequest` whose result confirms/refutes.
   - **Risks & assumptions:** what, beyond the probe result, could invalidate the read; carried as low-confidence markers on the delta's envelope.
   - **Falsifiability is mandatory:** an un-falsifiable "insight" is an Observation at most, never a typed claim.

3. **Reverse-engineering meta-reasoning — the meta-questions, hypotheses, and verification loop.**
   The core method, framed as the questions a real attacker asks (spec §1.1):
   - **The right meta-questions to ask (per service/system):**
     - *What is this service actually **for**?* (business function, not just its endpoints.)
     - *What does it **trust**, and what does it **assume** about what it trusts?* (Tier-1 data-flow trust, §4.4 — the crown jewel.)
     - *How could its **contract** be invalidated?* (interface agreement, data contract, the authorization-pyramid projection onto it.)
     - *What **mechanism** does it lie on, and does a finding against that mechanism **transfer**?* (System identity by adversarial transfer, `L1D-7`.)
     - *Which of its assumptions are **derived from a represented flow** vs merely asserted?* (Only the former are machine-checkable, `L1D-14`/`DD-18`.)
   - **How to make hypotheses:** convert each meta-question's answer into a falsifiable prediction (via the `define-hypothesis` structure above), prioritising Tier-1 inter-service data-flow trust and data-relationship invariants over Tier-3 request-path hops.
   - **How to verify them:** issue targeted backward recon (interface B, §7.5) whose routed result confirms/refutes; on refutation, retract or lower confidence; on confirmation, enrich the L1 model (new edge/DataItem/aspect) with the evidence attached. This is the reflection loop of phase B (§7.3), made into an explicit, teachable procedure.

### Deliverable shape (when scheduled)

- A skill file (e.g. `skills/analysis/service-dissection/SKILL.md`) authored as the analyser's **enrichment/phase-B** reasoning prompt, bound to the skill interface (`skill_for`, FR-SKILLIF), composed with — not replacing — the general `analyser-service-system-reasoning` skill already wired.
- Emits the anatomy-skill triple where applicable (§7.6): typed classification → spine slot; evidence → `Observation`; deeper probe → `AnalyserReconRequest`.
- Unit-testable: the skill file loads/degrades like the others; its *effect* is evaluated with Langfuse scores on analyser traces (judged rubric: are proposals evidence-bound, are hypotheses falsifiable, do probes map to interface B).

### Why deferred

Building it now would over-reach the MVP fence: it depends on FR-SKILLIF (the skill interface), FR-ENRICH (the enrichment reasoning it drives), and interface B being exercised by real reasoning (not just the scaffolding).
The MVP wires the *general* disciplines and the *interface*; this item supplies the *domain method* on top, after the substrate has proven out end-to-end.

---

## AMV-2 — Bake `skills/analysis/**` into the agent image / dev mount

**Status:** proposed.
**Raised:** 2026-07-16, when the analyser skill loader (`_load_analyser_skill`) was added.
**Detail:** the triager skill is "mounted at /srv/skills in dev, baked by the Dockerfile in prod" (`agent/recon/pod.py:_load_triager_skill`). The new analyser skill under `skills/analysis/analyser/SKILL.md` must be covered by the same mount/bake so the container-resident analyser loads it rather than silently degrading to the inline fallback. Verify the Dockerfile `COPY skills/` (or the dev bind mount) includes `skills/analysis/**`. Low-risk, but needed before the analyser runs meaningfully in the deployed container.

---

## AMV-3 — Scope filtering for targeted recon (`request_targeted_recon`)

**Status:** proposed.
**Raised:** 2026-07-16, during the live e2e of `request_targeted_recon` against `app.onlineorders.com`.
**Detail:** a targeted `katana` probe crawled the target's login page and ingested an off-scope `https://github.com` `BaseURL` (a link on the page). The full pipeline drops off-scope BaseURLs via the curator's `scope_domain` gate (`curator.curate(..., scope_domain=...)`, D14/D15), but `request_targeted_recon` does not set `scope_domain` in `extra`, so off-scope assets a targeted tool surfaces are curated in. This is defensible for the MVP (a targeted probe is caller-scoped and the analyser/skill controls the target), but for hygiene the executor should thread the project's `settings.recon.target_domain`/scope into `extra["scope_domain"]` so targeted probes obey the same scope gate as the pipeline. Small, additive; deferred because it needs the project scope plumbed into the request and is not on the interface-B critical path.

---

## AMV-4 — Typed `operator_kb` template + service-contract framework

**Status:** proposed.
**Raised:** 2026-07-16, when FR-ELICIT set `settings.recon.operator_kb` to free text (operator decision).
**Detail:** the bootstrap currently elicits the Service skeleton from a **free-text** `operator_kb`. The operator noted that this knowledge will later follow a **pre-defined template** and a **framework that encodes typed service contracts** (interface agreements, data contracts, the authorization-pyramid projection per service) rather than free prose. Deliverable: a structured `operator_kb` schema (business functions + declared systems + per-service contract skeletons) that the bootstrap parses deterministically where typed and hands the NL remainder to the analyser; the typed portion pre-fills the Service `contract`/spine slots (§5.1) instead of relying on elicitation. Deferred: needs the enrichment contract model (FR-ENRICH, now landed) and the authorization-pyramid schema (`L1OP-6`) to stabilise first so the template targets the right typed slots. When scheduled, keep the free-text path as a fallback (not every operator will supply the typed form).

---

<!-- Append new after-MVP work items below as AMV-n, newest last. Keep each item self-contained: intent, relation to MVP areas, deliverable shape, and why deferred. -->
