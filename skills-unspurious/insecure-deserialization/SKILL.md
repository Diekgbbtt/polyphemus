---
name: insecure-deserialization
description: Insecure deserialization testing across runtime languages covering gadget chains, type confusion, interpolation-triggered remote lookup, and safe validation
metadata:
  version: 1.0.0
---

# Insecure Deserialization

Insecure deserialization passes attacker-controlled byte streams or structured blobs to a native unmarshal function, enabling remote code execution, authentication bypass, and logic manipulation through lifecycle hooks and gadget chains. Test any endpoint accepting serialized objects, session blobs, or opaque binary tokens. Interpolated references reach the same outcome without any blob, so the class also covers a reference value the runtime resolves into a remote load.

## Attack Surface

**Format families**
- **Type-tagged binary object graphs**: where the decoder resolves a class or type name carried in the stream
- **Text formats with explicit type tags**: resolved by polymorphic document mappers
- **Self-executing encodings**: which run code during the decode itself by design
- **Integrity-gated state blobs**: session carriers, view-state style tokens, and stored descriptors
- **Wrapper-triggered implicit deserialization**: where a path reference causes a metadata read
- **Interpolation and lookup sinks**: ordinary fields whose value the runtime resolves as a lookup directive, fetching a remote class or resource with no serialized blob in play
- **Nested envelopes**: compressed and encoded layers around any of the above

**Input locations**
- **Request-borne carriers**: cookies, session carriers, hidden form fields
- **API parameters**: carrying opaque or encoded blobs
- **Transport carriers**: message queues, socket frames, uploaded files
- **Stored carriers**: cache entries and stored columns holding serialized values

## Reconnaissance

### Shape Fingerprinting

- **Blob decoding**: decode candidate blobs and note the leading bytes or prefixes that mark a format family
- **Content-type recording**: record the content type and any custom serialization declaration on the request
- **Stack indicators**: note stack indicators that identify the runtime family behind the endpoint
- **Signature reference**: see `references/deserialization-signatures.md` for the marker shapes behind each format family.

### Unmarshal Sink Discovery

- **Entry-point tracing**: trace every unmarshal entry point in the codebase back to its input source
- **Sink listing**: list the sinks reachable from user-influenced data: parameter decoders, session loaders, message consumers, file-operation paths
- **Interpolation sinks**: list interpolation and lookup sinks that resolve a reference value into a remote load, beside the byte-stream decoders
- **Integrity-check placement**: note which sinks run behind an integrity check and which accept unsigned input

### Trigger Mapping

- **Trigger timing**: for each sink, note whether the decode happens during the request or later, in a batch worker or a file operation
- **Plant storage**: record where a planted blob can be stored before the trigger fires

## Detection Channels

- **Magic-byte prefixes on decoded blobs**: confirm a native graph format is in play.
- **Stack indicators**: confirm the unmarshaller family behind the endpoint.
- **White-box unmarshal sink names**: confirm the exact decode entry point.
- **Stack traces naming graph-resolution failures**: confirm attacker bytes reach the resolver.
- **No-exec callback or delay oracles**: confirm live deserialization before any effect payload is sent.
- **Tamper-rejection responses**: confirm a verifier evaluates the binding before rehydration.
- **Unsigned-fallback acceptance**: confirms a keyless path exists beside the signed one.
- **Re-signed blob acceptance**: confirms a recovered or guessed secret binds correctly.
- **Local re-verification success**: predicts server acceptance before the minted blob is sent.
- **Claim-reflecting behaviour after acceptance**: confirms the forged state took effect.
- **Delayed callbacks**: confirm a planted blob rehydrated after the submission interaction closed.
- **Timing correlation between plant, trigger, and callback**: attributes the effect to the paired loci.
- **File-operation trigger signals**: confirm a path reference reached implicit deserialization.
- **Job and administrative invocation records**: confirm the trigger ran after the plant landed.
- **Lookup-resolution receipt**: an outbound name-resolution or fetch receipt tied to a crafted field value, which confirms an interpolated reference reached a remote loader.
- **Response-class differential**: binding-failure text beside state-invalid text, which separates a rejected binding from a rejected payload shape.

## Adversarial Capabilities

