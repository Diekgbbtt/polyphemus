---
name: header-cache-poisoning
description: Poisoning shared caches with unkeyed input that shapes cached bodies, sweeping fragmentation plus eligibility plus deception sub-shapes, and confirming with a clean second-session replay.
metadata:
  version: 1.0.0
---

# Cache Poisoning via Unkeyed Input

Caches separate the key they store under from the content they store, and that separation is a trust decision.
This variant sweeps unkeyed plus fragmentation plus proto-host plus eligibility plus deception sub-shapes under a clean-replay body oracle.
The poisoning goal is an attacker-influenced body served to a victim key, which later enables script execution plus redirect theft plus denial through the stored entry.

## Attack Surface

- **Applicability**: centers on a cache layer whose key composition stays distinct from response content.
- **Attacker-influenced input**: shapes the stored body while the cache ignores that input when computing the key.
- **Confirmation oracle**: needs no new header field and no line-break payload, which separates this variant from header-crlf-splitting by its body-proof predicate.
- **Excluded shapes**: line-break framing payloads never ride here, and proto-host link building that bends only the emitted link belongs to header-host-forward-spoof.

## Reconnaissance

- **Inventory**: narrows to the key-versus-content split plus the signals that expose it.
- **Cache-signal mapping**: map cache-signal headers in abstract form, namely age plus hit-or-miss plus key-status indicators, across repeated requests to learn the caching layer and its key behavior.
- **Split finding**: find inputs that move the body without moving the key by flipping headers plus parameters and diffing bodies beside signal values.
- **Unkeyed-input families**: see `references/unkeyed-input-families.md` for the component families to sweep against the key.
- **Baseline recording**: record eligibility plus fragmentation behavior per sub-shape before sweeping, so each sweep starts from a mapped baseline.

## Detection Channels

- **Poisoning**: listens for victim-key serving.
- **Clean-replay body serving**: attacker-influenced body served under a victim key on clean replay with no new header field required binds the probe to the key-versus-content split.
- **Cache-signal persistence**: cache-signal values showing a stored hit behind the poisoned body confirm the entry persisted rather than reflecting once.
- **Control-key body diff**: body diff between the poisoned key and a never-touched control key isolates the attacker influence from ambient content drift.
- **Eligibility-signal change**: eligibility-signal change across the sweep records which sub-shape flipped the entry from private to shared.

## Adversarial Capabilities

- **Poisoning**: presupposes unkeyed-input supply plus a clean second session, and it consumes both.
- **Unkeyed-input supply**: supply attacker-influenced input through headers plus parameters that the cache ignores when keying.
- **Clean second session**: hold a second clean session that replays the victim address with no attack headers and records the served body.
- **Churn settling**: repeat probes until cache churn settles, so a stored entry reads as stable rather than transient.
- **Single-sub-shape variation**: vary one sub-shape at a time so each poisoned entry attributes to exactly one sweep member.

## Trust Assumptions

- **The agreement**: the stack treats an attacker-influenced value that reaches a response header field as inert data at the moment the feature executes, holds the value free of framing meaning from capture through serialization, holds one declared interpreter for the value across the proxy-to-backend-to-client path, keeps the request in its declared method plus path plus protocol shape, keeps each response observable only to its caller, and keeps link targets plus cached bodies plus session state plus token-bearing destinations out of attacker reach.
- **The failing clause**: unkeyed input shapes a cached body that a second session receives under a victim key.

## Key Vulnerabilities

### Unkeyed Reflection Into Cached Bodies

- **Unkeyed reflection**: reflect an unkeyed header or parameter value into the stored body while the key stays fixed, then confirm a clean replay serves the influenced body.
- **Allow-origin reflection**: reflect a cross-origin request origin into an allow-origin value that the cache stores, so later callers receive the permissive value without sending the origin themselves.
- **Variant ownership**: the parent split step names only body-versus-key finding, so this variant owns the sub-shape sweep plus eligibility handling that turns one reflection into five storable primitives.
- **Boundary**: treat correctly keyed personalization as the boundary, because keyed variation is intended behavior rather than poisoning.

### Fragmentation Plus Eligibility Plus Deception Shapes

