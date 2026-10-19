# D1a enrichment proposal - slice 1

*Report only. No suite skill was modified. No git command was run. The orchestrator commits.*

## Slice header

- Groups (base suite level-1 directories): 6 - `authentication-jwt`, `oauth`, `csrf`, `http-method-tampering`, `open-redirect`, `subdomain-takeover`.
- Base skills (parents): 6.
- Variant leaves: 24 (`authentication-jwt` 4, `oauth` 5, `csrf` 5, `http-method-tampering` 4, `open-redirect` 3, `subdomain-takeover` 3).
- Suite files in scope: 30 `SKILL.md`.
- Base location: `/Users/diekgbbtt/polymerhus/.claude/worktrees/feat-w7-enrichment/skills-unspurious/`.
- Normative docs read: `/Users/diekgbbtt/polymerhus/.claude/worktrees/feat-w7-enrichment/docs/design/skills-variant-boundary.md` and `.../docs/design/skills-ontology.md`.
- Per-class boundary signatures read from `skills-unspurious/_analysis/<class>.md` (section 11 recommended set, section 6 non-discriminators, section 7 grey points).
- Sources indexed: `/Users/diekgbbtt/hacking-skills/skills` (43 `SKILL.md`); `/Users/diekgbbtt/claude-bug-hunter/skills` (83 `SKILL.md`); `/Users/diekgbbtt/awsome-offensive-security-skill/skills` (138 `SKILL.md`); `/Users/diekgbbtt/anthropic-cybersecurity-skills` (82 `SKILL.md` under `accepted/`, plus 818 catalog entries in `catalog/catalog.json`; catalog-only entries carry description only).
- Method note: the operator algorithm is obeyed literally. Where similarity is not sufficient, the boundary doc decides. Per the operator example, a source skill whose baseline the suite does not carry is reported as a non-match, never proposed.
- Confidence legend: HIGH, MEDIUM, LOW. Low-confidence items are flagged inline.

---

## authentication-jwt

Parent: `authentication-jwt/SKILL.md`. Variant leaves: `jwt-signature-forgery`, `jwt-key-resolution`, `jwt-claims-confusion`, `jwt-flow-lifecycle`.
Boundary signature (from `_analysis/authentication-jwt.md`): the class splits by which token-validity binding the test breaks - signature-algorithm, key-resolution, claims-context, flow-lifecycle.
Open question in the analysis: JWE decryption and content confusion could be a fifth variant once a JWE methodology exists.

**Sources matched**