- **Prerequisites**: deserialization testing presupposes control over the input bytes, knowledge of the decode path, and a callback destination, and it consumes all three.
- **Blob crafting**: craft and encode blobs by hand, including nested envelopes around a payload.
- **Sink reach**: reach a sink that runs during or after the request, and store a blob where a later trigger reads it.
- **No-effect oracle**: run a no-effect oracle first: a callback or delay that proves the decode happens.
- **Error reading**: read stack traces and rejection text to orient the next mutation.
- **Second principal**: hold a second principal where the forged state controls identity or role.
- **Lookup hosting**: host a reachable lookup target that serves the attacker's class or records the resolution, where an interpolation sink is in play.
- **Runtime matching**: match the runtime and library inventory of the target before assembling a chain.

## Trust Assumptions

- **The agreement**: the class rests on one agreement: every blob reaching a decoder is data, and the decoder instantiates only types the application itself would have produced. The agreement holds the stream free of attacker-chosen type names, holds lifecycle hooks to unreachable code paths, holds the decoder to an allow-list of types rather than the full runtime, and holds the blob to an integrity binding the attacker cannot mint. Sensitive position leaks when any clause fails: the decoder resolves a type the attacker named, a hook runs during rehydration, or an unsigned path bypasses the binding.
- **The failing clause**: each variant breaks one clause: the type-resolution clause, the integrity clause, or the timing clause.

## Key Vulnerabilities

### Native Object-Graph Chains

- **Attacker-named types**: the decoder resolves attacker-named types and then runs lifecycle hooks, which reach into libraries already on the classpath
- **Chain selection**: chain selection depends on the runtime inventory; enumerate it before assembling
- **Test flow**: confirm the sink, fingerprint the library inventory from errors and bundled artifacts, then deliver a callback-first payload

### Self-Executing Encodings

- **Decode-time execution**: some encodings execute code during decode by design; any input reaching them is effectively execution
- **Safe-oracle first**: a callback or delay confirms the sink before an effect payload is sent

### Type-Tagged Documents

- **Polymorphic mappers**: polymorphic document mappers instantiate the type named in the document when typing is enabled
- **Constructor side effects**: attacker-chosen type names reach constructors and setters that perform side effects
- **Enablement flag**: enablement is often a single configuration flag, so test the flag before the payload

### Lifecycle-Hook Object Injection

- **Rehydration hooks**: rehydration hooks run on the decoded object: wake-up, destructor, string-conversion, and call hooks carry effects
- **Reachable classes**: chains assemble from classes already reachable in the application's dependencies
- **External-resource graphs**: object graphs that reference external resources turn the hook into a fetch or a file read

### Integrity-Gated State Blobs

- **Weak verification**: integrity checks with disabled verification, weak keys, or a keyless fallback path let forged state verify
- **Secret recovery**: recovery of the signing secret lets the attacker mint any state the verifier trusts
- **Typed state carriers**: typed state carriers often control identity or role directly, which makes the forged claim the whole finding

### Wrapper-Triggered Implicit Deserialization

- **Wrapper-scheme path reference**: a path reference that names a wrapper scheme causes a metadata read, which deserializes during a file operation
- **File-operation trigger**: the trigger is any file operation: existence check, size read, copy, or upload
- **Uploadable blob**: the blob itself can be uploaded or stored as an ordinary file

### Interpolation-Triggered Remote Lookup

- **Reference in an ordinary field**: a string carrying a lookup directive in a field the runtime interpolates, such as a logged value or a templated name, causes a remote resolution and a class load with no serialized blob in play
- **Remote basis fetch**: the resolved reference names attacker-controlled material over a resolution protocol, so the loader fetches and instantiates it inside the application's own process
- **No chain required**: this path needs no gadget inventory, so test it beside the byte-stream decoders rather than after them
- **Procedure ownership**: the parent byte-stream description cannot cover a reference-triggered load, so this block owns the interpolation procedure while the object-graph variants stay disjoint

## Advanced Techniques

**Signed Blob Bypass**
- **Weak-secret forging**: where the integrity binding uses a weak secret or an ambiguous algorithm, forge the blob
- **Binding stripping**: strip the binding and test keyless code paths
- **Length extension**: length extension on a simple checksum scheme where the construction allows it

**Second-Order Deserialization**
- **Store then trigger**: store the blob in a stored field or import, then let an export, cache warm, or batch job trigger the decode
- **Attribution**: plant and trigger are separate interactions, so attribute the effect by timing and correlation

