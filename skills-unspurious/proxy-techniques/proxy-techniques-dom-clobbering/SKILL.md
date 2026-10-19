---
name: proxy-techniques-dom-clobbering
description: DOM clobbering where markup-only injection defines or shadows a named global the application trusts, covering single and nested clobbering when named elements resolve in place of an expected value, base-resolution hijack when the document's base is redirected, and sink reach when the clobbered value is consumed by a URL, markup, evaluation, or resource-load sink.
metadata:
  version: '1.0.0'
---

# DOM Clobbering

A client script reads a global by name, and markup can define that name. This variant injects no script at all: it plants named elements so a global the application trusts resolves to attacker-controlled structure, then drives the clobbered value into a sink. The primitive carries almost no impact alone, and its whole value is the downstream chain, so this leaf is the family's zero-impact primitive and every consumer names it at the step where the clobbered value is consumed.

## Attack Surface

DOM clobbering applicability centers on an injection point that admits markup and a client script that reads a global by name.
The surface holds profile, comment, preview, and rich-text fields that admit markup while stripping script, uploaded documents that the application renders as markup, and any client script that resolves a configuration value, a token, or a destination from a named global.
An allowlist that permits naming attributes, and a script that reads a global without checking its type, both widen the surface.
A page whose scripts read only their own declared values rides outside this variant, because no markup can define what they read.

## Reconnaissance

DOM clobbering maps the globals and their sinks before injecting anything, because a clobberable name with no sink carries nothing.
- Enumerate the globals the client scripts read, and record which of them are resolvable from markup rather than fixed by the runtime.
- Trace each candidate global to the sink it feeds: a navigation, a markup insertion, a string evaluation, or a resource load.
- Map the markup the injection point permits: which elements, which naming attributes, and whether nesting is allowed.
- Record the sanitizer's policy, because an allowlist that permits naming attributes is the precondition for the primitive.

## Detection Channels

DOM clobbering listens to the named global's resolution and to the sink it feeds, so only the entries below are live here.
- A global resolving to an element or a collection in place of its expected value, which proves the name was clobbered.
- The clobbered value appearing at the sink, such as a navigation, a markup insertion, or a resource load carrying the attacker's value.
- A per-attempt unique marker inside the clobbered value, so the sink effect is attributable to this injection rather than to ambient traffic.
- The smallest injected markup that still clobbers, which bounds the primitive's requirements.
- A negative where the global keeps its declared value, which reads as a name the markup cannot resolve.

## Adversarial Capabilities

DOM clobbering presupposes markup injection plus naming control plus a sink trace, and it consumes all three.
- Inject markup that the sanitizer admits while script does not survive it.
- Control the naming attributes of injected elements, including nesting where the allowlist permits it.
- Trace a global read to its sink in the client code, because the primitive is worthless without a consuming step.
- Instrument the page so each global read and each sink invocation is observable rather than inferred.

## Trust Assumptions

The client script trusts that the global it reads by name holds the value the application declared, and the page trusts that markup carrying names and identifiers is presentation rather than behaviour.
The agreement holds a named global to the value the application set, holds the document's base resolution to the document's own location, and holds markup to structure that reaches no sink.
This variant breaks the naming clause because attacker markup defines or shadows a name the script trusts, so the value the script consumes is attacker-controlled structure.
The primitive is claimed only with a sink effect, because a clobbered name that is never consumed is a curiosity rather than a finding.

## Key Vulnerabilities

### Single and Nested Clobbering

- One named element can occupy a global the script reads, and a nested shape built from a container and its named children can reach one level deeper into a namespace the script trusts.
- A named element whose string form is an attacker-chosen destination supplies a value the script treats as a URL rather than as an element.
- Prefer the smallest nested shape that reaches the target property, because each added level depends on the allowlist admitting more markup.

### Base-Resolution Hijack

- Redirecting the document's own base resolution bends every relative resource load and navigation the page performs afterwards, which is clobbering applied to the resolution rule rather than to one name.
- Confirm the page's relative loads before relying on it, because an application that emits absolute references closes this route.

### Sink Reach

