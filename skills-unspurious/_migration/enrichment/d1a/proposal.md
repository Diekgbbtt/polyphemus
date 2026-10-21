# D1a enrichment proposal (W7, C4-full enrichment)

*Report only. No suite skill was modified. No git command was run. The orchestrator commits.*
*Synthesis of six parallel slice reports: `slice-1.md` through `slice-6.md`, same directory.*
*Scope: the full `skills-unspurious/` suite, 44 groups, base skills plus variant leaves.*

## 1. Executive summary

### Totals

- New-skill proposals: 21 raw across the six slices. After cross-slice reconciliation: 19 distinct proposals (2 cross-slice duplicates collapsed: `session-management`, `client-side-path-traversal`).
- Enrichment candidates: 214 raw (slice-1 13, slice-2 26, slice-3 74, slice-4 15, slice-5 48, slice-6 38).
- References/scripts candidates: 48 enumerated (slice-2 12, slice-3 9, slice-4 6, slice-6 20, slice-5 1 flagged). 45 firm, 3 flagged low confidence. Slice-1 carries none.
- Out-of-slice triage candidates: 7 (`session-management`, `rate-limit-bypass`, `http-parameter-pollution`, LDAP injection, XPath injection, `cache-poisoning`, `cors-misconfiguration` routing).

### The algorithm, one line

Match each source skill to a base by vulnerability class or chainable technique; when similarity is insufficient apply the five boundary attributes and propose a new skill only on a boundary divergence; when similarity is sufficient run a macro semantic diff and abstract the delta onto one ontology entity, escalating to a proposal only when the diff spans several entities and touches a boundary attribute; then assess references and scripts for generalisation.

The five boundary attributes are: vuln-specific reconnaissance, attack-surface part family, communication protocol, trust-assumption difference, impact.

### Confidence distribution (19 distinct proposals)

- HIGH: 4 (`xxe-local-dtd-error-exfiltration`, `email-header-injection`, `race-conditions-partial-construction`, `dom-clobbering`).
- MEDIUM-HIGH: 3 (`graphql-subscription-hijack`, `mcp-tool-server-abuse`, `defence-bypass-attempt-batching`).
- MEDIUM: 9 (`subdomain-takeover/email-dns-takeover`, `excessive-data-exposure`, `session-management`, `lfi-filter-chain-execution`, `rag-vector-store-abuse`, `client-side-path-traversal`, `rce-config-delegate-execution`, `css-injection-exfiltration`, `cors-misconfiguration`).
- LOW-MEDIUM: 2 (`api-version-consistency`, `http-request-smuggling-cross-protocol-desync`).
- LOW: 1 (`crypto-oracle-decryption`).

### Headline findings

1. The suite has a structural session-state gap. Two slices propose a session class independently: slice-3 as `session-management`, slice-5 as an out-of-slice first-order class. Three separate leaves (`crypto-weakness`, `header-response-value-confusion`, `weak-credential-discovery`) treat the same cookie and session sources as out of class. No group owns session fixation, post-logout replay, invalidation-on-credential-change, or refresh-token rotation reuse. This is the largest single missing baseline.
2. Two first-order classes are missing with clean, uncontroversial sourcing. `email-header-injection` is named by the base `header-injection` analysis itself as its out-of-scope related class. `xxe-local-dtd-error-exfiltration` is a zero-egress bent step on the `PreconditionEnvironment` external-DTD axis that the blind variant cannot describe. Both are HIGH confidence.
3. The client-side cluster is under-covered and over-split-prone. `dom-clobbering`, `css-injection-exfiltration`, and `client-side-path-traversal` all diverge on client-side trust, and `client-side-path-traversal` is proposed with competing homes in two slices (an `xss` leaf or new group in slice-5, a `proxy-techniques` leaf in slice-6). This cluster needs one operator ruling on grouping.

---

## 2. Section A - New-skill proposals

This is the operator's assessment focus. Entries are deduplicated and cross-reconciled. Each entry gives the source path(s), the diverging boundary attribute, a decision-grade rationale, the confidence, and the stated alternative home.

### A1. `[NEW] subdomain-takeover/email-dns-takeover`

- Source: `CBH/hunt-subdomain/SKILL.md` (Chain 5, email DNS).
- Diverging boundary attribute: vuln-specific reconnaissance, attack-surface part family, communication protocol, and trust assumption diverge (four attributes at once).
- Rationale: the parent names a mail surface but treats it as an impact statement with no claim procedure, and the class analysis endorsed that as a grey point. The source supplies the missing procedure: enumerate DKIM selectors (`selector1._domainkey.<domain>`) and SPF includes (`include:<host>`), find a dangling selector or include host, claim it through the ordinary dangling-record flow, then publish DKIM and SPF records that authorize the attacker's sending server. The post-claim step (publish mail-authentication records) is a bent step the `dangling-record-resource-claim` variant cannot describe. This refutes the analysis grey point.
- Confidence: MEDIUM.
- Alternative home: add as a fourth variant under the existing parent, or record it as a documented aspect with an explicit post-claim step if the maintainers prefer to keep the mail surface as an impact statement.

### A2. `[NEW] excessive-data-exposure`

- Sources: `ACS/W5/exploiting-excessive-data-exposure-in-api/SKILL.md`, plus `ACS/W5/detecting-broken-object-property-level-authorization/SKILL.md` and `ACS/W5/testing-for-sensitive-data-exposure/SKILL.md`.
- Diverging boundary attribute: attack-surface part family (API response body field sets versus channels and deployables).
- Rationale: over-fetch is a single resource response carrying fields the caller is not entitled to see (password hashes, national identifiers, internal notes, a full user object embedded in an unrelated response). It is a single-response read of an ordinary resource, not of a deployable artifact. No parent step covers "read every field of an ordinary response against the caller's entitlement": the artifact step fetches artifacts and API documents, and the cross-channel entry fires only on disagreement between two representations of one object. The impact (confidentiality) and the trust assumption are shared, so a sibling class is the correct shape.
- Confidence: MEDIUM.
- Alternative home: a fourth `information-disclosure` variant if the operator prefers no new parent, but a variant would leave the parent method under-specified.

### A3. `[NEW] api-version-consistency` (shadow or zombie API)

- Sources: `CBH/hunt-shadow-api/SKILL.md`, plus `AWS/bug-hunting/api-security/api-enumeration-fuzzing-discovery/SKILL.md` and `CBH/hunt-spa-api/SKILL.md`.
- Diverging boundary attribute: trust assumption (the current control set is assumed to apply to every reachable version).
- Rationale: OWASP API9 improper inventory management. The finding is a behavioural security regression between an old and the current version of the same operation (weaker auth, missing rate limit, dropped validation), not a disclosure and not a single enforcement-locus gap.
- Confidence: LOW-MEDIUM.
- Alternative home: keep the version surface inside the `bfla-alternate-path` and `idor` older-version aspects, or place it in a recon group rather than a vulnerability class. Flagged for the operator's judgement.
- Cross-slice overlap: slice-6 `defence-bypass-edge-origin-differential` also carries shadow and deprecated-route enumeration (version downgrade, mobile subdomain, legacy path). If A3 is rejected, the slice-6 enrichment is the remaining home.

### A4. `[NEW] session-management` (RECONCILED: slices 3 and 5)

- Sources: `CBH/hunt-session/SKILL.md` and `HS/web/session/session-fixation/SKILL.md` (slice-3, proposal). Also `HS/web/session/cookie-attacks/SKILL.md` and `HS/web/session/session-fixation/SKILL.md` (slice-5, out-of-slice first-order class, alternative name `session-cookie-security`).
- Competing homes: slice-3 raises it as a new class proposal. slice-5 records it as an out-of-slice class gap that the operator should route. slice-5 `header-response-value-confusion` treats the same cookie sources as out of its leaf's class. slice-3 `crypto-weakness` treats session fixation and `hunt-session` as non-matches on trust-assumption and reconnaissance grounds.
- Diverging boundary attribute: trust assumption (the server trusts a client-supplied session identifier; a rotated token is assumed single-use) and attack-surface part family (session lifecycle, not header trust).
- Rationale: the base suite carries no session class. `crypto-weakness` owns artifact unpredictability, key recovery, and comparison timing only. It does not own session fixation, post-logout replay, invalidation-on-credential-change, or refresh-token rotation reuse detection. The reconnaissance differs: cookie lifecycle and two-session flows, not offline derivation. Both sources run a full, stable procedure.
- Confidence: MEDIUM (slice-3) / LOW-MEDIUM (slice-5).
- Alternative home: scope as a new variant of `crypto-weakness` on the server-chosen-identifier clause. Slice-3 rejects this because that clause is not a crypto clause. Operator must decide whether the suite wants a session group.

### A5. `[NEW] crypto-oracle-decryption`

- Sources: `HS/mobile/crypto/mobile-weak-crypto/SKILL.md` and `AWS/bug-hunting/deep-dive-labs/business-logic/SKILL.md` (Lab 11, padding oracle).
- Diverging boundary attribute: trust assumption (the ciphertext-opacity clause; the class trusts the ciphertext is opaque and a decryption endpoint leaks no bit of plaintext).
- Rationale: a padding oracle or a decryption-endpoint oracle bends a fourth, uncovered clause. The procedure differs: submit crafted ciphertext blocks, read a padding or MAC verdict, and flip bits position by position. It is not prediction, not key recovery, and not comparison timing.
- Confidence: LOW. The sources are thin (one lab line plus the mobile ECB and static-IV material), and the mobile source is out of scope.
- Alternative home: if accepted, it is a new variant of `crypto-weakness` (a fourth discriminator value) rather than a new class.

### A6. `[NEW] lfi-filter-chain-execution`

- Source: `CBH/hunt-lfi/SKILL.md` (Phase 4).
- Diverging boundary attribute: attack-surface part family; the bent step is payload synthesis from a read-only primitive.
- Rationale: a bare `php://filter` read primitive is upgraded to execution by chaining `iconv` charset conversions that synthesise an arbitrary PHP payload in memory. No upload, no log access, and no writable path are required. The `lfi-include-execution` variant owns "filter shapes that return transformed local content" and "poison-then-include with execution proof"; its step description implies reading existing content, not synthesising new content.
- Confidence: MEDIUM.
- Alternative home: collapses to an enrichment of `lfi-include-execution` if the operator judges "filter transformation" exhaustive over synthesis.

### A7. `[NEW] graphql-subscription-hijack`

- Sources: `CBH/hunt-graphql/SKILL.md` (subscription hijacking) and `ACS/W5/performing-graphql-introspection-attack/SKILL.md` ("subscriptions may have different authentication requirements").
- Diverging boundary attribute: attack-surface part family (a persistent stream versus request and response), communication protocol (WebSocket versus HTTP), trust assumption (per-channel and per-message authorization over a long-lived connection).
- Rationale: a subscription is a third operation type carried over a persistent WebSocket connection. It owns a bent step: authorize a stream subscription per channel and per message, and keep that authorization valid for the life of the connection. The base methodology has an object-level sweep per identifier-taking query and a function-level sweep per mutation; neither covers a channel subscription. The server trusts that the connection identity stays bound to every pushed event. The base `graphql` skill is declared non-decomposing, and both sources carry the technique while the base carries none.
- Confidence: MEDIUM-HIGH. The highest-confidence structural gap in slice-3.
- Alternative home: a bounded enrichment (a subscription block inside Key Vulnerabilities plus a subscription step in Testing Methodology) if the operator prefers to keep `graphql` non-decomposing, but the bent step argues for a leaf.

### A8. `[NEW] mcp-tool-server-abuse`

- Sources: `AWS/ai-red-teaming/agent-security/mcp-protocol-exploitation/SKILL.md` and `AWS/ai-red-teaming/agent-security/ai-agent-tool-abuse-and-privilege-escalation/SKILL.md`.
- Diverging boundary attribute: attack-surface part family (a protocol tool-call endpoint versus a chat feature) and trust assumption (the tool server must enforce caller identity and parameter validation independently of the model, whereas the base trusts the model to separate instructions from data).
- Rationale: the base `tool-abuse` variant treats the model as the actuator and requires a logged model-steered call. The MCP tool server is a directly reachable API: tool enumeration, unauthenticated tool calls, path traversal in a file tool, command injection in an execution tool, URL fetch through a fetch tool, and tool-permission gaps. The model is bypassed. The reconnaissance differs: enumerate `tools/list`, read input schemas, map destructive tools. Both sources carry a full, stable procedure.
- Confidence: MEDIUM-HIGH.
- Alternative home: a bounded enrichment of `tool-abuse` (tool-permission enforcement gap and cross-tool chain) if the MCP leaf is not created.
- Flag: this is an AI-agent surface. Confirm it is inside the operator's web-testing scope before authoring.

### A9. `[NEW] rag-vector-store-abuse`

