---
name: scheme-translated-command-execution
description: Translate SSRF fetches into raw-protocol commands through non-HTTP scheme handlers, read local files through wrapper schemes, and probe key-value handlers under a direct response oracle.
metadata:
  version: 1.0.0
---

# Scheme-Translated Command Execution

Server-side fetchers sometimes translate a destination scheme into a raw protocol conversation instead of a plain web fetch.
This variant translates that translation into impact by crafting protocol grammar plus wrapper reads inside the destination itself.
The translation goal is command execution against internal text-protocol services plus local file disclosure, all confirmed through a direct response oracle.

## Attack Surface

Applicability centers on a server-side fetch sink whose fetcher supports at least one non-HTTP scheme handler.
The sink accepts attacker-influenced destination input with enough expressive room to carry grammar text past the scheme separator.
The handler translates the destination remainder into a raw conversation with an internal service, or into local-file semantics, or into a key-value lookup.
The response oracle stays direct, meaning the handler outcome returns visibly in the body or in a distinguishable error.
Blind translated craft adds no step beyond inference plus the craft below, so it rides as a secondary inside the inference variant.

## Detection Channels

Translation listens to handler outcomes rather than side channels, so only the entries below are live here.
- Direct response body echoes the handler outcome, such as returned file content or a service banner or an error text.
- Error-class difference separates a reachable handler from an absent one.
- Downstream state change confirms execution, such as a scheduled entry firing or a written record appearing.
- Timing gap on the command path separates a processed grammar from a refused destination.

## Adversarial Capabilities

Translation presupposes destination supply plus handler selection plus grammar shaping, and it consumes all three.
- Supply destination input that selects the handler by scheme and carries grammar text past the separator.
- Shape multi-line protocol grammar that the handler relays faithfully to the internal service.
- Distinguish local-file wrapper semantics from network-fetch semantics when choosing the scheme.
- Confirm outcomes through the direct response oracle rather than through statistical differencing.
- Hold callback infrastructure only as a secondary confirmation for fire-and-forget grammar.

## Trust Assumptions

The fetcher trusts a user-supplied destination to select only locations the server is permitted to reach.
The agreement holds the destination stable from allowlist check through fetch, keeps the response observable to the caller, keeps the request in plain-fetch shape with no translated protocol grammar, and keeps the request in plain-fetch shape with no gate-passing header or method pair.
Sensitive network position plus stored file content leak only when the server exposes them through such a fetch.
This variant breaks the plain-protocol clause because the scheme selects a non-HTTP handler that translates the destination into raw protocol grammar, so a fetch becomes a command.

## Key Vulnerabilities

### Raw-Protocol Grammar Crafting

Craft the destination remainder as the exact line sequence the internal text-protocol service expects, including command verbs plus argument lines plus terminators.
Keep the grammar inside destination-shaped placeholders so the fetcher still treats the whole value as one destination.
The parent protocol step covers only handler variation and cannot describe line-level grammar construction, so this variant owns the crafting procedure.

### Wrapper-Aware File Reads

Select a local-file wrapper scheme where the fetcher enables one, because wrapper semantics read server files rather than network locations.
Aim first at identity-revealing files that confirm the read with minimal sensitivity, then stop rather than widening into bulk disclosure.
Wrapper reads diverge from network fetches in error shape, so confirm each read through the direct body rather than through timing.

### Key-Value Handler Probing

Probe dictionary-style handlers with minimal lookup verbs to confirm handler presence before sending heavier grammar.
Record handler presence versus absence per scheme, because absent handlers close this variant entirely.
Carry blind translated replay as a secondary inside the inference variant, since blind craft adds no step beyond the craft above plus that oracle.

## Bypass Techniques

Bypass forms stay aspects inside this variant because no encoding difference changes the grammar-crafting step itself.
- Address encoding families such as decimal plus hex plus octal plus mapped forms steer the translated destination past a naive textual allowlist.
- Parser differentials between the enforcing side and the fetching side smuggle the translated scheme through a split parse.
- Redirect chains convert one allowlisted first hop into a translated second hop where the client follows scheme switches.
- Short-lived attacker-controlled resolution answers differently across the check-time and fetch-time lookups.

## Chaining Attacks

Translation chains forward into execution because a crafted grammar without a state change is only a probe.
- Pivot from a reachable in-memory store to a scheduled task entry, then to command execution.
- Pivot from a reachable gateway interface to a constructed request record, then to process creation.
- Pivot from a reachable container or orchestration endpoint to token or secret discovery, then to lateral movement.
- Hand a translated read that stays blind to the inference variant for oracle confirmation.

## Testing Methodology

Translation runs the direct oracle first and crafts grammar second, because grammar without a visible outcome cannot be confirmed.
1. **Inventory sinks** - list every attacker-influenced destination sink with its carrier plus its supported schemes, and the step completes when no unlisted sink or scheme remains.
2. **Establish the direct oracle** - confirm the handler outcome returns visibly in the body or in a distinguishable error, and the step completes when a benign translated destination shows a recorded positive and an absent handler shows a recorded negative.
3. **Confirm handler presence** - probe each candidate scheme with a minimal benign grammar, and the step completes when every scheme carries a present or absent verdict.
4. **Craft protocol grammar** - shape the destination remainder as the exact line sequence the service expects, and the step completes when each grammar shows a handler-acknowledged outcome or a recorded refusal.
5. **Read through wrappers** - select the local-file wrapper scheme and confirm with a minimal identity-revealing read, and the step completes when the read shows file content or a recorded denial.
6. **Confirm state change** - observe the scheduled entry firing or the written record appearing, and the step completes when each executed grammar shows its downstream effect or a recorded absence.

## False Positives

Stop when the handler never translates, because a plain fetch without translation is not this variant.
- Client-side fetch only, where no request ever leaves the server.
- Handler absent for every candidate scheme, confirmed by uniform negatives across all grammars.
- Canned simulator responses that return fixed bodies without real handler dispatch.
- Strict scheme allowlist with no redirect following, confirmed by uniform refusals of every translated destination.
- Callback hits whose source matches the tester machine rather than the server, which indicate a client-side fetch made the request.

## Pro Tips

Translation rewards minimal grammar plus direct confirmation plus quick chaining.
1. Confirm handler presence with the smallest benign grammar before crafting anything heavier.
2. Keep each grammar minimal and observe the direct outcome before extending it.
3. Read wrapper files narrowly and stop at the first confirming read.
4. Chain each confirmed execution quickly to durable impact such as a harmless internal read, then stop there.
5. Record absent handlers explicitly so later runs skip them without re-probing.

## Summary

A fetcher that translates schemes lets a destination become a raw protocol conversation or a local file read.
Translation confirms handler presence, crafts exact grammar inside destination-shaped placeholders, and verifies each outcome through the direct oracle.
