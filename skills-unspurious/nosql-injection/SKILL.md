---
name: nosql-injection
description: NoSQL injection testing covering operator injection, authentication bypass, blind extraction, GraphQL variable injection, and datastore-specific attack surfaces
metadata:
  version: 1.0.0
---

# NoSQL Injection

NoSQL injection exploits the mismatch between how applications pass user input to a store and how the store interprets it. Unlike SQL injection, it frequently takes the shape of operator embedding (a comparison or pattern operator where a value was expected) or structure injection (a nested document where a scalar was expected). The surface spans store families: document stores with filter operators, key-value stores with command framing, search engines with a query grammar, wide-column stores with a statement grammar, graph stores with a clause grammar, and schema-layer resolvers that pass variables straight into any of them.

## Attack Surface

**Input shapes that reach store queries**
- **Structured body parameters**: parsed straight into filter objects.
- **Bracket notation**: form fields with bracket notation, coerced into operator objects by the framework's body parser.
- **Encoded structured values**: in query strings, headers, and cookies.
- **Schema-layer variables**: passed directly into resolver-level filters.

**Code patterns that enable injection**
- **Raw filter objects**: taken from user input and handed to find or aggregate calls.
- **String concatenation**: into query grammars instead of the driver's parameterized form.
- **Object-document mapper passthrough**: where schema filtering is disabled or raw query helpers are exposed.
- **Server-side script surfaces**: where filter or aggregation stages accept executable function bodies.

**Store families in scope**
- **Document stores**: with filter operators and aggregation stages.
- **Key-value stores**: with command framing.
- **Search engines**: with a query grammar and scripted updates.
- **Wide-column stores**: with SQL-shaped statements.
- **Graph stores**: with clause grammars and procedure calls.
- **Compatible engines**: that follow one of the above models.

## Reconnaissance

### Input Shape and Encoding

- **Structured-body endpoints**: identify endpoints accepting structured bodies, which can receive operator objects directly.
- **Bracket-notation endpoints**: identify form-accepting endpoints, where bracket notation maps to an operator object in many frameworks.
- **Backend resolution**: determine whether the backend uses a mapper layer, the native driver, or a REST wrapper.

### Error Fingerprinting

- **Malformed-value probe**: send malformed values shaped like operator objects and read the error text.
- **Error-text reading**: look for driver and cast errors, validation errors, and stack traces naming collections, fields, and versions.

### Operator Probe

- **Pass-through test**: test whether operators pass through to the store: send a comparison operator where the endpoint expects a literal.
- **Success confirmation**: a login or filter success no literal could produce confirms operator injection.

## Detection Channels

- **Driver error text**: driver error and validation text names collections, fields, or cast failures after malformed operator objects.
- **Boolean differential**: a boolean response, status, or redirect difference appears between a true predicate and its false pair.
- **Impossible success**: a login or filter success comes from an operator predicate that no literal value could satisfy.
- **Progressive narrowing**: progressive match narrowing appears across iterated pattern prefixes during character-by-character extraction.
- **Enablement answer**: an enablement-state answer distinguishes an open script engine gate from a closed one.
- **Sleep-driven latency**: a sleep-driven latency differential appears between a truth branch that pauses and one that returns immediately.
- **Stage-error text**: stage-error text names stages, collections, or field paths after malformed stage fragments.
- **Cross-scope response**: response content comes from a collection outside the intended scope after a pivot attempt.
- **Join-cost signal**: latency or volume changes from heavy join stages across large unindexed collections.
- **Framing-error text**: framing-error text after delimiter probes names command or argument expectations.
- **Smuggled-key read**: a follow-on read shows a smuggled key with attacker-chosen content.
- **Parser error text**: parser error and syntax text appears after quote and metacharacter probes.
- **Widening differential**: hit-count or content widening appears between a literal control and a metacharacter attempt.
- **Vocabulary disclosure**: index and mapping listing content reveals fields and labels for the next fragment.
- **External-fetch callback**: an external-fetch callback fires where a procedure surface reaches an attacker-observed location.

## Adversarial Capabilities

