---
name: mass-assignment-bulk-nested-relation-write
description: Bulk-nested relation binding test that traverses child relations inside batch positions past boundary-only validation, records per-position child-scope verdicts, and covers position selection plus serializer reasoning combined.
metadata:
  version: 1.0.0
---

# Bulk Nested Relation Write

Batch payloads sometimes carry nested relations inside individual positions while validation covers only boundary items and never the children within.
This variant runs a per-position outer loop where each batch position gets full relation-graph traversal with its own child-scope verdict.
The goal is privilege plus ownership plus gate plus billing effects reached through a child hidden inside a batch slot.

## Attack Surface

- **Applicability**: centers on a bulk or batch endpoint whose items carry writable nested relations beneath a boundary-only item gate.
- **Array action exposure**: the server exposes array-of-objects actions where each position traverses nested serializers or relation helpers into child records.
- **Sparse update widening**: sparse or patch update support widens the surface because a nested path can arrive as a path string inside a batch document.
- **Aliased mutation widening**: aliased or batched GraphQL mutations with nested inputs widen the surface the same way through repeated relation writes in one request.
- **Out-of-scope variants**: pure singleton nesting belongs to the singleton nested sibling and pure flat batches belong to the flat bulk sibling, so neither rides here.

## Reconnaissance

- **Surface scope**: map only the nested-inside-batch surface, because single-axis payloads belong to the siblings.
- **Action inventory**: list bulk or batch actions whose items accept nested objects beneath the item.
- **Field harvesting**: harvest candidate child fields from schemas plus client bundles plus mutation examples, and record them as abstract protected-field entries per position shape.
- **Position recording**: record which positions accept nested objects plus dot or bracket paths plus sparse or patch path strings.
- **Boundary probe**: probe boundary behavior with benign nested batches so later verdicts have a clean comparison.

## Detection Channels

- **Channel scope**: combined proof listens to per-position child state rather than batch echo, so only the entries below are live here.
- **Persisted child value**: persisted child value inside one batch slot visible in a later per-item child read binds one slot plus one child to one verdict.
- **Silent nested persistence**: silent nested persistence inside a mid-batch slot without batch echo confirms a write the response never reflected.
- **Child-scope diff**: per-position child-scope diff across roles separates a permitted nested link from an out-of-scope nested write.
- **Recomputed child field**: recomputed child field ignoring input marks a guarded slot rather than a success.
- **Flat slot change**: flat slot change with no child persistence marks a non-finding for this variant.

## Adversarial Capabilities

- **Prerequisites**: combined writing presupposes an authenticated non-privileged session plus batch shaping plus nested shaping plus per-item child reads, and it consumes all four.
- **Object access**: create plus update reachable objects through a working non-privileged session.
- **Bulk submission**: submit bulk payloads that place one nested child inside a chosen batch position.
- **Position variation**: vary the nested position across first plus middle plus last slots in successive batches.
- **Child shaping**: shape the nested child as an object plus as dot or bracket paths plus as sparse or patch path strings.
- **Child-state reads**: read back per-item child state through fresh reads to diff before against after with a control batch for comparison.

## Trust Assumptions

- **The trust premise**: at the moment a create or update executes, the feature trusts client-supplied attributes to bind only to caller-writable fields.
- **The agreement**: it holds read-only markers plus derived-field recomputation steady, covers every encoding through one allowlist, and keeps nested relations inside caller scope.
- **The exposure**: sensitive privilege plus ownership plus gate plus billing state leaks only when the server binds what the caller may not write.
- **The failing clause**: this variant breaks the combined-scope clause because a nested relation inside a mid-batch item binds a child beyond caller scope while only boundary items face validation.

## Key Vulnerabilities

### Per-Position Outer Loop With Child-Scope Inner Checks

- **Outer-loop traversal**: run the batch as an outer loop over positions and traverse the full relation graph inside each position.
- **Per-child adjudication**: judge each nested child against caller scope with its own verdict, because slot permission never implies child permission.
- **Ownership boundary**: the parent variation step names nested objects plus batch operations separately but never names their conjunction, so this variant owns the combined procedure.

### Slot-Scoped Child Persistence Proof

