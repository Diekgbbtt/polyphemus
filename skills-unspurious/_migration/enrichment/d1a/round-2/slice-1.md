# D1a enrichment, round 2, slice 1 (auth / session / redirect / takeover / method)

## Slice header

- Base suite: `skills-unspurious/` in worktree `feat-w7-enrichment` (read-only here).
- Groups in this slice: `authentication-jwt`, `oauth`, `csrf`, `http-method-tampering`, `open-redirect`, `subdomain-takeover`.
- Base skills read in full: 6 group parents plus 24 variant leaves (30 skills).
- Parents: `authentication-jwt` (4 variants), `oauth` (5), `csrf` (5), `http-method-tampering` (4), `open-redirect` (3), `subdomain-takeover` (3).
- Sources indexed and searched: `/Users/diekgbbtt/hacking-skills/skills` (43), `/Users/diekgbbtt/claude-bug-hunter/skills` (105), `/Users/diekgbbtt/anthropic-cybersecurity-skills` (82 accepted skills plus an 818-entry catalog), `/Users/diekgbbtt/awsome-offensive-security-skill/skills` (138).
- Normative docs read: `docs/design/skills-variant-boundary.md`, `docs/design/skills-ontology.md`, `skills-unspurious/INVENTORY.md`, `skills-unspurious/DECOMPOSITION-REPORT.md` (grep only).
- No suite file was modified. No git command was run. Reports only.

### Cross-cutting observations on the sources

- The three "hunt"-style repos (`hacking-skills`, `claude-bug-hunter`, `awsome-offensive-security-skill`) sit at a lower abstraction level than the base suite.
- They carry concrete products, CVE identifiers, hostnames, and payload literals that the base suite's abstractness rule (`skills-ontology.md` section 7) forbids in a skill body.
- Every technique taken from them must be reframed as its abstract condition before it can enter a base skill.
- The `anthropic-cybersecurity-skills` accepted set is Python-tooling-heavy and mostly duplicates the class-level procedures already in the base.
- Source `references/` and `scripts/` assets are concrete automation (hardcoded endpoints, payload lists, the `requests` library), not generalised scripted tests; see the per-group notes and the "References and scripts" summary.
- The ontology matrix (`skills-ontology.md` section 6) marks `scripted tests` genuinely absent for all six groups in this slice; that matrix is treated as authoritative.

---

## authentication-jwt

### authentication-jwt (parent)

**Sources matched**

- `/Users/diekgbbtt/hacking-skills/skills/web/auth/jwt-misconfig/SKILL.md`
- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-jwt-crypto/SKILL.md`
- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W1/exploiting-jwt-algorithm-confusion-attack/SKILL.md`
- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W1/performing-jwt-none-algorithm-attack/SKILL.md`
- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W1/testing-for-json-web-token-vulnerabilities/SKILL.md`
- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W1/testing-jwt-token-security/SKILL.md`
- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/apis/jwt-null-signature/SKILL.md`
- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/apis/jwt-algorithm-confusion/SKILL.md`
- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/api-security/jwt-forgery-algorithm-confusion/SKILL.md`
- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/deep-dive-labs/jwt-labs/SKILL.md`

**Similarity**

- High. The sources cover the same four clauses the parent already decomposes into.
- `alg:none` and unsigned acceptance map to `jwt-signature-forgery`.
- RS256-to-HS256 confusion and weak-secret recovery map to `jwt-signature-forgery`.
- `kid`/`jku`/`x5u`/inline-`jwk` key control maps to `jwt-key-resolution`.
- Issuer/audience/privilege/lifetime/kind confusion maps to `jwt-claims-confusion`.
- Mix-up, downgrade, device, refresh-reuse, revocation, and fixation map to `jwt-flow-lifecycle`.
- No source adds a fifth clause that the parent cannot cover.

**Boundary**

- No boundary attribute diverges.
- The sources vary `TechnologyStack` (JWT library, algorithm family) and `PayloadPattern` (case-variant algorithm strings), both of which the boundary doc classifies as non-discriminators or aspects.
- The trust-assumption difference is already the class definition, and each source breaks exactly one of the four existing clauses.

**New-skill proposals**

- None.

**Enrichment candidates**

- `AttackTechnique` <- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/deep-dive-labs/jwt-labs/SKILL.md` (Lab 8): recover the asymmetric public key from two captured tokens when no key endpoint is exposed, then run the confusion forgery.
  - This is a distinct acquisition step for the algorithm-binding clause; the parent currently assumes a published key source.
