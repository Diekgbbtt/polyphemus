---
name: header-host-forward-spoof
description: Spoofing Host-family headers to bend emitted links and access decisions, comparing Host against forwarding-alias precedence, and mapping each alias to its allowlist or scheme-check outcome.
metadata:
  version: 1.0.0
---

# Host and Forwarding Header Spoofing

Link builders and access checks both read Host-family headers as statements of truth about the request.
This variant proves that one forged Host-family value bends the emitted link and the access decision under controlled precedence plus per-alias mapping.
The spoofing goal is token-bearing links pointed at attacker infrastructure plus guarded endpoints opened by a forged alias, which later enables takeover plus bypass chains.

## Attack Surface

Applicability centers on the oracles fed by one header family.
The first oracle is a link-generating flow that builds absolute destinations from the Host value, such as a credential-reset flow or a delegation-callback flow or a canonical-link tag.
A second link-generating oracle is a discovery document that republishes issuer plus endpoint addresses, because every consumer of that document inherits the forged authority without a further request.
The second oracle is an access-controlled endpoint that trusts a non-rewrite forwarding alias for allowlist or scheme decisions.
An authority that selects the upstream the front end forwards to is a third, routing-shaped value: the parent authority step is accurate for it, and the interior-body read that follows escalates to the `ssrf` class rather than staying here.
Routing and path rewriting act at different layers and never compose, so a rewrite-shaped result belongs to header-method-override even when the two arrive in one request.

## Reconnaissance

Inventory narrows to the Host-family surface plus the flows that consume it.
Send Host and the forwarding alias for host with swapped values and record which one wins in emitted links plus log entries plus redirects.
Spray each non-Host non-rewrite alias with a forged value and record the per-alias decision delta on allowlist-gated plus scheme-gated endpoints.
Enumerate the host-shape edges in abstract form, namely bracketed-literal form plus trailing-dot form plus port-confusion form plus trailing-port form plus userinfo-split form plus suffixed-host form, and record which shapes the parser accepts.
Read a discovery document back after each forged submission, because a republished issuer or endpoint address proves the document consumed the forgery.
Record the virtual-host read-out per forged value, namely a status or size delta that names the default host and the interior hosts behind the edge.

## Detection Channels

Spoofing listens to links plus decisions, so only the entries below are live here.
- Emitted link destination carrying an attacker host proves the URL builder consumed the forgery.
- Out-of-band arrival of a token-bearing link at attacker infrastructure confirms the emitted destination leaves the building.
- Auth decision flip with and without a forged forwarding alias binds the probe to the access check.
- Republished issuer or endpoint address in a discovery document proves a second link-generating consumer inherited the forgery.
- Virtual-host enumeration read-out, namely a status or size delta per forged value, names the default host and the interior hosts behind the edge.
- Per-alias decision map records one allowlist plus scheme verdict per alias with its negative control.

## Adversarial Capabilities

Spoofing presupposes arbitrary header supply plus capture infrastructure plus comparison discipline, and it consumes all three.
- Send arbitrary Host values plus arbitrary forwarding-alias values, including mismatched pairs for precedence control.
- Operate an attacker host that receives emitted links and records token-bearing arrivals.
- Hold two sessions or identities so a decision delta reads as allow versus deny rather than noise.
- Drive a link-generating flow end to end and capture the emitted destination outside the application.

## Trust Assumptions

The stack treats an attacker-influenced value that reaches a response header field as inert data at the moment the feature executes.
The agreement holds the value free of framing meaning from capture through serialization, holds one declared interpreter for the value across the proxy-to-backend-to-client path, keeps the request in its declared method plus path plus protocol shape, keeps each response observable only to its caller, and keeps link targets plus cached bodies plus session state plus token-bearing destinations out of attacker reach.
This variant breaks the canonical-host clause because one forged Host-family value bends the emitted link and the access decision under controlled precedence.

## Key Vulnerabilities

### Forged Host In Link-Generating Flows

