---
name: mass-assignment
description: Mass assignment testing for unauthorized field binding and privilege escalation via API parameters
metadata:
  version: 1.0.0
---

# Mass Assignment

Mass assignment binds client-supplied fields directly into models or data-transfer objects without field-level allowlists. It commonly leads to privilege escalation, ownership changes, and unauthorized state transitions in modern APIs and schema layers.

## Attack Surface

- Structured bodies, schema-layer inputs, form-encoded and multipart bodies
- Automatic model binding in controllers and resolvers; create and update helpers
- Writable nested relations, sparse and patch updates, bulk endpoints

## Reconnaissance

### Surface Map

- Handlers with automatic binding, where a request body reaches a model without a per-field map
- Schema-layer input types that mirror models; administrative tools exposed over the same API
- Interface descriptions and client bundles: forms and mutation payloads reveal field names
- Bulk and import paths, where per-item checks are often skipped

### Candidate Field Families

- Privilege and role fields: role, permission, and administrative marker fields
- Ownership and tenancy fields: user, owner, account, organization, tenant, and workspace references
- Limit and quota fields: usage limits, seat counts, project caps, credit balances
- Feature-gate fields: feature maps, flag lists, preview access, impersonation toggles
- Billing fields: price, amount, currency, proration, next invoice date, trial end

### Shape Variants

- Alternate shapes: arrays versus scalars, nested objects, objects under unexpected keys
- Path forms: dotted and bracketed keys reaching nested fields through different binders
- Duplicate keys, where precedence decides which value binds
- Sparse and patch formats: additive patch documents carrying forbidden paths

### Encodings and Channels

- Content types: structured, form-encoded, multipart, and plain text
- Schema-layer inputs: add candidate fields to input objects, then overfetch the response to detect change
- Bulk bodies: arrays of objects, verifying that per-item allowlists still apply

## Detection Channels

- A persisted value visible in a later read for the field under test, which binds the attempt to a verdict.
- Silent persistence without a corresponding echo in the response, which confirms a write the response never reflected.
- Per-position state inside a bulk request, where one slot persists a value the batch echo does not show.
- A per-position diff across roles, which separates a validated slot or field from a smuggled one.
- A child value persisted through a nested write and visible in a later child read or a parent overfetch.
- A silent nested persistence without parent echo, which confirms a write the response never reflected.
- A child-scope diff across roles, which separates a caller-permitted link from an out-of-scope write.
- A recomputed field that ignores the input, which marks a guarded field or slot rather than a success.
- A parent-only change with no child persistence, which marks a non-finding for the nested paths.
- Uniform rejection with nothing persisted, which marks a guarded batch rather than a finding.

## Adversarial Capabilities

Binding testing presupposes a writable resource per role, a candidate field list, and a read path that shows persisted state, and it consumes all three.
- Hold one session per role, including a low-privilege account and a second principal where ownership change is in question.
- Send arbitrary field sets alongside the legitimate update fields the client normally sends.
- Re-shape one field through every binder the application exposes.
- Read the resource back per item, per child relation, and per role after each attempt.
- Snapshot state before and after each attempt so a silent persistence is still visible.

## Trust Assumptions

The class rests on one agreement: the bind step maps exactly the fields the caller is entitled to set, whatever shape the request takes.
The agreement holds the field map to an allowlist at the boundary, holds every transport and shape to the same map, holds nested and child writes to the same per-field scope as the top level, and holds bulk requests to a per-item check rather than a boundary check once.
Sensitive position leaks when the bind step maps more than the caller may set: an extra flat field, a nested child, a mid-batch slot, or a shape another binder treats differently.
Each variant breaks one clause: the flat-field clause, the batch-scope clause, the nested-binding clause, or the shape-consistency clause.

## Key Vulnerabilities

### Privilege Escalation

- Set role, permission, or administrative markers during signup or profile update
- Toggle or add feature flags where the flag map is bound directly

### Ownership Takeover

