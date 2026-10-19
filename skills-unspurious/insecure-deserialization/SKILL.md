---
name: insecure-deserialization
description: Insecure deserialization testing across runtime languages covering gadget chains, type confusion, and safe validation
metadata:
  version: 1.0.0
---

# Insecure Deserialization

Insecure deserialization passes attacker-controlled byte streams or structured blobs to a native unmarshal function, enabling remote code execution, authentication bypass, and logic manipulation through lifecycle hooks and gadget chains. Test any endpoint accepting serialized objects, session blobs, or opaque binary tokens.

## Attack Surface

**Format families**
- Type-tagged binary object graphs, where the decoder resolves a class or type name carried in the stream
- Text formats with explicit type tags, resolved by polymorphic document mappers
- Self-executing encodings, which run code during the decode itself by design
- Integrity-gated state blobs: session carriers, view-state style tokens, and stored descriptors
- Wrapper-triggered implicit deserialization, where a path reference causes a metadata read
- Nested envelopes: compressed and encoded layers around any of the above

**Input locations**
- Cookies, session carriers, hidden form fields
- API parameters carrying opaque or encoded blobs
- Message queues, socket frames, uploaded files
- Cache entries and stored columns holding serialized values

## Reconnaissance

### Shape Fingerprinting

- Decode candidate blobs and note the leading bytes or prefixes that mark a format family
- Record the content type and any custom serialization declaration on the request
- Note stack indicators that identify the runtime family behind the endpoint

### Unmarshal Sink Discovery

- Trace every unmarshal entry point in the codebase back to its input source
- List the sinks reachable from user-influenced data: parameter decoders, session loaders, message consumers, file-operation paths
- Note which sinks run behind an integrity check and which accept unsigned input

### Trigger Mapping

- For each sink, note whether the decode happens during the request or later, in a batch worker or a file operation
- Record where a planted blob can be stored before the trigger fires

## Detection Channels

- Magic-byte prefixes on decoded blobs, which confirm a native graph format is in play.
- Stack indicators that confirm the unmarshaller family behind the endpoint.
- White-box unmarshal sink names that confirm the exact decode entry point.
- Stack traces naming graph-resolution failures, which confirm attacker bytes reach the resolver.
- No-exec callback or delay oracles, which confirm live deserialization before any effect payload is sent.
- Tamper-rejection responses, which confirm a verifier evaluates the binding before rehydration.
- Unsigned-fallback acceptance, which confirms a keyless path exists beside the signed one.
- Re-signed blob acceptance, which confirms a recovered or guessed secret binds correctly.
- Local re-verification success, which predicts server acceptance before the minted blob is sent.
- Claim-reflecting behaviour after acceptance, which confirms the forged state took effect.
- Delayed callbacks, which confirm a planted blob rehydrated after the submission interaction closed.
- Timing correlation between plant, trigger, and callback, which attributes the effect to the paired loci.
- File-operation trigger signals, which confirm a path reference reached implicit deserialization.
- Job and administrative invocation records, which confirm the trigger ran after the plant landed.

## Adversarial Capabilities

Deserialization testing presupposes control over the input bytes, knowledge of the decode path, and a callback destination, and it consumes all three.
- Craft and encode blobs by hand, including nested envelopes around a payload.
- Reach a sink that runs during or after the request, and store a blob where a later trigger reads it.
- Run a no-effect oracle first: a callback or delay that proves the decode happens.
- Read stack traces and rejection text to orient the next mutation.
- Hold a second principal where the forged state controls identity or role.
- Match the runtime and library inventory of the target before assembling a chain.

## Trust Assumptions

The class rests on one agreement: every blob reaching a decoder is data, and the decoder instantiates only types the application itself would have produced.
The agreement holds the stream free of attacker-chosen type names, holds lifecycle hooks to unreachable code paths, holds the decoder to an allow-list of types rather than the full runtime, and holds the blob to an integrity binding the attacker cannot mint.
Sensitive position leaks when any clause fails: the decoder resolves a type the attacker named, a hook runs during rehydration, or an unsigned path bypasses the binding.
Each variant breaks one clause: the type-resolution clause, the integrity clause, or the timing clause.

## Key Vulnerabilities

### Native Object-Graph Chains

- The decoder resolves attacker-named types and then runs lifecycle hooks, which reach into libraries already on the classpath
- Chain selection depends on the runtime inventory; enumerate it before assembling
- Test flow: confirm the sink, fingerprint the library inventory from errors and bundled artifacts, then deliver a callback-first payload