**Nested Envelopes**
- **Layer bypass**: compression and encoding layers wrapped around the blob bypass naive content inspection
- **Ordered decoding**: each layer is decoded in order at the target, so the payload survives intact

## Bypass Techniques

- **Alternative parameters**: alternative parameters that store the same session value, where some paths decode without the check
- **Content-type switching**: switching the content type or the parameter location between requests
- **Type confusion**: an array versus an object body reaches different decoder branches
- **Allow-list assembly**: defeat a type allow-list by assembling the chain from types the list still admits, and treat a decoder that admits only primitive structures as the closing control
- **Family handoff**: name the defence-bypass family at the encoding and framing steps for stacked layers and length-field smuggling, rather than restating those mechanics here.

When this section does not fulfil the knowledge gap, extend the reading with the defence-bypass and proxy-techniques families.

## Chaining Attacks

- **Deserialization plus execution**: the decode runs attacker-controlled code with the application's privileges
- **Deserialization plus authorization bypass**: a forged signed state carrier mints identity or role claims
- **Deserialization plus deferred trigger**: the planted blob detonates in an administrative export or batch job
- **Deserialization plus file operations**: a wrapper path turns an ordinary read into a decode
- **Interpolation lookup plus a fetch or a load**: name the ssrf skill where the resolution basis travels over a fetch, and the rce family where the loaded material executes

## Testing Methodology

1. **Find sinks** - Locate decode and unmarshal calls on user-influenced data, including interpolation and lookup sinks that resolve a reference value into a remote load
2. **Confirm format** - Leading bytes, error stack traces, and stack fingerprints
3. **Safe oracle** - A callback or delay before any effect payload, or a lookup-resolution receipt where the sink is interpolation-driven
4. **Chain selection** - Match the runtime and library inventory to an available chain
5. **Minimal proof** - Demonstrate execution or a critical logic bypass with the least destructive effect
6. **Session focus** - Decode server-side session carriers early, since they are the highest-value sink

- **Oracle reference**: see `references/deserialization-oracle.md` for the oracle classes and the bounded-effect discipline behind the safe-oracle step.

## Variants

- deserialization-gadget-chain - Unsigned object graphs reaching native unmarshallers, where type-tagged values resolve attacker-named types or self-executing encodings run at decode time.
- deserialization-signed-forgery - Signature-gated state blobs, where the binding is weakly protected, an unsigned fallback path exists, or mintable claims control identity and role.
- deserialization-deferred-trigger - Stored blobs rehydrated later, including plantable storage read by a later job and wrapper path references consumed by file operations.

## False Positives

- **Sound integrity checks**: blobs verified by a sound integrity check before deserialization
- **Primitive-only decoding**: only primitive values decoded, with no polymorphic types and no object instantiation
- **Plain-map parsing**: inputs parsed into plain maps without object construction
- **Isolated sandbox**: deserialization inside an isolated sandbox with no network or execution primitives, verified thoroughly
- **Dead-path error text**: error text naming a serialization class where the input never reaches the unmarshal call (dead path)
- **Local-only resolution**: an interpolated reference that resolves to a local constant or a disabled loader, with no remote fetch and no class load

## Pro Tips

- **Runtime fingerprinting**: fingerprint the runtime inventory before attempting a chain; the wrong chain wastes time and creates noise
- **Callback-first**: start with callback or delay gadgets before effect payloads on production-like targets
- **Session carriers first**: decode session carriers early; they are both the likeliest sink and the highest-value claim
- **Backward tracing**: in white-box work, trace from the unmarshal call backwards to its input source
- **Legacy verification**: integrity verification disabled on legacy deployments is still common; test it early
- **Bounded proof**: keep the proof bounded and reversible, and stop at the first confirmed decode or claim
- **Interpolation separation**: test interpolation and lookup sinks separately from byte-stream decoders; they carry no object graph and need no chain inventory

## Summary

Treat every deserialization of untrusted data as critical. Safe patterns validate a schema without type polymorphism, resolve no attacker-named types, verify an integrity binding before decode, keep lifecycle hooks unreachable from decoded data, and resolve no attacker-named reference in an interpolated field. Prove impact with a callback or a bounded effect, not with an error stack trace alone.
