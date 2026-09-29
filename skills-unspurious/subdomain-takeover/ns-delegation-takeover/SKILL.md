---
name: ns-delegation-takeover
description: Seize orphaned delegations through expired nameserver control. Use when a child zone delegates to lifeless nameservers, when nameserver domains show expiry signals, when subzone-wide control decides proof scope.
metadata:
  version: 1.0.0
---

# Ns Delegation Takeover

Seize a child zone whose delegation points at expired or lifeless nameservers.
This variant registers the expired nameserver domain plus hosts authoritative answers plus publishes records for the delegated subzone.
The impact goal is full subzone control with trusted-origin serving plus session plus trust-policy pivot across all hosts below the label.

## Attack Surface

Delegate applies where a child zone is delegated to nameservers no owner still operates.
Delegate applies where the nameserver domain has expired or no longer hosts authoritative answers.
Delegate applies where control of the delegated label decides every host below it.
Delegate varies only in which nameserver domain is expirable and which subzone records prove control.

## Reconnaissance

Inventory candidate names from transparency logs plus passive resolution history plus asset records plus infrastructure outputs.
Record each candidate with its source and keep every delegation chain traced from parent to child zone.
Trace each child-zone delegation to its nameserver domain and check expiry plus liveness signals.
Probe authoritative answers for delegation responsiveness plus record correctness plus subzone coverage.
Complete the survey when every delegated label carries a recorded nameserver chain with expiry and liveness verdicts.

## Detection Channels

Delegate listens to delegation-liveness evidence, so only the entries below are live here.
- Delegation trace showing a child zone cut to nameservers outside owner control.
- Nameserver-domain expiry signal showing the domain is released or awaiting release.
- Authoritative liveness gap showing no working answers from the delegated servers.
- Subzone-wide proof showing published records resolving across hosts below the label.

## Adversarial Capabilities

Delegate presupposes domain registration plus authoritative hosting plus zone publishing, and it consumes all three.
- Register the expired nameserver domain through a standard registrar flow.
- Host authoritative nameservers that answer for the delegated label.
- Publish records that control hosts across the delegated subzone.
- Observe expiry timing plus liveness gaps plus propagation across resolvers.
- Hold authorization to attempt the registration and stop at a live-delegation finding.

## Trust Assumptions

When the subdomain feature executes, DNS is trusted to point only at owned resources and the platform is trusted to bind a name only to its owning account and delegations are trusted to stay live under owner control and alternate names are trusted to stay bound to their owning distribution.
Sensitive content and session trust leak only through a name that still resolves to attacker-controlled content.
That trust fails at the delegation-liveness clause because the child zone still delegates to expired nameservers that accept outside registration and authoritative hosting.

## Key Vulnerabilities

Expired-domain registration with authoritative hosting is the bent step the parent creation phrase cannot describe.
Register the expired nameserver domain that the delegation still names.
Host authoritative servers and publish records that answer for every host below the delegated label.
Hold the proof shape abstract as subzone records resolving to content carrying <proof-token>.
The delta over the parent is delegation tracing plus expiry and liveness checks with registration plus authoritative hosting and subzone-wide proof.

## Advanced Techniques

Anchor proof on subzone breadth rather than one hostname because delegation control covers the whole label.
Treat child-zone cuts as authority boundaries because delegated answers outrank parent records.
Treat propagation delay as confirmation input because resolver caches converge on the new authoritative answers over time.
Confirm control only through multiple hosts below the label resolving to published records with <proof-token> evidence.
Monitor transparency logs for unexpected issuance on subzone names during the proof window.

## Bypass Techniques

Read each delegation control as seizure input and proceed only where the control permits.
- Treat missing registry lock or expiry as the signal that the nameserver domain is registrable.
- Treat lifeless authoritative answers as the signal that no owner still serves the delegation.
- Treat issuance restriction as a guardrail that limits certificate issuance while the delegation is triaged.
- Treat a live authoritative answer from the owner as a stop condition that marks the delegation unclaimable.

## Chaining Attacks

Carry proven subzone control into trust-policy impact owned by consumer checks.
- Carry subzone content into allowlisted redirect and callback abuse across delegated hosts.
- Carry subzone scripts into policy and script-source trust abuse.
- Carry subzone responses into scoped-cookie and cross-origin pivot below the label.
- Name the request-forgery companion at the fetch step rather than restating its procedure here.

## Testing Methodology

Delegate runs enumeration plus delegation tracing plus liveness checking plus authorized registration plus subzone-wide proof in order.
1. **Enumerate candidates** - aggregate transparency plus passive plus inventory sources with one source recorded per name, and the step completes when every candidate name carries its source.
2. **Bent step: trace delegations and check liveness** - trace each child-zone cut to its nameserver domain and record expiry plus authoritative responsiveness, and the step completes when every delegated label carries a nameserver chain with an expiry verdict and a liveness verdict.
3. **Probe subzone answers** - capture resolver plus status plus body plus certificate evidence per host below candidate labels, and the step completes when every host carries a recorded answer triple.
4. **Attempt authorized seizure** - register the expired nameserver domain plus host authoritative answers plus publish subzone records, and the step completes when every orphaned label shows authoritative control and every live label shows a recorded stop.
5. **Validate subzone control** - serve content carrying <proof-token> and resolve it across multiple hosts below the label, and the step completes when every tested host below the seized label returns its unique token.

## False Positives

Stop when the evidence shows a live or guarded delegation.
- Delegations whose nameservers still answer authoritatively for the child zone.
- Nameserver domains that remain registered and unexpirable by outside parties.
- Resolver failures caused by transient outage rather than orphaned delegation.
- Catch-all answers from parent infrastructure that mimic subzone control.

## Pro Tips

Delegate rewards careful tracing plus broad proof plus clean teardown.
1. Trace the full parent-to-child delegation chain before judging any expiry signal.
2. Prefer a minimal static proof page carrying <proof-token> served across several subzone hosts.
3. Record expiry state plus authoritative answers plus propagation per attempt.
4. Release the registered domain and remove authoritative hosting immediately after proof completes.
5. Treat any live authoritative answer from the owner as critical stop evidence.

## Summary

A delegation that points at expired nameservers yields its whole subzone to whoever registers and serves them.
Trace the delegation plus confirm expiry and lifelessness plus publish authoritative records and prove control across hosts below the label.
