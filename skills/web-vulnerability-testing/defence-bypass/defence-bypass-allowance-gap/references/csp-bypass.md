# Content Security Policy Bypass

This note holds the browser-confined script permit: what it enumerates, the directive-level gaps, the enumeration routes to execution, and the no-execution disclosure the same permit still gates.
It is the reference for the browser-confined script permit, classified like the cross-origin read permit under the family's allowance-gap procedure.

## The Permit and the Confinement

A declarative permit lists the origins and constructs that may execute inside a page, and the browser enforces it rather than the server.
The withheld capability is script execution, and the effect is confined to the browser context, so the bypass is proven as execution inside the page rather than as a server-side effect.
A permit that is declared but not enforced, such as a report-only declaration, is a control gap to record rather than a bypass, because nothing was withheld.
The policy's own text is the enumeration, so read the directives that are present, the values they permit, and the restrictions that are absent.

## Directive-Level Gaps

| Gap | What the permit omits | Route to the withheld capability |
|---|---|---|
| Permissive inline allowance | A restriction on inline script | The withheld execution occurs inside the page directly |
| Evaluation allowance | A restriction on runtime evaluation | A string reaches an evaluation primitive the permit admits |
| Missing document-base restriction | A restriction on the document's base resolution | Relative resource loads follow the attacker's base |
| Missing form-destination restriction | A restriction on where forms may submit | The page submits the disclosed value to an attacker destination |
| Missing plugin or object restriction | A restriction on embedded objects | An embedded object executes under the permit's fallback |
| Absent directive | A restriction a sibling directive would have supplied | The capability falls back to a broader directive |

## Enumeration Routes to Execution

An allowed origin that serves a callback-style data endpoint is an execution route, because the permitted origin reflects a caller-supplied callback name into executable content.
An allowed library that carries a gadget is the same route: a template evaluator, a script loader, or a sanitiser with a merge gap turns an allowed script into arbitrary execution.
An allowed indirection that turns data into a destination or into markup reaches the same effect without a new origin.
A policy whose own directive text is attacker-influenced admits a route the author never wrote, which is the permit's enumeration failing from the inside.
Prefer the route the permit itself admits, because it needs no second bypass behind it.

## Secret Permit Values

Some permits rely on a value meant to stay secret: a per-response key, a hash of the permitted content, or a value bound to one page.
Leak the value through a channel the permit does not watch, because the value's confidentiality is the permit's assumption rather than its rule; name `proxy-techniques-css-injection` where the channel is a stylesheet and `proxy-techniques-dom-clobbering` where markup redefines the value the page reads.
Reuse the value across the contexts the permit meant to separate, because a value accepted on a second page or a second response turns one permitted execution into many.
A value accepted in a permissive format is the same gap at the check rather than at the channel.

## No-Execution Disclosure

Where execution is genuinely closed, the permit still gates a data channel: an allowed image, connect, or stylesheet origin can carry the disclosed value out of the page.
The disclosure channel executes nothing, so it is not an execution finding; name the class that owns the disclosed value at its data-channel step.
Read the live permit before crafting the channel, because permitted egress origins decide whether the channel can leave the page at all.

## Consumption

Hand the reached execution to `xss` at its delivery step, and the leaked proof-of-intent value to `csrf` at its replay step.
Name the family at the permit step where the policy's source list is the control under test, and stop at the narrowest proof the permit's own text supports.
