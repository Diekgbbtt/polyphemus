---
name: header-injection
description: HTTP header injection testing covering CRLF / response splitting, cache poisoning, Host-header confusion, cookie fixation, and proxy / forwarding header smuggling
metadata:
  version: 1.0.0
---

# HTTP Header Injection

Header injection turns user input into protocol-level control: response splitting, cache poisoning, session fixation, authentication bypass, and request smuggling all trace back to a server-controlled header value that was not normalized. The bug usually lives in middle layers - frameworks that copy a request value into a response header, proxies that trust forwarded headers, caches keyed on something the attacker influences. Treat any user-controlled value that reaches a header as code-execution-equivalent until proven otherwise.

## Attack Surface

**Input shapes that reach headers**
- Query, body, and path values echoed into response headers: cookie setters, location, content type and disposition, link, custom fields
- Request headers re-emitted into responses (referer, client, correlation, and forwarding families)
- Webhook and callback flows where the server constructs outbound requests using user-supplied URLs
- Outbound message headers populated from user input

**Code patterns that enable injection**
- Direct concatenation of user input into header values without line-break stripping
- Frameworks that accept header values as strings and serialize them verbatim (no normalization)
- Proxy chains trusting forwarding headers set by an upstream that anyone can spoof
- Method-shaping headers respected past the authorization layer

**Transports and parser layers**
- Each HTTP version parses framing differently
- Edge to application server, where the two sides may disagree on framing
- Chunked transfer boundaries and multipart delimiters

## Reconnaissance

### Header Inventory

- Enumerate every response header that varies with input: flip query, body, and cookie values and diff the cookie, location, content-type, disposition, validator, and cache-control fields
- For each varying header, identify the source field (user-controlled vs server-derived)
- Look for request headers reflected into responses, such as the referer echoed into error pages or a correlation identifier

### Line-Break and Whitespace Variants

- Bare line feed, bare carriage return, and the CRLF pair
- Double encoding for filters that decode once
- Overlong encodings of the line-break bytes, accepted by some parsers although invalid
- Unicode line and paragraph separators, sometimes folded to a line feed by intermediaries
- Tab and leading whitespace, which the syntax allows inside field values
- Null byte, which truncates the value in some parsers

### Parser and Layer Fingerprinting

- Server, proxy, and platform banners reveal the stack
- Cache-signal headers reveal the caching layer and its key composition
- The same probe over HTTP/1.1, HTTP/2, and chunked framing: diff status, headers, and body length to map parsing differences
- Compare the authority header against its forwarding aliases: send both with different values and observe which wins in redirects, links, and stored entries

## Detection Channels

- An injected second header field stored and served downstream as a real field, which binds the probe to parser trust.
- A second response served to an unrelated clean request, which proves the injected framing left the attack session.
- A header-set diff between the attack replay and a clean replay, which isolates the injected field from ambient variation.
- Cache-signal values showing a stored entry behind a poisoned body, which confirms downstream persistence.
- An attacker-influenced body served under a victim key on clean replay, which binds the probe to the key-versus-content split.
- An emitted link destination carrying an attacker host, which proves the URL builder consumed the forgery.
- Out-of-band arrival of a token-bearing link at attacker infrastructure, which confirms the emitted destination leaves the building.
- An access decision flip with and without a forged forwarding alias.
- A guarded handler reached through a safe method plus an override carrier while the direct method stays refused.
- A guarded path served through a rewrite carrier while the direct guarded request stays refused.
- Victim request data appended to another request, which binds the probe to leftover bytes across the boundary.
- A response-queue anomaly, namely a response answering a request that was never sent.
- A timing plus length diff between the paired replay and a clean sequential baseline.
- A cookie-jar state change: widened scope, a persisted attacker cookie, or a shadowed session name.
- A render behaviour change, namely a body rendered as script-capable content after a media-value replacement.
- Navigation to a replaced destination inside the same response.

## Adversarial Capabilities

Header injection testing presupposes a knob that reaches a header, knowledge of the middle layers, and a second session to observe cross-user effects, and it consumes all three.
- Supply input that reaches a response header, a request header, or an outbound message header.
- Send probes that differ only in one header field so the winning value attributes cleanly.
- Reach the target through the full chain, edge first, rather than direct to the application.
- Hold a second session and a cache observation key so cross-user serving can be proven on clean replay.
- Host or reference an external destination when the emitted link or the resolved authority leaves the building.
- Read the stored entry behind the response, not only the current reply.

