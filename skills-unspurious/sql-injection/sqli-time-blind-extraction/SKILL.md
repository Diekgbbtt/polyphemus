---
name: sqli-time-blind-extraction
description: Timing-gated SQL extraction measuring predicate-driven delays bit by bit. Use when only response latency varies with predicate truth; when gated sleep calibration needs proving under network noise; when differentials and errors stay silent.
metadata:
  version: 1.0.0
---

# Time-Blind SQL Extraction

Some query paths answer uniformly in content, yet a gated delay still separates true from false.
This variant baselines latency then gates a timing function behind each predicate and rebuilds values from delays.
The extraction goal is metadata plus table rows rebuilt from timing differentials where no other oracle answers.

## Attack Surface

Applicability centers on a query path whose execution duration varies stably with injected predicate truth.
User input reaches SQL construction with string concatenation present and a sleep-capable function reachable from the injectable context.
The timing surface preserves predicate-gated delays rather than flattening every answer into uniform latency.
Identifier versus value influence plus query shape ride inside this variant only as aspects because neither changes the gating step itself.
DBMS dialect rides inside this variant only as function naming because renaming the delay primitive never changes the calibration procedure.
A schema-layer resolver is a valid carrier: the delay lands inside the resolver's own statement, and the schema layer changes nothing about the gating procedure.

## Detection Channels

Gated delays confirm this variant, so only the entries below are live here.
- Response-time delay separating a true predicate from its false pair under a calibrated baseline.
- Delay-baseline record separating database-induced latency from network plus CPU noise.
- Repeated-sample verdict separating a stable timing signal from jitter.
- Fallback content differential where a stable boolean difference answers alongside the delay.

## Adversarial Capabilities

Extraction presupposes anonymous request ability plus precise latency measurement, and it consumes both.
- Send paired requests differing only in one gated predicate and record arrival timing per probe.
- Baseline global latency with benign probes before gating any delay.
- Repeat each pair until the delay verdict stabilises across samples.
- Hold an authenticated session only where the sink requires privilege before executing the gated delay.

## Trust Assumptions

The feature trusts user input to remain a bound literal from request through query construction to execution.
The agreement holds concatenation shape stable, keeps ORM fragments bound, keeps identifiers quoted, keeps error output silent, keeps execution timing stable, and keeps database egress closed.
Query results expose only application data, and no statement shape or store internals leak to the caller.
This variant breaks the timing-stability clause because gated predicates force execution duration to vary with truth, so one bit of store content leaks per measured delay.

## Key Vulnerabilities

### Subselect-Gated Delay

Gate the timing function inside a subselect behind the predicate so only a true evaluation pays the delay.
Keep the delay short enough to separate from noise yet long enough to survive jitter.
The parent extraction step names time-based retrieval without stating subselect gating, so this variant owns the gating procedure.
```text
AND (SELECT CASE WHEN (<PREDICATE>) THEN <DELAY-CALL> ELSE <IDLE-VALUE> END)
```

### Latency Baselining

Measure benign latency across repeated probes before extracting, because a threshold without a baseline cannot separate signal from noise.
Re-baseline whenever global latency shifts mid-run rather than trusting a stale threshold.
The parent oracle step prefers quieter channels without describing delay baselining, so this variant owns the calibration procedure.

### Binary Search Under Latency

Walk each character by halving its value range with gated predicates, because linear guessing multiplies slow requests.
Promote the run to this variant only once gated sleep becomes the sole oracle, and keep boolean diffing where any content differential survives.
The parent extraction step never states range-halving under latency, so this variant owns the search procedure.

## Bypass Techniques

Bypass forms stay aspects inside this variant because no encoding difference changes the gating step itself.
- Comment sequences plus spacing swaps reach the parser past naive whitespace filtering.
- Keyword splitting plus case folding reach the parser past naive keyword blocklists.
- Numeric plus character-builder encodings reach the parser past literal-pattern filters.
- Clause relocation through derived tables plus common table expressions hides the gated shape.
- Fallback to callback exfiltration applies only when noise removes every stable delay.

When this section does not fulfil the knowledge gap, extend the reading with the defence-bypass and proxy-techniques families.

## Chaining Attacks

Delays chain forward into reads because one timed bit without a follow-up read is only a probe.
- Pivot from metadata to authentication records for a reversible login proof through gated timing.
- Pivot from metadata to role or privilege fields for a reversible modification proof where an UPDATE path is injectable.
- Pivot from the timing channel to file or command primitives only where granted privilege enables them.
- Stop each chain at the smallest read or reversible proof that confirms the architectural risk.

## Testing Methodology

Calibration runs baselining first and extraction second, because no delay is meaningful without a proven latency threshold.
The first bent step is the S5 time sub-value, namely subselect-gated sleep plus latency baselining.
The delta over the parent is the gated-delay construction plus the baseline calibration plus the range-halving search that S4 plus S5 prefer without describing.
1. **Inventory shapes** - list every candidate sink with its query shape plus clause presence, and the step completes when no unlisted sink remains.
2. **Classify influence** - name the value versus identifier versus raw-fragment position per input, and the step completes when every input carries one influence class.
3. **Rule out quieter oracles** - test rendering plus errors plus content differentials first, and the step completes when each quieter channel shows a working oracle or a recorded absence.
4. **Baseline latency** - send benign probes repeatedly and record the stable latency band, and the step completes when the band survives re-measurement.
5. **Gate a marker delay** - gate a short delay behind a known-true predicate and diff it against its false pair, and the step completes when the marker delay separates stably or gating is ruled out.
6. **Read metadata** - rebuild version plus current user plus database name through gated binary search, and the step completes when verifiable metadata is recorded.
7. **Target high-value tables** - pivot from metadata to authentication plus privilege plus file or command primitives, and the step completes when each target shows a read or a reversible proof or a recorded negative.

## False Positives

Stop when delays track the network rather than the predicate, because ungated latency is not extraction.
- Artificial delays from network plus CPU load unrelated to injected function calls.
- Global latency shifts mid-run that move every sample together rather than separating pairs.
- Uniform delays across true and false pairs, which signal a missing gate rather than a negative.
- Parameterized queries with no string concatenation, verified by code review.

## Pro Tips

Timing rewards short delays plus fresh baselines plus narrow alphabets.
1. Prefer the shortest delay that separates stably and keep it for the whole run.
2. Re-baseline often because global latency drifts without warning.
3. Gate one predicate per probe so each delay names exactly one bit.
4. Read metadata first, then jump directly to business-critical tables with minimal lateral noise.
5. Stop promoting jittered pairs and record them as inconclusive rather than negative.

## Summary

A query path that answers in latency leaks one bit per measured delay.
Baselining proves the threshold, gating proves the predicate, and metadata leads to the smallest confirming read.
