---
name: cdn-alternate-domain-binding
description: Bind a victim name as an alternate domain on attacker edge capacity. Use when edge responses show partial-configuration differentials, when a name is unbound on shared edge infrastructure, when cache-key persistence decides proof shape.
metadata:
  version: 1.0.0
---

# Cdn Alternate Domain Binding

Bind the trusted name as an alternate domain on attacker-controlled edge capacity.
This variant adds the victim name to an attacker distribution and proves control through edge routing plus certificate plus cache-key behavior.
The impact goal is trusted-origin content serving with phishing plus session plus cache persistence.

## Attack Surface

Bind applies where a trusted name is accepted as an alternate domain on edge capacity the tester controls.
Bind applies where the edge platform skips ownership verification before accepting the alternate-name association.
Bind applies where edge routing plus certificate handling plus cache keys decide whether the binding serves attacker content.
Bind varies only in which edge verification gap permits the association and which cache proof confirms it.

## Reconnaissance

Inventory candidate names from transparency logs plus passive resolution history plus asset records plus infrastructure outputs.
Record each candidate with its source and keep every alias chain collapsed to its terminal edge endpoint.
Probe each candidate edge endpoint for status plus body plus error text plus server headers plus certificate names.
Contrast edge answers across neighboring paths and hosts to record partial-configuration differentials.
Complete the survey when every candidate carries a recorded edge triple and a recorded differential verdict.

## Detection Channels

Bind listens to edge-configuration evidence, so only the entries below are live here.
- Edge differential separating partial alternate-name configuration from full refusal across status codes.
- Certificate name showing a platform default or attacker-managed issuance instead of the victim binding.
- Cache-key persistence showing attacker content surviving under the trusted name.
- Served proof content returning the unique claim token through the edge route.

## Adversarial Capabilities

Bind presupposes distribution operation plus alternate-name association plus certificate handling, and it consumes all three.
- Operate an edge distribution account that can declare alternate names.
- Associate the victim name as an alternate domain on the attacker distribution.
- Supply certificate material through upload or managed issuance for the bound name.
- Observe edge differentials plus cache-key behavior plus certificate readiness across attempts.
- Hold authorization to attempt the association and stop at an ownership-check refusal.

## Trust Assumptions

When the subdomain feature executes, DNS is trusted to point only at owned resources and the platform is trusted to bind a name only to its owning account and delegations are trusted to stay live under owner control and alternate names are trusted to stay bound to their owning distribution.
Sensitive content and session trust leak only through a name that still resolves to attacker-controlled content.
That trust fails at the alternate-name binding clause because the edge accepts the victim name on the attacker distribution without ownership proof.

## Key Vulnerabilities

Attacker-distribution alternate-name addition is the bent step the parent creation phrase cannot describe.
Add the victim subdomain as an alternate name on the attacker distribution where verification is absent.
Complete certificate handling through upload or managed issuance so the bound name serves over a secure channel.
Hold the proof shape abstract as edge-routed content carrying <proof-token> with cache-key scope.
The delta over the parent is alternate-name addition plus certificate handling with edge-differential fingerprinting and cache-aware proof.

## Advanced Techniques

Anchor proof on edge routing rather than origin state because the edge decides what the trusted name serves.
Read partial-configuration differentials as binding signal because split status answers reveal incomplete association.
Treat cache keys as proof scope because poisoned entries persist attacker content under the trusted name.
Confirm control only through the trusted name returning <proof-token> through the edge route with matching certificate names.
Monitor transparency logs for unexpected issuance on tested names during the proof window.

## Bypass Techniques

Read each ownership control as binding input and proceed only where the control permits.
- Treat prior-binding acceptance as the signal that an alternate name binds before challenge verification completes.
- Treat ownership-check refusal as a stop condition that marks the binding unclaimable.
- Treat fallback-origin exposure as the signal that unknown-domain answers still route through shared edge capacity.
- Treat issuance restriction as a guardrail that limits certificate issuance while the binding is triaged.

## Chaining Attacks

Carry proven edge control into trust-policy impact owned by consumer checks.
- Carry trusted-edge content into allowlisted redirect and callback abuse.
- Carry trusted-edge scripts into policy and script-source trust abuse.
- Carry trusted-edge responses into cache persistence under the victim name.
- Name the request-forgery companion at the fetch step rather than restating its procedure here.

## Testing Methodology

Bind runs enumeration plus edge probing plus differential fingerprinting plus authorized association plus cache-aware proof in order.
1. **Enumerate candidates** - aggregate transparency plus passive plus inventory sources with one source recorded per name, and the step completes when every candidate name carries its source.
2. **Probe the edge** - capture status plus body plus error text plus headers plus certificate names per candidate, and the step completes when every candidate carries a recorded edge triple.
3. **Fingerprint differentials** - contrast partial-configuration answers against refusal answers across status families, and the step completes when every candidate carries a differential verdict.
4. **Bent step: attempt authorized alternate-name association** - add the victim name as an alternate domain on the attacker distribution with certificate handling, and the step completes when every bindable candidate shows association success and every refused candidate shows a recorded ownership-check refusal.
5. **Validate edge control** - serve content carrying <proof-token> and fetch it from the trusted name through the edge route with cache-key observation, and the step completes when every bound name returns its unique token with matching certificate scope.

## False Positives

Stop when the evidence shows an unbindable or owned association.
- Unknown-domain pages guarded by enforced alternate-name ownership checks.
- Platform default pages served from a valid owned distribution.
- Catch-all virtual hosts and soft not-found answers from owned edge capacity.
- Edge differentials caused by routing variance rather than partial alternate-name configuration.

## Pro Tips

Bind rewards differential reading plus quiet proofs plus clean teardown.
1. Compare edge answers across neighboring hosts before judging a partial-configuration signal.
2. Prefer a minimal static proof page carrying <proof-token> for every binding.
3. Record alternate-name state plus certificate state plus cache-key behavior per attempt.
4. Remove the alternate-name association and release certificate material immediately after proof completes.
5. Treat any enforced ownership refusal as a stop condition rather than a retry target.

## Summary

An edge that accepts alternate names without ownership proof yields the trusted name to attacker distribution binding.
Bind the victim name through alternate-name association and prove control with edge-routed unique content under cache observation.
