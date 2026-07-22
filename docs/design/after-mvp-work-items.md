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

## AMV-5 — Richer L0 data-surface extraction for field-level DataItem granularity

**Status:** proposed.
**Raised:** 2026-07-16, from the soupmarket.shop (OWASP Juice Shop) data-rich e2e.
**Observation:** the analyser lifted 10 faithful, well-named DataItems (`user_identity`, `user_credential`, `payment_card`, `basket_item`, `product`, `order`, `address`, `complaint`, `feedback`, `challenge`) but their `SURFACES_AT` edges land on whole **Endpoints** (e.g. `/api/Cards`), not fine-grained `Parameter`/`Header`/response-field sites as the design intends (§6, L1D-13). Root cause is the L0 surface, not L1: on this run `arjun` recovered only 5 Parameters and `jsluice` recovered 0 (the Angular bundles weren't lifted — katana surfaced no `.js` Endpoints for jsluice to consume, so its consumes_where `.js`/`.mjs` selector matched nothing). With no field-level surface to attach to, the analyser reasonably fell back to endpoint-level surfacing. **Deliverable:** improve the L0 data surface so DataItems can surface at the field level — (a) investigate why katana yields no `.js` Endpoints for jsluice on an SPA (so the client-side JS data model is recovered), (b) response-field/JSON-body extraction (D25 runtime capture) so response data items get typed sites, (c) richer arjun param coverage. This is recon-layer work that raises DataItem fidelity; the L1 substrate already accepts field-level `SURFACES_AT` (any L0 label), so no L1 change is needed.

## AMV-6 — DataRelationship population via phase-B reflection

**Status:** proposed.
**Raised:** 2026-07-16, same e2e (`data_relationships: 0`).
**Observation:** the DataRelationship vocabulary + storage are built (FR-ENRICH) and the analyser correctly wrote Tier-1 `CONSUMES` trust assumptions (e.g. `shopping-basket CONSUMES product` *"Basket items reference products by ID"*), but it posited zero `DATA_RELATIONSHIP` functional-dependency edges (`derived_from`/`equals_hash_of`/…) in a single forward pass. These invariants (e.g. an order total derived from basket item price×quantity) need the deeper phase-B reflection loop (spec §7.3/§7.5) over the already-laid data flows, not a first-pass classification. **Deliverable:** the phase-B analyser reflection that, given the DataItems + flows, hypothesises DataRelationships and verifies them via interface-B backward recon (ties to AMV-1). Deferred to the phase-B reasoning area; the substrate is ready.

## AMV-7 — Ordered System→System perimeter chain (`ON_REQUEST_PATH {order}`)

**Status:** proposed.
**Raised:** 2026-07-17, during FR-NFR (the §15 closing walkthrough).
**Observation:** the §15 narrative lays an ORDERED perimeter chain between Systems - `CDN —ON_REQUEST_PATH{order:1}→ WAF —{order:2}→ ReverseProxy —{order:3}→ origin`. `ON_REQUEST_PATH` is in the `SYSTEM_EDGE_RELS` vocabulary, but `l1_curator.build_system_edge_cypher` (built + verified in FR-ENRICH) writes **Service→System** edges only, so the inter-System ordered chain is not writable today. This was never in a built FR area's scope (FR-ENRICH was scoped + verified with Service→System edges), and §15 interleaves it with other explicitly-deferred primitives (SystemAspect/NM-3, the concretisation reducer/NM-10). **In the MVP the perimeter Systems are still modelled** via the supported Service→System perimeter edges (`FRONTED_BY` CDN, `PROTECTED_BY` WAF, `ROUTED_BY` ReverseProxy) + each System's `discriminator` (e.g. CDN `{Datadome}`); only the inter-System *ordering* nuance is deferred. **Deliverable:** a System→System edge builder (`build_system_link_cypher` or a generalised endpoint-kind arg on the existing builder) that MERGEs `(:L1System)-[:ON_REQUEST_PATH {order}]->(:L1System)` (and the final `→(:L1Service)` origin hop), with the ordered-chain assertion. Clean, additive; no interface change. Deferred to keep FR-NFR a verification area (not a build area) and preserve maker/checker separation.

---

## AMV-8 — L0 crawl/parse scope + noise filtering (junk never becomes an Endpoint)

**Status:** proposed.
**Raised:** 2026-07-17, from the exhaustive soupmarket.shop (OWASP Juice Shop) e2e (project `soup_9b876a3c`), corroborated by an independent verifier.
**Relates to:** the recon L0 layer (katana / jsluice / `parsers/_urls.py`), upstream of FR-ELICIT/FR-ANALYSER; complements AMV-5 (data-surface fidelity).

### Observation (live evidence)
Of 182 crawled Endpoints all assigned by the analyser, **~58 (31%) are low-value noise** that arguably should never have been L0 `Endpoint` nodes at all:
- **katana over-crawled build/vendor/ftp trees**: `/juice-shop/node_modules/express/lib/router/*.js`, `serve-index/index.js` (Node source), ftp artifacts (`.bak`/`.pyc`/legal `.md`), and Angular internals (`chunk-*.js`, `*.component-*.js`).
- **JS bundles + compiler blobs surfaced as endpoints**: `/main.js`, `/polyfills.js`, `/scripts.js`, `/soljson-v0.8.21+commit.*.js` (Solidity compiler binaries pulled with the web3 feature), `ethers.js`.
- **jsluice string-concatenation fragments**: `/'+_(i[8])+'`, `/%27+_%28i%5B11%5D...` (JS source concatenation mis-read as a path).

Root cause is the L0 crawl/parse scope (what katana fetches and what the parsers admit as an `Endpoint`), NOT the L1 substrate. But it directly degrades L1: the analyser then aggregates this noise into services (see AMV-9).

### Deliverable (when scheduled)
- katana job scope: exclude `node_modules/`, `/build/`, ftp/backup trees, and (configurably) static-asset extensions from crawl or from Endpoint emission.
- parser hardening (`_urls.py` / `jsluice_parser` / `katana_parser`): drop malformed string-concatenation fragments (unbalanced quotes/parens, `+_(`), and classify pure static assets (`.js/.css/.map/.woff*/.png/...`) distinctly from API endpoints so L1 can treat them differently.
- assertion: on a re-run, the noise fraction of emitted Endpoints drops sharply and the concat-fragment paths disappear.

### Why deferred
Separate subsystem (L0 recon), each change wants its own bounded maker/checker loop + regression tests; not on the L1-substrate critical path. Fixing it mid-certification would be a cross-subsystem drive-by. Captured with concrete evidence so it is picked up as its own area.

---

## AMV-9 — Analyser assignment-confidence + stale-pool resolution policy (realises L1OP-5)

**Status:** proposed.
**Raised:** 2026-07-17, same e2e; this is the concrete, live-evidenced realisation of the spec's deferred open point **L1OP-5** (confidence-threshold / stale-pool numeric policy).

### Observation (counterintuitive, load-bearing)
The MVP analyser has NO assignment-confidence or stale-resolution policy, so it assigns **every** L0 node to *some* service rather than leaving low-confidence/low-value nodes in the stale pool. Concrete contrast on the SAME target:
- prior run (weaker analyser model): **79 / 133** Endpoints left stale (junk correctly unassigned).
- this run (stronger model, `deepseek/deepseek-v4-pro`): **0 / 182** stale — the stronger model confidently over-assigned, pulling ~31% noise into 5 services, including a genuine business service (`web3-wallet` polluted with `soljson` compiler blobs) and a `file-server` service fabricated largely from `node_modules` source.

**A more capable model produced WORSE assignment discipline** because nothing bounds over-assignment. `stale_pool=0` is therefore a NEGATIVE signal here (achieved by over-assigning noise), not the clean signal it superficially looks like. This invalidates any naive "empty stale pool = good" heuristic.

### Deliverable (when scheduled)
- an assignment-confidence gate at the AGGREGATES write (per L1OP-5): below a threshold, an L0 node stays in the stale pool rather than being assigned; the threshold + the policy are the L1OP-5 decision.
- a static-asset/low-value class (fed by AMV-8's classification) that is never business-assigned by default (or assigned only to an explicit frontend-assets service with low confidence).
- an evaluation: assignment faithfulness scored on Langfuse (precision of assigned business endpoints), tracked across analyser models so capability regressions like the above are caught.

### Why deferred
`L1OP-5` is explicitly out of the MVP fence (`L1-MVP-plan.md` §3 "Explicitly out of scope"). Building the confidence/stale policy now is deferred machinery. Captured with live evidence so the policy targets the real failure mode.

### Update 2026-07-18 - high run-to-run ASSIGNMENT VARIANCE also observed (under-assignment)
The FR-STREAM (NM-7) live runs exposed a second facet of the same missing-policy gap: the analyser LLM (`deepseek/deepseek-v4-pro`) is highly NON-DETERMINISTIC in assignment volume on the SAME target - one streaming run assigned **143** AGGREGATES (growth `[0,77,142,143,143]`), a later run over the identical surface assigned only **11** (with `analyser structured call returned no tool call` retries firing). So the analyser swings between over-assignment (31-38% noise, the original finding) and under-assignment (near-empty batches) with no confidence/stale policy to stabilise it. The AMV-9 deliverable should therefore ALSO include: (a) determinism/robustness of the assignment pass (retry-on-empty already exists via `_invoke_with_retry`, but a `no tool call` empty result should be retried too, and/or a stronger/temperature-pinned model); (b) an assignment-precision score tracked on Langfuse across runs so both failure directions are caught. This is the streaming feature's most useful finding - the mechanism is sound, but assignment QUALITY is the real lever.

---

## AMV-10 — DataItem attribute/field identification enrichment activity

**Status:** proposed.
**Raised:** 2026-07-19, from operator review of the streaming e2e L1 graph.
**Relates to:** FR-3H/FR-ENRICH (DataItem lifting, L1D-13); complements AMV-5 (richer L0 data-surface) and AMV-9 (evidence/confidence discipline).

### Observation
The analyser associated many DataItems with endpoints, which is fine **as long as it is evidenced rather than guessed**.
The immediate fix (landed 2026-07-19) removes any speculative `likely_fields` from the DataItem model: the analyser now records only fields it actually OBSERVED on the surface, under an evidence-bound `fields` list in `DataItem.props` (parameter names on the item's endpoints, keys present in the evidence), and omits `fields` when it observed none.
That deliberately leaves richer attribute discovery to a later, dedicated activity so a first-pass classification never fabricates a schema.

### Deliverable (when scheduled)
- A dedicated **attribute-identification enrichment activity** in the analyser (phase-B / curation) that, given a DataItem plus its `SURFACES_AT` sites and any bound docs / response-body captures (D25), infers additional fields with **evidence + confidence** attached, MERGEing them into `fields` rather than overwriting the observed set.
- Fields graduate from "observed" (recon-time) to "attributed" (enrichment) with provenance distinguishing the two, so a downstream reader can trust observed fields absolutely and attributed fields probabilistically.
- Evaluation: field precision/recall scored on Langfuse against a small hand-labelled DataItem set, tracked across analyser models (same discipline as AMV-9).

### Why deferred
It needs the richer L0 data surface (AMV-5: `.js` client-model recovery, response-field capture) and the confidence policy (AMV-9) to target real fields with calibrated confidence; doing it in the first pass would reintroduce the guessing this fix removed.

---

## AMV-11 - user journeys (WITHDRAWN from the model; the whole deferral record)

**Status:** proposed (the feature is REMOVED from the codebase; this item is its sole durable record).
**Raised:** 2026-07-19, during FR-JOURNEY (the light-membership journey model, plan §1 / §6).
**Rewritten:** 2026-07-22, when the operator WITHDREW journey grouping outright. This item now absorbs the whole journey question - the removal decision, the ordering extension (its original subject), and the naming-altitude defect formerly recorded as AMV-15.
**Relates to:** FR-JOURNEY and FR-CURATE stage 4 (both removed); plan §1 (adversarial rationale) and §1.2 (the order caveat); AMV-16 (the journey grouper was the one responsibility there argued to be irreducibly global).

### What was built, and what was removed

FR-JOURNEY shipped a LIGHT MEMBERSHIP model: an unordered `journeys: list[str]` prop on each `L1Service`, assigned by the curation pass, with "services in the same journey" as a single property match (`$j IN s.journeys`).
On 2026-07-22 the operator withdrew it: the grouping is complex to get right and does not yield a significant improvement to the L1 model.
Removed in full, with no compatibility shim: `CurationBatch.journeys`, `CurationReport.journeys_written`, `curation._write_journeys` and its pipeline stage, `l1_read.services_in_journey`, `tests/recon/test_l1_journey.py`, the journey sections of the curation and analyser SKILL prompts, and the plan's AST-JRNY-01 / AST-CUR-02 gates (annotated SUPERSEDED in place rather than deleted).

### Why the withdrawal is well-founded (the evidence, not just the decision)

The MECHANISM was correct and verified - `services_in_journey` agreed with stored membership in all three FR-CURE2E runs, and identity never churned (`identity ⊥ membership`, L1D-11).
What failed was the JUDGMENT feeding it. The grouping quality varied wildly across three runs of the same pipeline on the same target (FR-CURE2E, verifier-surfaced):

- `soupcure_pro_batch` (A): genuine business journeys that group properly - `shopper-checkout -> [cart, checkout, delivery, orders]`, `seller-sell -> 3 members`, 5 multi-member journeys.
- `soupcure_pro_stream` (B): most slugs were full ENGLISH SENTENCES ("Basket is converted into a placed order" -> `['checkout']`), each grouping a SINGLE service; only `shopping-flow` and `seller-flow` grouped anything.
- `soupcure_flash_batch` (C): every journey a bare phrase ("add to basket" -> `['cart']`), no high-level grouping at all.

A journey naming one service is not a grouping - it is a restatement of the service.
The entire adversarial value of journey membership (plan §1.1: concentrating cross-service trust reflection on same-journey pairs) evaporates when each journey has one member, so in 2 of 3 runs the feature delivered nothing while still costing a curation stage and prompt budget.
This is the same family as AMV-12 (cross-run identity instability): the LLM picks a different naming ALTITUDE each run, and nothing in the model constrains it.

### Deliverable, if journeys are ever reinstated

Reinstatement has three parts, and the first is the precondition for the other two.

1. **Constrain the altitude** (the defect that killed the feature; formerly AMV-15).
Do not hope for the right granularity - contract it: a slug-shape rule in the curation/bootstrap prompt (kebab-case, 2-4 tokens, naming a multi-step BUSINESS journey, not a single action), a worked example set at the right altitude (plan §1's `checkout-flow` / `signup-flow` / `password-reset-flow` are the right shape and should be IN the prompt), and a post-write validity check that flags single-member journeys and sentence-shaped slugs for re-proposal.
Without this, a future run silently regresses to the run-C shape with no test noticing.

2. **Restore light membership** as it was: `journeys: list[str]` on `L1Service`, assigned by a global pass, queried by property match. The removed implementation is recoverable from this branch's history.

3. **Only then consider ORDER** (this item's original subject).
Light membership cannot express STEP ORDER (basket -> checkout -> payment -> order), so plan §1.1's "unintended unfolding" reasoning - can a later step be invoked without completing an earlier one, can a step be replayed - is posed as hypotheses over an unordered set, not as a reachability query.
Promotion is a first-class `Journey` node with `STEP_OF` edges (`(:L1Service)-[:STEP_OF {order}]->(:Journey)`) placing each service at a step, plus `PRECEDES` edges within a journey.
With order represented, step-skip becomes reachability of a later step without traversing its predecessors, and replay becomes a self-loop / re-entry - each machine-checkable rather than hand-posed.
Journey-carried DataItems then bind to an ORDERED producer/consumer pair (produced at step i, consumed at step j > i), sharpening the journey-scoped trust assumption (plan §1.1 item 4) into a concrete "the value from step i is still trusted at step j" invariant.
This remains a TWO-WAY EXTENSION of light membership, not a rewrite: the unordered prop is the projection `Journey <- STEP_OF`, so both representations coexist and membership derives from order for free.

### Why deferred

The ordered model was always gated on light membership proving its worth first, and light membership did not: in 2 of 3 measured runs the LLM coined journeys at an altitude that grouped nothing.
Building the `Journey` node + `STEP_OF`/`PRECEDES` edges + sole-writer builders + reachability query on top of a judgment that unreliable would be adding schema surface to an unproven signal.
The honest ordering is altitude contract first, membership second, order last - and none of it before there is evidence that journey-scoped reasoning finds faults the per-service and cross-service trust reasoning misses.
Note the tension with AMV-16, recorded rather than resolved: that item argues journey grouping is the ONE responsibility genuinely requiring a global pass and therefore the natural residual home of a shrunken curation. Withdrawing journeys removes that residual, which strengthens the case for shrinking curation further - but it also removes the worked example AMV-16 leans on, so AMV-16's decomposition argument now rests on dedup alone.

---


## AMV-12 - cross-run identity stability for `business_function_slug`

**Intent:** make the L1 business-function identity reproducible across independent runs against the SAME target.

**Live evidence (FR-CURE2E, 2026-07-19/20).** Two runs of the identical pipeline, same target, same model produced only **41% identity overlap** (Jaccard 0.407, 18 vs 20 services). The "disjoint" sets are the SAME business functions under differently-coined slugs: `account-management`/`account`, `admin-panel`/`admin`, `reward-points`/`loyalty`, `support-desk`/`support`, `training-challenges`/`challenges`, `juice-club`/`subscription`. Bootstrap alone varied 15/18/17 services across three runs from an identical operator KB.

**Relation to MVP areas:** FR-INVENTORY solved the WITHIN-project case by injecting the current inventory into every analyser prompt - each run is internally clean (0 synonym pairs in all three runs). A FRESH project has an empty inventory, so the LLM coins fresh names with nothing to anchor on.

**Deliverable shape:** an anchor for first-write naming - a controlled business-function vocabulary seeded from the operator KB (the KB already names the journeys and records), and/or embedding-nearest-slug reuse at bootstrap, and/or a canonical-slug normaliser applied at write time.

**Why deferred:** operationally a project IS the accumulation unit, so within-project stability (already achieved) is what production needs. This bites cross-run graph COMPARISON - benchmarking, regression-diffing a target over time, and the observational half of the streaming-vs-batch check - not day-to-day operation.

---

## AMV-13 - dedup normaliser needs light stemming

**Intent:** catch morphological synonym pairs the current duplicate check misses.

**Live evidence:** FR-CURE2E surfaced `seller-payouts` vs `seller-payout` - a bare plural. The A1 normaliser (casefold + strip non-alphanumerics) maps these to `sellerpayouts` / `sellerpayout`, which do not collide, so the pair passes as distinct identities.

**Relation to MVP areas:** FR-INVENTORY (prevention, the reuse prompt) and FR-CURATE (the LLM's merge judgment). Both currently rely on exact-key reasoning.

**Deliverable shape:** light stemming (plural/singular, gerund) in the normaliser used by the dedup assertion and the curation prompt's duplicate hint. Deliberately NOT full embedding similarity - the plan already rejected that in favour of LLM-judged reuse; this is only the cheap morphological layer.

**Why deferred:** a single observed instance, and the curation LLM catches most such pairs semantically. Worth fixing when a dedup-precision pass is next opened.

---

## AMV-14 - a recon job that returns NOTHING is indistinguishable from one that worked

**Intent:** make an empty/failed tool result observable instead of silently succeeding.

**Live evidence (FR-CURE2E, near-miss).** The Juice Shop target container exited (133) mid-experiment. The next full run reported **every job `success`** and the run **`complete` in 39.7s** (against ~927s for a healthy run) while producing **1 endpoint** instead of 182. Nothing in the run status, job status, or logs distinguished a dead target from a clean run. Had the implausible 23x speedup not been questioned, this would have been written up as a MODEL QUALITY finding ("flash produces a far thinner graph than pro") when it was purely an infrastructure failure.

**Relation to MVP areas:** `run_pipeline` is deliberately best-effort (a job whose pods all fail is marked `degraded` and the pipeline still reaches terminal `complete`) - correct for resilience, but it means yield is never asserted. Compounds AMV-8 (crawl/parse scope): both concern trusting what recon returns.

**Deliverable shape:** per-job yield expectations (a job that historically returns N assets returning ~0 is `degraded`, not `success`); a run-level surface-sanity gate; and a target-liveness precondition checked BEFORE a run rather than inferred afterwards. The FR-CURE2E driver now carries an interim gate (abort below 20 endpoints) - that belongs in the pipeline, not a scratchpad driver.

**Why deferred:** it is an observability/quality-gate change to the recon pipeline, outside the curation plan's scope, and the interim driver gate covers the immediate e2e need. It should be picked up with AMV-8/AMV-9 as one "trust what recon returns" area.

---


## AMV-15 - journey slugs are coined at an inconsistent ALTITUDE across runs

**Status:** FOLDED INTO [AMV-11](#amv-11---user-journeys-withdrawn-from-the-model-the-whole-deferral-record) (2026-07-22).
The altitude defect recorded here is what motivated withdrawing journey grouping entirely, so its evidence and its deliverable (the slug-shape contract + post-write validity check) now live in AMV-11 as the precondition for any reinstatement.
The number is retained so existing references resolve; do not add new content here.

---

## AMV-16 - decompose the analyser into responsibility-scoped agents behind an AUDITOR (prevention-at-creation over repair-after-the-fact)

**Status:** proposed.
**Raised:** 2026-07-20, from operator review of the FR-CURE2E results (`docs/design/post-recon-curation-and-l1-remediation-plan.md` §7).
**Relates to:** the analyser pod (`agent/recon/analysis/pod.py`), the curation pass (`agent/recon/analysis/curation.py`), the streaming step (`agent/recon/analysis/streaming.py`), the sole-writer (`agent/recon/analysis/l1_curator.py`); and directly subsumes AMV-8 (L0 noise), AMV-9 (assignment-confidence / stale policy, realising L1OP-5), AMV-12 (cross-run identity stability), AMV-13 (dedup stemming), AMV-15 (journey altitude).

### The thesis, sharpened

The operator's seed: *a curation phase can be a defective design choice, because in principle fixing something done earlier is wrong - such flaws should be prevented during creation.*
The proposal below decomposes the analyser into several responsibility-scoped agents fronted by an **auditor**, and is deliberately orthogonal to whether analysis runs streamed or batched.

The empirical case is strong, but it does not support deleting curation outright.
It supports SHRINKING curation to the work that genuinely needs a global view, and moving the rest to prevention at creation.
The evidence, not first principles:

1. **A whole repair stage was structurally broken for a long time, undetected, because on a clean graph it is indistinguishable from a no-op.**
Post-recon curation could not deduplicate at all (§7, "the headline finding"): `run_curation` read its index-cards ONCE at stage 1 (`curation.py:_read_context` at stage 1) and passed that snapshot to every later stage; stage 3 merged a duplicate away, then stage 5's `commit_anatomy` MERGEd the Service back by slug from the stale list, so curation silently undid its own dedup and reported `merged=1` forever without converging.
The bug was root-caused and fixed by re-reading the context after any destructive op (`curation.py:427-428`), but the deeper lesson is the one that motivates this item: a repair stage whose success on the happy path is *identical to doing nothing* rots undetected.
Runs A and B passed the dedup assertions VACUOUSLY with `merged=0` (§7, "why it was nearly missed") - not because reconciliation worked, but because upstream PREVENTION (FR-INVENTORY identity pinning + FR-TYPESEP-a) meant no duplicate was ever written.
That is the thesis in live form: the prevention that was added at creation is what actually kept the graph clean; the repair that existed to fix earlier mistakes was both broken and never exercised on the real path.

2. **Assignment quality is highly non-deterministic and, under repeated partial passes, monotonically degrades.**
Streaming over-assigns (19.7% strict noise vs batch 0%, §7 precision table) because the surface is analysed once per producing job against a PARTIAL surface and MERGE accumulates monotonically with no retraction, so every speculative early assignment is permanent (`streaming.py` header; §7 "plausible mechanism").
`deepseek-v4-flash` produced 0 assignments on the identical 182-endpoint surface where `v4-pro` produced 90 (STATE.md, "LLM_MODEL_ANALYSER ... CANNOT assign").
Cross-run identity is unstable (Jaccard 0.407, AMV-12) and journey slugs are coined at inconsistent altitude (AMV-15).
None of these is fixed by a downstream repair pass; each is a property of HOW the write is made.

3. **Decomposition-by-responsibility is already proven to improve quality in this codebase.**
The analyser is ALREADY a two-pass split (`pod.py:_two_pass_analyse`, `pod.py:377`): an assignment pass, then a DEDICATED data-modelling pass.
The split was introduced because one combined "do everything" call systematically deprioritised data modelling under assignment load (observed live: `finish_reason='tool_calls'`, not a token cutoff, 150 aggregates + 90 system_edges, 0 data_items - `pod.py:388-390`).
This item generalises that finding: when two responsibilities INTERFERE inside one prompt, splitting them by responsibility recovers the crowded-out one.

**Where the evidence contradicts the thesis (recorded honestly, per the loop's evidence standard).**
The thesis "fixing-after-the-fact is wrong in principle" is only partly borne out:

- **Some work is irreducibly global and cannot be done at per-slice creation time.**
Journey grouping is a whole-solution judgment: a per-slice creator that sees one recon job's surface literally cannot see the whole service set a flow spans (plan §1, §4).
Cross-service dedup needs a global view by construction.
For these, a global pass is the RIGHT shape, not a design defect - the honest conclusion is "shrink curation to what needs a global view", not "delete curation".

- **The failure that seeded the thesis was a testability/observability failure, not proof that repair is conceptually wrong.**
The repair stage rotted because it was a no-op on clean inputs and nobody could tell.
An auditor that vetoes bad writes BEFORE they land inherits *exactly* the same trap: on a clean proposal stream it is also a no-op, and it is equally hard to prove it is doing anything (this is the `stale_pool=0 is a NEGATIVE signal` lesson, §7, in a third form).
Moving the check earlier does not, by itself, solve "the check is vacuous on good inputs".
So the auditor must be built with its own adversarial (dirty-input) probe from day one - the same discipline the FR-CURE2E dirty-graph probe supplied for reconcile (§7, ADV-1..4) - or it will rot the same way.

- **The batch path already reaches 0% noise via prevention alone.**
FR-INVENTORY prompt-shaping (the un-truncated EXISTING L1 IDENTITIES block, `pod.py:_inventory_block` at `pod.py:202`) took batch from the 2026-07-17 baseline's 31-38% noise to 0% (§7, final paragraph) with NO new agent.
That is evidence FOR the thesis (prevention worked) and simultaneously a caution AGAINST over-building: if cheap prompt-shaping already got batch to 0%, a multi-agent orchestration must clear a high bar to justify itself (see Falsifiers).

### The agent decomposition

Each agent has ONE responsibility, a typed input, a typed proposal output, and writes ONLY through the `l1_curator` sole-writer.
All proposal types already carry `confidence` + `evidence_refs` (`analyser_types.py:AggregatesProposal`, `anatomy.py:SpineClassification`), which is the interface the auditor consumes.

1. **Assigner** - responsibility: L0 element -> Service membership (the AGGREGATES edge).
Input: an L0 slice + the current Service inventory + observations.
Output: `AggregatesProposal[]` (service_slug, l0 ref, confidence, evidence_refs).
This is `pod.py` pass 1's assignment portion.
**Per-slice: safe to stream** - "which service owns this endpoint" is a local judgment over the element and the (globally-consulted) Service inventory.

2. **Data modeller** - responsibility: logical DataItems + Tier-1 PRODUCES/CONSUMES trust + DataRelationships.
Input: the settled assignment (services + the endpoints they own) + an identity-only surface digest (`pod.py:_compact_l0_for_data`).
Output: `data_items`, `surfaces_at`, `data_flows`, `data_relationships`.
This is `pod.py` pass 2 (already split out, empirically).
**Mostly per-slice**, but its quality depends on the assignment being reasonably settled, so in streaming it is best run on the fuller slices.

3. **Mechanism typist** - responsibility: system/mechanism typing (rendering, navigation, API paradigm, auth, perimeter) as typed Service->System edges, never Service props.
Input: a Service + its surface signals.
Output: `system_edges` + the target System deltas (e.g. a `WebPresentation` carrying rendering_model + navigation_model as independent props).
This logic is TODAY scattered across three places: the analyser prompt rule (`pod.py:_SYSTEM_FACTS_ARE_EDGES_RULE`, `pod.py:231`), the curation deterministic re-homing backstop (`curation.py:rehome_service_props` + `_REHOME_RULES`, `curation.py:108`), and the anatomy skills (`anatomy.py:webpage_profile` / `classify_authz`).
Consolidating it into one agent removes the scatter and the "the analyser should have produced this with a `system_edges` entry in the first place" round-trip the re-homing backstop exists to undo (`skills/analysis/curation/SKILL.md:68`).
**Per-slice** (per-service), so safe to stream.
Its `fingerprint_only -> forced-Low-confidence + forced-probe` rule (`anatomy.py:_enforce_fingerprint_insufficiency`, `anatomy.py:113`) is already a working *micro-auditor*: a deterministic structural rule that caps an over-confident classification and demands corroborating evidence.
The auditor below generalises exactly this proven pattern.

4. **Journey grouper** - responsibility: whole-graph journey membership.
Input: the WHOLE settled Service set (index-cards).
Output: `journeys` memberships (light membership prop, plan §1).
**Inherently global**: it cannot be a per-slice creator because a flow spans services that a single recon-job slice never co-observes.
This is the one responsibility that genuinely justifies a global pass, and it is the natural residual home of the shrunken curation.
It also owns the AMV-15 altitude contract (kebab-case, 2-4 tokens, multi-step business journey, reject single-member journeys).

5. **Identity reconciler (residual, global)** - responsibility: only the dedup that prevention structurally cannot reach.
Prevention (agents 1-4 consulting the shared inventory at creation, FR-INVENTORY) already keeps a project internally clean (0 synonym pairs in every FR-CURE2E run, §7).
What it cannot reach is the FRESH-project case (empty inventory, nothing to anchor on -> AMV-12) and morphological collisions (`seller-payouts` vs `seller-payout` -> AMV-13).
So this agent shrinks to a controlled-vocabulary anchor + a stemming-aware normaliser, not a full cross-service merge engine.

**The interface between agents** is the existing `L1DeltaBatch` proposal shape plus the sole-writer.
Agents never see each other's internal reasoning; they see the current L1 inventory + index-cards (the token-light projection, `index_card.py`) and emit typed proposals.
That is the same seam the two-pass split already uses (pass 2 receives pass 1's assignment, `pod.py:402-405`), so the decomposition is a widening of an existing contract, not a new one.

### The AUDITOR (central)

The auditor sits between every proposer and the sole-writer.
It audits **proposals BEFORE they are written**, not the graph after - that placement is the whole point, because it is what makes this prevention-at-creation rather than repair-after-the-fact.

**What it audits** (each maps to a measured failure mode, so the auditor is the natural home for the currently-orphaned AMV policies):
- the assignment-confidence / stale-pool policy (**AMV-9** / L1OP-5): below a threshold, an AGGREGATES proposal does NOT become an edge and the L0 node stays in the stale pool - directly bounding the over-assignment that made a stronger model produce WORSE discipline (§7; `stale_pool=0` as a negative signal);
- the noise classifier (**AMV-8**): a static-asset / source-tree / string-concat-fragment L0 element is never business-assigned by default (`/chunk-*.js`, `/ethers.js`, `node_modules` source, `/'+_(i[8])+'`);
- identity-reuse enforcement (**AMV-12/13**): a proposed slug that collides with an existing identity under a stemming-aware normaliser is rejected in favour of reuse;
- the journey-altitude contract (**AMV-15**): a single-member or sentence-shaped journey slug is rejected.

**How it avoids being another LLM whose output nobody checks** - the load-bearing design constraint:
- It is **deterministic first**.
The confidence gate is a numeric threshold; the noise classifier is an extension/pattern allowlist; the identity normaliser is stemming; the altitude check is a token-count + member-count rule.
None of these needs an LLM, and each is unit-testable against the live-evidenced failure sets already recorded (§7, AMV-8/9/12/13/15).
- Where a judgment IS genuinely ambiguous, the auditor's LLM call emits a **structured verdict** (`accept` / `reject` / `demand-evidence`, with a cited reason), and that verdict is checkable against the `evidence_refs` the proposer supplied: does the ref point to a real L0 node in the slice; does the assigned endpoint actually carry the claimed signal.
An LLM that must cite a checkable ref is not an unchecked LLM.
- Its verdicts are logged and scored on Langfuse (the eval discipline AMV-9 already calls for), so a capability regression like flash-cannot-assign is caught by a moving score, not by luck.
- Critically, it embodies the **maker/checker discipline the humans already use**: the proposer is the maker, the auditor is the SEPARATE checker (different responsibility, ideally a different/cheaper model), never the proposer re-reading itself.
This is the same principle `loop-constraints.md` mandates for the loop-verifier, and the same principle the FR-CURE2E write-up vindicated when a separate verifier caught two overstatements in a self-honest write-up (§7, A6; loop-run-log 2026-07-20: "the argument for maker/checker being a SEPARATE agent rather than a self-review pass").

**Authority** (staged, see Migration): start at **score-and-annotate** (verdict written onto the proposal envelope, no write blocked), graduate to **veto** (a rejected proposal does not become a write) only once the annotations are shown to correlate with the known-noise set, and reach **demand-evidence** (the auditor emits an interface-B backward-recon request, reusing `AnalyserReconRequest`, and defers the write until the probe resolves) last.
Veto is powerful and dangerous: a mis-calibrated veto suppresses real surface, and a suppressed element that never becomes an Endpoint is invisible (the AMV-14 "nothing is indistinguishable from success" hazard, one layer up).

### Orthogonality to streaming vs batch

The agent set is IDENTICAL in both modes; only the slice size differs.
This follows directly from L1D-23 and the existing pure-function framing: batch runs proposer(s) -> auditor -> writer ONCE over the complete surface; streaming runs the SAME proposer -> auditor -> writer per recon-job slice as surface is produced (`streaming.py` invokes the same `run_analyser`).
The decomposition transcends delivery mode because none of the agents' responsibilities are defined in terms of "batch" or "stream" - they are defined in terms of the surface and inventory they are handed.

**Hypothesis: an auditor with RETRACTION authority would close the streaming precision gap.**
The measured cause of streaming's precision decay is monotonic MERGE accumulation with no retraction (§7): every speculative early assignment over a partial surface is permanent.
If the auditor may, on a later fuller slice, propose a DELETE of a previously-written AGGREGATES edge that the fuller surface now contradicts, streaming stops being monotone and its precision should converge toward batch's 0%.
**Falsifier:** run streaming with the retraction-capable auditor on the FR-CURE2E target; if the noise share does not fall materially from 19.7% toward batch's 0%, retraction is not the lever and the streaming precision gap has another cause.
**Cost caveat on this hypothesis:** retraction reintroduces DESTRUCTIVE writes into the streaming path, which today is OOM-safe partly because it only does idempotent MERGE (`streaming.py` design notes); destructive ops mid-recon change that property and must be re-benchmarked on the constrained host.

### Migration path (incremental; no big-bang rewrite)

**Two-way doors (reversible; do first):**
1. Name the existing `_two_pass_analyse` passes as the **Assigner** and **Data modeller** agents, each with its own skill file, composed via `skill_for` (the loader already supports this, `skills.py`).
Pure refactor of code that already runs as two passes.
2. Introduce the **Auditor** in **score-and-annotate mode only** - it annotates each proposal with a verdict + audit-confidence but blocks nothing.
This lets you MEASURE whether the auditor's verdicts correlate with the AMV-8/9 known-noise set before giving it teeth.
Fully reversible (delete the annotation).
3. Consolidate the three scattered mechanism-typing sites (prompt rule, re-homing backstop, anatomy skills) into the **Mechanism typist** agent, keeping the deterministic re-homing backstop as its fallback.

**One-way doors (do later, behind evidence):**
1. Grant the Auditor **veto** authority.
Once creators rely on it to catch their noise, removing it regresses precision; and a mis-calibrated veto silently suppresses real surface.
Gate on the score-and-annotate correlation from step 2 above.
2. Grant the Auditor **retraction** authority in the streaming path (destructive writes during recon), which changes streaming's OOM-safety and idempotency profile.
Gate on the orthogonality hypothesis's falsifier.
3. **Shrink curation** to the Journey grouper + residual Identity reconciler once the prevention agents are shown (by an adversarial dirty-input probe) to keep the graph clean without the reconcile/rehome/anatomy stages.
This deletes a safety net, so it is one-way in the sense that matters.

### Why deferred / what it costs

- **More LLM calls.**
Today: 2 analyser passes + 1 curation propose + N webpage-profile calls (one per Service).
Adding an auditor call per proposal batch at minimum doubles the round-trips per slice; in streaming that multiplies by the number of producing jobs.
The FR-CURE2E streaming run already cost 2421s recon (2.6x the 927s batch, §7); an auditor on the streaming path pushes that further.
- **More latency and OOM risk on a host that already fails.**
The target alone holds 1.788GiB of the 3.827GiB host (STATE.md), leaving ~0.9GiB for the whole stack; that run saw two postgres recovery events, a target `exit(133)`, and two agent-container recreations.
Mitigation (mirroring the streaming design): run agents SEQUENTIALLY, never concurrently, so peak memory stays one model pass.
- **More orchestration surface = more interaction defects.**
The exact class of bug FR-CURE2E caught (a stale context snapshot passed between stages, resurrecting a merged-away node) multiplies with more stages and more inter-stage contracts.
This is a direct argument both for deferral and for a hard rule that every agent (and the auditor) re-derives from the live graph, never from a snapshot handed down a pipeline.
- **An eval harness is a prerequisite.**
The auditor's gate needs a labelled assignment-precision set on Langfuse (AMV-9's deliverable) to calibrate; that harness does not exist yet, and building the auditor without it just moves the uncalibrated judgment to a new place.

### Falsifiers (what would show this refactor is NOT worth doing)

1. **No auditor signal.**
If the score-and-annotate auditor's verdicts do not correlate with the AMV-8 known-noise set, the auditor has nothing to gate on: the noise is upstream (an L0 element that should never have been an Endpoint), and no L1 auditing fixes it - AMV-8 (L0 crawl/parse scope) is the fix, not this.
2. **Cheaper prevention already suffices.**
Batch already reaches 0% noise from FR-INVENTORY prompt-shaping alone (§7).
If a simple AMV-9 threshold-gate inside the existing single writer plus the AMV-8 L0 classifier recovers most of the remaining precision (the streaming case), the multi-agent orchestration is over-engineering.
3. **Cost outweighs gain on the real host.**
If the added LLM latency / OOM cost makes runs infeasible on the target host and the precision gain is below what the AMV-9 gate alone delivers, defer indefinitely.
4. **Decomposition is not monotone in quality.**
The evidence is that MORE capability (v4-pro) and MORE passes (streaming) both made assignment WORSE, not better; decomposition helped only where responsibilities INTERFERED (assignment vs data modelling).
If a controlled measurement of per-responsibility quality before/after splitting Assigner from Mechanism typist shows no interference between them, that split buys nothing and should not be made.

## AMV-17 - adaptive rate-limit degradation: a throttled tool must back off, not fail silently

**Status:** proposed.
**Raised:** 2026-07-22, from the arjun non-determinism fix (`agent/recon/jobs.py`, the `arjun` JobSpec).
**Relates to:** the pod retry gate (`agent/recon/pod.py`), the job-level LLM steering (`agent/recon/job_agent.py`), the triager (`skills/recon/triager/writing-observations/SKILL.md`), and the steering-signal channel (`agent/recon/pipeline.py` / `agent/recon/steering.py`). Compounds AMV-14 (a job that returns nothing is indistinguishable from one that worked) - a throttled tool is precisely that failure mode with a known cause.

### Intent

When a tool is blocked or throttled by the target, degrade its request rate GRADUALLY - with a pause between attempts - until it succeeds, instead of retrying identically until the attempt budget is exhausted.
Two halves that must be built together: a configurator specialised in this reasoning (it owns the ladder), and a triager that can DETECT rate limiting (a 429, or a 403 that appears under load but not in isolation) and steer the configurator with that finding.

### Live evidence

arjun's parameter detection was non-deterministic run-to-run on an identical surface (58 params one run, 5 the next, FR-CURE2E forensics), root-caused to the target throttling the request burst: arjun's own error handler reads a rate-limited target as an anomaly, so throttled responses become phantom or missed parameters.
The interim fix is a FIXED cap, `--rate-limit 5`, chosen from measurement (see the JobSpec comment: ~260 requests per URL, wall-clock exactly linear in the cap, ~52s per URL at 5 rps against ~6x headroom under `EXEC_TIMEOUT_S=300`; the unlimited default sustained ~65 rps per process and, unbatched at `MAX_PODS=20`, ~1300 rps aggregate against a single host).
A fixed cap is a guess at a budget that is a property of the TARGET, not of the tool: too high and it still trips a stricter target, too low and every run pays the worst case. Only an adaptive ladder tracks the real budget.

### What exists today (verified, and it is less than expected)

- **The retry loop is identical-retry.** `pod.py` `gate` routes back to `configurator` while `iteration < MAX_POD_ITERS` (default 3). The failure predicate is exactly one thing: `exec_result.returncode != 0`. A clean exit with empty stdout is deliberately routed to the parser as a valid zero-finding result.
- **There is NO backoff and NO reconfiguration between attempts.** `configurator` recomputes the command via `fill_template`, a pure function of `(command_template, input_asset, extra, session_id, tool)` - none of which change between attempts. It never reads `iteration` or `exec_result`. Attempt 2 and 3 issue a byte-identical command, immediately, with no pause.
- **Correction to the framing that raised this item:** katana does NOT implement a degraded-retry pattern to inspire from. Its template is a fixed constant string with hardcoded `-d 3 -c 10 -rl 50` and no variant set, no ladder, and no `{rate_flags}` slot (it is deliberately excluded from the throttle mechanism because it already carries its own `-rl`/`-c`). **No job anywhere in the repo is retried with different parameters.** The only genuine analogue is `pod._RATE_FLAGS`, a single-entry table `{"ffuf": "-rate 5 -p 0.2"}` filled into a `{rate_flags}` placeholder - and it is decided ONCE before the pod starts, constant across all attempts. It is a preventive pre-run choice, not failure-driven adaptation.
- **The triager cannot report throttling.** It runs only on the SUCCESS path (a failed pod goes `fail -> END` and never reaches it), emits only free-form `Observation` records, and its skill explicitly BANS recording HTTP status codes as an anti-pattern (a bare 403 must be interpreted, e.g. as `exposed_admin`, never recorded as a status). 429 appears nowhere in the skill or in any steering vocabulary.
- **The steering channel is too coarse and too late.** `read_steering_signals` matches only `WAF_MACRO_KINDS = {"waf_protected", "waf_detection"}`, and is called once per PHASE after every job in it has finished. There is no path from a triager back to the configurator of the same pod, or even the same phase.

So all three capabilities this item needs - per-attempt reconfiguration, a pause between attempts, and a rate-limit signal reaching the gate or configurator - are absent. This is a build, not an extension.

### Deliverable shape (when scheduled)

1. **A rate-limit detection signal.** Make throttling observable: admit a `rate_limited` macro_kind (429, or 403 correlated with request volume) into the triager's vocabulary as a deliberate exception to the no-status-codes rule - the ban exists to stop status codes masquerading as findings, and this is a control signal, not a finding. It must be emitted on the FAILURE path too, which today terminates before any triage.
2. **A ladder-aware configurator for throttle-sensitive jobs.** Per-attempt reconfiguration keyed on the previous attempt's outcome: a descending rate ladder (e.g. arjun 5 -> 2 -> 1 rps) with an explicit pause between attempts, a stop condition, and the chosen rung recorded on the result so a run's effective rate is legible afterwards. This requires `configurator` to read `iteration` and `exec_result`, which it currently does not.
3. **A same-pod feedback path** from detection to the ladder, since the existing steering channel resolves only at a phase boundary - far too late for the pod being throttled.
4. **Interaction with concurrency.** The budget is per-TARGET, not per-process: `MAX_PODS=20` unbatched arjun pods each honouring 5 rps still present ~100 rps to one host. The ladder is close to meaningless without a per-target aggregate budget shared across concurrent pods.

### Why deferred

It spans four subsystems (pod gate, configurator, triager skill, steering vocabulary), each wanting its own bounded maker/checker loop, and every one of the three prerequisite capabilities has to be built from nothing - the assumed prior art (katana) does not exist.
The fixed `--rate-limit 5` covers the immediate defect with measured headroom, so the adaptive ladder is a quality improvement on a working path rather than a fix for a broken one.
It should be picked up together with AMV-14 and AMV-8 as one "trust what recon returns" area: all three are the same question - distinguishing a tool that genuinely found nothing from one that was prevented from looking.

---

<!-- Append new after-MVP work items below as AMV-n, newest last. Keep each item self-contained: intent, relation to MVP areas, deliverable shape, and why deferred. -->