- `PayloadPattern` <- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W1/performing-jwt-none-algorithm-attack/SKILL.md`: case-variant unsigned algorithm identifiers and signature-segment variants for the unsigned-acceptance sub-step.
- `AttackTechnique` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-jwt-crypto/SKILL.md` and `/Users/diekgbbtt/hacking-skills/skills/web/auth/jwt-misconfig/SKILL.md`: name the sink families a key selector can reach (record-store query, command sink, fetch sink) under the key-resolution variant.
  - The parent already abstracts this as "steer key lookup outside the intended store"; the enrichment is to name the three sink families explicitly.
- `AttackTechnique` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-jwt-crypto/SKILL.md`: cross-tenant claim injection (tenant/organisation claim edits) as a named sub-step of claims confusion.

**References/scripts candidates**

- Candidate: `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W1/exploiting-jwt-algorithm-confusion-attack/scripts/agent.py` and `references/api-reference.md`.
- Assessment: not sufficiently generalised. The script hardcodes the forgery helpers and uses `requests`; the reference hardcodes algorithm tables.
- The ontology matrix marks scripted tests genuinely absent for `authentication-jwt`.
- Decision: no `references/` addition.

### Variant leaves (jwt-signature-forgery, jwt-key-resolution, jwt-claims-confusion, jwt-flow-lifecycle)

- The leaves were read in full.
- Each source technique lands inside an existing leaf as a bypass form or an aspect; no leaf acquires a new bent step.
- The leaf-level enrichments are the four parent-level candidates above, distributed as follows:
  - `jwt-signature-forgery`: public-key recovery from two tokens; case-variant unsigned shapes.
  - `jwt-key-resolution`: named selector sink families.
  - `jwt-claims-confusion`: cross-tenant claim injection.
  - `jwt-flow-lifecycle`: no addition.

---

## oauth

### oauth (parent)

**Sources matched**

- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-oauth/SKILL.md`
- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W1/exploiting-oauth-misconfiguration/SKILL.md`
- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W1/testing-oauth2-implementation-flaws/SKILL.md`
- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/api-security/oauth-flow-exploitation/SKILL.md`
- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/logic-flaws/oauth-state-parameter-abuse/SKILL.md`
- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/deep-dive-labs/oauth/SKILL.md`
- Catalog entry `attacking-oauth-with-device-code-phishing` in `/Users/diekgbbtt/anthropic-cybersecurity-skills/catalog/catalog.json` (no full skill body).

**Similarity**

- High for destination, freshness, possession, client-binding, and approval.
- Redirect manipulation, duplicate-carrier precedence, path traversal in the destination, and logout-continuation looseness map to `oauth-redirect-uri-validation`.
- Missing/replayed `state`/`nonce` and login CSRF map to `oauth-state-nonce-csrf`.
- Challenge-less issuance, any-verifier acceptance, and method downgrade map to `oauth-pkce-enforcement`.
- Code/token swapping across clients, audience confusion, secretless redemption, and mix-up map to `oauth-code-client-binding`.
- Device-code polling and approval inducement map to `oauth-device-approval`.

**Boundary**

- One source technique group bends a step none of the five clauses covers: the browser-messaging delivery channel and the response-type swap.
- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-oauth/SKILL.md` documents `response_mode=web_message` interception through a lax `postMessage` origin check, and `response_type` swap to a fragment-borne token ("dirty dancing").
- The delivery destination can be perfectly registered and the credential still leaks through the in-browser carrier.
- This is a `communication protocol` divergence, one of the boundary attributes named in the task brief.
- The parent covers "harvest-channel arrival" and "referrer-based harvesting" as an exfil channel of the destination variant, so a competing reading places this material as an aspect of `oauth-redirect-uri-validation`.
- The call is flagged as low confidence and left to the synthesis.

**New-skill proposals**

- `source`: `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-oauth/SKILL.md` (the "dirty dancing" citations, items 19 and 20).
- `[NEW] target`: `oauth-response-type-swap` (working name).
- Rationale:
  - The bent step is "force the authorization response into a browser-readable delivery carrier (a fragment or a parent-window message) and read the credential from a lax listener".
  - No parent step covers it: the destination step validates where the credential is delivered, and the freshness/possession/client/approval steps do not read the delivery channel.
  - The divergence is stable across providers and is a protocol feature, so it passes the stability criterion.
  - Alternative reading (lower-risk): fold it into `oauth-redirect-uri-validation` as an additional exfil channel beside referrer harvesting.
  - Confidence: low to medium. If the synthesis prefers the aspect reading, the same source becomes the first enrichment candidate below.