### Self-Executing Encodings

- Some encodings execute code during decode by design; any input reaching them is effectively execution
- Safe-oracle first: a callback or delay confirms the sink before an effect payload is sent

### Type-Tagged Documents

- Polymorphic document mappers instantiate the type named in the document when typing is enabled
- Attacker-chosen type names reach constructors and setters that perform side effects
- Enablement is often a single configuration flag, so test the flag before the payload

### Lifecycle-Hook Object Injection

- Rehydration hooks run on the decoded object: wake-up, destructor, string-conversion, and call hooks carry effects
- Chains assemble from classes already reachable in the application's dependencies
- Object graphs that reference external resources turn the hook into a fetch or a file read

### Integrity-Gated State Blobs

- Integrity checks with disabled verification, weak keys, or a keyless fallback path let forged state verify
- Recovery of the signing secret lets the attacker mint any state the verifier trusts
- Typed state carriers often control identity or role directly, which makes the forged claim the whole finding

### Wrapper-Triggered Implicit Deserialization

- A path reference that names a wrapper scheme causes a metadata read, which deserializes during a file operation
- The trigger is any file operation: existence check, size read, copy, or upload
- The blob itself can be uploaded or stored as an ordinary file

## Advanced Techniques

**Signed Blob Bypass**
- Where the integrity binding uses a weak secret or an ambiguous algorithm, forge the blob
- Strip the binding and test keyless code paths
- Length extension on a simple checksum scheme where the construction allows it

**Second-Order Deserialization**
- Store the blob in a stored field or import, then let an export, cache warm, or batch job trigger the decode
- Plant and trigger are separate interactions, so attribute the effect by timing and correlation

**Nested Envelopes**
- Compression and encoding layers wrapped around the blob bypass naive content inspection
- Each layer is decoded in order at the target, so the payload survives intact

## Bypass Techniques

- Alternative parameters that store the same session value, where some paths decode without the check
- Switching the content type or the parameter location between requests
- Type confusion: an array versus an object body reaches different decoder branches
- Name the defence-bypass family at the encoding and framing steps for stacked layers and length-field smuggling, rather than restating those mechanics here.

## Chaining Attacks

- Deserialization plus execution: the decode runs attacker-controlled code with the application's privileges
- Deserialization plus authorization bypass: a forged signed state carrier mints identity or role claims
- Deserialization plus deferred trigger: the planted blob detonates in an administrative export or batch job
- Deserialization plus file operations: a wrapper path turns an ordinary read into a decode

## Testing Methodology

1. **Find sinks** - Locate decode and unmarshal calls on user-influenced data
2. **Confirm format** - Leading bytes, error stack traces, and stack fingerprints
3. **Safe oracle** - A callback or delay before any effect payload
4. **Chain selection** - Match the runtime and library inventory to an available chain
5. **Minimal proof** - Demonstrate execution or a critical logic bypass with the least destructive effect
6. **Session focus** - Decode server-side session carriers early, since they are the highest-value sink

## Variants

- deserialization-gadget-chain - Unsigned object graphs reaching native unmarshallers, where type-tagged values resolve attacker-named types or self-executing encodings run at decode time.
- deserialization-signed-forgery - Signature-gated state blobs, where the binding is weakly protected, an unsigned fallback path exists, or mintable claims control identity and role.
- deserialization-deferred-trigger - Stored blobs rehydrated later, including plantable storage read by a later job and wrapper path references consumed by file operations.

## False Positives

- Blobs verified by a sound integrity check before deserialization
- Only primitive values decoded, with no polymorphic types and no object instantiation
- Inputs parsed into plain maps without object construction
- Deserialization inside an isolated sandbox with no network or execution primitives, verified thoroughly
- Error text naming a serialization class where the input never reaches the unmarshal call (dead path)

## Pro Tips

1. Fingerprint the runtime inventory before attempting a chain; the wrong chain wastes time and creates noise
2. Start with callback or delay gadgets before effect payloads on production-like targets
3. Decode session carriers early; they are both the likeliest sink and the highest-value claim
4. In white-box work, trace from the unmarshal call backwards to its input source
5. Integrity verification disabled on legacy deployments is still common; test it early
6. Keep the proof bounded and reversible, and stop at the first confirmed decode or claim

## Summary

Treat every deserialization of untrusted data as critical. Safe patterns validate a schema without type polymorphism, resolve no attacker-named types, verify an integrity binding before decode, and keep lifecycle hooks unreachable from decoded data. Prove impact with a callback or a bounded effect, not with an error stack trace alone.
