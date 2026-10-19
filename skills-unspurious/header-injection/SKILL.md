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
- **Query, body, and path values echoed into response headers**: cookie setters, location, content type and disposition, link, custom fields
- **Request headers re-emitted into responses**: referer, client, correlation, and forwarding families
- **Webhook and callback flows**: where the server constructs outbound requests using user-supplied URLs
- **Outbound message headers**: populated from user input

**Code patterns that enable injection**
- **Direct concatenation**: direct concatenation of user input into header values without line-break stripping
- **Verbatim serialization**: frameworks that accept header values as strings and serialize them verbatim (no normalization)
- **Upstream trust**: proxy chains trusting forwarding headers set by an upstream that anyone can spoof
- **Method-shaping headers**: method-shaping headers respected past the authorization layer

**Transports and parser layers**
- **Protocol-version framing**: each HTTP version parses framing differently
- **Edge-to-application boundary**: edge to application server, where the two sides may disagree on framing
- **Transfer boundaries**: chunked transfer boundaries and multipart delimiters

## Reconnaissance

### Header Inventory

- **Varying-header inventory**: enumerate every response header that varies with input - flip query, body, and cookie values and diff the cookie, location, content-type, disposition, validator, and cache-control fields
- **Source attribution**: for each varying header, identify the source field (user-controlled vs server-derived)
- **Reflected request headers**: look for request headers reflected into responses, such as the referer echoed into error pages or a correlation identifier

### Line-Break and Whitespace Variants

- **Bare line-break bytes**: bare line feed, bare carriage return, and the CRLF pair
- **Double encoding**: double encoding for filters that decode once
- **Overlong encodings**: overlong encodings of the line-break bytes, accepted by some parsers although invalid
- **Unicode separators**: Unicode line and paragraph separators, sometimes folded to a line feed by intermediaries
- **Tab and whitespace**: tab and leading whitespace, which the syntax allows inside field values
- **Null byte**: null byte, which truncates the value in some parsers

### Parser and Layer Fingerprinting

- **Banners**: server, proxy, and platform banners reveal the stack
- **Cache-signal headers**: cache-signal headers reveal the caching layer and its key composition
- **Cross-version probing**: the same probe over HTTP/1.1, HTTP/2, and chunked framing - diff status, headers, and body length to map parsing differences
- **Authority-versus-alias probing**: compare the authority header against its forwarding aliases - send both with different values and observe which wins in redirects, links, and stored entries

## Detection Channels

- **Stored second field**: an injected second header field stored and served downstream as a real field, which binds the probe to parser trust.
- **Second response**: a second response served to an unrelated clean request, which proves the injected framing left the attack session.
- **Header-set diff**: a header-set diff between the attack replay and a clean replay, which isolates the injected field from ambient variation.
- **Cache-signal persistence**: cache-signal values showing a stored entry behind a poisoned body, which confirms downstream persistence.
- **Clean-replay body serving**: an attacker-influenced body served under a victim key on clean replay, which binds the probe to the key-versus-content split.
- **Emitted link destination**: an emitted link destination carrying an attacker host, which proves the URL builder consumed the forgery.
- **Out-of-band link arrival**: out-of-band arrival of a token-bearing link at attacker infrastructure, which confirms the emitted destination leaves the building.
- **Access decision flip**: an access decision flip with and without a forged forwarding alias.
- **Override-carrier reach**: a guarded handler reached through a safe method plus an override carrier while the direct method stays refused.
- **Rewrite-carrier reach**: a guarded path served through a rewrite carrier while the direct guarded request stays refused.
- **Leftover-bytes disclosure**: victim request data appended to another request, which binds the probe to leftover bytes across the boundary.
- **Response-queue anomaly**: a response-queue anomaly, namely a response answering a request that was never sent.
- **Timing and length diff**: a timing plus length diff between the paired replay and a clean sequential baseline.
- **Cookie-jar state change**: widened scope, a persisted attacker cookie, or a shadowed session name.
- **Render behaviour change**: a body rendered as script-capable content after a media-value replacement.
- **Virtual-host read-out**: a status or size delta across forged authority values, which names the default virtual host and the interior hosts behind the edge.
- **Replaced navigation**: navigation to a replaced destination inside the same response.

## Adversarial Capabilities

