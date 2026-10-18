# The `EVIDENCED_BY` writer for the mechanism-typist (ticket #354)

*Grill record and the decisions the fix encodes.
The ticket: the mechanism-typist grounds every System in observed evidence but never writes the cross-layer edge, so `EVIDENCED_BY` only ever appeared through the reconcile relabel remap (`l1_curator._RELABEL_EDGE_REMAP`, a mis-typed Service re-kinded to a System).*

## 1. What the fix adds

The typist proposes, per System, the L0 nodes whose observation witnesses the claim.
The sole-writer MATERIALISES one `(:L1System)-[:EVIDENCED_BY]->(:L0)` edge per witness it can MATCH.

Pipeline: `mechanism_typist.type_mechanisms` (systems-extraction call) -> `SystemProposal.evidence`
-> `analyser_types.enrichment_proposals_to_deltas` -> `l1_curator.SystemEvidenceDelta`
-> `l1_curator.build_system_evidence_cypher` (pure) -> `l1_curator.enrich` (impure, fail-open per item).

## 2. The decisions

### Q1 - Which L0 node kinds count as a witness?

A witness is an L0 node a tool OBSERVED, never a prose note and never an `Observation` node.

**Decision.** The witness labels are a fixed, single-sourced allowlist: `EVIDENCE_L0_LABELS = ("Endpoint", "BaseURL", "Header", "Technology", "Certificate")`.

- `Header` / `Technology` / `Certificate` are the ticket's named fingerprint evidence, and `sweep.DEFAULT_ASSIGNABLE_LABELS` already classes them as "System EVIDENCED_BY evidence, not Service members".
- `Endpoint` is the carrier of the recorded-transaction witness: the HTTP history is NOT materialised into L0 (`2026-10-17-gt-wellformedness-outcome-assessment.md` D-3, "The L1 contract cannot reference them"), so the only L0 node a transaction can witness through is the Endpoint it was recorded against. An `exec`-read JS artefact (a `.js` path) is an Endpoint too.
- `BaseURL` is the broad host-level surface element (a redirect shape, a same-origin policy) and the anchor the triager itself uses.
- REJECTED: `Domain` / `Subdomain` / `IP` / `Port` / `Service` - the chunk FILTER drops these connectivity types before any proposer sees them, because they are how the target is REACHED, not surface (`CONTEXT.md`, "Chunk-builder"; the 2026-10-15 arm-H decision). Re-admitting them as witness targets would re-import the mechanism noise that gate removed.
- REJECTED: `Parameter` (the surface is a known-broken carrier, #366/#367) and `Secret` (a value, not a surfaced mechanism).
  Extending the set later is a one-line data edit in `l1_curator`, exactly like `SYSTEM_KINDS`.
- REJECTED: the `Observation` node. An Observation is the triager's own claim, anchored UP to a broad asset; the witness is the asset it is anchored to. EVIDENCED_BY grounds a judgment in the OBSERVED store, not in another judgment read.

Semantics unchanged from the catalogue (`l1-domain-model-catalogue.md` §5.1): `L1System -> L0 node`, provenance and timestamps only.

### Q2 - How does the typist express the witness in its proposal?

**Decision.** A typed `evidence: list[L0Ref]` field on `SystemProposal` - the domain's OWN L0 reference shape (`{label, identity}`), the identical type `AggregatesProposal.l0` already uses - carried by the systems-extraction call (the call that owns a System's attributes), never by the linking call (which owns `system_edges` only).

- Free text is not writable as an edge: the label + identity map is what the writer MATCHes on.
  The adversarially-oriented `description` prop remains the human-readable carrier; `evidence` is the machine-readable one.
- `L0Ref.identity` carries the L0 node's own keys, single-sourced to `l0_stream.L0_IDENTITY_KEYS`
  (`Endpoint` path/method/baseurl, `Header` name/endpoint/baseurl, `Technology` name/version,
  `Certificate` subject_cn, `BaseURL` url).
  The proposer emits the keys the node ACTUALLY carries (method-blind recon mints Endpoints with no `method`), never a null placeholder.
- `_merge_systems` UNIONS the witness sets of the two structured calls (deduped), rather than the primary-wins rule it applies to scalar props: each witness independently licenses the claim and the edge MERGE is idempotent, so a witness the co-producing call named must not be silently dropped (the co-produced-Systems ruling of 2026-10-16 in spirit).
- `drop_unknown_vocabulary` (the shaping gate that guarantees the proposer emits only writer-acceptable values) also drops witnesses whose label is outside `EVIDENCE_L0_LABELS`.

### Q3 - The curator write semantics

**Decision.** `build_system_evidence_cypher` + the `enrich` writer, mirroring `build_aggregates_cypher` / `write_aggregates` exactly:

- `MATCH (l0:<label> {identity keys}, project_id: $project_id)` - the L0 node is **MATCHed, never MERGEd**, so `l1_curator` can never mint an L0 node (the ACL of CODING_STANDARD §2).
- **An unmatched witness degrades without an edge**: a MATCH that finds nothing makes the whole statement a no-op. No crash, no fabricated node, no error surfaced.
- `MERGE (sy:L1TestableUnit:L1System {kind, discriminator, project_id})` with provenance `ON CREATE` (mirrors `build_system_edge_cypher`), so the edge write is self-sufficient and the node its own primary writer already made keeps its own provenance.
- `MERGE (sy)-[r:EVIDENCED_BY]->(l0)`: idempotent on re-emission; `first_seen` ON CREATE, `last_seen` refreshed, `prov_job`/`prov_model`/`prov_prompt_id` stamped. NO judgment envelope - the §4.3 asymmetry is a deliberate ontological commitment (assignment is graded, fingerprinting is not).
- `__singleton__` Systems are INCLUDED (no special case): the discriminator defaults to the sentinel exactly as in every other System writer, and a discriminated System (a per-cluster `WebPresentation`) carries its own witnesses.
- Guards: an unknown `kind`, a label outside `EVIDENCE_L0_LABELS`, an unsafe/empty label or identity key, or a NULL identity value raises `ValueError`; the impure loop skips+logs that item and continues (fail-open, per item).
  An EMPTY-STRING identity value is legitimate L0 identity (both parsers write a Technology's `version` as `""`), so only null is refused - the TDD loop caught the stricter first draft dropping every Technology witness.
- The **relabel remap path is untouched**: `_RELABEL_EDGE_REMAP[("L1Service","L1System")] == {"AGGREGATES": "EVIDENCED_BY"}` and `EVIDENCED_BY` stays in `_REPOINT_REL_TYPES`. The new writer is additive.
- Write ORDER: the evidence rides the same curate call as the systems, after `l1_curate` (the pod's `default_curate_with_enrichment_fn` already writes core then enrichment), so the System node exists before its edge; the MERGE makes the order non-load-bearing anyway.

### Q4 - The read side

**Decision.** No new read tool; the existing read surfaces already carry the edge, and the fix pins them with tests plus one contract addition:

- `index_card` edge-degree is already relation-agnostic (`collect(type(r))`), so a System's card reports `edge_degree.EVIDENCED_BY = n`. Pinned by test.
- The read-only `graph_view` (analysis `graph_tools` and the shared hunting seam) already names `EVIDENCED_BY` in its SCHEMA. The analysis contract gains the witness labels and the `Technology` / `Certificate` identity keys - without them the typist cannot name the exact witness node it read - single-sourced from `l0_stream.L0_IDENTITY_KEYS` and pinned by a parity test.
- A System-neighbours query (`MATCH (sy:L1System ...)-[:EVIDENCED_BY]->(l0)`) is readable through the tool unchanged; pinned by test.
- `dfs_down` stays Service-shaped and is not extended: the System->L0 hop is a graph_view query, not a typed L1 hop.

### Q5 - The withhold-the-unproven-claim rule is unchanged

**Decision.** A System whose claim has no witness in the slice is still PROPOSED and still WRITTEN, simply edgeless. The writer never withholds a System for a missing witness and never fabricates one; the epistemic decision stays where it already lives - the model's own reflection/extraction judgment (and the reflection-exhaustion fail-CLOSED path is untouched). An absent evidence list and a witness that cannot be MATCHed are both a valid empty outcome, never an error.

## 3. Alternatives considered and rejected

- **Nesting the witness set in a System prop** (`props.evidence`) instead of a typed field: props are opaque to the writer, replace-on-extend, and reserved-key-stripped; a witness is an edge, not an attribute.
- **Emitting evidence as its own sub-batch from the linking call**: the linking call owns `Service->System` edges; a witness belongs to the claim the extraction call makes, and a second call's evidence would need reconciling against the first's.
- **Writing the evidence inside `l1_curate`** (so every System writer carries its evidence): it would change `l1_curate`'s 2-tuple contract and put a cross-layer hop inside the node writer; `enrich` is the delta-category writer and exposes the counts in the existing `AnalyserExport.enrichment` map.
- **A live UPDATE of a witness set** (delete edges no longer asserted): the model is monotonic/append-only (CONTEXT.md, "Defeasibility"); retraction is out of scope.

## 4. Residual risks

- A witness reference that names too FEW keys (e.g. a Header `{name}` without `endpoint`/`baseurl`) matches every L0 node carrying that name and edges each of them. The prompt directs a single-node identity; the write itself stays MATCH-only and safe.
- A transaction-only fact whose endpoint recon never minted stays edgeless (D-3), which is the honest reading: the graph holds no witness to point at.
- `evidence` is a new field on the shared LLM-facing `SystemProposal`, so the bootstrap/scaffold paths (which emit no evidence) are unaffected by construction.