- **Store injection testing**: presupposes a query-reaching input, knowledge of the store family, and a boolean or timing oracle, and it consumes all three.
- **Query-reaching parameter**: reach a parameter that flows into a filter, a statement, a command frame, or a pipeline stage.
- **Delivery coverage**: send structured, form-encoded, and encoded values so the operator passes whichever way the parser accepts.
- **Second principal**: hold a second principal and a privileged target so a bypass converts into data or action.
- **Oracle reading**: read boolean, status, redirect, latency, and volume differences as oracle answers.
- **Store fingerprinting**: fingerprint the store family and its script-engine state before choosing a technique.
- **No-effect oracles**: trigger callbacks or delays as no-effect oracles before extraction.

## Trust Assumptions

- **The agreement**: user input reaches the store as a value, never as query structure.
- **Held clauses**: the agreement holds every input to a typed scalar before it enters the query, holds the query grammar to the application's own fragments, holds script and procedure surfaces closed to unprivileged callers, and holds each stage or frame to the single operation the application intended.
- **Leak condition**: sensitive data and control leak when structure is caller-controlled: an operator changes the predicate, a delimiter splits the frame, a grammar fragment widens the match, or a script body executes.
- **The failing clause**: each variant breaks one clause: the value clause, the grammar clause, the script-surface clause, the stage clause, or the frame clause.

## Key Vulnerabilities

### Operator Predicate Injection

- **Classic bypass**: a filter object whose fields carry comparison operators instead of values matches the first document that satisfies them.
- **Encodings**: structured body objects, form bracket notation, and encoded structured values in other carriers.
- **Variations**: a literal for one field plus an operator for another, pattern operators matching any value, and set-membership operators listing candidate identities.

### Blind Extraction Through Pattern Operators

- **Extraction condition**: when results are not reflected but observable through a boolean, redirect, status, or timing difference, extract field values character by character with pattern operators.
- **Binary search**: binary search over the character space minimizes requests.
- **Field coverage**: the technique works on any string field, including recovery tokens and API keys.

### Server-Side Script Injection

- **Script surfaces**: filter and aggregation surfaces accepting executable function bodies run attacker script in the store process.
- **Observable shapes**: timing oracles via sleep, and truth branches that return documents, are the two observable shapes.
- **Engine gate**: the same engine gate governs filter-level and aggregation-level script; aggregation paths are often the reachable one when the filter surface is filtered.

### Aggregation Pipeline Injection

- **Stage parity**: match, lookup, and projection stages accept the same operator payloads as plain finds.
- **Caller-controlled lookup**: a caller-controlled lookup target is the highest-impact shape: it pivots the query to a different collection and returns cross-scope data.
- **Stage-versus-row targeting**: stage targeting differs from row filtering, so a filtered find surface does not imply a filtered pipeline surface.

### Key-Value Command Smuggling

- **Delimiter splitting**: where commands are built by string concatenation, injected delimiters split one command into several.
- **Follow-on read**: the follow-on read shows whether the extra command took effect.
- **Framing-error text**: framing-error text reveals the command and argument expectations.

### Query-Language Injection

- **Metacharacter widening**: search and graph query grammars accept metacharacters that widen a match, list fields, or chain clauses.
- **Wildcard enumeration**: wildcards and existence probes enumerate documents without a filter.
- **Procedure calls**: procedure calls in graph surfaces fetch external resources or run dynamic queries when enabled.

### Statement Grammar Injection

- **Clause injection**: SQL-shaped wide-column stores follow the classic pattern where input is concatenated instead of bound: clause injection, always-true predicates, and chained clauses.
- **Detection limits**: no sleep or out-of-band primitive is available on these surfaces, so detection is boolean or error-based.

### Schema-Layer Variable Injection

- **Variable passthrough**: resolvers passing variables straight into a store filter turn any input type that accepts arbitrary objects into an operator candidate.
- **Introspection**: introspection enumerates which input types accept objects rather than scalars.
- **Aliasing and batching**: combine with aliasing and batching to compare verdicts inside one request.

### Exhaustion Surfaces

- **Backtracking**: catastrophic backtracking through nested pattern operators against long values.
- **Membership arrays**: very large membership arrays forcing linear scans on unindexed fields.
- **Script loops**: unbounded script loops where the engine accepts them without query timeouts.
- **Join stages**: chained heavy join stages across large unindexed collections.

## Advanced Techniques

### Engine State Fingerprinting

- **Gate establishment**: establish the script-engine gate and the server version before investing in script payloads; both decide feasibility.
- **One-request answer**: error text and status endpoints answer the gate question in one request.