- The clobbered value must reach a consuming step: a navigation, a markup insertion, a string evaluation, or a resource load; without one the primitive has no effect.
- Trace the read to the sink in the client code rather than assuming it, because a value that is read and discarded is not a finding.
- Hand the reached sink to the class that owns the consequence rather than restating that class's procedure here.

### Sanitizer Interplay

- An allowlist that admits naming attributes while stripping script is exactly the precondition, so read the sanitizer's element and attribute policy before crafting.
- A sanitizer that rebuilds markup can drop or rename elements, so confirm the clobbered name survives the round trip.

## Bypass Techniques

Bypass shapes are tried only after the injection point and the global read are both mapped, because a name that cannot resolve carries nothing.

- A naming attribute the allowlist admits, planted on an element the allowlist keeps.
- A nested container-and-child shape that reaches one property deeper into a namespace.
- An element whose string form is an attacker-chosen destination, consumed where a URL is expected.
- A base-resolution element that bends every relative reference on the page.
- A markup round trip through a sanitizer that rebuilds structure without renaming the injected elements.

## Chaining Attacks

DOM clobbering is a zero-impact primitive, so every chain names the class that owns the sink's consequence.

- `xss` where the clobbered value reaches a markup insertion or an evaluation sink, because the execution belongs to that class.
- `csrf` where the clobbered name carries a proof-of-intent value, so the clobbered token is the chain's enabling step.
- `open-redirect` and `proxy-techniques-client-side-path-traversal` where the clobbered value is consumed as a destination.
- `prototype-pollution` where the clobbered structure merges into a shared namespace the application later reads.
- `business-logic` where a clobbered configuration value decides a client-side state or flow.
- Name the class at its own step rather than restating its procedure here.

## Testing Methodology

DOM clobbering maps the globals and the sinks first and injects the smallest markup second, because the primitive is worthless without a consuming step.

1. **Map the globals** - every name the client scripts read with its declared value, and the step completes when each candidate global is recorded as markup-resolvable or fixed.
2. **Trace the sinks** - the consuming step each candidate global feeds, and the step completes when each global carries a sink or a recorded dead end.
3. **Map the allowed markup** - the elements, naming attributes, and nesting the injection point admits, and the step completes when the smallest admissible clobbering shape is named.
4. **Inject the smallest shape** - the least markup that resolves the target name, and the step completes when the global resolves to the injected structure.
5. **Drive the flow** - exercise the page so the script reads the clobbered value, and the step completes when the read is observed with the injected value.
6. **Confirm the sink** - the sink invocation carrying the clobbered value with a unique marker, and the step completes when the effect is attributed to this injection.
7. **Attribute and stop** - separate the clobbering primitive from the class that owns the sink's consequence, and the step completes when the chain's enabling step is recorded rather than the whole chain.

## False Positives

Stop when the name cannot resolve or the value reaches no sink, because neither is a clobbering finding.

- A global that is fixed by the runtime or read through a primitive the markup cannot shadow, confirmed by an unchanged value.
- A clobbered name whose value is never consumed, where the read was recorded and discarded.
- An injection point that strips naming attributes, confirmed by the element arriving without its name.
- A sanitizer round trip that rebuilds the markup without the injected structure.
- A sink effect that fires on every page load rather than on the injected marker, which reads as ambient behaviour.

## Pro Tips

DOM clobbering rewards global mapping plus sink tracing plus the smallest admissible markup.

1. Map the globals before injecting, because the primitive is a naming collision rather than a payload.
2. Trace the read to the sink first, since a clobbered value that is never consumed is not a finding.
3. Inject the smallest shape the allowlist admits, so each added element stays justified.
4. Prefer the string-coercing shape where a destination is expected, because it needs no second step.
5. Keep a unique marker inside the clobbered value, so the sink effect is attributable.
6. Hand the sink to the class that owns the consequence, and stop at the enabling step.

## Summary

Markup can define a name the application trusts, and the clobbered value is only as strong as the sink it reaches. DOM clobbering maps the globals and their sinks, injects the smallest admissible shape, and hands the reached sink to the class that owns the consequence.
