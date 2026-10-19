---
name: nosql-command-protocol-smuggling
description: Command-frame smuggling splitting one key-value request into extra store commands. Use when key or value text concatenates into command construction; when frame delimiters reach the command stream; when injected-command persistence needs proving.
metadata:
  version: 1.0.0
---

# Command Protocol Smuggling

Some key-value paths build store commands by concatenating user text, so crafted bytes split one request into several commands.
This variant smuggles frame delimiters into keys and values, then proves the injected commands persisted and executed.
The smuggling goal is command execution plus persistent store control rather than record filtering.

## Attack Surface

Applicability centers on a command path whose key or value text concatenates into store-command construction.
User input arrives as a key name or a stored value that the builder splices into a framed command stream without delimiter neutralization.
The driver offers a parameterized command form that the code path skips in favor of string assembly.
Filter, script, pipeline, and query-string sinks stay outside this variant and belong to their own siblings.

## Reconnaissance

Reconnaissance maps framing behavior before any smuggling work, because each command path needs its own delimiter test.
Inventory every endpoint whose keys or values flow into command construction, and the step completes when each candidate sink carries a named command field.
Submit delimiter probes and record framing-error text versus silent acceptance, and the step completes when every sink carries a frame-handling verdict.
Enumerate readable and writable key namespaces through benign reads, and the step completes when each sink carries a persistence target or a recorded absence.

## Detection Channels

Injected frames confirm this variant, so only the entries below are live here.
- Framing-error text after delimiter probes that names command or argument expectations.
- Follow-on read showing a smuggled key with attacker-chosen content.
- Boolean response difference between a framed multi-command attempt and its single-command control.
- Latency or volume change from heavy scan frames across large unindexed keyspaces.

## Adversarial Capabilities

Smuggling work presupposes anonymous request ability plus follow-on read ability, and it consumes both.
- Send frame delimiters inside keys and values and compare stream handling.
- Read back smuggled keys to verify persistence with the smallest confirming sample.
- Shape padding commands around the injected frame so surrounding syntax stays valid.
- Hold an authenticated low-privilege session only where the command path requires privilege before executing.

## Trust Assumptions

The feature trusts user input to arrive as plain data values inside declared field shapes from request through filter construction to execution.
The agreement holds filter shape closed to declared fields, keeps interpreter primitives unreachable, keeps stage and collection selection server-side, keeps script bodies server-authored, keeps query strings literal-bound, keeps command frames single, and keeps stored records plus store internals unexposed.
Query answers expose only matched application records, and no predicate truth or store content leaks beyond the intended view.
This variant breaks the frame-singularity clause because input bytes carry frame delimiters into the command stream, so crafted frames execute as additional store commands.

## Key Vulnerabilities

### Frame-Delimiter Smuggling

Submit frame delimiters inside a key or value so the stream parser closes the intended command early and opens an injected one, because concatenation preserves the delimiter bytes.
Wrap the injected command with padding fragments that absorb the trailing syntax of the original command.
The parent store step names command construction without describing delimiter framing, so this variant owns the smuggling procedure.
```text
<KEY><FRAME-BREAK><INJECTED-COMMAND><FRAME-BREAK><PADDING-KEY>
<VALUE><FRAME-BREAK><INJECTED-COMMAND><FRAME-BREAK><PADDING-VALUE>
```

### Injected-Command Persistence

Shape the injected frame as a write of attacker-chosen content under a marker key, because a follow-on read of that key proves execution beyond parser acceptance.
Read the marker key once and treat present content as execution proof and absent content as a failed frame.
The parent store step never states marker-based persistence verification, so this variant owns the persistence procedure.

### Scan-Cost Pressure

Submit heavy scan frames with large membership lists against unindexed fields only within explicitly authorized scope, because linear scans convert one frame into disproportionate store work.
Treat latency or volume change as a cost signal rather than an execution proof and confirm through marker reads.

## Bypass Techniques

Bypass forms stay aspects inside this variant because no encoding difference changes the frame-splitting step itself.
- Encoded line breaks reach the stream parser past filters that match only literal delimiter bytes.
- Split delimiters across key and value halves reach the parser past per-field length checks that inspect each half alone.
- Padding-command shapes reach the parser past trailing-syntax validation that assumes single commands.
- Mixed text and binary framings reach the parser past checks written for one framing only.

When this section does not fulfil the knowledge gap, extend the reading with the defence-bypass and proxy-techniques families.

## Chaining Attacks

Frames chain forward into control because one smuggled command without a follow-up read is only a probe.
- Pivot from a smuggled write to a marker-key read for the smallest execution proof.
- Pivot from a marker read to privilege or configuration keys for the smallest confirming escalation.
- Pivot from framing-error text to argument expectations that sharpen the next frame.
- Reach the command port from the interior: hand the fetch step to the `ssrf` class and the relay step to the `proxy-techniques` family rather than restating their mechanics here.
- Stop each chain at the smallest read or reversible proof that confirms the architectural risk.

## Testing Methodology

Smuggling work runs frame mapping first and persistence proving second, because no injected command proves anything until its delimiters are known live.
The first bent step is the S9 store step command-frame sub-value, namely delimiter framing plus injected-command persistence.
The delta over the parent is the frame-splitting procedure plus the padding discipline plus the marker-based persistence verification that S9 lists without describing.
1. **Inventory command sinks** - list every endpoint whose keys or values reach command construction, and the step completes when no unlisted sink remains.
2. **Probe frame handling** - submit delimiter probes beside single-command controls, and the step completes when every sink carries a frame-handling verdict.
3. **Map key namespaces** - enumerate readable and writable key spaces through benign reads, and the step completes when each sink carries a persistence target or a recorded absence.
4. **Smuggle benign frames** - submit delimiter splits with harmless injected commands and padding, and the step completes when each sink shows framing or a recorded negative.
5. **Prove persistence** - shape injected frames as marker-key writes and read each marker once, and the step completes when every frame carries an execution proof or a recorded negative.
6. **Measure scan cost** - submit heavy scan frames within authorized scope and record latency or volume change, and the step completes when each sink carries a cost verdict or a ruled-cheap negative.

## False Positives

Stop when commands answer as single framed units, because neutralized delimiters without extra execution are safe.
- Parameterized command forms that bind keys and values outside the frame grammar, verified by code review.
- Delimiter neutralization that strips or escapes frame bytes before stream assembly.
- Uniform responses across framed attempts and single-command controls, which carry no execution information.
- Marker-key absence after a framed attempt, which refutes execution rather than proving filtering alone.

## Pro Tips

Frames reward delimiter patience plus marker discipline plus minimal writes.
1. Prove delimiter handling with harmless frames before attempting any persistent write.
2. Shape padding around each injected command so trailing syntax never breaks the stream.
3. Verify every frame with one marker-key read rather than bulk extraction.
4. Read framing-error text for argument expectations that sharpen the next frame.
5. Keep scan-cost frames inside explicitly authorized scope and treat cost signals as secondary to marker proofs.

## Summary

A command path that concatenates input into the stream answers crafted delimiters with extra commands.
Frame splitting proves the injection, marker-key reads prove the execution, and the smallest follow-up read confirms the control.