- Change owner, account, or tenancy references to seize or relocate resources
- Move objects across principals or tenants through the same bind path

### Feature Gate and Limit Bypass

- Enable premium or preview flags through the flag fields
- Raise limits, seat counts, and quotas through their bound fields

### Billing and Entitlements

- Modify plan, price, proration, trial end, or credit balance fields
- Bypass server-side recomputation of derived financial values

### Nested and Relation Writes

- Writable nested serializers and relation helpers let a caller create or link related objects beyond its scope
- A nested write inside a batch position passes a boundary-only check

## Advanced Techniques

### Schema-Layer Inputs

- Field-level authorization missing on input types: attempt forbidden fields inside mutation inputs
- Combine with aliasing and batching to compare effects within one request
- Overfetch immediately after the mutation to see fields the response filtered

### Binding-Layer Edges

- Deep nesting features that reach child records through an authorized parent
- Blanket-permit configuration that opens every field, and type casts that mutate hidden fields
- Writable nested serializers with missing read-only marks and partial updates that skip validation
- Schema paths excluded from reads that nevertheless accept writes, and upsert defaults that fill unset fields

### Parser and Validator Gaps

- Validators that run after binding and cover only the expected fields
- Unknown fields dropped from the response but persisted underneath
- Inconsistent allowlists between clients or layers, where an alternate encoding bypasses the validation pipeline

## Bypass Techniques

### Content-Type Switching

- Switch structured, form-encoded, multipart, and plain-text bodies; some code paths validate only one
- Name the defence-bypass family at its parser step for content-type switching and key-path reshaping, rather than restating those mechanics here.

### Key Path Variants

- Dotted, bracketed, and object-reshaped keys reaching nested fields through different binders

### Batch Paths

- Per-item checks skipped in bulk operations; insert one hostile object inside a large batch

### Race and Reorder

- Race two updates: the first sets the forbidden field, the second normalizes; the final state may retain the change

When this section does not fulfil the knowledge gap, extend the reading with the defence-bypass and proxy-techniques families.

## Testing Methodology

1. **Identify endpoints** - Create and update endpoints, including schema-layer mutations
2. **Capture responses** - Observe returned fields to build the candidate list
3. **Build a sensitive-field dictionary** - Per resource: role, ownership, status, plan, limits, flags
4. **Inject candidates** - Alongside legitimate update fields, across transports and encodings
5. **Compare state** - Before-and-after diffs across roles, per item and per child relation
6. **Test variations** - Nested objects, arrays, alternate shapes, duplicate keys, and batch bodies; the step completes when every shape carries a persisted-or-rejected verdict

## Variants

- mass-assignment-nested-relation-write - Write child objects through serializers or relation helpers on singleton payloads, judging each child against caller scope.
- mass-assignment-bulk-collection-injection - Smuggle flat fields mid-batch past boundary-only validation, with per-position verdicts and aliased batch shapes.
- mass-assignment-bulk-nested-relation-write - Traverse child relations inside batch positions past boundary-only validation, with per-position child-scope verdicts.

## False Positives

- The server recomputing derived fields (plan, price, role) and ignoring the client input
- Fields marked read-only and enforced consistently across encodings
- Changes visible only in the interface with no persisted effect
- A batch rejection that persists nothing, which marks a guarded batch rather than a gap

## Pro Tips

1. Build a sensitive-field dictionary per resource and fuzz it systematically
2. Always try alternate shapes and encodings; many validators are shape-specific
3. In the schema layer, read the resource immediately after the mutation; the effect is often visible even when the response filters fields
4. Inspect client bundles and mobile payloads for hidden field names and nested write examples
5. Prefer minimal proofs that show durable state change; discard interface-only effects
6. Diff per position and per child, not per batch, so one smuggled slot is not hidden by an echoed batch

## Summary

Mass assignment is eliminated by explicit mapping plus per-field authorization. Treat every client-supplied attribute, especially nested and batch inputs, as untrusted until validated against an allowlist and the caller's scope.
