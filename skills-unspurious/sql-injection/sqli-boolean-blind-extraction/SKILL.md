---
name: sqli-boolean-blind-extraction
description: Boolean-blind SQL extraction diffing paired true and false responses bit by bit. Use when responses differ by predicate truth without rendering rows or errors; when binary search needs proving for character extraction; when stable differentials beat timing or callback channels.
metadata:
  version: 1.0.0
---

# Boolean-Blind SQL Extraction

Some query paths answer with no rows and no errors, yet paired predicates still produce distinguishable responses.
This variant diffs true-versus-false pairs and walks each value out with binary search.
The extraction goal is metadata plus table rows rebuilt from response differentials without any direct output channel.

## Attack Surface

Applicability centers on a query path whose responses vary stably with injected predicate truth.
User input reaches SQL construction with string concatenation present and at least one observable response difference per paired probe.
The differential surface preserves status plus body plus length plus presence-header distinctions rather than normalizing every answer.
Identifier versus value influence plus query shape ride inside this variant only as aspects because neither changes the diffing step itself.
DBMS dialect rides inside this variant only as predicate naming because renaming a string function never changes the binary-search procedure.

## Detection Channels

Paired differentials confirm this variant, so only the entries below are live here.
- Status plus body plus length plus presence-header difference between a true predicate and its false pair.
- Stable per-pair verdict separating a reachable truth signal from random variance.
- Normalized response digest confirming the differential survives templating noise.
- Ordered-output shaping signal where sort plus paging contexts carry the predicate into visible row order.

## Adversarial Capabilities

Extraction presupposes anonymous request ability plus paired-response observation, and it consumes both.
- Send paired requests differing only in one predicate truth value.
- Normalize each response by length plus digest plus presence headers before comparing.
- Repeat each pair until the verdict stabilises across samples.
- Hold an authenticated session only where the sink requires privilege before answering differentially.

## Trust Assumptions

The feature trusts user input to remain a bound literal from request through query construction to execution.
The agreement holds concatenation shape stable, keeps ORM fragments bound, keeps identifiers quoted, keeps error output silent, keeps execution timing stable, and keeps database egress closed.
Query results expose only application data, and no statement shape or store internals leak to the caller.
This variant breaks the response-stability clause because paired predicates force distinguishable responses for true versus false, so one bit of store content leaks per pair.

## Key Vulnerabilities

### Predicate-Pair Diffing

Submit each predicate beside its exact negation and compare the normalized responses, because a single request without its pair proves nothing.
Treat a consistent class change as one bit and treat uniform randomness as inconclusive rather than negative.
The parent extraction step names boolean bit extraction without stating true-versus-false pairing or normalization, so this variant owns the diffing procedure.
```text
AND <TRUE-PREDICATE>
AND <FALSE-PREDICATE>
```

### Binary-Search Bit Extraction

Walk each character by halving its value range with substring plus comparison predicates, because linear guessing wastes requests.
Encode outputs in a compact alphabet to normalize before comparing.
The parent extraction step never states substring iteration or range halving, so this variant owns the search procedure.
```text
SUBSTRING(<TARGET>, <POSITION>, <LENGTH>) <GUESS>
```

### Ordered-Output Shaping

Carry predicates into sort plus paging contexts where row content stays hidden, because row order still answers truth.
Shape one ordering expression per pair and record which permutation the response preserves.
The parent boolean step never states sort-context shaping, so this variant owns the ordered-output procedure.

## Bypass Techniques

Bypass forms stay aspects inside this variant because no encoding difference changes the diffing step itself.
- Comment sequences plus spacing swaps reach the parser past naive whitespace filtering.
- Keyword splitting plus case folding reach the parser past naive keyword blocklists.
- Numeric plus character-builder encodings reach the parser past literal-pattern filters.
- Clause relocation through derived tables plus common table expressions hides the predicate shape.
- Promotion to gated timing applies only when jitter removes every stable differential.

## Chaining Attacks

Differentials chain forward into reads because one extracted bit without a follow-up read is only a probe.
- Pivot from metadata to authentication records for a reversible login proof through paired diffing.
- Pivot from metadata to role or privilege fields for a reversible modification proof where an UPDATE path is injectable.
- Pivot from the boolean channel to file or command primitives only where granted privilege enables them.
- Stop each chain at the smallest read or reversible proof that confirms the architectural risk.

## Testing Methodology

Diffing runs calibration first and extraction second, because no bit is meaningful without a proven true-versus-false difference.
The first bent step is the S5 boolean sub-value, namely predicate-pair diffing plus binary-search extraction plus response normalization.
The delta over the parent is the paired-truth procedure plus the substring range-halving plus the digest normalization that S5 names without specifying.
1. **Inventory shapes** - list every candidate sink with its query shape plus clause presence, and the step completes when no unlisted sink remains.
2. **Classify influence** - name the value versus identifier versus raw-fragment position per input, and the step completes when every input carries one influence class.
3. **Calibrate the differential** - submit known-true versus known-false pairs and record the stable difference class, and the step completes when every sink carries a differential or a ruled-uniform verdict.
4. **Normalize responses** - reduce each answer to length plus digest plus presence headers and re-check the calibration, and the step completes when the differential survives normalization.
5. **Extract by binary search** - halve each character range with substring predicates until one value remains, and the step completes when every requested character carries one confirmed value.
6. **Read metadata** - rebuild version plus current user plus database name through paired diffing, and the step completes when verifiable metadata is recorded.
7. **Target high-value tables** - pivot from metadata to authentication plus privilege plus file or command primitives, and the step completes when each target shows a read or a reversible proof or a recorded negative.

## False Positives

Stop when paired predicates answer uniformly, because differentials without truth signal are only noise.
- Static response sizes from templating rather than from predicate truth.
- Generic errors unrelated to SQL parsing or constraints, which carry no differential information.
- Timing gaps alone without a content differential, which belong to the timing sibling once gated sleep becomes the sole oracle.
- Parameterized queries with no string concatenation, verified by code review.

## Pro Tips

Diffing rewards calibration plus normalization plus narrow alphabets.
1. Prefer the smallest predicate pair that shows a stable difference before extracting anything.
2. Normalize every response before comparing so boilerplate never poses as signal.
3. Repeat each pair until the class stabilises, and log every sample behind its pair.
4. Read metadata first, then jump directly to business-critical tables with minimal lateral noise.
5. Record inconclusive pairs as inconclusive rather than negative so later runs revisit them.

## Summary

A query path that answers differentially leaks one bit per pair.
Calibration proves the difference, binary search rebuilds each value, and metadata leads to the smallest confirming read.