- Sources: `CBH/hunt-rag-vector/SKILL.md` and `AWS/ai-red-teaming/ml-security/rag-poisoning-and-data-exfiltration/SKILL.md`.
- Diverging boundary attribute: trust assumption (tenant isolation must hold at the vector database, not only at the chat API).
- Rationale: the base class covers injection through ingested content. It does not cover the vector store as a directly reachable data store: unauthenticated corpus reads, cross-tenant vector IDOR through a controlled namespace or document ID, and source-text or metadata leakage in similarity results.
- Confidence: MEDIUM.
- Alternative home: the direct-read half is arguably an `idor` or `information-disclosure` case, and the persistent-poisoning half is already owned by `indirect-injection-plant`. If the operator judges the direct-read half to belong to `idor`, this reduces to an enrichment of `indirect-injection-plant` (retrieval hijack) plus an out-of-slice note for `idor`.
- Cross-slice overlap: the direct-read half shares the "response carries more than the caller is entitled to" shape with A2 (`excessive-data-exposure`).

### A10. `[NEW] xxe-local-dtd-error-exfiltration`

- Source: `CBH/hunt-xxe/SKILL.md`.
- Diverging boundary attribute: `PreconditionEnvironment` external-DTD-fetch enabled versus disabled.
- Rationale: the base blind variant `blind-parameter-entity-oob-exfiltration` requires attacker-hosted external resolution plus a callback destination. When external DTD fetch is disabled but a locally installed DTD is still processed, a distinct bent step exists: locate an on-disk DTD, redefine one of its internal entities, and force a read file into a parse-error message with zero network egress. The observable channel is error text rather than a callback. The diff spans multiple ontology entities (`PreconditionEnvironment`, `AttackTechnique`, `ObservableSignal`, `PayloadPattern`) and touches a boundary attribute, so it escalates to a new variant per the algorithm.
- Confidence: HIGH. The only firm new-skill proposal in slice-4.
- Alternative home: none stated; a fourth variant under the existing parent.
- Companion reference: `references/local-dtd-repurposing.md` (Section C).

### A11. `[NEW] email-header-injection` (SMTP message-header injection)

- Source: `ACS/W3/testing-for-email-header-injection/SKILL.md`.
- Diverging boundary attribute: communication protocol (SMTP message headers, not HTTP headers), trust assumption (the mail library and transport treat a form field as header data, and the header/body boundary is CRLF, not the HTTP framing contract), and impact (spam relay, sender spoofing, phishing-body override, token copy via injected Cc/Bcc, SMTP/IMAP command injection).
- Rationale: the base `header-injection` analysis explicitly places outbound SMTP email-header injection out of scope and assigns it to its related class, and no suite group carries that class. The source is well-formed and carries the concrete procedures: CRLF variants (`%0A`, `%0D`, `%0D%0A`, double-encode), Cc/Bcc/From/Reply-To injection, MIME boundary override, and SMTP/IMAP command injection. This is a first-order class, so the operator's missing-baseline caution does not apply.
- Confidence: HIGH. Actionable now.
- Alternative home: none.

### A12. `[NEW] race-conditions-partial-construction` (alias multi-endpoint-race)

- Sources: `CBH/hunt-race-condition/SKILL.md` (lines 17-29); corroborated by `ACS/W6/exploiting-race-condition-vulnerabilities/SKILL.md` (lines 112-143) and `AWS/bug-hunting/web-vulnerabilities/race-condition-toctou-exploitation/SKILL.md` (lines 105-121).
- Diverging boundary attribute: trust assumption (the object exists in a usable state mid-creation) and attack-surface part family (two actions against one state machine, not one action duplicated).
- Rationale: the parent testing step is explicitly identical-input. Three independent sources carry a different-request shape (register-then-confirm; email-change against password-reset; email-update against checkout). The delta is the different-request synchronisation plus the mid-creation window targeting, which the parent's identical-input step neither performs nor describes. The three sources agree on the procedure, which lifts it above a grey point.
- Confidence: HIGH (strong-medium).
- Alternative home: none. Decision-grade caveat: the base analysis folded "one-time-token races" into the parent core as an aspect, so the operator should confirm the seam is request-content diversity (this proposal) and not token consumption (already an aspect).

### A13. `[NEW] dom-clobbering`

- Sources: `CBH/hunt-dom/SKILL.md` (lines 47-88); corroborated by `AWS/bug-hunting/web-vulnerabilities/dom-based-cross-site-scripting-xss/SKILL.md` (lines 124, 140) and `AWS/bug-hunting/web-vulnerabilities/xss-reflected-stored-dom/SKILL.md`.
- Diverging boundary attribute: trust assumption (attacker markup defines a global the application trusts) and attack-surface part family (DOM structure, not a string source).
- Rationale: the first bent step is "inject markup that defines or shadows a named element so a JavaScript global the application trusts resolves to attacker-controlled structure, then drive the clobbered value into a sink". The source is a client-only flow whose source is DOM structure, so the parent source list (URL components, referrer, message channels, storage, server data) is not exhaustive for it. The delta is the clobberable-global discovery plus the markup-only injection requirement, which no existing leaf names.
- Confidence: HIGH (strong-medium).
- Alternative home: a new leaf under the `xss` group. The strongest of the three client-side items in slice-5.

### A14. `[NEW] client-side-path-traversal` (CSPT) (RECONCILED: slices 5 and 6)

- Source: `HS/web/client-side/cspt/SKILL.md`.
- Competing homes:
  - slice-5 proposes `client-side-path-traversal`, flagged as a possible new group rather than an `xss` leaf.
  - slice-6 proposes `proxy-techniques-client-side-path-traversal`, a new level-2 leaf under `proxy-techniques`.
- Diverging boundary attribute: trust assumption (the client trusts its own concatenated path and follows redirects), attack-surface part family (client request construction), and impact (response injection and authenticated internal-endpoint reach, not script execution in the reflected sense).
- Rationale: the first bent step is "concatenate an attacker value into the path component of a client fetch, traverse to a gadget endpoint, and let the client follow the redirect so the attacker controls the response". It chains to XSS but is not XSS. The mechanism is distinct: the two readers are not competing for one destination value (that is `url-parser-differential`), and it relocates the request path client-side rather than carrying an approved operation to a second destination (that is `redirect-chain`).
- Confidence: MEDIUM.
- Alternative homes: slice-6 rejected folding into `proxy-techniques-redirect-chain` as the Consumer Libraries aspect, because the client-side relative-base completion is a distinct step the aspect list does not hold. slice-5 left it open between a new client-side group and an `xss` leaf.
- Operator decision: choose one home. The two slices agree on the mechanism and the divergence; they disagree only on the parent (`xss`/new group versus `proxy-techniques`). Author it once.

### A15. `[NEW] rce-config-delegate-execution` (configuration-as-code delegate execution)

- Source: `CBH/hunt-rce/SKILL.md` (lines 84-92, 298-302, 410-411).
- Diverging boundary attribute: attack-surface part family (a configuration field, not a direct string and not an uploaded file), sink-primitive kind (a configuration-file renderer or daemon that evaluates embedded directives), and trust assumption (administrators are treated as trusted, so field values pass straight into a configuration file that carries execution primitives).
- Rationale: a third input-vector topology appears in the source: a configuration field in a management interface reaching a configuration-rendering delegate that supports execution primitives (a log-daemon destination, a metrics-plugin exec block, a job-template renderer). Its first step is neither direct-string discovery nor file-mediated construction, so the parent step is not exhaustive for it.
- Confidence: MEDIUM. The source carries one scenario per delegate family and no per-delegate matrix.
- Alternative home: hold it as a named aspect inside `rce-pipeline-execution` until a source with a delegate matrix is found. This aligns with the base analysis open question about a dedicated delegate matrix. Do not action both ways at once.

### A16. `[NEW] css-injection-exfiltration`

- Sources: `CBH/hunt-dom/SKILL.md` (lines 180-211); corroborated by `ACS/W4/performing-content-security-policy-bypass/SKILL.md` (lines 138-165, 167-190).
- Diverging boundary attribute: trust assumption (styles are treated as presentation-only, not as a data channel) and impact (data disclosure without execution).
- Rationale: the first bent step is "inject CSS that uses attribute selectors to leak a token character by character to an out-of-band receiver, with no script execution".
- Confidence: MEDIUM.
- Alternative home: both sources tie this to CSP gating (external resource origins must be open for the leak), so it can instead be an aspect inside `information-disclosure`. The operator must choose one home, not both.

### A17. `[NEW] http-request-smuggling-cross-protocol-desync`

- Source: `CBH/hunt-http-smuggling/SKILL.md` (matrix row only).
- Diverging boundary attribute: communication protocol (framing desync at a translation hop into a non-HTTP binary protocol, for example HTTP to a Java servlet-connector protocol).
- Rationale: the group's discrimination function splits by transport framing channel, and a cross-protocol translation hop is a third channel, not a value of either existing channel. The source names it (cross-protocol HTTP-to-connector desync, smuggled request opaque to the WAF, reaching internal connector admin paths) but carries no probe procedure.
- Confidence: LOW-MEDIUM, flagged.
- Alternative home: none. Decision-grade caveat: do NOT action this until a source with an actual cross-protocol probe procedure is found. The base analysis already parked research-stage third channels (QUIC) outside the suite for the same reason. If a procedure is found later, this becomes a new leaf under the group.

### A18. `[NEW] defence-bypass-attempt-batching` (new level-2 leaf under `defence-bypass`)

