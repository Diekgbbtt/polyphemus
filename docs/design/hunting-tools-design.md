# Hunting tools design (draft)

*Status: DRAFT - not operator-locked.* This document captures the design of the hunting module's agent tool surfaces. It is intentionally incomplete: as of this revision it covers ONLY the `graph_view` tool (the surface changed by #197); the other tools (`hunts_store`, `notes`, `kb_query`/`query_lightrag`, `exec`, `note`) are future sections and are NOT redesigned here.

The authority for the tool-surface contracts that already exist is the per-agent lineage: `docs/design/hunting-orchestrator-candidates-rewrite-spec.md` §3.4 (the orchestrator's `hunts_store` / `notes` / `graph_view` surface), `docs/design/hunting-164-state-graph-spec.md` (the hunter's five-tool surface), and `docs/design/hunting-67-test-executor-pod-spec.md` (the pod's `exec` / `note` / `query_lightrag` surface). Where this draft and a ratified spec overlap, the ratified spec is the authority until this draft is locked.

## Why a tools design exists (the gap)

The hunting module binds a tool surface at THREE agent seams - the orchestrator, the hunting agent, and the test-executor pod - and `graph_view` is the one tool all three share. Before #197 the tool existed in two divergent implementations: the orchestrator's `@tool graph_view(cypher, params)` (`attack/hunting/actors.py`) and the hunter's `GraphViewTool(BaseTool)` (`attack/hunting/hunter_tools.py`), which disagreed on the argument name (`cypher` vs `query`), the return shape (dict vs JSON string), the description, and the location of the read-only guard. Neither description carried the usage contract, so no agent had a contract to query against. This design resolves that by making `graph_view` ONE shared tool with a single-source contract, bound at all three seams.

## graph_view (the single shared read-only L0/L1 view tool)

### 1. Shape (operator-locked via the #197 grilling)

- **One tool, three bindings.** A single tool implementation lives in ONE shared module; the orchestrator surface, the hunter tool surface, and the pod's runner+triager surfaces all bind it. `GraphViewTool` (the hunter's `BaseTool` subclass) is REMOVED.
- **Argument name: `cypher`.** Matches `ReadOnlyGraphView.read`'s `(cypher, params)` signature; the hunter's divergent `query` argument dies.
- **Return shape: `{"rows": [...]}`.** The orchestrator's plain-dict shape; the hunter's JSON-string convention dies. A failure degrades to `{"error": ...}` (fail-open, O5) - never a raise into the turn.
- **Construction: a factory** in the tool's home module, taking the read-only seam (`ReadOnlyGraphView(project_id).read` or an injected equivalent) and returning the bound tool.
- **Read-only guard: single-sourced** in the same module (the `_WRITE_SHAPED` token regex). The underlying `ReadOnlyGraphView.read` guard remains as defense-in-depth; the tool-level guard is the shared single source both the orchestrator and the pod/hunter paths ride.
- **Row caps: none** (operator ruling, #197 Q6). The contract documents the `LIMIT` discipline; the tool enforces no truncation.

### 2. The usage contract (single-sourced, imported + interpolated at every binding)

The contract is a single constant rendered into the tool's description, so no agent receives a divergent contract. It covers:

**Schema** - derived from the live enums in `analysis/l1_curator.py` so it cannot drift:
- node labels: `L1Service` / `L1System` / `L1DataItem` (L1), `Endpoint` / `Parameter` / `BaseURL` / `Header` (L0);
- cross-layer rels: `AGGREGATES` (`(:L1Service)-[:AGGREGATES]->(:L0)`), `SURFACES_AT` (`(:L1DataItem)-[:SURFACES_AT]->(:L0)`), `EVIDENCED_BY` (`(:L1System)-[:EVIDENCED_BY]->(:L0)`);
- data-flow rels: `PRODUCES` / `CONSUMES`;
- the System-edge taxonomy (`SYSTEM_EDGE_RELS`);
- key identity properties (a Service's `business_function_slug`; a System's `kind` + `discriminator`; an Endpoint's `path` / `method` / `baseurl` with the full URL in `url`; a Parameter's `name` / `position`).

**Query-language primitives** - the read-only Cypher subset the agent may use: `MATCH`, `OPTIONAL MATCH`, `WHERE`, `RETURN`, `ORDER BY`, `LIMIT`, `DISTINCT`, `labels()`, `type()`, `properties()`, relationship patterns `(a)-[:REL]->(b)`, `collect(...)`, and `$param` parameter syntax. Write-shaped tokens (`MERGE` / `CREATE` / `DELETE` / `SET` / `REMOVE` / `FOREACH` / `LOAD CSV`) are refused.

**Read-only guard** - write-shaped cypher is rejected; `ReadOnlyGraphViewError` surfaces to the model (orchestrator path) / a denoted error (hunter+pod paths); never a write.

**Return shape** - `{"rows": [...]}` on success; `{"error": ...}` on absence/misconfiguration/failure.

**At least one worked example** - a read-only query traversing `Service -> AGGREGATES -> Endpoint -> HAS_PARAMETER -> Parameter` (or the equivalent), showing the agent how to navigate from an L1 unit down to its observed attack surface.

### 3. Bindings

- **Orchestrator** (`attack/hunting/actors.py`): the shared tool replaces the local `@tool graph_view` closure; the contract is interpolated into its description.
- **Hunter** (`attack/hunting/hunter_tools.py`): `GraphViewTool` is removed; `build_hunter_tools` binds the shared tool over the injected `graph_view_fn` seam.
- **Pod** (`attack/hunting/pod/agents.py`): the shared tool is bound into the Runner's `runner_react_tools` AND the Triager's `triager_react_tools`, always-on, threaded via the pod harness context (`ReadOnlyGraphView(project_id).read`).

## Open / not yet designed

- The other tools' contracts (`hunts_store` / `notes` / `kb_query` / `exec` / `note`) - future sections of this draft.
- Whether the orchestrator's `hunts_store` / `notes` closures migrate into this shared module.