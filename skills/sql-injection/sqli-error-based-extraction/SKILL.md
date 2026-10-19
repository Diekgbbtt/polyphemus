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

- **Applicability**: centers on a query path whose failure responses carry database-generated error text.
- **Input reach**: user input reaches SQL construction with string concatenation present and error output reflected to the caller.
- **Error surface**: preserves type plus constraint plus parser detail rather than replacing it with a generic page.
- **Identifier versus value influence plus query shape**: ride inside this variant only as aspects because neither changes the shaping step itself.
- **DBMS dialect**: rides inside this variant only as shaper naming because renaming a conversion never changes the shaping procedure.

## Detection Channels

- **Shaped errors**: confirm this variant.
- **Error text detail**: type plus constraint plus parser error text carrying database internals such as version or path detail.
- **Probe divergence**: error-text change between a benign probe and a shaped probe separating shaping success from failure.
- **Metadata echo**: stable metadata echo confirming version plus user plus database name through repeated shaped errors.
- **Rendered-row fallback**: UNION fallback signal where filtering removes shaping but a rendered row still answers.

## Adversarial Capabilities

- **Extraction**: presupposes anonymous request ability plus failure-text observation, and it consumes both.
- **Structure-altering requests**: send requests carrying structure-altering input into the candidate sink.
- **Controlled failures**: trigger controlled failures with one malformed class at a time and record the error text per probe.
- **Baseline comparison**: compare each shaped error against its benign baseline to confirm the injected value rendered.
- **Privileged session**: hold an authenticated session only where the sink requires privilege before reflecting errors.

## Trust Assumptions

- **The agreement**: the feature trusts user input to remain a bound literal from request through query construction to execution, holds concatenation shape stable, keeps ORM fragments bound, keeps identifiers quoted, keeps error output silent, keeps execution timing stable, keeps database egress closed, and query results expose only application data with no statement shape or store internals leaking to the caller.
- **The failing clause**: this variant breaks the error-silence clause because crafted conversions force the database to embed chosen values inside failure text, so store internals arrive as errors.

## Key Vulnerabilities

### Error Shaping With Conversions

- **Conversion-failure forcing**: force a conversion failure whose message embeds the requested value, because the message template quotes its offending input.
- **Conversion-target variation**: vary the conversion target until the message carries the full value rather than a truncation.
- **Shaping procedure**: the parent extraction step names error-based retrieval without stating conversion shaping, so this variant owns the shaping procedure.
  ```text
  <CAST-SHAPER>(<TARGET-VALUE>)
  <CONVERT-SHAPER>(<TARGET-VALUE>)
  ```

### Disclosure Scoping Through Errors

- **Metadata pivot**: pivot from single values to metadata by shaping version plus current user plus database name into consecutive errors.
- **Table continuation**: continue from metadata to target tables once the metadata echo proves the shaping is stable.
- **Variant boundary**: crafted conversion errors stay in this variant while the error text carries the value, and row-rendering probes belong to the UNION sibling.
  ```text
  <CAST-SHAPER>(<METADATA-VALUE>)
  <CAST-SHAPER>(<TARGET-VALUE>)
  ```

### Structured-Document Error Generation

- **Document-function shaping**: shape errors through structured-document functions where plain conversions are filtered, because malformed documents fail with quoted paths.
- **Document-class probing**: submit one malformed document class at a time and record which shape returns quoted detail.
- **Document-shaping procedure**: the parent error step never states document-path shaping, so this variant owns the document-shaping procedure.

## Bypass Techniques

- **Bypass forms**: stay aspects inside this variant because no encoding difference changes the shaping step itself.
- **Comment and spacing swaps**: comment sequences plus spacing swaps reach the parser past naive whitespace filtering.
- **Keyword splitting**: keyword splitting plus case folding reach the parser past naive keyword blocklists.
- **Numeric and character-builder encodings**: numeric plus character-builder encodings reach the parser past literal-pattern filters.
- **Clause relocation**: clause relocation through derived tables plus common table expressions hides the conversion shape.
- **Channel fallback**: fallback to UNION or blind channels applies only when filtering silences every shaped error.
- **Extended reading**: when this section does not fulfil the knowledge gap, extend the reading with the defence-bypass and proxy-techniques families.

## Chaining Attacks

- **Shaped errors**: chain forward into reads because one disclosed value without a follow-up read is only a probe.
- **Authentication pivot**: pivot from metadata to authentication records for a reversible login proof through shaped errors.
- **Privilege pivot**: pivot from metadata to role or privilege fields for a reversible modification proof where an UPDATE path is injectable.
- **Execution pivot**: pivot from the error channel to file or command primitives only where granted privilege enables them.
- **Stop condition**: stop each chain at the smallest read or reversible proof that confirms the architectural risk.

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

- **Stop condition**: stop when the error text carries no injected value, because generic failure without shaping is not extraction.
- **Generic errors**: generic errors unrelated to SQL parsing or constraints, which carry no database detail.
- **Static error templates**: static error templates that never quote the offending input regardless of the shaped value.
- **Application-layer validation**: application-layer validation messages that reject input before any query executes.
- **Parameterized queries**: parameterized queries with no string concatenation, verified by code review.

## Pro Tips

- **Shaping discipline**: shaping rewards baselines plus one conversion at a time plus early metadata.
- **Quietest shaper first**: prefer the quietest working shaper first and keep it for the whole run.
- **Baseline recording**: record one benign baseline per sink before shaping anything.
- **One value per probe**: shape one value per probe so each error names exactly one disclosed field.
- **Metadata first**: read metadata first, then jump directly to business-critical tables with minimal lateral noise.
- **Truncation handling**: treat a truncation as a shaper problem and switch conversion targets before assuming enforcement.

## Summary

A query path that reflects database errors answers extraction through shaped failures.
Conversion shaping embeds each chosen value, baselines prove the channel, and metadata leads to the smallest confirming read.