- **Shape sweep**: sweep fragmentation games that over-split or under-split the key space, proto-host URL building that plants attacker destinations in cached links, eligibility flips that convert private entries to shared ones, and deception-suffixed public addresses that store authenticated bodies under cacheable shapes.
- **Envelope and error shapes**: carry fat-request shapes whose body the backend processes while the cache keys on the address alone, forwarded-port and method-override shapes where the cache keys one method's address while the backend answers another, and cached error responses produced from attacker input that later callers then receive.
- **Eligibility handling**: handle eligibility explicitly per sub-shape, since a stored entry that never becomes shareable is only a private reflection.
- **Sibling boundary**: name link-only proto-host bending at this step rather than restating it, since header-host-forward-spoof owns the link oracle without the cache store.

## Bypass Techniques

- **Bypass forms**: stay aspects inside this variant because no spelling changes the clean-replay oracle itself.
- **Value smuggling**: smuggle the unkeyed value through encoded plus case-varied plus whitespace-padded forms past a naive key-normalizer.
- **Eligibility-marker flip**: flip eligibility markers in abstract form, namely shareability plus freshness-window directives, past a filter that inspects only the first directive.
- **Fragmentation-marker variation**: vary fragmentation markers so the key computation collapses entries the filter meant to separate.
- **Deception-suffix shaping**: suffice deception suffixes in cacheable shape past a rule that keys off the address tail alone.
- **Deception path-discrepancy sweep**: sweep the deception path-discrepancy family, namely delimiter append, encoded separator, encoded percent, null byte, fragment, dot-segment normalization, case variation, and double-encoded path, because each member moves the cache key and the origin path apart.
- **Sibling boundary**: name the proxy-techniques family at the shared-cache keying step rather than restating its mechanics.
- **Extended reading**: when this section does not fulfil the knowledge gap, extend the reading with the defence-bypass and proxy-techniques families.

## Chaining Attacks

- **Poisoning**: chains forward through the stored body because a stored entry without a victim consumer is only persistence.
- **Session theft**: hand a poisoned script-capable body to session theft once a victim loads the victim key.
- **Credential capture**: hand a poisoned redirect destination to credential capture once the victim follows the stored link.
- **Availability pressure**: hand a poisoned cache-busting entry to availability pressure where repeated eviction plus refill fits the goal better than content theft.

## Testing Methodology

Poisoning runs split-finding before sweeping and clean replay last, because attacker-visible reflection without victim serving is only noise.
1. **Map key behavior** - record cache-signal values plus key composition across repeated requests, and the step completes when every signal reads stable with its baseline.
2. **Find the split** - flip candidate inputs and diff bodies beside signal values, and the step completes when each body-moving but key-ignored input carries a recorded split verdict.
3. **Sweep sub-shapes** - replay unkeyed plus fragmentation plus proto-host plus eligibility plus deception shapes one at a time under a fresh throwaway key, and the step completes when every shape carries a stored-or-clean verdict with its samples.
4. **Confirm by clean replay** - replay the victim address from a second session with no attack headers, and the step completes when the served body shows attacker influence or the entry is ruled out with its evidence.
5. **Bound eligibility** - record the shareability plus freshness behavior of each confirmed entry, and the step completes when every entry shows who can receive it and for how long.

## False Positives

- **Stop condition**: stop when the evidence shows the influenced body never leaves the attacker session, because private reflection is only noise.
- **Personalization**: keyed correctly per session, confirmed by clean-session absence across all sub-shapes.
- **Fragmentation markers**: honored by the cache, confirmed by per-variant keys that never collapse.
- **Eligibility**: stays private across the sweep, confirmed by shareability signals that never flip.
- **Poisoned body**: visible only while attack headers ride along, confirmed by clean-replay absence.

## Pro Tips

- **Poisoning**: rewards split-finding patience over sweep speed, because the unkeyed input is the whole finding.
- **Split-first**: prefer the body-moving but key-ignored input hunt first, since every sub-shape follows from it.
- **One sub-shape per probe**: favor one sub-shape per probe so each stored entry attributes cleanly.
- **Clean-session confirmation**: confirm through the second clean session before claiming impact, since attacker-session visibility proves nothing.
- **Eligibility watch**: watch eligibility signals beside bodies, because a stored-but-private entry is not a victim finding.
- **Sibling handoff**: hand link-only proto-host results to the spoofing sibling where no cache store backs them.

## Summary

A cache that keys without the input it stores under hands shared responses to whoever finds the unkeyed value.
Poisoning maps key behavior, sweeps the five sub-shapes, and proves a clean second session receives the influenced body before any theft or disruption chain begins.