- `source`: `/Users/diekgbbtt/anthropic-cybersecurity-skills/catalog/catalog.json` (entry `attacking-oauth-with-device-code-phishing`).
- `[NEW] target`: `oauth-consent-grant-abuse` (working name).
- Rationale:
  - The bent step is "induce the victim to grant a malicious application access", which differs from `oauth-device-approval` (induce the victim to approve a device code) and from freshness CSRF.
  - The catalog entry is a description only; no full body was available, so the proposal is weaker evidence than the other entries.
  - Confidence: low. Flagged for the synthesis; do not treat as decision-grade without a full body.

**Enrichment candidates**

- `AttackTechnique` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-oauth/SKILL.md`: add the browser-messaging (parent-window message) interception channel and the response-type swap to the destination variant's harvest step, if the aspect reading is chosen.
- `AttackTechnique` <- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/deep-dive-labs/oauth/SKILL.md` (Lab 2): server-side request forgery through dynamic client registration metadata URL fields (client logo or key-set URL) as a named sub-step of the client-authentication weakness.
- `AttackTechnique` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-oauth/SKILL.md`: silent re-authentication abuse by forcing a no-prompt authorization request (session fixation and silent-auth abuse).
- `AttackTechnique` <- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W1/testing-oauth2-implementation-flaws/SKILL.md`: confirmation that public-client exemption from the possession challenge is a named bypass of `oauth-pkce-enforcement` (the parent already abstracts it; confirm coverage rather than add).
- `ObservableSignal` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-oauth/SKILL.md`: identity-collision signal when two providers emit the same subject for different users (the parent already names subject collisions; confirm coverage).

**References/scripts candidates**

- Candidates: `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W1/exploiting-oauth-misconfiguration/scripts/agent.py` and `references/api-reference.md`; `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W1/testing-oauth2-implementation-flaws/scripts/agent.py`.
- Assessment: not sufficiently generalised. Hardcoded destinations, payload lists, and `requests` calls.
- The ontology matrix marks scripted tests genuinely absent for `oauth`.
- Decision: no `references/` addition.

### Variant leaves (oauth-redirect-uri-validation, oauth-state-nonce-csrf, oauth-pkce-enforcement, oauth-code-client-binding, oauth-device-approval)

- The leaves were read in full.
- Each is a strong match to the corresponding source section; the leaves already own their bent steps.
- `oauth-redirect-uri-validation`: the browser-messaging harvest channel and the response-type swap are the only candidate additions (aspect reading).
- `oauth-state-nonce-csrf`: no addition.
- `oauth-pkce-enforcement`: no addition beyond confirming the public-client exemption bypass.
- `oauth-code-client-binding`: no addition.
- `oauth-device-approval`: no addition; the consent-grant abuse is the separate proposal above.

---

## csrf

### csrf (parent)

**Sources matched**

- `/Users/diekgbbtt/hacking-skills/skills/web/client-side/csrf/SKILL.md`
- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-csrf/SKILL.md`
- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W4/performing-csrf-attack-simulation/SKILL.md`
- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/web-vulnerabilities/csrf-token-bypass-techniques/SKILL.md`
- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/deep-dive-labs/csrf/SKILL.md`
- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/web-vulnerabilities/websocket-hijacking-testing/SKILL.md`
- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W5/exploiting-websocket-vulnerabilities/SKILL.md`

**Similarity**

- High. The five clauses (proof-of-intent, scoping, parser, login-identity, transport) cover the sources.
- Form/multipart/plain-text delivery, storage-effect confirmation, and JSON-via-plain-text coercion map to `csrf-form-post` and `csrf-parser-differential`.
- Top-level GET navigation, confirmation chains, and staff GET tools map to `csrf-navigation-get`.
- Logout-then-plant and account-identity completion map to `csrf-login-fixation`.
- Cross-site socket handshake and over-socket actions map to `csrf-websocket-handshake`.
- Every source technique is a bypass form or an aspect, not a new bent step.

**Boundary**

- No boundary attribute diverges.
- SameSite sibling-domain abuse, Origin/Referer spoofing, and token-cookie planting are all `DefensiveControl` values that the existing variants' bypass sections can carry.
- The socket material duplicates `csrf-websocket-handshake`; the message-level injection material (SQLi/XSS/IDOR over sockets) belongs to a WebSocket class the suite lacks (see residuals).

**New-skill proposals**

- None.

**Enrichment candidates**

- `DefensiveControl` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-csrf/SKILL.md`: SameSite=Lax sibling-subdomain bypass, where an attacker-controlled sibling subdomain is same-site to the parent, so the scoping clause does not exclude the delivery.
- `DefensiveControl` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-csrf/SKILL.md`: direct Origin/Referer header spoofing that satisfies a naive string check, with no real cross-site page.
- `DefensiveControl` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-csrf/SKILL.md`: path-traversal token bypass, where the token scope is matched on the pre-normalisation path while execution uses the post-normalisation path.
- `DefensiveControl` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-csrf/SKILL.md`: static custom-header antiforgery not bound to the user, role-partition replay under one session, and the socket carve-out that excludes a hub path from the check.
- `DefensiveControl` <- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/deep-dive-labs/csrf/SKILL.md` (Labs 5, 6, 10): token-cookie pairing defeated by planting the token cookie through a response-header-injection sink, and the cookie-refresh grace window that re-admits top-level navigation.
- `PreconditionEnvironment` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-csrf/SKILL.md`: mobile-app CSRF through an exported custom-scheme deep-link handler that performs a state change with ambient session authority.

**References/scripts candidates**

- Candidate: `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W4/performing-csrf-attack-simulation/scripts/agent.py`.
- Assessment: not sufficiently generalised (hardcoded analysis routine and `requests` session).
- The ontology matrix marks scripted tests genuinely absent for `csrf`.
- Decision: no `references/` addition.

### Variant leaves (csrf-form-post, csrf-navigation-get, csrf-parser-differential, csrf-login-fixation, csrf-websocket-handshake)

- The leaves were read in full.
- All source CSRF techniques distribute into the existing bypass sections of these five leaves.
- `csrf-form-post`: SameSite sibling-domain, header spoofing, token-cookie planting.
- `csrf-navigation-get`: cookie-refresh grace window.
- `csrf-parser-differential`: path-traversal token scope and duplicate-key precedence.
- `csrf-login-fixation`: no addition.
- `csrf-websocket-handshake`: no addition; socket message injection has no home in this class.

---

## http-method-tampering

### http-method-tampering (parent)

**Sources matched**

- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-api-misconfig/SKILL.md`
- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-host-header/SKILL.md`
- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-cache-poison/SKILL.md`
- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-auth-bypass/SKILL.md`
- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W2/bypassing-authentication-with-forced-browsing/SKILL.md`
- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W2/exploiting-broken-function-level-authorization/SKILL.md`
- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/deep-dive-labs/access-control/SKILL.md`
- `/Users/diekgbbtt/hacking-skills/skills/web/authz/authz-bypass/SKILL.md`
- `/Users/diekgbbtt/hacking-skills/skills/web/auth/auth-bypass/SKILL.md`

