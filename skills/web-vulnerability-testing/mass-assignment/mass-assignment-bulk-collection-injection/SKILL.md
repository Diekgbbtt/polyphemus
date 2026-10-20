---
name: mass-assignment-bulk-collection-injection
description: Bulk collection binding test that smuggles flat fields mid-batch past boundary-only validation, records per-position verdicts, and covers array-alternate plus aliased batch shapes.
metadata:
  version: 1.0.0
---

# Bulk Collection Injection

Bulk endpoints sometimes validate only boundary items while a mid-batch item binds unchecked into persisted state.
This variant places one malicious flat object mid-batch and records a persistence verdict per batch position.
The goal is privilege plus ownership plus gate plus billing effects reached through a batch slot rather than through a singleton write.

## Attack Surface

- **Applicability**: a bulk or batch endpoint whose per-item enforcement gaps let one slot bind what the others would refuse.
- **Array action exposure**: the server exposes array-of-objects actions with allowlists applied at the boundary or on first elements only.
- **Sparse update widening**: sparse or patch update support widens the surface because a flat candidate can arrive inside a batch patch document.
- **Aliased mutation widening**: aliased or batched GraphQL mutations widen the surface the same way through repeated input objects in one request.
- **Out-of-scope variants**: flat singleton injection belongs to the parent baseline and any nested relation inside a batch belongs to the combined sibling, so neither rides here.

## Reconnaissance

- **Surface scope**: map only the batch surface, because singleton fields belong to the baseline.
- **Action inventory**: list bulk or batch create plus update actions with their per-item enforcement points.
- **Field harvesting**: harvest candidate flat fields from schemas plus client bundles plus mutation examples, and record them as abstract protected-field entries.
- **Slot recording**: record which batch slots accept array alternates plus scalar alternates plus aliased mutation inputs.
- **Boundary probe**: probe boundary behavior with benign batches so later verdicts have a clean comparison.

## Detection Channels

- **Channel scope**: batch proof listens to per-position state rather than batch echo.
- **Persisted flat value**: a flat value persisted inside one batch slot and visible in a later per-item read binds one slot to one verdict.
- **Silent mid-batch persistence**: a mid-batch write without batch echo confirms a write the response never reflected.
- **Per-position diff**: a per-position diff across roles separates a validated slot from a smuggled one.
- **Recomputed flat field**: a recomputed flat field that ignores input marks a guarded slot rather than a success.
- **Uniform batch rejection**: a batch rejected uniformly with no slot persisted marks a guarded batch rather than a finding.

## Adversarial Capabilities

- **Prerequisites**: batch smuggling presupposes an authenticated non-privileged session plus batch shaping plus per-item reads, and it consumes all three.
- **Object access**: create plus update reachable objects through a working non-privileged session.
- **Bulk submission**: submit bulk payloads that place one malicious flat object among benign items.
- **Position variation**: vary the malicious slot across first plus middle plus last positions in successive batches.
- **State reads**: read back per-item state through fresh per-item reads to diff before against after.
- **Control batch**: hold a control batch of fully benign items so each slot verdict has its comparison.

## Trust Assumptions

- **The agreement**: at the moment a create or update executes, the feature trusts client-supplied attributes to bind only to caller-writable fields, holds read-only markers plus derived-field recomputation steady, covers every encoding through one allowlist, and keeps nested relations inside caller scope, and sensitive privilege plus ownership plus gate plus billing state leaks only when the server binds what the caller may not write.
- **The failing clause**: this variant breaks the collection-scope clause because a mid-batch flat item binds while only boundary items face validation on a bulk payload.

## Key Vulnerabilities

### Per-Position Verdicts Against Boundary-Only Validation

- **Mid-batch placement**: place the malicious flat object mid-batch where only boundary elements face checks.
- **Per-position verdict**: record one persistence verdict per batch position rather than one verdict per batch, because batch totals cannot attribute a write to its slot.
- **Ownership boundary**: the parent variation step names batch operations but never describes mid-batch smuggling or per-element persistence decisions, so this variant owns the per-position procedure.

### Slot-Scoped Persistence Proof

