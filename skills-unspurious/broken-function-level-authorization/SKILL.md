---
name: broken-function-level-authorization
description: BFLA testing for action-level authorization failures across endpoints, admin functions, and API operations
metadata:
  version: 1.0.0
---

# Broken Function Level Authorization (BFLA)

BFLA is action-level authorization failure: callers invoke functions (endpoints, mutations, admin tools) they are not entitled to. It appears when enforcement differs across transports, gateways, roles, or when services trust client hints. Bind subject × action at the service that performs the action.

## Attack Surface

- **Vertical authz**: privileged/admin/staff-only actions reachable by basic users
- **Feature gates**: toggles enforced at edge/UI, not at core services
- **Transport drift**: rEST vs GraphQL vs gRPC vs WebSocket with inconsistent checks
- **Gateway trust**: backends trust X-User-Id/X-Role injected by proxies/edges
- **Unlinked interfaces**: administrative, debug, or internal surfaces reachable without an actor, where the surface is assumed unreachable rather than actor-checked
- **Version surface**: an old or alternate version of one action that enforces less than the current version
- **Background workers**: background workers/jobs performing actions without re-checking authz

## Reconnaissance

### Surface Enumeration

- **Surface sources**: admin/staff consoles and APIs, support tools, internal-only endpoints exposed via gateway
- **Hidden UI paths**: hidden buttons and disabled UI paths (feature-flagged) mapped to still-live endpoints
- **GraphQL schemas**: mutations and admin-only fields/types; gRPC service descriptors (reflection)
- **Client bundles**: mobile clients often reveal extra endpoints/roles in app bundles or network logs
- **Unlinked administrative, debug, and internal interfaces**: enumerate them from listings, artifacts, and naming conventions, then reach each one without an actor, because obscurity is the whole control
- **Version inventory**: enumerate every reachable version of one action, then behaviourally diff authorization, validation, and rate-limit strength between the old and the current version

### Role and Route Inventory

- **Session per role**: collect one session per role so every action can be exercised with each actor
- **Middleware diffing**: diff middleware stacks between the primary route and its aliases, legacy paths, and alternate encodings
- **Actor-value tracing**: trace the actor value from the edge inward: token claim, gateway-injected header, and body hint
- **Identity-source candidates**: enumerate client-supplied privilege flags and requester markers from bundles and prior traffic as candidate identity sources, since a service that reads them self-elevates
- **Tier inventory**: inventory the route surface by tier before any replay, because one action is frequently reachable through more than one route, handler, or version; the sibling-route and version-consistency inventory is owned by `proxy-techniques-channel-wrapping`, and the authorization verdict per form is recorded here

## Detection Channels

- **Denial beside alternate success**: denial on the primary path beside success on an alternate path for the same action decides the finding.
- **Privileged effect**: a privileged effect observed after an alias, shadow-route, or parser-path replay, even when the status line looks normal.
- **Cross-transport differentials**: status and effect differentials across transports or encodings for the same action.
- **Hint-only access change**: access that changes on a hint or selector change alone, without any token change.
- **Precedence failure**: a privileged effect under a hinted lower-role token beside denial without the hint.
- **Conflicting hints**: conflicting-hint pairs where the service honors one source over the other show which source wins.
- **Deferred-effect gap**: a privileged effect from a deferred step replayed by an unentitled caller, beside denial on the direct call.
- **Redelivery effects**: state changes applied by a redelivered webhook or retried finalize without a fresh actor check.
- **Stale-approval reuse**: session swaps that inherit a cached edge decision.
- **Method-inconsistency pair**: denial on one verb beside success on another verb of the same action, which reads as per-path enforcement.
- **Version regression**: a more permissive answer from an old or alternate version of one action than from the current version, which reads as a behavioural regression.
- **Unlinked surface answer**: a privileged surface answering at all without an actor, where the surface was assumed unreachable.
- **State snapshot**: a before-and-after state snapshot showing the privileged change completes the proof.

## Adversarial Capabilities

- **Prerequisites**: bFLA testing presupposes a role ladder, a second identity source, and reach into every transport that performs the action, and it consumes all three.
- **Role sessions**: hold one authenticated session per role, from unauthenticated through staff, on every transport in scope.
- **Single-variable replay**: replay one action across transports, encodings, and routes while changing only the actor or the identity hint.
- **Hint and selector supply**: supply identity hints and selectors (tenant, organization, project) independently of the token.
- **Background reach**: reach background delivery paths, such as queue and webhook endpoints, that perform the action later.
- **Durable-effect reads**: read the durable effect of each replay, not only the status line, through a before-and-after snapshot.

## Trust Assumptions

- **The trust premise**: the class rests on one agreement: the service that performs an action checks the actor against that action, on every path that reaches it.
- **The agreement**: it holds the actor claim as the only identity source, holds the action check at the same layer for every transport and encoding, and holds deferred steps to a fresh check at execution time.
- **The exposure**: sensitive position leaks when any path performs the action while skipping the actor check: an alias, a weaker parser, a trusted upstream hint, or a job that runs later.
- **The failing clause**: each variant breaks one clause: the path-binding clause, the identity-source clause, or the execution-time clause.
- **Shared root**: service-to-service trust is the shared root, because an internal caller is assumed to have been authorized upstream.

## Key Vulnerabilities

### Verb Drift and Aliases