## Trust Assumptions

The class rests on one agreement: every value that reaches a header is normalized so that input stays a value, and every intermediary binds the message framing to the request that declared it.
The agreement holds header values free of line breaks, holds the authority and forwarding families to values set by the layer that terminates the connection, holds the cache key to cover everything that shapes the body, and holds each hop to the same framing declaration.
Sensitive position and session control leak when any clause fails: a value breaks out of its field, an upstream alias overrides a decision, or a cache stores a body under a key that another user also reaches.
Each variant breaks one clause: the normalization clause, the authority clause, the cache-key clause, the framing clause, or the same-response semantics clause.

## Key Vulnerabilities

### CRLF Response Splitting and Smuggling

Injecting a line-break pair terminates the current response and starts an attacker-controlled one. A cache or downstream proxy may key on the first response and serve the second to other users.

Request smuggling is the same primitive at the request layer: inject a header that makes the proxy and the backend disagree on message framing, most commonly conflicting length and encoding declarations or two length fields with different values. The front-end reads one request and the backend another; the leftover bytes become a smuggled request prepended to the next connection.

### Cache Poisoning

- **Unkeyed input to keyed response**: input that influences the body but not the cache key, such as a forwarding alias echoed into a link or an unkeyed parameter reflected into markup
- **Cache-control manipulation**: inject a freshness or eligibility value to flip an entry private or shared, or to extend its life
- **Forwarding alias poisoning**: the backend builds canonical URLs from forwarded values, and the cache stores the response with attacker-controlled links
- **Cache deception**: trick the cache into storing an authenticated response at a public-looking URL by appending a cacheable extension

### Authority Confusion

Backends often trust the authority header or its forwarding alias when constructing absolute URLs: password reset messages, authorization callbacks, canonical links. A forged authority produces a message pointing at attacker infrastructure that still carries the victim's token.

Also test precedence between the authority header and its aliases, bracketed and trailing-dot forms, and port confusion shapes.

### Cookie Manipulation

- Widen the scope of an attacker-set cookie through a broader domain or path attribute
- Relax the cross-site attribute so the cookie travels on cross-site requests
- Set a long lifetime for persistence, or a negative lifetime to destroy the victim's session
- Shadow a real session cookie by reusing its name, where precedence rules favor the later entry
- Reflected cookie rendering: the injection point is the header and the sink is the page

### Forwarding Header Spoofing

The forwarding family is informational: no protocol guarantee says who set it. Any application that trusts it past the boundary it controls is exploitable.

- A loopback value in a client-address header bypasses IP allowlists or rate limits
- A scheme value satisfying "secure transport only" checks while the connection stays unencrypted
- An authority alias feeding the confusion variants above
- Rewrite and override headers honored after the authorization check, the classic guarded-path bypass
- Address families under several names: spray all of them, since each layer may read a different one

### Content-Type and Encoding Confusion

- Inject an HTML media type into an endpoint that returned structured data; browsers may sniff and render it
- Inject a legacy charset to enable encoded-script rendering
- Inject an inline disposition to switch a download into in-page rendering
- Inject a content-encoding declaration without compressing; clients decode-fail and may reveal raw bytes in error paths
- A missing sniffing-prevention header on some endpoints is what enables the sniffing attacks above; target the endpoints that lack it

### Script and Redirect Sinks in Headers

- A location header whose target is reflected unescaped reaches legacy clients and embedded hosts
- A refresh-style header carries the same navigation without script
- Reflected request headers rendered into an error page or a debug field combine header injection with a body sink
- A server-internal rewrite header makes internal-only files reachable when user input reaches it

### HTTP/2 Pseudo-Header and Frame Confusion

- HTTP/2 splits framing into pseudo-headers and regular fields; servers downgrading to HTTP/1.1 sometimes mishandle pseudo-header values, enabling smuggling across the boundary
- HTTP/2 lowercases header names; an upstream filter that is case-sensitive may miss the lowercase variant
- Header-block frame splitting: a payload spans frames and intermediaries differ on whether they reassemble before filtering

## Bypass Techniques

