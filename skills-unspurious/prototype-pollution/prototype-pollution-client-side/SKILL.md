---
name: prototype-pollution-client-side
description: Browser-consumed prototype pollution turning merged keys into routing, auth, and DOM effects. Use when rendering or routing derives from inherited properties, when privilege flags arrive through shared defaults, when a confirmed pollution needs per-library sink proof.
metadata:
  version: 1.0.0
---

# Client-Side Prototype Pollution

Client-side prototype pollution corrupts shared object prototypes in the browser so that attacker-chosen defaults flow into live application state.
Routing decisions, privilege-gated interface elements, and rendering sinks then consume those defaults as if the application had set them.
The result turns an unsafe recursive merge into privilege bypass and script execution inside the victim session.

## Attack Surface

**Merge sinks accept user-controlled objects** through recursive merge, extend, defaults, or deep copy in browser-reachable code.
**Key-preserving parsers keep prototype-path keys** across structured bodies, query strings, multipart fields, socket messages, and file imports.
**Browser consumers read inheritable properties** inside routing logic, auth-state checks, and rendering sinks.
**Unfrozen prototypes permit the write** because the merge runs before any instance or prototype freezing.

## Detection Channels

**Unrelated reads prove corruption** when a marker set through one input becomes readable through an unrelated object or a later render.
**Routing shifts signal effect** when navigation, route guards, or view selection behave differently after the marker is sent.
**Auth-interface shifts signal effect** when privilege-gated controls render, unlock, or disappear once the marker lands.
**Rendering shifts signal effect** when markup, script-loader behavior, or configuration-driven output changes in a way tied to the marker.

## Adversarial Capabilities

**Testers send structured input** through bodies, query strings, multipart fields, socket messages, and file imports.
**Testers drive a browser session** far enough to observe routing, privilege-gated interface state, and rendering outcomes.
**Testers read a gadget catalog** that maps polluted keys to concrete per-library sink rules.
**Testers isolate each attempt** by minting unique marker keys so every effect traces to exactly one probe.

## Trust Assumptions

The feature agrees that keys arriving from user input are inert data.
Each key supplies a value only and never names prototype machinery.
Every downstream consumer may therefore treat inherited properties as trustworthy defaults.
This agreement fails at the browser consumer, where a routing, auth-state, or rendering consumer reads an attacker-named prototype property as its own configuration.

## Key Vulnerabilities

**Gadget effects flip privilege checks** when a polluted flag reaches a check that reads it from the prototype chain.
**Gadget effects reach rendering sinks** when a polluted property flows into markup or script loading and executes attacker-chosen content.
**Gadget effects steer configuration** when a polluted defaults entry drives session or option handling that the application reads from merged objects.
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
**Array-index forms address a numeric slot** through the prototype-link key.
**Lookalike forms spell the prototype-path key** with an encoded or width-variant character that the parser normalizes before the merge.

## Bypass Techniques

**Wrapper swaps evade single-shape filters** by moving between the prototype-link key and the two-level wrapper.
**Array notation evades plain-key blocks** by addressing the marker through an indexed prototype-path slot.
**Lookalike keys evade exact-spelling blocklists** through normalized or width-variant spellings of the prototype-path key.
**Content-type switching evades parser-specific filtering** by replaying the same marker as structured body, urlencoded form, and multipart fields.
**Split pollution evades per-input limits** by spreading the path across inputs that merge sequentially.
**Stored triggering evades immediate inspection** by resting the payload until a later background merge or export step activates it.

## Testing Methodology

Shared setup runs first across merge-point mapping, canary proof, shape variation, and channel variation.
The first bent step is the catalog-driven client-sink proof.
The delta over the parent is gadget-catalog consultation plus per-library sink driving to behavioral proof.

1. **Merge-point mapping locates** recursive merges over user-controlled objects on client-reachable paths.
The step is done when every candidate merge sink is listed.
2. **Canary proof sends a benign unique marker** through one channel and reads it back through an unrelated object or render.
The step is done when shared-prototype corruption or its absence is proven.
3. **Shape variation replays the canary** through each payload shape in Key Vulnerabilities.
The step is done when every shape shows acceptance or filtering.
4. **Channel variation repeats the canary** across each input channel for the same target.
The step is done when every channel shows acceptance or rejection.
5. **Catalog consultation drives client sinks** by looking up the confirmed marker in the per-library gadget catalog and proving each listed sink across routing, auth state, and rendering.
The step is done when every catalog-listed sink reachable from the marker shows an effect or its absence.
6. **Delayed-trigger ruling stores the payload** and re-checks after any asynchronous merge completes.
The step is done when delayed effects are captured or confirmed absent.

## False Positives

**Echoes without merges reflect only** while the marker never reaches the object graph, so no unrelated read observes it.
**Stripping parsers drop prototype-path keys** before the merge, so the marker never lands on the prototype.
**Frozen prototypes block behavioral change** even though the marker sends cleanly, so no consumer reacts to it.
**Consistent blocking signals enforcement** when every encoding of the marker is rejected uniformly rather than a missed shape.

## Pro Tips

**Canaries come first** because verification with a unique marker precedes any gadget attempt.
**Greps find the sinks** by searching client-reachable code for merge, extend, defaults, and deep-copy helpers over user input.
**Both merge moments matter** across request parsing and rendering-configuration merges, including second-order ones.
**Catalogs lead the proof** by matching each confirmed marker to sink rules before hand-driving effects.
**Renders deserve follow-through** by combining with client-side template injection when polluted keys flow into rendering configuration.

## Tooling

**Request loops spray shapes** across endpoints with a small sending loop keyed on a canary property while each response and render is checked for the pollution effect.
**Gadget catalogs serve as the sink reference** that turns a confirmed pollution into library-specific impact.
**Behavioral confirmation stays manual** because no reliable one-click prover exists for client effects.

## Summary

Any browser-reachable recursive merge of user-controlled keys is a client-side pollution candidate.
Block prototype-path keys, prefer null-prototype objects, and claim impact only with catalog-backed behavioral proof rather than reflected keys.
