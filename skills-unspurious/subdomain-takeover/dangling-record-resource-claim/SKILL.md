---
name: dangling-record-resource-claim
description: Claim dangling names through exact-name resource creation. Use when a name resolves to an unclaimed external binding, when probe output shows an unclaimed-resource signature, when binding flows or verification gaps decide claimability.
metadata:
  version: 1.0.0
---

# Dangling Record Resource Claim

Claim trusted names whose records still point at released external resources.
This variant creates the missing resource under the exact required name and proves control by serving unique content from the trusted name.
The impact goal is trusted-origin content serving with phishing plus session plus trust-policy pivot.

## Attack Surface

Claim applies where a subdomain record points at an external binding no account still owns.
Claim applies where the binding is an alias or address record toward hosting or storage or edge capacity.
Claim applies where a decommissioned integration left its external binding referenced in DNS.
Claim varies only in which binding flow consumes the exact-name creation and which proof confirms control.

## Reconnaissance

Inventory candidate names from transparency logs plus passive resolution history plus asset records plus infrastructure outputs.
Record each candidate with its source and keep every alias chain collapsed to its terminal endpoint.
Resolve every record type across address plus alias plus delegation plus mail plus challenge-token records.
Probe each candidate for status plus body plus error text plus server headers plus certificate names.
Complete the survey when every candidate carries a recorded record chain and a recorded response triple.

## Detection Channels

Claim listens to unclaimed-resource evidence, so only the entries below are live here.
- Unclaimed-resource text in status plus body that matches a known missing-resource signature.
- Resolver signal separating dangling termination from live delegation failure.
- Certificate name showing a platform default instead of the tested custom name.
- Challenge-token residue in text records hinting at a previous external binding.
- Served proof content returning the unique claim token over a secure channel.

## Adversarial Capabilities

Claim presupposes account operation plus exact-name creation plus proof hosting, and it consumes all three.
- Operate an account on the hosting platform that can create named resources.
- Create the missing resource with the exact required name in the required region and shape.
- Serve a minimal unique proof page from the claimed binding over a secure channel.
- Observe binding acceptance plus verification refusal plus race-window availability across attempts.
- Hold authorization to attempt the claim and stop at a verification refusal.

## Trust Assumptions

When the subdomain feature executes, DNS is trusted to point only at owned resources and the platform is trusted to bind a name only to its owning account and delegations are trusted to stay live under owner control and alternate names are trusted to stay bound to their owning distribution.
Sensitive content and session trust leak only through a name that still resolves to attacker-controlled content.
That trust fails at the resource-ownership clause because the dangling record still points at an unclaimed binding that accepts exact-name creation.

## Key Vulnerabilities

Exact-name creation of the released binding is the bent step the parent claim phrase cannot describe.
Create the missing resource with the exact required name through the binding flow that owns the terminal endpoint.
Handle website versus interface endpoints separately because claimability and fingerprints differ between them.
Record the binding-flow family per candidate: a regional name pool that re-issues a released name to the first requester, a project namespace that re-opens after deletion, and edge capacity that re-attaches an unverified hostname are three separate claim paths.
Hold the proof shape abstract as a minimal static page carrying <proof-token>.
The delta over the parent is binding-flow handling plus verification-gap reading plus race-window re-claim plus website-versus-interface handling with unclaimed-text proof.

## Advanced Techniques

Anchor proof on a minimal unique page that renders quietly and compares cleanly.
Treat bucket-style naming constraints as claimability input because some hostnames cannot map to some stores.
Treat wildcard alias scope as enumeration widening inside this same claim procedure.
Treat fallback-origin behavior as confirmation input because unknown-domain answers reveal claimable surface.
Confirm control only through the trusted name returning <proof-token> over a secure channel.

## Bypass Techniques

Read each ownership control as claimability input and proceed only where the control permits.
- Treat prior-binding acceptance as the signal that a platform binds before challenge verification completes.
- Treat race-window availability as the signal that a recently released name is claimable again.
- Treat fallback-origin exposure as the signal that an unknown-domain answer still routes to attacker content.
- Treat issuance restriction as a guardrail that limits certificate issuance while the claim is triaged.

When this section does not fulfil the knowledge gap, extend the reading with the defence-bypass and proxy-techniques families.

## Chaining Attacks

Carry proven control into trust-policy impact owned by consumer checks.
- Carry trusted-origin content into allowlisted redirect and callback abuse.
- Carry trusted-origin scripts into policy and script-source trust abuse.
- Carry trusted-origin responses into scoped-cookie and cross-origin pivot.
- Name the request-forgery companion at the fetch step rather than restating its procedure here.

## Testing Methodology

Claim runs enumeration plus resolution plus probing plus fingerprinting plus authorized creation plus control proof in order.
1. **Enumerate candidates** - aggregate transparency plus passive plus inventory sources with one source recorded per name, and the step completes when every candidate name carries its source.
2. **Resolve records** - record every address plus alias plus delegation plus mail plus challenge-token chain with its terminal endpoint, and the step completes when every candidate carries a complete chain.
3. **Probe and fingerprint** - capture status plus body plus error text plus headers plus certificate names and map each triple to a known unclaimed signature or to unknown, and the step completes when every candidate carries a signature verdict.
4. **Bent step: attempt authorized exact-name claim** - create the missing resource with the exact required name through its binding flow including verification-gap and race-window handling, and the step completes when every claimable candidate shows creation success and every refused candidate shows a recorded verification refusal.
5. **Validate control** - serve a minimal page carrying <proof-token> and fetch it from the trusted name over a secure channel, and the step completes when every claimed name returns its unique token and no unclaimed name does.

## False Positives

Stop when the evidence shows an unclaimable or owned binding.
- Unknown-domain pages guarded by enforced ownership checks that refuse creation.
- Platform default pages served from a valid owned resource.
- Catch-all virtual hosts and soft not-found answers from owned infrastructure.
- Interface endpoints whose claimability differs from website endpoints on the same platform.

## Pro Tips

Claim rewards a current signature corpus plus quiet proofs plus clean teardown.
1. Keep the unclaimed-signature corpus current because platform messages change frequently.
2. Prefer a minimal static proof page carrying <proof-token> for every claim.
3. Record binding-flow and verification behavior per attempt so retests stay comparable.
4. Remove the claim resource and restore safe records immediately after proof completes.
5. Treat any enforced ownership refusal as a stop condition rather than a retry target.

## Summary

A dangling record that points at a released binding yields its trusted name to exact-name creation.
Claim the missing resource through its own binding flow and prove control with unique content served from the trusted name.
