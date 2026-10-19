---
name: nosql-server-side-script-injection
description: Script-body injection placing executable functions in query filters and aggregation expressions. Use when script-engine enablement needs fingerprinting; when sleep-driven timing differentials answer blind predicates; when expression-context placement bypasses top-level filter stripping.
metadata:
  version: 1.0.0
---

# Server-Side Script Injection

Some query paths forward user text to an embedded script engine, so crafted input runs as function body with the query's read reach.
This variant fingerprints engine enablement, places function bodies where the engine evaluates them, and confirms execution through timing or content differentials.
The execution goal is record matching plus field extraction under script semantics rather than filter semantics.

## Attack Surface

Applicability centers on a query path whose filter or expression context reaches a server-side script engine.
User input arrives as a function-valued filter clause or as an expression document inside an aggregation context or as a script source field on an index or view surface.
The engine gate stands open on the target release, so submitted bodies evaluate instead of rejecting.
Store product rides inside this variant only as body spelling because renaming a store never changes the placement procedure.

## Reconnaissance

Reconnaissance fingerprints the engine gate before any body work, because a closed engine answers nothing worth extracting.
Inventory every filter and aggregation and script-source surface that could carry a function body, and the step completes when each candidate sink is listed.
Query the engine-enable state through administrative parameter reads and version-identifying error text, and the step completes when each sink carries an enabled-or-disabled verdict.
Submit benign function bodies that match a known record versus an impossible one and record the difference class, and the step completes when script evaluation is proven or refuted per sink.

## Detection Channels

Script evaluation confirms this variant, so only the entries below are live here.
- Enablement-state answer distinguishing an open engine gate from a closed one.
- Driver error and validation text after malformed function bodies.
- Sleep-driven latency differential between a truth branch that pauses and one that returns immediately.
- A key-set probe that answers per candidate field name rather than per value, which exposes the schema behind the query.
- Boolean response, status, or redirect difference between a matching function body and a non-matching one.

## Adversarial Capabilities

Script work presupposes anonymous request ability plus timing observation, and it consumes both.
- Send function bodies to filter clauses and to expression contexts and compare evaluation.
- Measure response latency across repeated samples to separate engine pauses from network jitter.
- Iterate blind predicates inside function bodies with binary search over the value alphabet.
- Hold an authenticated low-privilege session only where the sink requires privilege before evaluating.

## Trust Assumptions

The feature trusts user input to arrive as plain data values inside declared field shapes from request through filter construction to execution.
The agreement holds filter shape closed to declared fields, keeps interpreter primitives unreachable, keeps stage and collection selection server-side, keeps script bodies server-authored, keeps query strings literal-bound, keeps command frames single, and keeps stored records plus store internals unexposed.
Query answers expose only matched application records, and no predicate truth or store content leaks beyond the intended view.
This variant breaks the script-body clause because input text reaches the script engine as executable body, so crafted functions run with the query's read reach.

## Key Vulnerabilities

### Function-Filter Placement

Submit a function body as a top-level filter clause that reads record fields and returns a match verdict, because an open engine evaluates the body per record.
Pair a matching body with an impossible one and treat a consistent class change as proof of evaluation.
The parent script step names top-level function filters without stating match-versus-impossible pairing, so this variant owns the paired-body procedure.
```text
{"<SCRIPT-FILTER>": "function(){ return <FIELD-ACCESS> <COMPARISON> <VALUE> }"}
```

### Expression-Context Placement

Carry the function body into an expression document inside a projection or computed-field context, because aggregation endpoints that strip top-level function clauses still evaluate expression contexts.
Place the body with its argument bindings and language marker exactly where the engine expects a callable, and record evaluation versus rejection per context.
The parent script step never states the expression-context placement rule, so this variant owns the context-placement procedure.
```text
{"<EXPRESSION>": {"<FUNCTION-OPERATOR>": {"body": "function(<ARGS>){ return <PREDICATE> }", "args": [<BINDINGS>], "lang": "<LANG>"}}}
```

### Script-Source Control

Submit crafted source to script-source fields on index-update and view-definition surfaces, because those sinks store the body and evaluate it on later queries.
Treat stored evaluation as a distinct confirmation class from immediate filter evaluation and verify persistence through a follow-up read.
The parent store list never states script-source control, so this variant owns the source-placement procedure.

