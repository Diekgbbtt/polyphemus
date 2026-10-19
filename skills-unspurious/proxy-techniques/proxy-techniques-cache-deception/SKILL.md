---
name: proxy-techniques-cache-deception
description: Shared-cache key confusion where a stored response reaches a caller it was not produced for, covering unkeyed input when a selector shapes the body but not the key, stored failure and permission classes when the entry carries an error or a verdict, key normalisation and fragmentation when the key collapses entries it should separate, eligibility suffixes when a static-looking tail decides storage, and stored-response reads when one caller reads an entry produced for another.
metadata:
  version: 1.0.0
---

# Cache Deception

A shared cache stores one response under one key and serves it to every caller that names the key. This variant works the key rather than the response: an input that shapes the body but not the key stores attacker-influenced content for later callers, and a key that omits an identity binding serves one caller's content to another. The goal is a stored entry reaching a caller the entry was not produced for, proved by a second-caller read.

## Attack Surface

- **Applicability**: centers on a shared cache between the caller and the origin, with a key the caller can influence or name.
- **Surface composition**: unkeyed selectors that shape the body, key-variation and accept fields, address tails and suffixes that decide whether an entry is stored, and identity bindings the key omits.
- **Widening factors**: a cache that keys on the address alone while the body varies by anything else, and a cache whose normalisation collapses distinct entries, both widen the surface.
- **Out-of-scope variant**: a cache whose key covers every selector that shapes the response rides outside this variant, because there is nothing left to omit.

## Reconnaissance

- **Reconnaissance scope**: cache deception reads the key before crafting, because the mechanism is an omission in the key rather than a malformed request.
- **Cache identification**: identify the shared cache on the path and the fields that decide whether a response is stored.
- **Selector enumeration**: enumerate the selectors that shape the body and record which of them the key covers.
- **Refusal baseline**: establish the refusal baseline with a request the cache does not store, so a later stored entry is attributable to the key.
- **Second-caller read**: read a stored entry back with a second caller, because an entry that no second caller reaches proves nothing.

## Detection Channels

- **Channel scope**: cache deception listens to the stored entry and its key, so only the entries below are live here.
- **Later-caller serving**: a shared cache serving a response to a later caller under a key the caller influenced or reads.
- **Cache status fields**: the cache's own status and age fields, which name the cache, the entry's state, and its lifetime.
- **Paired baseline**: a paired baseline where the same operation differs with and without the cache in the path.
- **Cross-caller entry**: the stored entry read back under a key that omits an identity binding, which proves the entry reaches another caller.
- **Stored-body effect**: the effect of the stored body on a caller who never sent the shaping input.
- **Uniform negative**: a negative that holds across every key shape, which reads as a key that covers its selectors.

## Adversarial Capabilities

- **Prerequisites**: cache deception presupposes key knowledge plus a second caller plus a stored-entry read, and it consumes all three.
- **Selector identification**: identify the selectors that shape the body and the fields that decide storage.
- **One selector per attempt**: shape one selector per attempt, keeping the request otherwise identical.
- **Second-caller reading**: read the entry back as a second caller or in a second session, so the entry's reach is proved rather than inferred.
- **Second identity**: hold a second identity where the key's omission is the identity binding.

## Trust Assumptions

- **The agreement**: the shared cache trusts that its key covers everything that varies the response, and that a stored entry is served only to callers the entry was produced for, holds the key to every selector that shapes the body, holds normalisation to a one-to-one mapping between keys and entries, and holds an entry to the caller set it was produced for.
- **The failing clause**: this variant breaks the cache-key clause because a selector that shapes the response is absent from the key, so one entry reaches callers the response was not produced for.
- **Claim discipline**: the reach is claimed only when a second caller reads the entry, because the first caller's own read proves nothing about the key.

## Key Vulnerabilities

### Unkeyed Input to a Keyed Response

- **Selector omission**: find the selector that shapes the body while the key ignores it, and store a body the origin would produce only for the shaping request.
- **Response class**: a response class is a selector too: a failure produced from attacker input is stored under a healthy request's key, so a later caller reaches a failed response for a working operation.
- **Carrier variation**: a header the key omits is the same clause with a different carrier, and a permission field produced for a shaping value is served to later callers as the origin's own verdict.
- **Structural omission**: a duplicate member the parser reads and the key omits, and a body carried on a read-only verb whose parameters the key ignores, are the same omission in a structural form.
- **One selector per attempt**: vary one selector per attempt and re-read the entry each time, because storage eligibility and key coverage are decided separately.
- **Ownership**: the parent intermediary-characterisation step covers what a hop forwards and cannot describe a key that omits a selector, so this variant owns the key-coverage procedure.

### Key Normalisation and Fragmentation

