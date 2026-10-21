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

- **Applicability**: centers on a query path whose execution duration varies stably with injected predicate truth.
- **Input reach**: user input reaches SQL construction with string concatenation present and a sleep-capable function reachable from the injectable context.
- **Timing surface**: preserves predicate-gated delays rather than flattening every answer into uniform latency.
- **Identifier versus value influence plus query shape**: ride inside this variant only as aspects because neither changes the gating step itself.
- **DBMS dialect**: rides inside this variant only as function naming because renaming the delay primitive never changes the calibration procedure.
- **Schema-layer carriers**: a schema-layer resolver is a valid carrier: the delay lands inside the resolver's own statement, and the schema layer changes nothing about the gating procedure.

## Detection Channels

- **Gated delays**: confirm this variant.
- **Response-time delay**: response-time delay separating a true predicate from its false pair under a calibrated baseline.
- **Delay baseline**: delay-baseline record separating database-induced latency from network plus CPU noise.
- **Repeated-sample verdict**: repeated-sample verdict separating a stable timing signal from jitter.
- **Content-differential fallback**: fallback content differential where a stable boolean difference answers alongside the delay.

## Adversarial Capabilities

- **Extraction**: presupposes anonymous request ability plus precise latency measurement, and it consumes both.
- **Paired requests**: send paired requests differing only in one gated predicate and record arrival timing per probe.
- **Latency baselining**: baseline global latency with benign probes before gating any delay.
- **Verdict stabilisation**: repeat each pair until the delay verdict stabilises across samples.
- **Privileged session**: hold an authenticated session only where the sink requires privilege before executing the gated delay.

## Trust Assumptions

- **The agreement**: the feature trusts user input to remain a bound literal from request through query construction to execution, holds concatenation shape stable, keeps ORM fragments bound, keeps identifiers quoted, keeps error output silent, keeps execution timing stable, keeps database egress closed, and query results expose only application data with no statement shape or store internals leaking to the caller.
- **The failing clause**: this variant breaks the timing-stability clause because gated predicates force execution duration to vary with truth, so one bit of store content leaks per measured delay.

## Key Vulnerabilities

### Subselect-Gated Delay

- **Subselect gating**: gate the timing function inside a subselect behind the predicate so only a true evaluation pays the delay.
- **Delay sizing**: keep the delay short enough to separate from noise yet long enough to survive jitter.
- **Gating procedure**: the parent extraction step names time-based retrieval without stating subselect gating, so this variant owns the gating procedure.
  ```text
  AND (SELECT CASE WHEN (<PREDICATE>) THEN <DELAY-CALL> ELSE <IDLE-VALUE> END)
  ```

### Latency Baselining

- **Benign-latency measurement**: measure benign latency across repeated probes before extracting, because a threshold without a baseline cannot separate signal from noise.
- **Re-baselining**: re-baseline whenever global latency shifts mid-run rather than trusting a stale threshold.
- **Calibration procedure**: the parent oracle step prefers quieter channels without describing delay baselining, so this variant owns the calibration procedure.

### Binary Search Under Latency

- **Range-halving walk**: walk each character by halving its value range with gated predicates, because linear guessing multiplies slow requests.
- **Promotion discipline**: promote the run to this variant only once gated sleep becomes the sole oracle, and keep boolean diffing where any content differential survives.
- **Search procedure**: the parent extraction step never states range-halving under latency, so this variant owns the search procedure.

## Bypass Techniques

- **Bypass forms**: stay aspects inside this variant because no encoding difference changes the gating step itself.
- **Comment and spacing swaps**: comment sequences plus spacing swaps reach the parser past naive whitespace filtering.
- **Keyword splitting**: keyword splitting plus case folding reach the parser past naive keyword blocklists.
- **Numeric and character-builder encodings**: numeric plus character-builder encodings reach the parser past literal-pattern filters.
- **Clause relocation**: clause relocation through derived tables plus common table expressions hides the gated shape.
- **Callback fallback**: fallback to callback exfiltration applies only when noise removes every stable delay.
- **Extended reading**: when this section does not fulfil the knowledge gap, extend the reading with the defence-bypass and proxy-techniques families.

## Chaining Attacks

- **Delays**: chain forward into reads because one timed bit without a follow-up read is only a probe.
- **Authentication pivot**: pivot from metadata to authentication records for a reversible login proof through gated timing.
- **Privilege pivot**: pivot from metadata to role or privilege fields for a reversible modification proof where an UPDATE path is injectable.
- **Execution pivot**: pivot from the timing channel to file or command primitives only where granted privilege enables them.
- **Stop condition**: stop each chain at the smallest read or reversible proof that confirms the architectural risk.

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

- **Stop condition**: stop when delays track the network rather than the predicate, because ungated latency is not extraction.
- **Artificial delays**: artificial delays from network plus CPU load unrelated to injected function calls.
- **Global latency shifts**: global latency shifts mid-run that move every sample together rather than separating pairs.
- **Uniform delays**: uniform delays across true and false pairs, which signal a missing gate rather than a negative.
- **Parameterized queries**: parameterized queries with no string concatenation, verified by code review.

## Pro Tips

- **Timing discipline**: timing rewards short delays plus fresh baselines plus narrow alphabets.
- **Shortest stable delay**: prefer the shortest delay that separates stably and keep it for the whole run.
- **Frequent re-baselining**: re-baseline often because global latency drifts without warning.
- **One predicate per probe**: gate one predicate per probe so each delay names exactly one bit.
- **Metadata first**: read metadata first, then jump directly to business-critical tables with minimal lateral noise.
- **Jitter logging**: stop promoting jittered pairs and record them as inconclusive rather than negative.

## Summary

A query path that answers in latency leaks one bit per measured delay.
Baselining proves the threshold, gating proves the predicate, and metadata leads to the smallest confirming read.
