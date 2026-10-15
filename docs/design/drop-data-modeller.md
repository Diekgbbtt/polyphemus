# Drop the data_modeller proposer and the analysis L1 DataItem substrate

Status: accepted.
Date: 2026-10-15.
Supersedes: `docs/design/dataplane-A1-decisions.md` (the DataPlane Analyser A.1 design).
Scope: the `analysis` bounded context only.
Branch: `feat/drop-data-modeller` (off `dev`).

## Decision

Remove the `data_modeller` proposer COMPLETELY, and with it the analysis-owned L1
`DataItem` substrate it fed.
Nothing will ever write a `DataItem` again, so the proposal shapes, the curator
writers, the inventory reads, the prompt renders, the census counter and the role
registration all go too.
This is a full removal, not a proposer-only retirement.

The read-only consumers of the L1 data axis in the **hunting** context
(`attack/hunting/unit_projection.py`, `llm.py`, `hunt_orchestrator.py`,
`graph_view_tool.py`, `predicate.py` and their tests) are OUT OF SCOPE for this
change: they read a node type that analysis no longer writes, and they are a
separate track.
The shared vocabulary they import from `analysis.l1_curator` is therefore RETAINED,
not deleted (see "Retained" below).

## Why now

The data plane was a Tier-1 trust substrate lifted from streamed
`Parameter`/`Header`/`Secret` surface.
Its output was never consumed into a decision that justified its cost: the
proposer, its prompt, its two-call reflection/extraction turn and its shaping
gates were the last of the chunk-fed roles, and the operator has decided the model
will not carry logical data records.
With no writer, every reader is dead code and every write path is a dormant seam.

## Impact map (the grep of PHASE 1)

Tokens grepped across `src/`, `tests/`, `eval/`, `docs/`:
`data_modeller`, `DataModeller`, `DataItem`, `SURFACES_AT`, `CONSUMES`,
`PRODUCES`, `DataRelationship`, `data_flows`, `surfaces_at`, `data_items`,
`data-plane`, `dataplane`.

Removed (analysis):

- Proposer and wiring: `analysis/data_modeller.py`, `analysis/prompts/data-plane.md`.
- Role registration: the `ROLE_ADMITS["data_modeller"]` entry and the `CHUNK_ROLES`
  entry in `chunking.py`; the `data_modeller` member of `messages.Role` and
  `PROPOSER_ROLES`; the `_role_prompt` branch and its KeyError trio message and the
  `_role_structured_schema` tuple in `proposer_turn.py`; the `data_modeller` role in
  `app/llm/providers.ROLES`; the `data_modeller` entry in `app/llm/skills.ROLE_SKILLS`.
- Supervisor: the `data_modeller_invoke_fn` and `aggregations_fn` seams, the
  `make_data_modeller_body`/`dm_stateful_invoke_fn` imports, the proposer body, the
  schedule role, the admitted-parameter/header observe metadata, the
  `analyse-data-plane` Langfuse tag, and the `PassCensus.data_items_written` counter.
- Type shapes: `DataItemDelta`/`SurfacesAtDelta`/`DataFlowDelta`/`DataRelationshipDelta`
  in `l1_types.py`; `DataItemProposal`/`SurfacesAtProposal`/`DataFlowProposal`/
  `DataRelationshipProposal` and the four `L1DeltaBatch` lists in `analyser_types.py`.
- Curator: `build_dataitem_cypher`/`build_surfaces_at_cypher`/`build_data_flow_cypher`/
  `build_data_relationship_cypher`, `_l0_match_clause`, and the data kwargs/writes of
  `enrich`.
- Inventory and renders: the `L1DataItem` read and the `data_items`/`data_item_fields`/
  `data_item_notes` keys of `read_l1_inventory`; the DataItem render in
  `pod._inventory_block`; the data lines in `curation` and `sweep` prompts; the
  `data_flows`/`surfaces_at` shell slots in `bootstrap`; the `L1DataItem`/`SURFACES_AT`/
  `CONSUMES`/`PRODUCES` vocabulary in `graph_tools._SCHEMA`; the DataItems/CONSUMES
  docstring refs in `index_card.py` and `l0_stream.py`.
