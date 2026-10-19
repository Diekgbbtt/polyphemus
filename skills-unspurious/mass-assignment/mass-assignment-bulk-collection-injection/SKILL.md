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

Applicability centers on a bulk or batch endpoint whose per-item enforcement gaps let one slot bind what the others would refuse.
The server exposes array-of-objects actions with allowlists applied at the boundary or on first elements only.
Sparse or patch update support widens the surface because a flat candidate can arrive inside a batch patch document.
Aliased or batched GraphQL mutations widen the surface the same way through repeated input objects in one request.
Flat singleton injection belongs to the parent baseline and any nested relation inside a batch belongs to the combined sibling, so neither rides here.

## Reconnaissance

Map only the batch surface, because singleton fields belong to the baseline.
- List bulk or batch create plus update actions with their per-item enforcement points.
- Harvest candidate flat fields from schemas plus client bundles plus mutation examples, and record them as abstract protected-field entries.
- Record which batch slots accept array alternates plus scalar alternates plus aliased mutation inputs.
- Probe boundary behavior with benign batches so later verdicts have a clean comparison.

## Detection Channels

Batch proof listens to per-position state rather than batch echo, so only the entries below are live here.
- Persisted flat value inside one batch slot visible in a later per-item read binds one slot to one verdict.
- Silent mid-batch persistence without batch echo confirms a write the response never reflected.
- Per-position diff across roles separates a validated slot from a smuggled one.
- Recomputed flat field ignoring input marks a guarded slot rather than a success.
- Uniform batch rejection with no slot persisted marks a guarded batch rather than a finding.

## Adversarial Capabilities

Batch smuggling presupposes an authenticated non-privileged session plus batch shaping plus per-item reads, and it consumes all three.
- Create plus update reachable objects through a working non-privileged session.
- Submit bulk payloads that place one malicious flat object among benign items.
- Vary the malicious slot across first plus middle plus last positions in successive batches.
- Read back per-item state through fresh per-item reads to diff before against after.
- Hold a control batch of fully benign items so each slot verdict has its comparison.

## Trust Assumptions

At the moment a create or update executes, the feature trusts client-supplied attributes to bind only to caller-writable fields.
The agreement holds read-only markers plus derived-field recomputation steady, covers every encoding through one allowlist, and keeps nested relations inside caller scope.
Sensitive privilege plus ownership plus gate plus billing state leaks only when the server binds what the caller may not write.
This variant breaks the collection-scope clause because a mid-batch flat item binds while only boundary items face validation on a bulk payload.

## Key Vulnerabilities

### Per-Position Verdicts Against Boundary-Only Validation

Place the malicious flat object mid-batch where only boundary elements face checks.
Record one persistence verdict per batch position rather than one verdict per batch, because batch totals cannot attribute a write to its slot.
The parent variation step names batch operations but never describes mid-batch smuggling or per-element persistence decisions, so this variant owns the per-position procedure.

### Slot-Scoped Persistence Proof

Diff per-item state before against after with fresh reads, and record one durable verdict per slot.
Treat silent mid-batch persistence as a positive even when the batch response echoes nothing.
Treat a recomputed flat field as a guarded slot rather than a success.

### Batch Shape Reach

Carry array alternates plus scalar alternates plus aliased mutation inputs as defeat detail inside this variant.
Hold the per-position verdict constant across every shape, because reshaping reaches the same batch binder through another framing.
Nested relations never ride here, and any nested relation inside a batch belongs to the combined sibling.

## Advanced Techniques

Batch depth rewards position awareness plus comparison discipline.
- Sweep the malicious slot across positions because enforcement often covers only the first element.
- Pad the batch with benign items so the malicious slot sits deep inside realistic traffic.
- Alias repeated mutations in one GraphQL request and compare per-alias effects immediately after.
- Treat validators that run pre-batch as suspect, because per-item checks may never execute underneath a passing batch gate.

## Bypass Techniques

Bypass forms stay aspects inside this variant because no framing difference changes the per-position verdict itself.
- Switch body encoding while holding the batch candidate constant, because some code paths validate only one framing.
- Reshape the batch across array plus object-wrapped plus aliased forms to reach the binder through another parser.
- Nested key reshaping never rides here, and race interleaving names the race-conditions skill at its TOCTOU step rather than restating it.

When this section does not fulfil the knowledge gap, extend the reading with the defence-bypass and proxy-techniques families.

## Testing Methodology

Per-position reasoning runs after the baseline is fixed, because no slot verdict is meaningful without a paired control.
1. **Inventory bulk endpoints** - list every bulk or batch create plus update action with its slot layout, and the step completes when no batch slot remains unlisted.
2. **Capture slot state** - record the visible attribute set per item with schemas plus client hints, and the step completes when each batch item shows a listed attribute set.
3. **Build the slot dictionary** - assemble per-resource protected-field candidates with one flat entry per slot shape, and the step completes when every slot shape carries a seeded candidate list.
4. **Inject mid-batch** - send each flat candidate inside a padded batch beside a benign control batch, and the step completes when every candidate shows a paired batch beside its control.
5. **Diff per position** - compare before against after through fresh per-item reads across roles, and the step completes when every slot carries a durable persistence verdict.
6. **Vary batch shapes** - replay each verdict across array plus aliased plus alternate-encoding framings, and the step completes when every structural shape shows a recorded decision.

## False Positives

Stop when no batch slot shows a durable out-of-scope write, because batch echo alone proves nothing here.
- Server recomputes the flat field and ignores client input, confirmed by identical before plus after reads.
- Read-only marking enforced per item across encodings, confirmed by uniform negatives on every slot.
- Batch-wide rejection with nothing persisted, which is guarded behavior rather than a finding.
- Slot change inside caller scope, which is permitted behavior rather than a finding.

## Pro Tips

Batch smuggling rewards deep slots plus fresh per-item reads.
1. Prefer one malicious slot per batch so each verdict attributes cleanly to its position.
2. Favor fresh per-item reads over batch responses, because silent mid-batch persistence is the common positive.
3. Sweep first plus middle plus last positions, because boundary-only validation is the common gap.
4. Pad with realistic benign items so the batch passes structural gates before item checks.
5. Record inconclusive slot states as inconclusive rather than negative.

## Summary

A bulk binder that validates boundary items while binding every slot lets a caller smuggle flat fields through a mid-batch position.
Per-position diffs prove the write where a batch-total check would miss it.