**Similarity**

- High for verb switching and override smuggling.
- Sibling-verb dispatch gaps, write-via-read-verb, and read-via-write-verb map to `http-method-tampering-verb-switch`.
- Override headers and body/query markers, and gate-versus-executor method divergence, map to `http-method-tampering-override-smuggling`.
- Allowed-method disclosure, header-only responses, and echo material map to `http-method-tampering-informational-verb`.
- Preflight-versus-simple shape divergence maps to `http-method-tampering-preflight-coercion`.

**Boundary**

- No boundary attribute diverges for the method-identity clauses.
- The parent already names rewrite carriers (`X-Original-URL`, `X-Rewrite-URL`) in "Layer Divergence Chains", so path-override is covered.
- The parent already names duplicate verb-carrying inputs, so the duplicate-parameter precedence case is covered.
- One source technique is boundary-adjacent: authorization keyed on the `Referer` header (deep-dive-labs Lab 13).
  - This is a different gate input from the method, so it sits closer to the authorization classes than to the method-identity class.
  - Reported as a low-confidence enrichment and echoed in the residuals.

**New-skill proposals**

- None.

**Enrichment candidates**

- `AttackTechnique` <- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/deep-dive-labs/access-control/SKILL.md` (Labs 10, 11): make the rewrite-carrier probe explicit (send the request to an unguarded path with the guarded path carried in a rewrite header) and the method-based authorization bypass explicit (change the verb on a route whose guard is verb-bound).
- `DefensiveControl` <- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W2/bypassing-authentication-with-forced-browsing/SKILL.md`: path-normalisation shapes (case, dot-segments, encoded slash, semicolon, trailing character, null byte) that evade path-based authorization rules.
- `AttackTechnique` <- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/deep-dive-labs/access-control/SKILL.md` (Lab 13): authorization check keyed on a client-supplied `Referer` value (low confidence for this class).
- `AttackTechnique` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-api-misconfig/SKILL.md`: informational-verb enablement (`TRACE`, `OPTIONS` method list) and GET-bypass-of-CSRF (confirm coverage by the informational-verb variant).

**References/scripts candidates**

- None relevant. No source ships a method-tampering script.
- Decision: no `references/` addition.

### Variant leaves (verb-switch, override-smuggling, informational-verb, preflight-coercion)

