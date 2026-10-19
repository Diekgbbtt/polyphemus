# Intermediary Role Map

This note holds the roles a component between the caller and the effect can play, the inputs each role lets the caller influence, and the proof each role's contribution needs.

## The Roles

| Role | What it does | Caller-influenced inputs | Proof of its contribution |
|---|---|---|---|
| Resolver | Answers a name more than once between the approval and the connection | The record the name answers with, and its lifetime | The second answer differing from the first, and an arrival at the second answer |
| Redirector or forwarder | Answers with a destination and follows it | The destination value, its shape, and the hop count | The arrival at a destination the approver never saw |
| Relay or gateway | Forwards the request with its own view of the authority, the client address, the scheme, or the destination | The fields it forwards or lets the caller supply | The origin acting on a value the caller supplied through the relay's own fields |
| Shared cache | Stores a response under a key and serves it to a later caller | The selectors that shape the body, the key's coverage, and the entry's eligibility | A second caller reading an entry produced for another |
| Second carrier | Carries one operation through a content type, verb, transport, endpoint, session, device, protocol version, or batch envelope | The choice of carrier | The same operation passing on a carrier whose guard differs from the primary carrier's |
| Consumer library | Resolves a destination value for its own connection at a different moment than the enforcing side | The value completed against its own base | The derived target differing from the approved one |
| Client-side structure | Reads the document's own names, globals, or styles | Markup the page admits, and the client-built request path | The script consuming attacker-controlled structure, or a request path the page never chose |

## The Pair Rule

Every role's effect is claimed against a paired baseline: the same operation sent directly and through the intermediary, with the operation identical across the pair.
The pair separates the path's contribution from the effect, because an arrival the direct route also produces carries nothing.
An arrival whose source is the tester's client rather than an intermediary reads as a client-side request, not as a proxy effect.

## Separation Rules

Separate the layers before composing anything: an authority field that selects the upstream, a path-override field that restates the routed path, and a destination value a later hop follows act at different layers and never compose into one request.
A reflection is not trust: the value must reach a decision or an arrival, not merely appear in the response.
Cached-for-you is not cached-for-others: an entry the producing caller alone can read proves nothing about the key's reach.
A stored verdict is not a stored body: the tier-gap family owns the verdict, and the cache-key family owns the body.

## Reading the Intermediary

Read the intermediary's own state where it is reachable, such as a stored entry, a forwarded field set, or a stored verdict, rather than inferring it from the response.
Land every probe under a throwaway key where a shared cache is in the path, because a stored probe is a live entry rather than a test.
Prove the second hop at operated infrastructure before crafting the next hop, because a silent hop is not a blocked one.
