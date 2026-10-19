---
name: mass-assignment-nested-relation-write
description: Nested relation binding test that writes child objects through serializers or relation helpers on singleton payloads, judges each child against caller scope, and covers patch-path plus GraphQL input nesting shapes.
metadata:
  version: 1.0.0
---

# Nested Relation Write

Singleton update endpoints sometimes bind nested objects through serializers or relation helpers without checking each child against caller scope.
This variant writes one child object per attempt through the nested path and judges that child with its own scope verdict.
The goal is privilege plus ownership plus gate plus billing effects reached through a child rather than through a flat field.

## Attack Surface

- **Applicability**: centers on a singleton create or update action whose binder traverses nested objects into related records.
- **Nested helpers**: the server exposes writable nested serializers or relation helpers beneath an otherwise guarded parent.
- **Sparse update widening**: sparse or patch update support widens the surface because a nested path can arrive as a path string rather than as an object.
- **GraphQL input widening**: graphQL input types that mirror model relations widen the surface the same way through nested input fields.
- **Out-of-scope variants**: flat singleton injection belongs to the parent baseline and any batch payload belongs to a bulk-owning sibling, so neither rides here.

## Reconnaissance

- **Surface scope**: map only the nested surface, because flat fields belong to the baseline.
- **Action inventory**: list singleton create plus update actions whose binder accepts nested objects beneath the parent.
- **Field harvesting**: harvest candidate child fields from schemas plus client bundles plus mutation examples, and record them as abstract protected-field entries.
- **Path recording**: record which nested paths accept object shapes plus dot or bracket paths plus sparse or patch path strings.
- **Input recording**: record GraphQL nested input fields that mirror model relations for later input addition.

## Detection Channels

- **Channel scope**: child-scope proof listens to child state rather than parent echo, so only the entries below are live here.
- **Persisted child value**: persisted child value visible in a later child read or in a parent overfetch binds one attempt to one child verdict.
- **Silent child persistence**: silent child persistence without parent echo confirms a write the response never reflected.
- **Child-scope diff**: child-scope diff across roles separates a caller-permitted link from an out-of-scope write.
- **Recomputed child field**: recomputed child field ignoring input marks a guarded attempt rather than a success.
- **Parent-only change**: parent-only change with no child persistence marks a non-finding for this variant.

## Adversarial Capabilities

- **Prerequisites**: relation writing presupposes an authenticated non-privileged session plus nested shaping plus control reads, and it consumes all three.
- **Object access**: create plus update reachable objects through a working non-privileged session.
- **Child injection**: resubmit a legitimate singleton update with one added nested child per attempt.
- **Child shaping**: shape the child as an object plus as dot or bracket paths plus as sparse or patch path strings.
- **Child-state reads**: read back child state through a fresh child read or an overfetch to diff before against after.
- **Control read**: hold a control read from a second scope so each child verdict has its comparison.

## Trust Assumptions

- **The trust premise**: at the moment a create or update executes, the feature trusts client-supplied attributes to bind only to caller-writable fields.
- **The agreement**: it holds read-only markers plus derived-field recomputation steady, covers every encoding through one allowlist, and keeps nested relations inside caller scope.
- **The exposure**: sensitive privilege plus ownership plus gate plus billing state leaks only when the server binds what the caller may not write.
- **The failing clause**: this variant breaks the nested-scope clause because a nested relation object binds plus creates or links a child beyond caller scope on a singleton payload.

## Key Vulnerabilities

### Relation-Graph Traversal on One Object

- **Graph traversal**: walk the writable nested path to create or link exactly one child object per attempt.
- **Child adjudication**: judge that child against caller scope rather than judging the parent, because parent permission never implies child permission.
- **Ownership boundary**: the parent variation step names nested objects but never describes relation-graph reasoning or per-child authorization verdicts, so this variant owns the traversal procedure.

### Child-Scoped Persistence Proof

- **Child diff**: diff child state before against after with a fresh read, and record one durable verdict per child.
- **Silent persistence**: treat silent child persistence as a positive even when the parent response echoes nothing.
- **Recomputed child field**: treat a recomputed child field as a guarded attempt rather than a success.

### Nested Shape Reach

