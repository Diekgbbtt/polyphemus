---
name: differential-oracle-disclosure
description: Response differentials disclose state. Use when method swaps change answers on one resource; when cached responses leak across sessions; when parallel channels disagree on the same object.
metadata:
  version: 1.0.0
---

# Differential Oracle Disclosure

Agreement is a channel.
This variant compares two responses that should match and reads their delta: same-principal method and conditional replays, second-session cache serving, and cross-channel field mirrors in one compare-two-responses procedure.

## Attack Surface

- **Method handling**: lives wherever one resource answers two verbs or a conditional replay differently: header-only versus full responses and revalidation outcomes.
- **Cache keying**: lives in intermediary layers whose keys may omit identity or tenant headers and whose fragment reassembly may serve foreign bytes.
- **Channel hardening**: lives across parallel representations of the same object: API flavors, socket transports, and server versus client rendering paths.
- **Role comparison**: lives in owner versus non-owner versus anonymous renderings and is owned by the two-principal-authz skill, which this variant names at that step instead of restating.

## Reconnaissance

- **Pair mapping**: map the replayable pairs before comparing them.
- **Pair construction**: pair each resource with its alternate method, each conditional validator with its replay shape, each cacheable response with a second session, and each object with its parallel-channel representations.
- **Keying-signal recording**: record the keying signals each cache layer emits so later serving has a baseline.
- **Completion condition**: reconnaissance is complete when every resource carries its method, conditional, session, and channel pairs.

## Detection Channels

- **Method-swap deltas**: method-swap deltas where a header-only answer diverges from the full answer on existence or state.
- **Conditional-replay deltas**: conditional-replay deltas where revalidation outcomes diverge on existence or state for the same principal.
- **Second-session serving**: second-session serving where a foreign session receives poisoned or fragment-reassembled content the first session keyed.
- **Origin-versus-cache disagreement**: an origin-versus-cache path-normalization disagreement, where the cached key does not match the resource the origin served.
- **Pre-redirect body**: a body that carries content before the redirect fires, read without following the redirect.
- **Per-channel field extras**: per-channel field extras where parallel representations of the same object disagree on fields or hardening.
- **Channel scope**: only channels carried by two-response comparison fire here; cross-role renderings belong to two-principal-authz and single-response content belongs to the sibling variants.

## Adversarial Capabilities

- **Paired requesting**: paired requesting is the entry capability: the procedure presupposes the ability to issue two shaped requests as the same principal and hold both answers.
- **Conditional replay**: conditional replay extends the pairing: the ability to resubmit validators and read revalidation outcomes per resource.
- **Second-session holding**: second-session holding confirms cache effects: a separate session that reads what the first session keyed, plus fragment reassembly reads where partial content applies.
- **Multi-channel fetching**: multi-channel fetching mirrors one object across representations to record per-channel extras.

## Trust Assumptions

- **The trust premise**: at the moment the server answers the second request, the target trusts that what it does not intend to reveal cannot be elicited.
- **The agreement**: the precise agreement is that two responses which must remain indistinguishable will in fact agree: same-principal replays, cached servings, and channel mirrors carry no distinguishing delta.
- **The failing clause**: the failing clause is the agreement-of-indistinguishables clause: the pair diverges where the agreement promised sameness, and the delta alone concludes.

## Key Vulnerabilities

- **Method swapping**: method swapping replays a header-only request against the full request on the same resource as the same principal to confirm existence or state.
- **Conditional replaying**: conditional replaying resubmits validators to read revalidation outcomes as existence or state signals.
- **Key manipulating**: key manipulating submits identity-varying input that leaves the cache key unchanged, then confirms a second session is served foreign content with fragment reassembly.
- **Cache-deception forcing**: cache-deception forcing makes a dynamic or authenticated response cacheable under a static-looking key (path extension, delimiter, or normalization form), then reads it without credentials; the proxy-techniques family owns the generic cache mechanics and this oracle records only the serving verdict.
- **Cache-miss forcing**: cache-miss forcing uses a cache-busting query value rather than a cache-control header, because intermediaries frequently ignore the header while honouring the key.
- **Mirroring**: mirroring requests the same object across API flavors, socket transports, and rendering paths and records per-channel field extras with hardening deltas.
- **Secondary checking**: checking records redaction-holds and key-correctness states as secondary aspects inside the same oracle rather than standalone defeats.

## Chaining Attacks

- **Existence to targeting**: confirmed existence or state scopes follow-on requests the owning skills execute.
- **Cross-session serving to boundary crossing**: foreign content served to a second session feeds tenant-boundary escalation owned by the authorization skills.
- **Channel extras to hidden operations**: fields visible on only one channel scope authorization-bypass attempts.
- **Chain discipline**: each chain stops at a reversible proof or a stated architectural risk rather than a full exploit.

## Testing Methodology

1. **Map replayable pairs** - pair each resource with its alternate method, conditional replay shape, second session, and parallel-channel representations. Complete when every in-scope resource carries all four pairs.
2. **Execute unified same-principal compare-two-responses** - replay method swaps, conditional validators, second-session cache reads with fragment reassembly, and cross-channel mirrors, normalizing both answers per pair on status, length, validators, and headers, over parent step P2, which describes only cross-role comparison and never names the unified same-principal oracle. Complete when every pair carries normalized digests for both responses.
3. **Conclude from the delta alone** - decide each pair only where neither response alone suffices and the comparison concludes existence, state, foreign serving, or field extras. Complete when every pair is decided by its delta or ruled agreeing.
4. **Record secondary controls** - note redaction-holds and key-correctness states observed during the same comparisons. Complete when each observed control carries a state note.
5. **Correlate to impact** - map each concluded delta to cross-tenant exposure, cache poisoning, hidden operations, or existence disclosure, with a minimal reversible proof or a stated risk. Complete when every concluded delta carries a proof or a risk statement.

## False Positives

- **Role-only deltas**: role-only deltas decided by principal comparison belong to two-principal-authz rather than this oracle.
- **Redacted fields**: redacted fields that leave every pair agreeing carry no leak.
- **Intentional channel differences**: intentional per-channel representation differences with no sensitive extra and no exploit path are not findings.
- **Single responses**: single responses that already disclose without comparison belong to the sibling variants.

## Pro Tips

- **Digest diffing**: normalize both answers and diff by digest so boilerplate never poses as signal.
- **Same-principal discipline**: hold the principal constant across each pair: same-principal discipline is what separates this oracle from role comparison.
- **Second-session confirmation**: confirm cache effects with a true second session rather than a header tweak in one session.
- **Throwaway keys**: probe under a throwaway cache-busting key and never store under the live key, so the probe itself does not become the incident.
- **Pre-redirect reading**: read a redirect's body before following it, because content frequently rides in the body that the redirect discards.
- **Field-extra pivot**: treat one field extra as a pivot: its name scopes the next mirror to request.

## Summary

Differential oracle disclosure turns agreement into intelligence.
Replay each pair as one principal, conclude from the delta alone, and convert every divergence into a scoped follow-on.
