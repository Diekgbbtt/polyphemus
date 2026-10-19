# Field Dictionary

The dictionary is built per resource before any injection: the field families decide what to try, and the binder shapes decide how each family reaches the model.
It serves the reconnaissance and the injection steps of the `mass-assignment` class and the shape step of its leaves.
The dictionary completes when every resource carries a candidate list, every candidate carries a binder shape, and every attempt carries a persisted-or-rejected verdict from a read-back.

## Field Families

- **Privilege and role**: role, permission, and administrative marker fields, including the plural and array forms a role set is carried in.
- **Ownership and tenancy**: user, owner, account, organization, tenant, workspace, and project references.
- **Limit and quota**: usage limits, seat counts, project caps, and credit balances.
- **Feature gates**: feature maps, flag lists, preview access, and impersonation toggles.
- **Billing and entitlements**: plan, price, amount, currency, proration, trial end, and next-invoice fields.
- **Temporal and audit**: creation, update, and author markers, whose binding rewrites provenance and the audit trail.
- **Verification and status**: verification markers, workflow-state fields, and ownership-transfer fields.
- **Administrative and override markers**: status, override, and approval fields a client never sends but a handler accepts.

## Binder Shapes

One field family is tried through every binder the application exposes, because the allowlist frequently differs per binder.

- **Flat member**: the field as a top-level key of the body.
- **Nested object**: the field under an unexpected parent key, which reaches a child binder the top-level allowlist never inspects.
- **Dotted path**: the field addressed through a dotted key.
- **Bracketed path**: the field addressed through a bracketed key, which a form binder resolves differently from a structured one.
- **Array-for-scalar**: a set supplied where a single value was expected, including a role array.
- **Array of objects**: a list of child documents bound in one request.
- **Sparse or patch document**: an additive patch that carries a forbidden path.
- **Upsert default**: an unset field filled by the binder's own default rather than by the request.
- **Update-operator form**: the operator shapes that belong to the query-language classes, named at their step rather than restated here.
- **Duplicate member**: the same field sent twice, because precedence decides which value binds.

## Dictionary Sources

- Interface documents that enumerate every model field, including the privileged ones the client never sends.
- Client bundles, mobile payloads, and lazily loaded chunks, which carry the field names the client does send and hints at those it does not.
- Response bodies whose field set exceeds what the client sent, which name the model directly.
- Import and export templates, which enumerate the writable surface in bulk.
- Validation and error text that names a field the surface rejected.
- Prior traffic and a second role's payloads, where the field sets differ.

## Read-Back Verification

- Re-read the resource after every attempt, because an echoed field is not a persisted field and a filtered response is not a rejection.
- Diff the state per role, per item of a batch, and per child relation, so one smuggled position is not hidden by a batch echo.
- Treat a recomputed field as a guarded field rather than a success, since a server that ignores the input may still persist it elsewhere.
- On a destructive update path, record the persistence verdict first and restore the original value afterwards, so the probe leaves no lasting change and the verdict rests on a real diff.

## Delegation

- Content-type switching and key-path reshaping are named at the parser step owned by the `defence-bypass` family.
- Duplicate-member precedence is owned by `defence-bypass-parser-confusion` and `http-parameter-pollution`.
- The operator forms that reach a document store are owned by the query-language classes.
- Nested child writes are owned by `mass-assignment-nested-relation-write`; mid-batch positions by the bulk leaves.
- The authorization verdict behind an ownership change is owned by the authorization classes.

## False Positives

- A field the server recomputes and ignores, confirmed by a read-back that shows the original value.
- A field marked read-only and enforced consistently across every binder shape.
- A change visible only in the response with no persisted effect.
- A uniform rejection across every shape, which marks a guarded field rather than a gap.
