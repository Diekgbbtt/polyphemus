---
name: bfla-alternate-path
description: Alternate privileged-path testing that replays actions through shadow routes and permissive parser chains. Use when an alias or legacy route may skip the current middleware, when one content-type handler may enforce less than its siblings, when an edge block may hide a live core path.
metadata:
  version: 1.0.0
---

# BFLA Alternate Path

Action-level authorization fails open when the check lives on one path while the same privileged action stays reachable through another.
The leading word is alternate: every probe replays one privileged action through a different route, method framing, parser chain, or core reach and reads the verdict beside its proper-path control.

## Attack Surface

Alternate applies where one privileged action is reachable through more than one route, method framing, parser handler, or service entry point.
The alternate may be a legacy or versioned route, a method alias or override framing, a sibling content-type handler with its own middleware, or a core service entry reachable around an edge gate.
Version forms count as alternates too: an old or deprecated version of one action frequently keeps the weaker middleware the current version dropped.
Where the stack carries proxy path-override headers, the edge can rewrite the route before the application sees it, which makes the override a candidate alternate rather than a separate class.
Trust direction and impact severity change reporting only, so escalation, state-change, and configuration effects share this one procedure.
Parser encoding labels alone never define the attempt; only a middleware gap between handler chains brings a case into this variant.

## Reconnaissance

Map every route and framing that reaches each privileged action before replaying anything.
Collect interface documents, client bundles, prior HTTP history, and gateway routing notes until each action owns a list of candidate aliases, legacy versions, and method framings.
Inventory the version surface explicitly, then behaviourally diff each old version against the current one on authorization, validation, and rate-limit strength, because a regression shows only in the diff.
Diff the middleware chain per route and per parser handler until the permissive chains are named.
Confirm the proper-role baseline succeeds on the primary path before judging any alternate attempt.

## Detection Channels

Denial on the primary path beside success on the alternate decides the finding.
A privileged effect observed after an alias, shadow-route, or parser-path replay confirms the gap even when the status line looks normal.
Status and effect differentials across transports or encodings for the same action confirm inconsistent enforcement.
A before-and-after state snapshot showing the privileged change completes the proof.

## Adversarial Capabilities

This variant presupposes a working lower-role session plus knowledge of one privileged action, and it consumes direct-call ability outside the interface.
It consumes the ability to resubmit one action body through changed routes, method framings, and content-type handlers while holding the token constant.
It consumes the ability to route around edge gates toward the core entry where the engagement permits it.
Steps owned by the defence-bypass family at its edge-versus-core step are named here rather than restated.

## Trust Assumptions

The privileged function executes under the agreement that every route and handler reaching it enforces the same caller-to-action binding, that edge and interface gates transfer no authority downstream, that actor identity comes only from verified token claims rather than request hints, and that an approval recorded in a prior step never authorizes a later execution, so no lower-privileged caller causes a privileged effect and no privileged state leaks to an unentitled observer.
The agreement fails when the check lives only on the primary route or edge gate while an alias, shadow route, parser-specific handler, or direct core reach executes the same action unchecked.

## Key Vulnerabilities

Middleware-stack diffing plus alias, shadow-route, parser-specific, and direct-to-core resubmission is the bent step this variant owns over the parent.
Resubmit each privileged action through every alias and legacy route with the same body, and record which chain authorized the call.
Resubmit the action through every path-normalisation form (case variation, dot segments, encoded separators, delimiter insertion, trailing dot or extension, double encoding), because each form may reach a different route entry than the primary spelling.
Diff each version of the action behaviourally against the current one on authorization, validation, and rate-limit strength, since a regression surfaces only in the comparison rather than in a single version.
Resubmit through each sibling parser handler, since one permissive chain among strict siblings is the gap this variant hunts.
Resubmit around the edge gate toward the core entry where exposure permits, and treat the edge-versus-core reach as the defence-bypass family's invoked step while recording only the authorization verdict here.
The parent exercise step covers transports and method overrides but never describes chain diffing or shadow resubmission, so this variant owns that procedure.

## Advanced Techniques

Alternate transport handlers extend the same resubmission where the runtime exposes them.
Probe structured-query mutations and nested privileged fields beside their top-level guards, since resolver-level checks drift independently.
Probe remote-procedure methods hidden from the gateway descriptor, since interceptor coverage drifts per method.
Probe privileged events on persistent channels after a standard handshake, since per-message authorization drifts from handshake checks.

## Bypass Techniques

Route shadowing is the control defeat live for this variant.
Replay the action against legacy and versioned route forms until each form carries a decided verdict.
Vary method-override framings while keeping route and body constant, and read which framing the service honors.
Record the middleware attribution per finding so parser-wiring gaps stay separate from route-table gaps.

When this section does not fulfil the knowledge gap, extend the reading with the defence-bypass and proxy-techniques families.

## Testing Methodology

1. Build the actor-by-action matrix by enumerating each role against each privileged action, with completion when every action has an expected-role cell (procedure owned by `two-principal-authz`).
2. Establish principals by acquiring one working session per matrix role, with completion when each role issues an authenticated baseline (procedure owned by `two-principal-authz`).
3. Diff enforcement chains by comparing middleware per route, per parser handler, and per version, with completion when every alternate form and version of each action names its chain.
4. Replay through alternates by resubmitting each privileged action via alias, shadow route, method framing, and sibling parser handler beside its primary-path control, with completion when every alternate form carries a lower-role attempt beside a proper-role control.
5. Reach around the edge by resubmitting toward the core entry where exposure permits, with completion when each edge-blocked action shows whether the core entry re-checks.
6. Confirm the effect by comparing state snapshots and audit entries across the pair, with completion when every positive shows a privileged change rather than a status artifact alone.

## False Positives

Discard read-only endpoints documented as public, since reachability without a privileged effect is not an action-binding failure.
Discard preview toggles intentionally open to all roles under a clear policy, confirming the policy before filing.
Discard stubbed privileged endpoints in simulated environments that record no real effect.
Discard single-encoding failures judged before every sibling handler was tried, since the shape may be wrong while an alternate chain stays untested.

## Pro Tips

Diff middleware stacks before replaying anything, since weak chains cluster on legacy and alternate handlers.
Hold the token constant across each pair, since only the path may vary when the path is the question.
Prefer minimal proofs: one alternate request that flips a privileged field or invokes a privileged method with a lower-role session.
Treat transport-specific handlers as aspects of the same resubmission, recording verdicts per handler without splitting the procedure.
Never conclude resistance from one rejected framing, since a sibling chain may still enforce less.

## Summary

Every route, framing, handler, and entry that reaches a privileged action must bind caller to action at the performing service.
Replay each action through every alternate beside its control, and file every pair where the alternate authorizes what the primary denies.
