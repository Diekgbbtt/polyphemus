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
- Structured body parameters parsed straight into filter objects
- Form fields with bracket notation, coerced into operator objects by the framework's body parser
- Encoded structured values in query strings, headers, and cookies
- Schema-layer variables passed directly into resolver-level filters

**Code patterns that enable injection**
- Raw filter objects taken from user input and handed to find or aggregate calls
- String concatenation into query grammars instead of the driver's parameterized form
- Object-document mapper passthrough, where schema filtering is disabled or raw query helpers are exposed
- Server-side script surfaces, where filter or aggregation stages accept executable function bodies

**Store families in scope**
- Document stores with filter operators and aggregation stages
- Key-value stores with command framing
- Search engines with a query grammar and scripted updates
- Wide-column stores with SQL-shaped statements
- Graph stores with clause grammars and procedure calls
- Compatible engines that follow one of the above models

## Reconnaissance

### Input Shape and Encoding

- Identify endpoints accepting structured bodies, which can receive operator objects directly
- Identify form-accepting endpoints, where bracket notation maps to an operator object in many frameworks
- Determine whether the backend uses a mapper layer, the native driver, or a REST wrapper

### Error Fingerprinting

- Send malformed values shaped like operator objects and read the error text
- Look for driver and cast errors, validation errors, and stack traces naming collections, fields, and versions

### Operator Probe

- Test whether operators pass through to the store: send a comparison operator where the endpoint expects a literal
- A login or filter success no literal could produce confirms operator injection

## Detection Channels

- Driver error and validation text naming collections, fields, or cast failures after malformed operator objects.
- Boolean response, status, or redirect difference between a true predicate and its false pair.
- Login or filter success from an operator predicate that no literal value could satisfy.
- Progressive match narrowing across iterated pattern prefixes during character-by-character extraction.
- An enablement-state answer distinguishing an open script engine gate from a closed one.
- Sleep-driven latency differential between a truth branch that pauses and one that returns immediately.
- Stage-error text naming stages, collections, or field paths after malformed stage fragments.
- Response content from a collection outside the intended scope after a pivot attempt.
- Latency or volume change from heavy join stages across large unindexed collections.
- Framing-error text after delimiter probes that names command or argument expectations.
- A follow-on read showing a smuggled key with attacker-chosen content.
- Parser error and syntax text after quote and metacharacter probes.
- Hit-count or content widening between a literal control and a metacharacter attempt.
- Index and mapping listing content revealing fields and labels for the next fragment.
- An external-fetch callback where a procedure surface reaches an attacker-observed location.

## Adversarial Capabilities

Store injection testing presupposes a query-reaching input, knowledge of the store family, and a boolean or timing oracle, and it consumes all three.
- Reach a parameter that flows into a filter, a statement, a command frame, or a pipeline stage.
- Send structured, form-encoded, and encoded values so the operator passes whichever way the parser accepts.
- Hold a second principal and a privileged target so a bypass converts into data or action.
- Read boolean, status, redirect, latency, and volume differences as oracle answers.
- Fingerprint the store family and its script-engine state before choosing a technique.
- Trigger callbacks or delays as no-effect oracles before extraction.

## Trust Assumptions

The class rests on one agreement: user input reaches the store as a value, never as query structure.
The agreement holds every input to a typed scalar before it enters the query, holds the query grammar to the application's own fragments, holds script and procedure surfaces closed to unprivileged callers, and holds each stage or frame to the single operation the application intended.
Sensitive data and control leak when structure is caller-controlled: an operator changes the predicate, a delimiter splits the frame, a grammar fragment widens the match, or a script body executes.
Each variant breaks one clause: the value clause, the grammar clause, the script-surface clause, the stage clause, or the frame clause.

## Key Vulnerabilities

### Operator Predicate Injection

- The classic bypass: a filter object whose fields carry comparison operators instead of values matches the first document that satisfies them
- Encodings: structured body objects, form bracket notation, and encoded structured values in other carriers
- Variations: a literal for one field plus an operator for another, pattern operators matching any value, and set-membership operators listing candidate identities

### Blind Extraction Through Pattern Operators

- When results are not reflected but observable through a boolean, redirect, status, or timing difference, extract field values character by character with pattern operators
- Binary search over the character space minimizes requests
- The technique works on any string field, including recovery tokens and API keys

