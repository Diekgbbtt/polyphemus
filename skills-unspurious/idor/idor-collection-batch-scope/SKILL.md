---
name: idor-collection-batch-scope
description: Scope set-level collections and batch endpoints for per-item binding gaps. Use when a paged list may skip its filter, when a bulk array may validate only its first element, when an import file may carry foreign keys.
metadata:
  version: 1.0.0
---

# IDOR Collection Batch Scope

Set-level scope testing decides whether a collection path binds every member to the caller rather than the collection as a whole.
The leading word is scope: every probe reasons about positions inside a set, never about a lone identifier.

## Attack Surface

Scope applies where an endpoint reads or writes many objects at once through paging, bulk arrays, or import payloads.
The set may arrive as page windows and cursors, as ordered bulk elements, or as rows inside an uploaded structured file.
Cooperative listing endpoints double as identifier seeders and as the first distrust target.
Single-reference swaps stay in the sibling direct variant, and only set-position reasoning lives here.

## Reconnaissance

Distrust cooperative listing from the start by recording which filter each list endpoint claims to enforce.
Map cursor and page-window shapes from history and interface material until adversarial windows are constructible.
Map bulk element ordering and per-row key shapes until foreign identifiers can be placed at first, middle, and trailing positions.
Seed a per-principal identifier corpus from list, search, and export endpoints until each role owns known foreign candidates.

## Detection Channels

Foreign rows appearing mid-array while the first element stays owned signals per-item validation gaps.
A page window that returns another principal's objects after cursor manipulation signals filter-skip.
Count and size anomalies between the control window and the adversarial window confirm scope failure without reading full content.
An import acknowledgement that persists foreign-keyed rows confirms create-path binding gaps.

## Adversarial Capabilities

This variant presupposes working sessions for at least an owner and a non-owner, with a second foreign principal where page comparison needs one.
It consumes the ability to craft adversarial page windows and cursors outside the cooperative sequence.
It consumes the ability to place foreign identifiers at chosen bulk positions and import rows.
Principal handling follows the procedure owned by `two-principal-authz`, named here rather than restated.

## Trust Assumptions

The feature executes under the agreement that an object reference arriving with a request is private to the caller, that any surrounding authorization already binds the referenced object to that caller, that identity arriving through surrounding channels belongs to the same caller, that a token accepted by one service transfers only to its intended audience, and that a check performed at creation still holds at retrieval, so no caller reaches data beyond its own scope.
The agreement fails when a set-level path validates the collection without rebinding each member to the caller.

## Key Vulnerabilities

Adversarial pagination with per-position verdicts is the bent step this variant owns over the parent.
Manipulate cursors and page windows to skip scoping filters, then compare each returned page against the control principal's page.
Inject foreign identifiers at mid-array and trailing bulk positions where first-element-only validation is suspected, and decide each position separately.
Submit structured imports carrying foreign owner and scope keys through the create-time path, then verify persistence per row.

## Bypass Techniques

Pollute duplicate paging fields with both orderings to probe which occurrence the scoping filter honors.
Coerce serialization framings across the bulk endpoint while holding positions constant, since per-item checks often differ per stack.
Treat race-window detail as owned by `race-conditions`, recording only the per-position authorization verdict here.

## Chaining Attacks

Feed identifiers harvested from list and search seeders into bulk positions and import rows.
Pivot a confirmed batch write into direct reads of the affected foreign objects to prove persistence.
Pivot a confirmed filter-skip into export endpoints that widen the exposed window, keeping each step's verdict separate.

## Testing Methodology

1. Derive the request shape from evidence by collecting client, interface, and history material, with completion when the real method, paging shapes, and bulk field shapes are inferable.
2. Build the subject-object-action matrix with one cell per set action, with completion when every bulk and paging action has an expected-principal cell.
3. Establish principals by acquiring one working session per matrix role, with completion when each role issues an authenticated baseline (procedure owned by `two-principal-authz`).
4. Seed the corpus by capturing valid identifiers per principal, with completion when foreign candidates exist for every position under test.
5. Skip filters adversarially by manipulating cursors and page windows outside the cooperative sequence, with completion when every paging action has an adversarial window beside its control window.
6. Decide per position by injecting foreign identifiers at first, middle, trailing, and import-row positions, with completion when every position carries its own verdict.
7. Verify persistence by rereading affected foreign objects under separated roles, with completion when each written row is confirmed present or absent rather than assumed.

## False Positives

Discard shared collections the design exposes to every member of a scope, confirming membership before filing.
Discard empty pages that reflect genuine filter enforcement rather than hidden data, comparing against the owner's view of the same window.
Discard metadata counts that aggregate without exposing member content, confirming no row data leaks.
Discard import rejections that quarantine foreign rows before persistence, verifying storage rather than trusting the acknowledgement.

## Pro Tips

Test list and search endpoints before bulk writes, since they seed identifiers and reveal filter claims together.
Decide every bulk position independently, since first-element validation masks mid-array gaps.
Vary page windows beyond the cooperative sequence, since filters often bind only the expected cursor.
Prove batch impact with role-separated rereads of each affected row, since acknowledgements overstate and understate alike.
Name the bypass family at parser-coercion steps rather than restating its mechanics.

## Summary

Set-level binding must tie the caller to every member, not to the collection container.
Skip each filter and decide each position, and file every member that answers a foreign caller.
