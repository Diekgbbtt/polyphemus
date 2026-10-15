# ADR: the streamed Assigner judges its chunk against the adjacent surface

Date: 2026-10-14.
Status: PARTIALLY SUPERSEDED 2026-10-15 for the Assigner (D-A2 and D-A4;
see `docs/design/assigner-http-history-surface-adr.md`). The D-A2
typist amendment of 2026-10-15 and D-A1/D-A3 stand.
Supersedes: `docs/experiments/l0-l1-pipeline-split-report.md` D-1 (both the first
reading and its 2026-10-14 revision) as the statement of what the streamed
assigner may read and what the gate may refuse.

## Context

The httpx:0 forensics (`docs/experiments/l0-l1-pipeline-split-report.md`, D-1
revision) showed a graph-capable streamed assigner producing 37/37 correct
`AGGREGATES` proposals and the chunk-scoped `resolve_l0_refs` gate refusing every
one as `unresolvable`, because each named an endpoint outside the chunk's single
admitted endpoint. The pipeline paid ~1.9M input tokens and banked nothing: the
model obeyed a work order ("enumerate the L0 Endpoints this target exposes")
that the gate then contradicted, and the backlog was carried but not
transported, so the correct edges were lost entirely.

The defect is the scope mismatch, not the discovery. An endpoint's owner is
rarely decidable from the endpoint alone: ownership is a topological judgment
(which service area a path belongs to), and topology lives in the surface
around the endpoint, not in it.

## Decisions

**D-A1. The streamed chunk stays the unit of work.**
A chunk is the slice recon most recently collected. The assigner is dispatched
per chunk, judges per chunk, and the per-chunk session reset keeps each chunk's
reasoning scoped to its own turn chain. Nothing here reintroduces a global pass.

**D-A2. The assigner runs a bounded adjacent-surface phase.**
Before judging ownership the assigner MAY widen its view beyond the slice, in
this order and within these bounds:

1. Judge the chunk slice first - it is the recently collected evidence and the
   primary subject.
2. Enumerate the BaseURLs of the project and join the endpoints they expose
   (`graph_view`, read-only, always a LIMIT), so the slice's neighbourhood -
   which service areas surround it - is read, not guessed.
3. The HTTP-history pair (`search_http_history` / `get_http_artifact`) is the
   recorded-transaction read, in two modes: DISAMBIGUATION AND CONFIRMATION (an
   endpoint whose ownership is ambiguous or deceiving, or a surface whose full
   request shape and response are needed to confirm a hypothesis) AND AN
   ADJACENTLY PROMISING SURFACE (an endpoint that looks even minimally promising
   for a candidate Service - one endpoint often embeds several features, iframes
   in HTML, menu entries, tabs - may be read for its fuller response before the
   judgment). Diving into the technical understanding of a surface area is the
   mechanism-typist's ownership, not the assigner's; the assigner stops at the
   ownership judgment.

The bound is load-bearing: unbounded roaming is what cost httpx:0 ~1.9M input
tokens for one chunk. A handful of bounded graph queries per chunk is the
budget; the firehose stays shut.

**AMENDED 2026-10-15** (proposer-tool-workflows rework): item 3's remit widened
from disambiguation/confirmation only to the two modes above, and the read tools
plus a bounded `exec` are now also bound on the mechanism-typist's turn. See
`docs/design/typist-tool-workflows.md` for the trace evidence, the state model,
and the binding decisions.

**D-A3. The L1 dump in the first HumanMessage is the deductive target.**
The inventory block (overview, services with contracts, live systems) is
re-read live at every chunk dispatch, so it is progressively updated as the run
writes. The assigner reasons FROM the observed surface TO these identities by
deduction - contract nouns and actions against path nouns, parameters and
methods - never the reverse. A judgment that cannot cite the surface against a
listed identity is withheld, not placed.

**D-A4. The out-of-chunk write gate is dropped, completely.**
`resolve_l0_refs` no longer refuses a reference for naming an endpoint outside
the chunk. It resolves every reference against the KNOWN surface - the chunk's
admitted endpoints UNION the settled project surface the caller supplies - and
canonicalises the `l0` shape against it. What it still drops, unchanged, is a
reference to surface nobody knows: an endpoint neither in the chunk nor settled
is a reference to nothing, and its own chunk will judge it when recon collects
it. The writer stays fail-safe behind this: the sole-writer MATCHes the L0
node and never creates one, so an unsettled reference still cannot fabricate
surface. Cross-chunk duplicate proposals collapse by construction - the writer
MERGEs `(Service)-[:AGGREGATES]->(L0)`, so the same judgment from two chunks
is one edge.

## Consequences

- Correct out-of-chunk proposals become edges instead of `unresolvable` census
  lines; `AssignmentStats.unresolvable` now counts only truly unknown
  references.
- Per-chunk cost grows by the bounded adjacent phase (a handful of graph
  queries); the reset-per-chunk session lifecycle keeps each chunk from paying
  for the previous chunk's trail.
- `tests/integration/test_assigner_contracts.py::test_C33` and `test_C36`
  encoded the dropped gate and are rewritten by this change, not grandfathered.