- **Testing prerequisites**: a knob that reaches a header, knowledge of the middle layers, and a second session to observe cross-user effects, which the class consumes.
- **Header-reaching input**: supply input that reaches a response header, a request header, or an outbound message header.
- **Single-field differential**: send probes that differ only in one header field so the winning value attributes cleanly.
- **Full-chain reach**: reach the target through the full chain, edge first, rather than direct to the application.
- **Second session**: hold a second session and a cache observation key so cross-user serving can be proven on clean replay.
- **External destination**: host or reference an external destination when the emitted link or the resolved authority leaves the building.
- **Stored-entry read**: read the stored entry behind the response, not only the current reply.

## Trust Assumptions

- **The agreement**: every value that reaches a header is normalized so that input stays a value, and every intermediary binds the message framing to the request that declared it.
- **Held conditions**: the agreement holds header values free of line breaks, holds the authority and forwarding families to values set by the layer that terminates the connection, holds the cache key to cover everything that shapes the body, and holds each hop to the same framing declaration.
- **The failing clause**: sensitive position and session control leak when any clause fails - a value breaks out of its field, an upstream alias overrides a decision, or a cache stores a body under a key that another user also reaches.
- **Variant clauses**: each variant breaks one clause - the normalization clause, the authority clause, the cache-key clause, the framing clause, or the same-response semantics clause.

## Key Vulnerabilities

### CRLF Response Splitting and Smuggling

- **Response splitting**: injecting a line-break pair terminates the current response and starts an attacker-controlled one. A cache or downstream proxy may key on the first response and serve the second to other users.
- **Request-layer smuggling**: request smuggling is the same primitive at the request layer - inject a header that makes the proxy and the backend disagree on message framing, most commonly conflicting length and encoding declarations or two length fields with different values. The front-end reads one request and the backend another; the leftover bytes become a smuggled request prepended to the next connection.

### Cache Poisoning

- **Unkeyed input to keyed response**: input that influences the body but not the cache key, such as a forwarding alias echoed into a link or an unkeyed parameter reflected into markup
- **Cache-control manipulation**: inject a freshness or eligibility value to flip an entry private or shared, or to extend its life
- **Forwarding alias poisoning**: the backend builds canonical URLs from forwarded values, and the cache stores the response with attacker-controlled links
- **Cache deception**: trick the cache into storing an authenticated response at a public-looking URL by appending a cacheable extension
- **Keying-mechanics ownership**: the shared-cache keying mechanics these shapes work are the proxy-techniques family's step; name it there and keep the injection detail here.

### Authority Confusion

- **Authority trust**: backends often trust the authority header or its forwarding alias when constructing absolute URLs - password reset messages, authorization callbacks, canonical links. A forged authority produces a message pointing at attacker infrastructure that still carries the victim's token.
- **Precedence and shape testing**: also test precedence between the authority header and its aliases, bracketed and trailing-dot forms, and port confusion shapes.
- **Double authority and absolute-target shapes**: send a second authority field, and send an absolute request target whose authority differs from the field, so the precedence order decides which layer reads which value
- **Discovery-document oracle**: a discovery document that publishes issuer and endpoint addresses is a second link-generating oracle beside a reset or callback flow, because the authority family is rebuilt into every published address
- **Routing versus rewriting**: an authority that selects the upstream the front end forwards to and a rewrite header that changes the routed path act at different layers and never compose; the interior-body read that follows a routed fetch escalates to the `ssrf` class

### Cookie Manipulation

- **Scope widening**: widen the scope of an attacker-set cookie through a broader domain or path attribute
- **Cross-site relaxation**: relax the cross-site attribute so the cookie travels on cross-site requests
- **Lifetime control**: set a long lifetime for persistence, or a negative lifetime to destroy the victim's session
- **Name shadowing**: shadow a real session cookie by reusing its name, where precedence rules favor the later entry
- **Reflected cookie rendering**: the injection point is the header and the sink is the page

### Forwarding Header Spoofing

- **Informational family**: the forwarding family is informational - no protocol guarantee says who set it. Any application that trusts it past the boundary it controls is exploitable.
- **Loopback value**: a loopback value in a client-address header bypasses IP allowlists or rate limits
- **Scheme value**: a scheme value satisfying "secure transport only" checks while the connection stays unencrypted
- **Authority alias**: an authority alias feeding the confusion variants above
- **Rewrite and override headers**: rewrite and override headers honored after the authorization check, the classic guarded-path bypass
- **Address families under several names**: spray all of them, since each layer may read a different one
- **Relay-mechanics ownership**: the relay mechanics these shapes work are the proxy-techniques family's relay step; name it there and keep the header-shape detail here.
See references/forwarded-field-families.md for the family list with its per-family consumer and read-out.

### Content-Type and Encoding Confusion