- The leaves were read in full.
- `http-method-tampering-verb-switch`: the explicit method-based-authorization probe is the only candidate addition.
- `http-method-tampering-override-smuggling`: the explicit rewrite-carrier probe is the only candidate addition; the header mechanics themselves live in `header-injection/header-method-override`, so the base must cross-reference rather than restate.
- `http-method-tampering-informational-verb`: no addition.
- `http-method-tampering-preflight-coercion`: no addition.

---

## open-redirect

### open-redirect (parent)

**Sources matched**

- `/Users/diekgbbtt/hacking-skills/skills/web/client-side/open-redirect/SKILL.md`
- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-open-redirect/SKILL.md`
- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W6/testing-for-open-redirect-vulnerabilities/SKILL.md`
- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/web-vulnerabilities/open-redirect-chaining-attacks/SKILL.md`
- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/deep-dive-labs/oauth/SKILL.md` (Lab 5)

**Similarity**

- High. The three clauses (canonicalisation, whole-destination, per-hop, credential-relay) cover the sources.
- Parser differentials, allowlist evasion, client-side dispatch, and multi-hop chains map to `generic-redirect-parser-bypass`.
- Credential relay through a trusted redirector maps to `oauth-redirect-uri-relay`.
- Fetcher pivot to an internal target maps to `redirector-to-fetcher-pivot`.
- The bypass tables in all sources match the parent's existing bypass list.

**Boundary**

- No boundary attribute diverges.
- The sources vary `PayloadPattern` (userinfo, backslash, encoding, confusable names) and `TechnologyStack`, both of which are aspects.

**New-skill proposals**

- None.

**Enrichment candidates**

- `AttackTechnique` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-open-redirect/SKILL.md`: DOM-based open redirect through a client-side navigation sink (source-to-sink), which the parent already names under client-side dispatch; confirm the explicit probe.
- `PayloadPattern` <- `/Users/diekgbbtt/hacking-skills/skills/web/client-side/open-redirect/SKILL.md`: the `javascript:`/`data:` scheme shapes and the internationalised-name homograph shape (already in the parent bypass list; confirm).
- `AttackTechnique` <- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W6/testing-for-open-redirect-vulnerabilities/SKILL.md`: CRLF injection inside the redirect value that injects a `Location` header; note that the header mechanics belong to `header-injection/header-crlf-splitting`, so cross-reference rather than restate.

**References/scripts candidates**

- Candidate: `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W6/testing-for-open-redirect-vulnerabilities/scripts/agent.py`.
- Assessment: not sufficiently generalised (hardcoded parameter and payload lists, `requests`).
- The ontology matrix marks scripted tests genuinely absent for `open-redirect`.
- Decision: no `references/` addition.

### Variant leaves (generic-redirect-parser-bypass, oauth-redirect-uri-relay, redirector-to-fetcher-pivot)

- The leaves were read in full.
- All three are strong matches; no leaf acquires a new bent step.
- The candidate additions above distribute into the existing bypass and reconnaissance sections.

---

## subdomain-takeover

### subdomain-takeover (parent)

**Sources matched**

- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-subdomain/SKILL.md`
- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W8/performing-dns-enumeration-and-zone-transfer/SKILL.md`
- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W8/performing-subdomain-enumeration-with-subfinder/SKILL.md`
- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W6/exploiting-broken-link-hijacking/SKILL.md`
- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/osint/corporate-infrastructure/domain-and-asn-enumeration/SKILL.md`
- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/network/ipv6-dns-takeover-mitm/SKILL.md`
- Catalog entry `hunting-for-dns-based-persistence` in `/Users/diekgbbtt/anthropic-cybersecurity-skills/catalog/catalog.json`.

**Similarity**

- High for the three existing clauses (dangling-record, alternate-name, delegation).
- Provider fingerprinting, dangling canonical records, and exact-name re-claim map to `dangling-record-resource-claim`.
- Alternate-domain association on edge capacity, certificate handling, and cache-aware proof map to `cdn-alternate-domain-binding`.
- Expired-nameserver-domain registration and subzone-wide proof map to `ns-delegation-takeover`.
- The impact-chain table in `hunt-subdomain` matches the parent's "Chaining Attacks" section.

**Boundary**

- Two source technique groups bend a step no existing clause covers: the mail surface and the mail-authorisation records.
- The parent explicitly carries the mail surface "without a claim procedure of its own" and treats any receipt capability as an impact statement, not a claim step.
- `hunt-subdomain` (item 13) provides a claim procedure for a decommissioned mail/help-desk resource and a message-interception impact.
- `hunt-subdomain` (chain 5) provides a claim procedure for an email-authorisation record host (key selector, sender-policy include) and a send-authority impact.
- Both differ from the parent's trust assumption (name-to-content trust), so they are genuine bent steps rather than aspects.

