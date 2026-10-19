---
name: excessive-data-exposure
description: Single-response field over-exposure testing that reads an ordinary resource response against the caller's entitlement. Use when a raw response carries fields the rendered view never shows, when a serializer emits the full model, when an embedded related object exceeds the caller's scope.
metadata:
  version: 1.0.0
---

# Excessive Data Exposure

An ordinary resource response can carry more fields than the caller is entitled to see, because the serializer emits the full model and every client filters the excess.
This variant reads one response against the caller's entitlement: it maps the emitted field set, classifies each excess field by sensitivity, and concludes from that single response alone, with no second representation and no deployable artifact.

## Attack Surface

Applicability centers on a live resource response whose field set exceeds what the caller's scope renders: an object, a collection item, a nested related object, or an expansion of one.
The excess lives in the response body: credential and secret material, identity and contact values, internal notes and scoring fields, internal addresses and routing detail, audit and session metadata, and business-sensitive figures the interface never renders.
Embedded related objects widen the surface, because a resource may carry a full counterparty or member object whose fields the caller never sees.
Schema-driven selection widens the surface where the interface admits arbitrary field selection, because field-level authorization gaps admit names no rendered view requests.
Response metadata can widen the surface when internal or debug fields ride alongside an ordinary response.
Deployable artifacts and two-response differentials belong to the sibling variants, so this variant reads only the single ordinary response.

## Reconnaissance

Map the emitted field set before judging it, because an unlisted field is an unjudged one.
- Record the rendered field set per resource from the interface and the client, so the comparison target is explicit rather than assumed.
- Extract the full emitted field set per response, including nested objects, collection items, and expansion knobs, rather than judging the top level alone.
- Name the field families that matter per resource: credential material, identity and contact values, internal notes, scoring and risk figures, internal addresses, and audit or session metadata.
- Record which roles see which field sets, because a field entitled for one role and emitted for another is the finding.
- Treat a documented response schema as the entitlement statement to compare against where one exists.

## Detection Channels

Excess sensitive fields present in a single response to an entitled caller decides the finding.
A raw field set larger than the rendered field set for the same resource confirms over-exposure without a second representation.
A nested or embedded related object carrying fields beyond the caller's scope confirms a child-level excess.
A field whose sensitivity family exceeds the caller's rendered entitlement, present in the same response.
Response metadata carrying internal addresses, build identifiers, or routing detail alongside an ordinary response.
A field-selection channel that returns fields no rendered view requests, which confirms a field-level authorization gap.
A persisted identifier found in an excess field, which scopes follow-on requests rather than concluding the finding alone.

## Adversarial Capabilities

Field-set reading presupposes one authenticated session per role plus the rendered representation for comparison, and it consumes both.
- Hold sessions for the roles the resource serves, including a low-privilege principal and a second principal where embedded objects are in scope.
- Capture the rendered representation per resource, so the entitlement statement is explicit rather than assumed.
- Read raw responses outside the interface, where the excess is visible before any rendering filter applies.
- Extract nested and embedded field sets recursively, because embedded objects carry the highest-value excess.
- Classify each excess field by sensitivity family rather than reporting a field count.
- Principal handling follows the procedure owned by `two-principal-authz`, named here rather than restated.

## Trust Assumptions

At the moment the serializer answers a read, the feature trusts that the emitted field set equals the caller's entitlement scope.
The precise agreement is that a response carries exactly the fields the caller's scope renders: no credential material, no other party's fields, and no internal metadata beyond the entitlement.
The failing clause is the field-scope clause: the serializer emits the full model, and the rendered view's filtering carries no security.
The class agreement it breaks is the field-scope clause, while identity scope stays with the sibling variants and the principal step stays with `two-principal-authz`.

## Key Vulnerabilities

### Field-Set Comparison

- Compare the emitted field set against the rendered field set for the same resource and caller, and classify the difference by sensitivity rather than reporting every extra field.
- Judge nested and embedded objects with their own comparison, because a top-level field set can look entitled while an embedded object is not.
- Treat a documented response schema as the entitlement statement where one exists, and a mismatch between schema and response as the excess.

### Sensitivity Classification

