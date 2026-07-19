osu# Post-Recon Curation and L1 Remediation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Follow `loop-constraints.md` verbatim and the maker/checker discipline (a SEPARATE verifier runs each area's assertions; the implementer never self-approves).

> **STATUS (2026-07-19): every BUILD area is verifier-APPROVED and committed. `FR-CURE2E` (§7) is the ONLY open area.**
> Approved and landed: FR-INVENTORY, FR-MERGE, FR-JOURNEY, FR-TYPESEP (a+b), FR-CURATE, FR-MODELFIX.
> Green baseline at handoff: 827 unit tests pass, 46 of them this plan's tests (including 4 live-Neo4j integration, 0 skips), plus 4 frontend colour tests.
> One PRE-EXISTING failure is unrelated to this plan and must not be read as curation fallout: `tests/recon/test_pipeline_e2e.py::test_pipeline_e2e_httpx_to_arjun_prop_dependent_target` reproduces identically at `ce5e351` (the commit before this plan's work) with `.env` present. It is separately a hermeticity defect - a `tests/recon/` unit-tier test reaches live Neo4j via `read_steering_signals`, fails open, and leaves arjun unexecuted. Tracked in `STATE.md`.

**Goal:** build the post-recon curation phase (a driver-invoked module) that consolidates the accumulated L1 graph - deduplicating, pruning, and transforming nodes destructively through the sole-writer - plus at-write duplicate prevention, a light journey membership model, and Service/System typing separation, then re-run the exhaustive pipeline+curation e2e.

**Architecture:** the analyser stays a pure `f(L0-slice+observations) -> L1-deltas` written by idempotent MERGE (`l1_curator`, L1D-22). This plan adds a second phase after recon: a curation LLM pass proposes typed *reconciliation* operations (merge / prune / transform / journey-grouping) over the whole accumulated L1+L0 graph, and the `l1_curator` sole-writer executes them destructively (re-pointing edges, deleting/relabelling nodes) with provenance. Duplicate *prevention* is added upstream by injecting the current L1 identity inventory into every analyser prompt. Curation is orchestrated by a new driver-invoked module (`agent/recon/analysis/curation.py`), not wired into the request pipeline (operator decision).

**Tech Stack:** Python 3.13, LangGraph, pydantic, Neo4j 5.26-community (single physical DB, disjoint `:L1*` namespace), pytest (`.venv/bin/python -m pytest`), the analyser LLM role.

## Global Constraints

- The MVP fence is DOWN as of 2026-07-19 (operator decision). Destructive reconciliation (merge / delete / relabel) is now IN SCOPE, permitted in `l1_curator` ONLY, and must be idempotent, provenance-stamped, and re-point (never orphan) the edges of any node it removes or relabels. (`loop-constraints.md`)
- All `:L1*` writes go ONLY through `agent/recon/analysis/l1_curator.py` (sole-writer). L0 writes stay in `agent/recon/curator.py`; never edit the L0 sole-writer or `db/neo4j/schema.py` except through the sanctioned L1 seam.
- Provenance on every node/edge/ref write (L1D-25). `discriminator` defaults to the non-null string `"__singleton__"` (L1D-9/L1R-2). `identity ⊥ membership` (L1D-11).
- Fail-open / graceful degrade: an LLM / read / write error degrades to an empty-or-error result; it never crashes the caller (mirror the analyser pod).
- Curation is a SEPARATE driver-invoked module; do NOT wire it into `run_pipeline` (operator decision - protects the 3.8GiB host from a heavier terminal phase).
- Journey is a LIGHT MEMBERSHIP prop (a `journeys: list[str]` on each Service), not a node and not ordered (operator decision). Order is a documented two-way extension, not built now.
- Loop discipline: assertions first, one area = one bounded goal in its own worktree, maker/checker, minimal-fix, max 3 attempts then escalate, never weaken a test to go green. Do not start a second area until the first is verifier-APPROVED.
- Never use the em dash; use a plain dash. Never auto-add a co-author to commits. Commit only when the operator asks.

---

## 0. Dependency graph (for independent dispatch)

```
Parallel now (no cross-deps):
  FR-INVENTORY   (at-write duplicate prevention)
  FR-MERGE       (sole-writer destructive reconciliation ops)
  FR-JOURNEY     (light journey membership prop + grouping instruction)
  FR-TYPESEP-a   (analyser prompt hardening: systems are edges, not Service props)

Then (integrator, depends on the above):
  FR-CURATE  ->  needs FR-MERGE (executor), FR-INVENTORY (reduces load),
                 FR-JOURNEY (grouping), FR-TYPESEP-b (re-homing transform),
                 and the existing anatomy modules (webpage-profile / authz).

Finally:
  FR-CURE2E  ->  full pipeline + curation e2e re-run + independent verifier.
```

Each FR area is a bounded goal with its own assertion ledger (below) and an independent verifier gate.
FR-INVENTORY, FR-MERGE, FR-JOURNEY, and FR-TYPESEP-a can be dispatched to four subagents concurrently.
FR-CURATE is the integrator and must wait for FR-MERGE + FR-JOURNEY + FR-TYPESEP.

---

## 1. The `journey` attribute - role, mechanism, and adversarial leverage

The operator chose a LIGHT MEMBERSHIP shape: each `L1Service` carries `journeys: list[str]` naming the business journeys it participates in (e.g. `"checkout-flow"`, `"signup-flow"`, `"password-reset-flow"`).
"Services in the same journey" is then a single property-match query (services sharing a `journeys` entry) - no new node, no new edge, no schema migration (props are an open map already).
Journey membership is assigned by the curation pass (§4), not the recon-time analyser, because it is a whole-solution judgment best made once the service set has stabilised.

### 1.1 How journey membership drives adversarial reasoning (brainstorm)

The membership grouping is a *prior* that concentrates the analyser's trust-boundary reflection where the impactful faults cluster:

1. **Cross-service trust within a journey.** Same-journey services pass state between steps (basket -> checkout -> payment -> order), so the Tier-1 `PRODUCES`/`CONSUMES` data-flow trust (L1D-14/15) concentrates on same-journey pairs. The grouping tells phase-B to reflect on those pairs first, not all-pairs.
2. **Unintended unfolding = step skipping / reordering / replay.** Even without explicit order, membership lets the analyser pose falsifiable business-logic hypotheses: can a later step be invoked without completing an earlier one (reach order-confirmation without payment)? can a step be replayed (re-apply a coupon, double-submit)? Each is a `define-hypothesis` claim -> an interface-B backward-recon probe.
3. **Trust-boundary discontinuities across a journey.** A journey that crosses auth realms/roles mid-flow (anonymous cart -> authenticated checkout) is a high-value boundary; grouping surfaces where same-journey services differ in `auth_methods`/realm - a structural signal for context/privilege confusion.
4. **State/secret carriage across steps.** A DataItem produced at step 1 and consumed at step 3 (coupon token, cart signature, price snapshot) is a journey-scoped trust assumption ("the price computed at add-to-cart is still valid at checkout") - the classic business-logic fault locus. Membership marks which DataItems are journey-carried vs step-local.
5. **Journey as a concretisation scope.** For a whole-journey abstract test (coupon reuse across checkout), the membership set bounds which services'/DataItems' L0 sites to concretise against - a coarser sibling of the DataItem selector for the L1R-8 noise hazard.

### 1.2 Caveat (recorded honestly)

Light membership cannot express ORDER, so "unintended unfolding" is reasoned as hypotheses over an unordered set, not a precise state-machine reachability query.
If order-based reasoning proves necessary, promote to an ordered structure (a `Journey` node with `STEP_OF`/`PRECEDES` edges) - a two-way extension, since the membership prop is a subset of that model.
This limitation is registered as a follow-up (AMV-11) rather than pre-built.

---

## 2. FR-INVENTORY - at-write duplicate prevention

*Goal:* stop the analyser coining synonym identities (sign-in / signin / login) across passes by injecting an explicit, un-truncated inventory of the CURRENT L1 identities into every analyser prompt, with a reuse instruction.
*Root cause it fixes:* today the reuse hint ("REUSE the exact business_function_slug ... already present in the slice", `pod.py:206`) is toothless - existing L1 nodes are buried in a raw slice dump truncated at 400 and dropped entirely by the data-modelling pass (`_compact_l0_for_data`).
*Non-goals:* reconciliation of duplicates already present (that is FR-CURATE); embedding-similarity dedup (LLM-judged reuse is the mechanism).

**Files:**
- Create: `agent/recon/analysis/l1_inventory.py` - `read_l1_inventory(project_id, *, read_fn=None) -> dict` returning `{"services": [slug,...], "systems": ["kind:disc",...], "data_items": [item_key,...]}` (sorted, deduped).
- Modify: `agent/recon/analysis/pod.py` - `_assignment_prompt` and `_data_modelling_prompt` gain an `inventory: dict` argument and render an "EXISTING L1 IDENTITIES - reuse these exact keys, do not coin a synonym" block at the TOP; `default_analyse_fn` / `_two_pass_analyse` read the inventory once and thread it in; `bootstrap.default_elicit_fn` likewise for services already seeded.
- Test: `tests/recon/test_l1_inventory.py`, and extend `tests/recon/test_analyser_prompts.py`.

**Interfaces:**
- Produces: `read_l1_inventory(project_id) -> {"services": list[str], "systems": list[str], "data_items": list[str]}`.
- Consumes: `agent.app.clients.neo4j_client.read` (lazy, like `sweep.py:_resolve_read_fn`).

- [x] **Step 1: failing test for the inventory reader.** `test_l1_inventory.py::test_reads_service_slugs_systems_dataitems` injects a fake `read_fn` returning rows for two services, one non-singleton system, one data item; assert the returned dict shape + that a `__singleton__` system renders as just its kind while a discriminated one renders `kind:disc`.
- [x] **Step 2: run it, watch it fail** (`ModuleNotFoundError`/`AttributeError`). Run: `.venv/bin/python -m pytest tests/recon/test_l1_inventory.py -q`.
- [x] **Step 3: implement `read_l1_inventory`** with three read queries (`:L1Service` slugs; `:L1System` kind+discriminator; `:L1DataItem` item_key), all `WHERE n.project_id = $project_id`, sorted. Fail-open: on a read error return empty lists.
- [x] **Step 4: green.** Rerun Step 2's command.
- [x] **Step 5: failing test for prompt injection.** `test_analyser_prompts.py::test_assignment_prompt_pins_existing_identities` calls `_assignment_prompt(slice, obs, inventory={"services":["sign-in"],...})` and asserts the slug appears under an "EXISTING L1 IDENTITIES" heading and the reuse instruction is present; same for `_data_modelling_prompt`.
- [x] **Step 6: run, watch fail** (arg does not exist yet).
- [x] **Step 7: implement** the `inventory` arg + rendered block in both prompts; thread it through `_two_pass_analyse`/`default_analyse_fn` (read once via `read_l1_inventory`, pass to both passes) and `bootstrap.default_elicit_fn`. Keep the block OUTSIDE the `_MAX_L0_NODES` truncation so it is never dropped.
- [x] **Step 8: green** + run the full analyser prompt/pod suite (`-k "analyser or pod or inventory"`).

```yaml
# FR-INVENTORY assertion ledger
- id: AST-INV-01
  kind: functional
  statement: "read_l1_inventory returns the project's current service slugs, system kind:disc keys, and data-item keys (sorted, deduped), fail-open to empty on read error."
  test: tests/recon/test_l1_inventory.py::test_reads_service_slugs_systems_dataitems ; ::test_read_error_is_fail_open
  status: green (verifier-APPROVED 2026-07-19)
- id: AST-INV-02
  kind: functional
  statement: "Both analyser prompts render the existing-identities block at the top with a reuse instruction, un-truncated, and the bootstrap elicitation receives the current service slugs."
  test: tests/recon/test_analyser_prompts.py::test_assignment_prompt_pins_existing_identities ; ::test_data_modelling_prompt_pins_existing_identities
  status: green (verifier-APPROVED 2026-07-19)
```

---

## 3. FR-MERGE - sole-writer destructive reconciliation

*Goal:* give `l1_curator` the three destructive operations the curation pass needs - MERGE-two-nodes (dedup), DELETE-node (prune), RELABEL/RE-KIND-node (transform) - each idempotent, provenance-stamped, and edge-preserving (re-point, never orphan).
*Non-goals:* deciding WHICH nodes to merge/prune/transform (that judgment is FR-CURATE); reified `Assignment` competing-provenance nodes (a later refinement, tracked separately).

**Files:**
- Modify: `agent/recon/analysis/l1_curator.py` - add pure builders + impure executors:
  - `build_merge_units_cypher(label, canonical_identity, duplicate_identity, provenance)` - re-point every in/out relationship of the duplicate onto the canonical node, copy non-identity props the canonical lacks, stamp `superseded` provenance, then DELETE the duplicate. One Cypher statement using `apoc`-free vanilla `MATCH ... CALL { }`/`MERGE`+`DELETE` (Neo4j 5 supports `MATCH (dup)-[r]->(x) MERGE (canon)-[r2:...]->(x)` via dynamic type only through iteration, so re-point per relationship-type with a fixed allowlist of L1 rel types + AGGREGATES/SURFACES_AT/etc.).
  - `build_delete_unit_cypher(label, identity, provenance)` - DETACH DELETE the L1 node (never an L0 node; guard `label in L1_ALLOWED_LABELS | {"L1DataItem"}`), recording an audit provenance row is out of scope (deletion is terminal).
  - `build_relabel_unit_cypher(from_label, to_label, identity, new_identity, provenance)` - remove the old subtype label, add the new one, rewrite identity keys (e.g. a Service that is really a System becomes `:L1TestableUnit:L1System {system_kind, discriminator}`), re-point edges whose semantics change (e.g. `AGGREGATES` from a mis-typed Service becomes `EVIDENCED_BY` from the System) per an explicit mapping table.
  - Impure `reconcile(project_id, *, merges, deletes, relabels, merge_fn=None) -> dict` fail-open per op (mirror `enrich`).
- Test: `tests/test_l1_curator_reconcile_builders.py` (pure builders), `tests/integration/test_l1_curator_reconcile.py` (real Neo4j).

**Interfaces:**
- Produces: `reconcile(project_id, *, merges: list[MergeOp], deletes: list[DeleteOp], relabels: list[RelabelOp]) -> {"merged": int, "deleted": int, "relabelled": int}`.
- New delta types in `l1_types.py`: `MergeOp{label, canonical, duplicate, provenance}`, `DeleteOp{label, identity, provenance}`, `RelabelOp{from_label, to_label, identity, new_identity, provenance}`.

- [x] **Step 1: failing pure-builder test** `test_merge_builder_repoints_and_deletes` - assert the Cypher MATCHes both nodes by identity, re-points each allowlisted rel type, and DETACH DELETEs the duplicate; identity keys are parameterised (injection guard via `_SAFE_IDENT`).
- [x] **Step 2: run, watch fail.** `.venv/bin/python -m pytest tests/test_l1_curator_reconcile_builders.py -q`.
- [x] **Step 3: implement `build_merge_units_cypher`** (re-point over the fixed rel allowlist + `AGGREGATES`/`SURFACES_AT`/`PRODUCES`/`CONSUMES`/`DATA_RELATIONSHIP`/`OF_KIND`/`SYSTEM_EDGE_RELS`; canonical gets `superseded_from` + provenance; duplicate DETACH DELETEd).
- [x] **Step 4: green.**
- [x] **Steps 5-8: repeat TDD** for `build_delete_unit_cypher` and `build_relabel_unit_cypher` (with the AGGREGATES->EVIDENCED_BY re-point mapping for Service->System).
- [x] **Step 9: integration test** `test_l1_curator_reconcile.py` on real Neo4j: create two duplicate services with distinct aggregates, `reconcile(merges=[...])`, assert one node remains, all aggregates now hang off the canonical, running `reconcile` again is a no-op (idempotent).
- [x] **Step 10: green** against the live container Neo4j.

```yaml
# FR-MERGE assertion ledger
- id: AST-MERGE-01
  kind: functional
  statement: "Merging duplicate B into canonical A re-points ALL of B's L1 edges onto A, copies missing props, DETACH DELETEs B, and is idempotent (second run is a no-op)."
  test: tests/integration/test_l1_curator_reconcile.py::test_merge_repoints_all_edges ; ::test_merge_idempotent
  status: green (verifier-APPROVED 2026-07-19)
- id: AST-MERGE-02
  kind: functional
  statement: "Deleting an L1 node DETACH-deletes it and never touches an L0 node; delete of a non-existent node is a safe no-op."
  test: tests/integration/test_l1_curator_reconcile.py::test_delete_l1_only
  status: green (verifier-APPROVED 2026-07-19)
- id: AST-MERGE-03
  kind: functional
  statement: "Relabelling a mis-typed Service to a System swaps the subtype label, re-keys identity to (system_kind, discriminator), and re-points AGGREGATES into EVIDENCED_BY; provenance stamped."
  test: tests/integration/test_l1_curator_reconcile.py::test_relabel_service_to_system
  status: green (verifier-APPROVED 2026-07-19)
- id: AST-MERGE-04
  kind: nonfunctional
  statement: "reconcile is fail-open per op (one bad op is skipped+logged, the batch continues) and only ever emits :L1* writes (never an L0 MERGE/DELETE)."
  test: tests/test_l1_curator_reconcile_builders.py::test_reconcile_fail_open ; ::test_no_l0_writes
  status: green (verifier-APPROVED 2026-07-19)
```

---

## 4. FR-CURATE - the curation pass + driver-invoked orchestrator

*Goal:* a curation LLM pass reads the whole accumulated L1 (index-cards + inventory) plus the L0 stale/noise signals, proposes typed reconciliation (merge duplicates, prune/transform off-role nodes, assign journeys), executes them via FR-MERGE, runs the anatomy skills (webpage-profile / authz) and the stale+missing-systems sweep, and returns a report. Orchestrated by a new driver-invoked module.
*Non-goals:* wiring into `run_pipeline`; the signature engine (NM-8); risk scoring.

**Files:**
- Create: `agent/recon/analysis/curation.py` - `run_curation(project_id, run_id, *, read_fn=None, propose_fn=None) -> CurationReport`. Steps: (1) read L1 index-cards + inventory + stale pool; (2) `propose_fn` = a curation LLM pass emitting a `CurationBatch{merges, deletes, relabels, journeys, reassignments}` (structured output, `function_calling`, retry-on-empty via the existing `_invoke_with_retry`); (3) execute merges/deletes/relabels via `l1_curator.reconcile`; (4) write journey memberships + any reassignments via `l1_curator`; (5) invoke the anatomy skills (`anatomy.webpage_profile` -> `commit_anatomy`, `anatomy.classify_authz`) so rendering/nav land on Systems; (6) `sweep.stale_pool` + `sweep.missing_system_kinds`; (7) return `CurationReport`.
- Create: `skills/analysis/curation/SKILL.md` - the curation reasoning prompt (dedup by `business_function_slug` / `system_kind:discriminator`, prune/transform off-role nodes, group journeys, Service/System separation), composed with the analyser reasoning skill.
- Create: `agent/recon/analysis/curation_types.py` - `CurationBatch` / `CurationReport` + `curation_proposals_to_ops`.
- Add: a curation prop-writer for `journeys` on services (reuse `l1_curate` with a `journeys` prop, since props are open and `identity ⊥ membership`).
- Test: `tests/recon/test_curation.py` (injected fakes, no live LLM/DB).

**Interfaces:**
- Produces: `run_curation(project_id, run_id) -> CurationReport{merged, deleted, relabelled, journeys_written, stale_count, missing_kinds, error}`.
- Consumes: `l1_inventory.read_l1_inventory`, `index_card` projection, `l1_curator.reconcile` + `l1_curate`, `anatomy.*`, `sweep.*`.

- [x] **Step 1: failing test** `test_curation_executes_proposed_ops` - inject a `propose_fn` returning a `CurationBatch` with one merge + one journey; a fake `reconcile`/`curate`; assert `run_curation` calls reconcile with the merge and writes the journey, and the report counts match.
- [x] **Step 2: run, watch fail.**
- [x] **Step 3: implement** `curation.py` orchestration + `curation_types.py` + `curation_proposals_to_ops`, fail-open per stage (a failed stage degrades, later stages still run).
- [x] **Step 4: green.**
- [x] **Step 5: failing test** `test_curation_groups_same_journey_services` - proposed journeys `{"checkout-flow": ["cart","checkout","payment"]}` -> each service gets `journeys` containing `"checkout-flow"`; a later same-journey query returns all three.
- [x] **Step 6-7: implement + green** the journey writer.
- [x] **Step 8: failing test** `test_curation_invokes_anatomy_and_sweep` - assert the webpage-profile/authz skills and both sweeps are invoked and their results are in the report; anatomy failure is fail-open.
- [x] **Step 9: green** + author `skills/analysis/curation/SKILL.md`, load it via `skill_for("analysis/curation", fallback=...)`.

```yaml
# FR-CURATE assertion ledger
- id: AST-CUR-01
  statement: "run_curation executes proposed merges/deletes/relabels via l1_curator.reconcile and writes journey memberships; the report counts them; each stage is fail-open."
  test: tests/recon/test_curation.py::test_curation_executes_proposed_ops ; ::test_stage_fail_open
  status: green (verifier-APPROVED 2026-07-19)
- id: AST-CUR-02
  statement: "Same-journey services share a journeys entry after curation (light membership); querying by journey returns the group."
  test: tests/recon/test_curation.py::test_curation_groups_same_journey_services
  status: green (verifier-APPROVED 2026-07-19)
- id: AST-CUR-03
  statement: "Curation invokes the anatomy skills (rendering/nav land on Systems, not Service props) and the stale + missing-systems sweeps; results are in the report."
  test: tests/recon/test_curation.py::test_curation_invokes_anatomy_and_sweep
  status: green (verifier-APPROVED 2026-07-19)
```

---

## 5. FR-TYPESEP - Service/System typing separation

*Goal:* stop navigation/rendering/perimeter facts landing as `L1Service` props; they belong on a `System` reached by a typed edge (`RENDERED_BY`, `EXPOSED_VIA`, `FRONTED_BY`, ...), so the Stage-3 DFS over a service's system edges works.
*Two halves:* (a) prompt hardening (independent, dispatch now); (b) structural re-homing in curation (depends on FR-MERGE's relabel + a prop-strip transform).

**Files:**
- Modify: `skills/analysis/analyser/SKILL.md` + `agent/recon/analysis/pod.py` `_assignment_prompt` - add an explicit "SYSTEMS ARE EDGES, NOT SERVICE PROPS" rule enumerating the spine slots that must be a `system_edges` entry (navigation_model/rendering_model -> `RENDERED_BY` a RenderingSystem; api_paradigm -> `EXPOSED_VIA`; perimeter -> `FRONTED_BY`/`PROTECTED_BY`/`ROUTED_BY`), and the DFS rationale.
- Modify: `agent/recon/analysis/curation.py` - a structural backstop that detects spine-slot props wrongly set on a Service and re-homes them to the correct System (creates/links the System via `l1_curator.build_system_edge_cypher`, strips the prop from the Service). Reuses the `anatomy` navigation/rendering enforcement.
- Test: extend `tests/recon/test_analyser_prompts.py` (prompt rule present) and `tests/recon/test_curation.py` (re-homing transform).

- [x] **Step 1 (half a): failing prompt test** `test_assignment_prompt_forbids_system_facts_on_service` - assert the rule text names rendering_model/navigation_model and instructs a `RENDERED_BY` System edge, not a Service prop.
- [x] **Step 2-4:** implement the rule in the prompt + SKILL.md; green. (This half is independently dispatchable.)
- [x] **Step 5 (half b): failing test** `test_curation_rehomes_rendering_prop_to_system` - a Service carrying `rendering_model="CSR"` in props -> after curation the prop is gone and the Service has a `RENDERED_BY` edge to a `RenderingSystem_CSR_JSMap`.
- [x] **Step 6-7:** implement the re-homing transform in curation (uses FR-MERGE relabel/prop-strip + `build_system_edge_cypher`); green.

```yaml
# FR-TYPESEP assertion ledger
- id: AST-TYPE-01
  statement: "The analyser prompt/skill forbids putting system facts (rendering/navigation/paradigm/perimeter) on a Service; they must be typed System edges."
  test: tests/recon/test_analyser_prompts.py::test_assignment_prompt_forbids_system_facts_on_service
  status: green (verifier-APPROVED 2026-07-19)
- id: AST-TYPE-02
  statement: "Curation re-homes a rendering/navigation prop wrongly set on a Service into a System reached by RENDERED_BY, stripping the Service prop."
  test: tests/recon/test_curation.py::test_curation_rehomes_rendering_prop_to_system
  status: green (verifier-APPROVED 2026-07-19)
```

---

## 6. FR-JOURNEY - light membership prop

*Goal:* the `journeys: list[str]` prop on `L1Service`, its curation-pass assignment (in FR-CURATE), the same-journey query helper, and the §1 adversarial rationale documented.
*Non-goals:* ordered journeys / `Journey` node / `PRECEDES` edges (AMV-11).

**Files:**
- Modify: `agent/recon/analysis/l1_read.py` (or `l1_inventory.py`) - `services_in_journey(project_id, journey_slug) -> list[str]`.
- Modify: `curation.py` - the journey writer (§4).
- Doc: this plan §1 + an `AMV-11` in `after-mvp-work-items.md` for the ordered-journey promotion path.
- Test: `tests/recon/test_l1_journey.py`.

- [x] **Step 1: failing test** `test_services_in_journey_returns_members` (fake read_fn). **Step 2:** fail. **Step 3:** implement the query (`MATCH (s:L1Service) WHERE $j IN s.journeys ...`). **Step 4:** green.
- [x] **Step 5:** add `AMV-11` (ordered-journey promotion) to `after-mvp-work-items.md`.

```yaml
# FR-JOURNEY assertion ledger
- id: AST-JRNY-01
  statement: "A Service can carry a journeys list; services_in_journey returns all services sharing a journey slug; membership never churns Service identity (identity ⊥ membership)."
  test: tests/recon/test_l1_journey.py::test_services_in_journey_returns_members ; ::test_journey_prop_does_not_change_identity
  status: green (verifier-APPROVED 2026-07-19)
```

---

## 7. FR-CURE2E - full pipeline + curation e2e re-run

*Goal:* the reproducible end-to-end proof against `soupmarket.shop` (OWASP Juice Shop, system stays BLIND to the by-design identity): bootstrap -> recon (both a batch run and a streaming run) -> `run_curation` -> assert the L1 graph is deduplicated, correctly typed (no system facts on services), journey-grouped, and swept; THEN compare streaming vs batch on this ONE identical complete pipeline.
*Non-goals:* asserting streaming beats batch beyond what the graph evidences (the quality lever remains AMV-9).

**Files:**
- Create: `scratchpad` driver `e2e_curation.py` (bootstrap-first per the operator-KB seeding memory; idempotent stream-step convergence; run curation; dump metrics).
- Doc: append the run to `STATE.md` + `loop-run-log.md`; update memory.

**Assertions (live):**
- [ ] No two `L1Service` share a normalised business function (dedup rate reported; zero synonym pairs after curation).
- [ ] No `L1Service` carries a rendering/navigation/paradigm/perimeter prop (all are System edges); every service with a UI is `EXPOSED_VIA` a `WebPresentation` System carrying `rendering_model` + `navigation_model` as independent props. (Corrected 2026-07-19 by FR-MODELFIX: this assertion previously named `RENDERED_BY` a RenderingSystem, an edge and kind the correction deleted.)
- [ ] Journey memberships present and coherent (checkout/signup/etc.); `services_in_journey` returns sensible groups.
- [ ] Stale pool + missing-systems sweep run; noise nodes are pruned/reclassed, not business-assigned (ties to AMV-8/AMV-9).
- [ ] Streaming-final L1 == batch-final L1 after curation (idempotent convergence holds through curation), OR the divergence is explained.
- [ ] Independent verifier re-runs the driver + graph queries and APPROVEs.

---

## 7b. FR-MODELFIX - the mechanism-as-System correction (operator, 2026-07-19)

*Goal:* implement the correction ratified in `docs/design/l1-domain-model-catalogue.md` (the authoritative catalogue + audit): a mechanism classification lives on a `System`, reached by a typed edge, NEVER as a Service prop.
Specifically: merge rendering + navigation into ONE `WebPresentation` System carrying both as INDEPENDENT attributes, reached by `EXPOSED_VIA`; DELETE `RENDERED_BY` and the SPA->CSR inference; and re-home `api_paradigm` (-> API System, `EXPOSED_VIA`) and `auth_methods` (-> `AuthenticationMechanism`, `AUTHENTICATED_BY {realm}`) off the Service.
*Why:* review of FR-CURATE caught the SPA->CSR inference violating L1D-31a; the audit found the same conflation for api_paradigm/auth_methods.
*Build target:* the catalogue doc §7 migration checklist (8 items).
*Supersedes:* FR-CURATE's `_navigation_target`/`_REHOME_RULES` navigation branch; FR-CURATE is verified together with FR-MODELFIX (its navigation re-homing was never gated).
*Non-goals:* the Stage-3 signature rewrite (out of scope; it reads the `rendering_model` prop instead of the sub-kind - a strict simplification).

```yaml
# FR-MODELFIX assertion ledger
- id: AST-MODEL-01
  statement: "SYSTEM_KINDS contains WebPresentation and NOT RenderingSystem_SSR_UI/_CSR_JSMap; SYSTEM_EDGE_RELS does NOT contain RENDERED_BY."
  status: green (verifier-APPROVED 2026-07-19)
- id: AST-MODEL-02
  statement: "commit_anatomy writes rendering_model + navigation_model as INDEPENDENT props on the WebPresentation System (via SystemDelta + EXPOSED_VIA edge), never as Service props; neither is inferred from the other."
  status: green (verifier-APPROVED 2026-07-19)
- id: AST-MODEL-03
  statement: "Curation re-homing moves rendering_model/navigation_model to WebPresentation props (EXPOSED_VIA), api_paradigm to the API System (EXPOSED_VIA), and auth_methods to AUTHENTICATED_BY; the Service prop is stripped in every case; no SPA->CSR (or any cross-dimension) inference remains."
  status: green (verifier-APPROVED 2026-07-19)
- id: AST-MODEL-04
  statement: "The analyser/webpage-profile/curation SKILL prompts state the corrected model (Service EXPOSED_VIA a WebPresentation carrying rendering + navigation; no mechanism classification on a Service). Existing FR-MERGE/anatomy tests are updated to the corrected model and the full regression stays green."
  status: green (verifier-APPROVED 2026-07-19)
```

## 8. Self-review (spec coverage)

- Dedupe services/systems + related nodes -> FR-MERGE (executor) + FR-CURATE (judgment) + FR-INVENTORY (prevention). Covered.
- Prune off-role nodes / transform kind / merge into existing -> FR-MERGE (delete/relabel/merge) + FR-CURATE (proposal). Covered.
- Prevent dup by consulting existing slugs / system_kind:discriminator before creating -> FR-INVENTORY. Covered.
- Journey role + mechanism + same-journey identification + adversarial brainstorm -> §1 + FR-JOURNEY + FR-CURATE. Covered.
- Service/System typing separation (webpage facts -> System, DFS traversal) -> FR-TYPESEP. Covered.
- Feedback 1 (L1 node colours) -> landed (WI-1, verifier-gated). Feedback 2 (likely_fields -> observed fields + AMV-10) -> landed (WI-2). Feedback 3 (SystemKind/DataRelationshipKind as nodes) -> answered (controlled-vocab registry, L1D-6); no change beyond viz muting.
- Post-recon curation actually runs (was never wired) -> FR-CURATE driver module + FR-CURE2E. Covered.

## 9. Execution handoff

Dispatch order: FR-INVENTORY, FR-MERGE, FR-JOURNEY, FR-TYPESEP-a in parallel (four subagents); then FR-CURATE + FR-TYPESEP-b (integrator); then FR-CURE2E. Each area closes only through an independent verifier. Do not start FR-CURATE until FR-MERGE + FR-JOURNEY are verifier-APPROVED.