- **Slot-plus-child diff**: diff per-item child state before against after with fresh reads, and record one durable verdict per slot plus child pair.
- **Silent persistence**: treat silent nested persistence inside a mid-batch slot as a positive even when the batch response echoes nothing.
- **Recomputed child field**: treat a recomputed child field as a guarded slot rather than a success.

### Combined Shape Reach

- **Combined shape reach**: carry batch position selection plus dot or bracket paths plus sparse or patch path strings plus aliased nested inputs as defeat detail inside this variant.
- **Verdict stability**: hold the per-position child-scope verdict constant across every shape, because reshaping reaches the same combined binder through another framing.
- **Delegated axes**: neither single-axis payload rides here, and singleton nesting plus flat batches stay with their owning siblings.

## Advanced Techniques

- **Depth premise**: combined depth rewards position awareness plus relation awareness together.
- **Position sweep**: sweep the nested child across slot positions because enforcement often covers only boundary items.
- **Hop-by-hop traversal**: traverse one relation hop at a time inside the chosen slot and confirm each hop persists before deepening.
- **Schema mining**: mine schema excerpts plus client field names for hidden nested paths that batch forms never show.
- **Aliased input addition**: add nested fields to aliased GraphQL inputs and overfetch each affected child immediately after the request.

## Bypass Techniques

- **Bypass scope**: bypass forms stay aspects inside this variant because no framing difference changes the per-position child-scope verdict itself.
- **Encoding switch**: switch body encoding while holding the nested batch candidate constant, because some code paths validate only one framing.
- **Nested key reshaping**: reshape the nested key across object plus dot plus bracket plus patch-path forms inside the chosen slot to reach the binder through another parser.
- **Batch reshaping**: reshape the batch across array plus object-wrapped plus aliased forms for the same reason.
- **Delegated race handling**: race interleaving names the race-conditions skill at its TOCTOU step rather than restating it.

When this section does not fulfil the knowledge gap, extend the reading with the defence-bypass and proxy-techniques families.

## Testing Methodology

Combined reasoning runs after both single-axis baselines are understood, because no slot-plus-child verdict is meaningful without a paired control.
1. **Inventory nested batch endpoints** - list every bulk or batch action whose items carry nested paths, and the step completes when no nested slot remains unlisted.
2. **Capture slot-plus-child state** - record the visible attribute set per item plus per nested child with schemas plus client hints, and the step completes when each slot plus child shows a listed attribute set.
3. **Build the combined dictionary** - assemble per-resource protected-field candidates with one nested entry per position shape, and the step completes when every position shape carries a seeded candidate list.
4. **Inject nested children mid-batch** - send each nested candidate inside a padded batch beside a benign control batch, and the step completes when every candidate shows a paired batch beside its control.
5. **Diff per position plus child** - compare before against after through fresh per-item child reads across roles, and the step completes when every slot plus child pair carries a durable child-scope verdict.
6. **Vary combined shapes** - replay each verdict across slot positions plus nested path plus aliased framings, and the step completes when every structural shape shows a recorded decision.

## False Positives

- **Durable-write stop**: stop when no slot-plus-child pair shows a durable out-of-scope write, because batch echo alone proves nothing here.
- **Server recomputation**: server recomputes the child field and ignores client input, confirmed by identical before plus after reads.
- **Read-only enforcement**: read-only marking enforced per item plus per child across encodings, confirmed by uniform negatives on every shape.
- **Batch-wide rejection**: batch-wide rejection with nothing persisted, which is guarded behavior rather than a finding.
- **In-scope nested change**: nested change inside caller scope, which is permitted behavior rather than a finding.

## Pro Tips

- **Discipline**: combined writes reward deep slots plus narrow children plus fresh reads.
- **Single child per slot**: prefer one nested child in one slot per batch so each verdict attributes cleanly to its pair.
- **Fresh child reads**: favor fresh per-item child reads over batch responses, because silent nested persistence is the common positive.
- **Position-first sweep**: sweep slot positions before deepening relation hops, because boundary-only validation is the common outer gap.
- **Client mining**: mine client bundles plus mutation examples for nested batch field names before fuzzing blindly.
- **Inconclusive recording**: record inconclusive slot-plus-child states as inconclusive rather than negative.

## Summary

A bulk binder that traverses nested relations inside batch positions without per-position child-scope checks lets a caller hide an out-of-scope child inside a mid-batch slot.
Outer position loops plus inner child diffs prove the write where single-axis checks would miss it.