- `/Users/diekgbbtt/hacking-skills/skills/web/auth/jwt-misconfig/SKILL.md` - alg:none, RS256 to HS256 confusion, weak HMAC cracking, kid path traversal and SQLi, jku/x5u, embedded jwk, expiry skip.
- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-jwt-crypto/SKILL.md` - the same forgery set plus cross-tenant claim injection (`org_id`/`tenant_id` swap) and an admin-objective escalation sequence.
- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/api-security/jwt-forgery-algorithm-confusion/SKILL.md` - algorithm confusion and none-alg, decision flow.
- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/apis/jwt-algorithm-confusion/SKILL.md` - algorithm confusion.
- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/apis/jwt-null-signature/SKILL.md` - none-alg.
- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/deep-dive-labs/jwt-labs/SKILL.md` - lab playbooks for unverified signature, jwk, jku, kid traversal, algorithm confusion.
- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W1/exploiting-jwt-algorithm-confusion-attack/SKILL.md` - algorithm confusion.
- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W1/performing-jwt-none-algorithm-attack/SKILL.md` - none-alg.
- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W1/testing-jwt-token-security/SKILL.md` - forgery, key injection, claim tampering, lifetime and revocation.
- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W1/testing-for-json-web-token-vulnerabilities/SKILL.md` - the same forgery and key-resolution set.
- Catalog-only (description assessed): `testing-api-authentication-weaknesses` (API auth breadth), `implementing-jwt-signing-and-verification` (defensive hardening), `attacking-oauth-with-device-code-phishing`, `detecting-oauth-token-theft`.
- Non-match candidates read: `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-saml/SKILL.md` (SAML assertion attacks), `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-auth-bypass/SKILL.md` (cross-protocol auth bypass and legacy-protocol matrix), `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W1/exploiting-type-juggling-vulnerabilities/SKILL.md` (PHP loose comparison).

**Similarity**

- Sufficient for the forgery, key-resolution, claims, and lifetime sources. Every technique they carry maps to an existing variant or a named aspect.
- Insufficient (out of class) for the SAML/SSO, legacy-protocol, and type-juggling sources.

**Boundary**

- JWT forgery and key sources: no boundary attribute diverges. The base already owns signature-algorithm trust, key-resolution control, claims-context acceptance, and flow lifecycle.
- SAML assertion attacks (`hunt-saml`, `hunt-auth-bypass`): the communication protocol, the attack-surface part family, the trust assumption, and the impact all diverge from JWT/OIDC. However, SAML needs an assertion-semantics and XML-signature-validation baseline the suite does not carry (the `xxe` class carries XML parsing, not SAML assertion trust). Per the operator rule this is a NON-MATCH, not a proposal. HIGH confidence on the non-match.
- Legacy-protocol auth bypass (`hunt-auth-bypass` legacy-endpoint matrix: XMLRPC, SOAP, REST, and `.asmx` endpoints accept native credentials while the UI enforces SSO): a distinct authentication-bypass class whose per-platform endpoint baseline is absent from the suite. NON-MATCH, and it is owned outside this slice (`weak-credential-discovery` or a future auth-bypass class). HIGH confidence.
- PHP type juggling (`exploiting-type-juggling-vulnerabilities`): a language-level comparison class, not token validation. NON-MATCH. HIGH confidence.

**New-skill proposals**

- None. The one boundary divergence found (SAML, legacy-protocol bypass) fails the operator's baseline test, so it is deliberately not proposed.

**Enrichment candidates**

- `AttackTechnique` (Chaining Attacks) <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-jwt-crypto/SKILL.md`: satisfy a `jku`/`x5u` host allowlist by chaining an open redirect or an SSRF-reachable path on the target's own domain so the key fetch resolves to the attacker JWKS. The base names remote-key SSRF generally but not the allowlist-satisfying redirect shape. LOW confidence, small delta.
- `AttackTechnique` (Key Vulnerabilities) <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-jwt-crypto/SKILL.md`: cross-tenant claim swap (`org_id`, `tenant_id`, `workspace_id`) as an explicit claims-confusion shape. This is already an aspect of `jwt-claims-confusion` under the analysis (claim choice is an aspect), so it is a wording-level add only. LOW confidence.

**References/scripts candidates**

- None. The corpus supplies concrete token literals and lab payloads, which violate the abstractness rule (ontology doc section 7).

---

## oauth

Parent: `oauth/SKILL.md`. Variant leaves: `oauth-redirect-uri-validation`, `oauth-state-nonce-csrf`, `oauth-pkce-enforcement`, `oauth-code-client-binding`, `oauth-device-approval`.
Boundary signature (from `_analysis/oauth.md`): the class splits by which authorize-to-token binding check bends its probe step - redirect validation, freshness (state/nonce), PKCE verifier binding, code-and-token-to-client binding, plus the device-approval channel.
The analysis explicitly discarded flow-label splits (H3) and token-format splits (H4), and kept transport, Referer, dynamic-registration, scope, and secret values as aspects.

**Sources matched**

- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-oauth/SKILL.md` - redirect_uri bypass table, state and nonce abuse, PKCE bypass, dynamic registration, cross-client confusion, Referer leak, mobile deep links, plus the "Dirty Dancing" response-type swap, `response_mode=web_message` and postMessage interception, `prompt=none` silent re-auth, IdP `sub` collision, mutable email claim, and unverified-email token-endpoint bypass.
- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/api-security/oauth-flow-exploitation/SKILL.md` - redirect_uri theft, state CSRF account linking, implicit-flow leakage.
- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/logic-flaws/oauth-state-parameter-abuse/SKILL.md` - state CSRF account linking (malformed body, low value).
- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/deep-dive-labs/oauth/SKILL.md` - lab playbooks including SSRF via dynamic-registration metadata (`logo_uri` to a metadata endpoint) and forced profile linking.
- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W1/exploiting-oauth-misconfiguration/SKILL.md` - redirect_uri bypass, code reuse, scope escalation, account-linking, token revocation.
- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W1/testing-oauth2-implementation-flaws/SKILL.md` - redirect_uri matrix, state, PKCE bypass, scope, implicit flow, code replay.
- Catalog-only (description assessed): `attacking-oauth-with-device-code-phishing` (device-code and illicit-consent phishing), `detecting-oauth-token-theft` (defensive), `performing-oauth-scope-minimization-review` (defensive review), `configuring-oauth2-authorization-flow` (defensive config).

**Similarity**

- Sufficient for the redirect, state, PKCE, binding, and device sources. The bulk restates the base.
- Novel delta is concentrated in `hunt-oauth` and in the awsome deep-dive registration-SSRF lab.

**Boundary**

- No boundary attribute diverges. The novel items are delivery-channel, sequencing, and sink values, which the analysis classifies as aspects inside existing variants.
- Cross-window delivery ("Dirty Dancing"): the `response_mode`/postMessage delivery channel is a communication-protocol value. The boundary doc states the protocol is usually a runtime or class-selection concern rather than a variant axis, and the analysis already discarded flow-label splits. It is an ASPECT, not a variant. MEDIUM confidence on keeping it an aspect.

**New-skill proposals**

- None. The one borderline candidate (a `web-message`/response-mode variant) is rejected because it bends no step kind beyond the destination-delivery clause the redirect variant already owns.

**Enrichment candidates**

- `AttackTechnique` (Advanced Techniques) <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-oauth/SKILL.md`: cross-window credential delivery where `response_mode=web_message` returns the code to a parent window and a lax postMessage origin check lets the attacker read it, defeating destination binding without a browser navigation. Add as an aspect of `oauth-redirect-uri-validation`. MEDIUM confidence.
- `AttackTechnique` (Key Vulnerabilities) <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-oauth/SKILL.md`: prerequisite-step completeness check at the token endpoint, where a credential is issued to an account that never completed email verification or another prerequisite step. This is a flow-completeness clause the base does not name. Add to `oauth-code-client-binding`. MEDIUM confidence.
- `AttackTechnique` (Key Vulnerabilities) <- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/deep-dive-labs/oauth/SKILL.md`: dynamic-registration metadata fields (`logo_uri`, `jwks_uri`, `sector_identifier_uri`) fetched server-side at registration, giving an SSRF sink at the registration step. Add to `oauth-code-client-binding`; the egress sink itself stays owned by `ssrf`. MEDIUM confidence.
- `AttackTechnique` (Advanced Techniques) <- catalog `attacking-oauth-with-device-code-phishing`: illicit consent-grant phishing where the victim consents to an attacker-registered application and the attacker keeps persistent tokens. Distinct from device-code polling and from dynamic registration. Add to `oauth-device-approval` or `oauth-code-client-binding`. MEDIUM confidence, description-only evidence.
- `ObservableSignal` (Detection Channels) <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-oauth/SKILL.md`: silent re-authentication under `prompt=none` as a session-fixation and silent-auth signal. Add to `oauth-state-nonce-csrf`. LOW confidence.

**References/scripts candidates**

- None. The sources are body prose and concrete request literals.

---

## csrf

Parent: `csrf/SKILL.md`. Variant leaves: `csrf-form-post`, `csrf-navigation-get`, `csrf-parser-differential`, `csrf-login-fixation`, `csrf-websocket-handshake`.
Boundary signature (from `_analysis/csrf.md`): the class splits by the cross-origin delivery-and-acceptance mechanism - simple-request form acceptance, GET-state-change acceptance, parser or method coercion acceptance, fixation-capable login acceptance, and handshake Origin reliance.
The analysis keeps OAuth/GraphQL GET inside `csrf-navigation-get`, multipart file forgery inside `csrf-form-post`, and double-submit and GET-carried tokens inside the per-variant defeat sub-step.

**Sources matched**

- `/Users/diekgbbtt/hacking-skills/skills/web/client-side/csrf/SKILL.md` - token bypass, SameSite, JSON-as-text/plain, WebSocket handshake.
- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-csrf/SKILL.md` - token omission and reuse, JSON-as-text/plain, RelayState, GraphQL GET, mobile deeplink CSRF, plus the Duende BFF static-header antiforgery analysis, the SignalR carve-out, cookie-domain wildcard session fixation, and the raw-client Origin-spoofing shortcut.
- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-websocket/SKILL.md` - CSWSH, per-message authentication, message tampering, namespace and room authorization bypass, handshake-layer Upgrade smuggling, signed-message replay.
- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/web-vulnerabilities/csrf-token-bypass-techniques/SKILL.md` - token removal, format, session reuse, double-submit, Origin null, SameSite, method override, XSS chain.
- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/deep-dive-labs/csrf/SKILL.md` - lab playbooks including CRLF header injection to set the `csrfKey` cookie.
- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/web-vulnerabilities/websocket-hijacking-testing/SKILL.md` - CSWSH and in-band message attacks.
- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W4/performing-csrf-attack-simulation/SKILL.md` - token tests, SameSite, Referer and Origin checks, text/plain JSON.
- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W5/testing-websocket-api-security/SKILL.md` - CSWSH, per-message auth, injection, flooding.
- Catalog-only: `exploiting-websocket-vulnerabilities` (same surface as the two WebSocket sources).

