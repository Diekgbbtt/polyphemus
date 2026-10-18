---
name: prototype-pollution
description: Client and server prototype pollution testing covering JavaScript object merge bugs, server-side runtime RCE chains, and filter bypasses
metadata:
  version: 1.0.0
---

# Prototype Pollution

Prototype pollution corrupts shared object prototypes through unsafe merges of user-controlled keys, which leads to logic bypass, denial of service, and remote code execution on runtimes with consuming sinks. Test anywhere user input merges into objects without safe key filtering.

## Attack Surface

**Runtimes**
- Browser-consumed objects and server-side runtimes that share prototype-based objects
- Structured parsers that preserve prototype-shaped keys
- Template engines and configuration merge utilities

**Input Vectors**
- Structured request bodies, query strings, and form fields
- Encoded nested objects in parameter notation
- Socket messages, schema-layer variables, and import formats

**Vulnerable Patterns**
- Recursive merge and extend helpers: deep merge functions, framework extend calls, custom assign loops
- Query and body parsers that build nested objects from bracketed keys
- Routing, state hydration, and SDK configuration merges that consume shared defaults
- Stored inputs that a later job, export pipeline, or render path merges

## Reconnaissance

### Merge-Point Discovery

- Trace every extend, merge, defaults, deep-copy, and configuration-merge call that consumes user-influenced data
- Note parsers that build nested structures from bracketed or dotted keys
- Note stored inputs that a background job or export merges second-order

### Baseline Canary

- Send a benign pollution marker under a unique key, then read an unrelated object, a later request, or a rendering path for the marker
- Verify through response behavior, error text, or a follow-up read that shares the object state
- A marker that never lands marks a safe merge; a marker that lands marks the candidate surface

### Shape and Channel Matrix

- Enumerate the key-shape families accepted per carrier: prototype-key forms, constructor-chain forms, and encoded nested forms
- Send the same marker over each carrier the endpoint accepts and record which merges it

## Detection Channels

- Follow-up reads prove corruption when a marker set through one input becomes observable through a later request or an unrelated object.
- Routing shifts signal effect when navigation, route guards, or view selection behave differently after the marker is sent.
- Auth-interface shifts signal effect when privilege-gated controls render, unlock, or disappear once the marker lands.
- Rendering shifts signal effect when markup, script-loader behavior, or configuration-driven output changes in a way tied to the marker.
- Response deltas signal effect when status codes, error text, or timing shift after the marker is sent.
- Template output shifts signal effect when rendered server output carries the marker or a computed result tied to it.
- Out-of-band effects prove execution when a delay or a created artifact shows a process-spawning sink consumed the polluted property.

## Adversarial Capabilities

Prototype pollution testing presupposes a merge path that consumes user-controlled keys, a marker channel, and a consuming gadget, and it consumes all three.
- Reach a merge, extend, or configuration path that consumes attacker-shaped keys.
- Deliver the same key shape over every carrier the endpoint accepts.
- Observe shared object state through an unrelated read, a later request, or a rendering path.
- Enumerate the dependency inventory where white-box access exists and match polluted keys to consuming sinks.
- Hold a privilege contrast where a polluted flag changes an authorization outcome.

## Trust Assumptions

The class rests on one agreement: objects are built from the application's own defaults, and caller-supplied keys never reach the shared prototype.
The agreement holds merged input to own, application-chosen keys, holds shared prototypes frozen or absent from merge paths, holds consuming gadgets to properties the application set itself, and holds every carrier class to the same key filtering.
Sensitive logic and execution position leak when a caller-supplied key lands on a shared prototype that a consuming gadget reads.
Each variant breaks one clause at a different consumer: browser-side routing, rendering, and privilege consumers, or server-side template and process-spawning consumers.

## Key Vulnerabilities

### Client-Side Effects

- Privilege flags read from shared defaults grant UI or route access once polluted
- Markup and script-loader sinks consume polluted properties and reach script execution
- Routing, analytics, and SDK configuration read polluted defaults and change behavior
- Trusted-content channels that also merge keys carry the same class

### Server-Side Merge Sinks

- Deep merge and extend helpers that recurse into attacker-controlled structured input
- Body and query parsers that construct nested objects from bracketed keys
- Document loaders that honour prototype keys rather than constructing keyless objects
- Parse-then-merge patterns that copy attacker input onto shared state

