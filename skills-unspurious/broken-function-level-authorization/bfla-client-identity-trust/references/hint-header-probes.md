# Hint Header Probes

The identity-source variant decides which request input the service treats as the actor, and this reference holds the hint families and the one primitive that tests them.
Every probe keeps the credential, the route, and the body constant while only the hint varies, so a verdict attributes to the hint rather than to the credential.
The procedure completes when every hint input of every privileged action carries a supply, remove, and contradict attempt beside its unhinted control.

## The Triple Primitive

One primitive covers every hint class, because the question is always precedence rather than the value.

- **Supply**: send the hint the token never granted and read whether the verdict changes.
- **Remove**: send the same request without the hint and read whether the verdict returns.
- **Contradict**: send the hint against the token's own claim, so agreement between the two can never be mistaken for precedence.

An unhinted denial proves nothing on its own, because the hinted form may still resolve in the attacker's favor.

## Identity Hint Families

- **Identity headers**: the user, role, or scope headers an edge injects and a backend trusts as authoritative.
- **Cookie-carried flags**: a role, plan, or administrative marker carried in a cookie beside the session.
- **Request-parameter roles**: a role, account-type, or requester marker accepted in the body or the query.
- **Scope selectors**: tenant, organization, project, workspace, and account selectors that double as the actor.
- **Origin and network-address hints**: the forwarding-address family, including the standard header, its common misspellings, its private-address form, and the sibling address headers that record the same fact under another name; also the origin header where a gate reads it as provenance.

## Non-Identity Hint Gates

A gate keyed on a value that is not an identity claim decides the verdict the same way, so test it with the same triple.

- **Navigation provenance**: the referer value, which narrates where the caller came from rather than who the caller is.
- **Routing overrides**: the path-override headers and method-override framings an edge honors before the application sees the request; the route-shadowing delta belongs to `bfla-alternate-path`, so record only the identity verdict here.
- **Scope hints that route**: a selector that scopes a query without identifying the caller stays an aspect, and enters this variant only where it changes the privilege verdict.

## Precedence Recording

- Record which source won per attempt: token wins, hint wins, or the service refuses the contradiction outright.
- Test conflicting-hint pairs, because a service that honors one source over the other names the winning reader.
- Compare the same hinted request behind the gateway and direct to the service, because injection precedence differs at that boundary.
- Treat the winning source as the finding's attribution: claim-wins cases stay separate from hint-wins cases.

## Read-outs

- Access changes on a hint change alone, with the credential constant.
- A privileged effect under a hinted lower-role token beside denial without the hint.
- A gate that opens on a provenance, origin, or routing change alone.
- A before-and-after state snapshot showing the privileged change completes the proof.

## Delegation

- Parser and encoding mechanics behind a hint shape are owned by the `defence-bypass` family.
- The route-shadowing delta of a routing override is owned by `bfla-alternate-path`.
- Principal handling and the control pair are owned by `two-principal-authz`.
- The proxy hop that injects or forwards a hint is named at the step owned by `proxy-techniques-relay-forwarding`.

## False Positives

- A hint echoed in the response is not a hint honored; only a verdict change counts.
- A routing selector that scopes without identifying the caller carries no privilege gain.
- A denial that flips only when the credential changes attributes to the token, not to the hint.
- A gate that opens for a private-address value while the request is genuinely internal carries no trust failure.
