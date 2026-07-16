# Layer-1 Service/System Model — MVP Plan (Phase-0 artifact)

> **For agentic workers:** this is the reviewed decomposition + assertion ledger produced by Phase 0 of `docs/design/L1-MVP-executor-loop-prompt.md`.
> Each FR area is a bounded goal in its own git worktree; its verifiable stop condition is "every assertion for this area is green, run by a separate verifier sub-agent (`loop-engineering/skills/loop-verifier`)".
> Steps use checkbox (`- [ ]`) syntax for tracking. The live backlog + status is `STATE.md`; the binding guardrails are `loop-constraints.md`.

**Goal:** build the Layer-1 service/system-model substrate (the two node kinds, the two typed interface agreements A & B, and the skill interface) as scoped by `service-system-model-L1-implementation-bridge.md`, swapping reasoning onto the existing recon substrate rather than re-cutting it.

**Architecture:** L1 lives as a disjoint `:L1*` label namespace inside the one physical `neo4j:5-community`, written only by a new sole-writer `l1_curator` mirroring the L0 `curator.py` discipline.
Cross-layer `AGGREGATES` references are native Neo4j edges from the L1 Service to the co-resident L0 node, carrying the L1D-25 judgment envelope as edge properties (operator decision, option A; see §5 note).
The analyser is a new compiled LangGraph subgraph mirroring `build_pod_graph`, reusing `configurator/gate/fail` and replacing `execute→L0-slice read`, `triager→analyser LLM`, `curator→l1_curator`.
Backward recon is one contract (`AnalyserReconRequest`) + one executor (`request_targeted_recon`) reusing `run_job` outside the phase barrier.

**Tech Stack:** Python 3.13, LangGraph, `langchain-openai` structured output (`method="function_calling"`), Neo4j 5 community (Cypher `MERGE` + `IS UNIQUE` constraints), Postgres 16 + pgvector, pytest (unit / integration / e2e), Langfuse tracing + scores.

## Global Constraints

- **MVP fence:** build only what the bridge marks in-scope. Everything `NM-n`, every `L1OP-n` engine, and anything behind the Stage-3 fence (projection algorithm, signature-evaluation engine, risk scoring, phase-2 abduction) is denylisted for implementation — forward-compat constraint only.
- **Sole-writer:** L0 graph writes go only through `agent/recon/curator.py`; L1 graph writes go only through the new `l1_curator`. Never write `:L1*` labels from anywhere else.
- **Denylist paths (escalate, never edit):** `.env`, `.env.*`, secrets/credentials, and the L0 sole-writer guarantees `agent/recon/curator.py` + `db/neo4j/schema.py` except through sanctioned L1 seams.
- **Idempotency:** every L1 write is an idempotent `MERGE` on L1 identity (`L1D-22`); running twice yields one node.
- **`identity ⊥ membership`** (`L1D-11`): never key an L1 unit on its member set.
- **`__singleton__` is a literal non-null string** (`L1D-9`/`L1R-2`), never SQL/Cypher `null`.
- **Provenance on every node/edge/ref write** (`L1D-25`, mirrors `curator.py:187-188`).
- **Fail-open / graceful degrade:** a steering / skill / LLM / targeted-job error degrades to an empty-or-error result; it never crashes the caller (mirrors `pipeline.py:341-346,355-359` and `steel_client.py:43-100`).
- **Attempt cap = 3** per FR area, then escalate with full context in `STATE.md`.
- **Maker/checker:** the implementer never marks its own work done; a separate `loop-verifier` sub-agent runs the assertions and APPROVEs.

---

## 1. Phase-0 ratified one-way doors (with probe evidence)

All five decide-first, irreversible decisions from bridge §3 were probed against the running code on 2026-07-16 and ratified to the bridge's recommended option.
Reversing one later invalidates finished work, so no Phase-1 code starts until these are settled — they are settled below.

