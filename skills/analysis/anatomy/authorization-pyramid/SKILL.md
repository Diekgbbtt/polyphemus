---
name: authorization-pyramid
description: Use when an anatomy skill must reverse-engineer a service's role to permission structure by probing the same action under different roles.
---

# Authorization-pyramid anatomy skill

You reverse-engineer a Service's authorization structure and write it as typed
edges. You are a system-anatomy skill (spec §7.6): your output is a
*classification*, its *evidence*, and *live probes*.

## The inverse-pyramid probe

Authorization can only be settled by INTERACTION, not inspection. Take one
service action (an endpoint + method that does something privileged - place an
order, issue a refund, read another user's data) and issue it **once per role**,
each time carrying THAT role's credentials:

- for each role, select its credential set (`select_auth_context`), attach it to
  an interface-agreement-B request against the same action target, and observe
  the outcome (allowed vs denied);
- probe the WHOLE role span - guest / unauthenticated, shopper, member, seller,
  support, admin - not just the one you expect to succeed. The security signal
  lives in the roles that succeed when they should not.

Each probe is a backward-recon request (`origin=anatomy_skill`,
`skill_id=authorization_pyramid`) carrying `scope.auth_context` per role; its
result routes back to you.

## Write the structure STRUCTURALLY (not prose)

From the per-role outcomes, write typed edges - the reason role edges are typed
at all is that this skill must write them so downstream reasoning can traverse
them:

- every role that COULD perform the action -> an `AUTHORIZED_BY {role}` edge from
  the Service to the AuthorizationSystem;
- each authentication realm involved (credential vs IdP) -> an
  `AUTHENTICATED_BY {realm}` edge to the AuthenticationMechanism.

Keep the two separate (L1D-5): the AuthenticationMechanism / AuthorizationSystem
are the *mechanism* (Systems); the `role` / `realm` on the edges are the *policy*.

## Classification + evidence

Set the `authz_model` spine slot from the probed role set: `locked` (no role
could), `unrestricted` (every probed role could), or `role-restricted` (some
gated). Record the authorised-vs-denied role set verbatim as an `Observation`.

Record who CAN act - the STRUCTURE. Whether a given role *should* be able to
(a privilege violation) is downstream Stage-3 reasoning, not yours to decide here.
