---
name: http-method-tampering
description: Bypassing authorization and authentication controls by manipulating HTTP methods, override headers, and verb-specific logic
metadata:
  version: 1.0.0
---

# HTTP Method Tampering

Authorization controls are sometimes tied to the HTTP method rather than the resource. Switching from one verb to a sibling, using method override headers, or sending unexpected verbs can bypass access controls, cross-origin protections, and authentication checks.

## Attack Surface

- Handlers registered per verb, where a guard decorates one registration and not its siblings
- Override carriers honored by frameworks: override headers, form fields, and query markers
- Gate layers that decide on one method view and executor layers that perform another
- Informational and debugging verbs answered outside the normal handler chain
- Shape-sensitive policies that treat preflighted and simple requests differently
- Cacheable read paths reachable through a state-changing verb

## Reconnaissance

### Verb Coverage

- Enumerate the verbs each route answers; the allowed-method list in an options response is the fastest inventory
- For every guarded route, note which verb carries the guard and which sibling verbs reach the same handler or a near copy
- Record status, body length, and redirect target per verb so later differentials have a baseline

### Override Support

- Probe override headers and body or query markers on a harmless state-changing route and watch whether the routed method changes
- Test each carrier independently, then in combination, so precedence stays attributable
- Confirm whether the override is consulted before or after the authorization check by comparing a guarded and an open route

### Layer Views

- Compare the method the edge sees with the method the application executes, through logging endpoints, reflected values, or explicit error text
- Note whether the edge normalizes casing, whitespace, or unknown verbs before forwarding

## Detection Channels

- Status plus length divergence across sibling verbs on one route signals a dispatch gap.
- Guarded data returned, or a state change applied, on a sibling verb whose guard is absent.
- Redirect-target divergence across verbs signals a per-verb handler split.
- Disclosed allowed-method list confirms the disclosure channel.
- Header-only success diverging from the guarded read confirms the metadata-extraction channel.
- Reflection containing session or credential material confirms the echo-capture channel.
- Gate-view versus executor-view divergence signals reinterpretation acceptance.
- A state-change effect or guarded-data return under an override carrier confirms backend execution of the reinterpreted verb.
- Absence of effect under every carrier signals the backend ignores reinterpretation.
- A blocked preflighted shape paired with an executed simple shape signals shape-dependent divergence.
- Gate decisions observed across the shape pair confirm the policy split.

## Adversarial Capabilities

Method testing presupposes a session at one privilege level, a route inventory, and control over the verb and its carriers, and it consumes all three.
- Hold a low-privilege session so a guarded success is attributable to the verb rather than to the role.
- Send any verb, plus override carriers, to any route on the inventory.
- Send both preflighted and simple request shapes for the same intended effect.
- Read status, length, redirect target, and header-only responses per attempt.
- Reach the target through the edge and, where possible, directly, to compare gates.

## Trust Assumptions

The class rests on one agreement: the layer that authorizes and the layer that executes agree on which action is being performed.
The agreement holds the verb that reaches the handler to the verb the gate evaluated, holds the guard attached to one verb to every sibling verb that reaches the same handler, holds the request shape to the policy the gate applied, and holds informational verbs to metadata only.
Sensitive position leaks when the two layers disagree: the gate reads a safe verb or a safe shape while the executor performs the guarded action.
Each variant breaks one clause: the dispatch clause, the reinterpretation clause, the shape clause, or the informational-verb clause.

## Key Vulnerabilities

### Verb Dispatch Gaps

- Per-verb guards: a privileged action registered for one verb, with a sibling registration that lacks the guard
- State-changing reads: a read verb whose handler mutates state or triggers an action through a callback path
- Redirect and error divergence: sibling verbs reaching different handlers, one guarded and one open

### Override Reinterpretation

- Frameworks honoring override headers or body markers after the gate has authorized the transport verb
- Override accepted only during normalization, so the gate sees the transport verb and the backend performs the override
- Multiple carriers honored with a precedence order the gate does not follow

### Informational Verb Exposure

- The options response discloses the allowed-method list, which maps guarded routes without authentication
- Header-only verbs reach metadata and guard decisions that the full read denies
- Echo verbs return the request as received, including credentials and session material

### Shape-Sensitive Gate Splits

