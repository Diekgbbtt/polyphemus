---
name: proxy-techniques-cache-deception
description: Shared-cache key confusion where a stored response reaches a caller it was not produced for, covering unkeyed input when a selector shapes the body but not the key, key normalisation and fragmentation when the key collapses entries it should separate, and stored-response reads when one caller reads an entry produced for another.
metadata:
  version: 1.0.0
---

# Cache Deception

A shared cache stores one response under one key and serves it to every caller that names the key. This variant works the key rather than the response: an input that shapes the body but not the key stores attacker-influenced content for later callers, and a key that omits an identity binding serves one caller's content to another. The goal is a stored entry reaching a caller the entry was not produced for, proved by a second-caller read.

## Attack Surface

Cache deception applicability centers on a shared cache between the caller and the origin, with a key the caller can influence or name.
The surface holds unkeyed selectors that shape the body, key-variation and accept fields, address tails and suffixes that decide whether an entry is stored, and identity bindings the key omits.
A cache that keys on the address alone while the body varies by anything else, and a cache whose normalisation collapses distinct entries, both widen the surface.
A cache whose key covers every selector that shapes the response rides outside this variant, because there is nothing left to omit.

## Reconnaissance

Cache deception reads the key before crafting, because the mechanism is an omission in the key rather than a malformed request.
- Identify the shared cache on the path and the fields that decide whether a response is stored.
- Enumerate the selectors that shape the body and record which of them the key covers.
- Establish the refusal baseline with a request the cache does not store, so a later stored entry is attributable to the key.
- Read a stored entry back with a second caller, because an entry that no second caller reaches proves nothing.

## Detection Channels

Cache deception listens to the stored entry and its key, so only the entries below are live here.
- A shared cache serving a response to a later caller under a key the caller influenced or reads.
- A paired baseline where the same operation differs with and without the cache in the path.
- The stored entry read back under a key that omits an identity binding, which proves the entry reaches another caller.
- The effect of the stored body on a caller who never sent the shaping input.
- A negative that holds across every key shape, which reads as a key that covers its selectors.

## Adversarial Capabilities

Cache deception presupposes key knowledge plus a second caller plus a stored-entry read, and it consumes all three.
- Identify the selectors that shape the body and the fields that decide storage.
- Shape one selector per attempt, keeping the request otherwise identical.
- Read the entry back as a second caller or in a second session, so the entry's reach is proved rather than inferred.
- Hold a second identity where the key's omission is the identity binding.

## Trust Assumptions

The shared cache trusts that its key covers everything that varies the response, and that a stored entry is served only to callers the entry was produced for.
The agreement holds the key to every selector that shapes the body, holds normalisation to a one-to-one mapping between keys and entries, and holds an entry to the caller set it was produced for.
This variant breaks the cache-key clause because a selector that shapes the response is absent from the key, so one entry reaches callers the response was not produced for.
The reach is claimed only when a second caller reads the entry, because the first caller's own read proves nothing about the key.

## Key Vulnerabilities

### Unkeyed Input to a Keyed Response

Find the selector that shapes the body while the key ignores it, and store a body the origin would produce only for the shaping request.
Vary one selector per attempt and re-read the entry each time, because storage eligibility and key coverage are decided separately.
The parent intermediary-characterisation step covers what a hop forwards and cannot describe a key that omits a selector, so this variant owns the key-coverage procedure.

### Key Normalisation and Fragmentation

Shape separators, casing, and fragmentation markers that the key's normalisation collapses, so entries the origin meant to separate share one key.
Use suffixes and address tails where storage eligibility keys off the address alone, because eligibility and key identity are different rules.
Treat a collapse that serves another caller as the completed probe, and record the normalisation step that caused it.

### Stored-Response Reads Across Callers

Read a stored entry as a second caller where the key omits the identity binding, because a stored response outlives the session that produced it.
Hold a second session and request the entry with the key the first caller named.
Treat an entry reachable only by the producing caller as a private entry rather than a deception.

## Bypass Techniques

Relay shapes are tried only after the direct route is baselined, because a cache that never stored carried nothing.

- A selector that shapes the body while the key omits it.
- Separators, casing, and fragmentation markers the key's normalisation collapses.
- Address tails and suffixes that change an entry's storage eligibility or reach.
- Key-variation and accept fields that select between stored entries.
- A second caller or session reading an entry produced for another.

## Chaining Attacks

Cache deception chains forward into the class that owns the effect, because a stored entry is only the first hop.
- Hand the stored body to the class that owns the effect, and prove the class-specific consequence for a later caller there.
- Chain into the stored-response disclosure class where the entry carries content from another caller.
- Chain into the tier gap where the cache also stores a verdict rather than a response body.
- Name the class at its own step rather than restating its procedure here.

## Testing Methodology

Cache deception reads the key first and stores second, because the omission is a property of the key.

1. **Locate the cache** - the shared cache on the path and the fields that decide storage, and the step completes when the cache and its storage rule are both named.
2. **Enumerate the selectors** - every input that shapes the body with the key's coverage of each, and the step completes when the uncovered selector is named.
3. **Baseline a non-stored request** - send a request the cache does not store, and the step completes when the absence of a stored entry is recorded with the test that showed it.
4. **Store the shaped body** - send the shaping input and read the entry back, and the step completes when the stored body carries the shaping input's effect.
5. **Read as a second caller** - request the entry from a second caller or session, and the step completes when the second read returns the stored body.
6. **Attribute the reach** - pair the first caller's shaping request with the second caller's read, and the step completes when the omitted selector or binding is named from the pair.

## False Positives

Stop when the entry reached only the caller that produced it, because a private entry is not a deception.

- A cache whose key covers every selector that shapes the body, confirmed by distinct entries per selector.
- An entry reachable only by the producing caller or session.
- A cache that stored the tester's own session entry under a key that names the tester.
- A response that looks stored but is regenerated per request, confirmed by a changing body.
- A simulator that answers the entry itself without a real cache in the path.

## Pro Tips

Cache deception rewards key reading plus a second-caller read.

1. Read the key's coverage before crafting, because the mechanism is an omission in the key.
2. Vary one selector per attempt so the omission is nameable.
3. Read every entry back as a second caller, since the first caller's read proves nothing.
4. Treat storage eligibility and key identity as separate rules, because a suffix can change one without the other.
5. Hand the stored body to the class that owns the effect, and stop at the narrowest proof.

## Summary

A shared cache serves one stored response to every caller that names its key. Cache deception shapes a selector the key omits, stores a body for later callers, and claims the reach only when a second caller reads the entry.