**Encoding**
- URL-encode and double-encode for filters that decode the wrong number of times
- Mix encodings inside one probe: alternate case and mixed escape forms
- Newline-equivalent Unicode and overlong encodings

**Header normalization edges**
- Leading and trailing whitespace and tabs in field names and values
- Field folding: continuation lines starting with whitespace, formally obsolete but still accepted by some parsers
- Duplicate fields: the syntax says join, but servers pick the first, the last, or differ from the proxy in front of them

**Method and method-override**
- Method-override headers reach state-changing handlers when the framework consults the override before method-based authorization
- Effective from server-side and non-browser callers; from a browser the override header triggers a preflight, so it is not on its own a cross-site primitive

**Header name games**
- Case mangling for filters that key off exact casing
- Null-byte truncation inside the field name on parsers that stop at the null

## Chaining Attacks

- Header injection plus cache poisoning: the poisoned entry serves the injected body to every later requester
- Header injection plus cross-site scripting: the injected field becomes a script sink once the body is rendered
- Authority confusion plus recovery flows: the forged link carries a live token to attacker infrastructure
- Forwarding spoof plus access control: the decision flips without touching credentials
- Framing disagreement plus authentication bypass: the smuggled request skips the front-end check

## Testing Methodology

1. **Inventory varying headers** - Enumerate every response header whose value moves with input; the step completes when each varying field carries its source
2. **Probe normalization** - Inject line-break variants into each varying source; the step completes when each source carries a stripped or a landed verdict
3. **Test the authority family** - Submit a link-generating flow with a forged authority and its aliases; the step completes when the emitted destination is recorded per alias
4. **Probe forwarding headers** - Spoof the client-address and scheme families against restricted endpoints; the step completes when each decision carries a with-and-without verdict
5. **Test cache key versus content** - Find inputs that change the body but not the key; the step completes when a clean second session observes the stored entry
6. **Test override carriers** - Override headers paired with state-changing handlers; the step completes when the guarded path carries a reach-through verdict
7. **Test framing pairs** - Conflicting length and encoding declarations, duplicate length fields, malformed chunked framing against the front-end to backend pair; the step completes when each pair carries a desync verdict
8. **Cross-version replay** - Replay each interesting probe over both protocol versions; the step completes when the behaviour diff is recorded

## Variants

- header-crlf-splitting - Split responses when line-break payloads land as stored header fields, then bend downstream storage with injected framing.
- header-cache-poisoning - Poison shared caches with unkeyed input that shapes cached bodies, covering fragmentation, eligibility, and deception sub-shapes.
- header-host-forward-spoof - Spoof the authority and forwarding families to bend emitted links and access decisions, mapping each alias to its outcome.
- header-method-override - Override the routed method or rewrite the path past authorization checks, proving the reroute lands before the check.
- header-request-smuggling - Smuggle requests through framing disagreements between chained parsers, pairing length against encoding declarations.
- header-response-value-confusion - Confuse same-response header semantics without line breaks, rewriting cookie attributes, media types, and redirect targets.

## False Positives

- Headers that vary by input but are correctly keyed in the cache (intentional personalization, cache-key variation set correctly)
- Forwarding values reflected back but used only for logging, which is not a security boundary
- Client-side refusal to navigate to script or data destinations, which leaves the protocol capability without a live sink
- Line breaks appearing in a response but stripped by an outer proxy before reaching any client or cache
- Framing indicators that turn out to be ordinary pipelining or keep-alive behavior

## Pro Tips

1. The fastest win is usually a forged authority in a recovery or authorization flow; try it first, it costs one request
2. For cache poisoning, find the unkeyed input first; the rest follows
3. Override headers are high-yield against backends that route on them before checking method-based auth, most useful from server-side callers
4. Smuggling lives at the boundary: identify the pair and target the framing disagreement
5. Rewrite headers against guarded paths remain a high-yield bypass on stacks that honor them
6. Before claiming a splitting win, verify the second field landed as a real field in the cache or downstream consumer
7. Outbound message flows are a related surface with the same root cause: user input reaching message headers

## Summary

Header injection is fundamentally a normalization failure: somewhere on the request-to-response path, user input reached a header value without line-break stripping or proper escaping. The impact tiers up from redirection to cache poisoning to request smuggling depending on which downstream component trusts the resulting header. Audit every header whose value moves with input, and treat every authority or forwarding trust as a security boundary that needs explicit justification.