**Similarity**

- Sufficient for the CSRF sources. The base already covers token, Origin, SameSite, parser, navigation, login-fixation, and handshake delivery.
- Insufficient (out of class) for the WebSocket message-layer sources.

**Boundary**

- CSRF sources: no boundary attribute diverges.
- WebSocket message-layer content (per-message authorization, message tampering, namespace and room authorization, Upgrade smuggling, signed-message replay): the attack-surface part family and the communication protocol diverge from CSRF, and no cross-site forgery occurs. This is a distinct class. The suite carries only the WebSocket handshake baseline inside `csrf-websocket-handshake`; the per-message authorization baseline is absent. Per the operator rule this is a NON-MATCH, not a proposal. HIGH confidence. It is a genuine suite gap, owned outside this slice.

**New-skill proposals**

- None.

**Enrichment candidates**

- `DefensiveControl` (Bypass Techniques) <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-csrf/SKILL.md`: a presence-only static antiforgery header whose value is identical for every caller and is not bound to user or role (the Duende BFF `X-CSRF: 1` shape), defeated by any same-origin script and replayable across privilege partitions. The base already warns that some servers check header presence, not value; this adds the role-partition consequence. MEDIUM confidence.
- `AttackTechnique` (Chaining Attacks) <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-csrf/SKILL.md`: a taken-over sibling subdomain sets a parent-domain (`Domain=.target.com`) session cookie, producing session fixation on the parent application. This is cookie injection, distinct from the login-CSRF plant of `csrf-login-fixation`. MEDIUM confidence.
- `AttackTechnique` (Testing Methodology) <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-csrf/SKILL.md`: satisfy a naive Origin/Referer string check directly from a raw HTTP client, with no real cross-origin page delivery. This is a method nuance for header-check targets. LOW confidence.
- `AttackTechnique` (Bypass Techniques) <- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/deep-dive-labs/csrf/SKILL.md`: CRLF injection into a reflected parameter to set the double-submit cookie, then replay with the matching token. The CRLF primitive itself stays owned by `header-injection`. LOW confidence.

