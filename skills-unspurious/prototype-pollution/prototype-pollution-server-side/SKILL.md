---
name: prototype-pollution-server-side
description: Server-weaponised prototype pollution turning merged keys into template and process-sink execution. Use when server merges feed template or process-spawning sinks, when a dependency inventory gates chain assembly, when stored payloads merge in background jobs.
metadata:
  version: 1.0.0
---

# Server-Side Prototype Pollution

Server-side prototype pollution corrupts shared prototypes in the server runtime so that attacker-chosen properties flow into template engines, process-spawning wrappers, and module-loading sinks.
A confirmed pollution then becomes a gadget chain the tester assembles against the enumerated dependency inventory.
The result turns an unsafe recursive merge into server-side code execution.

## Attack Surface

**Merge sinks accept user-controlled objects** through recursive merge, extend, defaults, or deep copy on server-reachable paths.
**Key-preserving parsers keep prototype-path keys** across bodies, query strings, multipart fields, socket messages, file imports, and variables.
**Server sinks consume polluted properties** inside template engines, process-spawning wrappers, and module-path resolution.
**Unfrozen prototypes permit the write** because the merge runs before any instance or prototype freezing.

## Detection Channels

**Follow-up reads prove corruption** when a marker set through one request becomes observable through a later request reading shared server state.
**Response deltas signal effect** when status codes, error text, or timing shift after the marker is sent.
**Template output shifts signal effect** when rendered server output carries the marker or a computed result tied to it.
**Out-of-band effects prove execution** when a delay or a created artifact shows a process-spawning sink consumed the polluted property.

## Adversarial Capabilities

**Testers send structured input** through bodies, query strings, multipart fields, socket messages, and file imports.
**Testers read an oracle** across response behavior, error messages, and follow-up state as confirmation of pollution.
**Testers enumerate a dependency inventory** under white-box scope to gate chain assembly on available sinks and versions.
**Testers stage stored payloads** that rest until a background merge or export step triggers them, then re-check for effects.

## Trust Assumptions

The feature agrees that keys arriving from user input are inert data.
Each key supplies a value only and never names prototype machinery.
Every downstream consumer may therefore treat inherited properties as trustworthy defaults.
This agreement fails at the server merge sink, where a recursive merge applies attacker-named keys to a shared prototype feeding template or process-spawning sinks.

## Key Vulnerabilities

**Unsafe merge sinks fold attacker keys** into live server objects without key filtering.
**Unsafe loader sinks feed the same procedure** when structured file-import loaders preserve prototype-path keys into the merge.
**Gadget chains yield server-side execution** when polluted properties flow into template output functions, process-spawning options, and module paths.
**Payload shapes stay abstract** with placeholders denoting the prototype-link key, the intermediate key, the prototype-name key, the marker key, and the marker value.
**Direct wrappers nest the marker pair** under the prototype-link key.
```json
{"<PROTO-KEY>": {"<CANARY>": "<MARKER>"}}
```
**Two-level wrappers nest the marker pair** under the intermediate key and then the prototype-name key.
```json
{"<CTOR-KEY>": {"<PROTO-NAME>": {"<CANARY>": "<MARKER>"}}}
```
**Query-nested forms attach the marker** through bracketed prototype-path segments.
```text
?<PROTO-KEY>[<CANARY>]=<MARKER>
?<CTOR-KEY>[<PROTO-NAME>][<CANARY>]=<MARKER>
```
**Process-control bodies nest process-spawning keys** with attacker-chosen values under the prototype-link key.
**Template-engine bodies nest an output-function key** whose value breaks into server-side execution.
**Lookalike forms spell the prototype-path key** with an encoded or width-variant character that the parser normalizes before the merge.

## Bypass Techniques

**Wrapper swaps evade single-shape filters** by moving between the prototype-link key and the two-level wrapper.
**Array notation evades plain-key blocks** by addressing the marker through an indexed prototype-path slot.
**Lookalike keys evade exact-spelling blocklists** through normalized or width-variant spellings of the prototype-path key.
**Content-type switching evades parser-specific filtering** by replaying the same marker as structured body, urlencoded form, and multipart fields.
**Split pollution evades per-input limits** by spreading the path across inputs that merge sequentially.
**Stored triggering evades immediate inspection** by resting the payload until a background job or export pipeline merges it.
**Operator-key overlap belongs elsewhere** by handing dollar-prefixed or dotted keys to the NoSQL-injection skill at that step.

## Testing Methodology

Shared setup runs first across merge-point mapping, canary proof, shape variation, and channel variation.
The first bent step is the inventory-driven gadget-chain assembly.
The delta over the parent is white-box module enumeration plus version-gated chain assembly plus server-execution proof.

1. **Merge-point mapping locates** recursive merges over user-controlled objects on server-reachable paths.
The step is done when every candidate merge sink is listed.
2. **Canary proof sends a benign unique marker** through one channel and observes it through response behavior or a follow-up shared-state read.
The step is done when shared-prototype corruption or its absence is proven.
3. **Shape variation replays the canary** through each non-chain payload shape in Key Vulnerabilities.
The step is done when every shape shows acceptance or filtering.
4. **Channel variation repeats the canary** across each input channel for the same target.
The step is done when every channel shows acceptance or rejection.
5. **Enumeration assembles the chain** by inventorying server dependencies under white-box scope, gating candidate sinks on available versions, and driving the assembled keys to execution evidence.
The step is done when a server-side gadget chain or its absence is proven.
6. **Delayed-trigger ruling stores the payload** and re-checks after any asynchronous merge completes.
The step is done when delayed effects are captured or confirmed absent.

## False Positives

**Echoes without merges reflect only** while the marker never reaches the object graph, so no follow-up read observes it.
**Stripping parsers drop prototype-path keys** before the merge, so the marker never lands on the prototype.
**Null-prototype options deny a surface** because the framework builds its options objects without a prototype throughout.
**Absent gadgets yield negatives** when the marker pollutes cleanly yet no enumerated sink consumes it.
**Consistent blocking signals enforcement** when every encoding of the marker is rejected uniformly rather than a missed shape.

## Pro Tips

**Canaries come first** because verification with a unique marker precedes any gadget-chain attempt.
**Greps find the sinks** by searching server-reachable code for merge, extend, defaults, and deep-copy helpers over user input.
**Both merge moments matter** across request parsing and background or export merges, including second-order ones.
**Versions gate the claim** by matching each candidate sink against enumerated dependency versions before asserting execution.
**Inventories precede assembly** by letting the white-box module list decide which chains are assemblable on the target.

## Tooling

**Request loops spray shapes** across endpoints with a small sending loop keyed on a canary property while each response and follow-up read is checked for the pollution effect.
**Inventory matching guides assembly** by pairing the white-box dependency list with sink keys for template output functions and process-spawning options.
**Chain building stays manual** because no reliable one-click builder exists for server gadgets.

## Summary

Any server-reachable recursive merge of user-controlled keys is a server-side pollution candidate.
Block prototype-path keys, prefer null-prototype objects, and claim execution only with version-gated chain proof rather than reflected keys.
