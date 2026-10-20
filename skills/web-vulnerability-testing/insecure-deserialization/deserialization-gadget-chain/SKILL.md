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

- **Applicability**: an unsigned blob reaches a native unmarshal sink with attacker-influenced bytes.
- **Request locus**: the blob arrives at a request locus that the agent can submit to directly.
- **Sink behaviour**: the sink instantiates object graphs instead of parsing into primitive-only structures.
- **Runtime inventory**: the runtime library set determines which reusable class paths exist, and that inventory is runtime knowledge.
- **Variant boundaries**: stored or wrapper-mediated triggers belong to the deferred-trigger variant, and signature-gated blobs belong to the signed-forgery variant.

## Reconnaissance

- **Request-locus hunt**: hunt request loci carrying opaque blobs that survive a round trip into server state.
- **Format-marker read**: read format markers to route the run, since magic-byte prefixes and binary content types distinguish native graphs from plain structured data.
- **Framework indicators**: record framework indicators that narrow the unmarshaller family without naming a version in the skill.
- **Backward trace**: trace backward in white-box views from unmarshal calls to the nearest attacker-influenced source.
- **Session-store priority**: treat server-side session stores as priority loci and test each one or rule it out with an observation.
- **Hunt completion**: stop hunting loci only when every reachable blob-carrying locus has a sink reference or a documented no-sink finding.

## Detection Channels

- **Magic-byte prefixes**: confirm a native graph format is in play on decoded blobs.
- **Framework indicators**: confirm the unmarshaller family behind the endpoint.
- **Unmarshal sink names**: confirm the exact decode entry point in white-box views.
- **Graph-resolution stack traces**: confirm attacker bytes reach the resolver.
- **No-exec oracles**: confirm live deserialization before any payload with effects is sent.

## Adversarial Capabilities

- **Blob submission**: presupposes the ability to submit blobs at reachable request loci.
- **Inventory consumption**: consumes version and library inventory from the runtime knowledge base to select a matching chain.
- **Oracle gating**: operates a callback listener or timing oracle to gate proof without executing effects first.
- **Bounded-effect payloads**: mints payloads that demonstrate control with the least destructive action.

## Trust Assumptions

- **The agreement**: the feature executes an object-graph rehydration step where every consumed blob is sender-faithful and every unsigned graph instantiates only benign object shapes, the runtime exposes a native unmarshaller, resolves only expected types, and leaks at most a benign error on malformed input.
- **The failing clause**: the blob arrives without integrity binding and the unmarshaller instantiates attacker-chosen graphs.

## Key Vulnerabilities

- **Chain assembly**: matches the fingerprinted library inventory to a reusable class path and binds it behind the no-exec gate.
- **Type-named construction**: injects an attacker-chosen type through a discriminator field with property placeholders, using the abstract shape `[TYPE-DISCRIMINATOR, TYPE-NAME-PLACEHOLDER, PROPERTY-PLACEHOLDER]`.
- **Self-executing encodings**: run at decode time without inventory matching, using the abstract shape `[EXEC-DIRECTIVE-PLACEHOLDER, ARGUMENT-PLACEHOLDER]`.
- **Name-resolution gadget**: a name-resolution-only gadget is the cheapest liveness probe, because it needs no code execution and no response reading, so it gates every later chain.
- **Interpolation-triggered lookup**: resolves a reference value into a remote load with no object graph in play; the parent lookup block owns the reference shape while this variant owns the graph assembly.
- **Oracle-gated assembly delta**: the oracle-gated assembly spanning matched and selection-free formats is the delta generic confirm-and-pick language never names.
- **Convergence**: each construction path converges on the same gate: no callback or delay confirmation means no effect-bearing payload.

## Advanced Techniques

- **Fingerprint first**: fingerprint the library set before assembling anything, since a mismatched chain wastes the run and burns noise budget.
- **Oracle gating**: gate every effect behind the no-exec oracle, starting with callback or delay payloads before any bounded command.
- **Session-store priority**: prioritise session stores early, since they offer the shortest path from blob acceptance to rehydration.
- **Type-named probing**: carry it as a secondary divergence inside the proof loop, using discriminator-field responses to confirm resolution rather than re-reading markers.

## Bypass Techniques

- **Encoding layering**: layer text encodings or compression wrappers to pass inspection points that match only outer shapes.
- **Request-locus shifting**: shift the blob across equivalent request loci when one locus is filtered and another feeds the same sink.
- **Alternate structural shapes**: offer alternate shapes where the resolver branches on shape, confirming each branch with the oracle.
- **Defence-bypass family naming**: name the family at steps that defeat hardened verifiers instead of restating its mechanics here.
- **Extended reading**: when this section does not fulfil the knowledge gap, extend the reading with the defence-bypass and proxy-techniques families.

## Chaining Attacks

- **Confirmed code execution**: hands off to command-execution consumers for bounded impact demonstration.
- **Data-source bindings**: type-named bindings that reach data-source properties hand off to server-side request consumers where the resolved property opens egress.
- **Forged identity or role effects**: hand off to the authorization-principal skill instead of being re-proven here.

## Testing Methodology

1. Map unmarshal sinks to injection loci; the step is complete when each reachable blob-carrying locus has a sink reference or a documented no-sink finding.
2. Confirm the graph format through markers, traces, or fingerprints; the step is complete when the responsible deserializer family and blob shape are recorded.
3. Prove liveness with a no-exec callback or delay oracle; the step is complete when the callback or delay attributes attacker input to deserialization.
4. Assemble the oracle-gated payload by matching library inventory to a chain, naming a type through a discriminator field, or selecting a self-executing encoding with a version rationale; the step is complete when exactly one construction path is chosen with its rationale recorded.
5. Demonstrate bounded execution or critical logic bypass with the least destructive action; the step is complete when the observed effect ties to the gated payload and not to an earlier probe.
6. Cover priority session stores first and revisit skipped loci; the step is complete when each named session locus is tested or ruled out with an observation.

## False Positives

- **Verified integrity checks**: binding the blob before unmarshalling closes this variant when the binding uses a strong secret.
- **Primitive-only whitelists**: close this variant when every accepted shape parses to inert structures and no polymorphic or discriminator-driven type is accepted.
- **Safe loaders and plain-structure parsing**: close this variant when no object instantiation follows the parse.
- **Sandboxed rehydration**: neutralises the effect demonstration when no network or execution primitive is reachable and isolation is verified thoroughly.
- **Misleading error text**: error text naming graph classes without attacker bytes reaching the sink marks a dead code path rather than a finding.

## Pro Tips

- **Fingerprint first**: fingerprint before firing, since chain selection depends on inventory rather than guesswork.
- **Callback gadgets**: favour callback gadgets over command execution on production-like targets to keep proof bounded.
- **Backward tracing**: trace from unmarshal sinks backward to sources in white-box views to find the shortest attacker-influenced path.
- **Session-store focus**: treat session stores as the early focus, since they rehydrate on almost every authenticated interaction.
- **Inventory rationale**: record the inventory rationale beside each payload so a failed run still narrows the next selection.

## Summary

Unsigned graphs that reach native unmarshallers yield control through matched chains, named types, or self-executing encodings.
Gate every run on the no-exec oracle and prove impact with bounded execution only after liveness is confirmed.
Safe patterns parse untrusted input into primitive-only structures, use safe loaders, or bind blobs with verified integrity before any rehydration.