- Sources: `AWS/bug-hunting/api-security/api-rate-limit-bypass-techniques/SKILL.md`, `AWS/bug-hunting/api-security/graphql-batching-attacks/SKILL.md`, `CBH/security-arsenal/SKILL.md`, `CBH/hunt-api-misconfig/SKILL.md`.
- Diverging boundary attribute: `AttackTechnique` (a new bent step; the limiter's counting unit, request versus logical operation).
- Rationale: the mechanism collapses many logical attempts into one counted request through an array body, a GraphQL alias set, a `multipart/mixed` batch, or a fat request the limiter counts once and the backend iterates. The parent's "spread one dimension" step covers distributing one effect across an uncounted lane and cannot describe collapsing many attempts into one counted unit, so the step is bent. The variant is disjoint from `throttle-evasion`, which spreads across lanes, because batching reduces the counted request count rather than moving the effect to another lane. Coverage holds because every batching carrier shares the one bent step.
- Confidence: MEDIUM-HIGH.
- Alternative home: none.
- Cross-slice overlap: slice-5 `race-conditions/single-request-fanout` shares the batching carriers (array, alias) as an intra-request fan-out. The two are not duplicates: slice-5 owns the fan-out as a race primitive, slice-6 owns the counting-unit collapse as a rate-limit bypass. Note the shared source (`graphql-batching-attacks`) so the enrichment is authored once.

### A19. `[NEW] cors-misconfiguration` (cross-slice, class group, flagged out of family scope)

- Sources: `ACS/W4/testing-cors-misconfiguration/SKILL.md`, `HS/web/client-side/cors-misconfig/SKILL.md`, `CBH/hunt-cors/SKILL.md`.
- Diverging boundary attribute: trust assumption (the browser's same-origin read model and the credentialed cross-origin read, not the generic permit-enumeration mechanic) and impact (a browser PoC is required, which bends a step: the family's permit step has no browser-enforcement step).
- Rationale: the class definition is the browser's same-origin read model. The baseline web-vulnerability-testing is present.
- Confidence: MEDIUM.
- Alternative home: route it to the class-slice owner, not to `defence-bypass`. The `defence-bypass-allowance-gap` leaf keeps the permit-enumeration enrichments (regex-class bypass, origin prefix match). Cross-slice note: the CSP class is also absent from the suite; its material lives in the `defence-bypass-allowance-gap` enrichments and `references/csp-permit-gaps.md`.

### A20. Noted but not proposed

- `cache-poisoning` (slice-6). A dedicated cache-poisoning class may be warranted for the suite, but that is a class-group question, not a family variant. The `proxy-techniques-cache-deception` leaf already states both cache clauses (cache-key and produced-for-caller), and the only differing boundary attribute would be impact, which alone is not a discriminator. Flagged, not proposed.

---

## 3. Section B - Enrichment candidates (the D1b execution plan)

Executable after the assessment. Grouped by level-1 directory, ordered by group, then by base skill, then by ontology entity. Deduplicated across slices.

Source path aliases used below:

- `HS/` = `/Users/diekgbbtt/hacking-skills/skills/`
- `CBH/` = `/Users/diekgbbtt/claude-bug-hunter/skills/`
- `ACS/` = `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/`
- `AWS/` = `/Users/diekgbbtt/awsome-offensive-security-skill/skills/`

Each line is `<ontology entity> <- <source path>: what to abstract`.

### Group `authentication-jwt`

`authentication-jwt` (parent)
- `AttackTechnique` (Chaining Attacks) <- `CBH/hunt-jwt-crypto/SKILL.md`: satisfy a `jku`/`x5u` host allowlist by chaining an open redirect or an SSRF-reachable path on the target's own domain so the key fetch resolves to the attacker JWKS. LOW.
- `AttackTechnique` (Key Vulnerabilities) <- `CBH/hunt-jwt-crypto/SKILL.md`: cross-tenant claim swap (`org_id`, `tenant_id`, `workspace_id`) as an explicit claims-confusion shape. Wording-level add. LOW.

### Group `oauth`

`oauth` (parent)
- `AttackTechnique` (Advanced Techniques) <- `CBH/hunt-oauth/SKILL.md`: cross-window credential delivery where `response_mode=web_message` returns the code to a parent window and a lax postMessage origin check lets the attacker read it. Aspect of `oauth-redirect-uri-validation`. MEDIUM.
- `AttackTechnique` (Key Vulnerabilities) <- `CBH/hunt-oauth/SKILL.md`: prerequisite-step completeness check at the token endpoint, where a credential is issued to an account that never completed email verification. Add to `oauth-code-client-binding`. MEDIUM.
- `AttackTechnique` (Key Vulnerabilities) <- `AWS/bug-hunting/deep-dive-labs/oauth/SKILL.md`: dynamic-registration metadata fields (`logo_uri`, `jwks_uri`, `sector_identifier_uri`) fetched server-side at registration, an SSRF sink at the registration step. Add to `oauth-code-client-binding`; the egress sink stays owned by `ssrf`. MEDIUM.
- `AttackTechnique` (Advanced Techniques) <- catalog `attacking-oauth-with-device-code-phishing`: illicit consent-grant phishing where the victim consents to an attacker-registered application. Add to `oauth-device-approval` or `oauth-code-client-binding`. MEDIUM, description-only evidence.
- `ObservableSignal` (Detection Channels) <- `CBH/hunt-oauth/SKILL.md`: silent re-authentication under `prompt=none` as a session-fixation and silent-auth signal. Add to `oauth-state-nonce-csrf`. LOW.

### Group `csrf`

`csrf` (parent)
- `DefensiveControl` (Bypass Techniques) <- `CBH/hunt-csrf/SKILL.md`: a presence-only static antiforgery header whose value is identical for every caller and is not bound to user or role (the Duende BFF `X-CSRF: 1` shape), defeated by any same-origin script and replayable across privilege partitions. MEDIUM.
- `AttackTechnique` (Chaining Attacks) <- `CBH/hunt-csrf/SKILL.md`: a taken-over sibling subdomain sets a parent-domain (`Domain=.target.com`) session cookie, producing session fixation on the parent application. MEDIUM.
- `AttackTechnique` (Testing Methodology) <- `CBH/hunt-csrf/SKILL.md`: satisfy a naive Origin/Referer string check directly from a raw HTTP client, with no real cross-origin page delivery. LOW.
- `AttackTechnique` (Bypass Techniques) <- `AWS/bug-hunting/deep-dive-labs/csrf/SKILL.md`: CRLF injection into a reflected parameter to set the double-submit cookie, then replay with the matching token. The CRLF primitive itself stays owned by `header-injection`. LOW.

### Group `http-method-tampering`

`http-method-tampering` (parent): 0 net. The WAF method-evasion source is a NON-MATCH (already named, mechanics delegated to `defence-bypass`). The override-response cache source is already covered by "Method tampering plus caching".

### Group `open-redirect`

`open-redirect` (parent)
- `AttackGoal` and `Artifact` (Chaining Attacks) <- `CBH/hunt-open-redirect/SKILL.md`: open redirect to session fixation, where the victim is forced through a login endpoint with a pre-set session. LOW-MEDIUM.

### Group `subdomain-takeover`

`subdomain-takeover` (parent)
- `AttackTechnique` (Reconnaissance) <- `ACS/W8/performing-dns-enumeration-and-zone-transfer/SKILL.md`: AXFR zone transfer as a name and record inventory source that reveals the full zone, including dangling records. MEDIUM.
- `AttackGoal` and `Artifact` (Chaining Attacks) <- `CBH/hunt-subdomain/SKILL.md`: a claimed host inside a CORS allowlist enables a credentialed cross-origin API read. MEDIUM.
- `AttackTechnique` (Reconnaissance) <- `ACS/W6/exploiting-broken-link-hijacking/SKILL.md`: crawl external script and domain references, check registration status, and test for absent SRI. LOW-MEDIUM, flagged (arguably a distinct class).
- `Artifact` (Chaining Attacks) <- `CBH/hunt-subdomain/SKILL.md`: a wildcard `*.target.com` in an OAuth `reply_to` or `redirect_uri` allowlist lets a claimed dangling host complete a one-click authorization-code theft. LOW.

### Group `broken-function-level-authorization`

`broken-function-level-authorization` (parent)
- `AttackTechnique` <- `CBH/hunt-shadow-api/SKILL.md`: version-inventory plus a behavioural auth/validation diff between an old and the current version of one action.
- `DefensiveControl` <- `ACS/W2/bypassing-authentication-with-forced-browsing/SKILL.md`: the path-normalization bypass set (case, `./`, `..`, `;`, `%2f`, trailing dot/extension, double-encode).
- `ObservableSignal` <- `ACS/W2/exploiting-broken-function-level-authorization/SKILL.md`: the 403-on-GET beside 200-on-PUT method-inconsistency pair as an explicit detection entry.
- `PayloadPattern` <- `CBH/hunt-spa-api/SKILL.md`: client-supplied privilege-flag fields (`is_admin`, `role_id`, `account_type`, `requested_by`).

`bfla-alternate-path`
- `AttackTechnique` <- `CBH/hunt-shadow-api/SKILL.md`: version-inventory plus behavioural regression diff as a concrete alternate-path delta.
- `DefensiveControl` <- `ACS/W2/bypassing-authentication-with-forced-browsing/SKILL.md`: normalization bypass set for the shadow-route step.
- `PreconditionEnvironment` <- `HS/web/authz/authz-bypass/SKILL.md`: proxy path-override headers (`X-Original-URL`, `X-Rewrite-URL`) present in the stack.

`bfla-client-identity-trust`
- `AttackTechnique` <- `AWS/bug-hunting/deep-dive-labs/access-control/SKILL.md`: cookie-carried role flag and request-parameter role as identity sources beside token and header.
- `PreconditionEnvironment` <- `ACS/W2/exploiting-broken-function-level-authorization/SKILL.md`: tenant/organization selector headers present as identity carriers.
- LOW flag: both are likely aspects of the existing selector-as-identity sub-block rather than new deltas.

`bfla-deferred-execution`: clean no-match, none.

### Group `idor`

`idor` (parent)
- `AttackTechnique` <- `CBH/hunt-idor/SKILL.md`: harvest a leaked identifier from one surface to fuel a second, distinct access (double-IDOR chaining).
- `AttackTechnique` <- `CBH/hunt-fintech-graphql/SKILL.md`: the asymmetric binding check where the destination of a debit is validated but the source is not.
- `ObservableSignal` <- `CBH/hunt-idor/SKILL.md`: post-removal or soft-delete temporal access where a cached authorization context still passes.

`idor-direct-object-swap`
- `PayloadPattern` <- `HS/web/authz/bola-idor/SKILL.md`: JSON globbing and extension append (`[id1,id2]`, `*`, `true`, `0`, `-1`, `.json`).
- `ObservableSignal` <- `CBH/hunt-idor/SKILL.md`: the control pair (owner request beside foreign request).

`idor-collection-batch-scope`
- `AttackTechnique` <- `ACS/W2/testing-api-for-broken-object-level-authorization/SKILL.md`: bulk-export endpoint that accepts an array of identifiers and applies no per-item ownership check.
- `AttackTechnique` <- `CBH/hunt-idor/SKILL.md`: indirect filter injection (`sort`, `filter[user_id]`) to skip scoping.

`idor-deferred-artifact-redemption`
- `AttackTechnique` <- `CBH/hunt-idor/SKILL.md`: post-removal token validity where a cached auth context still passes (temporal IDOR).
- `ObservableSignal` <- `CBH/hunt-idor/SKILL.md`: retrieval by a principal that did not create the artifact, persisted after a policy change.

`idor-context-carrier-substitution`
- `AttackTechnique` <- `CBH/hunt-idor/SKILL.md`: a per-resource short-lived token reused across users when only the format is validated.
- `AttackTechnique` <- `CBH/hunt-idor/SKILL.md`: check the same operation at a different API version.

`idor-nested-expansion-binding`
- `AttackTechnique` <- `CBH/hunt-fintech-graphql/SKILL.md`: a per-type field-level check missing on a shared type returned nested inside an unrelated query.
- `AttackTechnique` <- `AWS/bug-hunting/apis/graphql-idor/SKILL.md`: alias multiplex of several principals' nodes in one request with a per-node verdict.

### Group `information-disclosure`

`information-disclosure` (parent)
- `ObservableSignal` <- `CBH/hunt-source-leak/SKILL.md`: content-hashed build artifacts rotate on every deploy, so a 404 at a previously recorded artifact URL is a new build, not remediation. Belongs in False Positives and Pro Tips.
- `AttackTechnique` <- `ACS/W5/performing-graphql-introspection-attack/SKILL.md`: reconstruct a disabled schema from field-suggestion errors (the Clairvoyance pattern).
- `AttackTechnique` <- `CBH/hunt-source-leak/SKILL.md`: fetch-parse-triage of a downloaded artifact for embedded metadata and for auth-gated observability panels as one procedure.
- `Artifact` <- `CBH/hunt-source-leak/SKILL.md`: additional deployable families (asset manifest, build-info, package manifests, server config, `.DS_Store`, crossdomain policy).
- `ObservableSignal` <- `AWS/bug-hunting/deep-dive-labs/access-control/SKILL.md`: a leak inside the body of a redirect response that fires before the 3xx is followed.
- `PreconditionEnvironment` <- `CBH/hunt-cache-poison/SKILL.md`: an origin that caches a dynamic or authenticated response under a static-looking path key. Propose only the authorization-delta step; generic cache mechanics stay with `proxy-techniques`.

`error-verbosity-disclosure`
- `ObservableSignal` <- `CBH/hunt-exceptional-conditions/SKILL.md`: fail-open, where the error path executes the action rather than only disclosing.
- `AttackTechnique` <- `CBH/hunt-source-leak/SKILL.md`: debug, actuator, version, and build-info endpoint enumeration.
- `PayloadPattern` <- `CBH/hunt-exceptional-conditions/SKILL.md`: the one-assumption-at-a-time break set (wrong type, malformed body, oversized field, null byte).

`stored-artifact-disclosure`
- `ObservableSignal` <- `CBH/hunt-source-leak/SKILL.md`: content-hash rotation as a false-positive and pro-tip entry.
- `AttackTechnique` <- `ACS/W5/performing-graphql-introspection-attack/SKILL.md`: schema reconstruction from field-suggestion errors when introspection is closed.
- `Artifact` <- `CBH/hunt-source-leak/SKILL.md`: additional deployable families.
- `AttackTechnique` <- `CBH/hunt-spa-api/SKILL.md`: route and secret harvest from lazy-loaded async chunks, not only the shell-referenced bundles.

`differential-oracle-disclosure`
- `AttackTechnique` <- `CBH/hunt-cache-poison/SKILL.md`: force the cache to store an authenticated response via a static-looking path append or delimiter, then read it unauthenticated (web cache deception).
- `AttackTechnique` <- `CBH/hunt-cache-poison/SKILL.md`: force a cache miss with a cache-busting query parameter rather than `Cache-Control: no-cache`.
- `ObservableSignal` <- `AWS/bug-hunting/deep-dive-labs/cache-deception/SKILL.md`: origin-versus-cache path-normalization disagreement.

### Group `mass-assignment`

`mass-assignment` (parent)
- `PayloadPattern` <- `ACS/W5/exploiting-mass-assignment-in-rest-apis/SKILL.md`: temporal and audit fields (`created_at`, `updated_at`, `created_by`) as a candidate family for audit-log manipulation.
- `AttackTechnique` <- `ACS/W5/testing-api-for-mass-assignment-vulnerability/SKILL.md`: framework-specific binder shapes (model-nested key, form-bracket keys, ORM operator `$set`, `_id` override). Flag: `$set` and `_id` cross into `nosql-injection`; propose only the binder-differential framing.
- `AttackTechnique` <- `CBH/hunt-api-misconfig/SKILL.md`: OData `$expand` navigation-property binding where authorization decorators cover the top-level entity set but not the joined entity. Flag: OData is a distinct protocol; check the boundary.
- `AttackTechnique` <- `CBH/hunt-fintech-graphql/SKILL.md`: admin-shaped input fields (`status`, `override`) accepted by a mutation the client never exposes.
- `PreconditionEnvironment` <- `ACS/W5/exploiting-mass-assignment-in-rest-apis/SKILL.md`: an exposed OpenAPI `components.schemas` enumerating every model field, including privileged ones.

`mass-assignment-nested-relation-write`
- `AttackTechnique` <- `CBH/hunt-api-misconfig/SKILL.md`: the joined-entity authorization gap on a navigation-property expansion as a nested-write shape.
- `PayloadPattern` <- `HS/web/authz/mass-assignment/SKILL.md`: nested-object and array-for-scalar shapes reaching a child binder.

`mass-assignment-bulk-collection-injection`: clean no-match, none.
`mass-assignment-bulk-nested-relation-write`: clean no-match, none.

### Group `business-logic`

`business-logic` (parent)
- `AttackTechnique` <- `AWS/bug-hunting/deep-dive-labs/business-logic/SKILL.md` and `ACS/W6/testing-for-business-logic-vulnerabilities/SKILL.md`: inconsistent-identity-domain logic (register under an allowed domain, then move the identity to a privileged domain).
- `AttackTechnique` <- `AWS/bug-hunting/deep-dive-labs/business-logic/SKILL.md`: a flawed state machine where dropping a role-selection request leaves the default role privileged.
- `AttackTechnique` <- `ACS/W6/testing-for-business-logic-vulnerabilities/SKILL.md`: invitation or delegation abuse where the inviter grants a role above its own ceiling. Flag: boundary to `two-principal-authz`.
- `AttackTechnique` <- `ACS/W6/testing-for-business-logic-vulnerabilities/SKILL.md`: gift-card circular value (buy with gift balance) and change-as-credit.
- `ObservableSignal` <- `CBH/hunt-business-logic/SKILL.md`: an unvalidated payment-provider webhook (no signature) as a downstream-trust signal.

`concurrent-duplication`
- `AttackTechnique` <- `CBH/hunt-fintech-graphql/SKILL.md`: single-request alias-batched duplicate submission as a pre-parallel confirmation step.
- `ObservableSignal` <- `CBH/hunt-business-logic/SKILL.md`: a second distinct transaction identifier from an identical idempotency key.

`value-domain-manipulation`
- `AttackTechnique` <- `CBH/hunt-fintech-graphql/SKILL.md`: a custom `Decimal`/`Money` scalar that falls back to native float parsing under scientific notation or oversized strings.
- `AttackTechnique` <- `CBH/hunt-business-logic/SKILL.md`: mid-flow price-version swap against an archived price (cart-state TOCTOU).
- `AttackTechnique` <- `AWS/bug-hunting/deep-dive-labs/business-logic/SKILL.md`: identity-domain and email-truncation boundary cases feeding an entitlement change.

`quota-window-slicing`: clean no-match, none.

`async-boundary-abuse`
- `AttackTechnique` <- `CBH/hunt-business-logic/SKILL.md`: an unvalidated payment-provider webhook (no HMAC) as a downstream-trust trigger.
- `AttackTechnique` <- `CBH/hunt-fintech-graphql/SKILL.md`: a resolver that writes debit, credit, and fee entries as separate statements, opening a between-call mutation window.

### Group `two-principal-authz`

`two-principal-authz` (parent)
- `AttackTechnique` <- `CBH/hunt-spa-api/SKILL.md`: establish a control endpoint that is gated, then compare a whole route family against it.
- `AttackTechnique` <- `CBH/hunt-fintech-graphql/SKILL.md`: asymmetric binding where the destination of a debit is validated but the source is not.
- `AttackerCapability` <- `CBH/hunt-idor/SKILL.md`: hold a harvested identifier corpus from other surfaces before the swap.
- `ObservableSignal` <- `CBH/hunt-spa-api/SKILL.md`: a 400 "field X is mandatory" response that reached business-logic validation without an auth check.
- `ObservableSignal` <- `CBH/hunt-idor/SKILL.md`: a post-removal or soft-delete token still passing (temporal binding gap).

### Group `crypto-weakness`

`crypto-weakness` (parent)
- `AttackTechnique` <- `CBH/hunt-jwt-crypto/SKILL.md` and `HS/web/auth/jwt-misconfig/SKILL.md`: key-source injection (the verifier derives its key from attacker-controlled token input: `kid` path traversal, `jku`/`x5u` URL, embedded `jwk`). Flag: overlaps `authentication-jwt`, the natural JWT-specific owner.
- `PayloadPattern` <- `CBH/hunt-jwt-crypto/SKILL.md`: claim-swap for cross-tenant access (mint the claim set that controls identity, role, or tenant).
- `AttackTechnique` <- `CBH/hunt-jwt-crypto/SKILL.md`: automation-first recon (run the forgery suite before manual chaining). Pro Tip, not a step.
- `ObservableSignal` <- `CBH/hunt-session/SKILL.md`: rotation-reuse detection (replay a superseded refresh token, watch for a reuse alarm). Flag: route to `oauth` or `authentication-jwt`.

`crypto-predictable-token`
- `AttackTechnique` <- `HS/web/session/cookie-attacks/SKILL.md`: entropy-bound adjudication (collect a large sample, compare effective bits against the strong-randomness bound).

`crypto-signing-key-forgery`
- `AttackTechnique` <- `CBH/hunt-jwt-crypto/SKILL.md`: key-source injection as a third technique block beside offline search and algorithm removal.
- `AttackTechnique` <- `CBH/hunt-jwt-crypto/SKILL.md`: local-verify-before-send discipline. LOW value.
- `AttackTechnique` <- `HS/web/auth/jwt-misconfig/SKILL.md`: expiry and `nbf` claim manipulation. LOW value.

`crypto-timing-oracle`: clean no-match, none.

### Group `insecure-deserialization`

`insecure-deserialization` (parent)
- `AttackTechnique` and `PayloadPattern` <- `CBH/hunt-deserialization/SKILL.md`: interpolation-triggered remote lookup (JNDI and Log4Shell), where a reference value in an ordinary field causes a remote codebase fetch over LDAP/RMI. Add to the parent and to `deserialization-gadget-chain` first; if the remote-fetch step proves uncoverable by "reference-triggered resolution", escalate to a fourth variant `deserialization-remote-lookup`.
- `AttackTechnique` <- `CBH/hunt-aspnet/SKILL.md`: dual-parser MAC bypass (binding-region disagreement between two parsers).
- `AttackTechnique` <- `CBH/hunt-aspnet/SKILL.md`: machineKey or signing-key recovery from known plaintext. LOW value.
- `PayloadPattern` <- `CBH/hunt-deserialization/SKILL.md`: `phar://` polyglot construction (valid image magic bytes plus a PHAR archive).
- `AttackTechnique` <- `AWS/bug-hunting/web-vulnerabilities/php-deserialization-rce/SKILL.md`: type-juggling inside a PHP serialized string. LOW value.

`deserialization-gadget-chain`
- `AttackTechnique` <- `AWS/bug-hunting/deserialization/java-insecure-deserialization-ysoserial/SKILL.md`: the `URLDNS` gadget as the canonical no-exec oracle (DNS-only gadget as the cheapest liveness probe).
- `AttackTechnique` <- `CBH/hunt-deserialization/SKILL.md`: the JNDI lookup technique (if kept at the parent, no duplication here).

`deserialization-signed-forgery`
- `AttackTechnique` <- `CBH/hunt-aspnet/SKILL.md`: dual-parser MAC bypass. Best home is this variant's Bypass Techniques.
- `AttackTechnique` <- `CBH/hunt-aspnet/SKILL.md`: known-plaintext machineKey recovery.
- `ObservableSignal` <- `CBH/hunt-aspnet/SKILL.md`: "signed-only versus encrypted" adjudication (distinguish a signed-but-readable blob from an encrypted one before choosing strip versus recover).

`deserialization-deferred-trigger`
- `PayloadPattern` <- `CBH/hunt-deserialization/SKILL.md`: `phar://` polyglot (image magic bytes plus archive) so the plant survives upload inspection.
- `AttackTechnique` <- `CBH/hunt-deserialization/SKILL.md`: trigger enumeration breadth (any filesystem function on a `phar://` path). LOW value.

### Group `insecure-file-uploads`

`insecure-file-uploads` (parent)
- `AttackTechnique` <- `CBH/hunt-file-upload/SKILL.md`: browser-engine renderer abuse (HTML-to-PDF, screenshot, and report services run a headless browser that fetches internal URLs, reads `file://` paths, and may execute JavaScript). Flag: the fetch impact overlaps `ssrf` and the script impact overlaps `xss`; name those skills at the fetch and render steps.
- `AttackTechnique` <- `CBH/hunt-file-upload/SKILL.md`: FFmpeg HLS and concat demuxer fetch. MEDIUM value.
- `DefensiveControl` <- `HS/web/logic/insecure-file-upload/SKILL.md`: content-type sniffing when no guard header is present. Covered.
- `PayloadPattern` <- `CBH/hunt-file-upload/SKILL.md`: polyglot families. Covered.

`upload-server-execution`
- `AttackTechnique` <- `CBH/hunt-file-upload/SKILL.md`: configuration-file upload to re-enable handlers (`.htaccess`, `web.config`). Covered.
- `AttackTechnique` <- `CBH/hunt-file-upload/SKILL.md`: extension-alternate lists (`.phtml`, `.phar`, `.php5`, `.pht`). LOW value.

`upload-client-execution`
- `ObservableSignal` <- `CBH/hunt-file-upload/SKILL.md`: same-origin serving as the deciding signal. Add only the explicit "same origin versus sandboxed" adjudication if absent.

`upload-archive-extraction`
- `AttackTechnique` <- `CBH/hunt-lfi/SKILL.md`: outside-write canary confirmation. Covered.
- `AttackTechnique` <- `CBH/hunt-file-upload/SKILL.md`: compression-ratio exhaustion. Covered.

`upload-toolchain-execution`
- `AttackTechnique` <- `CBH/hunt-file-upload/SKILL.md`: browser-engine renderer abuse. Best home is this variant.
- `AttackTechnique` <- `CBH/hunt-lfi/SKILL.md`: pseudo-protocol coders (`msl:`, `ephemeral:`, `label:@`) as a read-sink without a file parameter. MEDIUM value.

`upload-pipeline-deferred-trust`
- `AttackTechnique` <- `CBH/hunt-file-upload/SKILL.md`: metadata swap between initiation and completion. Covered.

### Group `path-traversal-lfi-rfi`

`path-traversal-lfi-rfi` (parent)
- `AttackTechnique` and `PayloadPattern` <- `CBH/hunt-lfi/SKILL.md`: PHP filter-chain payload synthesis. If not the A6 variant, the top enrichment to `lfi-include-execution`.
- `ObservableSignal` <- `CBH/hunt-lfi/SKILL.md`: blind-read confirmation via an out-of-band callback with a unique sub-tag per sink, plus a triple-confirmed timing or length delta.
- `AttackTechnique` <- `CBH/hunt-lfi/SKILL.md`: read the log plainly before poisoning it, to confirm readability. LOW value.
- `AttackTechnique` <- `CBH/hunt-lfi/SKILL.md`: non-parameter traversal surfaces (archive extract and image-coder read-sinks with no `?file=` parameter). MEDIUM value.

`traversal-read`
- `ObservableSignal` <- `CBH/hunt-lfi/SKILL.md`: OOB blind-read confirmation. Best home is this variant's Detection Channels.
- `AttackTechnique` <- `CBH/hunt-lfi/SKILL.md`: the false-positive gate for reflected paths and lone status changes. MEDIUM value.

`lfi-include-execution`
- `AttackTechnique` and `PayloadPattern` <- `CBH/hunt-lfi/SKILL.md`: filter-chain payload synthesis. Primary enrichment to this variant.
- `AttackTechnique` <- `CBH/hunt-lfi/SKILL.md`: code-execution wrapper prerequisites (`data://`, `php://input`, `expect://` each require an enablement flag). LOW value.

`rfi-remote-include`
- `AttackTechnique` <- `CBH/hunt-lfi/SKILL.md`: fetch-only confirmation when execution is blocked. Covered, LOW value.
- `AttackTechnique` <- `CBH/hunt-lfi/SKILL.md`: appended-extension truncation (`?` or `#`) for RFI paths. LOW value.

`archive-zipslip-write`
- `AttackTechnique` <- `CBH/hunt-lfi/SKILL.md`: tar preserves symlinks, so a symlink entry plus a follow-on write escapes where zip entries may be sanitised. MEDIUM value.
- `AttackTechnique` <- `CBH/hunt-file-upload/SKILL.md`: write to a cron or template location for persistence. Covered.

### Group `graphql`

`graphql` (parent, non-decomposing)
- `AttackTechnique` <- `CBH/hunt-graphql/SKILL.md`: cross-API dual-write state desync (revoke through REST, re-assert through the GraphQL mutation). Flag: overlaps `business-logic` and `race-conditions`.
- `DefensiveControl` <- `CBH/hunt-graphql/SKILL.md`: query-cost-calculator abuse (a negative list argument contributes a negative cost and refills the request budget).
- `AttackTechnique` <- `CBH/hunt-graphql/SKILL.md`: subscription hijack, as the enrichment alternative if A7 is not created.
- `AttackTechnique` <- `CBH/hunt-fintech-graphql/SKILL.md`: money-movement mutation sweep. MEDIUM value.
- `AttackTechnique` <- `AWS/bug-hunting/api-security/graphql-injection-introspection/SKILL.md`: backward graph traversal to a guarded field through a public parent. Covered.
- `ObservableSignal` <- `CBH/hunt-graphql/SKILL.md`: alias-batching race adjudication (aliases win only under concurrent resolver execution). MEDIUM value, overlaps `race-conditions`.

### Group `llm-prompt-injection`

`llm-prompt-injection` (parent)
- `PayloadPattern` <- `CBH/hunt-llm-ai/SKILL.md`: Unicode Tags-block smuggling (U+E0000 to U+E007F) plus zero-width and bidi variants.
- `AttackTechnique` <- `CBH/hunt-llm-ai/SKILL.md` and `AWS/ai-red-teaming/llm-attacks/llm-indirect-prompt-injection/SKILL.md`: multimodal image-embedded instructions (low-contrast text, EXIF, metadata).
- `AttackTechnique` <- `CBH/hunt-llm-ai/SKILL.md`: DNS-only exfil (base32 label) plus tool-use fetch to cloud metadata.
- `AttackTechnique` <- `AWS/ai-red-teaming/agent-security/ai-agent-tool-abuse-and-privilege-escalation/SKILL.md`: implicit trust in tool responses (a poisoned file, database field, or API response carries instructions the agent follows).
- `AttackTechnique` <- `CBH/hunt-rag-vector/SKILL.md`: retrieval hijack by embedding-proximity dominance.
- `AttackTechnique` <- `CBH/hunt-llm-ai/SKILL.md`: AI code-completion sabotage. LOW confidence, thin evidence, may be its own class.
- `AttackTechnique` <- `CBH/hunt-llm-ai/SKILL.md`: ASI01 to ASI10 agentic mapping, abstracted to capability classes only.
- `PayloadPattern` <- `AWS/ai-red-teaming/model-exploitation/ai-jailbreak-obfuscation-ciphers/SKILL.md`: cipher and encoding bypass (Base64, ROT13, leetspeak) of keyword classifiers.
- `AttackTechnique` <- `AWS/ai-red-teaming/model-exploitation/prompt-leaking-system-prompts/SKILL.md`: output-encoding evasion for extraction.
- `AttackTechnique` <- `AWS/ai-red-teaming/agent-security/mcp-protocol-exploitation/SKILL.md`: tool-permission enforcement gap and cross-tool chain (if A8 is not created).

`direct-injection-override`
- `PayloadPattern` <- `AWS/ai-red-teaming/llm-attacks/llm-direct-prompt-injection/SKILL.md`: JSON-role and XML-tag framing to match the target templating.
- `PayloadPattern` <- `AWS/ai-red-teaming/model-exploitation/ai-jailbreak-obfuscation-ciphers/SKILL.md`: cipher and encoding bypass.
- `AttackTechnique` <- `AWS/ai-red-teaming/llm-attacks/llm-direct-prompt-injection/SKILL.md`: context-window flush (long filler then extraction). LOW value.

`indirect-injection-plant`
- `AttackTechnique` <- `CBH/hunt-llm-ai/SKILL.md`: multimodal image placements. Best home is Hidden Placement.
- `AttackTechnique` <- `CBH/hunt-rag-vector/SKILL.md`: retrieval hijack and embedding-surface maximisation. Best home is Corpus Seeding.
- `AttackTechnique` <- `AWS/ai-red-teaming/agent-security/ai-agent-tool-abuse-and-privilege-escalation/SKILL.md`: implicit trust in tool responses, a second-order ingestion source.
- `PayloadPattern` <- `AWS/ai-red-teaming/llm-attacks/llm-indirect-prompt-injection/SKILL.md`: HTML-comment, hidden-div, and markdown-comment placements. Mostly covered, LOW value.
- `AttackTechnique` <- `CBH/hunt-llm-ai/SKILL.md`: second-session verification rule (a clean session must inherit the poison). MEDIUM value.

`context-leakage`
- `AttackTechnique` <- `AWS/ai-red-teaming/model-exploitation/prompt-leaking-system-prompts/SKILL.md`: output-encoding evasion (request the hidden text Base64-encoded to bypass output filters).
- `AttackTechnique` <- `CBH/hunt-llm-ai/SKILL.md`: anchor to a non-guessable string to defeat confabulation. LOW value.
- `AttackTechnique` <- `CBH/hunt-llm-ai/SKILL.md`: tool-schema extraction as the entry to SSRF or command injection. MEDIUM value.

`tool-abuse`
- `AttackTechnique` <- `CBH/hunt-llm-ai/SKILL.md`: tool-use fetch to cloud metadata (an SSRF primitive with an elevated network position).
- `AttackTechnique` <- `AWS/ai-red-teaming/agent-security/mcp-protocol-exploitation/SKILL.md`: tool-permission enforcement gap and capability leak. MEDIUM value.
- `AttackTechnique` <- `AWS/ai-red-teaming/agent-security/ai-agent-tool-abuse-and-privilege-escalation/SKILL.md`: progressive escalation and capability boundary testing. LOW-MEDIUM value.
- `AttackTechnique` <- `AWS/ai-red-teaming/agent-security/ai-agent-tool-abuse-and-privilege-escalation/SKILL.md`: persistence through the agent (scheduled task, key placement). LOW value.

`output-handling`
- `AttackTechnique` <- `CBH/hunt-llm-ai/SKILL.md`: DNS-only exfil (base32 label) when HTTP egress is filtered. MEDIUM value.
- `AttackTechnique` <- `CBH/hunt-llm-ai/SKILL.md`: per-sink sub-tagged callbacks so the firing feature is attributable. LOW value.

### Group `nosql-injection`

`nosql-injection` (parent)
- `AttackTechnique` <- `AWS/bug-hunting/deep-dive-labs/nosql-injection/SKILL.md`: blind field-name and schema enumeration through a document-introspection primitive character by character.
- `AttackTechnique` <- `CBH/hunt-nosqli/SKILL.md`: string-context syntax breakout into a concatenated script predicate. MEDIUM confidence, the grammar clause may already cover it.
- `AttackTechnique` <- `CBH/hunt-nosqli/SKILL.md`: the key-value store reach through an SSRF or proxy relay to its command port. Route it to the `ssrf` and `proxy-techniques` families at the frame clause.

### Group `prototype-pollution`

`prototype-pollution` (parent)
- `AttackTechnique` <- `ACS/W3/exploiting-prototype-pollution-in-javascript/SKILL.md`: denial of service through coercion-primitive pollution (`toString`/`valueOf`).
- `AttackTechnique` <- `AWS/bug-hunting/deep-dive-labs/prototype-pollution/SKILL.md`: data exfiltration through response-shaping properties (pollute serialization options, then read a reflected surface).
- `ObservableSignal` <- `AWS/bug-hunting/deep-dive-labs/prototype-pollution/SKILL.md` and `ACS/W3/exploiting-prototype-pollution-in-javascript/SKILL.md`: reflection-free confirmation by polluting a property with a deliberate observable side effect.

### Group `sql-injection`

`sql-injection` (parent)
- `AttackTechnique` <- `ACS/W3/performing-second-order-sql-injection/SKILL.md` and `AWS/bug-hunting/web-vulnerabilities/advanced-sql-injection-sqli/SKILL.md`: expand the two-line second-order advanced technique into storage-point and trigger-point mapping plus cross-context execution.
- `PreconditionEnvironment` <- `CBH/hunt-sqli/SKILL.md`: authenticated-only injection surfaces as a recon target. MEDIUM confidence, pro-tip-shaped.

### Group `ssti`

`ssti` (parent)
- `AttackTechnique` <- `CBH/hunt-ssti/SKILL.md` and `AWS/bug-hunting/deep-dive-labs/ssti/SKILL.md`: expression-context break-out, where the injected value lands inside an existing expression and the payload closes the surrounding context before opening its own.
- `AttackTechnique` <- `CBH/hunt-ssti/SKILL.md`: length-constrained field staging (confirm with a short probe, dump the object list, select the execution index in a second probe).
- `AttackTechnique` <- `CBH/hunt-ssti/SKILL.md`: the deferred sink is frequently an outbound message or generated document. LOW confidence, likely already covered.

### Group `xxe`

`xxe` (parent)
- `AttackTechnique` <- `CBH/hunt-xxe/SKILL.md`: XSLT-extension execution, where a reachable transform processor exposes an extension that runs host code.
- `PreconditionEnvironment` <- `CBH/hunt-xxe/SKILL.md` and `ACS/W3/testing-for-xxe-injection-vulnerabilities/SKILL.md`: content-type negotiation probing (a JSON-accepting endpoint retried as XML to expose a hidden parser).
- `AttackTechnique` <- `CBH/hunt-xxe/SKILL.md`: the inline-entity pre-flight gate (define an internal entity, reference it, confirm expansion before investing in SYSTEM reads). MEDIUM confidence.

### Group `weak-credential-discovery`

`weak-credential-discovery` (parent)
- `AttackTechnique` <- `CBH/offensive-osint/references/secret-validators.md`: credential liveness and scope validation against the issuing service's read-only identity endpoint.
- `AttackTechnique` <- `CBH/offensive-osint/references/secret-validators.md`: weigh the detectability cost of validating a credential before confirming it.
- `PreconditionEnvironment` <- `CBH/hunt-source-leak/SKILL.md`: extend the deployable-artifact family with build and bundle artifacts (source maps, asset manifests, API specification documents, build-info files).
- `AttackTechnique` <- `HS/web/auth/default-credentials/SKILL.md`: client-side-only lockout bypass (a JavaScript-enforced lockout skipped by sending requests directly). MEDIUM confidence; may belong to `defence-bypass`.

### Group `header-injection`

`header-injection` (parent)
- `PreconditionEnvironment` <- `CBH/hunt-host-header/SKILL.md`: add the OIDC discovery/issuer document (`.well-known/openid-configuration`) as a link-generating oracle. MEDIUM.
- `AttackTechnique` <- `AWS/bug-hunting/web-vulnerabilities/host-header-injection-attacks/SKILL.md`: add the double-Host and absolute-URL-override shapes to the authority-family probe set.
- `ObservableSignal` <- `ACS/W6/testing-for-host-header-injection/SKILL.md`: add virtual-host enumeration as a distinct read-out (status/size delta across forged authority values). MEDIUM.

`header-crlf-splitting`: clean no-match, none.

`header-cache-poisoning`
- `PayloadPattern` <- `ACS/W6/performing-web-cache-deception-attack/SKILL.md`: add the delimiter-based path-discrepancy family (semicolon delimiter, encoded slash/percent, null byte, fragment, dot-segment normalization, case variation, double-encoded path).
- `AttackTechnique` <- `CBH/hunt-cache-poison/SKILL.md`: add the cached-CORS-header shape (Origin reflected into the allow-origin value and stored).
- `AttackTechnique` <- `CBH/hunt-cache-poison/SKILL.md`: add the fat-GET shape and the cached-error DoS shape.
- `AttackTechnique` <- `CBH/hunt-cache-poison/SKILL.md`: add the cache-buster discipline (probe under a fresh throwaway key).

`header-host-forward-spoof`
- `PayloadPattern` <- `CBH/hunt-host-header/SKILL.md`: add the host-shape edges (trailing-port, userinfo split on `@`, suffixed-host absolute-URL form).
- `PreconditionEnvironment` <- `CBH/hunt-host-header/SKILL.md`: add the OIDC discovery document as a second link-generating oracle, plus the "the two layers never compose" caution. MEDIUM.
- `ObservableSignal` <- `ACS/W6/testing-for-host-header-injection/SKILL.md`: add the virtual-host enumeration read-out. MEDIUM.

`header-method-override`
- `PayloadPattern` <- `CBH/hunt-host-header/SKILL.md`: add the `X-Override-URL` alias to the rewrite-header family.
- `AttackTechnique` <- `CBH/hunt-host-header/SKILL.md`: add the proof rule that the override is confirmed by a status/body diff against the edge-blocked direct request.

`header-request-smuggling`
- `AttackTechnique` <- `AWS/bug-hunting/web-vulnerabilities/http-request-smuggling-te-te/SKILL.md`: add the encoding-declaration obfuscation value set (spacing before the colon, invalid value spelling, obsolete folded-continuation form).
- `ObservableSignal` <- `CBH/hunt-http-smuggling/SKILL.md`: add the anomalous-response-to-a-normal-request signal. MEDIUM.

`header-response-value-confusion`
- `DefensiveControl` <- `HS/web/session/cookie-attacks/SKILL.md`: add the `__Host-` and `__Secure-` name prefixes as the hardening control.
- `PayloadPattern` <- `HS/web/session/cookie-attacks/SKILL.md`: add the cross-site-attribute semantics (`None` versus `Lax` versus `Strict`, leading-dot domain widens to siblings).

### Group `http-request-smuggling`

`http-request-smuggling` (parent)
- `Reconnaissance`/`AttackTechnique` <- `CBH/hunt-http-smuggling/SKILL.md`: add the abstract front-end strictness check as a gating step.
- `AttackTechnique` <- `CBH/hunt-http-smuggling/SKILL.md`: add the collector-gadget capture procedure.
- `ObservableSignal` <- `ACS/W6/exploiting-http-request-smuggling/SKILL.md`: add the paired-request differential confirmation.

`http-request-smuggling-h2-desync`
- `PayloadPattern` <- `ACS/W6/exploiting-http-request-smuggling/SKILL.md`: keep H2.CL and H2.TE as enumerated injection values and add the cleartext-upgrade and CONNECT tunneling shapes as aspect values.

### Group `race-conditions`

`race-conditions` (parent)
- `AttackTechnique` <- `CBH/hunt-race-condition/SKILL.md`: name the single-packet attack and last-byte-sync mechanism precisely, and add wire-capture validation.
- `AttackTechnique` <- `CBH/hunt-race-condition/SKILL.md`: add first-sequence-sync as the widening primitive.
- `AttackTechnique` <- `CBH/hunt-race-condition/SKILL.md`: add the race-window estimation decision tree.
- `PreconditionEnvironment` <- `CBH/hunt-race-condition/SKILL.md`: add the client-side-only guard precondition.
- `Reconnaissance`/`AttackTechnique` <- `CBH/hunt-race-condition/SKILL.md`: add the white-box read-then-write grep step.
- `AttackTechnique` <- `ACS/W5/performing-api-rate-limiting-bypass/SKILL.md`: resolve the base open question (identity-partitioned quota bursts) to "aspect, not variant", and enrich the existing rate-limit aspect with the counter-window burst rule.

`idempotency-dedup-bypass`
- `AttackTechnique` <- `CBH/hunt-race-condition/SKILL.md`: add the response-versus-effect forensics rule and the partial-fulfilment case.

`optimistic-guard-evasion`
- `AttackTechnique` <- `CBH/hunt-race-condition/SKILL.md`: add the cross-path enforcement probe.

`single-request-fanout`
- `PayloadPattern` <- `AWS/bug-hunting/api-security/graphql-batching-attacks/SKILL.md`: add the two concrete fan-out envelopes (an array of distinct operations; alias-named repetitions).
- `AttackGoal` <- `AWS/bug-hunting/api-security/graphql-batching-attacks/SKILL.md`: add the amplification-DoS outcome. MEDIUM.

`cross-service-consistency-race`
- `AttackTechnique` <- `CBH/hunt-race-condition/SKILL.md`: add the retry-storm induction procedure and the queue-multiplicity probe.

### Group `rce`

`rce` (parent)
- `AttackTechnique`/`PayloadPattern` <- `CBH/hunt-rce/SKILL.md`: add the content-type-to-parser matching rule as a first-class command-injection step. The strongest single enrichment in the group.
- `PreconditionEnvironment` <- `HS/web/injection/cmd-injection/SKILL.md`: add the utility-style surface family as a reconnaissance applicability signal.
- `AttackTechnique` <- `CBH/hunt-rce/SKILL.md`: add the out-of-band confirmation procedure (DNS and HTTP callbacks with a unique marker, and the base64-encoded subdomain exfil shape).
- `PayloadPattern` <- `CBH/hunt-rce/SKILL.md` and `AWS/bug-hunting/web-vulnerabilities/command-injection-os-level/SKILL.md`: add the reflection-indirection bypass shapes and the whitespace-bypass shapes.

`rce-command-injection`
- `AttackTechnique` <- `CBH/hunt-rce/SKILL.md`: add the argument-file-expansion shape (`@file` argument expansion by a Java-style CLI). MEDIUM.
- `PayloadPattern` <- `AWS/bug-hunting/web-vulnerabilities/command-injection-os-level/SKILL.md`: add the whitespace-bypass value set and the Windows caret-escape value.
- `PayloadPattern` <- `HS/web/injection/cmd-injection/SKILL.md`: add the path-component substitution value (`${PATH:0:1}`-style character extraction).
- `AttackTechnique` <- `ACS/W3/exploiting-api-injection-vulnerabilities/SKILL.md`: add the API injection-point inventory (path, query, body, header carriers).

`rce-pipeline-execution`
- `AttackTechnique` <- `CBH/hunt-rce/SKILL.md`: add the policy-gate and compile-flag fallback reasoning. This partially answers the base open question about a delegate matrix.

### Group `xss`

`xss` (parent)
- `AttackTechnique`/`Pro Tips` <- `CBH/hunt-xss/SKILL.md`: add the marker baseline-search discipline (search the no-marker baseline first).
- `PreconditionEnvironment`/`ObservableSignal` <- `CBH/hunt-xss/SKILL.md`: add the blind-XSS beacon-field family and the browser-user-agent confirmation rule.
- `PayloadPattern` <- `CBH/hunt-xss/SKILL.md`: add the sanitizer round-trip value set (math-plus-style and svg-plus-style parsing-ambiguity combinations).
- `PayloadPattern` <- `CBH/hunt-xss/SKILL.md`: add the client-side expression-evaluation sandbox-escape value set.
- `PreconditionEnvironment` <- `AWS/bug-hunting/web-vulnerabilities/dom-based-xss/SKILL.md`: add the cross-navigation client source (`window.name`).
- `AttackTechnique`/`Chaining Attacks` <- `CBH/hunt-xss/SKILL.md`: add the self-XSS-plus-CSRF-trigger chain.
- `DefensiveControl` <- `AWS/bug-hunting/web-vulnerabilities/dom-based-cross-site-scripting-xss/SKILL.md`: add the Trusted-Types policy beside the existing nonce/hash policy control.
- `DefensiveControl` <- `ACS/W4/performing-content-security-policy-bypass/SKILL.md`: the CSP bypass families belong to `defence-bypass`, not the `xss` body. Record as an out-of-slice enrichment for `defence-bypass`. No `xss` body change.

`xss-stored`
- `PreconditionEnvironment`/`AttackTechnique` <- `CBH/hunt-xss/SKILL.md`: add the blind-stored beacon-field family and the "plant early, keep the listener open" discipline.
- `AttackTechnique` <- `CBH/hunt-xss/SKILL.md`: add the reflected-to-stored conversion via a cache layer. Ownership of the cache mechanics stays with the `header-injection` cache leaf.

`xss-dom`
- `PreconditionEnvironment` <- `AWS/bug-hunting/web-vulnerabilities/dom-based-xss/SKILL.md`: add `window.name` as a client source family.
- `AttackTechnique` <- `CBH/hunt-dom/SKILL.md`: add the weak-origin-check bypass to the cross-document-message source family.
- `ObservableSignal` <- `CBH/hunt-dom/SKILL.md`: add the "source reachable but sink never invoked" negative read-out.

### Group `ssrf`

`ssrf` (parent)
- `False Positives` <- `CBH/hunt-ssrf/SKILL.md`: add the error-echo false positive. The single highest-value addition, the most common mis-report.
- `AttackTechnique` <- `CBH/hunt-ssrf/SKILL.md`: add the per-parameter attribution procedure (one fresh token per candidate field, with a negative control).
- `AttackTechnique` <- `CBH/hunt-ssrf/SKILL.md`: add the blind-versus-full-read settlement.
- `AttackTechnique` <- `CBH/hunt-ssrf/SKILL.md`: add the JavaScript-execution renderer sink.
- `AttackTechnique` <- `CBH/hunt-ssrf/SKILL.md`: add the trusted-internal-redirector shape.
- `PayloadPattern` <- `CBH/hunt-ssrf/SKILL.md`: add the wrapped/encoded destination family, with the rule that the number of decode passes before the fetch is the bug.
- `PayloadPattern` <- `CBH/hunt-ssrf/SKILL.md`: add the parser-confusion address shapes (userinfo split on `@`, fragment before host, encoded `@`, backslash before host).
- `PreconditionEnvironment` <- `AWS/ai-red-teaming/model-exploitation/ai-data-extraction-via-ssrf/SKILL.md`: add the LLM-tool carrier. MEDIUM.

`no-response-egress-inference`
- `AttackTechnique` <- `ACS/W6/performing-blind-ssrf-exploitation/SKILL.md`: add the internal-range sweep and port-scan timing loop with known-open and known-closed control points.
- `ObservableSignal` <- `CBH/hunt-ssrf/SKILL.md`: add the distinct-status-on-link-local signal.

`scheme-translated-command-execution`
- `AttackTechnique` <- `CBH/hunt-ssrf/SKILL.md`: add the store-to-scheduled-write pivot shape.

`header-gated-cloud-credential-read`
- `AttackTechnique` <- `AWS/cloud-security/aws-imdsv2-ssrf-bypass/SKILL.md`: add the token-request header value and the role-name-then-credentials two-read step, plus the negative rule that a GET-only sink cannot open the gate.
- `PreconditionEnvironment`/`AttackTechnique` <- `AWS/cloud-security/aws-metadata-ssrf-exploitation/SKILL.md`: add the instance user-data path as a metadata target.

### Group `defence-bypass`

`defence-bypass` (parent)
- `AttackTechnique` <- `ACS/W9/performing-web-application-firewall-bypass/SKILL.md`: a mechanism-selection order for the "Select the mechanism" step (control fingerprint, then encoding, then protocol, then parser quirk, then rule-specific gap).
- `DefensiveControl` <- `CBH/security-arsenal/SKILL.md`: the "WAF evaluation order matters" ordering (encoding, then parser quirks, then protocol-level, then vendor-rule-specific).
- `ObservableSignal` <- `ACS/W9/performing-web-application-firewall-bypass/SKILL.md`: the control's own vendor marker in its denial signal (`cf-ray`, `x-amzn-requestid`, `AkamaiGHost`, `incap_ses`).
- `Artifact` <- `ACS/W9/performing-web-application-firewall-bypass/SKILL.md`: a successful bypass payload recorded against the refused original.

`defence-bypass-signature-evasion`
- `AttackTechnique` <- `CBH/hunt-api-misconfig/SKILL.md`: a query-language operator obfuscation procedure (mixed case, encoded metacharacter, obscure sibling operator).
- `PayloadPattern` <- `CBH/security-arsenal/SKILL.md`: the quote-insertion keyword-splitting family (`c'a't`, `c"a"t`, `$(printf '\x63\x61\x74')`).
- `AttackTechnique` <- `HS/web/client-side/cspt/SKILL.md`: the "pad with dummy segments so the matcher's depth stays non-negative while the app depth goes negative" procedure.
- `AttackTechnique` <- `ACS/W9/performing-web-application-firewall-bypass/SKILL.md`: an alternative event-handler and tag-name enumeration over a DOM grammar. LOW confidence, borders on the `xss` class detail.
- `ObservableSignal` <- `CBH/security-arsenal/SKILL.md`: a rule that grows between attempts as the signal that the rule set is being extended.

`defence-bypass-encoding-differential`
- `AttackTechnique` <- `CBH/security-arsenal/SKILL.md`: an address-notation folding family (decimal, octal, hex, IPv4-mapped IPv6, short form, trailing dot).
- `AttackTechnique` <- `HS/web/client-side/cspt/SKILL.md`: depth-relative encoding selection (equal-level, over-encode, pad-to-depth).
- `PayloadPattern` <- `ACS/W9/performing-web-application-firewall-bypass/SKILL.md`: the declared-charset differential (`charset=ibm037`). LOW confidence, borderline carrier substitution.
- `ObservableSignal` <- `ACS/W9/performing-web-application-firewall-bypass/SKILL.md`: the control's own normalisation-before-rule-evaluation behaviour.

`defence-bypass-parser-confusion`
- `AttackTechnique` <- `HS/web/injection/http-request-smuggling/SKILL.md` and `CBH/hunt-http-smuggling/SKILL.md`: a framing-header obfuscation family (space before colon, tab, line folding, mixed case, duplicate framing headers).
- `AttackTechnique` <- `ACS/W9/performing-http-parameter-pollution-attack/SKILL.md`: a per-reader precedence matrix (first-wins, last-wins, array, concatenation).
- `AttackTechnique` <- `CBH/hunt-api-misconfig/SKILL.md` and `ACS/W2/bypassing-authentication-with-forced-browsing/SKILL.md`: the override-member family (`X-HTTP-Method-Override`, `X-Original-Method`, `X-Rewrite-URL`, `_method`).
- `ObservableSignal` <- `CBH/hunt-cache-poison/SKILL.md`: a response stored under a different method's key (a HEAD body under a GET key).
- `AttackTechnique` <- `CBH/hunt-http-smuggling/SKILL.md`: the front-end fingerprint matrix as the reader-inventory procedure.

`defence-bypass-allowance-gap`
- `AttackTechnique` <- `ACS/W4/performing-content-security-policy-bypass/SKILL.md`: allowed-script-gadget and allowlisted-JSONP-callback enumeration.
- `AttackTechnique` <- `ACS/W4/performing-content-security-policy-bypass/SKILL.md`: nonce/hash leak and reuse (CSS attribute-selector leak, cross-page nonce reuse, DOM clobbering of the nonce).
- `AttackTechnique` <- `CBH/hunt-cors/SKILL.md`: the allowlist regex-class bypass procedure (missing dot separator, missing end anchor, unescaped dot, prefix-only).
- `AttackTechnique` <- `ACS/W2/bypassing-authentication-with-forced-browsing/SKILL.md`: path-normalisation bypass of a path-based permit.
- `DefensiveControl` <- `AWS/bug-hunting/web-vulnerabilities/csrf-token-bypass-techniques/SKILL.md`: a presence-gated check and a referer/origin prefix-match allowlist.
- `PreconditionEnvironment` <- `ACS/W4/performing-content-security-policy-bypass/SKILL.md`: the capability is a browser-confined effect gated by a declarative permit.

`defence-bypass-edge-origin-differential`
- `AttackTechnique` <- `CBH/hunt-api-misconfig/SKILL.md` and `AWS/bug-hunting/api-security/api-rate-limit-bypass-techniques/SKILL.md`: a shadow/deprecated-route enumeration family (version downgrade, mobile subdomain, legacy path).
- `AttackTechnique` <- `ACS/W2/bypassing-authentication-with-forced-browsing/SKILL.md`: method-scope divergence.
- `ObservableSignal` <- `CBH/hunt-cache-poison/SKILL.md`: a stored verdict reused across a changed method.
- `DefensiveControl` <- `ACS/W2/bypassing-authentication-with-forced-browsing/SKILL.md`: the unauthenticated-versus-authenticated response comparison.

`defence-bypass-throttle-evasion`
- `ObservableSignal` <- `CBH/hunt-brute-force/SKILL.md`: the silent shadow-throttle (status unchanged while latency rises or the body changes). The single highest-value enrichment for correctness.
- `DefensiveControl` <- `CBH/hunt-brute-force/SKILL.md`: the four-state limit classification (hard lockout, soft IP throttle, CAPTCHA injection, silent shadow-throttle).
- `AttackTechnique` <- `CBH/hunt-captcha-bypass/SKILL.md`: sliding-window concurrency.
- `AttackTechnique` <- `AWS/bug-hunting/api-security/api-rate-limit-bypass-techniques/SKILL.md`: identifier-key canonicalisation gaps (case, whitespace, null byte, `+tag`).
- `AttackTechnique` <- `CBH/hunt-api-misconfig/SKILL.md`: `multipart/mixed` batching as a carrier the per-request limiter does not count.
- `PreconditionEnvironment` <- `CBH/hunt-brute-force/SKILL.md`: the endpoint's own required-field validation must be satisfied before a concurrent payload reaches the counting middleware.

### Group `proxy-techniques`

`proxy-techniques` (parent)
- `AttackTechnique` <- `CBH/hunt-cache-poison/SKILL.md`: cache-buster isolation (probe under a throwaway key, never store under the live key).
- `ObservableSignal` <- `CBH/hunt-host-header/SKILL.md`: the reflected-is-not-trusted and cached-for-you-is-not-cached-for-others attribution rules.
- `Artifact` <- `CBH/hunt-cache-poison/SKILL.md`: the cache-status header set (`X-Cache`, `CF-Cache-Status`, `Age`, `Via`).

`proxy-techniques-dns-rebinding`
- `PayloadPattern` <- `CBH/security-arsenal/SKILL.md`: the rebinding payload shape. Consolidation, LOW value.
- `AttackTechnique` <- `CBH/security-arsenal/SKILL.md`: the redirect-chain rebinding combination.

`proxy-techniques-redirect-chain`
- `AttackTechnique` <- `HS/web/client-side/cspt/SKILL.md`: the client-side `fetch()` auto-follow as a follower the caller does not control, and the traversal-to-gadget chain.
- `AttackTechnique` <- `CBH/hunt-open-redirect/SKILL.md`: the DOM-based redirect as a follower that emits no server-side `Location` header.
- `PayloadPattern` <- `ACS/W6/testing-for-open-redirect-vulnerabilities/SKILL.md`: the redirect-validation bypass table (`@`, protocol-relative, backslash, double-encode, null, fragment, subdomain).
- `AttackTechnique` <- `ACS/W6/testing-for-open-redirect-vulnerabilities/SKILL.md`: the continuation-value rule divergence. Consolidation.

`proxy-techniques-url-parser-differential`
- `AttackTechnique` <- `CBH/hunt-api-misconfig/SKILL.md`: the server-side URL builder as a second reader (the server interpolates the caller's value into a backend URL, `#`/`%23` terminates the original backend path, traversal moves within it). The strongest single enrichment in slice-6.
- `ObservableSignal` <- `CBH/hunt-api-misconfig/SKILL.md`: an API-definition or `Invalid route` error as the observable that the value reached a server-side URL router.
- `AttackTechnique` <- `CBH/hunt-cache-poison/SKILL.md`: cache-versus-origin path-normalisation disagreement as a two-reader parse gap.
- `AttackTechnique` <- `ACS/W6/testing-for-open-redirect-vulnerabilities/SKILL.md`: the userinfo, backslash, mixed-slash, trailing-dot, and fragment notation family. Consolidation.

`proxy-techniques-channel-wrapping`
- `AttackTechnique` <- `ACS/W9/performing-web-application-firewall-bypass/SKILL.md`: the protocol-version carrier (HTTP/0.9 with no headers, HTTP/2 versus HTTP/1.1, chunked framing).
- `AttackTechnique` <- `CBH/hunt-api-misconfig/SKILL.md`: the `multipart/mixed` sub-request carrier.
- `AttackTechnique` <- `ACS/W9/performing-web-application-firewall-bypass/SKILL.md`: the unusual-location carrier (a value carried in a header the guard does not inspect).
- `AttackTechnique` <- `AWS/bug-hunting/web-vulnerabilities/csrf-token-bypass-techniques/SKILL.md`: a multipart carrier that skips a token check bound to one content type.
- `ObservableSignal` <- `CBH/hunt-http-smuggling/SKILL.md`: a front-end that accepts HTTP/2 but downgrades to HTTP/1.1 for the origin.

`proxy-techniques-cache-deception`
- `AttackTechnique` <- `CBH/hunt-cache-poison/SKILL.md`: error-response caching (a 4xx/5xx produced from attacker input is stored and served to later callers).
- `AttackTechnique` <- `CBH/hunt-cache-poison/SKILL.md`: Origin-to-ACAO cache poisoning.
- `AttackTechnique` <- `CBH/hunt-cache-poison/SKILL.md`: extension-allowlist bypass (the Cloudflare Cache-Deception-Armor `.avif` case) and the WCD path-extension list.
- `AttackTechnique` <- `AWS/bug-hunting/deep-dive-labs/cache-deception/SKILL.md`: the exact-match-rule plus forced-miss trick (add a header such as `X-Custom: 1` to force a miss).
- `AttackTechnique` <- `ACS/W6/performing-web-cache-deception-attack/SKILL.md`: the delimiter-discrepancy family (`;`, `?`, `#`, `%2F`, `%3B`, null byte, dot-segment).
- `ObservableSignal` <- `CBH/hunt-cache-poison/SKILL.md`: the cache-status header set.
- `DefensiveControl` <- `CBH/hunt-cache-poison/SKILL.md`: `Vary`-header completeness as the control to defeat.

`proxy-techniques-relay-forwarding`
- `AttackTechnique` <- `CBH/hunt-host-header/SKILL.md`: the explicit two-layer disambiguation of routing SSRF from path override.
- `AttackTechnique` <- `CBH/hunt-host-header/SKILL.md`: OAuth/OIDC issuer and discovery poisoning.
- `AttackTechnique` <- `CBH/hunt-host-header/SKILL.md`: dual-Host and second-Host precedence, with a cross-link to `defence-bypass-parser-confusion`.
- `ObservableSignal` <- `CBH/hunt-host-header/SKILL.md`: the reflected-is-not-trusted guard.
- `DefensiveControl` <- `AWS/bug-hunting/api-security/api-rate-limit-bypass-techniques/SKILL.md`: the rate limiter trusting a client-supplied source header.

---

## 4. Section C - References/scripts candidates

Executable after the assessment. Deduplicated. Slice-1 carries none: the corpus supplies concrete lab solutions and provider fingerprints (abstractness violation) or template boilerplate.

### Slice-2 imports

- `scripts/bfla-role-matrix` <- `ACS/W2/exploiting-broken-function-level-authorization/SKILL.md`: generalised role-ladder by action by transport replay harness with an expected-role cell per action.
- `references/idor-two-account-matrix` <- `ACS/W2/testing-api-for-broken-object-level-authorization/SKILL.md` and `ACS/W2/exploiting-idor-vulnerabilities/SKILL.md`: owner-versus-non-owner swap harness with a per-endpoint verdict and a masked-response differential.
- `scripts/idor-id-enumeration` <- `CBH/hunt-idor/SKILL.md` and `AWS/bug-hunting/web-vulnerabilities/idor-vulnerability-hunting/SKILL.md`: sequential-ID wordlist generation and fuzzing against a parameterised base URL.
- `scripts/idor-graphql-node-swap` <- `AWS/bug-hunting/apis/graphql-idor/SKILL.md`: relay node-id decode, modify, re-encode, replay.
- `scripts/artifact-sweep` <- `CBH/hunt-source-leak/SKILL.md` and `ACS/W5/testing-for-sensitive-data-exposure/SKILL.md`: parameterised artifact-path list with status, size, and content-type triage.
- `references/source-map-reconstruction` <- `CBH/hunt-source-leak/SKILL.md`: source-map download, `sourcesContent` extraction, and secret grep.
- `scripts/schema-reconstruction` <- `ACS/W5/performing-graphql-introspection-attack/SKILL.md`: field-suggestion brute-force that harvests a schema from error messages when introspection is disabled.
- `scripts/mass-assignment-field-sweep` <- `ACS/W5/testing-api-for-mass-assignment-vulnerability/SKILL.md`: candidate-field dictionary with a per-field persisted-or-rejected verdict and a re-fetch verification.
- `references/mass-assignment-field-dictionary` <- `HS/web/authz/mass-assignment/SKILL.md` and `ACS/W5/exploiting-mass-assignment-in-rest-apis/SKILL.md`: sensitive-field families (role, ownership, limits, flags, billing, temporal).
- `references/business-logic-value-probes` <- `CBH/hunt-business-logic/SKILL.md` and `ACS/W6/testing-for-business-logic-vulnerabilities/SKILL.md`: the negative, zero, float, overflow, and currency value probe set.
- `scripts/business-logic-race-harness` <- `ACS/W6/testing-for-business-logic-vulnerabilities/SKILL.md` and `AWS/bug-hunting/logic-flaws/business-logic-bypass/SKILL.md`: concurrent-request harness for one-time operations, naming `race-conditions` for the timing primitive.
- `scripts/two-principal-swap-harness` <- `ACS/W2/testing-api-for-broken-object-level-authorization/SKILL.md` and `CBH/hunt-idor/SKILL.md`: owner-versus-non-owner replay with a per-operation verdict and masked-response differentials.

### Slice-3 imports

- `references/deserialization-signatures.md` <- `CBH/hunt-deserialization/SKILL.md` and `ACS/W3/exploiting-insecure-deserialization/SKILL.md`: generalised format-signature table (binary and base64 prefixes per runtime family, content types, cookie markers).
- `references/deserialization-oracle.md` <- `CBH/hunt-deserialization/SKILL.md`: the callback or delay safe-oracle workflow with bounded-effect proof discipline.
- `references/upload-bypass-matrix.md` <- `CBH/hunt-file-upload/SKILL.md`, `HS/web/logic/insecure-file-upload/SKILL.md`, and `CBH/security-arsenal/SKILL.md`: generalised extension, MIME, magic-byte, and filename-injection bypass matrix plus the magic-byte table.
- `references/traversal-encoding-matrix.md` <- `CBH/hunt-lfi/SKILL.md`, `CBH/security-arsenal/SKILL.md`, and `HS/web/authz/path-traversal/SKILL.md`: generalised encoding and bypass table plus the high-value file list.
- `references/php-filter-chain.md` <- `CBH/hunt-lfi/SKILL.md`: the filter-chain generation workflow, prerequisites, length caveats, and blind-target variant. Belongs with `lfi-include-execution` or the A6 variant.
- `references/graphql-payloads.md` <- `CBH/hunt-graphql/SKILL.md` and `CBH/security-arsenal/SKILL.md`: generalised introspection query, field-suggestion probe, alias-batch template, depth-bomb template, and batch-array template.
- `scripts/ascii-smuggle.py` (or `references/ascii-smuggling.md`) <- `CBH/hunt-llm-ai/SKILL.md`: the Tags-block encoder and decoder.
- `references/llm-injection-payloads.md` <- `CBH/hunt-llm-ai/SKILL.md` and `AWS/ai-red-teaming/llm-attacks/llm-direct-prompt-injection/SKILL.md`: generalised extraction and override phrases, delimiter-breakout shapes, and exfil templates.
- `references/rag-vector-probes.md` <- `CBH/hunt-rag-vector/SKILL.md`: vector-DB reachability probes and namespace or document-ID IDOR templates. Good candidate if A9 is created.

### Slice-4 imports

Firm:
- `references/secret-pattern-catalog.md` <- `CBH/offensive-osint/references/secret-patterns.md`: a generalised, ordered, typed credential-shape catalogue with severity and false-positive notes.
- `references/secret-validators.md` <- `CBH/offensive-osint/references/secret-validators.md`: generalised read-only liveness and scope validators.
- `scripts/secret-scan.py` <- `CBH/offensive-osint/scripts/secret_scan.py`: a generalised, dependency-free scanner that mirrors the catalogue and emits one JSON record per match.
- `references/local-dtd-repurposing.md` <- `CBH/hunt-xxe/SKILL.md`: the generalised recipe for zero-egress error-based exfiltration through a pre-existing on-disk DTD. Belongs with the A10 variant.

Flagged low confidence:
- `references/parser-capability-matrix.md` <- `CBH/hunt-xxe/SKILL.md`: the parser-versus-ecosystem hardening matrix is `TechnologyStack`, which the ontology marks NEVER in a body. Admissible only as a runtime knowledge-base example.
- `references/build-artifact-paths.md` <- `CBH/hunt-source-leak/SKILL.md`: generalised artifact-path families plus the reconstruction recipe. Partially overlaps the weak-credential enrichment.

### Slice-5 imports

- Flagged, not proposed: `references/race-single-packet.md` <- `CBH/hunt-race-condition/SKILL.md`. Borderline. The gate-sync template and window-estimation procedure are generalised in structure, but they name one tool. The base analysis records `scripted tests` as absent for `race-conditions`, and the import would need the tool name abstracted out first.

### Slice-6 imports

- `references/control-bypass-evaluation-order.md` <- `CBH/security-arsenal/SKILL.md` and `ACS/W9/performing-web-application-firewall-bypass/SKILL.md`: the generalised bypass-ordering heuristic and vendor-control families.
- `references/matcher-axis-matrix.md` <- `ACS/W9/performing-web-application-firewall-bypass/SKILL.md`, `HS/web/client-side/cspt/SKILL.md`, and `CBH/security-arsenal/SKILL.md`: the axis list (casing, separators, whitespace, comments, token boundaries, operators, encoding layers).
- `scripts/axis-probe.sh` <- `ACS/W9/performing-web-application-firewall-bypass/SKILL.md`: the one-axis-per-attempt probe loop.
- `references/encoding-layer-matrix.md` <- `HS/web/client-side/cspt/SKILL.md`, `ACS/W9/performing-web-application-firewall-bypass/SKILL.md`, and `CBH/security-arsenal/SKILL.md`: the encode-depth and notation-equivalence tables.
- `scripts/decode-count-probe.sh` <- `HS/web/client-side/cspt/SKILL.md`: the layer-one-step-at-a-time probe with a depth guard.
- `references/framing-obfuscation-table.md` <- `HS/web/injection/http-request-smuggling/SKILL.md`, `CBH/security-arsenal/SKILL.md`, and `ACS/W6/exploiting-http-request-smuggling/SKILL.md`: the TE.TE obfuscation variants and the CL/TE payload bank.
- `references/parameter-precedence-matrix.md` <- `ACS/W9/performing-http-parameter-pollution-attack/SKILL.md`: the per-stack duplicate-precedence table.
- `references/permit-enumeration-matrix.md` <- `ACS/W4/performing-content-security-policy-bypass/SKILL.md`, `CBH/hunt-cors/SKILL.md`, and `ACS/W2/bypassing-authentication-with-forced-browsing/SKILL.md`: the route-inventory matrix (directives, sources, elements, origins, paths, methods, tokens).
- `references/csp-permit-gaps.md` <- `ACS/W4/performing-content-security-policy-bypass/SKILL.md`: the directive-level gap list.
- `references/tier-route-inventory.md` <- `CBH/hunt-api-misconfig/SKILL.md` and `ACS/W2/bypassing-authentication-with-forced-browsing/SKILL.md`: the sibling-route and shadow-version inventory.
- `references/rate-limit-state-classifier.md` <- `CBH/hunt-brute-force/SKILL.md`: the four-state table and the shadow-throttle seed detector.
- `references/batching-carriers.md` <- `AWS/bug-hunting/api-security/graphql-batching-attacks/SKILL.md`, `CBH/hunt-api-misconfig/SKILL.md`, and `AWS/bug-hunting/api-security/api-rate-limit-bypass-techniques/SKILL.md`: the array, alias, multipart, and fat-request carriers. Reusable catalogue for the A18 leaf.
- `references/intermediary-role-map.md` <- `CBH/hunt-cache-poison/SKILL.md` and `ACS/W6/exploiting-http-request-smuggling/SKILL.md`: the intermediary role map (resolver, forwarder, relay, cache, carrier) with each role's caller-influenced inputs.
- `references/dns-rebinding-setup.md` <- `CBH/security-arsenal/SKILL.md`: the rebinding-plus-notation-bypass block. Flagged low value; the leaf already owns the procedure.
- `references/redirect-bypass-table.md` <- `HS/web/client-side/open-redirect/SKILL.md` and `CBH/hunt-open-redirect/SKILL.md`: the destination-validation bypass table.
- `references/cspt-gadget-chain.md` <- `HS/web/client-side/cspt/SKILL.md`: the fetch-traversal-to-gadget procedure. Reusable worked chain for the A14 home.
- `references/url-parse-differential-matrix.md` <- `ACS/W6/testing-for-open-redirect-vulnerabilities/SKILL.md`, `CBH/hunt-api-misconfig/SKILL.md`, and `CBH/hunt-cache-poison/SKILL.md`: the notation family across readers.
- `references/carrier-substitution-matrix.md` <- `ACS/W9/performing-web-application-firewall-bypass/SKILL.md`, `CBH/hunt-http-smuggling/SKILL.md`, and `AWS/bug-hunting/web-vulnerabilities/csrf-token-bypass-techniques/SKILL.md`: the carrier family table.
- `references/cache-key-shaping-matrix.md` <- `ACS/W6/performing-web-cache-deception-attack/SKILL.md`, `CBH/hunt-cache-poison/SKILL.md`, and `AWS/bug-hunting/deep-dive-labs/cache-deception/SKILL.md`: the key-shaping matrix.
- `references/forwarded-field-families.md` <- `CBH/hunt-host-header/SKILL.md`, `ACS/W6/testing-for-host-header-injection/SKILL.md`, and `CBH/security-arsenal/SKILL.md`: the forwarded-field family list and the layer disambiguation.

---

## 5. Section D - Decisions of note

### Deliberate non-matches and over-split guards

The operator's second-order examples are respected explicitly:

- Second-order IDOR. `HS/web/authz/bola-idor/SKILL.md` advertises second-order and blind IDOR. The suite already carries both (the second-order case as `idor-deferred-artifact-redemption`, the blind case as a confirmation aspect). NOT proposed. (slice-2)
- Second-order SQL injection. `ACS/W3/performing-second-order-sql-injection/SKILL.md` is a delivery-timing difference orthogonal to the channel axis. The parent already carries it as an Advanced Technique. NOT a variant. The same shape as the second-order-IDOR example. (slice-4, corroborated slice-6)
- Baseline-absent rule. `subdomain-takeover` broken-link hijacking (external-dependency inventory and SRI baseline absent), `csrf` WebSocket message-layer authorization (per-message authorization baseline absent), `authentication-jwt` SAML and legacy-protocol auth bypass (assertion-semantics and per-platform endpoint baselines absent), `weak-credential-discovery` breach-corpus lookup and credential stuffing (OSINT baseline absent), `session-management` (slice-3 caveat: a new class, not a variant, and the base suite lacks the baseline it extends). Each is a NON-MATCH, not a proposal.

Other deliberate non-matches and over-split guards:

- `authentication-jwt`: PHP type juggling (language-level comparison, not token validation). `oauth`: the `web-message`/response-mode variant rejected (bends no step beyond the redirect variant's destination-delivery clause). `http-method-tampering`: WAF method evasion (already named, mechanics delegated to `defence-bypass`). `open-redirect`: CRLF-to-header (owned by `header-injection`), mobile deep-link (owned by the mobile surface). `subdomain-takeover`: network-layer DNS takeover and BGP hijacking.
- `bfla-deferred-execution`, `mass-assignment-bulk-collection-injection`, `mass-assignment-bulk-nested-relation-write`, `quota-window-slicing`: clean no-match (the corpus is silent on the exact bent step).
- `crypto-timing-oracle`: clean no-match (no source runs a baseline-calibrated prefix-extraction procedure). `mobile-weak-crypto` and `hunt-tls-network`: non-matches for `crypto-weakness` on reconnaissance and trust-assumption grounds, and outside the fixed web-testing scope.
- `ssti`: client-side template injection correctly excluded (markup injection, browser-side). `xxe`: no second-order escalation. `sql-injection`: cleanest no-change verdict.
- `header-injection`: routing-based SSRF resolves cleanly to `ssrf` as a carrier, not a new header variant. `http-request-smuggling`: cleartext-upgrade smuggling and CONNECT tunneling are non-proposals (the base analysis already folded WebSocket handshake hijacking in as a secondary). `ssrf`: the headless-browser JavaScript-execution sink stays an aspect on current evidence.
- `defence-bypass`: second-order SQL injection, SSL stripping, IPv6 DNS takeover, AWS IMDSv2 SSRF bypass, and DNS enumeration are clean non-matches. `cache-poisoning` is noted but not proposed (class-group question; impact alone is not a discriminator).

### Flagged low-confidence items (carry the flag)

- slice-1: oauth `prompt=none` signal (LOW); JWT `jku` chain and claim swap (LOW); csrf raw-client Origin check (LOW); csrf CRLF double-submit (LOW); open-redirect session fixation (LOW-MEDIUM); broken-link recon (LOW-MEDIUM); wildcard OAuth allowlist claim (LOW).
- slice-2: NTLM info disclosure (low confidence, likely a concrete aspect); OData `$expand` (distinct protocol); GraphQL resolver mechanics owned by `graphql`; web cache deception owned by `proxy-techniques`; `2fa-bypass` as an authentication boundary case.
- slice-3: `crypto-oracle-decryption` (LOW); JNDI escalation to a fourth variant (flagged); AI code-completion sabotage (LOW, thin evidence, may be its own class); XXE parser-capability matrix (`TechnologyStack`, NEVER in a body).
- slice-4: NoSQL string-context breakout (may already be covered by the grammar clause); SSTI deferred-sink sharpening (likely covered); SQL authenticated-only surface (pro-tip-shaped); weak-credential client-side lockout bypass (may belong to `defence-bypass`); XXE parser-capability matrix.
- slice-5: `client-side-path-traversal` (MEDIUM, home undecided); `css-injection-exfiltration` (MEDIUM, home undecided); `rce-config-delegate-execution` (MEDIUM); `http-request-smuggling-cross-protocol-desync` (LOW-MEDIUM); race single-packet reference (borderline).
- slice-6: `cors-misconfiguration` (MEDIUM, out of family scope); dns-rebinding reference (low value); `cache-poisoning` (noted not proposed).

### Out-of-slice triage list (needs a routing ruling)

1. `session-management` (slice-3 proposal, slice-5 out-of-slice). Competing with the slice-5 `header-response-value-confusion` leaf and the slice-3 `crypto-weakness` non-match. Largest missing baseline.
2. `rate-limit-bypass` (slice-5, OWASP API4). The concurrent-counter part is already an aspect of `race-conditions`; the identifier-rotation taxonomy is new. Overlaps `header-injection` (forwarded-address spoofing) and `weak-credential-discovery` (brute force). Also the target of slice-6's `defence-bypass-throttle-evasion` and the A18 leaf.
3. `http-parameter-pollution` (slice-5). The duplicate-header-pollution part is already a `header-injection` bypass aspect; the parameter-precedence taxonomy is new. Also the source of slice-6's `defence-bypass-parser-confusion` precedence matrix.
4. LDAP filter injection (slice-4). A distinct `VulnerabilityClass`, not a `nosql-injection` variant.
5. XPath injection (slice-4). A distinct `VulnerabilityClass`, not an `xxe` variant.
6. `cache-poisoning` (slice-6). Class-group question; the `proxy-techniques-cache-deception` leaf already states both cache clauses.
7. `cors-misconfiguration` (slice-6, A19). Route to the class-slice owner; the CSP class is also absent and lives in `defence-bypass-allowance-gap` enrichments.

### Additional cross-slice coordination notes

- `rate-limit bypass` (slice-5 out-of-slice) versus the `throttle-evasion` enrichment (slice-6). Slice-5 records `rate-limit-bypass` as a possible class and resolves the base `race-conditions` open question (identity-partitioned quota bursts) to "aspect, not variant". Slice-6 enriches `defence-bypass-throttle-evasion` with the same source's identifier-rotation taxonomy and the counter-window burst rule, and raises the A18 leaf for the batch-collapse mechanism. Reconciliation: the identifier-rotation taxonomy stays an enrichment of `defence-bypass-throttle-evasion`; the concurrent-counter part stays an aspect of `race-conditions`; the batch-collapse mechanism is A18. A standalone `rate-limit-bypass` class is not recommended on current evidence (LOW).
- JWT header injection. Slice-3 routes the `kid`/`jku`/`jwk` key-source injection to `crypto-signing-key-forgery` and flags that `authentication-jwt` is the natural JWT-specific owner. Author the JWT-specific header injection in `authentication-jwt`, and keep only the abstract "key basis resolved from attacker-influenced input" clause in `crypto-weakness`.
- `hunt-session` rotation-reuse signal. Slice-3 routes it to `oauth` or `authentication-jwt`. If `session-management` (A4) is created, it belongs there.
- Vector-store direct read. Slice-3 records that the unauthenticated corpus read and cross-tenant vector IDOR may belong to `idor` or `information-disclosure`. Slice-2's A2 (`excessive-data-exposure`) is the adjacent new sibling of `information-disclosure`. Route once.
- Batching carriers. Slice-5 `race-conditions/single-request-fanout` and slice-6 `defence-bypass-attempt-batching` (A18) share `AWS/bug-hunting/api-security/graphql-batching-attacks/SKILL.md`. Author the payload envelopes once; reference them from both.
- Shadow/deprecated API versions. Slice-2 A3 (`api-version-consistency`) and slice-6 `defence-bypass-edge-origin-differential` both cover the version surface. If A3 is rejected, the slice-6 enrichment is the remaining home.
- AI-agent scope. Slice-3 flags that `mcp-tool-server-abuse` (A8), `rag-vector-store-abuse` (A9), and the AI surfaces must be confirmed inside the operator's web-testing scope before authoring.

### Decision surface

Section A plus the flagged out-of-slice triage list are what needs operator rulings. Section B and Section C are executable after the assessment. No suite edits were made. No git command was run.
