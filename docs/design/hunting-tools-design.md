# Hunting tools design (draft)

*Status: DRAFT - not operator-locked.*
*T10b (#397) note: the orchestrator/`HuntConfig` references below are historical.*
The modeller writes the unit threat model; the hunter spec set is keyed by the threat dispatch id.
This document captures the design of the hunting module's agent tool surfaces.
It covers the shared `graph_view` tool, the store/notes contracts, the KB tool, and the 2026-10-23 description-budget policy.
The per-agent surfaces are authoritative in `docs/design/hunting-67-hunting-agent-spec.md` §8.7, `docs/design/hunting-67-threat-modeller-spec.md` §5.5, and `docs/design/hunting-67-test-executor-pod-spec.md` §1.4 and §8.12.
Where this draft and a ratified spec overlap, the ratified spec is the authority until this draft is locked.

## Tool description policy (2026-10-23)

The request tool definition is the full tool surface.
It carries the name, the top-level description, and the JSON schema.
The schema is the machine contract for every field and nested type.
The top-level description is a dense usage projection, not a second schema.

The top-level description carries only:

- the purpose;
- the operation or command semantics;
- the hard constraints;
- the coded error envelope;
- the one or two clauses a wrong call would lose.

Field-level detail belongs in the pydantic field descriptions.
A role prompt carries a complete high-level tool summary, never a second description body.

Shared descriptions live in one module and are imported by every binding.
The shared constants are:

- `load_skill` and `record_skill_lesson` in `app/llm/skills.py`;
- `graph_view` in `attack/hunting/graph_view_tool.py`;
- `query_lightrag` in `lightrag/tool.py`;
- the HTTP read pair in `attack/hunting/http_history_contract.py`;
- the auth-store read contract in `app/auth/tool.py`;
- the suite pair in `attack/hunting/threat_modeller_tools.py`.

The role-local descriptions are the hunter and modeller `hunts_store` seams, the pod `exec` seam, and the pod note seam.
The conciseness directive is shared through `attack/hunting/conciseness.py`.

The hunter's 12 top-level descriptions are bounded at 8,500 chars.
The current committed total is 8,478 chars.
The critical-clause test is `tests/attack/test_tool_description_budget.py`.

### The sharing measurement

The description metric is `sum(len(tool.description))` over the bound surface.
It includes the shared conciseness directive where a tool appends it.
It is not the request-schema character count.

| Role | Before | After, same full auth | Description text cut | Auth-mode cut | Production after | Total cut |
|---|---:|---:|---:|---:|---:|---:|
| Hunter | 22,775 | 13,127 | 9,648 | 4,649 | 8,478 | 14,297 |
| Modeller | 18,594 | 11,499 | 7,095 | 4,649 | 6,850 | 11,744 |
| Runner | 12,979 | 9,750 | 3,229 | 4,649 | 5,101 | 7,878 |
| Triager | 12,715 | 9,486 | 3,229 | 4,649 | 4,837 | 7,878 |

The `After, same full auth` column isolates the shared description compaction.
The `Auth-mode cut` column is the full-to-read-only auth-store switch.
The full auth-store description remains 5,291 chars.

The shared text cut is the sum of the tools a role binds.
It is not four independent edits.
The modeller's cut is 7,095 shared text plus 4,649 auth mode.
The runner and triager receive the same 3,229 shared text cut and the same auth-mode cut.

`replay` is bound only when the runner has a replay seam.
Its description fell from 2,161 to 1,718 chars, a 443-char cut.

The threat tool surface is removed.
The first human message carries the application and loop context, not a second tool catalog.
The compaction pin keeps that context through a fold.

The cache accounting is in `docs/design/session-cache-measurement-348-adr.md`.
Removing cached fixed text lowers occupancy but can raise the miss share.
The hunter is the exception because the threat surface was uncached.

The decision record is `docs/design/hunting-context-dedup-2026-10-23-adr.md`.
The impact map is `docs/design/hunting-context-dedup-impact-map.md`.

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

*Superseded in part by #293: the coded teaching rejection and the tool binding
are now single-sourced in `app.memory.tool_contract` (originally
`attack/hunting/tool_contract.py`; lifted to the shared app module by the
service-sourced-analysis lift, T1, with the historical path kept as a thin
re-export), the orchestrator closures migrated
to the same discipline, and `notes` is ONE shared implementation - see the #293
section below. The `NoteProvenance` typed slot and the hunter/pod data contracts
recorded here remain in force.*

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

### HuntsStoreArgs (hunter `hunts_store` tool) - F-015 correction (2026-10-21)

**No store-writing tool exposes an open JSON object.** Every persisted object is
a pydantic model with `extra="forbid"`, every field carries a description, and
required versus optional is explicit in the schema. Nested objects reuse the
canonical read-side model, so the write schema and the stored record cannot
drift. The JSON schema sent in the request's `tools` body is the contract the
model evaluates; it is never prose the model must translate into an ad-hoc
object.

- `command` stays REQUIRED with the SAME coded teaching rejection on omission.
- `SpecWrite` is the typed write payload: `status`, `fault_keyword`,
  `strategy_keyword` and `target_identity` are REQUIRED; the remaining fields
  are optional and described. `target_identity` is the shared
  `spec_contract.TargetIdentity`; `provenance` is the typed
  `spec_contract.SpecProvenance` (including the typed `SkillProcedure`). The
  earlier `extra="allow"` tail is retired: `spec_id` and any invented field are
  rejected, because the pod's canonical `TestImplementationSpec` is
  `extra="forbid"` and never persisted them.
- Missing required fields and unknown fields are CODED teaching rejections
  naming the offending path and the accepted required/optional set, so a model
  self-corrects instead of decoding a bare pydantic error.

The same rule applies to the modeller's `hunts_store`: its `sections` payload
is the typed `threat_model.ModelSections`, not an open mapping. `notes` and the
pod `note` already carry typed sub-models; they inherit the shared missing/
unknown-field rejection through `StoreToolBase`.

### NoteToolSpec (pod `note` tool)

- `operation: str = "write"` already defaults to write (a tolerated
  discriminator); the SAME coded teaching rejection applies to a malformed
  call so the pod loop self-corrects instead of degrading silently.

### #293 - the shared contract base and the orchestrator migration (SUPERSEDES the #209 disposition)

*Status: DRAFT (records the #293 disposition; the authoritative spec sections
are `hunting-orchestrator-candidates-rewrite-spec.md` §3.4,
`hunting-164-state-graph-spec.md` §5/§6, and
`hunting-67-test-executor-pod-spec.md` §2, amended by the same change).*

#209 fixed the hunter and pod seams but left the orchestrator's `hunts_store` /
`notes` as prose-only `@tool` closures with an INFERRED schema and no coded
rejection; an empty-argument call surfaced a bare `1 validation error for
hunts_store` (#286). That disposition is now SUPERSEDED, and the discipline is
single-sourced:

1. **One shared contract module** (`app.memory.tool_contract`, lifted from
   `attack/hunting/tool_contract.py` by the service-sourced-analysis lift, T1):
   - `coded_teaching_rejection` - the shared translation of a known
     schema-drift `ValidationError` (a missing required discriminator, or an
     out-of-enum value) into the coded JSON rejection naming the discriminator
     and the known commands. The hunter's local `_coded_teaching_rejection`
     copy and `_WRITE_INTENT_FIELDS` are REMOVED.
   - `StoreToolBase` - the shared binding base: it validates through the tool's
     own `args_schema` (the ONE args model), translates the known drift before
     the turn sees a raise, and dispatches read/write on the declared
     discriminator. Every store tool (orchestrator, hunter, pod) rides it; the
     pod keeps its OWN `NoteToolSpec` contract but uses the shared
     binding/rejection base.
   - `StoreNotesTool` / `build_notes_tool` - ONE `notes` implementation bound
     at the orchestrator and hunter seams through a caller-bound
     `NotesStoreHandle` and an explicit `NotesFieldMap`. The map names the
     semantic fields of the bound schema and is validated at construction, so a
     read cannot silently treat a write field as its filter; the filesystem
     destination (orchestrator `memory.yaml` via `HuntStore`, hunter
     `notes.yaml` via `HunterMemoryStore`) is derived from the HANDLE, never a
     request field.
   - **Scope of the sharing for `hunts_store`.** Only the BINDING is shared:
     the typed `args_schema` + `StoreToolBase`'s read/write dispatch + the coded
     teaching rejection. The write algorithm itself is necessarily per-store
     (the orchestrator upserts a `HuntConfig` through `HuntStore` with the G4
     dedup gate and the G1 phase verbatims; the hunter writes a spec through
     `HunterMemoryStore`), so it stays in each seam's `_read` / `_write`. #293
     does NOT abstract the two store write paths into one body.
2. **Typed orchestrator schemas.** `OrchestratorHuntsStoreArgs` /
   `OrchestratorNotesArgs` are pydantic `BaseModel`s with `extra="forbid"`,
   every field a `Field(description=...)`, and the discriminators as `Literal`
   (`cmd: Literal["read","write"]`, `option` a `Literal` enum). The JSON schema
   emitted by `convert_to_openai_tool` therefore carries the enums and the
   descriptions - the old `"cmd": {"type":"string"}` cannot recur.
3. **Uniform rejection.** `hunts_store.invoke({})` / `notes.invoke({})` return
   the coded teaching rejection naming `cmd` and the known commands - never a
   bare pydantic error. The orchestrator keeps exactly the three tools
   (`hunts_store` / `notes` / `graph_view`); the `hunts_store` write algorithm
   (`hypothesised` create / `ratified` / `dropped` upsert, the G4 dedup
   signal, the G1 phase-transition verbatims) is unchanged in behaviour, only
   re-homed into a typed `BaseTool`. The hunter's production note binding goes
   through `notes_tool_for` (the named `build_notes_tool` path).

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

3. **Args-contract drift (#322)** - the hunter carried a stale local
   `KbQuerySpec` mirror of `QuerySpecV1` that lacked `expected_no_hypothesis`,
   while the shared usage skill (`skills/lightrag-query/SKILL.md`) documented
   the real contract; every hunter `kb_query` that passed the documented
   field degraded to the `tool_failed` fallback (run `09c0f4c8`). The fix
   RETIRES the local args mirror: the hunter tool binds the real
   `lightrag.query_spec.QuerySpecV1`, the same contract the pod wrapper and
   the real tool bind, and the canonical description appends the field list
   read from `QuerySpecV1.model_fields`. The schema, the description, and the
   skill field list are now single-sourced; a regression test pins the
   agreement. See `docs/design/kb-query-contract-322-adr.md`.

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
  Its 2026-10-23 description is a dense usage projection that points at the shared target-front 5xx rule in the role prompt.
- The orchestrator's `hunts_store` / `notes` closures MIGRATED into the shared
  module (`app.memory.tool_contract`, originally `attack/hunting/tool_contract.py`)
  as of #293 - see the #293 section above. The
  orchestrator now uses the same typed-schema + coded-teaching-rejection
  discipline as the hunter and pod, and the `notes` implementation is shared
  through a caller-bound store handle.