- Classify excess fields by family: credential material, identity and contact values, internal notes and scoring, internal addresses and routing, audit and session metadata, and business-sensitive figures.
- Rank the finding by the highest sensitivity family present, not by the count of extra fields.
- Discard excess fields that carry no sensitivity and no follow-on value, because a hardening note is not a finding.

### Serializer and Selection Paths

- Test the caller's own object first, because own-object over-exposure needs no second principal and no reference swap.
- Test embedded related objects next, where a shared type renders fields beyond the caller's scope.
- Test field-selection channels where the interface admits arbitrary selection, because field-level authorization gaps admit names no rendered view requests.
- Name `idor` where an excess field hands over an identifier for a foreign object, and `graphql` for schema-dialect selection shapes.

## Advanced Techniques

- Compare field sets across roles for one resource: a field emitted to every role but rendered to none is the cleanest proof.
- Compare field sets across the resource's serializer paths, keeping the single-response discipline inside each read.
- Test paginated and collection responses, because later pages and later items can carry field sets the first item does not.
- Test the update response, which often echoes the full model after a partial write, naming `mass-assignment` where the echo also reflects a bind.
- Treat expansion and projection knobs as reach into fields the default read omits, naming the `idor` nested-expansion sibling where a projection crosses an object boundary.

## Chaining Attacks

- Excess identifiers to authorization: identifiers found in excess fields scope foreign-object requests whose access verdict the authorization classes own.
- Excess credential material to control planes: leaked keys and tokens scope the credential-validation and control-plane work the credential classes own.
- Excess internal metadata to surface mapping: internal addresses, service names, and routing detail scope further surface enumeration.
- Excess personal data to a cross-principal sweep: own-object over-exposure widens to other principals only where an identity-scope gap exists, which the authorization classes own.
- Each chain stops at a reversible proof or a stated architectural risk rather than a full exploit.

## Testing Methodology

1. **Map resources and rendered sets** - list the resources in scope with the rendered field set per caller role, and the step completes when each resource names its entitlement statement.
2. **Extract emitted field sets** - read each raw response and extract its full field set recursively, including nested objects, collection items, and expansion knobs, and the step completes when every resource carries an emitted set beside its rendered set.
3. **Diff and classify** - compute the excess per resource and classify each excess field by sensitivity family, and the step completes when every excess field carries a family verdict or a no-sensitivity verdict.
4. **Confirm from the single response** - verify that the excess is present in the ordinary response itself, with no second representation and no deployable artifact needed, and the step completes when every positive rests on the single response.
5. **Compare roles and serializer paths** - repeat the extraction per role and per serializer path for the same resource, and the step completes when each role and path carries a field-set verdict.
6. **Correlate to a chain** - map each excess to identifiers, credentials, internal metadata, or a cross-principal sweep, and the step completes when every excess carries a chain verdict or a no-chain verdict.

## False Positives

- Fields the interface renders after all, which makes the excess a rendering question rather than a leak; confirm against the rendered set before filing.
- Intentional public fields whose disclosure the design documents, such as display names and public identifiers.
- Owner-visible fields the caller is entitled to see, even when the interface renders them elsewhere.
- Excess fields with no sensitivity and no follow-on value, which are a hardening note rather than a finding.
- Fields masked or redacted consistently across every response, which marks a held control rather than an exposure.
- A field-count difference that disappears when the comparison holds the role and the serializer path constant.

## Pro Tips

1. Read raw responses outside the interface, because the rendering filter is where the excess hides.
2. Compare against the rendered field set explicitly rather than against intuition about what looks sensitive.
3. Extract nested and embedded objects recursively, since embedded counterparties carry the highest-value excess.
4. Rank by sensitivity family rather than field count, so one credential field outranks many cosmetic extras.
5. Test the caller's own object first: own-object over-exposure needs no second principal and no reference swap.
6. Check collection pages and update echoes, because both frequently emit field sets the default read omits.
7. Re-check each candidate against the role that is entitled to it, so an entitled field is never filed as excess.

## Summary

A serializer that emits the full model and trusts the client to filter it exposes fields the caller is not entitled to see.
Read one ordinary response against the caller's entitlement, classify the excess by sensitivity, and confirm the finding from that single response.
