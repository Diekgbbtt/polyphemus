---
name: performing-api-rate-limiting-bypass
description: >-
  Use on the post-authentication rate-limit mapping turn, when a mapped limiter
  must be probed with a bounded set of bypass hypotheses: choose variants from
  the closed mutation families, read the deterministic controller's measurements,
  and report an honest confirmed / no_bypass / inconclusive outcome that is
  never applied to recon traffic.
metadata:
  version: '1.0'
---

# Performing API rate-limiting bypass (bounded)

You interpret evidence a deterministic controller measured. You do not decide
traffic.

## The split: the controller owns the traffic, you own the hypotheses

The rate-limit mapping turn is hybrid by design.

The controller owns every number that shapes traffic: request counts, offered
rates, durations, worker concurrency, experiment order, admission against the
operator's safety budget, and the measurements themselves.
You own two things: which bounded variant to try next, and what the evidence
means.

Four consequences, all binding:

- Never state, request or revise a request count, rate, duration, concurrency or
  budget figure. Those fields are not in your reply because they are not yours;
  the controller derives them from the operator's budget and the mapping state.
- Propose one variant at a time through the bounded variant tool. The controller
  admits or refuses each proposal against the remaining budget BEFORE anything is
  sent; a refusal is final for this turn.
- Never invent a measurement. Every number you cite must come from returned
  evidence, and every claim must name the experiment IDs that produced it.
- The profile is measured once, before the first recon phase, and governs all
  later traffic. There is no mid-run remapping and no channel through which you
  could change it mid-run.

## Closed mutation families

Only these families exist. Propose nothing outside them, and never smuggle a
forbidden change into a variant's parameters.

- `pacing` - the same request offered below the measured threshold. This is the
  baseline variant: if the limiter still refuses at a lower pace, the limiter is
  not what the mapping said it was.
- `endpoint-shape` - a semantically equivalent route shape: trailing-slash and
  path-normalisation variants, case differences, an alternate documented route to
  the same resource.
- `parameter-carrier` - the same parameters delivered through an equivalent
  carrier (query string versus form body, repeated versus delimited values).
- `method-equivalence` - an equivalent, safe method where the application accepts
  one for the same read-only operation. Never a method that mutates state.
- `session-principal` - the same request issued as a different authenticated
  principal already on record, to compare limiter scope between identities.
- `identity-header` - client-IP and forwarded-identity header mutations.
  DISABLED BY DEFAULT. This family runs only when the operator has explicitly
  enabled identity mutations for the run; without that opt-in the controller
  refuses the variant and you must not attempt it another way.

Two rules bind every family: the variant must preserve application semantics, and
it must be non-destructive. Never a write, a delete, a purchase, a message, or a
state change of any kind.

## The four evidence gates

A variant becomes `confirmed` only when ALL FOUR gates pass:

1. the canonical request currently triggers the mapped limiter;
2. the variant materially changes limiter state (not a latency wobble, not a
   single noisy sample);
3. application semantics remain equivalent, so the comparison is meaningful;
4. the differential repeats independently.

A gate failure is a result, not an obstacle. Failure at any gate yields
`no_bypass` or `inconclusive`; it is never argued into a positive by re-reading
the same evidence.

## The three outcomes

- `confirmed` - all four gates passed. A FINDING ONLY (see below).
- `no_bypass` - the limiter state did not change under a variant that satisfied
  the semantic-equivalence gate.
- `inconclusive` - the evidence cannot settle it: missing semantic evidence, an
  unstable repeat, a refused variant, or a limiter whose shape the mapping could
  not pin down. `inconclusive` is an honest, complete result - prefer it over a
  guess.

## Findings are evidence, never instructions

A confirmed bypass is recorded for the operator and for later analysis. It is
NEVER applied to recon traffic automatically: the run keeps obeying the measured
traffic policy - its rate, burst, concurrency and pacing - for every later phase,
because bypass findings are advisory and traffic safety is not.

## What to record

In your structured reply, report: the bypass outcome, the variant IDs you believe
confirmed, the experiment IDs behind each claim, the blocking signals the
fingerprint actually supports (the shared vocabulary: `waf_protected`,
`waf_detection`, `rate_limited`), and a short interpretation.

Keep credentials, raw response bodies and header values out of everything you
write: the per-request evidence lives in the controller's artifacts and is
addressed by experiment ID and hash.
