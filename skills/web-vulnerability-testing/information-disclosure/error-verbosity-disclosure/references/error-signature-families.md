# Error Signature Families

A verbose failure is read, not collected: the signature family names what the output reveals and which follow-on it scopes.
This reference holds the signature families, their read-outs, and the trigger discipline behind the class's controlled-failure step.
It serves the trigger step and the debug-enumeration step of `error-verbosity-disclosure`.
The read completes when every triggered failure carries a signature verdict and every signature names its follow-on or a no-chain verdict.

## Trigger Set

Break one assumption per attempt, so the failing assumption is attributable rather than bundled.

- A wrong type where a scalar was expected.
- A malformed body where a structured document was expected.
- A missing field the surface requires.
- An oversized or boundary-length value in a bounded field.
- A null-byte or truncation shape inside a string field.
- An unexpected content type, including the alternate serialization the surface also accepts.
- An alternate verb or framing, where one handler renders differently from its siblings.

## Signature Families

- **Stack frame with a path**: an absolute path, a source line, and a module name reveal the deployment layout, the module boundaries, and the framework family, which scopes an inclusion or file-read attempt.
- **Query text with a driver code**: the echoed statement and the storage engine's own error code reveal the schema, the table and column names, and sometimes the whole predicate, which scopes an injection attempt.
- **Template compile error with a line number**: the template engine and the template's own source path reveal where a rendered value is evaluated, which scopes a server-side template attempt.
- **Dependency banner with a version**: the exact component version scopes the version-to-known-flaw chain, so the version is only useful beside a reachable surface.
- **Object-graph or serializer dump**: a body that renders the whole model reveals field names, including fields no rendered view carries, which scopes a field-level authorization or write attempt.
- **Validation error naming an internal rule or field**: the boundary that rejected the input reveals the field vocabulary and the rule order, which scopes the next candidate shape.
- **Debug console or profiler answer**: an interactive surface behind the renderer confirms a live execution context, which is a stronger finding than the failure output itself.
- **Failure-adjacent tracing or timing metadata**: handling stages narrated beside the failure reveal internal hops the response never intended to expose.
- **Fail-open execution**: a failure path that executes the action rather than narrating it is an effect rather than a disclosure, so it needs its own before-and-after effect proof.

## Reading Discipline

- Record a baseline rendering per surface first, so a later divergence attributes to the trigger rather than to the surface.
- Normalize before diffing, because boilerplate can pose as signal.
- Treat one verbose field as a pivot: its vocabulary names the next trigger class to try.
- A signature that repeats a public banner or a documented message carries no finding.
- Keep the trigger set and the signature set separate: one trigger may produce several families, and one family may appear under several triggers.

## Delegation

- Debug and profiler surface enumeration is owned by the `error-verbosity-disclosure` body; only the signature read is recorded here.
- The version-to-known-flaw chain is owned by the `information-disclosure` chaining section.
- The path-to-file-read chain is owned by the file-access classes.
- The disclosure-to-authorization chain is owned by the authorization classes, which own the access verdict.

## False Positives

- A generic failure with no actionable detail.
- A documented message reachable through the same surface by design.
- A version banner with no reachable vulnerable surface and no chain.
- A redacted field that leaves no triggerable delta.
