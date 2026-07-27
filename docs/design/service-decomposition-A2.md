# Phase-A.2 service decomposition (the SolutionArchitect "decompose" phase)

> **STATUS: DEFERRED - post-v1.** Extracted from the v1 attack-surface-analysis stream (#1): service decomposition is complex and NOT strictly required for the first version of the analysis.
> This spec is intentionally kept as detailed as possible so it can be picked up later and taken straight to implementation.
> Tracking ticket #27 stays OPEN, labelled `enhancement` (no longer `workflow` / `ready-for-agent`, and no longer a sub-issue of #1).
> The ordered build steps are in §12 (implementation pickup sequence); the lift-ready assertion catalogue is in §11.

Status: RATIFIED DESIGN + SPEC (grilling closed 2026-07-26); DESIGNED-NOT-BUILT; DEFERRED post-v1.
This document is the architecture record (docs/design/) AND the `/to-spec` specification for the capability.
It supersedes the earlier additive-hierarchy draft, which the operator rejected in favour of the unpack model below.
It is subordinate to the ratified wayfinder (#1) and the per-agent specs (#7 Bootstrapper, #9 TechnicalSystem); the implementation ticket (#27) was opened from its "Specification" section.

Conventions: plain dash only; one full sentence per physical line; ubiquitous language from `src/polymerhus/analysis/CONTEXT.md`.

---

## 1. Why this capability exists (the eval finding)

The redesigned Bootstrapper (#7 / `bootstrap.py`, now the SolutionArchitect `bootstrap` phase) projects the operator KB into an L1 Service skeleton that is exhaustive and breadth-leaning, but its Services are UMBRELLAS too coarse to test discretely.
The three-target eval (`eval_daytona.json`, `eval_magnific.json`, `eval_moodique.json`) makes the failure concrete:

- daytona `agent-tools` (one node, `authenticated`) bundles file-ops, git, process/code execution, PTY, LSP, log-streaming, computer-use, and agent-skills.
- daytona `human-access` (one node, `authenticated`) bundles web-terminal, SSH (SSH-token), VNC, VPN, and preview-URL (preview-token OR a public signed URL) - functions with DISTINCT auth_contexts, one of which is actually PUBLIC, collapsed into one authenticated node.
- magnific `image-services` bundles roughly twelve tools behind one node.
- moodique `product-page-and-reviews` bundles a PUBLIC product/catalogue page with AUTHENTICATED review-write, and the umbrella's single `authenticated` exposure FLIPS the whole node closed, hiding the public surface.

Two harms follow.
(a) Coarse umbrellas lose discretely-testable units: a fault in git-exec and a fault in log-streaming are one indistinguishable target.
(b) Coarse umbrellas conflate distinct auth_contexts and let one leaf's exposure overwrite the node's, either hiding a public surface (moodique) or overstating an authenticated one.

Phase-A.2 service decomposition unpacks each umbrella business-function Service into finer subordinate services that stay discretely testable, and disambiguates the auth_context per leaf.
The operator calls this "screaming" decomposition after screaming architecture: each finer service should scream its discrete function rather than hide inside a catch-all.

---

## 2. Domain model (new and sharpened terms)

These land in `src/polymerhus/analysis/CONTEXT.md` when the capability is built (the keep-the-model-current rule); drafted here.

**SolutionArchitect (phase-parameterized agent).**
The agent that owns the shape of the L1 Service population in two phases: `bootstrap` (pre-A.1, project the KB into umbrella Services + the linchpin auth Systems - the existing #7 behaviour) and `decompose` (A.2, unpack each umbrella into discretely-testable subordinate services).
It is the Bootstrapper generalised, not a new agent; the roster stays at six.

**Umbrella service.**
A coarse business-function `Service` the `bootstrap` phase produced that bundles several discretely-testable functions and/or distinct auth_contexts under one node.
A valid Service (keyed on `(project_id, business_function_slug)`), not a defect - it is the deliberate breadth-first skeleton (a missed Service is costlier than an over-proposed one).
At `decompose` it is UNPACKED: deleted and replaced by its subordinate services.

**Subordinate service.**
A finer `Service` unpacked from an umbrella that is still discretely testable - it has its own business purpose and its own auth_context - and is NOT a single endpoint, parameter, or header.
An ordinary `:L1Service` PEER entity, keyed on its OWN `business_function_slug` of the form `<umbrella>-<leaf>` (a naming mnemonic that aids reasoning and traceability; it is a plain slug, not a structural key - see §5).
A subordinate is always a SOLUTION-PROFILE business function (e.g. `sign-out`), never a TECHNICAL System concern (e.g. the session lifecycle, which is an AuthenticationMechanism / IdentificationSystem property) - the same solution-vs-technical split the operator applied to the service linchpins in `bootstrap.py` (correcting `session-management` -> `sign-out`).
A leaf that names a technical mechanism rather than a business action is a category error (mechanism-as-System, `CODING_STANDARD` §1) and the testability guard must withhold it.
_Avoid_: sub-service, child, endpoint (that is Layer-0).

**Service decomposition (unpack).**
The `decompose`-phase operation that DELETES an umbrella and replaces it with flat peer subordinate services, redistributing every one of the umbrella's relationships (System edges, DataItem flows, L0 `AGGREGATES`) onto the correct subordinate.
A business-projection refinement that mints no new L0 references - it re-points existing ones.
_Avoid_: hierarchy, parenting (the rejected additive model); splitting into leaves-under-a-retained-parent.

**auth_context (per-leaf).**
The trust framing a leaf is reached under: on the Service, ONLY its `exposure` (`public` / `authenticated`).
Per mechanism-as-System (`CODING_STANDARD` §1), the specific gating MECHANISM (SSH-token vs preview-token vs public signed URL vs OIDC session) is a `System` reached by an `AUTHENTICATED_BY` / `AUTHORIZED_BY` edge, owned by the TechnicalSystem Analyser (#9), never a Service prop.
Decomposition MATERIALISES the auth_context distinction structurally - one leaf per distinct trust framing, each with its own `exposure` - and records any suspected mechanism only as a transient Langfuse `claim`.

**SPLIT op (the new sole-writer operation).**
The destructive `l1_curator` reconciliation that executes an unpack: MATCH the umbrella, MERGE the N subordinate services, re-point each of the umbrella's in/out edges onto the subordinate the redistribution map assigns it, then DETACH DELETE the umbrella - one idempotent, provenance-stamped delta.
It joins the existing `merge` / `delete` / `relabel` reconcile family (the one-to-many counterpart of `merge`'s many-to-one).
_Status_: DESIGNED-NOT-BUILT until the `l1_curator` op lands.
It REOPENS the wayfinder's deferred service-split - flagged in §9.

---

## 3. Where the phase sits in the A.1/A.2 flow

1. `bootstrap` (pre-A.1): KB -> umbrella Service skeleton + the 3 linchpin auth Systems + the forced service linchpins (unchanged; the existing #7 path, now `phase="bootstrap"`).
2. A.1 (streamed, per recon job): Assigner attaches L0 to umbrellas via `AGGREGATES`; TechnicalSystem/DataPlane build per-umbrella at high confidence.
3. **A.2 service decomposition (NEW, the FIRST A.2 sub-step)**: unpack each umbrella into subordinate services + per-leaf exposure; redistribute the umbrella's edges; delete the umbrella. Runs once, per-service loop, at the recon phase-barrier.
4. A.2 TechnicalSystem missing-systems sweep (#9): now iterates the FINER subordinate set and attaches the distinct `AUTHENTICATED_BY` / `AUTHORIZED_BY` System edges per leaf - where the SSH-token vs preview-token mechanism distinction lands, as System discriminators.
5. A.2 DataPlane sweep (#10).
6. A.2 Anti-cluttering cleaner (#11): dedup / retraction.

Decomposition MUST precede the A.2 TechnicalSystem/DataPlane sweeps so the finer subordinate set exists before per-service auth Systems and data flows are re-derived onto it.
Because the unpack redistributes the umbrella's existing edges at split time (§6, distribution), there is NO deferred re-home handoff to #11 - the graph is coherent the moment the phase completes.

---

## 4. The ratified decisions (the grilling ledger)

1. FORM: GENERALISE the Bootstrapper into a phase-parameterized SolutionArchitect (`phase in {bootstrap, decompose}`); the existing #7 path becomes `phase="bootstrap"`; the roster stays six.
2. STRUCTURE: UNPACK, not hierarchy - delete the umbrella, replace with flat peer subordinate services; no `DECOMPOSES` edge, no retained parent.
3. IDENTITY: subordinate slug `<umbrella>-<leaf>` (a naming mnemonic; since the umbrella is deleted there is no identity coupling and no L1D-11 parent-rename churn).
4. INPUT: per umbrella, the LIVE L1 slice (the service node + its linked Systems, DataItems, aggregated L0 assets) + the operator KB; the L0 arrives INSIDE the slice (attached by A.1), so no separate live-recon read.
5. auth_context: exposure-only on the leaf; mechanism deferred to #9's `AUTHENTICATED_BY`; suspected mechanism a transient Langfuse `claim`.
6. GUARD: TESTABILITY-ONLY, the LLM judges the axes - a leaf is valid iff it is independently testable and is not a lone endpoint / parameter / header; no fixed axis list; one level deep.
7. LOOP + KB DELIVERY: a per-service loop; the FULL operator KB rides a STABLE system-message prefix (provider prompt-caching) so its tokens are not re-sent per service; each iteration adds the per-service L1 slice.
8. OVERLAP: IN-PASS FR-INVENTORY threading - thread the full live service inventory into the prompt so the model reuses existing slugs and avoids overlap in one pass; no separate critique turn.
9. DISTRIBUTION: the LLM outputs the FULL redistribution map (per subordinate, which of the umbrella's Systems / DataItems / L0 `AGGREGATES` it inherits); the SPLIT op re-points every edge per that map and deletes the root in ONE delta.
10. SLICE FORMAT: the L1 slice is rendered as a natural-language briefing (for reasoning) PLUS a compact JSON identity appendix (so the redistribution map references exact edge/node identities precisely).
11. KB SOURCE: the FULL operator KB, cached (not distilled).
12. REASONING + SKILL: reuse `proposer_reasoning`'s 5-step scaffold (decompose -> expand -> ground -> withhold -> decide) scoped to ONE umbrella, carrying the testability-only guard in the withhold step; load `critical-thinking-logical-reasoning` (as #9/#10 A.2 do) plus the `service-decomposition` skill as the domain guide.

---

## 5. Identity and the unpack (reasoned)

The umbrella is DELETED, so the subordinate does not link to a persisting parent.
The slug `<umbrella>-<leaf>` (e.g. `human-access-ssh`, `human-access-preview-url`) is a naming mnemonic that aids LLM reasoning and preserves the business grouping in a readable form; it is a plain `business_function_slug`, keyed exactly like any Service.
Because no parent node survives, identity is independent by construction (no L1D-11 coupling): renaming or re-deriving one subordinate never churns a sibling, and there is no string-hierarchy the graph must enforce.
This is why the rejected additive `DECOMPOSES`-hierarchy was dropped: it introduced a two-tier Service ontology the L1 model does not have, left the coarse umbrella hoarding the L0 evidence while empty leaves waited on a deferred re-home (the "designed-not-built rots" hazard, §12), and its only real benefit (grouping traceability) survives here through the slug and provenance without a structural tier.

---

## 6. The redistribution (elements-distribution) and the SPLIT op

When an umbrella is unpacked, each of its relationships must move onto the correct subordinate - the elements-distribution task (the operator flagged it complex for DataItems and L0):

- `AGGREGATES` to L0 assets: each L0 element re-homes to the subordinate that owns it (the `/ssh` endpoint -> `human-access-ssh`, the preview URL -> `human-access-preview-url`).
- `EXPOSED_VIA` / `AUTHENTICATED_BY` / `AUTHORIZED_BY` / other System edges: re-home per subordinate (each leaf keeps only the Systems that gate it).
- `PRODUCES` / `CONSUMES` to DataItems: re-home per subordinate.

The SolutionArchitect's OUTPUT carries the redistribution map (decision 9): for each existing edge, identified by `(rel_type, target-identity)` from the JSON identity appendix, the subordinate slug it re-homes to.
The `l1_curator` SPLIT op consumes the map and executes atomically:

1. MATCH the umbrella by `(project_id, umbrella_slug)`.
2. MERGE each subordinate `(project_id, <umbrella>-<leaf>)` with its exposure-only props.
3. For each of the umbrella's in/out edges over the FIXED reconcile allowlist (`_REPOINT_REL_TYPES`), MERGE the same-typed edge from the assigned subordinate to the same target and copy its props, then DELETE the umbrella's edge - explicit per-rel-type re-pointing, since APOC is unavailable (mirrors `build_merge_units_cypher`).
4. DETACH DELETE the umbrella.
5. Stamp provenance + `last_seen`; record a `superseded_from` marker on each subordinate.

Idempotent: a second run cannot MATCH the (deleted) umbrella and is a no-op; FR-INVENTORY reuse keeps a re-bootstrap from re-coining the umbrella.
Fail-open per umbrella: a bad map or a write failure skips that umbrella (its skeleton stays coarse) and never aborts the loop.
An edge the map fails to assign defaults to being dropped with the umbrella (DETACH DELETE), so the map MUST cover every edge; the verifiability suite asserts no L0/DataItem is orphaned by a split.

---

## 7. The agent card (#9 schema)

Role.
A solution architect that shapes the L1 business-function Service population in two phases: `bootstrap` (pre-A.1, project the KB into umbrella Services + linchpin auth Systems) and `decompose` (A.2, unpack each umbrella into discretely-testable subordinate services with disambiguated exposure).

Workflow (`decompose`).
Per umbrella in the LIVE Service set, run the two-call reason -> extract runner (reuse of `proposer_reasoning`): call 1 is the 5-step reasoning scoped to the umbrella (decompose the umbrella into candidate functions -> expand along genuine functional lines -> ground each candidate to a KB span and, where present, an L0 signal from the slice -> withhold against the testability-only guard, dropping any candidate that is not independently testable or is a lone endpoint -> decide the subordinate set, each leaf's exposure, and the redistribution of the umbrella's edges); call 2 extracts the typed decomposition shells + the redistribution map.
Bounded retry per call; fail-open (a failed umbrella degrades to no split for that umbrella).
Sequential, one umbrella at a time.

Goal.
A subordinate set in which every service is discretely testable, grounded in a specific KB span (or slice signal), carries its own correct exposure, and inherits exactly the umbrella edges it owns, with no umbrella atomised into endpoints and no coherent single-auth_context umbrella split.

Tools.
The analyser chat model (role `analyser`); the reusable `proposer_reasoning` fragments; the LIVE L1 slice reader (the umbrella + its linked Systems / DataItems / aggregated L0) and `read_l1_inventory` for the current Service set; the `l1_curator` sole-writer (the SPLIT op) for all writes.
The `decompose` phase loads the `critical-thinking-logical-reasoning` skill (as #9/#10 A.2) plus the `service-decomposition` skill.

Context (LIVE reads, re-derived, never a snapshot).
The current umbrella Service set and their exposures; per umbrella, the LIVE L1 slice rendered as an NL briefing + a JSON identity appendix; the full live service inventory (FR-INVENTORY, threaded in-pass for overlap); the operator KB delivered as a cached system-message prefix.
No Service/System is cached on any message across umbrellas (the live-graph invariant, #16).

Output template (typed proposal shape; a new decomposition batch alongside `L1DeltaBatch`).
Per umbrella: `umbrella_slug` (to delete); `subordinates` = a list of subordinate shells `{business_function_slug: <umbrella>-<leaf>, exposure}`; `redistribution` = for each existing umbrella edge `(rel_type, target-identity)`, the subordinate slug it re-homes to; and per subordinate an optional transient `mechanism_claim` (Langfuse-only).
Maps down to the SPLIT op through the sole-writer.
No new L0, `AGGREGATES` targets, System, or DataItem nodes are minted - decomposition only re-points existing edges and mints Service nodes.

Produced outcome.
Each unpacked umbrella is replaced by a flat set of discretely-testable subordinate services, each with its own exposure and exactly the umbrella edges it owns; the umbrella is gone; the graph is coherent immediately (no deferred re-home).
This is the finer Service set the A.2 TechnicalSystem/DataPlane sweeps then type per leaf.

Observability (Langfuse, per #18).
One run = one session (`session_id=run_id`); the `decompose` pass is one trace `solution-architect-decompose` (the bootstrap phase trace is `solution-architect-bootstrap`); per-umbrella work is a nested span `decompose.umbrella.<umbrella_slug>` with child spans `decompose.reason` and `decompose.extract`.
Scores (flat kebab-case, per #18): `decompose-subordinate-count` (NUMERIC), `decompose-exposure-split-count` (NUMERIC - subordinates whose exposure differs from the umbrella), `decompose-exposure-flip-rescued` (NUMERIC - umbrellas where a public leaf was recovered from an authenticated umbrella, the moodique/human-access case), `decompose-withheld-count` (NUMERIC - candidates the testability guard rejected), `decompose-edges-redistributed` / `decompose-edges-orphaned` (NUMERIC - the latter MUST be 0), and the session-scoped `run-service-granularity`.
The transient per-leaf `mechanism_claim` and the rejected-candidate rationale are Langfuse-only, never persisted.

Verifiability (per #19; unit tier mocks Neo4j).
- UNIT (tdd-loop, pure builders): the SPLIT builder maps a decomposition batch to parameterised Cypher - subordinates MERGEd, every allowlisted edge re-pointed to its assigned subordinate, umbrella DETACH DELETEd, exposure-only props, invalid exposure dropped - no DB. A map that leaves an edge unassigned is rejected by the builder (no silent orphan).
- INTEGRATION (contract predicates over the typed VO, post-split, real DB): after a split the umbrella slug no longer exists; every subordinate is a peer `:L1Service`; every subordinate `exposure` in `{public, authenticated, null}`; the count of L0 `AGGREGATES` + DataItem + System edges is CONSERVED (moved, none dropped, none duplicated); no L0 node is created or deleted (the ACL holds).
- E2E (walkthrough to exact outcomes over the eval outliers): run `decompose` over the three eval umbrella sets and assert - daytona `human-access` unpacks into >= 2 subordinates with DISTINCT exposure including exactly one `public` (`human-access-preview-url`), and the preview L0 asset re-homes to it; daytona `agent-tools` does NOT explode into one leaf per tool (the guard withholds); moodique `product-page-and-reviews` yields a `public` product-page subordinate (exposure-flip rescued); daytona `secrets` (coherent single-auth_context umbrella) is NOT decomposed (anti-vacuity - a coherent umbrella flags nothing); and across every split, `decompose-edges-orphaned == 0`.
Expected outcomes come from this spec, never recomputed as the code computes them; these gate the verifier and never run in the unit red-green loop.

Responsibility / phase-parameterization / output (agent-specific).
- Responsibility: own the shape and granularity of the L1 Service population - mint the umbrellas (`bootstrap`) and unpack them into discretely-testable subordinate services with redistributed edges and disambiguated exposure (`decompose`).
- Phase-parameterization: `phase="bootstrap"` (pre-A.1, KB-only, existing) vs `phase="decompose"` (A.2, LIVE-slice + cached KB + inventory; adds the critical-thinking + service-decomposition skills and the testability-only guard).
- Output: `bootstrap` -> `L1DeltaBatch{services, systems}`; `decompose` -> the decomposition batch `{umbrella_slug, subordinates, redistribution}` consumed by the SPLIT op.

---

## 8. Specification (`/to-spec`)

### Problem Statement

The operator's attack-surface model is only as testable as its Service granularity.
Today the SolutionArchitect's `bootstrap` phase emits coarse umbrella Services (daytona `human-access`, `agent-tools`; magnific `image-services`; moodique `product-page-and-reviews`), which fuse many discretely-testable functions into one node and let one bundled function's exposure flip the whole node closed - hiding public surfaces and erasing the per-function targets a tester needs.

### Solution

Add a second `decompose` phase to the SolutionArchitect that, at the A.2 phase-barrier, loops over each umbrella, reads its live L1 slice plus the cached operator KB, and unpacks it into flat peer subordinate services - each discretely testable, each carrying its own exposure - redistributing the umbrella's System / DataItem / L0 edges onto the correct subordinate and deleting the umbrella, all through one new destructive SPLIT op in the L1 sole-writer.

### User Stories

1. As a tester, I want daytona `human-access` unpacked into `human-access-ssh`, `-vnc`, `-vpn`, `-web-terminal`, and `-preview-url`, so that each access channel is a distinct target.
2. As a tester, I want the `human-access-preview-url` subordinate marked `public`, so that the publicly-reachable preview surface is not hidden behind an authenticated umbrella.
3. As a tester, I want moodique `product-page-and-reviews` unpacked into a `public` product-page and an `authenticated` review-write, so that the public catalogue surface is testable in its own right.
4. As a tester, I want daytona `agent-tools` NOT exploded into one service per tool, so that a coherent single-auth_context bundle is not over-decomposed into untestable fragments.
5. As a tester, I want daytona `secrets` left whole, so that a coherent single-auth_context umbrella flags nothing.
6. As the analyser, I want each subordinate to inherit exactly the umbrella's L0 `AGGREGATES`, DataItem, and System edges it owns, so that no evidence is orphaned or duplicated by a split.
7. As the analyser, I want the umbrella deleted after unpack, so that the graph never carries a coarse node I have judged too coarse.
8. As the analyser, I want the specific auth mechanism (SSH-token vs preview-token) left to the TechnicalSystem #9 sweep, so that a Service never carries an auth method (mechanism-as-System).
9. As the analyser, I want to reuse an existing service slug rather than coin a synonym during decomposition, so that a subordinate does not duplicate a peer service.
10. As the operator, I want the operator KB sent once as a cached prefix across the per-service loop, so that decomposition does not re-bill the KB's tokens per umbrella.
11. As the analyser, I want the L1 slice presented as an NL briefing plus a JSON identity appendix, so that my redistribution map references exact edge identities.
12. As the operator, I want the SolutionArchitect to be the Bootstrapper generalised (phase in {bootstrap, decompose}), so that the Service-population responsibility stays in one home and the roster stays six.
13. As a maintainer, I want the SPLIT op to live only in `l1_curator` over `:L1*` labels, so that decomposition can never mint or delete an L0 node (the sole-writer / ACL boundary).
14. As a maintainer, I want a split to be idempotent and fail-open per umbrella, so that a re-run or a single bad umbrella never corrupts the batch.
15. As a verifier, I want an assertion that a split conserves the L0/DataItem/System edge count (moved, none dropped), so that the elements-distribution is provably lossless.
16. As the operator, I want the run traced with per-umbrella spans and granularity scores, so that I can see how much decomposition each run performed.

### Implementation Decisions

- Modules: generalise the Bootstrapper module into the SolutionArchitect (`phase` parameter; the existing path becomes `phase="bootstrap"`); add the `decompose` reason/extract collaborators reusing `proposer_reasoning`; add the SPLIT op to the L1 sole-writer (`l1_curator`), extending its reconcile family (`merge` / `delete` / `relabel` -> `+ split`).
- The SPLIT op is the one-to-many counterpart of `build_merge_units_cypher`: MATCH umbrella, MERGE subordinates, re-point each in/out edge over the fixed `_REPOINT_REL_TYPES` allowlist to the map-assigned subordinate (explicit per-rel-type, APOC-free), DETACH DELETE umbrella, stamp provenance; keyed on `(project_id, slug)`; idempotent; fail-open per op (mirrors `reconcile`).
- New typed output: a decomposition batch `{umbrella_slug, subordinates:[{business_function_slug, exposure}], redistribution:{edge-identity -> subordinate_slug}, mechanism_claim?}`, a value object alongside `L1DeltaBatch`, mapped down by the sole-writer; exposure-only prop baseline reused from the bootstrap/Assigner allowlist.
- Input contract: per umbrella, a LIVE L1 slice reader returns the umbrella + its linked Systems / DataItems / aggregated L0, rendered as an NL briefing + a compact JSON identity appendix; the L0 comes from the slice (A.1 `AGGREGATES`), not a fresh recon read.
- KB delivery: the full operator KB is a stable system-message prefix (prompt-caching); per umbrella the human turn adds the slice + the FR-INVENTORY inventory block; the loop is per-service and sequential.
- Guard: testability-only, enforced in the withhold step of the 5-step reasoning - a candidate survives iff it is independently testable and is not a lone endpoint / parameter / header; no fixed axis list; one level deep.
- auth_context: subordinates carry exposure only; the mechanism is a transient `mechanism_claim` (Langfuse), deferred to the #9 `AUTHENTICATED_BY` System edge.
- Ordering: `decompose` is the FIRST A.2 sub-step, before the #9/#10 sweeps, so they type the finer subordinate set.

### Testing Decisions

- A good test asserts external behaviour over the typed VO and the post-split graph, not the prompt wording: the subordinate set, the exposures, the conserved edge counts, the deleted umbrella - never an internal call shape.
- Unit tier (mocks Neo4j, tdd loop): the pure SPLIT builder and the shells-to-batch mapping - subordinates MERGEd, edges re-pointed per map, umbrella deleted, exposure-only props, an unassigned edge rejected. Prior art: the pure `build_merge_units_cypher` / `build_relabel_unit_cypher` builder tests and the bootstrap `shells_to_batch` contract tests.
- Integration tier (real Neo4j, `/to-assertions` contract predicates): edge-count conservation, umbrella-gone, subordinate-peer, no-L0-touched. Prior art: the L1 sole-writer reconcile integration tests.
- E2E tier (real LLM + real Neo4j, no mocks, over the three eval umbrellas): the walkthrough assertions in §7 Verifiability. Prior art: the no-mock Bootstrapper e2e (`test_bootstrap_reasoned_walkthrough.py`) and the multi-target eval driver.

### Out of Scope

- The specific auth-mechanism typing of a subordinate (SSH-token vs preview-token) - that is TechnicalSystem #9's `AUTHENTICATED_BY` sweep, which runs after decomposition.
- Recursive / multi-level decomposition (one level per umbrella in v1; deeper subdivision is Phase-B depth).
- Any fresh recon read - decomposition consumes only the L1 slice (with its already-attached L0) and the KB.
- The `service-linchpin` prompt wiring (retained-not-wired in `bootstrap.py`) - unaffected here.
- Cross-umbrella Service merges - overlap is handled in-pass by FR-INVENTORY reuse; residual dedup remains #11's.

### Further Notes

- FLAG (domain.md "flag design-spec conflicts"): the SPLIT op REOPENS the wayfinder's deferred service-split retraction. The operator ratified reopening it; this spec builds it.
- The prompt does NOT push the account-surface umbrellas (that caused the breadth regression); decomposition operates on whatever umbrellas `bootstrap` produced.
- Designed-not-built seams (§12 named): the `l1_curator` SPLIT op; the decomposition output VO; the transient `mechanism_claim`.

---

## 9. Designed-not-built seams (named, never faked)

- The SPLIT op in `l1_curator` (and its `_REPOINT_REL_TYPES` re-use) is designed-not-built until it lands; the reconcile family grows by one.
- The decomposition output VO + the LIVE L1-slice reader (NL briefing + JSON appendix) are designed-not-built.
- The per-leaf `mechanism_claim` is transient (Langfuse-only); the mechanism System typing is #9's, reached by `AUTHENTICATED_BY` / `AUTHORIZED_BY`.
- The `service-decomposition` skill (`.claude/skills/service-decomposition/SKILL.md`) is the domain guide the `decompose` phase loads.

---

## 10. Ratification record

All grilling questions closed 2026-07-26 (A-Q1..A-Q5, G1..G3, plus the walkthrough grey points: slice format, KB source, reasoning+skill).
Decisions are the ledger in §4.
The implementation ticket #27 was opened from §8 (`/to-tickets`), then DEFERRED post-v1 and extracted from the #1 stream (2026-07-27): it is now labelled `enhancement` only (was `workflow` + `ready-for-agent`), is no longer a sub-issue of #1, and stays OPEN for later pickup.
It references #7 (the agent it generalises) and #9 (the sweep it feeds).

---

## 11. Verification predicate catalogue (`/to-assertions`, documented - not mechanised)

Written per `/to-assertions` as the lift-ready catalogue a future builder mechanises AT implementation.
It is DOCUMENTED here, not turned into test files, because the capability is deferred - red tests sitting in the tree for an unbuilt path are the anti-pattern `/to-assertions` forbids.
Every expected value is taken from this spec, never recomputed the way the code would compute it.
Contract predicates (C-n) attach at the SPLIT-op / decomposition-batch seam (integration tier, real Neo4j); walkthrough predicates (E-n) trace a full `decompose` to exact outcomes (e2e tier, real LLM + real Neo4j over the three eval umbrellas).

### Contract predicates (integration tier)

- C1 - subordinates are peers: after a SPLIT of umbrella U into `{s1, s2}`, each `si` exists as a peer `:L1Service` keyed `(project_id, <U>-<leaf>)`, with NO `DECOMPOSES`/parent edge and no second Service-tier label.
- C2 - umbrella deleted: after the split, `MATCH (:L1Service {project_id, business_function_slug: U})` returns nothing.
- C3 - exposure-only leaf: each subordinate's persisted props equal exactly `{exposure}` with `exposure in {public, authenticated}`; an invalid or absent exposure yields empty props (the allowlist defense, mirroring bootstrap `shells_to_batch`).
- C4 - edge-count conservation: the count of (`AGGREGATES` + `PRODUCES` + `CONSUMES` + System-edge) incident to U BEFORE equals the count incident to the subordinate set AFTER - none dropped, none duplicated.
- C5 - redistribution fidelity: each umbrella edge, identified by `(rel_type, target-identity)`, lands on exactly the subordinate the map assigned it, exactly once.
- C6 - ACL holds: the split creates and deletes NO L0 node (L0 targets are `MATCH`ed only); the L0 node census is unchanged across the op.
- C7 - unassigned edge rejected: a decomposition batch whose redistribution map omits any incident umbrella edge is REJECTED by the pure builder (`ValueError`), never silently orphaning it on the DETACH DELETE.
- C8 - idempotent re-run: running the same split twice yields an identical graph (the second run MATCHes no umbrella and is a no-op); the subordinate count stays N, never 2N.
- C9 - fail-open per umbrella: in a batch, one bad op (bad slug, unknown rel type, `merge_fn` exception) is skipped+logged and the remaining umbrellas still split (mirrors `reconcile`).
- C10 - in-pass overlap reuse: a subordinate slug that collides with an existing peer Service MERGEs onto it (FR-INVENTORY reuse), never mints a duplicate.
- C11 - mechanism_claim not persisted: the transient `mechanism_claim` never appears as a Service prop (Langfuse-only).
- C12 - provenance stamped: every minted subordinate and every re-pointed edge carries `prov_job`; each subordinate carries a `superseded_from` marker naming its umbrella.

### Walkthrough predicates (e2e tier, exact outcomes over the eval outliers)

- E1 - human-access unpack + public rescue: `decompose` over daytona `human-access` yields >= 2 subordinates with DISTINCT exposure including EXACTLY ONE `public` (`human-access-preview-url`); the preview L0 asset re-homes to that public leaf; `human-access` is deleted; `decompose-exposure-flip-rescued >= 1`.
- E2 - agent-tools not atomised: `decompose` over daytona `agent-tools` produces NO per-tool leaf (the eight Toolbox tools do not become eight services) - the testability guard withholds; the result is the umbrella kept whole or split only on a genuine testability axis, never a 1:1 tool explosion.
- E3 - moodique exposure-flip rescued: `decompose` over `product-page-and-reviews` yields a `public` product-page subordinate and an `authenticated` review subordinate; the public catalogue surface is no longer hidden behind an authenticated umbrella.
- E4 - coherent umbrella not split: `decompose` over daytona `secrets` (a coherent single-auth_context umbrella) does NOT decompose it - a coherent umbrella flags nothing (the anti-vacuity contract; the guard must not split on size alone).
- E5 - no orphans across the run: over a whole run, `decompose-edges-orphaned == 0` - every L0 `AGGREGATES`, DataItem flow, and System edge the umbrellas owned is re-homed onto a subordinate, none stranded and none left on a deleted node.
- E6 - granularity actually gained: for a multi-function KB the post-`decompose` Service count exceeds the pre-`decompose` umbrella count (the run refined the surface); for a coherent-only KB the count is unchanged (no vacuous splitting).

Outlier coverage: E1/E3 are the hidden-public-surface outliers (the core bug this capability fixes); E2/E4 are the over-decomposition outliers (the guard must NOT fire); E5 is the elements-distribution correctness outlier (the hardest part, per the operator); C7/C8/C9 are the empty/replay/degradation delivery-semantics outliers.

---

## 12. Implementation pickup sequence (straight-to-build checklist)

An ordered plan a builder can execute directly when this is un-deferred; each step is a bounded, independently-verifiable slice.

1. Prefactor - rename the Bootstrapper into the SolutionArchitect with a `phase` parameter; the existing behaviour becomes `phase="bootstrap"` (pure rename + parameter, no behaviour change; existing bootstrap tests stay green).
2. SPLIT op - add `build_split_service_cypher` (pure) + a `split` entry to `l1_curator.reconcile` (impure): MATCH umbrella, MERGE the subordinates, re-point each in/out edge over the FIXED `_REPOINT_REL_TYPES` allowlist to the map-assigned subordinate (explicit per-rel-type, APOC-free, mirroring `build_merge_units_cypher`), DETACH DELETE the umbrella, stamp provenance + `superseded_from`; idempotent; the `_SAFE_IDENT` + allowlist injection guards; reject a map that leaves an incident edge unassigned (C7). Mechanise the pure-builder unit tests.
3. Decomposition VO - add the typed decomposition batch `{umbrella_slug, subordinates:[{business_function_slug, exposure}], redistribution:{(rel_type, target-identity) -> subordinate_slug}, mechanism_claim?}` alongside `L1DeltaBatch`, plus its `shells_to_batch`-style mapper down to the SPLIT op (exposure-only allowlist reused).
4. LIVE L1-slice reader - a reader returning the umbrella + its linked Systems / DataItems / aggregated L0, rendered as an NL briefing + a compact JSON identity appendix (the identities the redistribution map references).
5. Decompose reason/extract runner - the two-call collaborators reusing `proposer_reasoning` (the 5-step scaffold scoped to one umbrella, testability guard in the withhold step), with the FULL operator KB as a cached system-message prefix, the FR-INVENTORY inventory block threaded in-pass, and the `critical-thinking-logical-reasoning` + `service-decomposition` skills loaded; per-service loop, sequential, fail-open per umbrella.
6. Wiring - schedule `decompose` as the FIRST A.2 sub-step in `run_analyser_supervised` (at the recon phase-barrier, before the #9/#10 sweeps), iterating the live umbrella set.
7. Verification - mechanise §11: the C-n contract predicates in the integration tier, the E-n walkthrough predicates in the e2e tier over the three eval umbrellas (no mocks, real LLM + real Neo4j), gating the verifier.
8. Model-current - add the SolutionArchitect / umbrella / subordinate-service / SPLIT-op / per-leaf-auth_context terms to `src/polymerhus/analysis/CONTEXT.md`, and the `decompose` Langfuse trace/span/score rollup per #18.