**References/scripts candidates**

- None.

---

## http-method-tampering

Parent: `http-method-tampering/SKILL.md`. Variant leaves: `http-method-tampering-verb-switch`, `http-method-tampering-override-smuggling`, `http-method-tampering-informational-verb`, `http-method-tampering-preflight-coercion`.
Boundary signature (from `_analysis/http-method-tampering.md`): the class splits by the handling layer whose method interpretation diverges - route-level verb dispatch, override-header reinterpretation, informational-verb exploitation, and preflight-gated handling.
Mutex rule: verb-switch owns GET, POST, PUT, DELETE, PATCH; informational-verb owns OPTIONS, HEAD, TRACE.

**Sources matched**

- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-api-misconfig/SKILL.md` - HTTP verb tampering (GET bypasses CSRF, X-HTTP-Method-Override, TRACE enabled); the rest of the file is mass assignment, prototype pollution, OData, and Swagger (other classes).
- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-cache-poison/SKILL.md` - X-HTTP-Method-Override reaching a shared cache to poison the canonical response.
- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W9/performing-web-application-firewall-bypass/SKILL.md` - method and protocol-view evasion of a WAF inspection layer (PUT/PATCH, HTTP/0.9, chunked, content-type).
- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W9/performing-http-parameter-pollution-attack/SKILL.md` - duplicate-parameter precedence, including duplicate `redirect_uri`.
- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W2/exploiting-broken-function-level-authorization/SKILL.md` and `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W2/testing-for-broken-access-control/SKILL.md` - method-based authorization bypass (other class: broken-function-level-authorization).
- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/deep-dive-labs/access-control/SKILL.md` - method-based access-control bypass lab.

