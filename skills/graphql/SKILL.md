---
name: graphql
description: OWASP GraphQL security testing — introspection, injection, DoS, IDOR/BFLA, batching, GraphiQL, and excessive errors
metadata:
  version: '1.0'
---

# GraphQL

Test GraphQL APIs using the [OWASP GraphQL Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/GraphQL_Cheat_Sheet.html). Every interesting action is a GraphQL operation (`query` / `mutation`), not a REST resource. Auth first, then abuse resolvers.

Send JSON POSTs:

```http
POST /api/graphql
Content-Type: application/json
Cookie: session=<cookie>

{"query":"query { hello }","variables":null}
```

Confirm the endpoint with `{__typename}` (or `{__schema{queryType{name}}}`). A JSON body with `data` or `errors`, or HTTP 401 on a `/graphql` path, means GraphQL.

Use project secrets (`TESTUSER_EMAIL` / `TESTUSER_PW`) for login. Typical login mutation:

```graphql
mutation { login(email: "USER", password: "PASS") { ok token } }
```

Reuse `Set-Cookie` (or a returned token) on later requests. If unauthenticated queries return 401, do not treat that as “not GraphQL”.

## Common attacks (OWASP)

### 1. Insecure defaults — introspection, GraphiQL, errors

```graphql
{__schema{queryType{name}mutationType{name}types{name fields{name args{name type{name kind ofType{name}}}}}}}
```

Also try GraphiQL/Playground: `/graphql`, `/graphiql`, `/playground`, `/altair`.

If introspection is off, brute-force field names and watch **Did you mean "user?"** suggestions (leaks schema). Unknown-field vs unauthorized-field errors also prove a field exists.

Production APIs must not return stack traces or debug dumps in `errors`. Record path/SQL/exception text as information disclosure.

### 2. Injection (resolver args)

GraphQL args are passed into SQL, NoSQL, OS, LDAP, XML, and HTTP clients. Probe **string arguments** (`id`, `email`, `search`, `url`, `path`, `host`) with the same payloads as those interpreters.

```graphql
query {
  user(id: "1 OR 1=1") { id }
  search(q: "\"} || true || \"") { id }
}
mutation {
  createNote(title: "'; SELECT pg_sleep(3)--") { id }
}
```

SSRF/CRLF: if an arg looks like a URL or host, pass an internal URL. Do not use user input as the HTTP target (OWASP process validation).

Prefer parameterized-looking failures vs true injection: a 200 with extra rows, time delay, or a fetched internal body is a finding. Pair with skills `sql-injection`, `ssrf`, `rce`.

### 3. Denial of service

Do **not** take a live target down. On authorized benches, show that limits are missing with modest payloads:

**Depth** (cyclic nesting):

```graphql
query {
  album(id: 1) { songs { album { songs { album { id } } } } }
}
```

**Amount** (unbounded lists):

```graphql
query { author(id: "1") { posts(first: 9999) { title } } }
```

**Alias amplification** (many resolvers, one HTTP request):

```graphql
query {
  a1: user(id: "1") { id }
  a2: user(id: "2") { id }
  a3: user(id: "3") { id }
}
```

A finding is: request succeeds, latency/size explodes, or the server hangs — and there is no depth/amount/cost/rate limit. Stop after proving it.

### 4. Broken authorization (BOLA/IDOR and BFLA)

Possession of an object ID is not authorization. After login as principal A, request principal B’s objects.

**Query IDOR (BOLA)** — same operation, foreign id:

```graphql
query {
  me { id email }
  own: user(id: "1") { id email apiKey }
  foreign: user(id: "2") { id email apiKey }
}
```

If `foreign` returns another user’s secrets (tokens, apiKey, email, PII), that is a GraphQL IDOR. Aliases in one request are enough; do not require REST.

**Relay `node` / `nodes`** — hidden IDOR even when `user(id:)` is locked down:

```graphql
query { node(id: "2") { ... on User { id email apiKey } } }
```

**Field-level access** — caller may read `user { id }` but not `user { apiKey role }`. Request sensitive fields as a low-privilege user.

**Mutation BFLA** — invoke admin/update/delete as a normal user:

```graphql
mutation { updateUser(id: "2", role: "admin") { id role } }
mutation { deleteUser(id: "2") { ok } }
```

Authorize **nodes and edges**. A list/connection that hides a row but `user(id:)` still returns it is still IDOR.

### 5. Batching attacks

Two GraphQL-specific brute-force forms (bypass HTTP-layer rate limits):

**JSON array batching** (Apollo-style):

```json
[
  {"query":"query($id:ID!){user(id:$id){email}}","variables":{"id":"1"}},
  {"query":"query($id:ID!){user(id:$id){email}}","variables":{"id":"2"}}
]
```

**Alias batching** in one operation (see DoS / IDOR examples).

Use this to enumerate users, brute OTPs/tokens, or multiply resolver cost. Sensitive mutations (`login`, `verifyOtp`) batched in one call are high impact.

## Request variants

Try each of these if the first POST JSON fails:

- `{"query":"..."}` vs `query=` form body vs `Content-Type: application/graphql`
- GET `/graphql?query={__typename}` (cookie-auth GET enables CSRF on mutations)
- `variables` vs inline args
- Comments and fragments to evade WAFs: `query { user(id:"2") { ...F } } fragment F on User { apiKey }`

## Testing order

1. Confirm GraphQL (`{__typename}`). Note 401 vs GraphQL errors.
2. Introspection / GraphiQL / field suggestions. Map Query and Mutation fields (or use already-recorded `POST /path Query.field` attack-surface items).
3. Authenticate with project secrets. Re-enumerate if the schema grows after login.
4. For each Query that takes an id: owned vs foreign (IDOR). Prefer aliases in one request.
5. For each Mutation: unauthenticated, low-priv, and cross-user ids (BFLA).
6. Injection in string args of those same fields.
7. Light depth/amount/alias probes for missing limits. Batching on login/OTP if present.
8. Record stack traces / SQL in `errors`.

## Validation

A GraphQL finding needs:

- The exact `POST` path, operation (`Query.user` / `Mutation.login`), and GraphQL document
- Cookie or token used
- Two responses: authorized vs unauthorized principal, or injected vs clean input
- Impact in the JSON `data` (foreign `apiKey`, extra rows, delay), not just “it returned 200”

Do not report CSRF/CORS without a cookie-auth GraphQL request that changes state. Do not report introspection on a deliberately public schema unless it exposes private/deprecated fields.

## False positives

- `Cannot query field "X"` — field does not exist
- `Unauthorized` / 401 on the whole endpoint — log in, then retest
- Public `hello` / health fields
- Empty `user(id: foreign)` when the owner query returns data — that is enforcement, not IDOR
- Introspection disabled is expected on many production APIs; still test IDOR and injection
