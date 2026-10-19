---
name: csrf
description: CSRF testing covering token bypass, SameSite cookies, CORS misconfigurations, and state-changing request abuse
metadata:
  version: 1.0.0
---

# CSRF

Cross-site request forgery abuses ambient authority (cookies, HTTP auth) across origins. Do not rely on CORS alone; enforce non-replayable tokens and strict origin checks for every state change.

## Attack Surface

- **Session types**: web apps with cookie-based sessions and HTTP auth, JSON/REST and GraphQL (GET/persisted queries) endpoints, and file upload endpoints.
- **Authentication flows**: login/logout, password/email change, and MFA toggles.
- **OAuth/OIDC**: authorize, token, logout, and disconnect/connect endpoints.

### Mobile/SPA

- **Deep links and WebViews**: deep links and embedded WebViews may auto-send cookies; trigger actions via crafted intents/links.
- **Exported custom-scheme handler**: an exported custom-scheme handler that performs a state change with ambient session authority reaches the endpoint from a crafted link, with no browser page and no cross-origin delivery.
- **Hybrid apps**: SPAs that rely solely on bearer tokens are less CSRF-prone, but hybrid apps mixing cookies and APIs can still be vulnerable.

### Integrations

- **Webhooks and back-office tools**: webhooks and back-office tools sometimes expose state-changing GETs intended for staff.
- **Confirmation**: confirm CSRF defenses there too.

## Reconnaissance

### Session and Cookies

- **Cookie attributes**: inspect cookies for HttpOnly, Secure, and SameSite (Strict/Lax/None).
- **SameSite semantics**: Lax allows cookies on top-level cross-site GET; None requires Secure.
- **Session model**: determine if Authorization headers or bearer tokens are used (generally not CSRF-prone) versus cookies (CSRF-prone).

### Token and Header Checks

- **Token location**: locate anti-CSRF tokens (hidden inputs, meta tags, custom headers).
- **Token behavior**: test removal, reuse across requests, reuse across sessions, and binding to method/path.
- **Origin and referer enforcement**: verify the server checks Origin and/or Referer on state changes.
- **Null and cross-origin values**: test null/missing and cross-origin values.

### Method and Content-Types

- **State-changing verbs**: confirm whether GET, HEAD, or OPTIONS perform state changes.
- **Simple content-types**: try simple content-types to avoid preflight: form-urlencoded, multipart, and plain text.
- **Parser coercion**: probe parsers that auto-coerce plain-text or form-encoded bodies into structured bodies.

### CORS Profile

- **Allow-origin and allow-credentials**: identify the allow-origin and allow-credentials response values.
- **Permissive CORS**: overly permissive CORS is not a CSRF fix and can turn CSRF into data exfiltration.
- **Per-endpoint differences**: test per-endpoint CORS differences; preflight vs simple request behavior can diverge.

## Detection Channels

- **Before-versus-after state comparison**: showing the intended effect without a proof of intent.
- **Missing-token acceptance**: showing the state change proceeds without the expected token.
- **Null-origin acceptance**: showing the state change proceeds from an empty-context delivery.
- **Per-endpoint encoding acceptance**: showing which simple encoding family succeeds per endpoint.
- **Storage-effect signal**: showing created plus modified plus deleted records after a delivery.
- **Confirmation-chain completion**: showing each chained navigation step executed in order.
- **Sending-scope observation**: showing the session cookie travels on the top-level navigation case.
- **Redirect-chain signal**: showing an authorization entry completed through navigation plus redirect following.
- **Coercion-applied signal**: showing the preflightless body executed with structured semantics.
- **Repeated-key plus collection-shape confusion signal**: showing the parser resolved the ambiguous shape into an action.
- **Override-acceptance signal**: showing the simple request executed as the stronger method.
- **Account-identity comparison**: showing the victim browser now sits in the attacker account.
- **Logout-clearing signal**: showing proof-of-intent state reset before planting.
- **Plant-acceptance signal**: showing the login flow accepted attacker-chosen credentials cross-origin.
- **Post-plant action attribution**: showing later victim actions land under the attacker account.
- **Handshake-acceptance signal**: showing the cross-site upgrade opened an authenticated channel.
- **Cookie-travel observation**: showing the session traveled on the upgrade request.
- **Origin-check outcome**: showing absent or permissive acceptance on the handshake path.
- **Over-socket action effect**: showing a subsequent socket message caused the intended state change.

## Adversarial Capabilities

