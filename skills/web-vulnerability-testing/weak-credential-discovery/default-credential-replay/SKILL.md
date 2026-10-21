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

- **Applicability**: centers on a login acceptor that still honors a published default pair.
- **Acceptor submit handling**: receives credential pairs over an ordinary submit and answers with an authentication-success signal on match.
- **Authenticated-state signal**: distinguishes authenticated from anonymous through a navigational or marker or status signal after submission.
- **Out-of-scope siblings**: linked source plus guessed artifacts plus identity oracles plus issued tokens ride outside this variant and belong to its siblings.

## Reconnaissance

- **Reconnaissance scope**: inventories the acceptor plus its success signals before any pair is submitted.
- **Acceptor location**: locate every login acceptor reachable without authentication and record its carrier plus its submission shape with placeholders.
- **Baseline recording**: record the anonymous baseline response for each acceptor so later success signals have a comparison point.
- **Candidate enumeration**: enumerate candidate default pairs only as abstract placeholders, because concrete literals are runtime knowledge-base facts.

## Detection Channels

- **Listening scope**: replay listens to post-submission success signals only.
- **Success definition**: success in this variant means the server accepted the pair, not that content matched a shape.
- **Navigational arrival**: signals acceptance when the response lands at an authenticated landing marker after submission.
- **Session marker**: signals acceptance when an authenticated session marker appears in the response.
- **Redirect sequence**: signals acceptance through a redirect-to-authenticated status sequence after submission.

## Adversarial Capabilities

- **Preconditions**: replay presupposes anonymous submit plus success observation, and it consumes both.
- **Candidate submission**: submit one candidate pair at a time to the login acceptor using ordinary submit primitives.
- **No prior session**: hold no authenticated session beforehand, because the session is the goal rather than the prerequisite.
- **Post-submission observation**: observe each post-submission response for navigational plus marker plus status success signals.
- **Polite pacing**: pace submissions politely so throttle state stays observable as a secondary check.

## Trust Assumptions

- **The agreement**: the application agrees that served content carries no reusable secret, deployable artifacts stay unreachable over guessable paths, published default pairs grant no access, login responses stay uniform across identities, and issued tokens disclose no authority, while the request uses only ordinary fetch plus submit primitives with unauthenticated or session-held capability, the server exposes only non-sensitive renderings plus uniform outcomes, and a reusable credential or an identity oracle or an authority claim leaks only through an explicit grant, never through side content or response shape.
- **The failing clause**: this variant fails the default-pair clause because a published pair grants access at the login acceptor.

## Key Vulnerabilities

### Guessable-Pair Submission

- **Paced submission**: submit published default pairs to the login acceptor in a paced sequence and read each response for authentication success.
- **Shape invariance**: vary the pair across attempts while keeping the submission shape fixed, because the acceptor not the shape decides the outcome.
- **Ownership**: the parent names this submit-and-read-success loop in exactly one step, and no fetch-and-read or oracle step covers credential submission, so this variant owns the replay procedure.

### Success-Signal Reading

- **Success predicate**: read navigational arrival plus session markers plus redirect sequences as the single success predicate for each attempt.
- **Negative versus inconclusive**: treat any response matching the anonymous baseline as a negative and treat throttle responses as inconclusive retries rather than negatives.
- **Throttle recording**: record lockout plus throttle state as a secondary check inside each attempt, because rate handling rides as an aspect rather than its own bypass procedure.

## Chaining Attacks

- **Forward chaining**: replay chains forward into authenticated testing because a session without follow-on use wastes the opening.
- **Session handoff**: hand each accepted session into follow-on authorization testing plus artifact review.
- **Identity handoff**: hand each accepted identity value to deeper credential review where richer pairs may share the same holder.
- **Token-validation naming**: treat token claim validation through authentication-jwt by naming it instead of restating its steps.

## Testing Methodology

Replay runs the acceptor inventory first and confirmation last, because success signals need a baseline to read against.
1. **Inventory acceptors** - list every login acceptor with its submission shape plus its anonymous baseline, and the step completes when every acceptor carries a recorded baseline.
2. **Submit guessable pairs** - replay one candidate pair per attempt in a paced order, and the step completes when every candidate pair carries a submitted verdict.
3. **Read authentication success** - compare each post-submission response against its baseline for navigational plus marker plus status signals, and the step completes when every attempt carries a success or negative or throttle-inconclusive verdict.
4. **Confirm the session** - reuse each success-signaling session against an authenticated-only marker, and the step completes when every success signal carries a confirmed-session or false-signal verdict.
5. **Record throttle state** - note lockout plus timing behavior observed during the run, and the step completes when every acceptor carries a throttle-observed or throttle-absent note.

## False Positives

- **No authentication**: stop when the signal shows no authentication, because a marker without a session is only noise.
- **Generic welcome wording**: matches the anonymous baseline, confirmed by baseline equality.
- **Throttle or block pages**: mistaken for success, confirmed when no authenticated-only marker follows.
- **Example credentials**: shown in help content that the acceptor rejects, confirmed by uniform negatives across attempts.

## Pro Tips

- **Replay economics**: replay rewards cheap attempts plus strict success reading.
- **Cheap-first ordering**: prefer default replay before any expensive vector, because a hit here costs almost nothing.
- **One pair per attempt**: favor one pair per attempt with baseline comparison, so each verdict traces to exactly one submission.
- **Throttle handling**: treat throttle responses as inconclusive and retry politely rather than recording them as negatives.
- **Success confirmation**: confirm every success signal with an authenticated-only marker before chaining forward.

## Summary

A login acceptor that honors a published pair surrenders authentication to the cheapest possible probe.
Replay submits guessable pairs in a paced order, reads navigational plus marker plus status success, and confirms the session before any follow-on testing begins.
