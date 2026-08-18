# Assertions - DataPlane Analyser A.1

**Source:** ticket #48 (Diekgbbtt/polyphemus), spec `docs/design/dataplane-A1-decisions.md` (RATIFIED 2026-07-30).
**Seams under assertion:** `data_modeller.shape_proposal` and its six named gates (`narrow_to_data`, `drop_unknown_relationship_kinds`, `resolve_surface_refs`, `drop_out_of_inventory_services`, `bind_fields_to_observed`, `enforce_groundedness`); `data_modeller.make_data_modeller_body` against the supervisor's `ProposerBody` protocol; the curator `write_fn` seam (`supervisor._chunked_write_fn`); `chunking.admit_for_role` over `ROLE_ADMITS["data_modeller"] = {Parameter, Header, Secret}`; the live graph via `l1_curator.enrich`.

Target interface: the module `src/polymerhus/analysis/data_modeller.py` does not exist yet. Every predicate below names the seam signature specified in the design doc (sections 5, 6, 7, 11); tests are written against that target interface and are RED until `/implement` builds it - this is intentional (TDD: assertions before implementation).

## Contract predicates (integration)

**C1 - narrow.** seam: `narrow_to_data`. semantic: success (structural exclusion). input: a raw `L1DeltaBatch` carrying 2 services, 3 aggregates, 1 system, 1 system_edge, 2 data_items, 2 surfaces_at, 2 data_flows, 1 data_relationship. observable: shaped batch has `services == systems == aggregates == system_edges == []`; the four data lists unchanged (2, 2, 2, 1). yields: `tests/integration/test_data_modeller_contracts.py::test_D1_narrow_strips_non_data_lists`.

**C2 - kind allowlist.** seam: `drop_unknown_relationship_kinds`. semantic: malformed (partial-valid input). input: 3 `data_relationships` with kinds `derived_from`, `reflected_in`, `sourced_from`. observable: exactly 2 survive; `stats.unknown_kind_dropped == 1`. yields: `test_D2_kind_allowlist_drops_unknown`.

**C3 - reference gate, canonicalisation.** seam: `resolve_surface_refs`. semantic: success (formatting-independent correctness). input: `surfaces_at` with `l0 = {label: "param", identity: {name: "ProductId"}}`; chunk carries `Parameter{name: ProductId, position: query, endpoint_path: /api/x, baseurl: B}`. observable: shaped entry has `l0.label == "Parameter"`, `l0.identity == {name: ProductId, position: query, endpoint_path: /api/x, baseurl: B}` (all four identity keys). yields: `test_D3_reference_gate_canonicalises`.

**C4 - reference gate, drop.** seam: `resolve_surface_refs`. semantic: outlier (unresolvable reference). input: 3 `surfaces_at`, 1 names a parameter absent from the chunk. observable: exactly 2 survive; `stats.unresolvable_surfaces == 1`. yields: `test_D4_reference_gate_drops_unresolvable`.

**C5 - validation gate.** seam: `drop_out_of_inventory_services`. semantic: outlier (reference to nothing). input: inventory `{cart, catalogue}`; 3 `data_flows` naming `cart`, `catalogue`, `wishlist`. observable: exactly 2 survive; `stats.out_of_inventory_flows == 1`; backlog contains exactly 1 entry with the literal substring `wishlist`. yields: `test_D5_validation_gate_drops_and_backlogs`.

