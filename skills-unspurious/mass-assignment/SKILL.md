---
name: mass-assignment
description: Mass assignment testing for unauthorized field binding and privilege escalation via API parameters
metadata:
  version: 1.0.0
---

# Mass Assignment

Mass assignment binds client-supplied fields directly into models or data-transfer objects without field-level allowlists. It commonly leads to privilege escalation, ownership changes, and unauthorized state transitions in modern APIs and schema layers.

## Attack Surface

- **Input carriers**: structured bodies, schema-layer inputs, form-encoded and multipart bodies
- **Binding surfaces**: automatic model binding in controllers and resolvers; create and update helpers
- **Widening shapes**: writable nested relations, sparse and patch updates, bulk endpoints

## Reconnaissance

### Surface Map

- **Binding handlers**: handlers with automatic binding, where a request body reaches a model without a per-field map
- **Schema inputs**: schema-layer input types that mirror models; administrative tools exposed over the same API
- **Interface descriptions and client bundles**: forms and mutation payloads reveal field names, and an interface document that enumerates every model field is the candidate dictionary, including privileged fields the client never sends
- **Bulk and import paths**: where per-item checks are often skipped

### Candidate Field Families

- **Privilege and role fields**: role, permission, and administrative marker fields
- **Ownership and tenancy fields**: user, owner, account, organization, tenant, and workspace references
- **Limit and quota fields**: usage limits, seat counts, project caps, credit balances
- **Feature-gate fields**: feature maps, flag lists, preview access, impersonation toggles
- **Billing fields**: price, amount, currency, proration, next invoice date, trial end
- **Temporal and audit fields**: creation, update, and author markers whose binding rewrites provenance and audit trails
- **Verification and status fields**: verification markers, workflow-state fields, and ownership-transfer fields
- **Field dictionary reference**: the families, the binder shapes that carry them, and the read-back verification rule are in `references/field-dictionary.md`

### Shape Variants

- **Alternate shapes**: arrays versus scalars, nested objects, objects under unexpected keys
- **Path forms**: dotted and bracketed keys reaching nested fields through different binders
- **Duplicate keys**: where precedence decides which value binds
- **Sparse and patch formats**: additive patch documents carrying forbidden paths
- **Binder-specific shapes**: nested keys, bracketed paths, and update-operator forms that reach the model through a different binder than the plain field; probe one binder per attempt and record which one accepts the field, leaving the operator forms that belong to the query-language classes at their own step

### Encodings and Channels

- **Content types**: structured, form-encoded, multipart, and plain text
- **Schema-layer inputs**: add candidate fields to input objects, then overfetch the response to detect change
- **Bulk bodies**: arrays of objects, verifying that per-item allowlists still apply

## Detection Channels

- **Persisted value**: a persisted value visible in a later read for the field under test, which binds the attempt to a verdict.
- **Silent persistence**: silent persistence without a corresponding echo in the response, which confirms a write the response never reflected.
- **Per-position state**: per-position state inside a bulk request, where one slot persists a value the batch echo does not show.
- **Per-position diff**: a per-position diff across roles, which separates a validated slot or field from a smuggled one.
- **Persisted child value**: a child value persisted through a nested write and visible in a later child read or a parent overfetch.
- **Silent nested persistence**: a silent nested persistence without parent echo, which confirms a write the response never reflected.
- **Child-scope diff**: a child-scope diff across roles, which separates a caller-permitted link from an out-of-scope write.
- **Recomputed field**: a recomputed field that ignores the input, which marks a guarded field or slot rather than a success.
- **Parent-only change**: a parent-only change with no child persistence, which marks a non-finding for the nested paths.
- **Uniform rejection**: uniform rejection with nothing persisted, which marks a guarded batch rather than a finding.

## Adversarial Capabilities

- **Prerequisites**: binding testing presupposes a writable resource per role, a candidate field list, and a read path that shows persisted state, and it consumes all three.
- **Role sessions**: hold one session per role, including a low-privilege account and a second principal where ownership change is in question.
- **Field-set injection**: send arbitrary field sets alongside the legitimate update fields the client normally sends.
- **Binder reshaping**: re-shape one field through every binder the application exposes.
- **Read-back**: read the resource back per item, per child relation, and per role after each attempt.
- **State snapshot**: snapshot state before and after each attempt so a silent persistence is still visible.

## Trust Assumptions

- **The trust premise**: the class rests on one agreement: the bind step maps exactly the fields the caller is entitled to set, whatever shape the request takes.
- **The agreement**: it holds the field map to an allowlist at the boundary, holds every transport and shape to the same map, holds nested and child writes to the same per-field scope as the top level, and holds bulk requests to a per-item check rather than a boundary check once.
- **The exposure**: sensitive position leaks when the bind step maps more than the caller may set: an extra flat field, a nested child, a mid-batch slot, or a shape another binder treats differently.
- **The failing clause**: each variant breaks one clause: the flat-field clause, the batch-scope clause, the nested-binding clause, or the shape-consistency clause.

## Key Vulnerabilities

### Privilege Escalation

- **Marker binding**: set role, permission, or administrative markers during signup or profile update
- **Path-kind comparison**: test both path kinds per resource: a registration or create path binds as readily as an update path, and one of the two frequently carries the weaker field map
- **Hidden-field addition**: add administrative or workflow-state fields to a mutation the client never exposes, then confirm whether the transition commits
- **Flag toggling**: toggle or add feature flags where the flag map is bound directly

