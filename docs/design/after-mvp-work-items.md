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

## AMV-11 - ordered journey promotion

**Status:** proposed.
**Raised:** 2026-07-19, during FR-JOURNEY (the light-membership journey model, plan §1 / §6).
**Relates to:** FR-JOURNEY (the `journeys: list[str]` prop + `services_in_journey`), FR-CURATE (journey assignment in the curation pass); plan §1.1 (adversarial rationale) and §1.2 (the recorded order caveat).

### Observation
The light-membership model records journey participation as an unordered `journeys: list[str]` prop on each `L1Service`, and "services in the same journey" is a single property match (`$j IN s.journeys`).
This deliberately cannot express STEP ORDER within a journey (basket -> checkout -> payment -> order), so the plan §1.1 "unintended unfolding" reasoning - can a later step be invoked without completing an earlier one, can a step be replayed - is posed as falsifiable hypotheses over an unordered set, not as a precise reachability query.
Order is the one thing light membership drops, and it is exactly what a rigorous business-logic / step-skip analysis wants once the service set has stabilised.

### Deliverable (when scheduled)
Promote journeys from a prop to an ORDERED structure: a first-class `Journey` node with `STEP_OF` edges (`(:L1Service)-[:STEP_OF {order}]->(:Journey)`) placing each service at a step, and `PRECEDES` edges (`(:L1Service)-[:PRECEDES]->(:L1Service)` within a journey) capturing the intended step succession.
With order represented, "unintended unfolding" becomes a precise state-machine reachability query over the journey graph: reachability of a later step's service without traversing its predecessors is a step-skip candidate, and a self-loop / re-entry is a replay candidate - each a machine-checkable claim rather than a hand-posed hypothesis.
Journey-carried DataItems then bind to an ORDERED producer/consumer pair (produced at step i, consumed at step j > i), sharpening the journey-scoped trust assumption (plan §1.1 item 4) into a concrete "value from step i is still trusted at step j" invariant.
This is a TWO-WAY EXTENSION of the light model, not a rewrite: the unordered `journeys` prop is the projection `Journey <- STEP_OF`, so the two representations coexist and membership derives from order for free (a curation pass can populate `journeys` from the `Journey`/`STEP_OF` structure and vice versa).

### Why deferred
Light membership is a strict SUBSET of the ordered model, and unordered membership already unlocks the plan §1 adversarial leverage that matters first: cross-service trust concentration on same-journey pairs, the step-skip / replay hypotheses (as hypotheses, per §1.1 item 2), the trust-boundary-discontinuity signal across a journey, and the journey-carried-DataItem marking.
Building the `Journey` node + `STEP_OF`/`PRECEDES` edges now would add a schema surface (a new node label + two ordered edge types + the sole-writer builders + the reachability query) ahead of any evidence that unordered reasoning is insufficient, and the operator explicitly chose light membership for exactly this reason (plan §1.2).
Captured as a clean two-way extension so the ordered structure is picked up as its own bounded area if order-based reasoning proves necessary, without churning the membership prop already in use.

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

<!-- Append new after-MVP work items below as AMV-n, newest last. Keep each item self-contained: intent, relation to MVP areas, deliverable shape, and why deferred. -->
