---
name: cache-poisoning
description: Web cache poisoning testing for a shared cache that stores a response shaped by an input its key omits, covering unkeyed input discovery when a selector changes the body but not the key, stored header and error classes when the entry serves a verdict or a failure to later callers, and mass delivery when one stored response reaches every caller without victim interaction.
metadata:
  version: 1.0.0
---

# Cache Poisoning

A shared cache stores one response under one key and serves it to every caller that names the key.
This class owns the poisoning direction: an input that shapes the body while the key omits it stores a response the origin never produced for the later callers who receive it, and the delivery is mass rather than single-caller.
The cache-key mechanics stay with `proxy-techniques-cache-deception`, the control that declares key coverage is read as a permit, and the effect the stored body produces belongs to the class that owns it.

## Attack Surface

- **Applicability**: a shared cache in front of a response whose body varies with an input the cache does not key on.
- **Unkeyed inputs**: request fields, query members, and cookies that shape the body while the key omits them.
- **Storage eligibility**: the fields and path shapes that decide whether a response is stored at all, including suffixes and extensions that change eligibility for a dynamic response.
- **Key declaration**: the response fields that declare which request fields the key covers, read as the cache's own statement of coverage.
- **Delegated mechanics**: key normalisation, fragmentation, and delimiter discrepancies belong to `proxy-techniques-cache-deception`, and this class names that skill at the key step.

## Reconnaissance

### Cache Identification

- **Status fields**: read the response fields that name the cache and the entry's age, so the stored path is distinguishable from the origin's answer.
- **Key probing**: send one request twice and compare the cache fields, because a stored second answer proves the cache is active on the path.
- **Storage rule**: record which path shapes and fields decide storage, because eligibility and key coverage are different rules.
- **Declaration reading**: read the key-coverage declaration on the response, and record a missing declaration with the test that showed it.

### Unkeyed Input Discovery

- **Selector sweep**: vary one request field per attempt under a throwaway key and read whether the body changes, because a body change under an unchanged key is the unkeyed input.
- **Reflection check**: confirm the shaped value appears in the response before storing anything under the live key, because an unreflected input carries nothing.
- **Cookie and parameter cases**: treat cookies and query members as selectors beside request fields, because each is keyed or omitted on its own.
- **Throwaway discipline**: land every probe on a fresh throwaway key first, so a live entry is never shaped before the mechanism is proven.

## Detection Channels

- **Later-caller delivery**: a stored response served to a caller who never sent the shaping input, which is the primary poisoning signal.
- **Cache-status transition**: the entry moving from a fresh answer to a stored one after the shaped request, which proves the shaped body was stored.
- **Paired baseline**: the keyed baseline beside the shaped entry for one path, which localises the omitted selector.
- **Stored verdict class**: an entry that carries a permission field produced for a shaping value and is served to later callers, which proves a header class was stored.
- **Stored failure class**: an error-class response stored under a healthy request's key, which proves the failure was cached.
- **Storage window**: the entry's age and lifetime fields, which bound the exposure window and the affected caller set.
- **Negative across selectors**: a body that holds across every varied field, which reads as a key that covers its selectors.

## Adversarial Capabilities

- **Unkeyed input shaping**: the ability to vary request fields, members, and cookies one at a time.
- **A throwaway key**: a fresh key under which probes can be landed without touching the live entry.
- **A second caller**: a second identity or session that reads the entry back, because the first caller's own read proves nothing about delivery.
- **A storage window read**: the entry's lifetime, so the exposure is bounded by evidence rather than by assumption.
- **A repeated store**: the ability to re-send the shaped request as the entry expires, because a persistent poison needs a refreshed store.

## Trust Assumptions

- **The agreement**: the cache trusts that its key covers everything that varies the response, and the origin trusts that a response it produced for one request is served only to callers that made an equivalent request.
- **The failing clause**: this class breaks the key-coverage clause because a selector that shapes the body is absent from the key, so one stored response reaches callers it was never produced for.
- **Claim discipline**: the delivery is claimed only when a second caller receives the stored body, because the shaping caller's own read cannot separate storage from a live answer.

## Key Vulnerabilities

### Unkeyed Input to a Keyed Response

- **Selector omission**: a request field, a query member, or a cookie changes the body while the key ignores it, so the shaped response is stored for every later caller.
- **Key coverage first**: read the coverage declaration and the storage rule before shaping anything, because the omission is a property of the key.
- **Delegation**: key normalisation, fragmentation, and delimiter discrepancies are `proxy-techniques-cache-deception` steps, and the key's declaration is a permit the `defence-bypass` family reads.

### Stored Header and Error Classes

- **Permission-field storage**: a response that carries a permission field produced for the shaping value is stored, so later callers receive a verdict the origin never made for them.
- **Failure storage**: an error-class response produced from attacker input is stored under a healthy request's key, so later callers reach a failed response for a working operation.
- **Class breadth**: any response class the cache stores can be shaped, so the probe set covers successes, failures, and permission fields rather than the body alone.

### Mass Delivery

