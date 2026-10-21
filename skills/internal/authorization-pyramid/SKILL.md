---
name: authorization-pyramid
description: Use when an anatomy skill must reverse-engineer a service's role to permission structure by probing the same action under different roles.
metadata:
  version: '1.0'
---

# Authorization-pyramid anatomy skill

You reverse-engineer a Service's authorization structure and write it as typed
edges. You are a system-anatomy skill (spec §7.6): your output is a
*classification*, its *evidence*, and *live probes*.

## The inverse-pyramid probe

Settle authorization by INTERACTION, never inspection alone. Take one service
action (an endpoint + method carrying a privilege - place an order, issue a
refund, read another user's data) and issue it **once per role**, each time
with THAT role's credentials:

- per role, select its credential set (`select_auth_context`), attach it to an
  interface-agreement-B request against the same action target, and observe the
  outcome (allowed vs denied);
- cover the whole role span - guest / unauthenticated, shopper, member,
  seller, support, admin. The security signal lives in the roles that succeed
  where they should not.

Each probe is a backward-recon request (`origin=anatomy_skill`,
`skill_id=authorization_pyramid`) carrying `scope.auth_context` per role; its
result routes back to you.

## Write the structure STRUCTURALLY (not prose)

From the per-role outcomes, write typed edges:

- every role that COULD perform the action -> an `AUTHORIZED_BY {role}` edge from
  the Service to the AuthorizationSystem;
- each authentication realm involved (credential vs IdP) -> an
  `AUTHENTICATED_BY {realm}` edge to the AuthenticationMechanism.

Keep the two apart (L1D-5): the AuthenticationMechanism / AuthorizationSystem
are the *mechanism* (Systems); the `role` / `realm` on the edges is the
*policy*.

## Classification + evidence

Set the `authz_model` spine slot from the probed role set: `locked` (no role
could), `unrestricted` (every probed role could), `role-restricted` (gating
observed). Record the authorised-vs-denied role set verbatim as an `Observation`.

Record who CAN act - the STRUCTURE. Whether a role *should* hold that power
(a privilege violation) is downstream Stage-3 reasoning: state the structure
and stop there.