- Tests: `tests/analysis/test_data_modeller.py`,
  `tests/integration/test_data_modeller_contracts.py`,
  `tests/e2e/test_data_modeller_walkthrough.py` (deleted); every other test that
  named the role or the removed shapes (updated).

Retained (analysis, for the out-of-scope hunting read-only projection):

- `l1_curator.DATA_RELATIONSHIP_KINDS` and `l1_curator._DATA_FLOW_RELS`, imported by
  `attack.hunting.unit_projection` / `predicate` / `fault_source` / `graph_view_tool`.
- `l1_curator.L1_RECONCILE_LABELS` still includes `"L1DataItem"`, which
  `attack.hunting.graph_view_tool` reads to build its schema hint.
- `l1_curator._REPOINT_REL_TYPES` keeps the data edge labels for legacy merge re-point.

These are vocabulary constants, not write paths; they are commented as retained.
The hunting and recon readers of the now-unwritable substrate carry a one-line
`# RETAINED (dormant legacy ...) -> docs/design/drop-data-modeller.md` marker at the
point of read (`attack/hunting/{unit_projection,predicate,fault_source,graph_view_tool,llm,hunt_orchestrator}.py`,
`recon/domain/graph_read.py`).
`l1_curator.vocabulary_prompt()` no longer renders the DataRelationship kind catalogue
into the live proposer prompts: nothing can emit one.

## The fork-H guarantee holds with two roles

The `ADMIT_ALL` sentinel is KEPT, and the generalist role is still the
mechanism-typist.
The original argument was that with per-role allow-sets an asset type no role names
would be admitted by nobody and silently dropped, losing the fork-H guarantee.
That argument is unchanged by dropping the data-modeller: the admission table is now
`{assigner: Endpoint, mechanism_typist: ADMIT_ALL}`, so every asset type a recon job
produces is still admitted by the generalist.
`admit_for_role` still returns nothing for an unknown role, so a new role must
declare itself.
The guarantee is therefore preserved with two roles, and the `ADMIT_ALL` comment was
reworded from "three allow-sets" to "more than one allow-set".

## Left to the coordinator

- `src/polymerhus/analysis/CONTEXT.md` is NOT edited here (coordinator applies it at
  merge): its DataPlane Analyser, Observed-only fields, Grounded DataItem, DataItem
  notes, Ground-vs-Withhold, Chunk feeding and Proposer decomposition sections must be
  revised or removed in the same change.
- `docs/design/domain-model.md`, `recon/CONTEXT.md` and `docs/design/l1-domain-model-catalogue.md`
  still narrate the DataItem layer; they should be revised with the model update.
- The vestigial `"data_items": []`/`"data_flows": []` keys in
  `assigner.narrow_to_assignment` and `mechanism_typist.narrow_to_typing` are
  harmless (`model_copy` ignores unknown keys) and were left untouched to respect the
  scope guard on those two files' shaping logic.
- Other tracks own `assigner.py` / `mechanism_typist.py` (their `:91` / `:77` comment
  refs) and `tests/integration/test_assigner_contracts.py:32` /
  `tests/e2e/test_assigner_walkthrough.py:26` (vestigial inventory dict keys); the
  coordinator resolves those at merge.

## Consequences

- The chunk-fed analyser is a two-role schedule: `assigner -> mechanism_typist`.
- `analyse_chunked` no longer takes `data_modeller_invoke_fn` or `aggregations_fn`.
- `enrich()` and `enrichment_proposals_to_deltas()` carry only `system_edges`.
- No analysis write path can create a `:L1DataItem`, a `SURFACES_AT`, a `PRODUCES`/
  `CONSUMES` flow or a data-relationship edge.
- The hunting rich projection renders empty data slots on any graph analysed after
  this change; that is a known, accepted consequence of the substrate removal and the
  subject of the separate hunting track.