**Similarity**

- Sufficient. Every method-tampering technique in these sources maps to an existing variant or to a named chain.
- The parameter-pollution and BFLA sources are owned by other classes.

**Boundary**

- No boundary attribute diverges. Verb tampering, override smuggling, TRACE and OPTIONS and HEAD, and preflight shape splits are all owned.

**New-skill proposals**

- None.

**Enrichment candidates**

- `DefensiveControl` (Bypass Techniques) <- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W9/performing-web-application-firewall-bypass/SKILL.md`: a WAF that inspects one method or protocol view and forwards another. The base already names this shape and delegates the mechanics to the `defence-bypass` family, so this is a NON-MATCH for enrichment. HIGH confidence.
- `Artifact` (Chaining Attacks) <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-cache-poison/SKILL.md`: an override-reinterpreted response stored by a shared cache for other clients. The base chaining already states "Method tampering plus caching". Covered, no delta. HIGH confidence.

**References/scripts candidates**

- None.

---

## open-redirect

Parent: `open-redirect/SKILL.md`. Variant leaves: `generic-redirect-parser-bypass`, `oauth-redirect-uri-relay`, `redirector-to-fetcher-pivot`.
Boundary signature (from `_analysis/open-redirect.md`): the class splits by redirect sink and validation locus crossed with redirect consumer - generic parser-differential, OAuth-registered relay, fetcher-followed pivot.
Grey points: client-side router guards and `javascript`/`data` scheme acceptance ride inside the generic variant; post-logout looseness rides inside the OAuth variant.

**Sources matched**

- `/Users/diekgbbtt/hacking-skills/skills/web/client-side/open-redirect/SKILL.md` - parameter list, parser bypass table, javascript scheme, DNS-rebinding mention (description only).
- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-open-redirect/SKILL.md` - parameter list, bypass table, DOM-based redirect, OAuth chain, server-side redirect to SSRF, session-fixation chain.
- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/web-vulnerabilities/open-redirect-chaining-attacks/SKILL.md` - OAuth token theft chain, SSRF-filter bypass chain, `javascript:` XSS.
- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W6/testing-for-open-redirect-vulnerabilities/SKILL.md` - bypass set including CRLF injection in the redirect, and the OAuth and phishing chains.
- Catalog-only: `exploiting-deeplink-vulnerabilities` (mobile deep-link redirect manipulation).

**Similarity**

- Sufficient. The base already covers the parser-differential, OAuth-relay, and fetcher-pivot consumers plus the payload families.

**Boundary**

- No boundary attribute diverges.
- CRLF injection in the redirect value leading to a header effect is owned by `header-injection`. NON-MATCH for this class. HIGH confidence.
- Mobile deep-link redirect manipulation is owned by the mobile surface; the base carries custom-scheme dispatch as an OAuth aspect. NON-MATCH here.

**New-skill proposals**

- None.

**Enrichment candidates**

- `AttackGoal` and `Artifact` (Chaining Attacks) <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-open-redirect/SKILL.md`: open redirect to session fixation, where the victim is forced through a login endpoint with a pre-set session. The base chaining lists phishing, credential relay, fetcher pivot, and subresource embed, but not session fixation. LOW-MEDIUM confidence.