- Cross-origin policy applied only to preflighted shapes, leaving simple shapes to execute the same effect
- Content-type coercion that makes a structured body arrive as a simple one
- Layers treating a request as simple while the application parses it as structured

## Advanced Techniques

### Layer Divergence Chains

- The edge normalizes one verb while the backend accepts another, so the gate verdict and the executed action separate
- Rewrite carriers applied after the authorization check move the request onto an unguarded path

### Verb-Specific Side Effects

- Read verbs that trigger side effects through background callbacks or link unfurling
- Verbs whose handlers share a code path with a guarded verb but register no guard of their own

### Carrier Precedence

- Each override carrier satisfies a different layer; combining carriers reaches the handler with a verb no single layer authorized

## Bypass Techniques

- Case variation, extra whitespace, or an unknown verb token that a normalizing layer accepts and forwards as a known verb
- Duplicate verb-carrying inputs so the gate and the executor read different positions
- Carry the override in the body or query when the header path is filtered
- Reach the route over a protocol version or request form whose parse path skips the gate
- Request the guarded path directly where the edge block hides a live core route
- Name the defence-bypass family at its signature, parser, and edge-versus-core steps for the verb-token, duplicate-input, parse-path, and core-route shapes, rather than restating those mechanics here.

When this section does not fulfil the knowledge gap, extend the reading with the defence-bypass and proxy-techniques families.

## Chaining Attacks

- Method tampering plus function-level authorization: the sibling verb reaches the privileged action
- Method tampering plus cross-site delivery: a state-changing read verb turns a navigation into an effect
- Method tampering plus caching: a cacheable read path stores a state-changing response for other users
- Method tampering plus disclosure: the allowed-method list maps guarded routes for later steps

## Testing Methodology

1. **Inventory routes and verbs** - Map each route to the verbs it answers, using the options response as a first pass; the step completes when every route carries a verb list
2. **Record baselines** - Per route, record status, body length, and redirect target for every verb; the step completes when each verb carries a baseline
3. **Sweep guarded routes with a low-privilege session** - Exercise each verb, including siblings of the guarded one; the step completes when each route carries a guard-versus-success verdict
4. **Probe override carriers** - Test each carrier independently and combined on one harmless route; the step completes when the carrier list and its precedence are recorded
5. **Test informational verbs** - Request allowed-method lists, header-only responses, and echo behaviour where enabled; the step completes when each carries a disclosure verdict
6. **Test shape splits** - Send the same intended effect as preflighted and simple shapes; the step completes when the policy split is recorded
7. **Confirm effects** - Snapshot state before and after each promising replay; the step completes when every claim has a durable-effect snapshot

## Variants

- http-method-tampering-verb-switch - Switch request verbs across application-decision methods where one verb is guarded and a sibling verb executes the action.
- http-method-tampering-override-smuggling - Smuggle overridden verbs through gate-visible safe methods where the gate authorizes one method and the backend executes another.
- http-method-tampering-informational-verb - Exploit informational verbs beyond transport reads where header-only responses leak guarded metadata or echo material replays as credentials.
- http-method-tampering-preflight-coercion - Coerce state-changing requests into simple shapes where a preflighted shape is blocked and the simple shape executes.

## False Positives

- Routes that legitimately answer several verbs with the same authorization applied on every path
- Header-only responses answered by the framework or an edge layer without reaching the guarded handler
- Allowed-method lists served only to authenticated callers
- Override carriers honored after the authorization check, where the transport verb remains the authorized one
- Differences that are pure transport behaviour, such as redirect handling, with no guard divergence

## Pro Tips

1. Sweep every verb on every route, not only the obvious ones; guards are attached per registration
2. Compare status, length, and redirect target across verbs; the dispatch gap usually shows as a divergence in one of the three
3. Override carriers are widely supported; test them where method-based guards are likely
4. Path-pattern authorization means a rewrite or an alias can move the request onto an unguarded route
5. Header-only verbs are often forgotten in access control logic
6. State-changing read handlers are common in legacy surfaces and sidestep cross-site protections
7. Confirm each promised bypass with a durable-effect snapshot before filing

## Summary

Authorization must bind the actor to the action the handler actually performs, on every verb and every request shape that reaches it. When the gate and the executor read different method views, the guard applies to a request nobody sent.
