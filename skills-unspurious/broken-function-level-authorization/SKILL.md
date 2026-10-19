---
name: broken-function-level-authorization
description: BFLA testing for action-level authorization failures across endpoints, admin functions, and API operations
metadata:
  version: 1.0.0
---

# Broken Function Level Authorization (BFLA)

BFLA is action-level authorization failure: callers invoke functions (endpoints, mutations, admin tools) they are not entitled to. It appears when enforcement differs across transports, gateways, roles, or when services trust client hints. Bind subject × action at the service that performs the action.

## Attack Surface

- Vertical authz: privileged/admin/staff-only actions reachable by basic users
- Feature gates: toggles enforced at edge/UI, not at core services
- Transport drift: REST vs GraphQL vs gRPC vs WebSocket with inconsistent checks
- Gateway trust: backends trust X-User-Id/X-Role injected by proxies/edges
- Background workers/jobs performing actions without re-checking authz

## Reconnaissance

### Surface Enumeration

- Admin/staff consoles and APIs, support tools, internal-only endpoints exposed via gateway
- Hidden buttons and disabled UI paths (feature-flagged) mapped to still-live endpoints
- GraphQL schemas: mutations and admin-only fields/types; gRPC service descriptors (reflection)
- Mobile clients often reveal extra endpoints/roles in app bundles or network logs

### Role and Route Inventory

- Collect one session per role so every action can be exercised with each actor
- Diff middleware stacks between the primary route and its aliases, legacy paths, and alternate encodings
- Trace the actor value from the edge inward: token claim, gateway-injected header, and body hint

## Detection Channels

- Denial on the primary path beside success on an alternate path for the same action decides the finding.
- A privileged effect observed after an alias, shadow-route, or parser-path replay, even when the status line looks normal.
- Status and effect differentials across transports or encodings for the same action.
- Access that changes on a hint or selector change alone, without any token change.
- A privileged effect under a hinted lower-role token beside denial without the hint.
- Conflicting-hint pairs where the service honors one source over the other show which source wins.
- A privileged effect from a deferred step replayed by an unentitled caller, beside denial on the direct call.
- State changes applied by a redelivered webhook or retried finalize without a fresh actor check.
- Session swaps that inherit a cached edge decision.
- A before-and-after state snapshot showing the privileged change completes the proof.

## Adversarial Capabilities

BFLA testing presupposes a role ladder, a second identity source, and reach into every transport that performs the action, and it consumes all three.
- Hold one authenticated session per role, from unauthenticated through staff, on every transport in scope.
- Replay one action across transports, encodings, and routes while changing only the actor or the identity hint.
- Supply identity hints and selectors (tenant, organization, project) independently of the token.
- Reach background delivery paths, such as queue and webhook endpoints, that perform the action later.
- Read the durable effect of each replay, not only the status line, through a before-and-after snapshot.

## Trust Assumptions

The class rests on one agreement: the service that performs an action checks the actor against that action, on every path that reaches it.
The agreement holds the actor claim as the only identity source, holds the action check at the same layer for every transport and encoding, and holds deferred steps to a fresh check at execution time.
Sensitive position leaks when any path performs the action while skipping the actor check: an alias, a weaker parser, a trusted upstream hint, or a job that runs later.
Each variant breaks one clause: the path-binding clause, the identity-source clause, or the execution-time clause.
Service-to-service trust is the shared root, because an internal caller is assumed to have been authorized upstream.

## Key Vulnerabilities

### Verb Drift and Aliases

- Alternate methods: GET performing state change; POST vs PUT vs PATCH differences; method-override headers or fields
- Alternate endpoints performing the same action with weaker checks (legacy vs v2, mobile vs web)

### Edge vs Core Mismatch

- The edge blocks an action but the core service accepts it directly; call the internal service through an exposed route
- Gateway-injected identity headers override token claims; supply conflicting headers to test precedence

### Feature Flag Bypass

- Client-checked feature gates; call the backend endpoints directly
- Admin-only mutations exposed but hidden in the UI; invoke them through the schema or RPC tools

### Batch Job Paths

- Create export/import jobs where creation is allowed but finalize/approve lacks authz; finalize another actor's jobs
- Replay webhook or background task endpoints that perform privileged actions without verifying the caller

### Content-Type Paths

- JSON vs form vs multipart handlers using different middleware: send the action through the most permissive parser

## Advanced Techniques

### Schema and Resolver Paths

- Resolver-level checks per mutation and field; do not assume top-level auth covers nested mutations or admin fields
- Abuse aliases and batching to reach privileged fields; persisted queries sometimes bypass auth transforms

### RPC and Descriptor Paths

- Method-level auth via interceptors must enforce audience and roles; probe the service directly with a lower-role token
- Reflection lists services and methods; call admin methods the gateway hid

### Socket Paths

- Handshake-only auth: ensure per-message authorization on privileged events
- Emit privileged actions after joining a standard channel

### Multi-Tenant

- Actions requiring tenant admin enforced only by header or subdomain; attempt cross-tenant admin actions by switching selectors with the same token

### Microservices

- Internal RPCs trust upstream checks; reach them through exposed endpoints; verify each service re-enforces authz

## Bypass Techniques

### Header Trust

- Supply identity headers; remove or contradict token claims; observe which source wins

### Route Shadowing

- Legacy or alternate routes that skip the newer middleware chain

### Idempotency and Retries

- Retry or replay finalize and approve endpoints that apply state without checking the actor on each call

### Cache Key Confusion

- Cached authorization decisions at the edge reused across users; test with cache-key variation and session swaps, with the edge-versus-core step owned by the defence-bypass family

When this section does not fulfil the knowledge gap, extend the reading with the defence-bypass and proxy-techniques families.

## Testing Methodology

1. **Build Actor × Action matrix** - Unauth, basic, premium, staff/admin; enumerate actions per role
2. **Obtain tokens/sessions** - For each role
3. **Exercise every action** - Across all transports and encodings (JSON, form, multipart), including method overrides
4. **Vary headers and selectors** - Org/tenant/project; test behind gateway vs direct-to-service
5. **Include background flows** - Job creation/finalization, webhooks, queues; confirm re-validation
6. **Confirm the effect** - Snapshot the durable state before and after each replay, and the step completes when every privileged effect has a matched denial

## Variants

- bfla-alternate-path - Replay privileged actions through shadow routes and permissive parser chains that skip the current middleware.
- bfla-client-identity-trust - Decide which request input the service treats as the actor when hints or selectors can override the token.
- bfla-deferred-execution - Replay finalize, approval, and background deliveries under a different actor than the caller who created them.

## False Positives

- Read-only endpoints mislabeled as admin but publicly documented
- Feature toggles intentionally open to all roles for preview/beta with clear policy
- Simulated environments where admin endpoints are stubbed with no side effects

## Pro Tips

1. Start from the role matrix; test every action with basic vs admin tokens across REST/GraphQL/gRPC
2. Diff middleware stacks between routes; weak chains often exist on legacy or alternate encodings
3. Inspect gateways for identity header injection; never trust client-provided identity
4. Treat jobs and webhooks as first-class: finalize and approve must re-check the actor
5. Prefer minimal PoCs: one request that flips a privileged field or invokes an admin method with a basic token

## Summary

Authorization must bind the actor to the specific action at the service boundary on every request and message. UI gates, gateways, or prior steps do not substitute for function-level checks.
