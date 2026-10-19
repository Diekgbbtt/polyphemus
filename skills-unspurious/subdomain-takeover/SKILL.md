---
name: subdomain-takeover
description: Subdomain takeover testing for dangling DNS records and unclaimed cloud resources
metadata:
  version: 1.0.0
---

# Subdomain Takeover

Subdomain takeover lets an attacker serve content from a trusted name the owner no longer controls, by claiming the resource a dangling record still points at, by binding the name on edge infrastructure that does not verify ownership, or by seizing an orphaned delegation. Consequences run through every consumer that trusts the name: redirected credentials, session carriage, script inclusion, and cache persistence. Claim nothing before scope is confirmed.

## Attack Surface

**Binding Types**
- Dangling records (alias, address, or canonical forms) that resolve to a decommissioned or unclaimed external endpoint
- Orphaned delegations: a child zone delegated to nameservers whose domain has expired or no longer serves
- Alternate-domain mappings on edge infrastructure that serve a name without proof of ownership
- Decommissioned integration bindings (support, documentation, forms, marketing) still referenced by a record
- Mail bindings pointing at a decommissioned provider: selector, sender-policy, and mail-service records name a mail surface of their own beside the web-facing records

**Trust Consumers**
- Cookie scopes, origin checks, redirect allowlists, script-source policies, and certificate issuance all place trust in the name itself

## Reconnaissance

### Enumeration Pipeline

- Name inventory: certificate-transparency logs, passive DNS sources, in-house asset lists, and infrastructure-as-code outputs
- Zone transfer where a nameserver still allows it, which returns the whole zone in one read and exposes dangling records an external enumeration would miss
- Resolver sweep across every record type (address, canonical, delegation, mail, and verification), keeping canonical chains
- Track NXDOMAIN versus SERVFAIL versus provider-branded error codes to locate the failure at the record, resolver, or provider layer
- Build the record graph and collapse chains to their terminal external endpoint

### Dangling-Record Indicators

- A canonical target whose resource no longer exists or whose endpoint is unclaimed
- Verification artifacts in record text that suggest a previous external binding
- Mail records pointing at decommissioned providers
- Records kept after a decommission, where nothing removes or re-verifies the name
- External hosts the application itself loads from (script and resource origins): check each one's registration status and whether integrity pinning is absent, because an expired external host is a claimable dependency reached through the same claim mechanics, not a name of the target's own

### Delegation Indicators

- A child zone delegated to nameservers on a domain that has expired or no longer answers authoritatively
- Delegations that outrank parent records, so control of the delegated servers controls every label below

### Edge and Binding Indicators

- Provider unclaimed-resource responses: an unknown-name or missing-resource message carrying a provider signature
- Certificate subject mismatch: the presented certificate names the provider default rather than the requested name
- Edge differentials across status families for the same name, which show a partial alternate-domain configuration
- Binding flows that accept the name before ownership verification completes

## Detection Channels

- A provider unclaimed-resource response for the requested name, which is the classic claimable signal.
- A certificate naming the provider default rather than the requested name, which corroborates an external binding.
- NXDOMAIN versus SERVFAIL versus provider-branded error codes across resolvers, which locate the failure layer.
- The terminal external endpoint of a canonical chain, which decides which binding must be examined.
- Edge differentials across status families for one name, which show a partially configured alternate domain.
- A nameserver domain that fails expiry or liveness checks, which marks a delegation orphaned.
- A verification artifact in record text without a live binding, which signals a previous external mapping.
- A claim that succeeds and then serves attacker content for the name, which proves takeover.
- A certificate issued for the claimed name, which proves control over TLS-terminating clients.
- An authorization response or redirect that follows attacker-served content for the name, which proves a trust-chain effect.

## Adversarial Capabilities

Subdomain takeover testing presupposes a name inventory, record resolution, and an authorized claim path, and it consumes all three.
- Operate an account on the provider a record points at, able to create a resource with the exact required name.
- Register an expired nameserver domain and host authoritative servers for it.
- Add the target name as an alternate domain on attacker-held edge capacity.
- Resolve and probe the name over both plain and TLS channels, and read provider signatures.
- Serve a minimal unique proof page and confirm it through the name.
- Confirm scope before any claim step; claiming a name outside authorization is not a test.

## Trust Assumptions

The class rests on one agreement: every record points at a resource the owner still controls, and every binding path verifies ownership before the provider serves the name.
The agreement holds dangling records to live, owned endpoints, holds binding flows to verification before service, holds delegations to nameservers that stay owned and answer authoritatively, and holds alternate-domain mappings to proof of ownership.
Name control leaks when a clause fails: a record outlives its resource, a binding flow accepts a name before verification, a delegation points at a domain someone else can register, or edge capacity serves a name without proof.
Each variant breaks one clause: the dangling-record clause, the alternate-name clause, or the delegation clause.

## Key Vulnerabilities

### Dangling-Record Resource Claim

- Create the missing resource with the exact name the record resolves to, where the provider does not check that the requester owns the name
- Binding flows differ per resource type; some accept the name before verification completes, others after
- Resource variants of one provider (website endpoint versus API endpoint) differ in claimability and in their unclaimed signature
- Race windows: re-claim the exact name immediately after the owner deletes or releases it
- Wildcard records widen the set of claimable labels reachable under one endpoint

