---
name: sqli-union-extraction
description: Union-rendered SQL extraction appending result sets to visible responses. Use when injected rows render inside the response body; when column count and type alignment need proving before extraction; when a direct in-band channel beats blind or callback inference.
metadata:
  version: 1.0.0
---

# Union-Based SQL Extraction

Some query paths render an attacker-appended result set inside the visible response.
This variant proves column shape then aligns types and extracts data through that rendered channel.
The extraction goal is metadata plus table rows read directly from the response without blind inference.

## Attack Surface

- **Applicability**: centers on a query path whose response renders rows from the executed statement.
- **Input reach**: user input reaches SQL construction with string concatenation present in a SELECT path capable of set combination.
- **Rendering surface**: preserves appended rows rather than suppressing them into errors or uniform responses.
- **Identifier versus value influence plus query shape**: ride inside this variant only as aspects because neither changes the rendering step itself.
- **DBMS dialect**: rides inside this variant only as function naming because renaming a coercion never changes the alignment procedure.

## Detection Channels

- **Rendering**: confirms this variant.
- **Appended-row rendering**: rendered appended rows carrying data from outside the intended query.
- **Row-count change**: row-count change between arity probes separating wrong column counts from the correct one.
- **Coercion error text**: coercion error text separating a misaligned type attempt from an aligned one during alignment only.
- **Metadata echo**: stable metadata echo confirming version plus user plus database name through the established channel.

## Adversarial Capabilities

- **Extraction**: presupposes anonymous request ability plus repeated response observation, and it consumes both.
- **Structure-altering requests**: send requests carrying structure-altering input into the candidate sink.
- **Response observation**: observe rendered responses and record row presence plus arity plus type behavior per probe.
- **Arity adjustment**: repeat probes with adjusted arity until the appended set renders stably.
- **Privileged session**: hold an authenticated session only where the sink requires privilege before rendering.

## Trust Assumptions

- **The agreement**: the feature trusts user input to remain a bound literal from request through query construction to execution, holds concatenation shape stable, keeps ORM fragments bound, keeps identifiers quoted, keeps error output silent, keeps execution timing stable, keeps database egress closed, and query results expose only application data with no statement shape or store internals leaking to the caller.
- **The failing clause**: this variant breaks the shape-stability clause because injected structure appends a second result set that renders inside the visible response, so rows from outside the intended query appear as data.

## Key Vulnerabilities

### Column-Count Discovery

- **Ordering-position stepping**: step the ordering position upward until the response signals excess, because the failure boundary names the arity.
- **Count confirmation**: confirm the count by rendering a null row of exactly that width through set combination.
- **Counting procedure**: the parent extraction step names UNION without stating arity discovery, so this variant owns the counting procedure.
  ```text
  ORDER BY <N>
  UNION SELECT <NULL-ROW>
  ```

### Type Alignment With Coercion

- **Column coercion**: coerce each column toward a renderable form until every position accepts the appended row.
- **Coercion preference**: prefer text or structured coercion for positions that refuse their native type.
- **Alignment procedure**: the parent extraction step lists UNION without describing rendering coercion, so this variant owns the alignment procedure.
  ```text
  UNION SELECT <COERCED-ROW>
  ```

### Rendered Extraction

- **Metadata pivot**: pivot from alignment to metadata by requesting version plus current user plus database name through the aligned row.
- **Table continuation**: continue from metadata to target tables once the metadata echo proves the channel is stable.
- **Variant boundary**: UNION output that surfaces inside error text stays in this variant while column alignment proves the channel.
  ```text
  UNION SELECT <METADATA-ROW>
  UNION SELECT <TARGET-ROW>
  ```

## Bypass Techniques

- **Bypass forms**: stay aspects inside this variant because no encoding difference changes the rendering step itself.
- **Comment and spacing swaps**: comment sequences plus spacing swaps reach the parser past naive whitespace filtering.
- **Keyword splitting**: keyword splitting plus case folding reach the parser past naive keyword blocklists.
- **Numeric and character-builder encodings**: numeric plus character-builder encodings reach the parser past literal-pattern filters.
- **Clause relocation**: clause relocation through derived tables plus common table expressions hides the set-combination shape.
- **Channel fallback**: fallback to error or blind channels applies only when filtering removes the rendered rows entirely.
- **Extended reading**: when this section does not fulfil the knowledge gap, extend the reading with the defence-bypass and proxy-techniques families.

## Chaining Attacks

- **Rendering**: chains forward into reads because an aligned channel without a follow-up read is only a probe.
- **Authentication pivot**: pivot from metadata to authentication records for a reversible login proof through the rendered channel.
- **Privilege pivot**: pivot from metadata to role or privilege fields for a reversible modification proof where an UPDATE path is injectable.
- **Execution pivot**: pivot from the rendered channel to file or command primitives only where granted privilege enables them.
- **Stop condition**: stop each chain at the smallest read or reversible proof that confirms the architectural risk.

## Testing Methodology

Rendering runs alignment first and extraction second, because no read is meaningful without a proven column shape.
The first bent step is the S5 UNION sub-value, namely column counting plus null-arity discovery plus type alignment.
The delta over the parent is the ordering-position count plus the null-row confirmation plus the coercion alignment that S5 lists without describing.
1. **Inventory shapes** - list every candidate sink with its query shape plus clause presence, and the step completes when no unlisted sink remains.
2. **Classify influence** - name the value versus identifier versus raw-fragment position per input, and the step completes when every input carries one influence class.
3. **Confirm the rendering class** - submit structure probes and record rendered rows versus errors versus differentials, and the step completes when the rendering oracle or its absence is recorded.
4. **Count columns** - step the ordering position upward and confirm with a null row of matching width, and the step completes when exactly one arity renders stably.
5. **Align types** - coerce each position until the appended row renders without coercion errors, and the step completes when every column carries an aligned or ruled-unrenderable verdict.
6. **Read metadata** - request version plus current user plus database name through the aligned row, and the step completes when verifiable metadata is recorded.
7. **Target high-value tables** - pivot from metadata to authentication plus privilege plus file or command primitives, and the step completes when each target shows a read or a reversible proof or a recorded negative.

## False Positives

- **Stop condition**: stop when the response shows no appended structure, because rendering without injection is only templating.
- **Generic errors**: generic errors unrelated to arity or coercion, which signal no column-shape information.
- **Static response sizes**: static response sizes from templating rather than from an appended row rendering.
- **Parameterized queries**: parameterized queries with no string concatenation, verified by code review.
- **Uniform refusals**: uniform refusals across every arity, which signal enforcement rather than a missed count.

## Pro Tips

- **Rendering discipline**: rendering rewards patience plus minimal arity plus early metadata.
- **Smallest arity first**: prefer the smallest arity that renders before requesting anything sensitive.
- **Null-row confirmation**: confirm one stable null row before spending probes on coercion.
- **One column at a time**: coerce one column at a time so each failure names exactly one misaligned position.
- **Metadata first**: read metadata first, then jump directly to business-critical tables with minimal lateral noise.
- **Unrenderable logging**: record unrenderable positions explicitly so later runs skip them without re-probing.

## Summary

A query path that renders appended rows answers extraction directly.
Alignment proves the arity, coercion proves each type, and metadata leads to the smallest confirming read.
