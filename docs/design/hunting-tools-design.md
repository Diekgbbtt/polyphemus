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

## The store/notes tool contracts: typed structure + coded teaching rejection (#209)

*Status: DRAFT (records the #209 disposition; the authoritative spec sections are
`docs/design/hunting-164-state-graph-spec.md` §5/§6 and
`docs/design/hunting-67-test-executor-pod-spec.md` §2, amended by the same change).*

The store-writing tools (`hunts_store` / `notes` on the hunter surface,
`note` on the pod surface) share a contract pattern. The #209 defects surfaced
two ways the pattern drifted, and the fix is a shared contract discipline for
all three tools:

1. **Each parameter's typed structure rides the tool-calling protocol's own
   schema** (the JSON schema `convert_to_openai_tool` sends in the request's
   `tools` body), never prose-only description. A parameter the code itself
   writes must be a typed sub-model with the SAME field set, so the schema and
   the store-writer's record cannot drift. The one exception is a genuinely
   arbitrary parameter (the hunter's `spec` dict - the author adds arbitrary
   fields by design); it stays untyped.
2. **A required discriminator stays required.** When the model emits a call
   that omits it (write-intent fields present but no `command`, or a parameter
   of the wrong type), the tool returns a CODED teaching rejection - a JSON
   error object with a machine code (mirroring `fault_key_mismatch` /
   `duplicate_spec` / `invalid_args`) and a detail that names the exact fix -
   instead of the generic validation error. The model self-corrects on the
   retry instead of burning the turn on a bare `tool_failed`. This refines the
   D84-22 canon (the tool's OWN contract is the validator): a wrong parameter
   still FAILS as a rejected call, but the rejection TEACHES the correction.

### NotesArgs (hunter `notes` tool)

- `command: Literal["read","write"]` stays REQUIRED. `action` (the write
  option) is NOT the command: a write call must carry `command="write"` with
  `action` in `append|update|delete`. A call with write-intent fields
  (`action` / `fault_key` / `note_name` / `body`) but no `command` returns the
  coded rejection teaching `command="write"`.
- `evidence: str|None` stays PROSE. `provenance` is the structured slot and
  becomes a TYPED `NoteProvenance` sub-model with `extra="forbid"`:
  `source: str=""` (the design-pinned pod-session-id home, spec §6), `run_id:
  str=""`, `verdict_stub: bool=False` (the surfer's durable-export trio,
  `surfer.py::_record_durable_pod_export`) plus `probe_refs: list[str]=[]`
  (the model's structured evidence refs, e.g. `exec:SPA shell`, ratified by
  #209). A residual dict-valued `evidence` call returns the coded rejection
  teaching that structured refs go in `provenance` and `evidence` is prose.

### HuntsStoreArgs (hunter `hunts_store` tool)

- `command` stays REQUIRED with the SAME coded teaching rejection on omission.
- `spec: dict` stays UNTYPED (design intent: the author adds arbitrary fields).

### NoteToolSpec (pod `note` tool)

- `operation: str = "write"` already defaults to write (a tolerated
  discriminator); the SAME coded teaching rejection applies to a malformed
  call so the pod loop self-corrects instead of degrading silently.

## The `kb_query` / `query_lightrag` tool (#207): one canonical description + per-stage observability

*Status: DRAFT (records the #207 disposition; the authoritative tool contract is
`lightrag/tool.py` and the pipeline contract is
`docs/design/lightrag/lightrag_design_doc.md`, amended by the same change).*

The KB tool is the LightRAG **testing-methodology** knowledge base (WSTG +
writeup overlays), surfaced at two agent seams - the hunter's author-lane
`kb_query` (`attack/hunting/hunter_tools.py`) and the pod's
`query_lightrag` (`attack/hunting/pod/tools.py`) - both wrapping the real
`query_lightrag` tool (`lightrag/tool.py`). Two #207 defects shaped this
design:

1. **Wrong "fault KB" framing** - the tool was framed as a "fault knowledge
   base" and its descriptions drifted (pod said "one ontology entity",
   hunter listed config fields). The fix: ONE canonical description constant,
   `QUERY_LIGHTRAG_DESCRIPTION` in `lightrag/tool.py`, imported verbatim by
   all three description sites so it cannot drift. The description frames the
   KB **positively** - it retrieves the ontology's methodology concepts
   (technology stack, attack technique, payload pattern, artifact, observable
   signal, vulnerability class, attack goal, attacker capability, precondition
   environment, defensive control - the real `ENTITY_TYPES`) - and never
   invites using the KB to verify or adjudicate a bug. The prompt bullet
   (`{KB_TOOL}` at both pod prompt sites) is the same neutral pointer +
   trigger-line signature, zero overlap with the description.
2. **Observability black-box** - the pipeline's inner stages (retrieval,
   generation, validation) were untraced plain httpx; KB answers were not
   auditable. The fix records, per call, per-stage Langfuse observations via
   `lightrag/observability.py` (grey pt 6: the SDK primitives, reusing the
   wiring in `app/observability/langfuse_tracing.py` - raw OTel tracer scopes
   are dropped by the SDK export filter, see
   `docs/design/observability-recipe.md`). See
   `docs/observability-langfuse.md` and the lightrag design doc for the
   observation details.

### The author-lane recording seam (grey pt 8)

The hunter has no D6 log, so its author-lane `kb_query` reads land a
KbObservation-equivalent artifact **as observation metadata** (never a filesystem
artifact): a `kb_observation` observation per call recording the query + scenario
id as input and the returned entity names + provenance references as metadata
(`lightrag/observability.py::kb_observation_span`,
`hunter_tools.py::KbQueryTool._run`). The pod lane keeps its D6-log
`KbObservation` recording (`pod/tools.py::_record`, T3/#179) - that lane has a
log, so its observation metadata is the same shape for consistency.

## Open / not yet designed

- The `exec` tool contract (`exec` remains a partially future section).
- Whether the orchestrator's `hunts_store` / `notes` closures migrate into this
  shared module. The orchestrator closures (`actors.py::hunts_store` /
  `::notes`) already use a required positional `cmd` + a coded `unknown cmd`
  rejection - a stricter contract than the hunter's - and are left as-is by
  #209.