- **Normalisation collapse**: shape separators, casing, and fragmentation markers that the key's normalisation collapses, so entries the origin meant to separate share one key.
- **Eligibility suffixes**: use suffixes and address tails where storage eligibility keys off the address alone, because eligibility and key identity are different rules.
- **Static-looking suffix**: a static-looking suffix the key's allowlist omits changes storage eligibility for a dynamic response, which is the same rule read at the eligibility side.
- **Forced miss**: where the key's rule matches the path exactly, add a field the key treats as a distinct input to force a miss, so the shaped response is fetched and stored rather than served from an existing entry.
- **Completed probe**: treat a collapse that serves another caller as the completed probe, and record the normalisation step that caused it.
- **Key-shaping matrix**: see `references/cache-key-shaping-matrix.md` for the key-shaping shapes and their completion bars.

### Stored-Response Reads Across Callers

- **Second-caller read**: read a stored entry as a second caller where the key omits the identity binding, because a stored response outlives the session that produced it.
- **Second session**: hold a second session and request the entry with the key the first caller named.
- **Lifetime record**: record the entry's lifetime and age fields, because the storage window bounds the reach and is the report's exposure evidence.
- **Private entry**: treat an entry reachable only by the producing caller as a private entry rather than a deception.

## Bypass Techniques

- **Bypass scope**: relay shapes are tried only after the direct route is baselined, because a cache that never stored carried nothing.
- **Unkeyed selector**: a selector that shapes the body while the key omits it.
- **Normalisation collapse**: separators, casing, and fragmentation markers the key's normalisation collapses.
- **Address tails**: address tails and suffixes that change an entry's storage eligibility or reach.
- **Key-variation fields**: key-variation and accept fields that select between stored entries.
- **Forced miss**: a field the key treats as a distinct input, added to force a miss so the shaped response is fetched and stored.
- **Stored class**: a stored failure or permission class the key did not separate from the healthy or permitted case.
- **Declaration gap**: a key-coverage declaration that omits a selector the response varies with, read as the control to defeat.
- **Second caller**: a second caller or session reading an entry produced for another.

## Chaining Attacks

- **Chain scope**: cache deception chains forward into the class that owns the effect, because a stored entry is only the first hop.
- **Effect hand-off**: hand the stored body to the class that owns the effect, and prove the class-specific consequence for a later caller there.
- **Disclosure stack**: chain into the stored-response disclosure class where the entry carries content from another caller.
- **Tier-gap stack**: chain into the tier gap where the cache also stores a verdict rather than a response body.
- **Own-step naming**: name the class at its own step rather than restating its procedure here.

## Testing Methodology

Cache deception reads the key first and stores second, because the omission is a property of the key.

1. **Locate the cache** - the shared cache on the path and the fields that decide storage, and the step completes when the cache and its storage rule are both named.
2. **Enumerate the selectors** - every input that shapes the body with the key's coverage of each, and the step completes when the uncovered selector is named.
3. **Baseline a non-stored request** - send a request the cache does not store, and the step completes when the absence of a stored entry is recorded with the test that showed it.
4. **Store the shaped body** - send the shaping input and read the entry back, and the step completes when the stored body carries the shaping input's effect.
5. **Read as a second caller** - request the entry from a second caller or session, and the step completes when the second read returns the stored body.
6. **Attribute the reach** - pair the first caller's shaping request with the second caller's read, and the step completes when the omitted selector or binding is named from the pair.

## False Positives

- **Stop condition**: stop when the entry reached only the caller that produced it, because a private entry is not a deception.
- **Full key coverage**: a cache whose key covers every selector that shapes the body, confirmed by distinct entries per selector.
- **Producing caller only**: an entry reachable only by the producing caller or session.
- **Tester's own key**: a cache that stored the tester's own session entry under a key that names the tester.
- **Regenerated response**: a response that looks stored but is regenerated per request, confirmed by a changing body.
- **Simulator**: a simulator that answers the entry itself without a real cache in the path.

## Pro Tips

- **Discipline**: cache deception rewards key reading plus a second-caller read.
- **Key coverage first**: read the key's coverage before crafting, because the mechanism is an omission in the key.
- **One selector per attempt**: vary one selector per attempt so the omission is nameable.
- **Second-caller read**: read every entry back as a second caller, since the first caller's read proves nothing.
- **Separate rules**: treat storage eligibility and key identity as separate rules, because a suffix can change one without the other.
- **Effect hand-off**: hand the stored body to the class that owns the effect, and stop at the narrowest proof.

## Summary

A shared cache serves one stored response to every caller that names its key. Cache deception shapes a selector the key omits, stores a body for later callers, and claims the reach only when a second caller reads the entry.
