---
name: sqli-error-based-extraction
description: Error-shaped SQL extraction reading database internals from crafted failure text. Use when failure output carries type or constraint or parser detail; when error shaping needs proving before extraction; when verbose errors beat blind inference for speed.
metadata:
  version: 1.0.0
---

# Error-Based SQL Extraction

Some query paths reflect parser or type or constraint failures with database detail attached.
This variant shapes those failures so each error carries a chosen value inside its text.
The extraction goal is metadata plus table rows read from error text without needing rendered result sets.

## Attack Surface

Applicability centers on a query path whose failure responses carry database-generated error text.
User input reaches SQL construction with string concatenation present and error output reflected to the caller.
The error surface preserves type plus constraint plus parser detail rather than replacing it with a generic page.
Identifier versus value influence plus query shape ride inside this variant only as aspects because neither changes the shaping step itself.
DBMS dialect rides inside this variant only as shaper naming because renaming a conversion never changes the shaping procedure.

## Detection Channels

Shaped errors confirm this variant, so only the entries below are live here.
- Type plus constraint plus parser error text carrying database internals such as version or path detail.
- Error-text change between a benign probe and a shaped probe separating shaping success from failure.
- Stable metadata echo confirming version plus user plus database name through repeated shaped errors.
- UNION fallback signal where filtering removes shaping but a rendered row still answers.

## Adversarial Capabilities

Extraction presupposes anonymous request ability plus failure-text observation, and it consumes both.
- Send requests carrying structure-altering input into the candidate sink.
- Trigger controlled failures with one malformed class at a time and record the error text per probe.
- Compare each shaped error against its benign baseline to confirm the injected value rendered.
- Hold an authenticated session only where the sink requires privilege before reflecting errors.

## Trust Assumptions

The feature trusts user input to remain a bound literal from request through query construction to execution.
The agreement holds concatenation shape stable, keeps ORM fragments bound, keeps identifiers quoted, keeps error output silent, keeps execution timing stable, and keeps database egress closed.
Query results expose only application data, and no statement shape or store internals leak to the caller.
This variant breaks the error-silence clause because crafted conversions force the database to embed chosen values inside failure text, so store internals arrive as errors.

## Key Vulnerabilities

### Error Shaping With Conversions

Force a conversion failure whose message embeds the requested value, because the message template quotes its offending input.
Vary the conversion target until the message carries the full value rather than a truncation.
The parent extraction step names error-based retrieval without stating conversion shaping, so this variant owns the shaping procedure.
```text
<CAST-SHAPER>(<TARGET-VALUE>)
<CONVERT-SHAPER>(<TARGET-VALUE>)
```

### Disclosure Scoping Through Errors

Pivot from single values to metadata by shaping version plus current user plus database name into consecutive errors.
Continue from metadata to target tables once the metadata echo proves the shaping is stable.
Crafted conversion errors stay in this variant while the error text carries the value, and row-rendering probes belong to the UNION sibling.
```text
<CAST-SHAPER>(<METADATA-VALUE>)
<CAST-SHAPER>(<TARGET-VALUE>)
```

### Structured-Document Error Generation

Shape errors through structured-document functions where plain conversions are filtered, because malformed documents fail with quoted paths.
Submit one malformed document class at a time and record which shape returns quoted detail.
The parent error step never states document-path shaping, so this variant owns the document-shaping procedure.

## Bypass Techniques

Bypass forms stay aspects inside this variant because no encoding difference changes the shaping step itself.
- Comment sequences plus spacing swaps reach the parser past naive whitespace filtering.
- Keyword splitting plus case folding reach the parser past naive keyword blocklists.
- Numeric plus character-builder encodings reach the parser past literal-pattern filters.
- Clause relocation through derived tables plus common table expressions hides the conversion shape.
- Fallback to UNION or blind channels applies only when filtering silences every shaped error.

## Chaining Attacks

Shaped errors chain forward into reads because one disclosed value without a follow-up read is only a probe.
- Pivot from metadata to authentication records for a reversible login proof through shaped errors.
- Pivot from metadata to role or privilege fields for a reversible modification proof where an UPDATE path is injectable.
- Pivot from the error channel to file or command primitives only where granted privilege enables them.
- Stop each chain at the smallest read or reversible proof that confirms the architectural risk.

## Testing Methodology

Shaping runs baseline first and extraction second, because no error is meaningful without a benign rendering to diverge from.
The first bent step is the S5 error sub-value, namely cast-driven error shaping plus disclosure scoping.
The delta over the parent is the conversion-shaper selection plus the baseline-diff confirmation plus the metadata scoping that S3 plus S5 name without specifying.
1. **Inventory shapes** - list every candidate sink with its query shape plus clause presence, and the step completes when no unlisted sink remains.
2. **Classify influence** - name the value versus identifier versus raw-fragment position per input, and the step completes when every input carries one influence class.
3. **Record benign errors** - submit benign malformed input per sink and store each baseline error rendering, and the step completes when every sink carries a baseline or a generic-output verdict.
4. **Shape a marker** - force a conversion failure embedding a known marker and diff it against the baseline, and the step completes when the marker renders in error text or shaping is ruled out.
5. **Scope the disclosure** - repeat shaping across conversion targets plus document shapes until each target shows quoted detail or a recorded refusal.
6. **Read metadata** - shape version plus current user plus database name into consecutive errors, and the step completes when verifiable metadata is recorded.
7. **Target high-value tables** - pivot from metadata to authentication plus privilege plus file or command primitives, and the step completes when each target shows a read or a reversible proof or a recorded negative.

## False Positives

Stop when the error text carries no injected value, because generic failure without shaping is not extraction.
- Generic errors unrelated to SQL parsing or constraints, which carry no database detail.
- Static error templates that never quote the offending input regardless of the shaped value.
- Application-layer validation messages that reject input before any query executes.
- Parameterized queries with no string concatenation, verified by code review.

## Pro Tips

Shaping rewards baselines plus one conversion at a time plus early metadata.
1. Prefer the quietest working shaper first and keep it for the whole run.
2. Record one benign baseline per sink before shaping anything.
3. Shape one value per probe so each error names exactly one disclosed field.
4. Read metadata first, then jump directly to business-critical tables with minimal lateral noise.
5. Treat a truncation as a shaper problem and switch conversion targets before assuming enforcement.

## Summary

A query path that reflects database errors answers extraction through shaped failures.
Conversion shaping embeds each chosen value, baselines prove the channel, and metadata leads to the smallest confirming read.
