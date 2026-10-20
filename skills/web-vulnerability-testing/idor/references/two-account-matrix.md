# Two-Account Swap Matrix

The matrix is the class's adjudication apparatus: one control pair per cell, one verdict per cell, and a blind differential wherever content stays masked.
It serves the swap leaves and the parent alike, and it is the same apparatus `two-principal-authz` states as the shared agreement.
The matrix completes when every action on every object carries a swapped attempt beside its unchanged control, and every cell carries a decided verdict rather than an assumption.

## The Matrix

- **Rows**: one per action, read, write, delete, export, and each nested child action the surface exposes.
- **Columns**: one per principal, at least an owner and a non-owner, plus a privileged principal where vertical access is in scope.
- **Cell**: the expected outcome recorded before testing, then the observed outcome beside it.
- **The control pair**: the owner's request and the foreign request under identical shaping, with only the reference differing, so a success attributes to the binding rather than to the stack.
- **The stack control**: one endpoint that is demonstrably gated on the same stack, so a differing response across a route family attributes to the binding rather than to the routing.
- **Completion**: every action carries a pair, and every pair carries a verdict.

## Reference-Form Probe Table

A parser that coerces one form can match a broader set than the gate expects, so one identifier is probed through every form the binder accepts.

- **Plain reference**: the identifier as the application issued it.
- **Set-wrapped reference**: the identifier inside an array, including a foreign member placed beside an owned one.
- **Wildcard and glob forms**: a pattern that the lookup expands into a set rather than a single object.
- **Boolean and zero forms**: values that coerce into a broader match than the gate intended.
- **Negative and fractional forms**: numeric shapes a comparison treats as valid while the gate inspected another type.
- **Keyword swap**: the self-referential keyword replaced by a numeric or opaque identifier, so the lookup stops resolving from session context.
- **Extension-appended path form**: the same resource reached through a decorated path, which frequently skips the middleware.
- **Nested wrapper**: the identifier carried inside an unexpected object or key.
- **Duplicate member**: the reference sent twice with both orderings, because precedence decides which value reaches the lookup.
- **Alias and case spellings**: the reference name respelled so the gate and the lookup read different fields.

Each form carries its own verdict, because one refused form proves nothing about the next.

## Masked-Response Differentials

Where content stays masked, the verdict rests on the differential rather than on the body.

- **Status, size, and timing** between the control and the swapped attempt.
- **Error shape**: a different error for owned and foreign identifiers signals a missing binding even when no content returns.
- **Validators**: conditional-request validators that match for a foreign object confirm its existence without full content.
- **Empty versus withheld**: an empty result for the foreign identifier beside a full owner view reads as silent enforcement, so confirm the data is withheld rather than hidden by the response shape.
- **Count and window anomalies**: a page or count that exceeds the control window confirms a scope failure without reading full content.

## Temporal Re-check

The binding must hold at the moment of use, so re-run the pair after the principal changes.

- After a removal, revocation, or downgrade, because a cached authorization context may still pass.
- After a soft delete, because an identifier that still resolves keeps the access alive.
- After a policy or role change, because a persisted grant may outlive its rule.

## Verdict Vocabulary

- **Foreign-content**: the non-owner received the owner's content or metadata.
- **Foreign-effect**: a write under the non-owner's session landed on the owner's object and persisted.
- **Scope-gap**: a list, export, or count surface returned the owner's objects without full content.
- **Per-item gap**: one member of a batch, or one position of a bulk body, resolved without its own check.
- **Per-hop gap**: a child object returned inside an authorized parent without its own check.
- **Temporal gap**: the reference still resolved after the principal or the policy changed.
- **No-binding**: the reference resolved with no caller check at all, so any principal naming it reached it.
- **Silent enforcement**: the foreign attempt returned an empty or opaque shape while the owner view held data.

## Delegation

- Principal handling and the shared agreement are owned by `two-principal-authz`.
- Duplicate-member precedence is owned by `defence-bypass-parser-confusion` and `http-parameter-pollution`.
- The server-side URL builder as a second reader is noted in this bundle and its mechanism is owned by `proxy-techniques-url-parser-differential`.
- Schema-layer query and projection shapes are owned by `graphql`, named at the resolver step.
- The timing primitive behind a swap between check and use is owned by `race-conditions`.

## False Positives

- A public or intentionally shared object reached by design.
- Success on an identifier the second principal created itself.
- An empty result for the foreign identifier that is genuine withholding rather than a hidden response.
- A single wrong-verb or placeholder-identifier attempt judged as a refusal.
- A metadata lookup that returns no sensitive content for the foreign identifier.
