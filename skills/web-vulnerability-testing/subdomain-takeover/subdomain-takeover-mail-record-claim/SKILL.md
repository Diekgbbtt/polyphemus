---
name: subdomain-takeover-mail-record-claim
description: Claim a dangling host that a mail-authorisation or mail-service record still names, then publish the authorising records or enable receipt so the trusted name sends or receives mail under attacker control.
metadata:
  version: 1.0.0
---

# Mail Record Claim

A mail-authorisation record names a host whose published policy decides which infrastructure may send mail for the parent domain, and a mail-service record names the host that receives it.
When such a record outlives the binding that owned it, the host is claimable through the ordinary dangling-record flow, and the claim carries the mail role rather than a web content role.
This variant owns the post-claim step the web-content claim cannot describe: publish the authorising records for the claimed host, or enable receipt on it, and confirm the parent domain's mail either passes authentication or arrives at the attacker mailbox.

## Attack Surface

- **Applicability**: centers on a mail-authorisation or mail-service record that points at an external host the owner no longer controls, on the parent domain's published policy, and on the provider path that can re-issue the exact host.
- **Record families**: key-selector records under a signing label, sender-policy include hosts, mail-service host records, and support or help-desk host mappings the parent domain's mail still references.
- **Policy state**: which authorising records the parent domain publishes, and what each one authorises, because a claim over an unauthorised host proves nothing.
- **Shared claim mechanics**: the claim itself runs through this class's dangling-record, alternate-domain, or delegation procedure; only the post-claim mail step is this variant's own.
- **Out-of-scope effect**: serving web content from the claimed host is the sibling variants' completion; this variant completes on the mail role.

## Reconnaissance

- **Record-family enumeration**: enumerate the parent domain's mail records as their own pass, covering selector records under a signing label, sender-policy includes, mail-service hosts, and support host mappings.
- **Resolution and fingerprinting**: resolve each record to its terminal external endpoint and record the provider family, because the claim path and the unclaimed signature differ per family.
- **Policy-state reading**: record the parent domain's published authorising policy and the alignment it enforces, because the post-claim step must name the record the claim can satisfy.
- **Probe pass**: probe each candidate host for status, body, error text, and certificate subject, and record the unclaimed-resource verdict per candidate.
- **Sending baseline**: confirm the parent domain's current sending posture with a baseline message, so a later pass is attributable to the published records rather than to a pre-existing gap.

## Detection Channels

- **Unclaimed-resource response**: a provider unclaimed-resource response for a mail-record host, which is the claimable signal for this variant.
- **Provider-default certificate**: a certificate naming the provider default rather than the mail-record host, which corroborates an external binding.
- **Stale policy host**: the parent domain's published policy names a host that no longer resolves to an owned resource.
- **Send-authority verdict**: a message that passes the parent domain's authorisation checks after the claimed host publishes its records, which proves send authority.
- **Receipt delivery**: a message addressed to the trusted name arriving at the claimed host, which proves receipt.
- **Unique proof marker**: the claimed host serves a unique proof marker, which separates control from a provider default page.

## Adversarial Capabilities

- **Provider account**: operate an account on the provider a mail record points at, able to create the exact required host.
- **Record publication**: publish records for the claimed host where the provider path allows it.
- **Receipt configuration**: hold a mailbox or forwarding configuration on the claimed host to receive messages addressed to the trusted name.
- **Send-and-read ability**: send and read mail from the parent domain's perspective, so the authentication verdict on a delivered message is observable.
- **Scope and revert discipline**: confirm scope before any claim step, and revert the claim and its records after the proof completes.

## Trust Assumptions

- **The agreement**: every mail-authorisation record points at a host the owner controls, so the published policy authorises only the owner's sending infrastructure, and every mail-service record points at a host that receives the name's mail under owner control, and the parent domain's own policy trusts the records published under the claimed host, so the claim inherits send authority rather than only the name, and the parent domain's mail routing trusts the record's destination, so the claim inherits delivery for the trusted name.
- **The failing clause**: the record outlives its host binding, so a claimed host can publish authorising records the parent domain's policy then honours, or receive the messages the parent domain's mail service routes to it.

## Key Vulnerabilities

### Authorisation-Record Claim

- **Selector-record claim**: re-claim the host a key-selector record names, then publish a signing key under that selector, so messages the attacker sends pass the parent domain's signature check.
- **Include-host claim**: re-claim a host a sender-policy include names, then publish the sending policy there, so the attacker's sending infrastructure is authorised for the parent domain.
- **Policy publication**: the post-claim step is publishing the authorising records, not serving content; the claim proves on the parent domain's own authentication verdict for a delivered message.
- **Alignment reach**: where the parent domain enforces alignment, the claim satisfies the alignment clause the same way the owner's own infrastructure does.

### Mail-Service and Receipt Claim

- **Mail-service host claim**: re-claim the host a mail-service record names, so messages addressed to the trusted name route to infrastructure the attacker controls.
- **Receipt configuration**: enable forwarding or a mailbox on the claimed host and confirm a message addressed to the trusted name arrives, which is the receipt completion.
- **Support-host mapping**: a help-desk or support host mapping that still references the parent domain routes ticket traffic and recovery mail into the claimed host.
- **Aspect boundary**: receipt rides as a value of this variant's post-claim step, because both completions exercise the mail role the claimed name carries rather than a web content role.