### Ownership Takeover

- **Reference change**: change owner, account, or tenancy references to seize or relocate resources
- **Cross-principal moves**: move objects across principals or tenants through the same bind path

### Feature Gate and Limit Bypass

- **Flag enabling**: enable premium or preview flags through the flag fields
- **Limit raising**: raise limits, seat counts, and quotas through their bound fields

### Billing and Entitlements

- **Financial field writes**: modify plan, price, proration, trial end, or credit balance fields
- **Recomputation bypass**: bypass server-side recomputation of derived financial values

### Nested and Relation Writes

- **Nested relation writes**: writable nested serializers and relation helpers let a caller create or link related objects beyond its scope
- **Batch-position nesting**: a nested write inside a batch position passes a boundary-only check

## Advanced Techniques

### Schema-Layer Inputs

- **Input-type gaps**: field-level authorization missing on input types: attempt forbidden fields inside mutation inputs
- **Alias and batch comparison**: combine with aliasing and batching to compare effects within one request
- **Post-mutation overfetch**: overfetch immediately after the mutation to see fields the response filtered

### Binding-Layer Edges

- **Deep nesting**: deep nesting features that reach child records through an authorized parent
- **Blanket permits and casts**: blanket-permit configuration that opens every field, and type casts that mutate hidden fields
- **Serializer marks**: writable nested serializers with missing read-only marks and partial updates that skip validation
- **Write-only paths**: schema paths excluded from reads that nevertheless accept writes, and upsert defaults that fill unset fields

### Parser and Validator Gaps

- **Post-bind validators**: validators that run after binding and cover only the expected fields
- **Dropped fields**: unknown fields dropped from the response but persisted underneath
- **Allowlist inconsistency**: inconsistent allowlists between clients or layers, where an alternate encoding bypasses the validation pipeline

## Bypass Techniques

### Content-Type Switching

- **Content-type switching**: switch structured, form-encoded, multipart, and plain-text bodies; some code paths validate only one
- **Family naming**: name the defence-bypass family at its parser step for content-type switching and key-path reshaping, rather than restating those mechanics here.

### Key Path Variants

- **Key path variants**: dotted, bracketed, and object-reshaped keys reaching nested fields through different binders

### Batch Paths

- **Batch paths**: per-item checks skipped in bulk operations; insert one hostile object inside a large batch

### Race and Reorder

- **Race and reorder**: race two updates: the first sets the forbidden field, the second normalizes; the final state may retain the change

When this section does not fulfil the knowledge gap, extend the reading with the defence-bypass and proxy-techniques families.

## Testing Methodology

1. **Identify endpoints** - Create and update endpoints, including schema-layer mutations
2. **Capture responses** - Observe returned fields to build the candidate list
3. **Build a sensitive-field dictionary** - Per resource: role, ownership, status, plan, limits, flags
4. **Inject candidates** - Alongside legitimate update fields, across transports and encodings
5. **Compare state** - Before-and-after diffs across roles, per item and per child relation
6. **Test variations** - Nested objects, arrays, alternate shapes, duplicate keys, and batch bodies; the step completes when every shape carries a persisted-or-rejected verdict

The per-field injection and read-back walk is driven by `scripts/mass-assignment-field-sweep`, which sends one candidate beside the legitimate body and reads the resource back for the verdict.

## Variants

- mass-assignment-nested-relation-write - Write child objects through serializers or relation helpers on singleton payloads, judging each child against caller scope.
- mass-assignment-bulk-collection-injection - Smuggle flat fields mid-batch past boundary-only validation, with per-position verdicts and aliased batch shapes.
- mass-assignment-bulk-nested-relation-write - Traverse child relations inside batch positions past boundary-only validation, with per-position child-scope verdicts.

## False Positives

- **Server recomputation**: the server recomputing derived fields (plan, price, role) and ignoring the client input
- **Read-only enforcement**: fields marked read-only and enforced consistently across encodings
- **Interface-only changes**: changes visible only in the interface with no persisted effect
- **Batch rejection**: a batch rejection that persists nothing, which marks a guarded batch rather than a gap
- **Reverted probe**: a destructive probe that was reverted to the original value before the diff, which proves nothing about the bind; restore the original value only after the persistence verdict is recorded

## Pro Tips

- **Dictionary first**: build a sensitive-field dictionary per resource and fuzz it systematically
- **Shape variation**: always try alternate shapes and encodings; many validators are shape-specific
- **Immediate read-back**: in the schema layer, read the resource immediately after the mutation; the effect is often visible even when the response filters fields
- **Client mining**: inspect client bundles and mobile payloads for hidden field names and nested write examples
- **Minimal proofs**: prefer minimal proofs that show durable state change; discard interface-only effects
- **Per-position diffing**: diff per position and per child, not per batch, so one smuggled slot is not hidden by an echoed batch
- **Destructive-probe discipline**: on a destructive update path, record the persistence verdict first and restore the original value afterwards, so the probe leaves no lasting change and the verdict rests on a real diff

## Summary

Mass assignment is eliminated by explicit mapping plus per-field authorization. Treat every client-supplied attribute, especially nested and batch inputs, as untrusted until validated against an allowlist and the caller's scope.
