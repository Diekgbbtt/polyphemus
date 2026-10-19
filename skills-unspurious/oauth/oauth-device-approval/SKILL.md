---
name: oauth-device-approval
description: Device approval inducement grants attacker sessions. Use when short user codes are guessable or pollable; when a victim can be induced to approve an attacker-initiated login; when approval binds no verified channel to the requester.
metadata:
  version: 1.0.0
---

# Device Approval

Device flows move approval to a side channel where the victim confirms a code on a separate screen.
This variant proves the channel is abusable by running device-code polling plus approval inducement.
The theft goal is an attacker-initiated login the victim approves, yielding a session the attacker controls.

## Attack Surface

Applicability centers on a device-authorization flow where one screen issues a short user code plus a verification address and a second screen collects the victim approval.
The polling endpoint that reports approval status and the approval screen the victim visits form the two attack points.
Slow rate limits plus short code alphabets shape the guessing cost without removing the channel.
Flows with no out-of-band approval step fall outside this variant.

## Reconnaissance

Map the approval channel before polling it.
Catalogue the device-issuance response shape plus the code alphabet plus the code lifetime plus the polling interval the server advertises.
Record the baseline behavior for a guessed code that was never issued plus the approval screen reached without a prior issuance.
Reconnaissance is complete when the code shape plus lifetime plus polling rules carry recorded baselines.

## Detection Channels

Only the entries below fire here; destination, freshness, verifier, and binding signals belong to the sibling variants.
- Polling-status transitions, where a guessed code moves from denied through pending to approved.
- Approval completion on an attacker-issued code, where the victim confirmation binds to the attacker session.
- Rate-limit shaping, where the server slows but never blocks repeated guesses.
- Expiry verdicts, where aged codes stop polling and bound the guessing window.

## Adversarial Capabilities

Approval abuse presupposes issuance access plus polling stamina plus victim inducement, and it consumes all three.
- Request device codes at will to learn the alphabet plus lifetime plus polling rules.
- Poll the status endpoint with guessed codes across the full guessing window.
- Lure a victim to the approval screen with an attacker-issued code through a prompt the victim trusts.
- Hold the attacker session open so a victim approval converts directly into attacker access.
- Pace guesses within the advertised limits so the channel stays open for the whole window.

## Trust Assumptions

At the moment the grant chain executes, the server trusts one binding agreement: the callback destination, the freshness token, the single-use verifier, the client identity, and the token audience presented at each step belong to the same legitimate session and client, with each value checked at the step that consumes it.
Sensitive account access leaks only when the server delivers grant credentials through such a checked chain.
This variant breaks the approval-channel clause because a victim approval for an attacker-issued code is honored as though the requester and the approver were the same party.

## Key Vulnerabilities

### Device-Code Polling

Guess unissued codes across the alphabet and poll each guess through the status endpoint, tracking shapes like `<never-issued-code>` plus `<attacker-issued-code>` plus `<aged-code>`.
Treat a pending or approved verdict on a guessed code as a polling finding and treat uniform denial plus clean expiry as a negative.
The parent exchange step covers only credential swapping between clients and cannot describe guessing plus status polling, so this variant owns the polling procedure.

### Approval Inducement

Issue a code under the attacker session, then induce the victim to approve it through a trusted-looking prompt, then poll for the approval transition.
Treat attacker-session access following victim approval as the core finding.
The parent exchange step never names victim-approval sequencing, so this variant owns the inducement procedure.

### Consent-Grant Inducement

Induce the victim to grant an attacker-registered application access to the account, which yields persistent tokens without any device code.
Treat the grant surviving the victim session as the finding, and confirm the granted credential persists rather than expiring with the session.

## Advanced Techniques

No advanced divergence rides here beyond polling plus inducement, because the approval channel is the whole surface.
Carry prompt-framing variations such as urgency plus authority plus help-desk pretexts as lure parameters inside the inducement step rather than separate techniques.

## Bypass Techniques

Bypass forms are the check values this variant defeats, each confirmed through polling rather than request shape alone.
- Short guessable codes pass an issuance side that favors usability over entropy.
- Slow-only rate limits pass a polling side that throttles without ever blocking, with the partial-limit step owned by the defence-bypass family.
- Unbound approvals pass a confirmation side that never joins the approver identity to the requester session.
- Unverified approval screens pass an inducement where any visitor can confirm any code.

When this section does not fulfil the knowledge gap, extend the reading with the defence-bypass and proxy-techniques families.

## Chaining Attacks

Approval findings chain forward into session theft because a polled code without victim confirmation is only a guessing statistic.
- Hand an approved attacker code to session establishment as the takeover proof.
- Hand a prior phishing or lure companion result to the inducement step so the victim reaches the approval screen already trusting the prompt.
- Treat code-interception positions such as shoulder-visible screens or shared displays as amplifiers that remove the guessing cost.

## Testing Methodology

Approval runs polling first and inducement second, because no lure is meaningful before the guessing verdict is known.
1. **Inventory the channel** - record the code alphabet plus lifetime plus polling interval plus baseline guess verdicts, and the step completes when no unlisted channel property remains.
2. **Poll guessed codes** - guess across the alphabet and poll each guess over parent step P5, which describes only credential swapping and never names guessing plus victim-approval sequencing, and the step completes when every guess carries a denied, pending, approved, or expired verdict.
3. **Measure the limits** - pace guesses against the advertised throttling and record the shaping behavior, and the step completes when the sustainable guessing rate plus the expiry bound are both documented.
4. **Induce approval** - issue under the attacker session and lure the tester-controlled victim to approve, and the step completes when each inducement shows attacker-session access or a documented refusal.
5. **Confirm session impact** - exercise the resulting session to prove control, and the step completes when every approval carries an access verdict or a documented scope bound.

## False Positives

Stop when the evidence shows the approval channel holds, because denied guesses are only noise.
- High-entropy codes with uniform denial across the guessing window.
- Approval bound to the requesting party so victim confirmation of an attacker code fails.
- Expiry plus single-attempt binding that closes the window before guessing converges.
- Rate limits that block rather than shape, confirmed by a hard refusal that persists across intervals.

## Pro Tips

Approval rewards patience plus pacing plus a clean victim role.
1. Learn the alphabet and lifetime from legitimate issuances before guessing anything.
2. Pace polls inside the advertised interval so throttling never poses as a block.
3. Keep the attacker session and the victim role on separate agents so approval attribution stays exact.
4. Log every guess behind its code plus verdict so the window accounting stays exhaustive.
5. Stop promoting uniformly denied guesses and record them as denials rather than inconclusive.

## Tooling

Drive the device channel by hand so issuance plus polling plus approval stay under tester control.
Track guess windows locally so expiry bounds each polling batch before the next begins.

## Summary

An approval channel that never joins the approver to the requester lets a victim click hand the attacker a session.
Approval abuse polls the code space, induces the confirmation, and converts each approval into proven session control.
