osu# Post-Recon Curation and L1 Remediation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Follow `loop-constraints.md` verbatim and the maker/checker discipline (a SEPARATE verifier runs each area's assertions; the implementer never self-approves).

> **STATUS (2026-07-20): ALL areas verifier-APPROVED, including `FR-CURE2E`. This plan is COMPLETE.**
> FR-CURE2E caught two blocking defects that unit + integration tiers structurally could not (see §7).
> Approved and landed: FR-INVENTORY, FR-MERGE, FR-JOURNEY, FR-TYPESEP (a+b), FR-CURATE, FR-MODELFIX.
>
> **AMENDMENT (2026-07-22): FR-JOURNEY is WITHDRAWN by operator decision and removed from the codebase.** It was built and verifier-APPROVED; it is retired, not failed. AST-JRNY-01 and AST-CUR-02 are annotated SUPERSEDED in place. Everything below that specifies journey grouping (the §Goal, §Architecture, the Global Constraint on light membership, FR-CURATE's stage-4 journey writer, and the §7 A3 run record) is preserved as the HISTORICAL record of what was built - it no longer describes the code. See §1, §6, and AMV-11.
> Green baseline at handoff: 827 unit tests pass, 46 of them this plan's tests (including 4 live-Neo4j integration, 0 skips), plus 4 frontend colour tests.
> ~~One PRE-EXISTING failure is unrelated to this plan and must not be read as curation fallout: `tests/recon/test_pipeline_e2e.py::test_pipeline_e2e_httpx_to_arjun_prop_dependent_target` reproduces identically at `ce5e351` (the commit before this plan's work) with `.env` present. It is separately a hermeticity defect - a `tests/recon/` unit-tier test reaches live Neo4j via `read_steering_signals`, fails open, and leaves arjun unexecuted. Tracked in `STATE.md`.~~
>
> **RESOLVED 2026-07-22, and the diagnosis above was WRONG.** The test is fixed and the suite has NO known-failure carve-out (host `tests/` = 892 passed, 0 failed). The hermeticity leak was real but a SEPARATE second bug; fixing it alone did not make the test pass. The actual cause: the arjun template gained a `printf '{}' > … && arjun …` prefix in `77dc0c2`, while the test still filtered executed commands with `command.startswith("arjun")` - so the filter went VACUOUSLY EMPTY and reported `no arjun command was executed` while arjun was wired correctly all along. This is the same vacuous-assertion family as §7's headline dedup defect. See `docs/design/testing-strategy.md` §6 and `STATE.md`.
> Re-confirmed 2026-07-22 and the root cause now OBSERVED directly: the live read raises `Neo.ClientError.Security.AuthenticationRateLimit` ("incorrect authentication details too many times in a row"), the steering read fails open, and the assertion that trips is `no arjun command was executed` - arjun never runs at all. Verified independent of the `--rate-limit` change by stashing `agent/recon/jobs.py` back to HEAD and reproducing identically. Note the test asserts nothing about the arjun template's CONTENT, so no template edit can cause or fix it.

**Goal:** build the post-recon curation phase (a driver-invoked module) that consolidates the accumulated L1 graph - deduplicating, pruning, and transforming nodes destructively through the sole-writer - plus at-write duplicate prevention, a light journey membership model (WITHDRAWN 2026-07-22, see §1), and Service/System typing separation, then re-run the exhaustive pipeline+curation e2e.

**Architecture:** the analyser stays a pure `f(L0-slice+observations) -> L1-deltas` written by idempotent MERGE (`l1_curator`, L1D-22). This plan adds a second phase after recon: a curation LLM pass proposes typed *reconciliation* operations (merge / prune / transform / journey-grouping - the last WITHDRAWN 2026-07-22) over the whole accumulated L1+L0 graph, and the `l1_curator` sole-writer executes them destructively (re-pointing edges, deleting/relabelling nodes) with provenance. Duplicate *prevention* is added upstream by injecting the current L1 identity inventory into every analyser prompt. Curation is orchestrated by a new driver-invoked module (`agent/recon/analysis/curation.py`), not wired into the request pipeline (operator decision).

**Tech Stack:** Python 3.13, LangGraph, pydantic, Neo4j 5.26-community (single physical DB, disjoint `:L1*` namespace), pytest (`.venv/bin/python -m pytest`), the analyser LLM role.

## Global Constraints

- The MVP fence is DOWN as of 2026-07-19 (operator decision). Destructive reconciliation (merge / delete / relabel) is now IN SCOPE, permitted in `l1_curator` ONLY, and must be idempotent, provenance-stamped, and re-point (never orphan) the edges of any node it removes or relabels. (`loop-constraints.md`)
- All `:L1*` writes go ONLY through `agent/recon/analysis/l1_curator.py` (sole-writer). L0 writes stay in `agent/recon/curator.py`; never edit the L0 sole-writer or `db/neo4j/schema.py` except through the sanctioned L1 seam.
- Provenance on every node/edge/ref write (L1D-25). `discriminator` defaults to the non-null string `"__singleton__"` (L1D-9/L1R-2). `identity ⊥ membership` (L1D-11).
- Fail-open / graceful degrade: an LLM / read / write error degrades to an empty-or-error result; it never crashes the caller (mirror the analyser pod).
- Curation is a SEPARATE driver-invoked module; do NOT wire it into `run_pipeline` (operator decision - protects the 3.8GiB host from a heavier terminal phase).
- ~~Journey is a LIGHT MEMBERSHIP prop (a `journeys: list[str]` on each Service), not a node and not ordered (operator decision). Order is a documented two-way extension, not built now.~~ **WITHDRAWN 2026-07-22:** journey grouping is removed entirely (§1, AMV-11).
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

## 1. The `journey` attribute - WITHDRAWN (2026-07-22)

This section specified a LIGHT MEMBERSHIP journey model (`journeys: list[str]` on each `L1Service`, assigned by the curation pass) and set out its adversarial rationale: concentrating cross-service trust reflection on same-journey pairs, posing step-skip / replay hypotheses, surfacing trust-boundary discontinuities across a flow, marking journey-carried DataItems, and bounding concretisation scope.

**The operator withdrew journey grouping on 2026-07-22.**
It is complex to get right and did not yield a significant improvement to the L1 model: the mechanism was verified correct, but in 2 of the 3 FR-CURE2E runs the LLM coined journeys at an altitude that grouped a single service each, which is a restatement of the service rather than a grouping - and that is exactly the altitude the whole adversarial rationale above depends on.

The implementation is removed in full (no compatibility shim): the `journeys` prop writer and curation stage, `CurationBatch.journeys`, `CurationReport.journeys_written`, `l1_read.services_in_journey`, `tests/recon/test_l1_journey.py`, and the journey instructions in the curation and analyser skills.
The rationale above, the order caveat, the measured altitude defect, and the three-step reinstatement path (altitude contract -> light membership -> ordered `Journey` node) are preserved in **AMV-11**, which now absorbs the former AMV-15.

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

> **Amended 2026-07-22:** the journey-assignment stage specified below was built, then removed with FR-JOURNEY. `run_curation` now runs six stages (read -> propose -> reconcile -> anatomy -> re-home -> sweep); `CurationBatch.journeys` and `CurationReport.journeys_written` no longer exist. The text below is the original spec, kept as the build record.

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
  test: REMOVED (was tests/recon/test_curation.py::test_curation_groups_same_journey_services)
  status: SUPERSEDED 2026-07-22 - see AST-JRNY-01. Curation stage 4 (the journey
    writer) is deleted and the later stages renumbered; the remaining AST-CUR
    assertions are unaffected.
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

## 6. FR-JOURNEY - light membership prop (BUILT, then WITHDRAWN 2026-07-22)

This area shipped and was verifier-APPROVED on 2026-07-19: the `journeys: list[str]` prop on `L1Service`, its curation-pass assignment, `services_in_journey`, and the §1 rationale.
The operator withdrew journey grouping on 2026-07-22 and the area is removed in full; AST-JRNY-01 is annotated SUPERSEDED (retired, not failed) rather than deleted.
See §1 and AMV-11 for the evidence and the reinstatement path.

## 7. FR-CURE2E - full pipeline + curation e2e re-run

*Goal:* the reproducible end-to-end proof against `soupmarket.shop` (OWASP Juice Shop, system stays BLIND to the by-design identity): bootstrap -> recon (both a batch run and a streaming run) -> `run_curation` -> assert the L1 graph is deduplicated, correctly typed (no system facts on services), journey-grouped, and swept; THEN compare streaming vs batch on this ONE identical complete pipeline.
*Non-goals:* asserting streaming beats batch beyond what the graph evidences (the quality lever remains AMV-9).

**Files:**
- Create: `scratchpad` driver `e2e_curation.py` (bootstrap-first per the operator-KB seeding memory; idempotent stream-step convergence; run curation; dump metrics).
- Doc: append the run to `STATE.md` + `loop-run-log.md`; update memory.

### FR-CURE2E results (2026-07-19/20, target `soupmarket.shop`)

Run matrix (sequential, never parallel - the 3.83GiB host).
Streaming-vs-batch convergence is a SUBSTRATE property (L1D-23), so it is proven once on the baseline model; the model comparison runs on batch, the default mode.

| Run | Project | Model | Mode | Recon | Total |
|---|---|---|---|---|---|
| A | `soupcure_pro_batch` | v4-pro | batch | 927s | 1690s |
| B | `soupcure_pro_stream` | v4-pro | streaming | 2421s | 3486s |
| C | `soupcure_flash_batch` | v4-flash | batch | see below | - |

**The headline finding: the e2e caught a BLOCKING defect that unit + integration tiers could not.**
Post-recon curation could not deduplicate at all.
`run_curation` read its index-cards ONCE at stage 1 and passed that snapshot to every later stage; stage 3 merged a duplicate away, then stage 5 iterated the stale pre-merge list and `commit_anatomy` MERGEd the Service back by slug.
Curation silently undid its own dedup, reported `merged=1` (true when `reconcile` ran), and never converged - every subsequent run repeated the cycle forever.
`reconcile` and the FR-MERGE builders are correct in ISOLATION, which is exactly why the four live-Neo4j integration tests pass and never saw it: it is an INTERACTION defect, only reachable in the integrated flow.
Fixed at root cause (re-read the context after any destructive op, which also covers the journey and re-home stages); guarded by `test_curation_does_not_resurrect_a_merged_away_service`.

**Why it was nearly missed: runs A and B passed A1/A2 VACUOUSLY.**
Both reported `merged=0, deleted=0, relabelled=0, rehomed=0` - not because reconciliation worked, but because upstream PREVENTION (FR-INVENTORY identity pinning + FR-TYPESEP-a prompt rule) meant no duplicate and no stranded mechanism prop was ever written (`mech_props_pre_curation` was already 0).
A green A1/A2 on a clean graph says nothing about the destructive path.
This is the `stale_pool=0 is a NEGATIVE signal` lesson in a new form, and it motivated the adversarial probe below.

**The adversarial (dirty-graph) probe - the test that actually exercises reconciliation.**
Plants two synonym Services each AGGREGATING distinct real L0 Endpoints, plus one Service carrying stranded `rendering_model`/`navigation_model`/`api_paradigm`/`auth_methods`, then runs the REAL `run_curation` (real LLM proposal pass, real sole-writer, live Neo4j).

| Assertion | Before fix | After fix |
|---|---|---|
| ADV-1 synonyms merge into one | FAIL (3 services, both survived) | **PASS** (3 -> 2) |
| ADV-2 merge orphans no edges | PASS | **PASS** (4/4 endpoints keep inbound AGGREGATES) |
| ADV-3 stranded props re-homed + stripped | PASS | **PASS** (`svc_mech_props` 1 -> 0, `rehomed`=4) |
| ADV-4 idempotent second pass | PASS (wrongly - nothing ever changed) | **PASS** (2nd run `merged=0`, was `merged=1` forever) |

**A5 as written is CONFOUNDED and was split in two.**
Bootstrap is an LLM call: the same KB + same model seeded 15 services (A), 18 (B), 17 (C).
The arms therefore diverge BEFORE the analyser runs, so a cross-project set-difference measures bootstrap non-determinism, not the delivery mode.
- **A5-controlled (the real L1D-23 test, PASS):** run the BATCH analyser over the settled STREAMED project - same seed, same surface, both modes. Result: **0 new services / systems / data items, 0 lost.** Identity converged exactly. Honest caveat: AGGREGATES moved 168 -> 176 (+8), so identity converged while MEMBERSHIP accreted slightly - consistent with `identity ⊥ membership` (L1D-11) plus analyser non-determinism (AMV-9), not a delivery-mode difference.
- **A5-observational (FAIL, divergence EXPLAINED):** batch 18 vs streaming 20 services, Jaccard 0.407. The "disjoint" sets are the SAME business functions under differently-coined slugs: `account-management`/`account`, `admin-panel`/`admin`, `reward-points`/`loyalty`, `seller-payouts`/`seller-payout`, `support-desk`/`support`, `training-challenges`/`challenges`, `juice-club`/`subscription`.

**New finding - `business_function_slug` is stable WITHIN a project but not ACROSS runs.**
FR-INVENTORY pins identities by injecting the current inventory, so each project stays internally clean (0 synonym pairs in every run); a FRESH project starts from nothing and the LLM coins fresh names.
Operationally acceptable (a project is the accumulation unit) but it makes cross-run graph comparison unreliable. Registered as AMV-12.
Note `seller-payouts` vs `seller-payout`: a bare plural, which the A1 normaliser (casefold + strip non-alphanumerics) does NOT collapse - the dedup check wants light stemming. Registered as AMV-13.

**Assignment PRECISION - streaming's extra coverage is mostly noise (measured, not assumed).**
Same classifier shape as the 2026-07-17 baseline, so numbers are comparable.

> **Measurement ordering (verifier-flagged).** The run-B row below is a **pre-A5-controlled SNAPSHOT** and is NO LONGER RE-DERIVABLE from the live graph.
> `a5_controlled.py` runs the batch analyser OVER `soupcure_pro_stream` - that is a WRITE, and it added +8 assignments after this table was taken (disclosed below as 168 -> 176).
> Re-running the classifier today yields **155 assigned / 107 business / 18.7% strict / 31.0% inclusive**, i.e. 65 extra of which 17 business and 48 noise = **74% junk** (not 84%).
> The two are reconcilable exactly, against the PRE-A5 total: **168** total AGGREGATES minus 21 non-Endpoint edges (13 Header, 6 Parameter, 1 Technology, 1 BaseURL) = **147**, the figure published here; post-A5 the same arithmetic is 176 - 21 = **155**, today's re-measurement.
> The run-A row IS still re-derivable. The qualitative conclusion is unaffected under either measurement: streaming buys a lower stale pool with substantial noise, batch carries none, batch stays the default.

| | A (batch) | B (streaming) |
|---|---|---|
| Assigned endpoint edges | 90 | 147 |
| **Business** assignments | 90 | 99 (+9) |
| **Noise** assignments | **0** | **48** |
| Noise share (strict / inclusive) | **0% / 0%** | **19.7% / 32.7%** |
| Stale pool | 92/182 (50.5%) | 37/182 (20.3%) |

Of streaming's 57 extra assignments, 9 are business and **48 are noise** (84% junk; 74% on the post-A5 re-measurement above): `/chunk-*.js`, `/ethers.js`, `/juice-shop/build/lib/insecurity.js`, concentrated in `admin` (29) and `challenges` (17).
Streaming's lower stale pool was BOUGHT with over-assignment - precisely the AMV-9 failure direction.
Plausible mechanism: streaming runs the analyser once per producing job against a PARTIAL surface, and MERGE accumulates monotonically with no retraction, so every speculative early assignment is permanent; batch sees the complete surface once and can be selective. That is precision decay by construction, not a tuning problem.
**This settles NM-7's original deferral question in the opposite direction from the hope:** the deferral asked for streaming to be adopted only once a noise-reduction win was MEASURED. Measured on one identical pipeline, streaming *increases* noise 0% -> 19.7%, costs 2.6x recon wall-clock (927s -> 2421s), and buys +9 business assignments. The mechanism is sound and provably idempotent, but it is not the quality lever it was hoped to be. Batch remains the right default.
Batch reaching **0% noise** is itself a large improvement on the 2026-07-17 baseline's 31-38%, attributable to the FR-INVENTORY identity pinning tightening assignment discipline.

**Infrastructure failures encountered (recorded, none masked):**
1. Postgres entered recovery mode mid-run-A ("database system was not properly shut down", auto-recovered in ~14s). The run SURVIVED: the heartbeat loop is fail-open. Not container OOM (`RestartCount=0`, `OOMKilled=false`, ~1.8GiB of 3.83GiB in use) - consistent with the documented Docker Desktop VM I/O fault.
2. The agent container was RECREATED at 23:47:39, wiping `/srv/.cure2e` (only `./agent`, `./db`, `./skills` are bind-mounted). All JSON artifacts were lost; the Neo4j/Postgres volumes survived, so every figure was re-derivable from the live graphs. Artifacts must be copied host-side immediately.
3. macOS Docker file-sharing CACHE LAG meant a host edit to `curation.py` was not visible in the container for minutes, which briefly made a correct fix look like it had failed. Hash both sides before concluding a fix did not work.
4. **The target died mid-experiment and the pipeline did not notice.** The Juice Shop container exited (133) at ~23:07. The first run C then reported every job `success` and the run `complete` in 39.7s with **1 endpoint** - a DEAD-TARGET result that would have been reported as "flash produces a thinner graph". Invalidated and re-run against a restored target. Root gap: `run_pipeline` is best-effort, so a job whose tool returns nothing is indistinguishable from one that worked. Registered as AMV-14; the driver now carries a surface-sanity gate that aborts below 20 endpoints.

**Assertions (live):**
- [x] No two `L1Service` share a normalised business function (dedup rate reported; zero synonym pairs after curation).
- [x] No `L1Service` carries a rendering/navigation/paradigm/perimeter prop (all are System edges); every service with a UI is `EXPOSED_VIA` a `WebPresentation` System carrying `rendering_model` + `navigation_model` as independent props. (Corrected 2026-07-19 by FR-MODELFIX: this assertion previously named `RENDERED_BY` a RenderingSystem, an edge and kind the correction deleted.)
- [x] Journey memberships present and coherent (run A; runs B/C coin degenerate single-member journeys -> AMV-11, formerly AMV-15) (checkout/signup/etc.); `services_in_journey` returns sensible groups. **This finding is what motivated withdrawing journey grouping on 2026-07-22.**
- [x] Stale pool + missing-systems sweep run; noise nodes are pruned/reclassed, not business-assigned (ties to AMV-8/AMV-9).
- [x] Streaming-final L1 == batch-final L1 after curation (A5-controlled PASS; observational divergence explained) (idempotent convergence holds through curation), OR the divergence is explained.
- [x] Independent verifier re-runs the driver + graph queries and APPROVEs. **APPROVED 2026-07-20** (rejected once on documentation overstatement; both items corrected).

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
  test: tests/test_l1_curator_builders.py::test_webpresentation_replaces_rendering_systems ; ::test_rendered_by_removed_from_edge_taxonomy
  status: green (verifier-APPROVED 2026-07-19)
- id: AST-MODEL-02
  statement: "commit_anatomy writes rendering_model + navigation_model as INDEPENDENT props on the WebPresentation System (via SystemDelta + EXPOSED_VIA edge), never as Service props; neither is inferred from the other."
  test: tests/recon/test_anatomy.py::test_webpage_profile_sets_two_independent_slots ; ::test_dimensions_are_independent_spa_ssr
  status: green (verifier-APPROVED 2026-07-19)
- id: AST-MODEL-03
  statement: "Curation re-homing moves rendering_model/navigation_model to WebPresentation props (EXPOSED_VIA), api_paradigm to the API System (EXPOSED_VIA), and auth_methods to AUTHENTICATED_BY; the Service prop is stripped in every case; no SPA->CSR (or any cross-dimension) inference remains."
  test: tests/recon/test_curation.py::test_curation_rehomes_rendering_prop_to_system ; ::test_curation_rehomes_navigation_without_cross_dimension_inference ; ::test_curation_rehomes_auth_methods_to_authenticated_by ; ::test_curation_rehomes_llm_proposed_prop
  status: green (verifier-APPROVED 2026-07-19)
- id: AST-MODEL-04
  statement: "The analyser/webpage-profile/curation SKILL prompts state the corrected model (Service EXPOSED_VIA a WebPresentation carrying rendering + navigation; no mechanism classification on a Service). Existing FR-MERGE/anatomy tests are updated to the corrected model and the full regression stays green."
  test: tests/recon/test_analyser_prompts.py::test_assignment_prompt_forbids_system_facts_on_service (asserts RENDERED_BY absent)
  status: green (verifier-APPROVED 2026-07-19)
```

## 8. Self-review (spec coverage)

- Dedupe services/systems + related nodes -> FR-MERGE (executor) + FR-CURATE (judgment) + FR-INVENTORY (prevention). Covered.
- Prune off-role nodes / transform kind / merge into existing -> FR-MERGE (delete/relabel/merge) + FR-CURATE (proposal). Covered.
- Prevent dup by consulting existing slugs / system_kind:discriminator before creating -> FR-INVENTORY. Covered.
- Journey role + mechanism + same-journey identification + adversarial brainstorm -> §1 + FR-JOURNEY + FR-CURATE. Covered, then WITHDRAWN 2026-07-22 (§1, AMV-11).
- Service/System typing separation (webpage facts -> System, DFS traversal) -> FR-TYPESEP. Covered.
- Feedback 1 (L1 node colours) -> landed (WI-1, verifier-gated). Feedback 2 (likely_fields -> observed fields + AMV-10) -> landed (WI-2). Feedback 3 (SystemKind/DataRelationshipKind as nodes) -> answered (controlled-vocab registry, L1D-6); no change beyond viz muting.
- Post-recon curation actually runs (was never wired) -> FR-CURATE driver module + FR-CURE2E. Covered.

## 9. Execution handoff

Dispatch order: FR-INVENTORY, FR-MERGE, FR-JOURNEY, FR-TYPESEP-a in parallel (four subagents); then FR-CURATE + FR-TYPESEP-b (integrator); then FR-CURE2E. Each area closes only through an independent verifier. Do not start FR-CURATE until FR-MERGE + FR-JOURNEY are verifier-APPROVED.