### Server-Side Script Injection

- Filter and aggregation surfaces accepting executable function bodies run attacker script in the store process
- Timing oracles via sleep, and truth branches that return documents, are the two observable shapes
- The same engine gate governs filter-level and aggregation-level script; aggregation paths are often the reachable one when the filter surface is filtered

### Aggregation Pipeline Injection

- Match, lookup, and projection stages accept the same operator payloads as plain finds
- A caller-controlled lookup target is the highest-impact shape: it pivots the query to a different collection and returns cross-scope data
- Stage targeting differs from row filtering, so a filtered find surface does not imply a filtered pipeline surface

### Key-Value Command Smuggling

- Where commands are built by string concatenation, injected delimiters split one command into several
- The follow-on read shows whether the extra command took effect
- Framing-error text reveals the command and argument expectations

### Query-Language Injection

- Search and graph query grammars accept metacharacters that widen a match, list fields, or chain clauses
- Wildcards and existence probes enumerate documents without a filter
- Procedure calls in graph surfaces fetch external resources or run dynamic queries when enabled

### Statement Grammar Injection

- SQL-shaped wide-column stores follow the classic pattern where input is concatenated instead of bound: clause injection, always-true predicates, and chained clauses
- No sleep or out-of-band primitive is available on these surfaces, so detection is boolean or error-based

### Schema-Layer Variable Injection

- Resolvers passing variables straight into a store filter turn any input type that accepts arbitrary objects into an operator candidate
- Introspection enumerates which input types accept objects rather than scalars
- Combine with aliasing and batching to compare verdicts inside one request

### Exhaustion Surfaces

- Catastrophic backtracking through nested pattern operators against long values
- Very large membership arrays forcing linear scans on unindexed fields
- Unbounded script loops where the engine accepts them without query timeouts
- Chained heavy join stages across large unindexed collections

## Advanced Techniques

### Engine State Fingerprinting

- Establish the script-engine gate and the server version before investing in script payloads; both decide feasibility
- Error text and status endpoints answer the gate question in one request

### Blind Integration

- Combine the boolean oracle with timing to cross-check predicate truth where responses are partly masked
- Treat extraction as one letter per request across the partial space, halving with binary search

### Escalation After Bypass

- Convert an authentication bypass into durable access with a second request to a privileged surface
- Prefer the narrowest read that proves the scope break

## Bypass Techniques

**Type Coercion**
- Send operators as arrays, where some drivers coerce them; mix string and object types in one request to trigger parser branches

**Encoding**
- Encode brackets and operator markers; double-encode where a filter sits in front of a structured-body backend

**Operator Alternatives**
- Substitute operators that reach the same result when the obvious one is filtered, and wrap one operator inside another
- Expression contexts carry comparisons the top-level filter rejects

**Structure Manipulation**
- Dotted keys versus nested objects, where sanitizers strip one form and pass the other
- Array versus object operator wrapping, where parsers disagree on which is the operator
- Prototype keys in structured bodies that pollute shared objects consumed by the query builder
- Case-insensitive pattern flags that widen matches case-sensitive filters miss

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

- A query builder that casts input to a string before constructing the query
- Sanitization that strips operator keys before they reach the driver
- Endpoints that accept structured bodies but cast the sensitive field to a string, turning an operator object into a literal rendering
- Response differences caused by validation errors rather than operator execution

## Pro Tips

1. Try both the structured body and the bracket-notation form; different middleware handles them differently
2. Target recovery-token and key fields with pattern extraction, not only passwords
3. Fingerprint the engine gate and version early; it decides whether script surfaces are worth probing
4. For search engines, try listing and mapping surfaces before scripted updates
5. Combine a bypass with a second request to a privileged surface to escalate impact
6. Automate pattern extraction with binary search: a handful of requests per character
7. Schema-layer resolvers are an underexplored entry point; try operator objects in any input type that reaches a store filter

## Summary

NoSQL injection has the same root cause as SQL injection - user input controlling query structure - reached through operator embedding rather than syntax breaking. Enforce typed schema validation, bind values through the driver's parameterized form, keep script surfaces closed, and never pass raw user input as a query object.
