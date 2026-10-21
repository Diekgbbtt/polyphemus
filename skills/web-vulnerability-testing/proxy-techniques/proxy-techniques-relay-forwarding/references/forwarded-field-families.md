# Forwarded Field Families

This note holds the forwarded-field families by role, the decision each family reaches, the layer it acts at, and the confirmation its effect needs.

## Field Families

| Family | What it carries | Decision it reaches | Layer | Confirmation |
|---|---|---|---|---|
| Authority family | The host the request is for | The upstream the front tier selects, or a link the origin builds | Routing or construction | The origin's decision read, or an out-of-band fetch of the supplied host |
| Authority alternates | A historical or vendor spelling of the authority | The same decisions where a proxy forwards the alternate | Routing or construction | The family that reaches a decision while the primary field is ignored |
| Client-address family | The peer address the origin reads | A boundary check, an allowlist, or a rate decision | Accounting or permit | The decision changing with the supplied address while the real peer is constant |
| Scheme and transport family | The transport the origin reads | A secure-transport check or a redirect the origin builds | Transport or construction | The origin acting on the supplied scheme |
| Destination and forwarding family | The destination the request travelled through | A link the origin builds, or a routing decision | Construction or routing | The built link or the reached destination |
| Path-override family | A path the executor routes to | The routed path, applied after the front tier's decision | Rewrite | A status or body diff against the front tier's own answer |
| Method-override family | A verb the executor applies | The handler the request reaches | Rewrite | The same handler answering the overridden verb |
| Host-override family | A second authority occurrence | The authority the origin reads | Parsing | The reader that consumes the second occurrence |

## The Layer Rule

Separate the layers before composing anything: an authority field that selects the upstream, a path-override field that restates the routed path, and a destination value a later hop follows act at different layers and never compose into one request.
Probe each layer alone, because a composed request proves nothing about either mechanism.
Keep the real authority in place when probing a path-override family, and keep the path in place when probing an authority family.

## Construction Decisions

The decisions a supplied value reaches are the artefacts the origin builds: a recovery or invitation link, a canonical or share address, and an identity document's issuer or discovery value.
A rate limiter or an allowlist that reads a client-supplied source field makes its decision on an observation the caller authored, which is the same trust at an accounting or permit step.
Where the response reflects nothing, prove the origin resolved the supplied value with an out-of-band fetch of the supplied host, because a blind case carries no reflection to read.

## Spraying and Rewrite Position

Send the same value under each family the path might read, because every layer may key on a different spelling of one meaning.
Keep the value identical across families, so the field is the only changed variable.
Probe the rewrite position relative to the decision, because a rewrite applied after the decision carries leverage and a rewrite applied before it carries none.
A reflected value that reached no decision is not trust, and an origin that reads its own observation across every family is a recorded negative.
