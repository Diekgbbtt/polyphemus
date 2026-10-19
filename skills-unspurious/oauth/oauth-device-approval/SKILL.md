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

- **Applicability**: centers on a device-authorization flow where one screen issues a short user code plus a verification address and a second screen collects the victim approval.
- **Attack points**: the polling endpoint that reports approval status and the approval screen the victim visits form the two attack points.
- **Guessing cost**: slow rate limits plus short code alphabets shape the guessing cost without removing the channel.
- **Out-of-scope flows**: flows with no out-of-band approval step fall outside this variant.

## Reconnaissance

- **Approval-channel mapping**: map the approval channel before polling it.
- **Channel catalogue**: catalogue the device-issuance response shape plus the code alphabet plus the code lifetime plus the polling interval the server advertises.
- **Baseline recording**: record the baseline behavior for a guessed code that was never issued plus the approval screen reached without a prior issuance.
- **Completion criterion**: reconnaissance is complete when the code shape plus lifetime plus polling rules carry recorded baselines.

## Detection Channels

- **Channel scope**: destination, freshness, verifier, and binding signals belong to the sibling variants.
- **Polling-status transitions**: a guessed code moves from denied through pending to approved.
- **Approval completion on an attacker-issued code**: the victim confirmation binds to the attacker session.
- **Rate-limit shaping**: the server slows but never blocks repeated guesses.
- **Expiry verdicts**: aged codes stop polling and bound the guessing window.

## Adversarial Capabilities

- **Prerequisites**: approval abuse presupposes issuance access plus polling stamina plus victim inducement, and it consumes all three.
- **Code issuance**: request device codes at will to learn the alphabet plus lifetime plus polling rules.
- **Status polling**: poll the status endpoint with guessed codes across the full guessing window.
- **Victim inducement**: lure a victim to the approval screen with an attacker-issued code through a prompt the victim trusts.
- **Session holding**: hold the attacker session open so a victim approval converts directly into attacker access.
- **Guess pacing**: pace guesses within the advertised limits so the channel stays open for the whole window.

## Trust Assumptions

- **The agreement**: the callback destination, the freshness token, the single-use verifier, the client identity, and the token audience presented at each step belong to the same legitimate session and client, with each value checked at the step that consumes it.
- **The exposure**: sensitive account access leaks only when the server delivers grant credentials through such a checked chain.
- **The failing clause**: this variant breaks the approval-channel clause because a victim approval for an attacker-issued code is honored as though the requester and the approver were the same party.

## Key Vulnerabilities

### Device-Code Polling

- **Guessed-code polling**: guess unissued codes across the alphabet and poll each guess through the status endpoint, tracking shapes like `<never-issued-code>` plus `<attacker-issued-code>` plus `<aged-code>`.
- **Polling verdict**: treat a pending or approved verdict on a guessed code as a polling finding and treat uniform denial plus clean expiry as a negative.
- **Polling ownership**: the parent exchange step covers only credential swapping between clients and cannot describe guessing plus status polling, so this variant owns the polling procedure.

### Approval Inducement

- **Approval sequence**: issue a code under the attacker session, then induce the victim to approve it through a trusted-looking prompt, then poll for the approval transition.
- **Inducement verdict**: treat attacker-session access following victim approval as the core finding.
- **Inducement ownership**: the parent exchange step never names victim-approval sequencing, so this variant owns the inducement procedure.

### Consent-Grant Inducement

- **Consent-grant inducement**: induce the victim to grant an attacker-registered application access to the account, which yields persistent tokens without any device code.
- **Persistence verdict**: treat the grant surviving the victim session as the finding, and confirm the granted credential persists rather than expiring with the session.

## Advanced Techniques

- **Divergence scope**: no advanced divergence rides here beyond polling plus inducement, because the approval channel is the whole surface.
- **Lure parameters**: carry prompt-framing variations such as urgency plus authority plus help-desk pretexts as lure parameters inside the inducement step rather than separate techniques.

## Bypass Techniques

- **Bypass scope**: bypass forms are the check values this variant defeats, each confirmed through polling rather than request shape alone.
- **Short guessable codes**: pass an issuance side that favors usability over entropy.
- **Slow-only rate limits**: pass a polling side that throttles without ever blocking, with the partial-limit step owned by the defence-bypass family.
- **Unbound approvals**: pass a confirmation side that never joins the approver identity to the requester session.
- **Unverified approval screens**: pass an inducement where any visitor can confirm any code.

When this section does not fulfil the knowledge gap, extend the reading with the defence-bypass and proxy-techniques families.

## Chaining Attacks

- **Chain scope**: approval findings chain forward into session theft because a polled code without victim confirmation is only a guessing statistic.
- **Approved-code handoff**: hand an approved attacker code to session establishment as the takeover proof.
- **Lure-result handoff**: hand a prior phishing or lure companion result to the inducement step so the victim reaches the approval screen already trusting the prompt.
- **Interception amplifiers**: treat code-interception positions such as shoulder-visible screens or shared displays as amplifiers that remove the guessing cost.

## Testing Methodology

Approval runs polling first and inducement second, because no lure is meaningful before the guessing verdict is known.
1. **Inventory the channel** - record the code alphabet plus lifetime plus polling interval plus baseline guess verdicts, and the step completes when no unlisted channel property remains.
2. **Poll guessed codes** - guess across the alphabet and poll each guess over parent step P5, which describes only credential swapping and never names guessing plus victim-approval sequencing, and the step completes when every guess carries a denied, pending, approved, or expired verdict.
3. **Measure the limits** - pace guesses against the advertised throttling and record the shaping behavior, and the step completes when the sustainable guessing rate plus the expiry bound are both documented.
4. **Induce approval** - issue under the attacker session and lure the tester-controlled victim to approve, and the step completes when each inducement shows attacker-session access or a documented refusal.
5. **Confirm session impact** - exercise the resulting session to prove control, and the step completes when every approval carries an access verdict or a documented scope bound.

## False Positives

- **Channel-held stop**: stop when the evidence shows the approval channel holds, because denied guesses are only noise.
- **High-entropy codes**: show uniform denial across the guessing window.
- **Bound approval**: approval bound to the requesting party so victim confirmation of an attacker code fails.
- **Expiry and single-attempt binding**: close the window before guessing converges.
- **Rate-limit blocking**: rate limits block rather than shape, confirmed by a hard refusal that persists across intervals.

## Pro Tips

- **Discipline**: approval rewards patience plus pacing plus a clean victim role.
- **Alphabet learning**: learn the alphabet and lifetime from legitimate issuances before guessing anything.
- **Paced polling**: pace polls inside the advertised interval so throttling never poses as a block.
- **Role separation**: keep the attacker session and the victim role on separate agents so approval attribution stays exact.
- **Guess logging**: log every guess behind its code plus verdict so the window accounting stays exhaustive.
- **Denial recording**: stop promoting uniformly denied guesses and record them as denials rather than inconclusive.

## Tooling

- **Manual channel driving**: drive the device channel by hand so issuance plus polling plus approval stay under tester control.
- **Local window tracking**: track guess windows locally so expiry bounds each polling batch before the next begins.

## Summary

An approval channel that never joins the approver to the requester lets a victim click hand the attacker a session.
Approval abuse polls the code space, induces the confirmation, and converts each approval into proven session control.
