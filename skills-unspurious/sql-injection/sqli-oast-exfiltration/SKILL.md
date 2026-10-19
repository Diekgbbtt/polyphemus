---
name: sqli-oast-exfiltration
description: Out-of-band SQL exfiltration correlating database callbacks with injected labels. Use when the database reaches an attacker listener through name or web primitives; when label embedding needs proving for data smuggling; when in-band rows plus errors plus differentials all stay silent.
metadata:
  version: 1.0.0
---

# Out-of-Band SQL Exfiltration

Some query paths answer nothing usable in-band, yet the database itself can reach an outside listener.
This variant embeds data inside callback labels and correlates each inbound hit with its probe.
The exfiltration goal is metadata plus table rows delivered to the listener without touching the visible response.

## Attack Surface

- **Applicability**: centers on a query path whose database reaches an attacker-observed listener through a callback primitive.
- **Input reach**: user input reaches SQL construction with string concatenation present and at least one name-resolution or web-request primitive reachable.
- **Egress surface**: preserves outbound callbacks rather than blocking every database-initiated connection.
- **Identifier versus value influence plus query shape**: ride inside this variant only as aspects because neither changes the embedding step itself.
- **DBMS dialect**: rides inside this variant only as primitive naming because renaming the callback never changes the correlation procedure.

## Detection Channels

- **Listener hits**: confirm this variant.
- **Callback receipt**: callback receipt at the attacker listener carrying an embedded label from the database.
- **Per-probe correlation**: per-probe token correlation binding one inbound hit to exactly one outbound request.
- **Metadata echo**: stable metadata echo confirming version plus user plus database name through repeated callbacks.
- **Differential fallback**: blind-extraction fallback signal where egress filtering removes callbacks but a differential still answers.

## Adversarial Capabilities

- **Exfiltration**: presupposes anonymous request ability plus listener operation, and it consumes both.
- **Structure-altering requests**: send requests carrying structure-altering input into the candidate sink.
- **Listener operation**: operate a listener that mints one fresh token per probe and records each inbound hit with its label.
- **Per-probe labelling**: embed one label per probe and correlate each arrival with its request.
- **Privileged session**: hold an authenticated session only where the sink requires privilege before executing the callback primitive.

## Trust Assumptions

- **The agreement**: the feature trusts user input to remain a bound literal from request through query construction to execution, holds concatenation shape stable, keeps ORM fragments bound, keeps identifiers quoted, keeps error output silent, keeps execution timing stable, keeps database egress closed, and query results expose only application data with no statement shape or store internals leaking to the caller.
- **The failing clause**: this variant breaks the egress-closure clause because injected labels force the database to open outbound callbacks carrying chosen data, so store content arrives at the listener.

## Key Vulnerabilities

### Label Embedding

- **Label embedding**: embed the requested value inside the callback address so the listener label itself carries the data.
- **Label economy**: prefer one value per probe and keep labels short enough to survive resolution encoding.
- **Embedding procedure**: the parent extraction step names out-of-band retrieval without stating label embedding, so this variant owns the embedding procedure.
  ```text
  <CALLBACK-PRIMITIVE>(<LABEL>.<LISTENER>)
  ```

### Primitive Selection

- **Primitive selection**: select the callback primitive the target database actually exposes, because each store family enables a different egress shape.
- **Availability confirmation**: confirm primitive availability with a benign marker callback before embedding any data.
- **Selection procedure**: the parent extraction step never states primitive choice, so this variant owns the selection procedure.

### Listener Correlation

- **Token minting**: mint one fresh token per probe and attribute each inbound hit to its probe, because batch totals cannot identify which request succeeded.
- **Outcome recording**: record the listener outcome per token and treat unmatched hits as unattributed rather than positive.
- **Correlation procedure**: the parent callback step covers only quiet watching without per-token attribution, so this variant owns the correlation procedure.

## Bypass Techniques

- **Bypass forms**: stay aspects inside this variant because no encoding difference changes the embedding step itself.
- **Comment and spacing swaps**: comment sequences plus spacing swaps reach the parser past naive whitespace filtering.
- **Keyword splitting**: keyword splitting plus case folding reach the parser past naive keyword blocklists.
- **Numeric and character-builder encodings**: numeric plus character-builder encodings reach the parser past literal-pattern filters.
- **Clause relocation**: clause relocation through derived tables plus common table expressions hides the callback shape.
- **Blind fallback**: fallback to blind extraction applies only when egress filtering removes every callback.

When this section does not fulfil the knowledge gap, extend the reading with the defence-bypass and proxy-techniques families.

## Chaining Attacks

- **Callbacks**: chain forward into reads because one received label without a follow-up read is only a probe.
- **Authentication pivot**: pivot from metadata to authentication records for a reversible login proof through callback labels.
- **Privilege pivot**: pivot from metadata to role or privilege fields for a reversible modification proof where an UPDATE path is injectable.
- **Execution pivot**: pivot from the callback channel to file or command primitives only where granted privilege enables them.
- **Stop condition**: stop each chain at the smallest read or reversible proof that confirms the architectural risk.

## Testing Methodology

Correlation runs listener setup first and exfiltration second, because no hit is meaningful without per-probe attribution.
The first bent step is the S5 OAST sub-value, namely label embedding plus primitive selection plus listener correlation.
The delta over the parent is the label-encoding construction plus the per-database primitive choice plus the token attribution that S5 lists without describing.
1. **Inventory shapes** - list every candidate sink with its query shape plus clause presence, and the step completes when no unlisted sink remains.
2. **Classify influence** - name the value versus identifier versus raw-fragment position per input, and the step completes when every input carries one influence class.
3. **Establish the listener** - deploy name plus web receivers with per-probe token minting, and the step completes when a benign self-triggered callback arrives attributed.
4. **Confirm the primitive** - trigger one benign marker callback through the injectable context, and the step completes when the marker arrives or every primitive shows a recorded refusal.
5. **Embed a marker label** - send one labeled probe per token and attribute each arrival, and the step completes when the marker label returns intact or embedding is ruled out.
6. **Read metadata** - exfiltrate version plus current user plus database name through labeled callbacks, and the step completes when verifiable metadata is recorded.
7. **Target high-value tables** - pivot from metadata to authentication plus privilege plus file or command primitives, and the step completes when each target shows a read or a reversible proof or a recorded negative.

## False Positives

- **Stop condition**: stop when the listener receives nothing attributable, because unattributed traffic is not exfiltration.
- **Self-origin callbacks**: callback hits whose source matches the tester machine rather than the database, which indicate a client-side request made the connection.
- **Egress-blocked targets**: egress-blocked targets where every labeled probe shows no arrival, which call for the blind fallback rather than a finding.
- **Duplicate arrivals**: cached or replayed arrivals that duplicate an earlier token rather than confirming a new probe.
- **Parameterized queries**: parameterized queries with no string concatenation, verified by code review.

## Pro Tips

- **Callback discipline**: callbacks reward fresh tokens plus short labels plus quiet operation.
- **Oracle-first promotion**: prefer the callback oracle first on silent targets, then promote only stable positives to labeled extraction.
- **Token freshness**: mint one token per probe and never reuse a label across two requests.
- **Short value per probe**: embed one short value per probe so encoding never truncates the data.
- **Metadata first**: read metadata first, then jump directly to business-critical tables with minimal lateral noise.
- **Egress verdict recording**: record egress-blocked verdicts explicitly so later runs fall back to blind extraction without re-probing.

## Summary

A database that calls outward answers exfiltration through callbacks.
Label embedding carries each value, primitive selection opens the channel, and per-token correlation proves every hit before metadata leads to the smallest confirming read.
