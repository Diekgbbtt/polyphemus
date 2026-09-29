---
name: default-credential-replay
description: Replay published default pairs against the login acceptor when vendor placeholders stay active, when framework seeds stay unchanged, and when success signals follow submission.
metadata:
  version: 1.0.0
---

# Default Credential Replay

Deployments sometimes keep the published starting credential active on the login acceptor.
This variant converts guessable pairs into authentication through one submit-and-read-success replay procedure.
The replay goal is an immediate authenticated session at minimal noise before any expensive vector runs.

## Attack Surface

Applicability centers on a login acceptor that still honors a published default pair.
The acceptor receives credential pairs over an ordinary submit and answers with an authentication-success signal on match.
The server state distinguishes authenticated from anonymous through a navigational or marker or status signal after submission.
Linked source plus guessed artifacts plus identity oracles plus issued tokens ride outside this variant and belong to its siblings.

## Reconnaissance

Reconnaissance inventories the acceptor plus its success signals before any pair is submitted.
Locate every login acceptor reachable without authentication and record its carrier plus its submission shape with placeholders.
Record the anonymous baseline response for each acceptor so later success signals have a comparison point.
Enumerate candidate default pairs only as abstract placeholders, because concrete literals are runtime knowledge-base facts.

## Detection Channels

Replay listens to post-submission success signals only, so only the entries below are live here.
Success in this variant means the server accepted the pair, not that content matched a shape.
- Navigational arrival at an authenticated landing marker after submission signals acceptance.
- Presence of an authenticated session marker in the response signals acceptance.
- Redirect-to-authenticated status sequence after submission signals acceptance.

## Adversarial Capabilities

Replay presupposes anonymous submit plus success observation, and it consumes both.
Submit one candidate pair at a time to the login acceptor using ordinary submit primitives.
Hold no authenticated session beforehand, because the session is the goal rather than the prerequisite.
Observe each post-submission response for navigational plus marker plus status success signals.
Pace submissions politely so throttle state stays observable as a secondary check.

## Trust Assumptions

At the moment the authentication feature executes, the application agrees that served content carries no reusable secret, deployable artifacts stay unreachable over guessable paths, published default pairs grant no access, login responses stay uniform across identities, and issued tokens disclose no authority.
The request uses only ordinary fetch plus submit primitives with unauthenticated or session-held capability, and the server exposes only non-sensitive renderings plus uniform outcomes.
A reusable credential or an identity oracle or an authority claim leaks only through an explicit grant, never through side content or response shape.
This variant fails the default-pair clause because a published pair grants access at the login acceptor.

## Key Vulnerabilities

### Guessable-Pair Submission

Submit published default pairs to the login acceptor in a paced sequence and read each response for authentication success.
Vary the pair across attempts while keeping the submission shape fixed, because the acceptor not the shape decides the outcome.
The parent names this submit-and-read-success loop in exactly one step, and no fetch-and-read or oracle step covers credential submission, so this variant owns the replay procedure.

### Success-Signal Reading

Read navigational arrival plus session markers plus redirect sequences as the single success predicate for each attempt.
Treat any response matching the anonymous baseline as a negative and treat throttle responses as inconclusive retries rather than negatives.
Record lockout plus throttle state as a secondary check inside each attempt, because rate handling rides as an aspect rather than its own bypass procedure.

## Chaining Attacks

Replay chains forward into authenticated testing because a session without follow-on use wastes the opening.
Hand each accepted session into follow-on authorization testing plus artifact review.
Hand each accepted identity value to deeper credential review where richer pairs may share the same holder.
Treat token claim validation through authentication-jwt by naming it instead of restating its steps.

## Testing Methodology

Replay runs the acceptor inventory first and confirmation last, because success signals need a baseline to read against.
1. **Inventory acceptors** - list every login acceptor with its submission shape plus its anonymous baseline, and the step completes when every acceptor carries a recorded baseline.
2. **Submit guessable pairs** - replay one candidate pair per attempt in a paced order, and the step completes when every candidate pair carries a submitted verdict.
3. **Read authentication success** - compare each post-submission response against its baseline for navigational plus marker plus status signals, and the step completes when every attempt carries a success or negative or throttle-inconclusive verdict.
4. **Confirm the session** - reuse each success-signaling session against an authenticated-only marker, and the step completes when every success signal carries a confirmed-session or false-signal verdict.
5. **Record throttle state** - note lockout plus timing behavior observed during the run, and the step completes when every acceptor carries a throttle-observed or throttle-absent note.

## False Positives

Stop when the signal shows no authentication, because a marker without a session is only noise.
- Generic welcome wording that matches the anonymous baseline, confirmed by baseline equality.
- Throttle or block pages mistaken for success, confirmed when no authenticated-only marker follows.
- Example credentials shown in help content that the acceptor rejects, confirmed by uniform negatives across attempts.

## Pro Tips

Replay rewards cheap attempts plus strict success reading.
1. Prefer default replay before any expensive vector, because a hit here costs almost nothing.
2. Favor one pair per attempt with baseline comparison, so each verdict traces to exactly one submission.
3. Treat throttle responses as inconclusive and retry politely rather than recording them as negatives.
4. Confirm every success signal with an authenticated-only marker before chaining forward.

## Summary

A login acceptor that honors a published pair surrenders authentication to the cheapest possible probe.
Replay submits guessable pairs in a paced order, reads navigational plus marker plus status success, and confirms the session before any follow-on testing begins.