| # | Decision (ratified) | Probe evidence (`path:line`) | Requirement |
|---|---|---|---|
| **D1** | **Two-store topology = option (a):** disjoint `:L1*` label namespace + a second sole-writer inside the single physical `neo4j:5-community`. **Cross-layer `AGGREGATES` refs are native edges to the co-resident L0 node (option A), revised from the bridge's L1D-2 node-property recommendation** — see the §5 note; the bridge's "no native edges" rationale (a relationship can't carry a foreign composite key) is moot once D1 co-locates both layers in one store, so the edge is clean and matches the spec §6 taxonomy. | `grep -n "database=" agent/app/clients/neo4j_client.py` → **no match (exit 1)** ⇒ single default DB, community edition cannot host a second named DB. L0 `:Service` collision confirmed at `db/neo4j/schema.py:12` (`service_unique` on `(name, port_number, ip_address, project_id)`) ⇒ the `l1_*` label prefix is mandatory. | L1D-1 / L1D-2 |
| **D2** | **Identity keys + sentinel:** System `(project_id, system_kind, discriminator)` with `discriminator` a literal non-null string defaulting to `"__singleton__"`; Service `(project_id, business_function_slug)`; both hardened with `IS UNIQUE` mirroring `endpoint_unique`. | `db/neo4j/schema.py:7-24` — **every** existing constraint is a composite `(…, project_id) IS UNIQUE` with no nullable component. No nullable-key precedent exists, so the sentinel must be a real string (a `null` discriminator MERGE'd twice creates two nodes — the `L1R-2` trap). | L1D-9 / L1D-12 |
| **D3** | **Interface-B ⇄ D2 unification:** one contract `AnalyserReconRequest` (superset of D2's `{component,tool,template_set}`) + one executor `request_targeted_recon(...) -> list[PodExport]` reusing `run_job`; `recon_jobs` gains `correlation_id, requester_id, origin` via idempotent `ALTER`. | D2's fixed signature at `docs/design/recon-pipeline-forward-decisions.md:44,52`. Same seam: `run_job(job, input_assets, run_id=…, phase=…, extra=…)` call site at `agent/recon/pipeline.py:352`, executed sequentially (`pipeline.py:435-436`), terminal `set_run_status(run_id,"complete")` at `pipeline.py:444`. **Doc correction:** the forward-decisions doc's `pipeline.py:171` citation for the terminal statement is stale (file grew); the real line is `pipeline.py:444`, as the bridge already states. `recon_jobs` lacks the 3 columns today (`db/postgres/init.sql:48-59`); idempotent-`ALTER` precedent at `init.sql:60`. | L1D-26 |
| **D4** | **Typed-spine cut + skill interface:** freeze spine slots (`api_paradigm`, `navigation_model`, `rendering_model`, `auth_methods`) and the anatomy-skill triple (classification→slot, evidence→Observation, probe→interface-B); generalise `_load_triager_skill` into `skill_for`. | `agent/recon/pod.py:441-481` `default_triage_fn` is the exact structured-output pattern to copy: `chat_model_for("triager").with_structured_output(_ObservationBatch, method="function_calling")`. `_load_triager_skill` (`pod.py:415-438`) is the loader to generalise. **Load-bearing detail:** `method="function_calling"` is required (`pod.py:449-453`) because the strict `json_schema` path rejects open-ended `dict` fields (`Observation.anchor`); the analyser's `_L1DeltaBatch` must use the same method if it carries an open-ended field. | L1D-17 / L1D-31 |
| **D5** | **Preserve the endpoint-template key at assignment.** Write a derived `endpoint_template` (concrete path → `/{id}` by numeric/uuid segment) on the L0 `Endpoint` or the L1 `AGGREGATES` ref at assignment time; the full reducer is deferred (`NM-10`). | `agent/recon/parsers/katana_parser.py:20-52` emits **concrete** endpoints via `url_to_deltas` with no template normalization. The spec's §9.4/§9.6 claim "katana already yields path templates in L0" is **false of the code** — template-key preservation is net-new and must land at write time, not be assumed. | L1D-32 |

## 2. Stale-doc / stale-premise corrections carried into this plan (code wins)

These are verified against the files and reshape the work; they override any contrary reading of the spec.

1. **Phase barrier is sequential, not `asyncio.gather`** (`pipeline.py:431-436`, with the explicit anti-OOM comment). A single targeted job is already the unit of execution, so interface-B is a straightforward `run_job` call outside the loop.
2. **`doc_chunks` / `ingest_runs` are schema-built but pipeline-unbuilt** (`db/postgres/init.sql:62-85`; no writer repo-wide; `main.py` registers only `recon_router`). The `/ingest` content pipeline is **Deferred** (bridge §5); L1 nodes may carry identity-keyed anchors immediately, referencing an empty store.
3. **The triager skill loader is real** (`pod.py:415-438`), degrades to `""` gracefully; only a *generic* `skill_for` is missing.
4. **`job_orchestrator` is a live structured-output LLM role** (`orchestrator_agent.py`), so the analyser is not the first heavy-reasoning consumer — a proven pattern exists to copy.
5. **Recon emits concrete endpoint paths, never templates** (`katana_parser.py`, `parsers/_urls.py`); `sample_values` is written nowhere (repo-wide grep: 0) — the IDOR value-shape atom cannot rely on it.
6. **`auth_context` is already structured/multi-part and deep-merged** (`routes.py:47-119`, `init.sql:19-39`) but **not** role/realm-tagged — that tagging is the real FR-AUTH delta.
7. **Steel/CDP is config-gated with a real provider** (`steel_client.py:43-100`, `steel_provider.py`); the webpage-profile skill rides it, unblocked by supplying `STEEL_API_KEY`.

---

## 3. Complete FR-area catalogue

A functional-requirement area is a component with an independently verifiable behaviour.
Seeds from executor-prompt §11 are completed here.
Gap class ∈ {reuse | extend | net-new | blocked-on-unbuilt-dep}.
Each area's full assertion ledger is authored (and reviewed) at the moment that area's loop starts; FR-LCUR's full ledger is in §5 below because it is first.

| FR area | Phase | One-line goal | Non-goals (stay deferred) | Requirement refs | Deps | Gap class |
|---|---|---|---|---|---|---|
| **FR-LCUR** | 1 | L1 storage spine + `l1_curator`: `:L1*` constraints, sole-writer, `__singleton__` sentinel, `AGGREGATES` judgment envelope, `SystemKind` seed. | reified `Assignment` node (`NM-1`); service-splitting (`NM-4`); `SystemAspect` promotion engine (`NM-3`). | L1D-1/2/3/6/9/11/12/22/25 | — | net-new (mirrors `curator.py`/`schema.py`) |
| **FR-RECONREQ** | 2 | Synchronous `AnalyserReconRequest` + `request_targeted_recon` reusing `run_job` outside the phase barrier; `recon_jobs` correlation/requester/origin columns; result routed back in-process. | async dispatch + block-and-reuse (`NM-2`); unbounded scan loops (enforce a per-run cap). | L1D-26 + forward-decisions D2 | — (recon-side; may parallel FR-LCUR) | extend |
| **FR-ANALYSER** | 3 | New compiled analyser subgraph mirroring `build_pod_graph` (`configurator/gate/fail` reused; `execute→L0-slice read`, `triager→analyser LLM emitting `_L1DeltaBatch``, `curator→l1_curator`); add the `analyser` LLM role. | streaming analyser (`NM-7`); phase-2 abduction. | L1D-22/23 | FR-LCUR, FR-RECONREQ | reuse (pattern) + net-new (nodes) |
| **FR-ELICIT** | 3 | Bootstrap: operator-KB → Service skeleton (`MERGE (project_id, business_function_slug)`, no L0 refs) + linchpin authN/authZ Systems; assignment judgment writes `AGGREGATES` with envelope or falls to the stale pool. | web OSINT tool (deferred entirely); confidence-threshold numeric policy (`L1OP-5`). | L1D-4/5/12/25 | FR-LCUR, FR-ANALYSER | net-new |
| **FR-ENRICH** | 3 | Enrichment: Systems as **edges not strings** (`EXPOSED_VIA`/`FRONTED_BY`/…), `DataItem` nodes + `PRODUCES`/`CONSUMES` with assumption predicate, `SystemKind` `OF_KIND`, contract `AUTHORIZED_BY {role}` edges. | `DataRelationship` vocabulary (`L1OP-2`); `DataItem` identity key (`L1OP-1`); full runtime data-flow capture (D25). | L1D-13/14/15/16/18/21 | FR-ELICIT | net-new + blocked-on-unbuilt-dep (D25) |
| **FR-PODSTREAM** | 3 | Extend the recon pod/pipeline so every curated `AssetDelta` + triager `Observation` reaches the analyser exactly once. | streaming as the default substrate mode (batch stays default, `L1D-23`). | L1D-22/23 | FR-ANALYSER | extend |
| **FR-TEMPLATE** | 3 | Preserve the derived `endpoint_template` key on the L0 `Endpoint` / `AGGREGATES` ref at assignment. | the equivalence-class reducer engine (`NM-10`/`L1OP-7`). | L1D-32 | FR-LCUR (lands with FR-ELICIT assignment) | net-new |
| **FR-SWEEP** | 3 | End-of-phase stale-pool derived query (L0 nodes with no inbound `AGGREGATES`) + missing-systems sweep over the `SystemKind` registry. | numeric stale-pool resolution policy (`L1OP-5`). | L1D-24 | FR-LCUR, FR-ELICIT | reuse (derived query) |
| **FR-INDEXCARD** | 3 | Typed index-card projection over L1 for token-light BFS; DFS-down rides typed edges. | DFS-up via `SystemAspect` node reification (`NM-3`); downstream query shapes (`L1OP-3`). | L1D-27 / DD-4 | FR-LCUR, FR-ENRICH | net-new |
| **FR-SKILLIF** | 4 | Generalise `_load_triager_skill` → `agent/recon/skills.py::skill_for(kind\|role)`; retro-point the triager at it; anatomy node emits the triple. | the skill catalogue beyond the two seeds (`NM-9`). | L1D-31 | — (precedes anatomy skills) | extend (generalise loader) |
| **FR-SPINE** | 4 | Webpage-profile anatomy skill setting `navigation_model` ⟂ `rendering_model` as independent slots on the Steel/CDP path; classification carries confidence + verbatim evidence. | fingerprint-only inference (forbidden by `L1D-31a`); full CDP runtime-artifact capture beyond the two taps. | L1D-31/31a | FR-SKILLIF, FR-RECONREQ, FR-ANALYSER; config-gated on `STEEL_API_KEY` | net-new + blocked-on-unbuilt-dep (CDP taps) |
| **FR-AUTH** | 4 | Extend the single `auth_context` to a role/realm-tagged set via the existing `jsonb_deep_merge` append seam + a per-request selector at the injection points. | authorization-pyramid schema (`L1OP-6`). | L1D-5, L1OP-6 | — (precedes FR-AUTHZSKILL) | extend |
| **FR-AUTHZSKILL** | 4 | Authorization-pyramid anatomy skill: probe the same action under different roles, write `AUTHORIZED_BY {role}` / `AUTHENTICATED_BY {realm}` edges structurally. | risk scoring; the global-pyramid composition schema (`L1OP-6`). | L1D-31, L1D-5 | FR-SKILLIF, FR-AUTH, FR-RECONREQ | net-new |
| **FR-NFR** | cross-cutting | The invariants that span every area: sole-writer, MERGE idempotency, `identity ⊥ membership`, `__singleton__` non-null, provenance-on-write, fail-open/degrade, MVP-scope fence, traversal-then-fetch/token discipline. | — | L1D-11/22, L1R-2, curator.py:4, DD-4 | rides every area's verifier gate + one aggregate e2e | net-new (assertions) |

### Explicitly out of scope (denylisted for implementation; forward-compat only)

- **FR-INGEST content pipeline** (`POST /projects/{id}/ingest` writing `doc_chunks`) — bridge §5 defers it; not on the L1-substrate critical path. The operator KB enters via a small `settings.recon.operator_kb` field (reuses `PUT /settings` deep-merge), not the ingest pipeline. L1 nodes may carry identity-keyed anchors/`doc_ref` (that substrate piece folds into FR-LCUR).
- `NM-1` reified `Assignment`, `NM-2` async block-and-reuse, `NM-3` `SystemAspect` promotion engine, `NM-4` service-splitting, `NM-5` `DeploymentZone`, `NM-8` signature-evaluation engine, `NM-9` skill-catalogue growth, `NM-10` template reducer.
- Open points `L1OP-1` DataItem identity, `L1OP-2` DataRelationship vocabulary, `L1OP-3` query shapes, `L1OP-4` DeploymentZone, `L1OP-5` confidence/stale policy, `L1OP-6` authz schema, `L1OP-7` template equivalence relation.

---

## 4. Staged build order (front-loaded one-way doors, real dependencies)

- **Phase 0 — done:** ratify the 5 one-way doors (§1); produce this plan; seed `STATE.md` / `loop-constraints.md` / `loop-budget.md` / `loop-run-log.md`. No implementation code.
- **Phase 1 — FR-LCUR:** `db/neo4j/l1_schema.py` (constraints mirroring `schema.py`) + `agent/recon/analysis/l1_curator.py` (sole-writer, guarded MERGE builders, cross-layer-ref writer carrying the envelope) + `SystemKind` seed. Pure substrate, no reasoning.
- **Phase 2 — FR-RECONREQ:** idempotent `ALTER recon_jobs`; `request_targeted_recon` wrapping `run_job` outside the phase loop, sync `{observations}` return. Unblocks every reasoning consumer.
- **Phase 3 — analyser pod:** FR-ANALYSER → FR-ELICIT → FR-ENRICH, with FR-TEMPLATE landing at assignment, FR-PODSTREAM feeding it, FR-SWEEP + FR-INDEXCARD closing the pass. Operator-KB via the new settings field.
- **Phase 4 — skills:** FR-SKILLIF → FR-SPINE (webpage-profile) and FR-AUTH → FR-AUTHZSKILL (authorization-pyramid). Both raise backward recon via the Phase-2 executor.
- **FR-NFR** is verified continuously (every area's verifier gate) and once end-to-end via the §15 walkthrough.

Each phase is one or more FR-area goals; each goal closes only through the verifier.
Do not start a second area until the first is verifier-APPROVED.

---

## 5. FR-LCUR — full assertion ledger (the first area)

*Goal (one line):* stand up the L1 storage spine and its sole-writer `l1_curator` so every L1 node/edge is an idempotent, provenance-carrying `MERGE` on a non-null composite key, with the `AGGREGATES` judgment envelope present from day one.
*Non-goals:* reified `Assignment` (`NM-1`), service-splitting (`NM-4`), `SystemAspect` promotion (`NM-3`), any analyser reasoning (that is FR-ANALYSER).

> **§5 note — AGGREGATES encoding decision (operator-ratified, revises bridge L1D-2).**
> The bridge recommended encoding the cross-layer `AGGREGATES` reference as an L1-node property (its stated reason: a relationship cannot carry a foreign composite key cleanly).
> That rationale assumes L0 and L1 are separate stores; ratified door **D1** put both in one physical Neo4j, so a native edge to the actual L0 node is clean and needs no foreign key.
> An intermediate reified-ref-node design (option B) was implemented first, then rolled back after critical review: its only distinctive benefit (chaining services through shared L0 items to surface data flows) is unsound — shared L0 membership is undirected co-occurrence and structurally misses the cross-site producer→consumer flows the `DataItem` model (L1D-13) exists to capture, which the design already chose `DataItem` over L0-parameter-linking to get (spec §4.3).
> **Final encoding = option A:** native `(:L1Service)-[:AGGREGATES {confidence, status, evidence_refs, prov_*, ts}]->(:L0 node)`; the L0 target is MATCHed (never created here), idempotency comes from MERGE on the pattern, and resolution is one traversal hop (`l1_read.read_aggregated_l0`). This matches the spec §6 edge taxonomy and the "lazy fetch edge" of §1.3.

*Files delivered:*
- `db/neo4j/l1_schema.py` (3 L1 `CONSTRAINTS` + `INDEXES`, mirroring `db/neo4j/schema.py:7-34`).
- `agent/recon/analysis/l1_curator.py` (sole-writer; `L1_ALLOWED_LABELS`, guarded pure MERGE builders, native-edge `AGGREGATES` writer, `SystemKind` seed).
- `agent/recon/analysis/l1_types.py` (`ServiceDelta` / `SystemDelta` / `AggregatesDelta` + `JudgmentEnvelope` / `L0Ref` / `Provenance`).
- `agent/recon/analysis/l1_read.py` (traversal-then-fetch: resolve L0 via the `AGGREGATES` edge).
- `tests/test_l1_curator_builders.py` (unit, pure builders), `tests/integration/test_l1_curator_merge.py` (real Neo4j).

```yaml
# FR-LCUR assertion ledger
- id: AST-LCUR-01
  fr_area: FR-LCUR
  kind: nonfunctional
  requirement_ref: L1D-22
  statement: "Re-running the same Service L1-delta twice yields exactly one :L1Service node (idempotent MERGE)."
  tier: unit + integration
  test: tests/test_l1_curator_builders.py::test_service_merge_builder_is_pure_and_keyed
         ; tests/integration/test_l1_curator_merge.py::test_service_merge_twice_one_node
  langfuse_score: ast_lcur_01
  status: pending

- id: AST-LCUR-02
  fr_area: FR-LCUR
  kind: nonfunctional
  requirement_ref: L1D-9 + L1R-2
  statement: "discriminator defaults to the literal string '__singleton__' (never null); two singleton Systems of one kind MERGE to one node."
  tier: unit + integration
  test: tests/test_l1_curator_builders.py::test_discriminator_defaults_to_singleton_string
         ; tests/integration/test_l1_curator_merge.py::test_singleton_system_dedup
  langfuse_score: ast_lcur_02
  status: pending

- id: AST-LCUR-03
  fr_area: FR-LCUR
  kind: nonfunctional
  requirement_ref: L1D-11
  statement: "Re-running a Service delta with a DIFFERENT member set does not change the node's key or create a duplicate (identity is independent of membership)."
  tier: integration
  test: tests/integration/test_l1_curator_merge.py::test_identity_independent_of_members
  langfuse_score: ast_lcur_03
  status: pending

- id: AST-LCUR-04
  fr_area: FR-LCUR
  kind: functional
  requirement_ref: L1D-25
  statement: "Every AGGREGATES cross-layer edge carries {confidence, status, evidence_refs, provenance, ts} as edge properties; the MVP writes status='committed'; re-asserting the same assignment MERGEs to one edge (idempotent)."
  tier: unit + integration
  test: tests/test_l1_curator_builders.py::test_aggregates_edge_carries_full_envelope
         ; tests/integration/test_l1_curator_merge.py::test_aggregates_envelope_persisted_and_idempotent
  langfuse_score: ast_lcur_04
  status: green

- id: AST-LCUR-05
  fr_area: FR-LCUR
  kind: functional
  requirement_ref: L1D-2
  statement: "AGGREGATES is a native edge (:L1Service)-[:AGGREGATES]->(:L0 node) to the co-resident L0 node, resolved by one traversal hop; the L0 target is MATCHed never created (l1_curator never writes L0), and the L1 Service keeps its own (project_id, business_function_slug) key (never reuses an L0 key)."
  tier: integration
  test: tests/integration/test_l1_curator_merge.py::test_aggregates_edge_resolves_l0
         ; tests/integration/test_l1_curator_merge.py::test_aggregates_missing_l0_target_is_noop
  langfuse_score: ast_lcur_05
  status: green

- id: AST-LCUR-06
  fr_area: FR-LCUR
  kind: functional
  requirement_ref: L1D-6
  statement: "The SystemKind seed writes the 13 kinds as :SystemKind rows; a :L1System points to its kind via OF_KIND; seeding twice is idempotent (a kind is a row, not a migration)."
  tier: integration
  test: tests/integration/test_l1_curator_merge.py::test_systemkind_seed_idempotent_and_of_kind
  langfuse_score: ast_lcur_06
  status: pending

- id: AST-LCUR-07
  fr_area: FR-LCUR
  kind: functional
  requirement_ref: L1D-12 + L1D-9
  statement: "l1_schema declares l1service_unique on (project_id, business_function_slug) and l1system_unique on (project_id, system_kind, discriminator), both non-null composite IS UNIQUE, mirroring endpoint_unique (schema.py:15)."
  tier: unit + integration
  test: tests/test_l1_curator_builders.py::test_key_shapes
         ; tests/integration/test_l1_curator_merge.py::test_l1_constraints_present_and_enforced
  langfuse_score: ast_lcur_07
  status: pending

- id: AST-LCUR-08
  fr_area: FR-LCUR
  kind: nonfunctional
  requirement_ref: curator.py:4 (sole-writer)
  statement: "l1_curator is the only module that emits :L1* MERGE Cypher; a disallowed label raises ValueError (mirroring build_asset_cypher curator.py:124-125); no other module issues a :L1 write."
  tier: unit
  test: tests/test_l1_curator_builders.py::test_disallowed_label_raises
         ; tests/test_l1_curator_builders.py::test_no_other_module_writes_l1_labels
  langfuse_score: ast_lcur_08
  status: pending

- id: AST-LCUR-09
  fr_area: FR-LCUR
  kind: nonfunctional
  requirement_ref: L1D-25 (provenance-on-write)
  statement: "Every L1 node and cross-layer ref write carries provenance {job, model, prompt_id} plus first_seen/last_seen timestamps (mirroring curator.py:133-134,187-188)."
  tier: unit + integration
  test: tests/test_l1_curator_builders.py::test_writes_carry_provenance_and_timestamps
         ; tests/integration/test_l1_curator_merge.py::test_provenance_persisted
  langfuse_score: ast_lcur_09
  status: pending

- id: AST-LCUR-10
  fr_area: FR-LCUR
  kind: nonfunctional
  requirement_ref: L1D-1
  statement: "L1 nodes live under the disjoint :L1* label namespace in the same physical Neo4j; an L0 :Service and an L1 :L1Service coexist without key collision; L1 constraints target :L1* labels only."
  tier: integration
  test: tests/integration/test_l1_curator_merge.py::test_l1_namespace_disjoint_from_l0_service
  langfuse_score: ast_lcur_10
  status: pending
```

### FR-RECONREQ — full assertion ledger (the second area, DONE)

*Goal:* implement the synchronous `AnalyserReconRequest` seam (interface agreement B) so the analyser/skills can request one targeted recon job and receive the result routed back in-process. *Non-goals:* async dispatch + block-and-reuse (`NM-2`).

*Files delivered:* `agent/recon/targeted.py` (`AnalyserReconRequest`/`ReconScope`/`TargetedReconResult` + `request_targeted_recon`); `agent/app/clients/pg.py` (`ensure_recon_schema`, `record_targeted_job`, `get_job_by_correlation`, `TARGETED_PHASE`); `db/postgres/init.sql` (idempotent `ALTER recon_jobs`); `agent/app/main.py` (startup `ensure_recon_schema` + `ensure_l1_schema`); tests `tests/recon/test_targeted.py` (unit), `tests/integration/test_targeted_roundtrip.py` (integration).

```yaml
- id: AST-RECONREQ-01
  kind: functional
  requirement_ref: L1D-26
  statement: "A submitted AnalyserReconRequest runs exactly one recon job outside the phase barrier (TARGETED_PHASE=-1) and returns its result (pod exports + merged counts) to the caller in-process."
  tier: unit
  test: tests/recon/test_targeted.py::test_sync_roundtrip_runs_one_job_and_returns_observations
  langfuse_score: ast_reconreq_01
  status: green
- id: AST-RECONREQ-02
  kind: functional
  requirement_ref: L1D-26 + forward-decisions D2
  statement: "recon_jobs persists correlation_id, requester_id, origin for the targeted job; the row is retrievable by correlation_id; re-recording the same correlation_id upserts (no duplicate row)."
  tier: unit + integration
  test: tests/recon/test_targeted.py::test_registry_recorded_with_correlation_requester_origin
         ; tests/integration/test_targeted_roundtrip.py::test_registry_carries_correlation_and_is_retrievable
         ; tests/integration/test_targeted_roundtrip.py::test_registry_status_upserts_on_same_correlation
  langfuse_score: ast_reconreq_02
  status: green
- id: AST-RECONREQ-03
  kind: nonfunctional
  requirement_ref: L1D-22 + curator.py:4 (sole-writer)
  statement: "Ingesting the targeted job's assets is idempotent and flows only through the sanctioned L0 curator; re-running writes no duplicate L0 nodes."
  tier: integration
  test: tests/integration/test_targeted_roundtrip.py::test_idempotent_ingest_via_curator_no_duplicate_on_replay
  langfuse_score: ast_reconreq_03
  status: green
- id: AST-RECONREQ-04
  kind: nonfunctional
  requirement_ref: L1R (fail-open)
  statement: "A targeted-job failure (run_job raises, unknown tool, or a registry-write failure) degrades to an empty/error result and never raises into the caller."
  tier: unit
  test: tests/recon/test_targeted.py::test_run_job_exception_is_degraded_not_raised
         ; tests/recon/test_targeted.py::test_unknown_tool_is_degraded_not_raised
         ; tests/recon/test_targeted.py::test_registry_write_failure_does_not_crash_caller
  langfuse_score: ast_reconreq_04
  status: green
```

> **§ FR-RECONREQ note — Postgres runtime migration (decision taken, two-way door).** The 3 `recon_jobs` columns are applied two ways: appended to `db/postgres/init.sql` (fresh-clone baseline, per the bridge + the `last_heartbeat_at` precedent) **and** by `pg.ensure_recon_schema()` run at startup (`main.py`) + by the integration fixture. Reason: `init.sql` is mounted at `docker-entrypoint-initdb.d` and only runs on first volume init, so it never reaches the persistent dev DB or CI; the runtime ensure (symmetric with `neo4j_client.ensure_schema`) makes the live DB self-heal non-destructively. The DDL is kept in sync in both places.

### FR-ANALYSER — full assertion ledger (the third area, DONE pending verifier)

*Goal:* the analyser pod scaffolding — a compiled subgraph `f(L0-slice+obs)→L1-deltas` mirroring `build_pod_graph`, plus the dedicated `analyser` LLM role. *Non-goals:* the reasoning *content* (bootstrap/assignment/enrichment = FR-ELICIT/FR-ENRICH); `skill_for`-loaded prompt (FR-SKILLIF); streaming (`NM-7`).

*Files delivered:* `agent/app/llm/providers.py` (`analyser` in `ROLES`); `agent/recon/analysis/analyser_types.py` (`ServiceProposal`/`SystemProposal`/`AggregatesProposal` + `L1DeltaBatch` + `proposals_to_deltas`); `agent/recon/analysis/pod.py` (`build_analyser_graph` read→analyse→curate, `default_*` collaborators, `run_analyser`); tests `tests/recon/test_analyser_pod.py`, `tests/integration/test_analyser_pod_merge.py`, updated `tests/test_llm_providers.py`.

```yaml
- id: AST-ANALYSER-01
  kind: nonfunctional
  requirement_ref: L1D-22
  statement: "The analyser is f(L0-slice+obs)->L1-deltas written by idempotent MERGE through l1_curator; running it twice on the same input yields one Service/System/AGGREGATES (no duplicate)."
  tier: unit + integration
  test: tests/recon/test_analyser_pod.py::test_subgraph_flow_routes_deltas_to_curator
         ; tests/integration/test_analyser_pod_merge.py::test_analyser_writes_l1_idempotently_via_curator
  langfuse_score: ast_analyser_01
  status: green
- id: AST-ANALYSER-02
  kind: functional
  requirement_ref: providers.py:14,44-57
  statement: "The analyser is a first-class LLM role; adding it makes validate_llm_config require LLM_MODEL_ANALYSER at boot."
  tier: unit
  test: tests/test_llm_providers.py::test_analyser_role_is_registered_and_required
  langfuse_score: ast_analyser_02
  status: green
- id: AST-ANALYSER-03
  kind: nonfunctional
  requirement_ref: L1R (fail-open)
  statement: "An LLM error degrades to an empty delta batch — nothing is written and the run completes without raising; read/curate errors likewise degrade."
  tier: unit
  test: tests/recon/test_analyser_pod.py::test_llm_error_degrades_to_empty_no_write_no_crash
         ; tests/recon/test_analyser_pod.py::test_read_error_degrades_and_still_completes
         ; tests/recon/test_analyser_pod.py::test_curate_error_degrades_not_raised
  langfuse_score: ast_analyser_03
  status: green
- id: AST-ANALYSER-04
  kind: nonfunctional
  requirement_ref: L1D-25 (provenance system-controlled)
  statement: "The LLM emits proposals WITHOUT provenance; proposals_to_deltas injects system-supplied provenance (job=analyser:<run_id>) at the curate boundary, so the LLM cannot spoof provenance/status; the AGGREGATES envelope carries the LLM confidence + committed status."
  tier: unit + integration
  test: tests/recon/test_analyser_pod.py::test_proposals_to_deltas_injects_provenance_llm_cannot_set
         ; tests/recon/test_analyser_pod.py::test_proposal_models_have_no_provenance_field
  langfuse_score: ast_analyser_04
  status: green
- id: AST-ANALYSER-05
  kind: functional
  requirement_ref: L1D-22 (reads L0 slice, not re-run recon)
  statement: "The analyser reads the L0 slice via the read node (graph_read), and the read slice reaches the analyse step; default_curate_fn wires the real l1_curator."
  tier: unit
  test: tests/recon/test_analyser_pod.py::test_subgraph_flow_routes_deltas_to_curator
         ; tests/recon/test_analyser_pod.py::test_default_curate_fn_calls_l1_curator_and_assembles_counts
  langfuse_score: ast_analyser_05
  status: green
```

> **§ FR-ANALYSER notes.** (1) **Operator .env gate:** adding `analyser` to `ROLES` makes the app require `LLM_MODEL_ANALYSER=<provider>:<model>` at boot; the operator chose a dedicated role + stronger model and must set it before the next restart (tests mock the LLM). (2) **Proposal/delta split:** the LLM emits provenance-free *proposals*; `proposals_to_deltas` stamps system provenance — the same "LLM can't spoof identity/provenance" discipline as `l1_curator`'s reserved-prop stripping. (3) **Scaffolding only:** the analyser's system prompt is a minimal placeholder; FR-SKILLIF replaces it with a `skill_for`-loaded prompt and FR-ELICIT/FR-ENRICH supply the reasoning behaviours.

### Headline assertions for the remaining areas (full ledger authored at area start)
- **FR-ELICIT — DONE** (7 unit + 3 integration, `test_bootstrap*.py`). `operator_kb` = free-text (operator decision; typed template = AMV-4). `bootstrap_from_kb` elicits the Service skeleton via the analyser LLM, always ensures the linchpin `AuthenticationMechanism`/`AuthorizationSystem`, seeds `SystemKind`, writes **no L0 refs** (aggregates dropped — pure business projection), idempotent, fail-open. Bootstrap→assignment flow verified. Live smoke confirmed fail-open on a real LLM 400 (the operator's `LLM_MODEL_ANALYSER` id is currently invalid — see STATE Waiting-on-human).
- **FR-ENRICH — DONE** (15 unit + 5 integration, `test_l1_enrich_*.py`). **DataItem flexible identity** `(project_id, item_key)` — a semantic key, `identity ⊥ membership` (verified: item survives a growing `SURFACES_AT` set) (operator pulled `L1OP-1` into MVP). **Extensible DataRelationship vocabulary** — `DataRelationshipKind` catalogue (6 seeds) + one `DATA_RELATIONSHIP` edge carrying `{kind, predicate, rationale}` (`L1OP-2` resolved, `L1D-21`). `PRODUCES`/`CONSUMES` with the trust **assumption on CONSUMES** (`L1D-14`); `SURFACES_AT` native cross-layer edge (L0 MATCHed never created); systems as typed §6 edges (`L1D-18`). Analyser can propose all of it in one batch (`default_curate_with_enrichment_fn`); LLM-facing proposals carry no provenance (system-stamped).
- **FR-PODSTREAM** — every curated `AssetDelta` and `Observation` reaches the analyser exactly once; at-least-once + dedup semantics defined and tested.
- **FR-TEMPLATE** — a concrete path with a numeric/uuid segment derives `/{id}`; the template key is written at assignment and survives on the L0 ref.
- **FR-SWEEP** — the stale-pool query returns exactly the L0 nodes with no inbound `AGGREGATES`; the missing-systems sweep enumerates unrepresented `SystemKind` rows.
- **FR-INDEXCARD** — the BFS index-card carries edge-*degree* by family, never the raw member set (`DD-4` token discipline); DFS-down is one typed hop per edge family.
- **FR-SKILLIF** — `skill_for(kind|role)` loads a skill file, strips frontmatter, caches, and degrades to `""` on a missing file (mirroring `_load_triager_skill`); the triager still works retro-pointed at it.
- **FR-SPINE** — `navigation_model` and `rendering_model` are set **independently** by the webpage-profile skill; neither is inferred from the other; a fingerprint alone is never sufficient (`L1D-31a`); each classification carries confidence + verbatim evidence.
- **FR-AUTH** — multiple role/realm credentials coexist under `auth_context` via deep-merge; the right credential is selected per request; a partial PUT never wipes a sibling role.
- **FR-AUTHZSKILL** — the skill writes `AUTHORIZED_BY {role}` / `AUTHENTICATED_BY {realm}` edges structurally (not prose); mechanism (System) and policy (contract) stay separate (`L1D-5`).
- **FR-NFR** — the cross-cutting invariants hold across the whole flow; the §15 ecommerce walkthrough passes end-to-end.

---

## 6. Verifiability paradigm, observability, and definition of done

**The stop condition.** Every in-scope requirement becomes at least one assertion; every assertion becomes an executable pytest at the right tier(s) and a Langfuse score named after the ledger's `langfuse_score`; an FR area is **done iff a separate `loop-verifier` sub-agent has itself run every one of its assertions and all are green** — no disabled, skipped, or weakened checks.

**Test tiers (all three where observable).** Unit = pure builders/derivations (l1_curator MERGE/constraint builders, `__singleton__` encoding, endpoint-template derivation, `AnalyserReconRequest` contract). Integration = against the real Neo4j + pgvector containers (MERGE idempotency via `IS UNIQUE`, cross-layer ref resolution, envelope persistence, `recon_jobs` ALTER + round-trip, Langfuse emission). E2e = the spec §15 ecommerce walkthrough (bootstrap → recon L0 → assignment `AGGREGATES` → enrichment Systems/DataItems → sync `AnalyserReconRequest` round-trip → stale + missing-systems sweep → the two independent spine slots set independently).

**Observability.** Instrument each FR-area run as a Langfuse trace named by FR area (the analyser LLM inherits Langfuse callbacks once the `analyser` role is added — `providers.py:38-42`). Emit each assertion's pass/fail as a Langfuse score (name = `langfuse_score`), so the verifier's APPROVE is backed by a queryable green score set. In the debug leg, read failing traces via the langfuse skill's `references/error-analysis.md` before editing. Document-first: fetch current Langfuse docs, never implement from memory.

**Definition of done (per FR area):** verifier APPROVE with every assertion green (unit + integration + e2e where observable), Langfuse scores recorded, diff human-reviewed, `STATE.md` pruned, `loop-run-log.md` appended.
**Definition of done (MVP):** every FR area done + the §15 e2e walkthrough green + no deferred/Stage-3 machinery introduced.

## 7. Loop operating envelope

- One git worktree per FR-area attempt; discard on REJECT/escalation.
- Maker/checker: implementer sub-agent writes; a **separate** `loop-verifier` sub-agent (different instructions, ideally stronger model) runs the assertions and approves. The implementer may never mark its own work done.
- Debug via `loop-engineering/skills/minimal-fix`: reproduce → minimal root cause → smallest diff → rerun. One problem per fix. No drive-by refactors.
- Attempt cap = 3 per FR area → escalate with full context in `STATE.md` `Waiting on human`.
- No flake-masking: quarantine + escalate the infra cause; never weaken an assertion to pass it.
- Per-iteration `loop-run-log.md` entry records `{run_id, fr_area, attempt, assertions_green, assertions_total, tokens_estimate, escalations, outcome}`.