- **Alternate methods**: gET performing state change; POST vs PUT vs PATCH differences; method-override headers or fields
- **Alternate endpoints**: alternate endpoints performing the same action with weaker checks (legacy vs v2, mobile vs web)

### Edge vs Core Mismatch

- **Edge-versus-core mismatch**: the edge blocks an action but the core service accepts it directly; call the internal service through an exposed route
- **Header precedence**: gateway-injected identity headers override token claims; supply conflicting headers to test precedence

### Feature Flag Bypass

- **Client-checked gates**: client-checked feature gates; call the backend endpoints directly
- **Hidden mutations**: admin-only mutations exposed but hidden in the UI; invoke them through the schema or RPC tools

### Batch Job Paths

- **Job finalization**: create export/import jobs where creation is allowed but finalize/approve lacks authz; finalize another actor's jobs
- **Delivery replay**: replay webhook or background task endpoints that perform privileged actions without verifying the caller

### Multi-Step Workflow Gaps

- **Unguarded transitions**: one transition of a multi-step flow carries no authorization check while its siblings do; call the confirmation or completion step directly and skip the guarded steps
- **Skipped-step defaults**: dropping a step whose absence leaves a privileged default, such as a skipped selection request that leaves the privileged option in place

### Content-Type Paths

- **Parser-handler differences**: jSON vs form vs multipart handlers using different middleware: send the action through the most permissive parser

## Advanced Techniques

### Schema and Resolver Paths

- **Resolver-level checks**: resolver-level checks per mutation and field; do not assume top-level auth covers nested mutations or admin fields
- **Aliases and batching**: abuse aliases and batching to reach privileged fields; persisted queries sometimes bypass auth transforms

### RPC and Descriptor Paths

- **Interceptor coverage**: method-level auth via interceptors must enforce audience and roles; probe the service directly with a lower-role token
- **Reflection**: reflection lists services and methods; call admin methods the gateway hid

### Socket Paths

- **Handshake-only auth**: ensure per-message authorization on privileged events
- **Channel events**: emit privileged actions after joining a standard channel

### Multi-Tenant

- **Tenant-admin enforcement**: actions requiring tenant admin enforced only by header or subdomain; attempt cross-tenant admin actions by switching selectors with the same token

### Microservices

- **Internal RPC trust**: internal RPCs trust upstream checks; reach them through exposed endpoints; verify each service re-enforces authz

## Bypass Techniques

### Header Trust

- **Header trust**: supply identity headers; remove or contradict token claims; observe which source wins

### Route Shadowing

- **Route shadowing**: legacy or alternate routes that skip the newer middleware chain
- **Normalisation forms**: path-normalisation forms that reach a route the primary spelling does not: case variation, dot segments, encoded separators, delimiter insertion, trailing dot or extension, and double encoding; replay the same action through each form and read the verdict per form

### Idempotency and Retries

- **Idempotency and retries**: retry or replay finalize and approve endpoints that apply state without checking the actor on each call

### Cache Key Confusion

- **Cache key confusion**: cached authorization decisions at the edge reused across users; test with cache-key variation and session swaps, with the edge-versus-core step owned by the defence-bypass family

When this section does not fulfil the knowledge gap, extend the reading with the defence-bypass and proxy-techniques families.

## Testing Methodology

1. **Build Actor × Action matrix** - Unauth, basic, premium, staff/admin; enumerate actions per role
2. **Obtain tokens/sessions** - For each role
3. **Exercise every action** - Across all transports and encodings (JSON, form, multipart), including method overrides
4. **Vary headers and selectors** - Org/tenant/project; test behind gateway vs direct-to-service
5. **Include background flows** - Job creation/finalization, webhooks, queues; confirm re-validation
6. **Confirm the effect** - Snapshot the durable state before and after each replay, and the step completes when every privileged effect has a matched denial

The matrix and its transport replay are driven by `scripts/bfla-role-matrix`, which records an expected-minimum-role cell per action and a verdict per cell, so an unexpected grant is named rather than eyeballed.

## Variants

- bfla-alternate-path - Replay privileged actions through shadow routes and permissive parser chains that skip the current middleware.
- bfla-client-identity-trust - Decide which request input the service treats as the actor when hints or selectors can override the token.
- bfla-deferred-execution - Replay finalize, approval, and background deliveries under a different actor than the caller who created them.

## False Positives

- **Public read-only endpoints**: read-only endpoints mislabeled as admin but publicly documented
- **Open preview toggles**: feature toggles intentionally open to all roles for preview/beta with clear policy
- **Stubbed endpoints**: simulated environments where admin endpoints are stubbed with no side effects

## Pro Tips

- **Matrix first**: start from the role matrix; test every action with basic vs admin tokens across REST/GraphQL/gRPC
- **Middleware diffing**: diff middleware stacks between routes; weak chains often exist on legacy or alternate encodings
- **Gateway inspection**: inspect gateways for identity header injection; never trust client-provided identity
- **Jobs and webhooks first**: treat jobs and webhooks as first-class: finalize and approve must re-check the actor
- **Minimal PoCs**: prefer minimal PoCs: one request that flips a privileged field or invokes an admin method with a basic token

## Summary

Authorization must bind the actor to the specific action at the service boundary on every request and message. UI gates, gateways, or prior steps do not substitute for function-level checks.