- **Prerequisites**: CSRF testing presupposes a delivery surface the victim reaches, knowledge of the target action's shape, and a live victim session, and it consumes all three.
- **Attacker content delivery**: serve attacker content from a reachable origin and induce the victim to load it.
- **Request reconstruction**: reconstruct a state-changing request exactly as the target endpoint accepts it, including encoding and method.
- **Second browser profile**: hold a second browser profile with its own session to observe which account the effect lands in.
- **Effect reading**: read the durable effect of each attempt after the victim's browser returns.
- **Attacker credentials**: register attacker-held credentials when the flow under test is a login flow.

## Trust Assumptions

- **The agreement**: a request that changes state carries proof that the account owner intended it, and the browser's own scoping rules keep cross-site requests from carrying ambient authority.
- **The agreement clauses**: the agreement holds every state change to a non-replayable proof of intent, holds the session artifact to a scope that excludes cross-site delivery, holds the request parser to the shape the sender declared, and holds each transport to the same origin check as the browser channel.
- **The exposure**: sensitive position leaks when a request reaches a state change across origins with ambient authority and without proof of intent.
- **The failing clause**: each variant breaks one clause: the proof-of-intent clause, the scoping clause, the parser-clause, the identity clause of a login flow, or the transport clause of the socket handshake.

## Key Vulnerabilities

### Navigation CSRF

- **Auto-submitting form**: an auto-submitting form to the target origin works when cookies are sent and no token or origin checks are enforced.
- **Top-level GET navigation**: top-level GET navigation can trigger state if the server misuses GET or links actions to GET callbacks.

### Simple Content-Type CSRF

- **Form-urlencoded and multipart**: form-urlencoded and multipart POSTs do not require preflight.
- **Plain-text bodies**: plain-text form bodies can slip through validators and be parsed server-side.

### Structured-Body CSRF

- **Structured reconstruction**: if the server parses structured bodies from plain-text or form-encoded input, craft parameters that reconstruct the structure.
- **Duplicate keys**: some frameworks accept structured keys via form fields or treat duplicate keys leniently.

### Login/Logout CSRF

- **Logout-then-login chain**: force logout to clear anti-forgery state, then chain login CSRF to bind the victim to the attacker's account.
- **Login CSRF**: submit attacker credentials to the victim's browser; later actions occur under the attacker's account.

### OAuth/OIDC Flows

- **Authorize and logout endpoints**: abuse authorize/logout endpoints reachable via GET or form POST without origin checks.
- **Relaxed SameSite scope**: exploit relaxed SameSite scope on top-level navigations.
- **Open redirect chains**: open redirects or loose redirect validation can chain with CSRF to force unintended authorizations.

### File and Action Endpoints

- **File operations**: file upload/delete often lack token checks; forge multipart requests to modify storage.
- **Admin actions**: admin actions exposed as simple POST links are frequently forgeable.

### GraphQL CSRF

- **GET and persisted queries**: if queries/mutations are allowed via GET or persisted queries, exploit top-level navigation with encoded payloads.
- **Batched operations**: batched operations may hide mutations within a nominally safe request.

### WebSocket CSRF

- **Cookie carriage**: browsers send cookies on the WebSocket handshake.
- **Origin checks**: enforce Origin checks server-side; without them, cross-site pages can open authenticated sockets and issue actions.

## Bypass Techniques

### SameSite Nuance

- **Lax-by-default cookies**: Lax-by-default cookies are sent on top-level cross-site GET but not POST.
- **GET state changes**: exploit GET state changes and GET-based confirmation steps.
- **Nonstandard clients**: legacy or nonstandard clients may ignore SameSite; validate across browsers/devices.
- **Sibling-host same-site delivery**: a sibling host that shares the registrable site with the target makes the delivery same-site, so a lax-by-default cookie still travels; treat sibling ownership as a scoping input.

### Origin/Referer Obfuscation

- **Sandboxed frames**: sandboxed frames can produce a null origin; some frameworks incorrectly accept null.
- **Blank-document and data-URL origins**: blank-document and data-URL origins alter the referer value.
- **Explicit matching**: ensure the server requires an explicit origin or referer match.
- **Raw-client string satisfaction**: a naive string comparison on the origin or referrer value can be satisfied directly from a raw client, with no cross-origin page delivery; confirm the comparison shape before treating the check as enforced.

### Method Override

- **Override fields and headers**: backends honoring method-override fields or headers may allow destructive actions through a simple POST.

### Token Weaknesses