**New-skill proposals**

- `source`: `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-subdomain/SKILL.md` (item 13, help-desk takeover to email interception).
- `[NEW] target`: `mail-record-takeover` (working name), variant `mail-receipt-claim`.
- Rationale:
  - The bent step is "reclaim the decommissioned mail/help-desk resource a mail record still names, then receive the messages addressed to the name".
  - The parent's mail handling stops at impact; this source supplies the missing claim procedure.
  - The impact goal (message interception, reset-link capture) is distinct from content serving, so the variant owns its own completion criterion.
  - It is stable across providers and record types.
- `source`: `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-subdomain/SKILL.md` (chain 5, email-authentication record takeover).
- `[NEW] target`: `mail-record-takeover` (working name), variant `mail-authorisation-claim`.
- Rationale:
  - The bent step is "reclaim a key-selector or sender-policy include host and publish mail-authorisation records".
  - The trust defeated is outbound-mail authentication, not name-to-content resolution.
  - The procedure and proof differ from the receipt variant, so it is a second variant of the same new class.
  - Confidence: medium. The class is new, so the synthesis must decide whether it is a sibling class or a fourth variant family of `subdomain-takeover`.

**Enrichment candidates**

- `AttackTechnique` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-subdomain/SKILL.md`: named binding-flow families under the dangling-record variant, reframed to abstract conditions: regional-pool name re-issue (deploy a resource requesting the exact released name), deleted-project name re-claim, and CDN service re-attach.
- `AttackTechnique` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-subdomain/SKILL.md`: reconnaissance for the mail surface (key-selector records, sender-policy includes, mail records) to feed the mail-record proposals.
- `ObservableSignal` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-subdomain/SKILL.md`: provider error-string fingerprint families and the certificate-subject mismatch (the parent already names both; confirm coverage).
- `PreconditionEnvironment` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-subdomain/SKILL.md`: parent-domain cookie scope as an impact precondition for the session-fixation chain (the parent already names it under chaining; confirm coverage).

**References/scripts candidates**

- Candidates: `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W8/performing-subdomain-enumeration-with-subfinder/scripts/agent.py` and `process.py`; `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W8/performing-dns-enumeration-and-zone-transfer/scripts/agent.py`.
- Assessment: not sufficiently generalised; they are tool wrappers around concrete commands.
- The ontology matrix marks scripted tests genuinely absent for `subdomain-takeover`.
- Decision: no `references/` addition.

### Variant leaves (dangling-record-resource-claim, cdn-alternate-domain-binding, ns-delegation-takeover)

- The leaves were read in full.
- `dangling-record-resource-claim`: the named binding-flow families are the candidate addition; the mail claim procedures are the separate proposals above.
- `cdn-alternate-domain-binding`: no addition.
- `ns-delegation-takeover`: no addition.

---

## Residual candidates

This section lists source material with no adequate home in the current suite.
It is global to the suite, so some entries may also be claimed by another slice; the synthesis decides.
Each entry states the source, the proposed home, and the confidence.

1. **SAML / SSO assertion forgery (new class).**
   - Source: `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-saml/SKILL.md`; corroborated by `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-auth-bypass/SKILL.md`.
   - Content: signature wrapping, comment injection in the name identifier, signature stripping, key confusion, audience-restriction gaps, and assertion replay.
   - Home: no group; the suite has `authentication-jwt` and `oauth` but no SAML assertion class.
   - Rationale: a web authentication vulnerability class with a distinct trust assumption (assertion signature scope versus assertion consumption) and its own bent steps.
   - Confidence: high. The suite's own cross-reference list names `oauth`/`authentication-jwt` at token and flow steps but no SAML owner.
   - Note: the base `xss` and `ssti` skills folded a SAML subsection; a standalone class is still missing.