- **HTML media type**: inject an HTML media type into an endpoint that returned structured data; browsers may sniff and render it
- **Legacy charset**: inject a legacy charset to enable encoded-script rendering
- **Inline disposition**: inject an inline disposition to switch a download into in-page rendering
- **Content-encoding declaration**: inject a content-encoding declaration without compressing; clients decode-fail and may reveal raw bytes in error paths
- **Missing sniffing-prevention header**: a missing sniffing-prevention header on some endpoints is what enables the sniffing attacks above; target the endpoints that lack it

### Script and Redirect Sinks in Headers

- **Location header**: a location header whose target is reflected unescaped reaches legacy clients and embedded hosts
- **Refresh-style header**: a refresh-style header carries the same navigation without script
- **Reflected request headers**: reflected request headers rendered into an error page or a debug field combine header injection with a body sink
- **Server-internal rewrite header**: a server-internal rewrite header makes internal-only files reachable when user input reaches it

### HTTP/2 Pseudo-Header and Frame Confusion

- **Pseudo-header handling**: HTTP/2 splits framing into pseudo-headers and regular fields; servers downgrading to HTTP/1.1 sometimes mishandle pseudo-header values, enabling smuggling across the boundary
- **Lowercased names**: HTTP/2 lowercases header names; an upstream filter that is case-sensitive may miss the lowercase variant
- **Header-block frame splitting**: a payload spans frames and intermediaries differ on whether they reassemble before filtering

## Bypass Techniques

**Encoding**
- **Double encoding**: URL-encode and double-encode for filters that decode the wrong number of times
- **Mixed encodings**: mix encodings inside one probe - alternate case and mixed escape forms
- **Newline equivalents**: newline-equivalent Unicode and overlong encodings

**Header normalization edges**
- **Surrounding whitespace**: leading and trailing whitespace and tabs in field names and values
- **Field folding**: continuation lines starting with whitespace, formally obsolete but still accepted by some parsers
- **Duplicate fields**: the syntax says join, but servers pick the first, the last, or differ from the proxy in front of them

**Method and method-override**
- **Override before authorization**: method-override headers reach state-changing handlers when the framework consults the override before method-based authorization
- **Caller classes**: effective from server-side and non-browser callers; from a browser the override header triggers a preflight, so it is not on its own a cross-site primitive

**Header name games**
- **Case mangling**: case mangling for filters that key off exact casing
- **Null-byte truncation**: null-byte truncation inside the field name on parsers that stop at the null

When this section does not fulfil the knowledge gap, extend the reading with the defence-bypass and proxy-techniques families.

## Chaining Attacks

- **Header injection plus cache poisoning**: the poisoned entry serves the injected body to every later requester
- **Header injection plus cross-site scripting**: the injected field becomes a script sink once the body is rendered
- **Authority confusion plus recovery flows**: the forged link carries a live token to attacker infrastructure
- **Forwarding spoof plus access control**: the decision flips without touching credentials
- **Framing disagreement plus authentication bypass**: the smuggled request skips the front-end check

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

- **Correctly keyed variation**: headers that vary by input but are correctly keyed in the cache (intentional personalization, cache-key variation set correctly)
- **Logging-only reflection**: forwarding values reflected back but used only for logging, which is not a security boundary
- **Client-side refusal**: client-side refusal to navigate to script or data destinations, which leaves the protocol capability without a live sink
- **Outer-proxy stripping**: line breaks appearing in a response but stripped by an outer proxy before reaching any client or cache
- **Ordinary pipelining**: framing indicators that turn out to be ordinary pipelining or keep-alive behavior

## Pro Tips

- **Forged authority first**: the fastest win is usually a forged authority in a recovery or authorization flow; try it first, it costs one request
- **Unkeyed input first**: for cache poisoning, find the unkeyed input first; the rest follows
- **Override headers**: override headers are high-yield against backends that route on them before checking method-based auth, most useful from server-side callers
- **Smuggling lives at the boundary**: identify the pair and target the framing disagreement
- **Rewrite headers against guarded paths**: rewrite headers against guarded paths remain a high-yield bypass on stacks that honor them
- **Splitting-win verification**: before claiming a splitting win, verify the second field landed as a real field in the cache or downstream consumer
- **Outbound message flows**: outbound message flows are a related surface with the same root cause - user input reaching message headers

## Summary

Header injection is fundamentally a normalization failure: somewhere on the request-to-response path, user input reached a header value without line-break stripping or proper escaping. The impact tiers up from redirection to cache poisoning to request smuggling depending on which downstream component trusts the resulting header. Audit every header whose value moves with input, and treat every authority or forwarding trust as a security boundary that needs explicit justification.
