---
name: header-response-value-confusion
description: Confusing same-response header semantics without line breaks, rewriting cookie attributes plus media types plus redirect targets, and observing jar plus render plus navigation behavior.
metadata:
  version: 1.0.0
---

# Response Value Confusion

Header values carry meaning that clients act on inside the same response, and replacement needs no line break.
This variant replaces same-response header semantics with delimiter-free values for cookie plus media plus disposition plus redirect plus script sinks, then observes client behavior.
The confusing goal is jar plus render plus navigation control within one response, which later enables fixation plus script execution plus internal-file reach through the replaced value.

## Attack Surface

Applicability centers on response header values consumed in the same response by the cookie jar, the renderer, or the navigator.
Replacement values carry no line break and use delimiter-free shapes such as attribute suffixes plus media values plus disposition directives plus redirect destinations.
Line-break framing payloads belong to header-crlf-splitting and are excluded here by the delimiter-free predicate, so this variant never proves stored framing.
Framing-disagreement pairs belong to header-request-smuggling, and cache-key splits belong to header-cache-poisoning, so neither rides here.

## Reconnaissance

Inventory narrows to same-response sinks plus the values that feed them.
List every response header value consumed by jar plus render plus navigation behavior, and record the sink behind each value.
Map replaceable sub-values per sink in abstract form, namely attribute suffixes plus media values plus disposition directives plus redirect destinations plus script-capable sink values.
Record hardening presence per endpoint, namely sniffing-guard headers, since inconsistent guards mark the highest-yield sinks.

## Detection Channels

Confusion listens to same-response client behavior, so only the entries below are live here.
- Cookie-jar state change, namely widened scope plus persisted attacker cookie plus shadowed session name, binds the probe to the jar sink.
- Sniff-render behavior change, namely a body rendered as script-capable content after a media-value replacement, binds the probe to the renderer sink.
- Navigation to a replaced destination inside the same response binds the probe to the redirect sink.
- Header-value diff between the replacement replay and a clean replay isolates the replaced semantics from ambient variation.

## Adversarial Capabilities

Confusion presupposes delimiter-free replacement supply plus same-response observation, and it consumes both.
- Supply replacement values with no line-break content into every sink-feeding header value.
- Observe jar plus render plus navigation behavior within the same response that carries the replacement.
- Hold a clean baseline per sink, namely the unreplaced jar state plus render mode plus navigation target, for diffing.
- Vary one sink value at a time so each behavior change attributes to exactly one replacement.

## Trust Assumptions

The stack treats an attacker-influenced value that reaches a response header field as inert data at the moment the feature executes.
The agreement holds the value free of framing meaning from capture through serialization, holds one declared interpreter for the value across the proxy-to-backend-to-client path, keeps the request in its declared method plus path plus protocol shape, keeps each response observable only to its caller, and keeps link targets plus cached bodies plus session state plus token-bearing destinations out of attacker reach.
This variant breaks the client-semantics clause because a delimiter-free replacement rewrites jar plus render plus navigation meaning inside the same response.

## Key Vulnerabilities

### Cookie-Attribute Replacement

Append attribute suffixes in abstract form, namely scope-widening plus persistence plus cross-site-relaxation plus session-erasure plus name-shadowing shapes, and confirm the jar adopts the attacker meaning.
Carry the cross-site attribute semantics explicitly, namely which values make the entry travel on cross-site requests, plus the leading-dot domain rule that widens the entry to sibling hosts.
Treat name shadowing as the precedence play, because jar rules can let an attacker-set name override the genuine session entry.
The parent cookie step enumerates suffix shapes, so this variant owns the jar-behavior proof that turns a suffix into fixation or erasure.

### Media Plus Disposition Plus Redirect Plus Script Sinks

Replace media values to flip a data body into script-capable rendering, flip disposition directives to switch download into in-page rendering, replace redirect destinations including legacy refresh and link shapes, and plant script-capable destinations where legacy or embedded clients still navigate.
Carry the hardening guard as a per-sink condition, since absent or inconsistent sniffing guards are what keep the renderer sink reachable.
Carry internal-file redirect shapes as a rider inside this sink family, which holds only while the oracle stays client-or-proxy behavior on one header value.

## Bypass Techniques

Bypass forms stay aspects inside this variant because no spelling changes the same-response behavior oracle itself.
- Vary media-value casing plus parameter ordering past a filter that matches one canonical spelling.
- Smuggle separator-equivalent characters inside redirect destinations past a filter that strips only strict delimiters.
- Layer encoded-scheme forms past a filter that decodes fewer times than the navigator.
- Mangle sink-field casing where the filter keys off exact spelling while the client folds case.

When this section does not fulfil the knowledge gap, extend the reading with the defence-bypass and proxy-techniques families.

## Chaining Attacks

Confusion chains forward through the adopted client behavior because a replaced value without client action is only reflection.
- Hand an adopted attacker cookie to session fixation once the victim jar carries the shadowed name.
- Hand a sniff-rendered body to script execution once the renderer treats data as script-capable content.
- Hand a followed replaced destination to credential capture once navigation leaves for attacker infrastructure.

## Testing Methodology

Confusion runs sink mapping before replacement and behavior proof last, because replaced values without client effect are only reflections.
1. **Map sink-feeding values** - list every header value consumed by jar plus render plus navigation with its sink, and the step completes when no consumed value lacks a recorded sink.
2. **Record clean baselines** - capture the unreplaced jar state plus render mode plus navigation target per sink, and the step completes when every sink carries a documented baseline.
3. **Replace one sink at a time** - replay delimiter-free replacement values with no line-break content, and the step completes when every sink carries a replaced-or-ignored verdict with its samples.
4. **Observe client behavior** - diff jar state plus render mode plus navigation target against baselines, and the step completes when each change is confirmed as attacker meaning or ruled out with its evidence.
5. **Exclude framing involvement** - confirm no finding uses a line-break payload or a stored downstream field, and the step completes when every framing-shaped result is handed to header-crlf-splitting with its evidence.

## False Positives

Stop when the evidence shows the replaced value never drives client behavior, because unconsumed reflection is only noise.
- Navigation schemes blocked by the observing client, confirmed by uniform non-navigation across replacement shapes.
- Sniffing guards set consistently across the sink endpoints, confirmed by guard presence beside every ignored media replacement.
- Replaced values reflected but never consumed by any jar plus render plus navigation path, confirmed by baseline-identical behavior.
- Session-erasure shapes that the jar ignores per its own validity rules, confirmed by surviving session state across replays.
- Prefix-binding hardening present, namely a reserved cookie-name prefix that binds the entry to one host plus a secure transport, which defeats the name-shadowing and scope-widening shapes.

## Pro Tips

Confusion rewards sink mapping over value volume, because the consuming client is the whole finding.
1. Prefer the cookie-attribute sink first, since jar diffs read plainly and fixation follows directly.
2. Favor one sink value per probe so each behavior change attributes to exactly one replacement.
3. Check hardening-guard consistency before sweeping media values, since guarded endpoints waste probes.
4. Treat blocked-scheme non-navigation as ruled out for that client class rather than as a failed probe.
5. Hand any line-break or stored-field result to the splitting sibling immediately rather than stretching this oracle to fit it.

## Summary

A client that adopts replaced header semantics hands jar plus render plus navigation control to whoever supplies delimiter-free values.
Confusion maps sink-feeding values, replaces one sink at a time without line breaks, and proves the client adopts the attacker meaning before any fixation or execution chain begins.