Submit a link-generating flow with an attacker-controlled Host and capture the emitted destination outside the application.
Confirm the destination carries the attacker host while still bearing the victim token or session material, because a rewritten link without live token material is only a reflection.
The parent link step covers only one forged submission, so this variant owns the swapped-precedence comparison plus the out-of-band capture that turns a reflection into token theft.

### Forwarding-Alias Decision Bending

Replay each non-Host non-rewrite alias against allowlist-gated plus scheme-gated endpoints and map the decision delta per alias with a clean negative control.
Treat the alias family as informational input with no protocol guarantee of origin, so any trust past the controlled boundary reads as exploitable until proven otherwise.
The parent spray step covers only single-alias submission, so this variant owns the per-alias mapping that turns one delta into a complete bypass chart.

## Bypass Techniques

Bypass forms stay aspects inside this variant because no spelling changes the precedence or mapping oracle itself.
- Shape bracketed-literal plus trailing-dot plus port-confusion host forms past a naive host equality check.
- Split the authority on userinfo and suffix the host so a substring or prefix comparison reads a permitted name inside a hostile one.
- Send an absolute request target whose authority differs from the field, so the enforcing layer and the link builder read different members.
- Mangle alias casing where the filter keys off exact spelling while the consumer folds case.
- Duplicate the Host field so the enforcing side reads one member while the builder reads the other.
- Layer encoded-dot plus encoded-port forms past a filter that decodes fewer times than the builder.

When this section does not fulfil the knowledge gap, extend the reading with the defence-bypass and proxy-techniques families.

## Chaining Attacks

Spoofing chains forward through the bent link or the opened endpoint because a bent value without a consumer is only confusion.
- Hand a token-bearing attacker link to account takeover once the victim follows or the flow delivers it.
- Hand an opened guarded endpoint to privileged-action abuse under the forged allowlist identity.
- Hand a proto-host-shaped poisoned response to header-cache-poisoning confirmation where the cache oracle fits better than the spoof oracle.

## Testing Methodology

Spoofing runs precedence comparison before capture and per-alias mapping before claims, because single submissions cannot attribute the trusting consumer.
1. **Inventory consuming flows** - list every link-generating flow plus every discovery document that republishes addresses plus every alias-trusting guarded endpoint, and the step completes when no flow, document, or endpoint lacks a recorded consumer.
2. **Compare precedence** - send Host and the forwarding alias for host with swapped values plus each host-shape edge, and the step completes when every emitted link plus redirect plus log entry names its winning source.
3. **Capture out of band** - drive each link flow with a forged Host and record the arrival outside the application, and the step completes when every emitted destination shows its host plus its token material.
4. **Map per-alias decisions** - replay each non-rewrite alias with forged values against each guarded endpoint beside a clean negative control, and the step completes when every alias carries an allowlist plus scheme verdict.
5. **Rule out rewrite ownership** - confirm no finding depends on a path-rewriting header, and the step completes when every rewrite-shaped result is handed to header-method-override with its evidence.

## False Positives

Stop when the evidence shows the forgery never reaches a trusting consumer, because untrusted reflection is only noise.
- Forwarding values reflected into logs only, with no link plus no decision consuming them.
- Emitted links validated against an allowlist before sending, confirmed by clean destinations across all forged submissions.
- Access check re-resolved at an inner layer that ignores the alias, confirmed by uniform denies beside the forged allows at the edge.
- Host-shape edges rejected by strict parsing, confirmed by uniform error responses across the edge family.

## Pro Tips

Spoofing rewards comparison discipline over spray volume, because attribution is the whole finding.
1. Prefer the credential-reset style flow first, since it costs one request and yields a token-bearing link on success.
2. Favor swapped-value pairs over single forgeries so the winning source reads directly from the diff.
3. Keep one negative control per alias so a decision delta survives review.
4. Capture out of band before claiming token theft, since an in-response link without delivery is only half the chain.
5. Hand any path-rewriting result to the routing sibling immediately rather than stretching this oracle to fit it.

## Summary

A URL builder plus an access check that both trust Host-family input hand link control plus gate control to whoever forges a header.
Spoofing compares precedence under control, captures the emitted link outside the application, and maps every alias to its decision before any takeover or bypass chain begins.