### Blind Integration

- **Cross-checking**: combine the boolean oracle with timing to cross-check predicate truth where responses are partly masked.
- **Extraction discipline**: treat extraction as one letter per request across the partial space, halving with binary search.

### Escalation After Bypass

- **Durable access**: convert an authentication bypass into durable access with a second request to a privileged surface.
- **Narrowest read**: prefer the narrowest read that proves the scope break.

## Bypass Techniques

**Type Coercion**
- **Array coercion**: send operators as arrays, where some drivers coerce them; mix string and object types in one request to trigger parser branches.

**Encoding**
- **Bracket encoding**: encode brackets and operator markers; double-encode where a filter sits in front of a structured-body backend.

**Operator Alternatives**
- **Operator substitution**: substitute operators that reach the same result when the obvious one is filtered, and wrap one operator inside another.
- **Expression contexts**: expression contexts carry comparisons the top-level filter rejects.

**Structure Manipulation**
- **Dotted keys**: dotted keys versus nested objects, where sanitizers strip one form and pass the other.
- **Wrapping disagreement**: array versus object operator wrapping, where parsers disagree on which is the operator.
- **Prototype keys**: prototype keys in structured bodies that pollute shared objects consumed by the query builder.
- **Case-insensitive flags**: case-insensitive pattern flags that widen matches case-sensitive filters miss.

When this section does not fulfil the knowledge gap, extend the reading with the defence-bypass and proxy-techniques families.

## Testing Methodology

1. **Identify query-receiving endpoints** - Login, search, filter, lookup
2. **Determine the input format** - Structured body, form fields, query parameters
3. **Send error-probing values** - Malformed operator objects; watch for driver errors
4. **Attempt operator injection** - Comparison, pattern, and set-membership operators against the login surface
5. **Confirm the boolean oracle** - Response, status, or redirect differs between true and false predicates
6. **Extract blindly** - Character-by-character pattern operators on the sensitive fields
7. **Test script surfaces** - Where the engine gate is open, attempt a timing script body
8. **Probe aggregation surfaces** - Inject operators into the filter, match, and sort fields
9. **Probe the other store families** - Command framing, query grammar, statement grammar, graph clauses
10. **Test schema-layer resolvers** - Submit operator objects through variables on any input type reaching a store filter

## Variants

- nosql-operator-injection - Embed query operators in filter input to bypass checks and extract fields, using boolean differentials as the oracle.
- nosql-server-side-script-injection - Place executable function bodies in filter and aggregation expressions, using sleep-driven timing for blind predicates.
- nosql-aggregation-pipeline-injection - Steer aggregation stages and collection pivots with crafted input where filters, matches, and sorts feed pipeline construction.
- nosql-query-language-injection - Break escaping in graph, search, and statement grammars where input concatenates into clauses.
- nosql-command-protocol-smuggling - Split one key-value request into extra commands where key or value text concatenates into command construction.

## False Positives

- **String-casting builder**: a query builder that casts input to a string before constructing the query.
- **Operator-key sanitization**: sanitization that strips operator keys before they reach the driver.
- **Sensitive-field casting**: endpoints that accept structured bodies but cast the sensitive field to a string, turning an operator object into a literal rendering.
- **Validation differences**: response differences caused by validation errors rather than operator execution.

## Pro Tips

- **Envelope coverage**: try both the structured body and the bracket-notation form; different middleware handles them differently.
- **Field targeting**: target recovery-token and key fields with pattern extraction, not only passwords.
- **Early fingerprinting**: fingerprint the engine gate and version early; it decides whether script surfaces are worth probing.
- **Listing surfaces**: for search engines, try listing and mapping surfaces before scripted updates.
- **Escalation**: combine a bypass with a second request to a privileged surface to escalate impact.
- **Extraction automation**: automate pattern extraction with binary search: a handful of requests per character.
- **Resolver entry point**: schema-layer resolvers are an underexplored entry point; try operator objects in any input type that reaches a store filter.

## Summary

NoSQL injection has the same root cause as SQL injection - user input controlling query structure - reached through operator embedding rather than syntax breaking.
Enforce typed schema validation, bind values through the driver's parameterized form, keep script surfaces closed, and never pass raw user input as a query object.