- **Slot diff**: diff per-item state before against after with fresh reads, and record one durable verdict per slot.
- **Silent persistence**: treat silent mid-batch persistence as a positive even when the batch response echoes nothing.
- **Recomputed field**: treat a recomputed flat field as a guarded slot rather than a success.

### Batch Shape Reach

- **Shape reach**: carry array alternates plus scalar alternates plus aliased mutation inputs as defeat detail inside this variant.
- **Verdict stability**: hold the per-position verdict constant across every shape, because reshaping reaches the same batch binder through another framing.
- **Delegated nesting**: nested relations never ride here, and any nested relation inside a batch belongs to the combined sibling.

## Advanced Techniques

- **Depth premise**: batch depth rewards position awareness plus comparison discipline.
- **Position sweep**: sweep the malicious slot across positions because enforcement often covers only the first element.
- **Batch padding**: pad the batch with benign items so the malicious slot sits deep inside realistic traffic.
- **Alias comparison**: alias repeated mutations in one GraphQL request and compare per-alias effects immediately after.
- **Pre-batch validators**: treat validators that run pre-batch as suspect, because per-item checks may never execute underneath a passing batch gate.

## Bypass Techniques

- **Bypass scope**: bypass forms stay aspects inside this variant because no framing difference changes the per-position verdict itself.
- **Encoding switch**: switch body encoding while holding the batch candidate constant, because some code paths validate only one framing.
- **Batch reshaping**: reshape the batch across array plus object-wrapped plus aliased forms to reach the binder through another parser.
- **Delegated techniques**: nested key reshaping never rides here, and race interleaving names the race-conditions skill at its TOCTOU step rather than restating it.
- **Extended reading**: when this section does not fulfil the knowledge gap, extend the reading with the defence-bypass and proxy-techniques families.

## Testing Methodology

Per-position reasoning runs after the baseline is fixed, because no slot verdict is meaningful without a paired control.
1. **Inventory bulk endpoints** - list every bulk or batch create plus update action with its slot layout, and the step completes when no batch slot remains unlisted.
2. **Capture slot state** - record the visible attribute set per item with schemas plus client hints, and the step completes when each batch item shows a listed attribute set.
3. **Build the slot dictionary** - assemble per-resource protected-field candidates with one flat entry per slot shape, and the step completes when every slot shape carries a seeded candidate list.
4. **Inject mid-batch** - send each flat candidate inside a padded batch beside a benign control batch, and the step completes when every candidate shows a paired batch beside its control.
5. **Diff per position** - compare before against after through fresh per-item reads across roles, and the step completes when every slot carries a durable persistence verdict.
6. **Vary batch shapes** - replay each verdict across array plus aliased plus alternate-encoding framings, and the step completes when every structural shape shows a recorded decision.

## False Positives

- **Durable-write stop**: stop when no batch slot shows a durable out-of-scope write, because batch echo alone proves nothing here.
- **Server recomputation**: the server recomputes the flat field and ignores client input, confirmed by identical before plus after reads.
- **Read-only enforcement**: read-only marking is enforced per item across encodings, confirmed by uniform negatives on every slot.
- **Batch-wide rejection**: batch-wide rejection with nothing persisted is guarded behavior rather than a finding.
- **In-scope slot change**: a slot change inside caller scope is permitted behavior rather than a finding.

## Pro Tips

- **Discipline**: batch smuggling rewards deep slots plus fresh per-item reads.
- **Single slot**: prefer one malicious slot per batch so each verdict attributes cleanly to its position.
- **Fresh reads**: favor fresh per-item reads over batch responses, because silent mid-batch persistence is the common positive.
- **Position sweep**: sweep first plus middle plus last positions, because boundary-only validation is the common gap.
- **Realistic padding**: pad with realistic benign items so the batch passes structural gates before item checks.
- **Inconclusive recording**: record inconclusive slot states as inconclusive rather than negative.

## Summary

A bulk binder that validates boundary items while binding every slot lets a caller smuggle flat fields through a mid-batch position.
Per-position diffs prove the write where a batch-total check would miss it.