### Shared Claim Preconditions

- **Exact-name creation**: the claim runs through the binding flow that owns the terminal endpoint, exactly as the sibling variants describe.
- **Verification gaps**: a provider path that accepts the host before ownership verification completes shortens the claim.
- **Race window**: the window between host release and re-verification decides whether the exact name is still re-issuable.

## Advanced Techniques

- **Policy-first reading**: read the parent domain's published policy before claiming, because a claim over a host the policy does not name authorises nothing.
- **Selector breadth**: several selector records may exist beside the primary one; each is a separate claim candidate with its own key material.
- **Wildcard includes**: a wildcard in a sender-policy include widens the claimable set to any matching host.
- **Receipt-first proof**: where publication is blocked, receipt still proves the mail role, so take the narrower completion when it holds.
- **Window bracketing**: monitor the host for release and claim inside the re-verification window, because a released mail host is commonly re-issued first-come.
- **Revert discipline**: remove the published records and the claimed resource immediately after the proof, because a standing authorising record is a live capability.

## Bypass Techniques

- **Verification gaps**: binding flows that accept the host before ownership verification completes, and stale bindings that skip re-verification after the resource is deleted.
- **Provider record paths**: provider paths that publish records for a claimed host without an out-of-band ownership proof.
- **Receipt without proof**: provider paths that enable forwarding or a mailbox on a claimed host with no domain-ownership check.
- **Record-type independence**: one record family may stay verified while another stays claimable; probe each family separately.
- **Race windows**: re-claim the exact host inside the window between release and re-verification.
- **Extended reading**: when this section does not fulfil the knowledge gap, extend the reading with the defence-bypass and proxy-techniques families.

## Chaining Attacks

- **Send authority plus phishing trust**: messages that pass the parent domain's authorisation checks carry the brand through recipient-side filters.
- **Receipt plus recovery interception**: messages addressed to the trusted name carry recovery artifacts, and `account-recovery` owns the artifact-consumption step.
- **Receipt plus support traffic**: ticket and notification traffic routed to the claimed host exposes content the application never exposed to a claimant.
- **Claim plus web content**: the same claimed host can also serve content, so the mail claim composes with the sibling variants' completion.
- **Claim plus certificate issuance**: issuance for the claimed host produces verifiable proof over a secure channel.

## Testing Methodology

Claim runs mail-record enumeration plus resolution plus fingerprinting plus authorized creation plus the post-claim mail step in order.

1. **Enumerate mail records** - collect selector records, sender-policy includes, mail-service hosts, and support host mappings for the parent domain, and the step completes when every record family carries its candidate set.
2. **Resolve and fingerprint** - record each candidate's record chain, terminal endpoint, provider family, and unclaimed verdict, and the step completes when every candidate carries a claimability verdict.
3. **Read the published policy** - record the parent domain's authorising records and the alignment it enforces, and the step completes when the policy state is recorded with the records a claim could satisfy.
4. **Bent step: attempt authorized exact-name claim** - create the missing host through the binding flow that owns its terminal endpoint, and the step completes when the claim shows creation success and control is confirmed by a unique proof served from the claimed host.
5. **Publish the authorising records** - publish the selector or sending-policy records under the claimed host, then read the parent domain's authentication verdict on a delivered message, and the step completes when the verdict is recorded for the parent domain rather than for the attacker domain.
6. **Confirm the receipt value where chosen** - enable forwarding or a mailbox on the claimed host and send a message addressed to the trusted name, and the step completes when the message arrives at the claimed host and no other completion is claimed in its place.
7. **Record and revert** - record the full claim chain and remove the published records and the claimed resource, and the step completes when the mail role no longer resolves to the claimed host.

## False Positives

- **Enforced verification**: an unclaimed host whose provider enforces ownership verification before binding, confirmed by a refused claim.
- **Live owned resource**: a record that points at a live, owned resource, confirmed by a certificate and content that match the owner.
- **Live-resource default**: a provider default response served from a live resource rather than an unclaimed binding.
- **No authorising records**: a parent domain that publishes no authorising records, so a claim over the host authorises nothing.
- **Pre-existing permissive policy**: a message that arrives without the claim, because the parent domain's policy was already permissive.
- **Unrelated refusal**: a delivery refused at the receiving side for an unrelated reason, which is not evidence about the claim.

## Pro Tips

- **Separate mail pass**: enumerate the mail records as their own pass; the web-facing enumeration misses selector and include hosts.
- **Policy-first reading**: read the parent domain's published policy before claiming, because the post-claim proof depends on it.
- **Publication as proof**: the post-claim publication is the proof for send authority; a claimed host alone proves nothing about mail.
- **Narrower completion**: take the receipt completion where publication is blocked, and keep the two completions apart in the report.
- **Immediate revert**: record the claim chain and revert everything immediately, because a standing authorising record is a live capability.
- **Lifecycle discipline**: treat the mail surface as a lifecycle problem: remove or re-verify the record at decommission time, on every record family.

## Summary

A mail record that outlives its host binding hands the parent domain's mail role to whoever claims the host.
Claim the exact host, publish the authorising records or enable receipt, and prove the effect on the parent domain's own mail rather than on the attacker's.