- **Missing or empty tokens**: accepting missing/empty tokens.
- **Unbound tokens**: tokens not tied to session, user, or path.
- **Reusable tokens**: tokens reused indefinitely; tokens carried in the URL.
- **Double-submit cookie**: double-submit cookie without Secure/HttpOnly, or with predictable token sources.
- **Presence-only antiforgery header**: a presence-only antiforgery header whose value is identical for every caller and is not bound to the user or the role: any same-origin script can present it, and the value replays across privilege partitions.
- **Token-cookie planting**: a double-submit token-cookie pairing falls where the token cookie can be planted through a response-header injection sink; name `header-injection` at the injection step rather than restating the line-break mechanics here.
- **DOM clobbering**: hostile markup can clobber a named element or a trusted global the proof-of-intent logic reads, so the token value or the submission target resolves to an attacker-chosen value; name `proxy-techniques-dom-clobbering` at that step rather than restating the mechanism here.
- **Style-channel token extraction**: a style channel can read a token value out of the rendered page one character at a time where markup is injectable; name `proxy-techniques-css-injection` at the extraction step rather than restating the mechanism here.

### Content-Type Switching

- **Content-type switching**: switch between form, multipart, and plain text to reach different code paths.
- **Duplicate keys and array shapes**: use duplicate keys and array shapes to confuse parsers.
- **Parser-step handoff**: name the defence-bypass family at its parser step for method-override framings and content-type switching, rather than restating those mechanics here.

### Header Manipulation

- **Referer stripping**: strip the referer via meta refresh or navigation from a blank document.
- **Null-origin acceptance**: test null-origin acceptance.
- **CORS-added custom headers**: leverage misconfigured CORS to add custom headers that servers mistakenly treat as anti-forgery tokens.
- **Path-family carve-out**: a carve-out that excludes one path family, such as a socket hub or a long-polling path, from the proof-of-intent check leaves the excluded family reachable under the same session authority.
- **Extended reading**: when this section does not fulfil the knowledge gap, extend the reading with the defence-bypass and proxy-techniques families.

## Chaining Attacks

- **CSRF plus IDOR**: force actions on other users' resources once references are known.
- **CSRF plus clickjacking**: guide user interactions to bypass UI confirmations.
- **CSRF plus OAuth mix-up**: bind victim sessions to unintended clients.
- **CSRF plus subdomain takeover**: a claimed sibling host plants a session cookie scoped to the parent domain, so the victim enters the application under an attacker-chosen session; name `subdomain-takeover` at the claim step rather than restating its procedure here.

## Testing Methodology

1. **Inventory endpoints** - All state-changing endpoints including admin/staff
2. **Note request details** - Method, content-type, whether reachable via simple requests
3. **Assess session model** - Cookies with SameSite attrs, custom headers, tokens
4. **Check defenses** - Anti-CSRF tokens and Origin/Referer enforcement
5. **Attempt preflightless delivery** - Form POST, plain text, multipart
6. **Test navigation** - Top-level GET navigation
7. **Cross-browser validation** - Behavior differs by SameSite and navigation context
8. **Confirm the effect** - Snapshot the state before and after each delivery, and the step completes when every delivery carries an effect verdict

## Variants

- csrf-form-post - Deliver preflightless cross-site form POSTs that replay endpoint semantics, covering multipart and plain-text shapes per endpoint.
- csrf-navigation-get - Chain top-level cross-site GET navigations that trigger state changes, including confirmation steps and staff GET tools.
- csrf-parser-differential - Reconstruct rich request semantics inside preflightless encodings that coerce to structured bodies, including override markers.
- csrf-login-fixation - Plant attacker-chosen credentials through cross-site login flows that permit fixation, then attribute later victim actions to the planted account.
- csrf-websocket-handshake - Open authenticated cross-site socket handshakes that rely on origin checks alone, then issue over-socket actions.

## False Positives

- **Enforced defenses**: token verification present and required; Origin/Referer enforced consistently.
- **No ambient authority**: no cookies sent on cross-site requests (SameSite=Strict, no HTTP auth) and no state change via simple requests.
- **Idempotent operations**: only idempotent, non-sensitive operations affected.

## Pro Tips

- **Preflightless vectors**: prefer preflightless vectors (form-encoded, multipart, plain text) and top-level GET if available.
- **First targets**: test login/logout, OAuth connect/disconnect, and account linking first.
- **Origin and referer validation**: validate Origin/Referer behavior explicitly; do not assume frameworks enforce them.
- **SameSite toggling**: toggle SameSite and observe differences across navigation vs scripted requests.
- **GraphQL**: for GraphQL, attempt GET queries or persisted queries that carry mutations.
- **Overrides and differentials**: always try method overrides and parser differentials.
- **Clickjacking combination**: combine with clickjacking when visual confirmations block CSRF.

## Summary

CSRF is eliminated only when state changes require a secret the attacker cannot supply and the server verifies the caller's origin. Tokens and Origin checks must hold across methods, content-types, and transports.