2. **Broken-link / external-resource hijacking (new class).**
   - Source: `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W6/exploiting-broken-link-hijacking/SKILL.md`; corroborated by `hunt-subdomain` chains 3 and 5.
   - Content: claim an expired external domain, script host, stylesheet host, CDN package, or social handle that the target page references.
   - Home: no group; it is adjacent to `subdomain-takeover` but the trust relationship differs (the target's page trusts a third-party reference, not a record of its own name).
   - Rationale: a web supply-chain vulnerability class with its own reconnaissance (external-reference crawl) and its own claim step.
   - Confidence: high.

3. **Legacy-protocol authentication-endpoint parity (new class).**
   - Source: `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-auth-bypass/SKILL.md` (the Legacy-Protocol Matrix).
   - Content: a hardened modern login surface is bypassed by a legacy protocol endpoint that still accepts native credentials without the modern controls (multi-factor challenge, rate limit, allow-list).
   - Home: no group; `weak-credential-discovery` owns credential replay and enumeration, not surface parity.
   - Rationale: a web authentication vulnerability class; the trust assumption is that one authentication surface covers every surface that issues the same authority.
   - Confidence: high.

4. **HTTP parameter pollution (new class).**
   - Source: `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W9/performing-http-parameter-pollution-attack/SKILL.md`.
   - Content: duplicate-parameter precedence differences between the validating layer and the consuming layer; payload splitting for control bypass; security-critical value override.
   - Home: no group; `http-method-tampering` owns duplicate verb carriers only, and `oauth-redirect-uri-validation` owns duplicate destination carriers only.
   - Rationale: a general parameter-parsing class with its own precedence matrix; the two existing uses are special cases.
   - Confidence: high for the class; medium for placement, because the control-bypass and logic uses may instead fold into `defence-bypass` and `business-logic`.
   - Caution: do not let it duplicate the existing duplicate-carrier sub-steps; cross-reference them.

5. **WebSocket security (new class).**
   - Sources: `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-websocket/SKILL.md`; `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W5/exploiting-websocket-vulnerabilities/SKILL.md`; `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/web-vulnerabilities/websocket-hijacking-testing/SKILL.md`.
   - Content: handshake authentication gaps, per-message authorization gaps, message injection, namespace/room authorization bypass, handshake smuggling, and connection persistence after logout.
   - Home: `csrf-websocket-handshake` owns the cross-site handshake only; the message-layer material has no home.
   - Rationale: a distinct attack-surface part family with its own protocol.
   - Confidence: medium to high. The suite deliberately kept the socket handshake inside `csrf`; a full class would need the boundary to separate the handshake clause from the message clause.

6. **CORS misconfiguration (new class).**
   - Sources: `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-cors/SKILL.md`; `/Users/diekgbbtt/hacking-skills/skills/web/client-side/cors-misconfig/SKILL.md`; `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W4/testing-cors-misconfiguration/SKILL.md`; `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/web-vulnerabilities/cors-misconfiguration-exploitation/SKILL.md`.
   - Content: origin reflection with credentials, null-origin trust, regex/prefix bypass, preflight gating gaps, and post-message origin checks.
   - Home: no group; `csrf` and `oauth` reference CORS but do not own it.
   - Rationale: a web vulnerability class with its own trust assumption (which origins may read a credentialed response).
   - Confidence: medium to high.

7. **Clickjacking (new class).**
   - Sources: `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-clickjacking/SKILL.md`; `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W4/performing-clickjacking-attack-test/SKILL.md`; `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/web-vulnerabilities/clickjacking-ui-redressing/SKILL.md`.
   - Content: framing-policy absence, browser-verified framing, and same-site defeat conditions.
   - Home: no group; `csrf` names it only as a chaining partner.
   - Rationale: a web vulnerability class with its own bent step (the interaction is real but hidden).
   - Confidence: medium. It is low impact alone, which is why it may have been left out.

8. **Multi-factor authentication bypass (new class).**
   - Sources: `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-mfa-bypass/SKILL.md`; `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/logic-flaws/2fa-bypass/SKILL.md`.
   - Content: step enforcement gaps, direct navigation past the challenge, one-time-code replay, brute force, race on validation, recovery-code exposure, and factor downgrade.
   - Home: no group.
   - Rationale: a web authentication vulnerability class with its own trust assumption (the step-up is required on every sensitive transition).
   - Confidence: medium to high.

9. **Account-recovery flow flaws (new class).**
   - Sources: `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-forgot-password/SKILL.md`; `/Users/diekgbbtt/hacking-skills/skills/web/auth/password-reset-flaws/SKILL.md`.
   - Content: enumeration oracle, token in the response body, token replay, missing binding, and missing rate limit.
   - Home: no group; `weak-credential-discovery/username-enumeration-oracle` owns only the enumeration primitive.
   - Rationale: a web authentication vulnerability class with its own flow.
   - Confidence: medium.

10. **Session management and fixation (new class).**
    - Sources: `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-session/SKILL.md`; `/Users/diekgbbtt/hacking-skills/skills/web/session/session-fixation/SKILL.md`; `/Users/diekgbbtt/hacking-skills/skills/web/session/cookie-attacks/SKILL.md`.
    - Content: fixation, missing invalidation on logout or credential change, low-entropy identifiers, refresh rotation gaps, and cookie-attribute issues.
    - Home: no group; `csrf-login-fixation` owns the cross-site planting only.
    - Rationale: a web session-security class.
    - Confidence: medium.

11. **Loose-comparison coercion bypass (type juggling) (new class).**
    - Source: `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W1/exploiting-type-juggling-vulnerabilities/SKILL.md`; corroborated by `/Users/diekgbbtt/hacking-skills/skills/web/auth/auth-bypass/SKILL.md`.
    - Content: type coercion in comparison, magic-hash equality, and input-type control to defeat an equality check.
    - Home: no group; `crypto-weakness` and `insecure-deserialization` are adjacent but do not own it.
    - Rationale: a web authentication-bypass class with its own bent step (the comparison accepts a non-equal value).
    - Confidence: medium; abstract the language-level condition rather than naming the language.

12. **Client-controlled authorization state (new class or technique).**
    - Source: `/Users/diekgbbtt/hacking-skills/skills/web/auth/auth-bypass/SKILL.md`.
    - Content: the server reads authorization state from a client-supplied parameter or cookie (role, admin, debug, trust-origin flags) and trusts it.
    - Home: no group; adjacent to `mass-assignment` and `broken-function-level-authorization`.
    - Rationale: a distinct primitive (the authority itself is client-controlled), not merely an object- or function-level check gap.
    - Confidence: medium.

13. **OAuth device-code phishing and illicit consent grant (oauth variant).**
    - Source: catalog entry `attacking-oauth-with-device-code-phishing` in `/Users/diekgbbtt/anthropic-cybersecurity-skills/catalog/catalog.json`.
    - Content: induce the victim to approve an attacker code (already in `oauth-device-approval`) or to grant a malicious application consent (no home).
    - Home: the consent-grant part is the proposal in the oauth section above.
    - Confidence: low; description-only evidence.

14. **IPv6 DNS takeover and credential relay (out of scope).**
    - Source: `/Users/diekgbbtt/awsome-offensive-security-skill/skills/network/ipv6-dns-takeover-mitm/SKILL.md`.
    - Content: rogue address configuration and name resolution to intercept and relay credentials.
    - Assessment: an internal-network attack, not a web vulnerability testing procedure and not a web bypass or proxy technique.
    - Decision: do not propose. Recorded so the synthesis can confirm the discard.

15. **Verbose-error and fail-open disclosure (home exists).**
    - Source: `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-exceptional-conditions/SKILL.md`.
    - Home: `information-disclosure` (not in this slice).
    - Decision: route to the `information-disclosure` slice; not a residual.

16. **Path-override headers and method-override headers (home exists).**
    - Sources: `/Users/diekgbbtt/hacking-skills/skills/web/authz/authz-bypass/SKILL.md`; `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-host-header/SKILL.md`.
    - Home: `header-injection/header-method-override` and `header-injection/header-host-forward-spoof`.
    - Decision: not residuals; the base `http-method-tampering` must cross-reference the `header-injection` group rather than restate the mechanics.

---

## Slice summary

- Groups covered: 6 (`authentication-jwt`, `oauth`, `csrf`, `http-method-tampering`, `open-redirect`, `subdomain-takeover`); base skills read: 30 (6 parents, 24 leaves).
- Sufficient-similarity outcome: `authentication-jwt`, `csrf`, `http-method-tampering`, and `open-redirect` are covered by their existing clauses; all source material lands as aspects, bypass forms, or technique leaves.
- New-skill proposals from this slice:
  - `oauth-response-type-swap` (low to medium confidence; alternative reading folds it into `oauth-redirect-uri-validation`).
  - `oauth-consent-grant-abuse` (low confidence; description-only source).
  - `mail-record-takeover` with two variants, `mail-receipt-claim` and `mail-authorisation-claim` (medium confidence).
- Enrichment candidates (ontology entity <- source): 4 for `authentication-jwt`, 5 for `oauth`, 6 for `csrf`, 4 for `http-method-tampering`, 3 for `open-redirect`, 4 for `subdomain-takeover`.
- References/scripts: no additions. Every candidate is concrete tooling, and the ontology matrix marks scripted tests genuinely absent for all six groups.
- Residual candidates: 13 substantive entries plus 3 routed entries.
  - Strongest: SAML/SSO assertion forgery, broken-link/external-resource hijacking, legacy-protocol authentication-endpoint parity, HTTP parameter pollution.
  - Routed to other slices: verbose-error disclosure to `information-disclosure`; path-override and method-override headers already owned by `header-injection`.
  - Out of scope: IPv6 DNS takeover and credential relay.
- Lowest-confidence items, flagged for the synthesis: the two `oauth` proposals, `mail-record-takeover`, the WebSocket and clickjacking class proposals, and the loose-comparison class proposal.
- No suite file was modified. No git command was run.