### Process and Template Chains

- Polluted properties consumed by template rendering reach expression evaluation
- Environment-like properties consumed by process spawners reach command execution
- Module-resolution and require-path properties can redirect loading when polluted
- Gadget availability is inventory-specific: confirm the consuming sink and its version before claiming execution

### Freeze and Seal Gaps

- Pollution before a freeze applies to the instance but not the prototype it inherits from
- Objects created after the merge inherit the polluted property without further input

## Advanced Techniques

**Second-Order and Stored Pollution**
- Store the marker through a normal write, then trigger the merge in a background job, export, or report pipeline
- Stored forms survive restarts of the request path and reach consumers the request never touches

**Split and Layered Delivery**
- Split the key shape across several parameters that merge sequentially into one object
- Layer encoding around the key so the parser unwraps one layer and the merge unwraps the next

## Bypass Techniques

**Key Shaping**
- Substitute one prototype-key form for another when a filter removes only the obvious one
- Chain through the constructor path when the direct prototype key is filtered
- Nested and encoded forms that unwrap after the filter stage

**Carrier Switching**
- Move the same marker between structured body, form fields, query string, and socket messages
- Bracket and dotted notation where parsers disagree on which is the key

**Filter Gaps**
- Array and index shapes that reach the prototype through a different path
- Normalization variants of the key that compare unequal to a filter list
- Second-order delivery where the stored form merges after the filter stage

## Chaining Attacks

- Pollution to markup-sink execution on the client
- Pollution to template evaluation or process spawn on the server
- Pollution plus schema-layer variables where a resolver passes variables into a merge
- Pollution plus decoding of untrusted blobs where a decoded object graph merges into shared state
- Pollution plus shared caches where polluted defaults carry into rendered output

## Testing Methodology

1. **Identify merge points** - Search for extend, merge, defaults, and deep-copy calls on user-controlled objects
2. **Baseline canary** - Inject a benign marker under a unique key and verify it lands on shared state
3. **Shape variants** - Test prototype-key, constructor-chain, and nested bracket notation
4. **Channel matrix** - Send the same key over each carrier the endpoint accepts
5. **Gadget mapping** - Map polluted keys to consuming sinks in the dependency inventory: template, process, routing
6. **Consumer proof** - Confirm the effect at the consumer (routing change, rendering change, execution artifact) rather than at the key echo

## Variants

- prototype-pollution-client-side - Turn merged keys into browser-consumed routing, auth, and rendering effects, proved through unrelated reads and interface shifts.
- prototype-pollution-server-side - Turn merged keys into server template and process-spawning sink execution, proved through follow-up reads plus out-of-band effects.

## False Positives

- The parser strips prototype-shaped keys before the merge, so the marker never appears on the shared prototype
- Options objects are constructed with no prototype throughout
- The polluted key is visible in a structured echo but never merged into an object graph
- Client-side pollution blocked by frozen prototypes in hardened consumers - verify there is no behavioral change
- A payload filter blocks the probe and alternate encodings reproduce the filter rather than the pollution

## Pro Tips

1. Verify pollution with a unique canary key before attempting any execution gadget
2. In white-box scope, grep for merge, extend, defaults, and assign calls that consume user input
3. Check both request parsing and response-side configuration merges; second-order merges are easy to miss
4. Server gadget chains are version-specific - confirm the package version before claiming execution
5. Combine with template injection when polluted keys flow into rendering configuration
6. Prefer the consumer effect as proof: a routing change, an interface shift, or an execution artifact beats a reflected marker

## Tooling

Detection is mostly about key shapes plus manual verification, so use a spray harness and a gadget reference:
- A request-spraying harness that fans the same canary key across many endpoints and carriers, then flags responses that show the pollution effect
- Published gadget references that map polluted keys to concrete client-side sinks per library, used to turn a confirmed pollution into real impact
- For server-side chains there is no one-click tool: enumerate the dependency inventory in white-box scope and match polluted keys to consuming sinks

## Summary

Any unsafe recursive merge of user-controlled keys is a prototype pollution candidate. Filter prototype keys at every merge boundary, construct options objects without a prototype, freeze shared prototypes, and validate impact with behavioral proof rather than a reflected key.
