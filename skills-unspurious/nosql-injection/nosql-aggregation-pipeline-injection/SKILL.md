---
name: nosql-aggregation-pipeline-injection
description: Pipeline-stage injection steering aggregation stages and collection pivots with crafted input. Use when filter, match, or sort fields feed pipeline construction; when cross-collection reads need proving; when stage targeting differs from plain row filtering.
metadata:
  version: 1.0.0
---

# Aggregation Pipeline Injection

Some endpoints build multi-stage pipelines from user input, so crafted values steer stage selection and even the collection under read.
This variant targets match and projection stages, then proves collection pivots that cross tenant or collection boundaries.
The pivoting goal is cross-collection exfiltration that row filtering in a fixed collection can never reach.

## Attack Surface

Applicability centers on an endpoint whose filter, match, sort, or lookup fields feed pipeline-stage construction.
User input arrives as stage fragments or field selectors that the builder splices into an ordered stage list.
A join-style stage accepts a collection selector, so crafted input can redirect the read into a neighboring collection.
Row-filter sinks without stage construction stay outside this variant and belong to the operator sibling.

## Reconnaissance

Reconnaissance maps stage influence before any pivot work, because each stage field needs its own targeting test.
Inventory every endpoint whose filter, match, sort, or join fields reach pipeline construction, and the step completes when each candidate sink carries a named stage field.
Submit benign stage fragments and record stage-error text versus silent acceptance, and the step completes when every sink carries a stage-influence verdict.
Enumerate neighboring collection names through error text and prior reads, and the step completes when each sink carries a pivot-candidate list or a recorded absence.

## Detection Channels

Stage control confirms this variant, so only the entries below are live here.
- Stage-error text naming stages, collections, or field paths after malformed stage fragments.
- Response content from a collection outside the intended scope after a pivot attempt.
- Boolean response, status, or redirect difference between a live stage fragment and an inert one.
- Latency or volume change from heavy join stages across large unindexed collections.

## Adversarial Capabilities

Pipeline work presupposes anonymous request ability plus cross-response comparison, and it consumes both.
- Send stage fragments to filter, match, sort, and join fields and compare stage handling.
- Name neighboring collections as pivot targets from error text and prior enumeration.
- Read pivot answers for out-of-scope records while staying within the smallest confirming sample.
- Hold an authenticated low-privilege session only where the pipeline requires privilege before executing.

## Trust Assumptions

The feature trusts user input to arrive as plain data values inside declared field shapes from request through filter construction to execution.
The agreement holds filter shape closed to declared fields, keeps interpreter primitives unreachable, keeps stage and collection selection server-side, keeps script bodies server-authored, keeps query strings literal-bound, keeps command frames single, and keeps stored records plus store internals unexposed.
Query answers expose only matched application records, and no predicate truth or store content leaks beyond the intended view.
This variant breaks the stage-selection clause because input names reach the pipeline builder as stage and collection selectors, so crafted stages pivot the read into collections outside the intended scope.

## Key Vulnerabilities

### Stage-Fragment Targeting

Submit operator predicates inside match and projection and sort fields, because stage contexts evaluate the same operators with stage-wide effect.
Pair each fragment with an inert control and treat a consistent class change as proof of stage influence.
The parent aggregation step names stage fields without stating fragment-versus-control pairing, so this variant owns the stage-targeting procedure.
```text
{"<STAGE-FIELD>": {"<MATCH>": {"<FIELD>": {"<OPERATOR>": <VALUE>}}}}
{"<SORT-FIELD>": {"<FIELD>": <DIRECTION>}}
```

### Collection Pivot

Submit a neighboring collection name as the join-stage source, because the builder resolves the selector without scope checks on unhardened paths.
Verify the pivot by reading one out-of-scope record marker rather than bulk-extracting the collection.
The parent aggregation step names the collection-selector risk without stating marker-based verification, so this variant owns the pivot procedure.
```text
{"<JOIN-STAGE>": {"from": "<COLLECTION>", "localField": "<FIELD>", "foreignField": "<FIELD>", "as": "<ALIAS>"}}
```

### Expression Boundary

Treat expression-context function documents as owned by the script sibling at any step that introduces a function body, because only script semantics need the engine gate.
Keep pure operator expressions inside this variant and hand every function-body case to the script procedure instead of restating it.

## Bypass Techniques

Bypass forms stay aspects inside this variant because no encoding difference changes the stage-steering step itself.
- Operator alternatives plus negation wrappers reach stage contexts past single-operator blocklists.
- Nested stage documents reach the builder past flattening sanitizers that inspect only top-level keys.
- Dotted-key versus nested-object shapes reach the builder past sanitizers that strip only one form.
- Percent-encoded plus double-encoded stage text reaches the parser past filters that match only literal stage names.

When this section does not fulfil the knowledge gap, extend the reading with the defence-bypass and proxy-techniques families.

## Chaining Attacks

Stages chain forward into reads because one steered stage without a follow-up read is only a probe.
- Pivot from a steered match stage to out-of-scope records for the smallest confirming read.
- Pivot from a collection pivot to field names that sharpen the next stage fragment.
- Pivot from stage-error text to neighboring collection names for the next pivot candidate.
- Stop each chain at the smallest read or reversible proof that confirms the architectural risk.

## Testing Methodology

Pipeline work runs stage mapping first and pivoting second, because no collection pivot proves anything until stage influence is known.
The first bent step is S8 Probe aggregation endpoints, namely stage targeting plus join-stage collection pivots.
The delta over the parent is the fragment-versus-control pairing plus the marker-based pivot verification plus the expression-boundary handoff that S8 names without specifying.
1. **Inventory pipeline sinks** - list every endpoint with filter, match, sort, or join fields reaching stage construction, and the step completes when no unlisted sink remains.
2. **Prove stage influence** - submit benign stage fragments beside inert controls, and the step completes when every sink carries an influence or a recorded negative.
3. **Target match stages** - submit operator predicates inside match and projection fields, and the step completes when each stage shows control or a recorded negative.
4. **Target sort and projection** - submit ordering and field-selection fragments, and the step completes when each stage shows control or a recorded negative.
5. **Attempt collection pivots** - submit neighboring collection names as join-stage sources, and the step completes when each sink shows a pivot read or a recorded negative.
6. **Verify scope crossing** - read one out-of-scope record marker per successful pivot, and the step completes when every pivot carries a marker or a ruled-contained verdict.
7. **Hand off function bodies** - route every expression-context function case to the script sibling procedure, and the step completes when no function-body case remains unassigned.

## False Positives

Stop when stages answer as fixed plumbing, because server-built pipelines without user-shaped stages are safe.
- Fixed stage lists that never splice user input into stage names or selectors.
- Collection selectors resolved from server-side allowlists regardless of submitted names.
- Uniform responses across live-versus-inert stage fragments, which carry no control information.
- Join errors from missing test collections rather than from scope enforcement.

## Pro Tips

Stages reward field coverage plus small pivots plus clean handoffs.
1. Map every filter, match, and sort field because each feeds a different stage position.
2. Prove stage influence with benign fragments before attempting any collection pivot.
3. Verify each pivot with one record marker rather than bulk reads so scope crossing stays minimal.
4. Read stage-error text for neighboring collection names that seed the next pivot candidate.
5. Hand every function-body expression to the script sibling instead of duplicating its procedure.

## Summary

A pipeline path that splices input into stages answers crafted fragments with stage-wide effect.
Fragment pairing proves the influence, collection pivots cross the intended scope, and one record marker confirms each crossing.