### Alternate-Domain Binding

- Add the target name as an alternate domain on attacker-held edge capacity where the provider does not verify ownership
- Certificate handling decides the effect: a certificate for the claimed name makes the takeover usable over TLS
- Cache keys on shared edge infrastructure decide proof shape and how long a response persists

### Delegation Takeover

- Where a child zone is delegated to nameservers on an expired domain, register that domain and host authoritative servers
- Publish records for the delegated subzone, which yields control of every label below the delegation
- Delegation outranks parent records, so the effect is subzone-wide rather than single-name

### Mail Surface

- Mail records pointing at a decommissioned provider name a mail surface of their own: a selector, sender-policy, or mail-service record whose post-claim step publishes authorising records or enables receipt rather than serving content
- The claim mechanics are the shared dangling-record ones; only the post-claim mail step differs, and it completes on the parent domain's own mail behaviour

### Trust Consumers

- Cookies, origin checks, redirect allowlists, and script-source policies turn control of the name into session or script effects
- Certificate issuance plus monitoring: control of the name with issuance reach yields verifiable evidence

## Advanced Techniques

**Edge and Blind Channels**

- Read edge differentials to detect partial configuration before attempting any claim
- After takeover, reason about cache keys and TTLs to know how long the proof persists on shared capacity

**Certificate Evidence**

- Use certificate transparency both as an enumeration source and as issuance evidence for the claimed name
- Where scope allows, issue a certificate for the claimed name to produce verifiable proof over TLS

**Verification Gaps**

- Prefer binding flows that accept the name before verification completes
- Watch deletion events for the race window on the exact name

**Scope Discipline**

- Confirm authorization before any claim step; the claim is the point where testing becomes takeover

## Bypass Techniques

**Verification Gaps**
- Binding flows that accept the name before verification completes
- Stale bindings that skip re-verification after the resource is deleted
- Alternative resource types of the same provider that keep different verification states

**Race Windows**
- Re-claim the exact name inside the window between deletion and re-verification

**Wildcards and Fallbacks**
- Wildcard records that expose unbounded labels under one endpoint
- Fallback and multi-origin edge configurations that expose an unknown-name response

**Record-Type Differences**
- One record type may remain claimable while another stays verified; probe each independently

When this section does not fulfil the knowledge gap, extend the reading with the defence-bypass and proxy-techniques families.

## Chaining Attacks

- Takeover plus redirect-allowlist trust: an authorization flow sends codes or credentials to attacker-served content, and a wildcard pattern in the allowlist turns any claimed host under it into a valid destination
- Takeover plus session scope: the name carries a victim's session to attacker content
- Takeover plus script-source trust: the name serves scripts into an origin that trusts it
- Takeover plus cross-origin read policy: a claimed host inside an origin allowlist reads credentialed responses from a page it serves
- Takeover plus edge caching: persist the response for other clients on shared capacity
- Takeover plus mail records: messages addressed to the name become receivable, where the provider path allows

## Testing Methodology

1. **Enumerate names** - Certificate transparency, passive DNS, asset lists, and infrastructure definitions
2. **Resolve records** - Every record type, keeping canonical chains and terminal endpoints
3. **Probe plain and TLS channels** - Status, body, error text, provider signatures, and certificate subjects
4. **Fingerprint the binding** - Map the record chain and response to a binding type and provider signature family
5. **Attempt the claim (authorized only)** - Create the exact-name resource, add the alternate domain, or register the expired domain
6. **Validate control** - Serve a minimal unique proof over the name, and over TLS where the client path uses it

## Variants

- dangling-record-resource-claim - Claim dangling names through exact-name resource creation, including binding flows, verification gaps, race windows, and unclaimed-signature proof.
- cdn-alternate-domain-binding - Bind a victim name as an alternate domain on attacker edge capacity, proven through edge differentials, certificate issuance, and cache-aware persistence.
- ns-delegation-takeover - Seize orphaned delegations through expired-domain registration and authoritative hosting, proven with subzone-wide control.
- email-dns-takeover - Claim a dangling mail-record host and publish authorising records or enable receipt, proven on the parent domain's own mail behaviour.

## False Positives

- Unknown-name pages that are not claimable because ownership verification is enforced before binding
- Provider-branded default responses for a live, owned resource
- Soft 404s and catch-all virtual hosts inside the owner's own infrastructure
- A certificate mismatch caused by a shared or default certificate rather than an external binding
- A delegation to nameservers that are alive but misconfigured by the owner
- A claim attempt blocked at the verification step, which is enforcement rather than takeover

## Pro Tips

1. Combine certificate transparency, passive DNS, and the asset inventory; any one source alone misses decommissioned assets
2. Maintain a fresh provider-signature corpus; provider messages change often
3. Prefer minimal proofs: a unique static page and, where scope allows, certificate issuance
4. Monitor certificate transparency for unexpected issuance on your names
5. Fix the lifecycle, not the record: remove or re-verify at decommission time, on every provider path
6. Treat any expired nameserver domain as critical; its delegation outranks everything below it
7. Check both plain and TLS clients: the effect depends on which channel trusts the name
8. Record the binding type behind each finding so the fix lands on the owning lifecycle step

## Summary

Name trust is lifecycle trust: whatever a record points at must be owned and verified on every provider path, at every record type, on the day anything changes. Remove or verify; there is no safe middle.
