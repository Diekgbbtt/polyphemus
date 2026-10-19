---
name: graphql
description: GraphQL security testing - introspection, injection, DoS, IDOR/BFLA, batching, subscription channels, and excessive errors
metadata:
  version: 1.0.0
---

# GraphQL

GraphQL APIs expose one endpoint where every interesting action is an operation (`query` or `mutation`) rather than a REST resource. Establish the endpoint and the schema first, authenticate, then abuse resolvers. A subscription is a third operation type that carries a push channel over a persistent connection, so it is swept lightly and separately from the request-time resolvers.

## Attack Surface

**Endpoint Shape**
- **Single path**: a single path carrying queries and mutations; JSON POST bodies with a query document plus optional variables
- **Alternative transports**: form-encoded bodies, a dedicated media type, GET with a query parameter, and batch arrays
- **Console surfaces**: interactive query editors exposed alongside the API path

**Operation Types**
- **Query arguments**: queries that take identifiers, filters, search strings, URLs, or paths as arguments
- **Mutations**: mutations that create, update, delete, promote, invite, or verify
- **Nested selections**: nested selections that resolve relations and connections with pagination arguments
- **Subscription fields**: operations that open a push channel over a persistent connection and stream matching events to the subscriber, including events for other principals when channel scope is not enforced

**Access Paths**
- **Access tiers**: unauthenticated operations, session-cookie and bearer-token operations, and per-field permission tiers
- **Node lookups**: relay-style node and nodes lookups that resolve any type by identifier
- **Persisted operations**: persisted or pre-registered operations, and batched arrays of operations in one request

## Reconnaissance

### Confirm and Map

- **Endpoint confirmation**: confirm the endpoint with a well-known meta field; a structured body carrying data or errors, or an auth challenge on the path, marks GraphQL
- **Introspection**: introspect where enabled to map queries, mutations, types, fields, and arguments
- **Field-name enumeration**: where introspection is disabled, enumerate field names and read the suggestion text in unknown-field errors, which leaks neighbouring names
- **Error distinction**: distinguish unknown-field errors from unauthorized-field errors: the second proves the field exists
- **Subscription declaration**: note whether the schema declares a subscription operation type, and whether a push-channel handshake is available on the same path
- **Console surfaces**: watch for console and editor surfaces on sibling paths
- **Payload reference**: see `references/graphql-payloads.md` for the operation shapes behind introspection, the field-suggestion probe, alias batches, depth bombs, and batch arrays.

### Authenticate and Re-enumerate

- **Login reuse**: log in with available test credentials and reuse the returned session or token on later requests
- **Re-enumeration**: re-enumerate the schema after login: fields and types often grow with the authenticated role
- **Auth-challenge reading**: treat an unauthenticated auth challenge as expected rather than as evidence the endpoint is not GraphQL

### Record Baselines

- **Response baselines**: record one known-good response per operation shape (query, mutation, nested selection) to serve as the acceptance baseline
- **Size and latency**: note response size and latency per operation under a benign argument set

## Detection Channels

- **Structured bodies**: structured response bodies carrying data or errors that mark a live GraphQL endpoint.
- **Introspection output**: introspection output listing queries, mutations, types, and arguments.
- **Suggestion lists**: unknown-field error text carrying a suggestion list, which leaks neighbouring field names.
- **Field-existence proof**: unknown-field verdict beside unauthorized-field verdict for the same name, which proves the field exists.
- **Resolver error text**: resolver error text carrying internal paths, query fragments, or exception classes.
- **Foreign-object data**: foreign-object data returned for an identifier the caller does not own.
- **Privileged mutation effect**: a privileged mutation effect observed under a lower-privilege actor.
- **Amplification signals**: request success with latency or response size exploding under depth, amount, or alias amplification.
- **Batch leaks**: batch responses where a forbidden operation succeeds inside a nominally allowed array.
- **Pushed events over a connection**: events arriving after a subscription is established, including events for a principal the caller does not own, which proves a channel-scope gap.

## Adversarial Capabilities

- **Prerequisites**: GraphQL testing presupposes one authenticated session per privilege tier, a schema or field-name inventory, and repeated requests with controlled argument shapes, and it consumes all three.
- **Session holding**: hold low-privilege and foreign-principal sessions so access verdicts can be contrasted.
- **Document control**: send arbitrary operation documents, variable maps, aliases, fragments, and batch arrays to one endpoint.
- **Field enumeration**: enumerate field names and types where introspection is closed, through error text and brute force.
- **Amplification measurement**: measure response latency and size under amplified operations without taking the target down.
- **Transport replay**: replay one operation through each transport (JSON, form, media type, GET, batch).
- **Push-channel client**: hold a push-channel client that keeps one connection open and reads the events pushed over it.

## Trust Assumptions

