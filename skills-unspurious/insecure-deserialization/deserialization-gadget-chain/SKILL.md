---
name: deserialization-gadget-chain
description: Gadget-chain deserialization testing for unsigned object graphs. Triggers on opaque blobs reaching native unmarshallers, on type-tagged values resolving attacker-named types, on self-executing encodings running at decode time.
metadata:
  version: 1.0.0
---

# Deserialization Gadget Chain

Unsigned object graphs reaching native unmarshallers execute attacker-chosen logic through reusable class paths.
This variant proves live deserialization behind a no-exec oracle gate and then assembles an inventory-matched chain or a self-executing payload with a bounded effect.

## Attack Surface

This variant applies where an unsigned blob reaches a native unmarshal sink with attacker-influenced bytes.
The blob arrives at a request locus that the agent can submit to directly.
The sink instantiates object graphs instead of parsing into primitive-only structures.
The runtime library set determines which reusable class paths exist, and that inventory is runtime knowledge.
Stored or wrapper-mediated triggers belong to the deferred-trigger variant, and signature-gated blobs belong to the signed-forgery variant.

## Reconnaissance

Hunt request loci carrying opaque blobs that survive a round trip into server state.
Read format markers to route the run, since magic-byte prefixes and binary content types distinguish native graphs from plain structured data.
Record framework indicators that narrow the unmarshaller family without naming a version in the skill.
Trace backward in white-box views from unmarshal calls to the nearest attacker-influenced source.
Treat server-side session stores as priority loci and test each one or rule it out with an observation.
Stop hunting loci only when every reachable blob-carrying locus has a sink reference or a documented no-sink finding.

## Detection Channels

Magic-byte prefixes on decoded blobs confirm a native graph format is in play.
Framework indicators confirm the unmarshaller family behind the endpoint.
White-box unmarshal sink names confirm the exact decode entry point.
Stack traces naming graph-resolution failures confirm attacker bytes reach the resolver.
No-exec callback or delay oracles confirm live deserialization before any payload with effects is sent.

## Adversarial Capabilities

This variant presupposes the ability to submit blobs at reachable request loci.
It consumes version and library inventory from the runtime knowledge base to select a matching chain.
It operates a callback listener or timing oracle to gate proof without executing effects first.
It mints bounded-effect payloads that demonstrate control with the least destructive action.

## Trust Assumptions

The feature executes an object-graph rehydration step under a standing agreement.
The agreement holds that every consumed blob is sender-faithful and every unsigned graph instantiates only benign object shapes.
The runtime exposes a native unmarshaller, resolves only expected types, and leaks at most a benign error on malformed input.
The exact failing clause is the unsigned-graph clause: the blob arrives without integrity binding and the unmarshaller instantiates attacker-chosen graphs.

## Key Vulnerabilities

Chain assembly matches the fingerprinted library inventory to a reusable class path and binds it behind the no-exec gate.
Type-named construction injects an attacker-chosen type through a discriminator field with property placeholders, using the abstract shape `[TYPE-DISCRIMINATOR, TYPE-NAME-PLACEHOLDER, PROPERTY-PLACEHOLDER]`.
Self-executing encodings run at decode time without inventory matching, using the abstract shape `[EXEC-DIRECTIVE-PLACEHOLDER, ARGUMENT-PLACEHOLDER]`.
The oracle-gated assembly spanning matched and selection-free formats is the delta generic confirm-and-pick language never names.
Each construction path converges on the same gate: no callback or delay confirmation means no effect-bearing payload.

## Advanced Techniques

Fingerprint the library set before assembling anything, since a mismatched chain wastes the run and burns noise budget.
Gate every effect behind the no-exec oracle, starting with callback or delay payloads before any bounded command.
Prioritise session stores early, since they offer the shortest path from blob acceptance to rehydration.
Carry type-named probing as a secondary divergence inside the proof loop, using discriminator-field responses to confirm resolution rather than re-reading markers.

## Bypass Techniques

Layer text encodings or compression wrappers to pass inspection points that match only outer shapes.
Shift the blob across equivalent request loci when one locus is filtered and another feeds the same sink.
Offer alternate structural shapes where the resolver branches on shape, confirming each branch with the oracle.
Name the defence-bypass family at steps that defeat hardened verifiers instead of restating its mechanics here.

When this section does not fulfil the knowledge gap, extend the reading with the defence-bypass and proxy-techniques families.

## Chaining Attacks

Confirmed code execution hands off to command-execution consumers for bounded impact demonstration.
Type-named bindings that reach data-source properties hand off to server-side request consumers where the resolved property opens egress.
Forged identity or role effects hand off to the authorization-principal skill instead of being re-proven here.

## Testing Methodology

1. Map unmarshal sinks to injection loci; the step is complete when each reachable blob-carrying locus has a sink reference or a documented no-sink finding.
2. Confirm the graph format through markers, traces, or fingerprints; the step is complete when the responsible deserializer family and blob shape are recorded.
3. Prove liveness with a no-exec callback or delay oracle; the step is complete when the callback or delay attributes attacker input to deserialization.
4. Assemble the oracle-gated payload by matching library inventory to a chain, naming a type through a discriminator field, or selecting a self-executing encoding with a version rationale; the step is complete when exactly one construction path is chosen with its rationale recorded.
5. Demonstrate bounded execution or critical logic bypass with the least destructive action; the step is complete when the observed effect ties to the gated payload and not to an earlier probe.
6. Cover priority session stores first and revisit skipped loci; the step is complete when each named session locus is tested or ruled out with an observation.

## False Positives

Verified integrity checks that bind the blob before unmarshalling close this variant when the binding uses a strong secret.
Primitive-only whitelists without polymorphic or discriminator-driven types close this variant when every accepted shape parses to inert structures.
Safe loaders and plain-structure parsing close this variant when no object instantiation follows the parse.
Sandboxed rehydration without network or execution primitives neutralises the effect demonstration when isolation is verified thoroughly.
Error text naming graph classes without attacker bytes reaching the sink marks a dead code path rather than a finding.

## Pro Tips

Fingerprint first and fire second, since chain selection depends on inventory rather than guesswork.
Favour callback gadgets over command execution on production-like targets to keep proof bounded.
Trace from unmarshal sinks backward to sources in white-box views to find the shortest attacker-influenced path.
Treat session stores as the early focus, since they rehydrate on almost every authenticated interaction.
Record the inventory rationale beside each payload so a failed run still narrows the next selection.

## Summary

Unsigned graphs that reach native unmarshallers yield control through matched chains, named types, or self-executing encodings.
Gate every run on the no-exec oracle and prove impact with bounded execution only after liveness is confirmed.
Safe patterns parse untrusted input into primitive-only structures, use safe loaders, or bind blobs with verified integrity before any rehydration.
