# Read-Only Credential Validators

This note details the validator discipline the parent's liveness step summarises.
A validator proves a candidate live and reads the scope it grants; it never changes state.
The issuer endpoints and the exact response shapes are runtime knowledge-base facts.

## The validator shape

Four parts, in order.
1. An identity read: the read-only endpoint that answers with the principal behind the credential.
2. A verdict mapping: accepted, rejected, accepted-but-restricted, or transient failure.
3. A scope read: the grant list the response carries, or a permissions read beside the identity read.
4. A detectability tag: whether the read lands where the owner can see it.

Stop after the scope read, because everything beyond it is use rather than validation.

## Identity reads by issuer family

- Cloud infrastructure: an identity read at the control API returning the account, the principal, and its type; a user principal is broad, an assumed role is narrow, and account-root material is never validated.
- Source hosting: a principal read plus the scope list the response carries, which names repository, organisation, and workflow grants.
- Package registry: a principal read plus a token-permission read naming read, publish, or administration scope.
- Messaging platform: an authentication-test read returning the workspace and the identity the token acts as.
- Mail and notification service: a key-metadata or domain read; a post-only grant caps the impact at message delivery.
- Observability platform: a validation read that answers accepted or rejected, frequently needing a second key beside the first.
- AI model provider: a model-list read for liveness, plus a usage read where the grant is organisation-scoped.
- Payment processor: an account or balance read; never a charge, a transfer, or a customer read.
- Unknown issuer: infer the consuming service from the leak context, read the issuer's published validator, then validate; never submit the credential to a third-party validation service, because that discloses it to a fourth party.

## Detectability cost

- Low: the read writes no state and appears in no owner-visible trail.
- Medium: the read lands in an owner-visible audit trail, so the owner sees the access even when nothing changes.
- High: the read notifies a human, trips monitoring, or resets a counter the owner watches.

Prefer the quietest validator that still answers, and record the tag with the verdict.

## The output record

```json
{
  "status": "verified_live | verified_dead | scope_restricted | scope_unrestricted | validation_skipped_by_policy | validation_unsupported | validation_failed_transient",
  "issuer_family": "<family>",
  "account_reference": "<opaque>",
  "scope": "<freeform>",
  "metadata": {},
  "checked_at": "<UTC ISO8601>",
  "detectability": "low | medium | high"
}
```

## Hard rules

- Read-only endpoint only.
- Never create, modify, delete, or send with a validated credential.
- Tag every validation with its detectability and its UTC timestamp.
- When the rules of engagement forbid validation, record `validation_skipped_by_policy`, stop, and document the decision.
- Escalate broad or irreversible grants to the operator instead of validating: account-root material, infrastructure-write grants, organisation-administration grants, and any credential whose use notifies a human.
- A credential that answers nowhere is `verified_dead`; a credential that answers with a restriction is `scope_restricted`, which is a finding with a smaller blast radius rather than a negative.