- **The agreement**: the class rests on one agreement: each operation is authorized at the field or resolver that resolves it, and each argument is data rather than a fragment of a downstream instruction. The agreement holds authorization to every resolver and every node, holds argument values to their declared scalar type before they reach a downstream interpreter, holds query cost to a bound the server enforces, and holds error text to the operator while exposing only the caller's own data. Sensitive position and data leak when a resolver trusts its caller, trusts an argument's shape, or trusts that upstream cost and rate limits already apply.
- **The non-decomposing baseline**: the non-decomposing baseline is the endpoint itself: one surface where depth, aliasing, and nesting are all caller-controlled.
- **The subscription agreement**: a subscription adds a second agreement: the connection identity stays bound to every event pushed over it, so per-channel and per-message authorization must hold for the life of the connection.

## Key Vulnerabilities

### Insecure Defaults and Error Exposure

- **Introspection and editors**: introspection and query editors enabled in production expose the whole schema
- **Field-name suggestions**: field-name suggestions in errors leak schema shape where introspection is closed
- **Error payloads**: stack traces, internal paths, and query fragments in error payloads count as information disclosure

### Resolver-Argument Injection

- **Downstream interpreters**: arguments flow into downstream interpreters: query languages, document stores, command shells, directory services, XML parsers, and HTTP clients
- **Argument probing**: probe every string argument that looks like an identifier, a search term, a URL, or a path with the payload shapes of the interpreter behind it
- **URL-shaped arguments**: a URL-shaped or host-shaped argument reaches internal services when the resolver fetches it
- **Injection verdicts**: parameterized-looking failures versus true injection: extra rows in a 200, a measurable delay, or an internal body fetched back are the findings

### Denial of Service

- **Depth**: cyclic nesting that multiplies resolver calls per level
- **Amount**: unbounded list arguments pulling entire collections
- **Alias amplification**: many aliases of one resolver in a single request bypassing request-rate limits
- **Fragments after the check**: fragments that expand depth after the depth check counts them, including a fragment that references itself, reach the same recursion the check was meant to bound
- **Finding shape**: a finding is a succeeded request whose latency or size explodes without depth, amount, cost, or rate bounds; prove it and stop

### Broken Authorization (Object and Function Level)

- **Identifier possession**: possession of an identifier is not authorization; request foreign identifiers after authenticating as one principal
- **Aliased lookups**: alias several identifier lookups in one operation to test ownership contrast in one request
- **Relay lookups**: relay-style node and nodes lookups resolve hidden objects even when named lookups are locked down
- **Field-level access**: a caller entitled to one field set may read sensitive sibling fields; request them as a low-privilege actor
- **Mutation-level access**: invoke admin, update, promote, or delete operations as a normal user
- **Node and edge authorization**: authorize nodes and edges as well as top-level fields: a connection that hides a row while the identifier lookup still returns it remains a gap

### Batching Amplification

- **Rate-limit evasion**: array batches and aliases turn one HTTP request into many operations, evading per-request rate limits
- **Batch uses**: use them to enumerate identities, brute one-time codes or tokens, or multiply resolver cost
- **Concurrent resolvers**: batched aliases win only when the resolvers run concurrently, so a batch that succeeds where the same operations sent sequentially do not marks a race; name the race-conditions skill at that step
- **Sensitive mutations**: sensitive mutations batched in one call carry the highest value

### Subscription Channels

- **Per-message authorization**: a subscription authorizes the channel when the connection is established and then pushes every matching event over that same connection, so authorization must hold per message rather than per connect
- **Channel scope**: sweep the channel scope: subscribe to a channel another principal owns and read whether that principal's events arrive on the connection
- **Light sweep**: the push channel is a rare interaction protocol, so treat this as a light sweep beside the request-time object and function sweeps rather than a first-line target

## Advanced Techniques

### Batched and Persisted Operations

- **Brute-force targets**: batch arrays stress brute-force targets (login, verification, invitation) while the transport survives intact
- **Auth-transform skips**: persisted or pre-registered operations sometimes skip the auth transforms applied to ad-hoc documents

### Transport and Parser Differentials

- **Validation paths**: the same operation carried as JSON, form-encoded, a dedicated media type, or a GET parameter can land on different validation paths
- **GET-carried mutations**: GET-carried operations enable cross-site forgery on mutations where cookie auth applies

### Relay and Connection Paths

- **Node lookups**: node lookups resolve any mapped type by identifier, which turns one authorized lookup into a cross-type read
- **Connection edges**: connection edges carry their own authorization questions, including counts and page windows
- **Relay identifier decoding**: relay identifiers decode to a type and an identifier, so decode and re-encode them to reach a type the named lookup hides

### Cross-API State Reconciliation

- **Revocation disagreement**: revoke access through the REST surface, then re-assert it through the equivalent mutation, and show the privilege persists: two APIs disagree on ground truth and the revocation is never reconciled
- **Companion-skill reference**: name the business-logic and race-conditions skills at the reconciliation step rather than restating their procedures here
- **Durable finding**: treat a successful re-assertion as a durable authorization finding, not as a caching artefact, once it reproduces after the revocation settles

## Bypass Techniques