- **Every later caller**: the stored body is served to every caller that names the key, with no victim interaction beyond an ordinary request.
- **Exposure window**: the entry's lifetime bounds the affected caller set, and a refreshed store extends it.
- **Ownership**: the delivery step is this class's bent step, and the key mechanics that enable it stay with `proxy-techniques-cache-deception`.

## Advanced Techniques

- **Throwaway-key isolation**: prove reflection and storage under a fresh key first, and store under the live key only after the mechanism holds.
- **Forced miss**: add a field the key treats as a distinct input to force a miss, so a shaped response is fetched and stored rather than served from an existing entry.
- **Re-store for persistence**: re-send the shaped request as the entry expires, because a poison that is not refreshed is bounded by one lifetime.
- **Window measurement**: record the entry's age and lifetime, because the window is the delivery evidence and the report's exposure bound.
- **Paired routes**: compare the shaped entry against the keyed baseline for one path, so the omitted selector is nameable.

## Bypass Techniques

Bypass shapes are tried only after the entry's key coverage is read, because a selector the key covers stores nothing.

- **Unkeyed selector**: a request field, member, or cookie that shapes the body while the key omits it.
- **Declaration gap**: a key-coverage declaration that omits a selector the response actually varies with.
- **Storage-eligibility suffix**: a path shape that changes whether a dynamic response is stored at all.
- **Forced miss**: a field that makes the shaped request miss the existing entry, so the shaped response is fetched and stored.
- **Parameter and body duplication**: a duplicate member or a body carried on a read-only verb that the parser reads and the key omits.
- **Normalisation collapse**: separators, casing, and fragmentation the key's normalisation collapses, named with `proxy-techniques-cache-deception` at the key step.

When this section does not fulfil the knowledge gap, extend the reading with the defence-bypass and proxy-techniques families.

## Chaining Attacks

A stored entry is a mechanism rather than a finding, so the delivered body hands forward to the class that owns its effect.

- **Executable delivery**: `xss` where the stored body carries executable markup, because the cache delivers it to every later caller.
- **Disclosure direction**: `information-disclosure` and its `differential-oracle-disclosure` leaf where the entry carries content produced for another caller.
- **Destination layer**: `open-redirect` where the stored body carries a destination the origin built from the shaping value.
- **Availability**: the error-class store is a denial-of-service surface when later callers reach a failed response for a working operation.
- **Key mechanics**: `proxy-techniques-cache-deception` for the key's coverage, normalisation, and eligibility, and the `defence-bypass` family at the permit step.

## Testing Methodology

Cache poisoning reads the key first and stores second, because the omission is a property of the key rather than of the request.

1. **Identify the cache** - the shared cache on the path with its status and age fields, and the step completes when a second identical request proves a stored answer.
2. **Read the storage rule** - the path shapes and fields that decide storage, and the step completes when eligibility and key coverage are recorded as separate rules.
3. **Baseline a non-stored request** - a request the cache does not store, and the step completes when the absence of an entry is recorded with the test that showed it.
4. **Sweep the selectors** - one request field, member, or cookie per attempt under a throwaway key, and the step completes when each selector carries a reflected or ignored verdict.
5. **Confirm reflection and storage** - the shaped value appearing in the stored body under the throwaway key, and the step completes when storage is proven rather than inferred.
6. **Store and deliver** - the shaped request against the live key, then a second caller's read, and the step completes when the second caller receives the shaped body.
7. **Bound the window** - the entry's age and lifetime with the affected caller set, and the step completes when the exposure is bounded by the recorded lifetime.
8. **Attribute and stop** - separate the stored delivery from a live origin answer and from a private entry, and the step completes when the narrowest proof carries its attribution.

## False Positives

Stop when the entry reached only the caller that produced it or the body was regenerated, because neither is a poisoning delivery.

- **Key covers every selector**: a distinct entry per varied field, confirmed across the selector sweep.
- **Unreflected input**: a selector that changes storage but never appears in the body.
- **Regenerated response**: a body that changes per request despite the status fields, confirmed by a changing body.
- **Private entry**: an entry reachable only by the producing caller, session, or key.
- **Tester's own key**: a stored entry under a key that names the tester rather than a shared key.
- **Simulator or replay**: a cache-shaped answer produced by the tester's own tooling without a real cache in the path.

## Pro Tips

Cache poisoning rewards key reading plus a throwaway-key discipline plus a second-caller read.

1. Read the key's coverage before crafting, because the mechanism is an omission in the key.
2. Land every probe on a throwaway key first, since a live entry shaped early is a production incident rather than a test.
3. Vary one selector per attempt so the omitted input is nameable.
4. Read every entry back as a second caller, because the producing caller's read proves nothing about delivery.
5. Record the entry's lifetime, since the window is both the exposure bound and the re-store cadence.
6. Name the owning skill at each delegated step, and stop at the narrowest proof.

## Summary

A shared cache serves one stored response to every caller that names its key, and a selector the key omits stores a body for callers it was never produced for. Cache poisoning reads the key's coverage, proves reflection and storage under a throwaway key, and claims the delivery only when a second caller receives the stored body.