**References/scripts candidates**

- None.

---

## subdomain-takeover

Parent: `subdomain-takeover/SKILL.md`. Variant leaves: `dangling-record-resource-claim`, `cdn-alternate-domain-binding`, `ns-delegation-takeover`.
Boundary signature (from `_analysis/subdomain-takeover.md`): the class splits by claim mechanism - dangling-record resource claim, CDN alternate-domain binding, NS delegation takeover.
The analysis states a grey point: MX mail takeover stays an outlier because the skill gives no fingerprint, claim, or validation procedure for email receipt.
Non-discriminators: provider identity, TXT enforcement, impact, account ability, proof wording, certificate evidence.

**Sources matched**

- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-subdomain/SKILL.md` - provider fingerprints and claim flows, plus five trust-consumer chains: OAuth `redirect_uri` allowlist, cookie-domain wildcard session fixation, CSP `script-src`, CORS allowlist, and email DNS (DKIM selector / SPF include).
- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W6/exploiting-broken-link-hijacking/SKILL.md` - external script and domain expiry, CDN and npm package references, SRI absence, social-handle claim.
- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W8/performing-dns-enumeration-and-zone-transfer/SKILL.md` - AXFR zone transfer, wildcard detection, internal-IP leak, SPF/DKIM/DMARC enumeration.
- Catalog-only: `hunting-for-dns-based-persistence` (defensive threat-hunting for dangling CNAME and NS tampering).
- Non-match candidates read: `/Users/diekgbbtt/awsome-offensive-security-skill/skills/network/ipv6-dns-takeover-mitm/SKILL.md`, `.../ipv6-dns-takeover-mitm6/SKILL.md`, `.../bgp-hijacking-concepts/SKILL.md` (network-layer MITM and BGP hijack).

**Similarity**

- Sufficient for the claim mechanics and provider fingerprints. The provider-specific fingerprints are non-discriminators (technology stack).
- The email-DNS chain supplies a delta the base does not carry (see below).
- Insufficient (out of class) for the network MITM and BGP sources.

**Boundary**

- The five trust-consumer chains mostly match existing `Trust Consumers` and `Chaining Attacks` entries (cookie scope, origin checks, redirect allowlists, script-source policies, certificate issuance).
- Email DNS (DKIM selector / SPF include) takeover: the vulnerability-specific reconnaissance (selector and include enumeration), the attack-surface part family (email DNS), the communication protocol (SMTP), the trust assumption (email authentication trust), and the impact (email spoofing) all diverge. The claim mechanism does not bend (it is still a dangling-record resource claim), but the post-claim step does bend: publishing DKIM or SPF records that authorize the attacker's mail server is a step the resource-claim variant does not describe. This refutes the analysis grey point, which assumed no source supplies a fingerprint, claim flow, and validation step. See the proposal below. MEDIUM confidence.
- External-resource (broken-link) hijacking: the attack-surface part family (a third-party external dependency the target does not own), the reconnaissance (crawl external references, wayback, package and CDN checks), and the impact (supply-chain script injection) diverge. The claim mechanics are shared with the resource-claim variant, but the external-dependency inventory and SRI baseline is absent from the suite. Per the operator rule this is a NON-MATCH as a new class; the usable delta is carried as an enrichment below. MEDIUM confidence.
- Network-layer DNS takeover and BGP hijacking: distinct classes (on-path network attack). NON-MATCH. HIGH confidence.

**New-skill proposals**

- `source: /Users/diekgbbtt/claude-bug-hunter/skills/hunt-subdomain/SKILL.md` (Chain 5, email DNS).
- `[NEW] target: subdomain-takeover/email-dns-takeover` (new variant under the existing parent).
- Extended rationale: the parent already names a mail surface but deliberately treats it as an impact statement with no claim procedure ("the class carries it without a claim procedure of its own"), and the analysis endorsed this as a grey point. The source supplies the missing procedure: enumerate DKIM selectors (`selector1._domainkey.<domain>`) and SPF includes (`include:<host>`), find a dangling selector or include host, claim it through the ordinary dangling-record flow, then publish DKIM and SPF records that authorize the attacker's sending server. The post-claim step (publish mail-authentication records) is a bent step the `dangling-record-resource-claim` variant cannot describe, and the divergence touches four boundary attributes (reconnaissance, attack-surface family, protocol, trust assumption). Recommendation: add it as a fourth variant, or, if the maintainers prefer to keep the mail surface as an impact statement, record it as a documented aspect with an explicit post-claim step. MEDIUM confidence.
- Alternative considered and rejected: a new `broken-link-hijacking` class from `exploiting-broken-link-hijacking`. Rejected because its baseline (external-dependency inventory and SRI) is absent from the suite, per the operator rule. Its usable delta is listed as an enrichment instead.

**Enrichment candidates**

- `AttackTechnique` (Reconnaissance) <- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W8/performing-dns-enumeration-and-zone-transfer/SKILL.md`: AXFR zone transfer as a name and record inventory source that reveals the full zone, including dangling records, alongside the existing certificate-transparency and passive-DNS sources. MEDIUM confidence.
- `AttackGoal` and `Artifact` (Chaining Attacks) <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-subdomain/SKILL.md`: a claimed host inside a CORS allowlist enables a credentialed cross-origin API read. The base lists origin checks under `Trust Consumers` but not this concrete credentialed-read chain. MEDIUM confidence.
- `AttackTechnique` (Reconnaissance) <- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W6/exploiting-broken-link-hijacking/SKILL.md`: crawl external script and domain references, check registration status, and test for absent SRI, as a reconnaissance addition that surfaces claimable third-party dependencies. LOW-MEDIUM confidence, flagged because it is arguably a distinct class.
- `Artifact` (Chaining Attacks) <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-subdomain/SKILL.md`: a wildcard `*.target.com` in an OAuth `reply_to` or `redirect_uri` allowlist lets a claimed dangling host complete a one-click authorization-code theft. The base names redirect allowlists generally; this adds the wildcard-allowlist claim shape. LOW confidence.

**References/scripts candidates**

- None. The provider fingerprint tables and lab payloads are concrete and technology-specific, which violates the abstractness rule.

---

## Slice summary

**Counts**

- Base skills analysed: 6 parents plus 24 variant leaves.
- Source skills read and assessed: 49 (deduplicated across groups).
- New-skill proposals: 1 (`subdomain-takeover/email-dns-takeover`, MEDIUM).
- Non-match verdicts with rationale: 8 (SAML, legacy-protocol auth bypass, type juggling, WebSocket message-layer, CRLF-to-header, WAF method evasion, network DNS/BGP takeover, broken-link hijacking as a new class).
- Enrichment candidates: 13 (oauth 5, csrf 4, subdomain-takeover 4, open-redirect 1, authentication-jwt 2, http-method-tampering 0 net).
- References/scripts candidates: 0.

**Strongest findings**

1. `subdomain-takeover/email-dns-takeover` is the only decision-grade new-skill proposal. The source supplies the fingerprint, claim flow, and validation step the class analysis explicitly recorded as missing, so the mail-surface grey point no longer holds.
2. `oauth` cross-window credential delivery ("Dirty Dancing": response-type swap, `response_mode=web_message`, lax postMessage origin check) and the token-endpoint prerequisite-completeness gap are the two strongest oauth enrichments. Both are aspects inside existing variants, not new variants, because the analysis already discarded flow-label and format splits.
3. `csrf` gains the strongest single enrichment: a presence-only static antiforgery primitive that is not bound to user or role (the Duende BFF `X-CSRF=1` shape), which the base does not name as a defensive-control class.
4. Four clean non-matches protect the suite from over-splitting: SAML and legacy-protocol auth bypass (authentication-jwt), WebSocket message-layer authorization (csrf), and broken-link hijacking (subdomain-takeover). Each would need a baseline the suite does not carry, which the operator rule excludes.
5. No references/scripts candidates exist in this slice. The corpus supplies either concrete lab solutions and provider fingerprints (abstractness violation) or template boilerplate (generic `agent.py` and API tables), so nothing is generalised enough to lift into `references/`.