- **Nested shape reach**: carry dot or bracket paths plus sparse or patch path strings plus GraphQL nested inputs as defeat detail inside this variant.
- **Verdict stability**: hold the child-scope verdict constant across every shape, because reshaping reaches the same binder through another framing.
- **Wrapped-shape probing**: try the array-for-scalar form and the unexpected-key form against each child path, since a binder that rejects the plain shape frequently accepts the wrapped one.
- **Delegated batch handling**: batch payloads never ride here, and any nested relation inside a batch belongs to the combined sibling.

### Navigation-Property Expansion

- **Navigation-property expansion**: where the interface exposes a navigation-property expansion on a query, test the joined entity separately, because authorization decorators frequently cover the top-level entity set while the joined entity carries no scope check of its own.
- **Joined-entity adjudication**: judge the joined entity against caller scope with its own read and its own write attempt, rather than inheriting the verdict of the parent set.
- **Dialect naming**: name the interface dialect at the query-shape step rather than restating its query language here.

## Advanced Techniques

- **Depth premise**: nested depth rewards relation awareness plus schema reading.
- **Hop-by-hop traversal**: traverse one relation hop at a time and confirm each hop persists before deepening.
- **Schema mining**: mine schema excerpts plus client field names for hidden nested paths the visible form never shows.
- **Input addition**: add nested fields to GraphQL inputs and overfetch the child immediately after the mutation.
- **Post-bind validators**: treat validators that run post-bind as suspect, because extra nested fields may persist underneath a clean response.

## Bypass Techniques

- **Bypass scope**: bypass forms stay aspects inside this variant because no framing difference changes the child-scope verdict itself.
- **Encoding switch**: switch body encoding while holding the nested candidate constant, because some code paths validate only one framing.
- **Nested key reshaping**: reshape the nested key across object plus dot plus bracket plus patch-path forms to reach the binder through another parser.
- **Delegated techniques**: batch smuggling never rides here, and race interleaving names the race-conditions skill at its TOCTOU step rather than restating it.

When this section does not fulfil the knowledge gap, extend the reading with the defence-bypass and proxy-techniques families.

## Testing Methodology

Relation reasoning runs after the baseline is fixed, because no child verdict is meaningful without a paired control.
1. **Inventory singleton endpoints** - list every singleton create plus update action with its nested paths, and the step completes when no nested path remains unlisted.
2. **Capture child state** - record the visible attribute set per parent plus per child with schemas plus client hints, and the step completes when each resource shows a listed attribute set.
3. **Build the child dictionary** - assemble per-resource protected-field candidates with one child entry per relation, and the step completes when every relation carries a seeded candidate list.
4. **Inject one child per attempt** - send each nested candidate beside a legitimate singleton update, and the step completes when every candidate shows a paired attempt beside its control.
5. **Diff child scope** - compare before against after through fresh child reads across roles, and the step completes when every attempt carries a durable child-scope verdict.
6. **Vary nested shapes** - replay each verdict across object plus path plus patch plus GraphQL input framings, and the step completes when every structural shape shows a recorded decision.

## False Positives

- **Durable-write stop**: stop when the child state shows no durable out-of-scope write, because UI-only effects prove nothing here.
- **Server recomputation**: server recomputes the child field and ignores client input, confirmed by identical before plus after reads.
- **Read-only enforcement**: read-only marking enforced consistently across encodings, confirmed by uniform negatives on every shape.
- **Parent-only change**: parent-only change with no child persistence, which belongs to the baseline rather than to this variant.
- **In-scope child change**: child change inside caller scope, which is permitted behavior rather than a finding.

## Pro Tips

- **Discipline**: relation writes reward narrow attempts plus fresh child reads.
- **Single child per attempt**: prefer one child per attempt so each verdict attributes cleanly to its path.
- **Fresh child reads**: favor fresh child reads over parent responses, because silent persistence is the common positive.
- **Client mining**: mine client bundles plus mutation examples for nested field names before fuzzing blindly.
- **Shape replay**: replay every shape variant against the same child, because validators are often shape-specific.
- **Inconclusive recording**: record inconclusive child states as inconclusive rather than negative.

## Summary

A singleton binder that traverses nested relations without child-scope checks lets a caller create or link children beyond its scope.
Traversal plus per-child diffs prove the write where a parent-only check would miss it.