- **Comment and fragment evasion**: comments and fragments in the operation document evade text-matching filters while the operation stays valid
- **Variable indirection**: pass hostile values through the variable map rather than inline arguments, which moves them past argument-level filters
- **Aliasing**: aliasing to duplicate a filtered operation many times inside one document
- **Nested selections**: nested selections that reach a guarded field through an allowed parent
- **Batching**: batching to interleave a blocked operation among allowed siblings
- **Cost-function underflow**: a cost function that does not floor at zero lets one request refill its own budget, so a negative amount argument passes the limit check
- **Directives**: directives that change evaluation order or skip a selection, such as a conditional directive on a guarded field, move the operation past a filter that reads only the selection set
- **Field-alias introspection bypass**: alias a guarded field name inside an allowed query so the response reveals whether the field resolves
- **Family handoff**: name the defence-bypass family at its signature-evasion step for the filter shapes, rather than restating the matcher mechanics here.

When this section does not fulfil the knowledge gap, extend the reading with the defence-bypass and proxy-techniques families.

## Chaining Attacks

- **Injection chains**: resolver-argument injection + the interpreter class behind the argument (query language, command, path, URL) to turn one argument into a downstream finding
- **Enumeration chains**: broken object authorization + identifier enumeration to sweep collections for foreign data
- **Amplification chains**: denial-of-service probes + alias amplification to hold a rate-limit budget while brute-force operations run
- **Error-assisted chains**: error exposure + injection probing: leaked query fragments shorten the blind-exploitation path
- **Reconciliation chains**: revocation through one API beside re-assertion through the mutation: name the business-logic and race-conditions skills at the reconciliation step
- **Fetch and relay chains**: URL-like resolver arguments that reach an internal fetch name the proxy-techniques family at its relay step and `ssrf` at the fetch step, rather than restating either here

## Testing Methodology

1. **Confirm the endpoint** - A meta field answers with a structured body; record the auth challenge shape for later steps
2. **Map the schema** - Introspection, editor surfaces, and field-suggestion errors; the step completes when queries and mutations are enumerated or enumerated as far as the surface allows
3. **Authenticate and re-enumerate** - Log in per role and diff the reachable field set; the step completes when each role's reachable surface is recorded
4. **Object-level sweep** - Per identifier-taking query, request owned versus foreign identifiers; the step completes when each query carries an access verdict
5. **Function-level sweep** - Per mutation, attempt it unauthenticated, as a low-privilege actor, and with foreign identifiers, including money-movement mutations such as transfer, redemption, and withdrawal; the step completes when each mutation carries a verdict
6. **Subscription sweep** - Per subscription field, establish the push channel, subscribe to a channel another principal owns, and read whether that principal's events arrive; the step completes when each subscription carries a channel and per-message authorization verdict
7. **Argument injection** - Probe string arguments with the payload shapes of the interpreter behind them; the step completes when each argument carries an injection verdict
8. **Bounded amplification** - Light depth, amount, and alias probes for missing limits, including fragments that expand depth after the check counts them and a fragment that references itself, plus batching on login and verification operations; the step completes when each limit question carries a verdict
9. **Error review** - Read every error payload for internal detail and file it as disclosure; the step completes when listed error texts are triaged
10. **Transport replay** - Replay the interesting operations through the alternative transports; the step completes when each transport carries a reachability verdict

## False Positives

- **Unknown-field errors**: unknown-field errors for a name that does not exist; distinguish from unauthorized-field errors
- **Endpoint-wide auth challenge**: an auth challenge on the whole endpoint; log in and retest before filing
- **Public health fields**: public health and greeting fields that carry no data
- **Empty foreign lookup**: an empty foreign lookup while the owning lookup returns data, which is enforcement rather than a gap
- **Disabled introspection**: introspection disabled in production, which is a hardening choice and not itself a finding
- **Scoped subscription channels**: a subscription channel scoped to the connected principal with per-message re-authorization, confirmed by uniform refusals for foreign channels

## Pro Tips

- **Endpoint first**: establish the endpoint and auth shape before anything else; a challenge on the path still marks GraphQL
- **Aliased lookups**: alias identifier lookups so ownership contrast resolves in one request
- **Suggestion lists**: read the suggestion lists in unknown-field errors when introspection is closed
- **Nodes and edges**: test nodes and edges, not only named lookups; connections hide rows while lookups return them
- **Modest amplification**: keep amplification probes modest and stop after proving the bound is missing
- **Transports early**: try the alternative transports early; validation paths differ between them
- **Error payloads**: treat error payloads as a first-class disclosure channel
- **Per-argument payloads**: pair each argument with the interpreter behind it rather than a generic payload set
- **Light channel sweep**: sweep the push channel lightly: subscriptions are rare, so spend the effort on request-time authorization first and treat the channel as a secondary check

## Summary

One endpoint, caller-controlled depth, aliases, and nesting, and resolvers that own their own authorization and argument trust. Bind each field to its caller, each argument to its declared type, and each operation to a cost bound. A subscription adds a push channel that must re-authorize every pushed event rather than only the connection that opened it.
