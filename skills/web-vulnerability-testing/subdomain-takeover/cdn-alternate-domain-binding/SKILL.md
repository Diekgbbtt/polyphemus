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

- **Applicability**: a trusted name is accepted as an alternate domain on edge capacity the tester controls.
- **Verification gap**: the edge platform skips ownership verification before accepting the alternate-name association.
- **Serving factors**: edge routing plus certificate handling plus cache keys decide whether the binding serves attacker content.
- **Variation**: the binding varies only in which edge verification gap permits the association and which cache proof confirms it.

## Reconnaissance

- **Candidate inventory**: inventory candidate names from transparency logs plus passive resolution history plus asset records plus infrastructure outputs.
- **Candidate record**: record each candidate with its source and keep every alias chain collapsed to its terminal edge endpoint.
- **Edge probing**: probe each candidate edge endpoint for status plus body plus error text plus server headers plus certificate names.
- **Differential contrast**: contrast edge answers across neighboring paths and hosts to record partial-configuration differentials.
- **Survey completion**: complete the survey when every candidate carries a recorded edge triple and a recorded differential verdict.

## Detection Channels

- **Channel scope**: the binding listens to edge-configuration evidence.
- **Edge differential**: separates partial alternate-name configuration from full refusal across status codes.
- **Certificate name**: shows a platform default or attacker-managed issuance instead of the victim binding.
- **Cache-key persistence**: shows attacker content surviving under the trusted name.
- **Served proof content**: returns the unique claim token through the edge route.

## Adversarial Capabilities

- **Prerequisites**: the binding presupposes distribution operation plus alternate-name association plus certificate handling, and it consumes all three.
- **Distribution operation**: operate an edge distribution account that can declare alternate names.
- **Alternate-name association**: associate the victim name as an alternate domain on the attacker distribution.
- **Certificate supply**: supply certificate material through upload or managed issuance for the bound name.
- **Signal observation**: observe edge differentials plus cache-key behavior plus certificate readiness across attempts.
- **Authorization boundary**: hold authorization to attempt the association and stop at an ownership-check refusal.

## Trust Assumptions

- **The agreement**: when the subdomain feature executes, DNS is trusted to point only at owned resources and the platform is trusted to bind a name only to its owning account and delegations are trusted to stay live under owner control and alternate names are trusted to stay bound to their owning distribution, and sensitive content and session trust leak only through a name that still resolves to attacker-controlled content.
- **The failing clause**: the agreement fails at the alternate-name binding clause because the edge accepts the victim name on the attacker distribution without ownership proof.

## Key Vulnerabilities

- **Alternate-name addition**: attacker-distribution alternate-name addition is the bent step the parent creation phrase cannot describe.
- **Association step**: add the victim subdomain as an alternate name on the attacker distribution where verification is absent.
- **Certificate handling**: complete certificate handling through upload or managed issuance so the bound name serves over a secure channel.
- **Proof shape**: hold the proof shape abstract as edge-routed content carrying <proof-token> with cache-key scope.
- **Variant delta**: the delta over the parent is alternate-name addition plus certificate handling with edge-differential fingerprinting and cache-aware proof.

## Advanced Techniques

- **Proof anchoring**: anchor proof on edge routing rather than origin state because the edge decides what the trusted name serves.
- **Differential reading**: read partial-configuration differentials as binding signal because split status answers reveal incomplete association.
- **Cache-key scope**: treat cache keys as proof scope because poisoned entries persist attacker content under the trusted name.
- **Control confirmation**: confirm control only through the trusted name returning <proof-token> through the edge route with matching certificate names.
- **Issuance monitoring**: monitor transparency logs for unexpected issuance on tested names during the proof window.

## Bypass Techniques

- **Bypass scope**: read each ownership control as binding input and proceed only where the control permits.
- **Prior-binding acceptance**: treat prior-binding acceptance as the signal that an alternate name binds before challenge verification completes.
- **Ownership-check refusal**: treat ownership-check refusal as a stop condition that marks the binding unclaimable.
- **Fallback-origin exposure**: treat fallback-origin exposure as the signal that unknown-domain answers still route through shared edge capacity.
- **Issuance restriction**: treat issuance restriction as a guardrail that limits certificate issuance while the binding is triaged.
- **Extended reading**: when this section does not fulfil the knowledge gap, extend the reading with the defence-bypass and proxy-techniques families.

## Chaining Attacks

- **Chain scope**: carry proven edge control into trust-policy impact owned by consumer checks.
- **Redirect and callback abuse**: carry trusted-edge content into allowlisted redirect and callback abuse.
- **Policy and script-source abuse**: carry trusted-edge scripts into policy and script-source trust abuse.
- **Cache persistence**: carry trusted-edge responses into cache persistence under the victim name.
- **Companion-skill reference**: name the request-forgery companion at the fetch step rather than restating its procedure here.

## Testing Methodology

Bind runs enumeration plus edge probing plus differential fingerprinting plus authorized association plus cache-aware proof in order.
1. **Enumerate candidates** - aggregate transparency plus passive plus inventory sources with one source recorded per name, and the step completes when every candidate name carries its source.
2. **Probe the edge** - capture status plus body plus error text plus headers plus certificate names per candidate, and the step completes when every candidate carries a recorded edge triple.
3. **Fingerprint differentials** - contrast partial-configuration answers against refusal answers across status families, and the step completes when every candidate carries a differential verdict.
4. **Bent step: attempt authorized alternate-name association** - add the victim name as an alternate domain on the attacker distribution with certificate handling, and the step completes when every bindable candidate shows association success and every refused candidate shows a recorded ownership-check refusal.
5. **Validate edge control** - serve content carrying <proof-token> and fetch it from the trusted name through the edge route with cache-key observation, and the step completes when every bound name returns its unique token with matching certificate scope.

## False Positives

- **Stop condition**: stop when the evidence shows an unbindable or owned association.
- **Guarded unknown-domain pages**: unknown-domain pages guarded by enforced alternate-name ownership checks.
- **Owned platform default pages**: platform default pages served from a valid owned distribution.
- **Owned edge catch-all answers**: catch-all virtual hosts and soft not-found answers from owned edge capacity.
- **Routing-variance differentials**: edge differentials caused by routing variance rather than partial alternate-name configuration.

## Pro Tips

- **Discipline**: the binding rewards differential reading plus quiet proofs plus clean teardown.
- **Neighbor comparison**: compare edge answers across neighboring hosts before judging a partial-configuration signal.
- **Minimal proof page**: prefer a minimal static proof page carrying <proof-token> for every binding.
- **State recording**: record alternate-name state plus certificate state plus cache-key behavior per attempt.
- **Clean teardown**: remove the alternate-name association and release certificate material immediately after proof completes.
- **Ownership refusal**: treat any enforced ownership refusal as a stop condition rather than a retry target.

## Summary

An edge that accepts alternate names without ownership proof yields the trusted name to attacker distribution binding.
Bind the victim name through alternate-name association and prove control with edge-routed unique content under cache observation.