### Sleep-Timing Oracle

Branch the function body on a blind predicate with a pause primitive on the truth arm, because a latency gap answers one bit per request where content stays uniform.
Repeat each pair until the gap stabilises across samples and treat jitter without separation as inconclusive rather than negative.
The parent script step names sleep timing without stating repetition discipline, so this variant owns the timing procedure.

### Field and Schema Enumeration

Enumerate field names rather than values: a predicate over the document key set answers whether a candidate field exists, which maps the schema before any value is read.
Walk the key set character by character through the same boolean oracle, because a field name is as extractable as a field value.
Treat the key set as the first extraction target on an unknown document shape, so later reads name live fields instead of guessing them.
The parent blind step extracts values only, so this variant owns the field-name and schema enumeration procedure.

## Bypass Techniques

Bypass forms stay aspects inside this variant because no encoding difference changes the body-placement step itself.
- Expression-context placement reaches the engine past filters that strip only top-level function clauses.
- Stored source on view and index surfaces reaches the engine past request-time function blocklists.
- String-splitting plus concatenation inside the body reaches the engine past naive keyword matching.
- Percent-encoded plus double-encoded wrappings reach the parser past filters that match only literal function text.

When this section does not fulfil the knowledge gap, extend the reading with the defence-bypass and proxy-techniques families.

## Chaining Attacks

Bodies chain forward into reads because one evaluated function without a follow-up read is only a probe.
- Pivot from a matching body to record and field extraction for a reversible read proof.
- Pivot from a timing oracle to token, reset-code, or key fields for the smallest confirming read.
- Pivot from enablement state to the placement contexts the open gate admits.
- Stop each chain at the smallest read or reversible proof that confirms the architectural risk.

## Testing Methodology

Script work runs gate fingerprinting first and body placement second, because no function proves anything until the engine is known open.
The first bent step is S7 Test script-body filters, namely enablement fingerprinting plus body placement plus sleep-timing confirmation.
The delta over the parent is the enablement procedure plus the expression-context placement rule plus the repetition-disciplined timing oracle that S7 names without specifying.
1. **Inventory script surfaces** - list every filter, aggregation-context, index-source, and view-definition sink, and the step completes when no unlisted sink remains.
2. **Fingerprint the gate** - read enablement state and version-identifying error text per sink, and the step completes when every sink carries an enabled-or-disabled verdict.
3. **Probe benign bodies** - submit matching versus impossible function bodies and record the difference class, and the step completes when evaluation is proven or refuted per sink.
4. **Place filter bodies** - submit function filters against record-matching logic, and the step completes when each sink shows evaluation or a recorded negative.
5. **Place expression bodies** - carry function documents into projection and computed-field contexts, and the step completes when each context shows evaluation or a recorded negative.
6. **Place stored sources** - submit crafted bodies to index-source and view-definition fields and verify through follow-up reads, and the step completes when persistence is proven or refuted per sink.
7. **Extract by timing** - branch blind predicates on pause primitives with repeated samples, and the step completes when every requested field carries one confirmed value or a definitive negative.

## False Positives

Stop when bodies answer as inert text, because unexecuted script content is safe.
- Disabled engine gates that reject or ignore function bodies, verified by enablement reads.
- Query timeouts that cap runaway bodies before exfiltration completes.
- Latency gaps from load or network jitter without predicate correlation, which carry no oracle information.
- Sandboxed script contexts that block record-field access while still evaluating arithmetic.

## Pro Tips

Bodies reward gate discipline plus context coverage plus patient timing.
1. Fingerprint enablement before investing in body placement so closed gates cost no requests.
2. Try expression contexts wherever top-level function clauses are stripped because aggregation endpoints evaluate them independently.
3. Repeat every timing pair until the gap stabilises, and log every sample behind its pair.
4. Target token and reset-code and key fields with the timing oracle, not only credential fields.
5. Treat stored-source evaluation as persistent risk and verify it with a follow-up read before claiming impact.

## Summary

A query path that evaluates input as script body runs crafted functions with record reach.
Enablement fingerprinting proves the gate, placement puts the body where the engine reads it, and timing answers blind predicates.