**C6 - no Service minted by the data path.** seam: `shape_proposal` end-to-end against a live Neo4j fixture. semantic: outlier (defends #34 D4). input: a chunk whose raw model output names 2 non-existent service slugs in `data_flows`. observable: `count(:L1Service {project_id: $pid})` unchanged before/after a full pass. yields: `test_D6_no_service_minted` (integration, real Neo4j via `neo4j_target()`).

**C7 - observed-only fields.** seam: `bind_fields_to_observed`. semantic: malformed (speculative input rejected). input: admitted asset names `{ProductId, quantity}`; proposed `fields = [ProductId, quantity, price, discount]`. observable: shaped `fields == [ProductId, quantity]`; `stats.fields_unobserved_dropped == 2`. yields: `test_D7_fields_observed_only`.

**C8 - fields never shrink (compounding).** seam: `bind_fields_to_observed`. semantic: duplicate/idempotent (streamed re-proposal). input: persisted `fields = [ProductId]` for `shopping_basket`; new proposal `fields = [quantity]` from a chunk observing `quantity` only. observable: shaped `fields == [ProductId, quantity]`; `stats.fields_carried_forward == 1`. yields: `test_D8_fields_compound_never_shrink`.

**C9 - fields omitted when nothing observed.** seam: `bind_fields_to_observed`. semantic: empty-but-valid. input: proposed `fields = [price]`; observed vocabulary excludes `price`; no persisted fields. observable: shaped item's `props` contains no `fields` key at all. yields: `test_D9_fields_omitted_when_none_observed`.

**C10 - groundedness, surface required.** seam: `enforce_groundedness`. semantic: outlier (path-only lift rejected, per the 2026-07-30 ratification). input: 3 new `data_items` - one with a surviving `surfaces_at` only, one with a surviving `data_flow` only (no surfaces_at), one with neither. observable: exactly 1 survives (the surfaces_at-only item); `stats.ungrounded_items_dropped == 2`. yields: `test_D10_groundedness_requires_surface`.

**C11 - orphan relationship.** seam: `enforce_groundedness`. semantic: outlier. input: a `data_relationship` whose `to_item_key` names no surviving item and is absent from the live inventory. observable: 0 relationships survive; `stats.orphan_relationships_dropped == 1`. yields: `test_D11_orphan_relationship_dropped`.

**C12 - gate order is load-bearing.** seam: `shape_proposal` (full pipeline). semantic: ordering. input: a batch whose only anchor for a new item is a `surfaces_at` the reference gate (gate 3) drops. observable: `stats.kept_items == 0`, `stats.unresolvable_surfaces == 1`, `stats.ungrounded_items_dropped == 1` (proves gate 6 ran after gate 3 saw the drop, not before). yields: `test_D12_gate_order_load_bearing`.

**C13 - empty but valid.** seam: `make_data_modeller_body` / `admit_for_role`. semantic: empty-valid. input: a chunk admitting 0 Parameters, 0 Headers, 0 Secrets. observable: empty batch returned; injected `invoke_fn` call count == 0 (no LLM call for nothing to act on). yields: `test_D13_empty_admission_no_llm_call`.

**C14 - degradation.** seam: `make_data_modeller_body`. semantic: degradation (four sub-cases). input: (a) raising `invoke_fn`, (b) `None`-returning `invoke_fn`, (c) raising inventory read, (d) raising aggregation read. observable: each yields an empty-or-partial batch and never raises into the caller; case (a)/(b) additionally sets `stats.reflection_exhausted == True`. yields: `test_D14_degradation_invoke_raises`, `test_D14_degradation_invoke_none`, `test_D14_degradation_inventory_read_raises`, `test_D14_degradation_aggregation_read_raises`.

**C15 - idempotent replay.** seam: `shape_proposal` + `l1_curator.enrich` against a live Neo4j fixture. semantic: duplicate-idempotent. input: the same chunk + same inventory, shaped and written twice. observable: byte-identical shaped batch on both passes; every `:L1DataItem`, `SURFACES_AT`, `PRODUCES`, `CONSUMES`, and typed relationship COUNT unchanged between the two writes. yields: `test_D15_idempotent_replay` (integration, real Neo4j).

**C16 - the write path carries data (fixes the DPL-DEC-21 silent drop).** seam: `supervisor._chunked_write_fn`. semantic: outlier (regression guard for a found-and-fixed defect). input: a data-only batch (non-empty `data_items`, empty `systems`/`system_edges`) routed through the run's `write_fn`. observable: non-zero `enrichment` counts in the returned `AnalyserExport`; the SAME batch routed through the OLD `_aggregates_write_fn` in isolation produces zero (documents the defect this predicate guards against regressing). yields: `test_D16_write_routing_carries_data_only_batch`.

**C17 - the proposer emits no Cypher and sets no provenance.** seam: `data_modeller` module, static. semantic: success (structural invariant). input: none (static check). observable: no symbol in `data_modeller.py` contains the string `MERGE`; the four data proposal shapes (`DataItemProposal`, `SurfacesAtProposal`, `DataFlowProposal`, `DataRelationshipProposal`) carry no `provenance` field. yields: `test_D17_no_cypher_no_provenance`.

## Walkthrough predicates (end-to-end)

**E1 - exact-count pass over one chunk.**
grounds: T1's deliverable predicate (`count(:L1DataItem) >= 1`, each item grounded); #10's responsibility statement; DPL-DEC-10/13 (surface-required groundedness).
entry seam: `supervisor.analyse_chunked`, dispatching the three-role chunk-major schedule for one chunk.
input: one pseudo-job chunk carrying 2 Endpoints (`GET /api/basket`, `POST /api/orders`, both on baseurl `B`), 4 Parameters (`ProductId`, `quantity` on `/api/basket`; `addressId`, `couponCode` on `/api/orders`), 1 Header (`X-Cart-Token` on `B`); a bootstrapped inventory of exactly 2 Services (`cart`, `orders`), each carrying a `service_contract`; the Assigner having already assigned `/api/basket -> cart` and `/api/orders -> orders` (a pre-seeded `AGGREGATES` state).
live edge: the injected `invoke_fn` for the data_modeller - `none` for the internal graph/supervisor path (real Neo4j via `neo4j_target()`), a FIXED deterministic stub for the integration-tier exact-count assertion, the live LLM provider only in the separate live-tier variant (which asserts `>= 1` plus integrity clauses, never an exact model-dependent count, per the design doc's own precision-bar note).
path: `data_modeller` dispatched AFTER `assigner`/`mechanism_typist` on the same chunk (DPL ordering, section 3) -> reads the live L1 inventory + `read_service_aggregations` -> reflection call (bounded, fail-closed on exhaustion) -> extraction call -> `shape_proposal`'s six gates in order -> `_chunked_write_fn` widened routing -> `l1_curator.enrich`.
terminal: exactly 3 `:L1DataItem` nodes; exactly 5 `SURFACES_AT` edges, every one targeting a `Parameter` or `Header` node (never an `Endpoint`); at least 1 `PRODUCES` and at least 1 `CONSUMES`, every flow's source among the 2 pre-existing `:L1Service` nodes; exactly 2 `:L1Service` nodes (unchanged - no minting); every `:L1DataItem` carrying `prov_job == "analyser:<run_id>"`; no `:L1DataItem.fields` entry outside `{ProductId, quantity, addressId, couponCode, X-Cart-Token}`.
observed: the Neo4j query `MATCH (d:L1DataItem {project_id: $pid}) RETURN d` plus the analogous `SURFACES_AT`/`PRODUCES`/`CONSUMES` count queries, run against the real test database via `tests/conftest.py::neo4j_target()` (the repo's established live-tier fixture - no new operator-supplied bootstrap value needed, per `tests/e2e/test_mechanism_typist_walkthrough.py`'s precedent).
yields: `tests/e2e/test_data_modeller_walkthrough.py::test_E1_three_role_pass_exact_counts` (integration-tier fixed-invoke variant) and `test_E1_three_role_pass_live_floor` (live-tier `>= 1` + integrity-clause variant).
