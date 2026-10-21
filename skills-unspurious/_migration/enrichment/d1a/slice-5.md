# D1a enrichment proposal - slice 5

Report only. No suite skill was modified. No git command was run.

## Slice scope and counts

Groups (level-1 directories under `skills-unspurious/`, each with its parent `SKILL.md` plus its variant leaves at level 2):

- `header-injection` - 1 parent + 6 leaves = 7 skills.
- `http-request-smuggling` - 1 parent + 1 leaf = 2 skills.
- `race-conditions` - 1 parent + 4 leaves = 5 skills.
- `rce` - 1 parent + 2 leaves = 3 skills.
- `xss` - 1 parent + 2 leaves = 3 skills.
- `ssrf` - 1 parent + 3 leaves = 4 skills.

Total base skills in slice: 24.

Method executed literally as specified: base = the conformed suite in this worktree; sources read-only from the four repositories; candidate match by vulnerability class or chainable reasoning; sufficiency test then the boundary doc; macro semantic diff then ontology abstraction; references/scripts assessed last.

Source index built: 346 `SKILL.md` files across `/Users/diekgbbtt/hacking-skills/skills` (43 files), `/Users/diekgbbtt/claude-bug-hunter/skills` (105), `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted` (plus `catalog/`), `/Users/diekgbbtt/awsome-offensive-security-skill/skills` (370).

Candidates assessed in depth: 57.
Strong same-class matches: 41.
New-skill proposals (in-slice): 3 strong, 3 medium/flagged.
Out-of-slice new-skill candidates (lower confidence): 3.
Enrichment candidates: 48.
References/scripts imports proposed: 0 (all source references/scripts assessed as not generalised; see the slice summary).

Boundary vocabulary used: the five operator attributes (vuln-specific reconnaissance; attack-surface part family; communication protocol; trust-assumption difference; impact) tested against the variant-boundary doc's cover test (accurate + exhaustive) and its per-class signatures.

Confidence labels: strong, medium, low. Every low-confidence match is flagged inline.

---

## Group `header-injection`

### header-injection (parent)

**Sources matched**
- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-host-header/SKILL.md` - the same class as a superset: password-reset poisoning, unkeyed-Host cache poisoning, routing-based SSRF, path-override bypass, OAuth/OIDC issuer poisoning, virtual-host enumeration.
- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W6/testing-for-host-header-injection/SKILL.md` - the same class with connection-state and vhost-enumeration detail.
- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/web-vulnerabilities/host-header-injection-attacks/SKILL.md` - the same class, reflection-first decision flow.
- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-cache-poison/SKILL.md` - the cache-poisoning consumer (Host/X-Forwarded-Host unkeyed input).
- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W6/performing-web-cache-poisoning-attack/SKILL.md` - the cache-poisoning consumer.
- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W6/performing-web-cache-deception-attack/SKILL.md` - the cache-deception sub-shape.
- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/web-vulnerabilities/web-cache-poisoning-deception/SKILL.md` - the cache-poisoning/deception split.

**Similarity** sufficient. The parent is the conformed form of the host-header and cache-consumer sources.

**Boundary** none of the five attributes diverges for the six parent consumers (framing parser, Host-family spoof, cache, pre-auth router, framing pair, same-response client). One adjacent item is explicitly resolved away: routing-based SSRF (the Host header selects the upstream) is NOT a header-injection variant. Its trust assumption is the front-end fetch-sink selecting an interior destination, which is the `ssrf` class's assumption, and its carrier (a request header) is already an `ssrf` carrier-switching aspect. Verdict: non-match for header-injection, enrichment candidate for `ssrf` (listed there).

**New-skill proposals**
- `source: /Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W3/testing-for-email-header-injection/SKILL.md`
  `[NEW] target: email-header-injection` (SMTP message-header injection)
  Rationale: the base analysis for `header-injection` explicitly places outbound SMTP email-header injection "out of scope" and assigns it to "its related class", and no suite group carries that class. Boundary divergence is on two attributes at once. Communication protocol diverges (SMTP message headers, not HTTP headers). Trust-assumption diverges (the mail library and transport treat a form field as header data, and the header/body boundary is CRLF, not the HTTP framing contract). Impact diverges (spam relay, sender spoofing, phishing-body override, token copy via injected Cc/Bcc, and SMTP/IMAP command injection), none of which is protocol-level control of an HTTP response. The source is well-formed and carries the concrete procedures: CRLF variants (`%0A`, `%0D`, `%0D%0A`, double-encode), Cc/Bcc/From/Reply-To injection, MIME boundary override, and SMTP/IMAP command injection. Confidence: strong. This is a first-order class, not a derivative, so the operator's missing-baseline caution does not apply.

**Enrichment candidates**
- `PreconditionEnvironment` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-host-header/SKILL.md`: add the OIDC discovery/issuer document (`.well-known/openid-configuration`) as a link-generating oracle that reflects the authority family, distinct from a reset link (lines 197-205). Confidence: medium.
- `AttackTechnique` <- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/web-vulnerabilities/host-header-injection-attacks/SKILL.md`: add the double-Host and absolute-URL-override shapes (a second Host field, and an absolute request-target with a different Host) to the authority-family probe set (lines 97-113).
- `ObservableSignal` <- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W6/testing-for-host-header-injection/SKILL.md`: add virtual-host enumeration as a distinct read-out (status/size delta across forged authority values names the default vhost and internal vhosts), which is a different signal from a link or a decision (lines 145-161). Confidence: medium.

**References/scripts candidates** none. The source `references/api-reference.md` and `scripts/agent.py` files are concrete harnesses (hardcoded attacker host, named libraries, no placeholders), so they are not generalised and do not meet the `references/` PayloadPattern + Artifact contract.

### header-crlf-splitting (leaf)

**Sources matched** none in-slice beyond the parent's sources. The only CRLF-focused source found is the email-header-injection skill, whose CRLF carriage is the email class (see the new-skill proposal above), not the HTTP stored-framing oracle.

**Similarity** insufficient. The leaf's first bent step is "prove a line-break payload created a stored header field served downstream to an unrelated request", which no source carries.

**Boundary** not applicable; clean no-match verdict.

**New-skill proposals** none.

**Enrichment candidates** none.

**References/scripts candidates** none.

### header-cache-poisoning (leaf)

**Sources matched**
- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-cache-poison/SKILL.md` - the cache-consumer superset (unkeyed input, WCD, DoS via cached errors, Origin-to-ACAO shape, fat-GET, cache-buster discipline).
- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W6/performing-web-cache-poisoning-attack/SKILL.md` - the poisoning consumer with eligibility and `Vary` handling.
- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W6/performing-web-cache-deception-attack/SKILL.md` - the deception sub-shape with the path-normalization/delimiter family.
- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/web-vulnerabilities/web-cache-poisoning-deception/SKILL.md` - the poisoning/deception split.

**Similarity** sufficient. Same class and the same key-versus-content trust clause.

**Boundary** none diverges. The base analysis already folded deception into this leaf as a sub-shape, and both poisoning and deception break the same cache-key clause, so the source distinction is an aspect, not a variant. Respected as the base decision.

**New-skill proposals** none.

**Enrichment candidates**
- `PayloadPattern` <- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W6/performing-web-cache-deception-attack/SKILL.md`: add the delimiter-based path-discrepancy family (semicolon delimiter, encoded slash/percent, null byte, fragment, dot-segment normalization, case variation, double-encoded path) as the deception sub-shape, so the sweep enumerates the cache-vs-origin normalization seam (lines 97-134).
- `AttackTechnique` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-cache-poison/SKILL.md`: add the cached-CORS-header shape, where the unkeyed input is the Origin header reflected into the allow-origin value and then stored (line 209-210).
- `AttackTechnique` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-cache-poison/SKILL.md`: add the fat-GET shape (body parameters the backend processes while the cache ignores them) and the cached-error DoS shape to the sub-shape sweep (lines 109-113, 246).
- `AttackTechnique` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-cache-poison/SKILL.md`: add the cache-buster discipline (land on a fresh throwaway key while probing so a live victim key is never prematurely poisoned) as the safety rule on the sweep step (lines 101, 153-160).

**References/scripts candidates** none (same concrete-harness reason as the parent).

### header-host-forward-spoof (leaf)

**Sources matched**
- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-host-header/SKILL.md` - the authority-family oracle (precedence comparison, host-shape edges, out-of-band capture).
- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W6/testing-for-host-header-injection/SKILL.md` - the authority family with port/userinfo injection.
- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/web-vulnerabilities/host-header-injection-attacks/SKILL.md` - the authority family.

**Similarity** sufficient. Same leaf (link-builder plus access-decision oracles).

**Boundary** the routing-based-SSRF divergence is resolved to `ssrf` (see the parent). No attribute diverges for this leaf.

**New-skill proposals** none.

**Enrichment candidates**
- `PayloadPattern` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-host-header/SKILL.md`: add the host-shape edges as explicit values (trailing-port, userinfo split on `@`, suffixed-host absolute-URL form) beside the bracketed and trailing-dot forms already present (lines 102-110).
- `PreconditionEnvironment` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-host-header/SKILL.md`: add the OIDC discovery document as a second link-generating oracle (issuer and endpoint fields rebuilt from the authority), and add the "the two layers never compose" caution that separates routing SSRF from path override (lines 192-205). Confidence: medium.
- `ObservableSignal` <- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W6/testing-for-host-header-injection/SKILL.md`: add the virtual-host enumeration read-out (per-vhost status/size delta) as a third oracle beside link and decision (lines 145-161). Confidence: medium.

**References/scripts candidates** none.

### header-method-override (leaf)

**Sources matched**
- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-host-header/SKILL.md` - the path-override family (original-URL and rewrite-URL) with the edge-blocked direct-request proof.

**Similarity** sufficient. Same leaf (pre-auth router owning override and rewrite headers).

**Boundary** none diverges.

**New-skill proposals** none.

**Enrichment candidates**
- `PayloadPattern` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-host-header/SKILL.md`: add the `X-Override-URL` alias to the rewrite-header family and keep the "real authority stays put" scope note (lines 69, 181-190).
- `AttackTechnique` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-host-header/SKILL.md`: add the proof rule that the override is confirmed by a status/body diff against the edge-blocked direct request, which makes the reroute attributable rather than assumed (lines 189-190).

**References/scripts candidates** none.

### header-request-smuggling (leaf)

**Sources matched**
- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-http-smuggling/SKILL.md` - framing pairs plus the front-end strictness matrix.
- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W6/exploiting-http-request-smuggling/SKILL.md` - framing pairs plus downgrade.
- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/web-vulnerabilities/http-request-smuggling-desync/SKILL.md` - framing pairs.
- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/web-vulnerabilities/http-request-smuggling-te-te/SKILL.md` - encoding-declaration obfuscation.

**Similarity** sufficient. Same leaf (framing-disagreement pair, leftover-bytes oracle).

**Boundary** none diverges for the leaf.

**New-skill proposals** none at the leaf. The cross-protocol framing channel is a candidate at the `http-request-smuggling` group level (see there).

**Enrichment candidates**
- `AttackTechnique` <- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/web-vulnerabilities/http-request-smuggling-te-te/SKILL.md`: add the encoding-declaration obfuscation value set (spacing before the colon, invalid value spelling, obsolete folded-continuation form) to the pair-envelope sweep (lines 58-74).
- `ObservableSignal` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-http-smuggling/SKILL.md`: add the anomalous-response-to-a-normal-request signal (a normal request answered with a forbidden or wrong-path result because it was appended to the smuggled prefix) as a detection entry (lines 22-27). Confidence: medium.

**References/scripts candidates** none.

### header-response-value-confusion (leaf)

**Sources matched**
- `/Users/diekgbbtt/hacking-skills/skills/web/session/cookie-attacks/SKILL.md` - the cookie-attribute taxonomy (scope, persistence, cross-site, name shadowing) audited from the server side.
- `/Users/diekgbbtt/hacking-skills/skills/web/session/session-fixation/SKILL.md` - the cookie-attribute taxonomy and the prefix-binding hardening.
- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-host-header/SKILL.md` - the same-response content-type/redirect sinks.

**Similarity** partial. The cookie sources share the attribute taxonomy but not the injection mechanism, so similarity is insufficient for them as a whole class.

**Boundary** the session-management sources diverge on trust-assumption (the server's own weak cookie policy, not an attacker-supplied header value) and on attack-surface part family (session lifecycle, not header trust). They are out of this leaf's class (listed in the out-of-slice section). For the leaf's own header-value mechanism, no attribute diverges.

**New-skill proposals** none in-slice.

**Enrichment candidates**
- `DefensiveControl` <- `/Users/diekgbbtt/hacking-skills/skills/web/session/cookie-attacks/SKILL.md`: add the `__Host-` and `__Secure-` name prefixes as the hardening control that defeats the name-shadowing and scope-widening replacement shapes, so the leaf's False Positives can name it (lines 40, 138-139).
- `PayloadPattern` <- `/Users/diekgbbtt/hacking-skills/skills/web/session/cookie-attacks/SKILL.md`: add the cross-site-attribute semantics (the `None` versus `Lax` versus `Strict` value consequences and the "leading-dot domain widens to siblings" rule) to the cookie-attribute replacement block (lines 35-38, 133-139).

**References/scripts candidates** none.

---

## Group `http-request-smuggling`

### http-request-smuggling (parent)

**Sources matched**
- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-http-smuggling/SKILL.md` - framing pairs, front-end strictness matrix, mass-capture collector gadget, cross-protocol desync mention.
- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W6/exploiting-http-request-smuggling/SKILL.md` - framing pairs, downgrade, cleartext-upgrade and CONNECT shapes.
- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/web-vulnerabilities/http-request-smuggling/SKILL.md` - framing pairs.
- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/web-vulnerabilities/http-request-smuggling-desync/SKILL.md` - framing pairs.
- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/web-vulnerabilities/http-request-smuggling-te-te/SKILL.md` - encoding-declaration obfuscation.
- `/Users/diekgbbtt/hacking-skills/skills/web/injection/http-request-smuggling/SKILL.md` - framing pairs plus the capture/XSS chains.
- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/deep-dive-labs/http-request-smuggling/SKILL.md` - PortSwigger lab payload set (not read in full; header skim).

**Similarity** sufficient. Same class.

**Boundary** none diverges for the two known channels (HTTP/1.1 raw framing; HTTP/2 downgrade). One candidate third channel is flagged below.

**New-skill proposals**
- `source: /Users/diekgbbtt/claude-bug-hunter/skills/hunt-http-smuggling/SKILL.md` (matrix row only)
  `[NEW] target: http-request-smuggling-cross-protocol-desync` (framing desync at a translation hop into a non-HTTP binary protocol, e.g. HTTP to a Java servlet-connector protocol)
  Rationale: the group's discrimination function splits by transport framing channel, and a cross-protocol translation hop is a third channel, not a value of either existing channel. The source names it (cross-protocol HTTP-to-connector desync, smuggled request opaque to the WAF, reaching internal connector admin paths) but carries no probe procedure. Confidence: low-to-medium, flagged. Decision-grade caveat: do NOT action this until a source with an actual cross-protocol probe procedure is found; the base analysis already parked research-stage third channels (QUIC) outside the suite for the same reason. If a procedure is found later, this becomes a new leaf under this group.
- `source: /Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W6/exploiting-http-request-smuggling/SKILL.md` (lines 266-273) and `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-http-smuggling/SKILL.md` (lines 69-71)
  `[NEW] target: none` - recorded as a non-proposal. Cleartext-upgrade smuggling and CONNECT tunneling are upgrade-based shapes. The base analysis already folded WebSocket handshake hijacking into the confirming skill as a secondary, on the rule that the upgrade needs no distinct framing probe beyond the channel desync. This source confirms that rule, so the shapes stay aspects.

**Enrichment candidates**
- `Reconnaissance`/`AttackTechnique` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-http-smuggling/SKILL.md`: add the abstract front-end strictness check (fingerprint whether the front-end rejects ambiguous framing or normalises it, and record the version-strictness posture) as a gating step before investing in the pair sweep (lines 40-65). The concrete product list stays in the knowledge base, not the skill.
- `AttackTechnique` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-http-smuggling/SKILL.md`: add the collector-gadget capture procedure (aim the smuggled prefix at a backend handler that echoes the whole request, so the next victim's headers are attributed to the smuggled request and returned in a readable response) to the cross-user-capture step (lines 73-74).
- `ObservableSignal` <- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W6/exploiting-http-request-smuggling/SKILL.md`: add the paired-request differential confirmation (two rapid requests, one anomalous response) as the low-noise confirmation entry, distinct from the timing gap (lines 180-184).

**References/scripts candidates** none. The PortSwigger lab payload set in the deep-dive source is concrete lab-specific material, not a generalised scripted test.

### http-request-smuggling-h2-desync (leaf)

**Sources matched** the parent's downgrade sources: `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-http-smuggling/SKILL.md` (H2.CL/H2.TE dominant vector), `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W6/exploiting-http-request-smuggling/SKILL.md` (H2 header injection, CONNECT tunneling, cleartext-upgrade).

**Similarity** sufficient. Same leaf (HTTP/2 header-block injection with downgrade mapping).

**Boundary** none diverges.

**New-skill proposals** none.

**Enrichment candidates**
- `PayloadPattern` <- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W6/exploiting-http-request-smuggling/SKILL.md`: keep H2.CL and H2.TE as enumerated injection values inside the one variant, and add the cleartext-upgrade and CONNECT tunneling shapes as aspect values (lines 255-273). This matches the base analysis grey point that the values stay inside one variant while one inject-then-observe step covers both.

**References/scripts candidates** none.

---

## Group `race-conditions`

### race-conditions (parent)

**Sources matched**
- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-race-condition/SKILL.md` - the concurrency superset: single-packet attack, last-byte sync, first-sequence-sync, different-request/partial-construction race, window estimation, Wireshark validation.
- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W6/exploiting-race-condition-vulnerabilities/SKILL.md` - single-packet attack and multi-endpoint race.
- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/web-vulnerabilities/race-condition-toctou-exploitation/SKILL.md` - TOCTOU, single-packet, multi-endpoint race.
- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/api-security/graphql-batching-attacks/SKILL.md` - intra-request fan-out via batching and aliases.
- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W5/performing-api-rate-limiting-bypass/SKILL.md` - rate-limit counter race and per-entity enforcement.

**Similarity** sufficient for the class; the intra-request and rate-limit parts map to specific leaves and to the parent's rate-limit aspect.

**Boundary** one attribute diverges. The parent testing step "Concurrent requests - Issue parallel requests with identical inputs; observe deltas" is accurate but not exhaustive for a race that fires a list of different requests against a transient state. Three sources carry that shape (different-request partial construction, and racing two different endpoints such as email-change against password-reset or email-update against checkout). Trust-assumption diverges (the object exists in a usable state mid-creation) and the attack-surface part family diverges (two actions against one state machine, not one action duplicated). This is a bent step, so it is a new-variant proposal, not an aspect.

**New-skill proposals**
- `source: /Users/diekgbbtt/claude-bug-hunter/skills/hunt-race-condition/SKILL.md` (lines 17-29); corroborated by `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W6/exploiting-race-condition-vulnerabilities/SKILL.md` (lines 112-143) and `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/web-vulnerabilities/race-condition-toctou-exploitation/SKILL.md` (lines 105-121)
  `[NEW] target: race-conditions-partial-construction` (different-request / multi-endpoint race; alias multi-endpoint-race)
  Rationale: the first bent step is "fire a list of different requests in one synchronised window to exploit a transient mid-creation state, then complete the objective through the winning path". The delta over the parent is the different-request synchronisation plus the mid-creation window targeting, which the parent's identical-input step neither performs nor describes. Confidence: strong-medium. Decision-grade caveat: the base analysis folded "one-time-token races" into the parent core as an aspect, so the operator should confirm the seam is request-content diversity (this proposal) and not token consumption (already an aspect). The three sources agree on the procedure, which is what lifts this above a grey point.

**Enrichment candidates**
- `AttackTechnique` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-race-condition/SKILL.md`: name the single-packet attack and last-byte-sync mechanism precisely (one connection, all-but-last-byte buffered, final bytes released in one write) and add the wire-capture validation as the discipline that separates a real single-packet attack from a pipelined one (lines 333-376, 463-467). The base already carries last-byte sync as a phrase; this makes it a procedure.
- `AttackTechnique` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-race-condition/SKILL.md`: add first-sequence-sync as the widening primitive when the needed request count exceeds the single-packet bound (synchronised sequence numbers across connections, fragmentation), as an aspect of the synchronisation step (lines 440-450).
- `AttackTechnique` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-race-condition/SKILL.md`: add the race-window estimation decision tree (single, sequential, then concurrent timings decide whether the backend serialises and whether single-packet helps) as a pre-attack step (lines 387-397).
- `PreconditionEnvironment` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-race-condition/SKILL.md`: add the client-side-only guard precondition (a disabled button, an optimistic UI state set before the server confirms, sequential awaited calls without locking) as a race precondition (lines 67-76).
- `Reconnaissance`/`AttackTechnique` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-race-condition/SKILL.md`: add the white-box read-then-write grep step (find reads without locking and writes without atomicity) as a reconnaissance entry for source-available targets (lines 174-185).
- `AttackTechnique` <- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W5/performing-api-rate-limiting-bypass/SKILL.md`: resolve the base open question (identity-partitioned quota bursts) to "aspect, not variant". The source's rate-limit bypass is identifier rotation (header spoofing, path variation, method/content-type switch, account rotation) plus the counter-window burst, and the base parent already carries per-entity enforcement bypass with multiple addresses or sessions and burst-before-counter-propagation. Record the resolution and enrich the existing rate-limit aspect with the counter-window burst rule (lines 371, 405).

**References/scripts candidates**
- `references/race-single-packet.md` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-race-condition/SKILL.md`: borderline. The Turbo Intruder gate-sync template and the window-estimation procedure are generalised enough in structure to become a scripted test, but they name one tool. Flagged, not proposed, because the base analysis records `scripted tests` as absent for `race-conditions` and the import would need the tool name abstracted out first.

### idempotency-dedup-bypass (leaf)

**Sources matched** `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-race-condition/SKILL.md` (idempotency-key scope, cache-before-commit window, response-versus-effect forensics).

**Similarity** sufficient. Same leaf.

**Boundary** none diverges.

**New-skill proposals** none.

**Enrichment candidates**
- `AttackTechnique` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-race-condition/SKILL.md`: add the response-versus-effect forensics rule (the dedup response can suppress only the reply while the side effect still commits) as the confirmation discipline, and add the "partial fulfilment" case where one request errors yet both are honoured (lines 222-227, 237-238).

**References/scripts candidates** none.

### optimistic-guard-evasion (leaf)

**Sources matched** `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-race-condition/SKILL.md` (optimistic concurrency without version checking, cross-path enforcement gaps).

**Similarity** sufficient. Same leaf.

**Boundary** none diverges.

**New-skill proposals** none.

**Enrichment candidates**
- `AttackTechnique` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-race-condition/SKILL.md`: add the cross-path enforcement probe (the same versioned mutation reached through sibling channels, one of which commits unchecked) as the per-channel sweep, which the base leaf already names but without the "reach the same operation through several paths" procedure (lines 234-238).

**References/scripts candidates** none.

### single-request-fanout (leaf)

**Sources matched** `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/api-security/graphql-batching-attacks/SKILL.md` (array batching, alias batching, resource-exhaustion amplification).

**Similarity** sufficient. Same leaf; the source is the GraphQL instance of intra-request fan-out.

**Boundary** none diverges for the fan-out mechanism. The resource-exhaustion amplification impact is a different impact direction (denial rather than over-issuance); recorded as an aspect inside the leaf, not a variant, because the fan-out step is unchanged.

**New-skill proposals** none.

**Enrichment candidates**
- `PayloadPattern` <- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/api-security/graphql-batching-attacks/SKILL.md`: add the two concrete fan-out envelopes (an array of distinct operations in one request body, and alias-named repetitions of one field in one query) to the batching block, with the counter-window bypass as the goal (lines 53-90).
- `AttackGoal` <- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/api-security/graphql-batching-attacks/SKILL.md`: add the amplification-DoS outcome (one request carrying many costly operations) as a secondary goal beside over-issuance (lines 92-107). Confidence: medium.

**References/scripts candidates** none.

### cross-service-consistency-race (leaf)

**Sources matched** `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-race-condition/SKILL.md` (microservice TOCTOU, retry storms, queue serialisation gaps).

**Similarity** sufficient. Same leaf.

**Boundary** none diverges.

**New-skill proposals** none.

**Enrichment candidates**
- `AttackTechnique` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-race-condition/SKILL.md`: add the retry-storm induction procedure (provoke a timeout so an at-least-once consumer replays the side effect without dedup) and the queue-multiplicity probe (multiple workers consuming one queue pick up duplicates) to the cross-service window step (lines 228-232).

**References/scripts candidates** none.

---

## Group `rce`

### rce (parent)

**Sources matched**
- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-rce/SKILL.md` - the RCE superset: command injection, template injection, deserialization, prototype pollution, dependency confusion, path traversal, container surfaces, and configuration-as-code delegates.
- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/web-vulnerabilities/command-injection-os-level/SKILL.md` - OS command injection with blind/OOB and bypass shapes.
- `/Users/diekgbbtt/hacking-skills/skills/web/injection/cmd-injection/SKILL.md` - OS command injection.
- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W3/exploiting-api-injection-vulnerabilities/SKILL.md` - multi-class API injection (command, SQL, NoSQL, LDAP, SSRF).
- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/web-vulnerabilities/prototype-pollution-rce/SKILL.md` - prototype-pollution to Node execution (other class).
- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/deserialization/nodejs-deserialization-rce/SKILL.md` - deserialization to execution (other class).
- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-nodejs/SKILL.md` - Node-specific execution sinks (other class plus command injection).
- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/deep-dive-labs/os-command-injection/SKILL.md` - lab payload set.

**Similarity** sufficient for the command-injection and pipeline parts. The template, deserialization, prototype-pollution, path-traversal, supply-chain, and container parts are owned by other suite classes, exactly as the base cross-references state, and are non-matches for a new `rce` variant.

**Boundary** one attribute diverges. The discrimination function is "input-vector topology crossed with sink-primitive kind", with two cells carried: direct strings to OS wrappers, and uploaded files to out-of-process pipeline delegates. A third topology appears in the source: a configuration field in a management interface reaching a configuration-rendering delegate that supports execution primitives (a log-daemon destination, a metrics-plugin exec block, a job-template renderer). Its first step is neither direct-string discovery nor file-mediated construction, so the parent step is not exhaustive for it.

**New-skill proposals**
- `source: /Users/diekgbbtt/claude-bug-hunter/skills/hunt-rce/SKILL.md` (lines 84-92, 298-302, 410-411)
  `[NEW] target: rce-config-delegate-execution` (configuration-as-code delegate execution)
  Rationale: input-vector topology diverges (a configuration field, not a direct string and not an uploaded file), sink-primitive kind diverges (a configuration-file renderer or daemon that evaluates embedded directives), and the trust assumption diverges (administrators are treated as trusted, so field values pass straight into a configuration file that carries execution primitives). The source's procedure is concrete: enumerate management interfaces and free-form configuration fields, submit evaluation probes, then inject the delegate's execution primitive. Confidence: medium, flagged. Decision-grade caveat: the source carries one scenario per delegate family and no per-delegate matrix, so the operator may prefer to hold this as a named aspect inside `rce-pipeline-execution` until a source with a delegate matrix is found. This aligns with the base analysis open question about a dedicated delegate matrix. Do not action both ways at once.

**Enrichment candidates**
- `AttackTechnique`/`PayloadPattern` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-rce/SKILL.md`: add the content-type-to-parser matching rule as a first-class command-injection step (match the body encoding to the endpoint's parser, because a JSON body against a form parser yields a silent false negative with a plausible 200) (lines 8-25). This is the strongest single enrichment in the group.
- `PreconditionEnvironment` <- `/Users/diekgbbtt/hacking-skills/skills/web/injection/cmd-injection/SKILL.md`: add the utility-style surface family (network diagnostics, file conversion, archive utilities, report generators that build a shell string) as a reconnaissance applicability signal (lines 21-27).
- `AttackTechnique` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-rce/SKILL.md`: add the out-of-band confirmation procedure (DNS and HTTP callbacks with a unique marker, and the base64-encoded subdomain exfil shape) as the blind-confirmation entry (lines 225-231).
- `PayloadPattern` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-rce/SKILL.md` and `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/web-vulnerabilities/command-injection-os-level/SKILL.md`: add the reflection-indirection bypass shapes (a language-level send/call indirection to reach the same operation when its name is filtered) and the whitespace-bypass shapes (field separator, brace expansion, wildcard, quote-splitting, encoded token) to the bypass block (hunt-rce lines 323-334, 382-389; command-injection lines 66-87).

**References/scripts candidates** none.

### rce-command-injection (leaf)

**Sources matched** `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/web-vulnerabilities/command-injection-os-level/SKILL.md`, `/Users/diekgbbtt/hacking-skills/skills/web/injection/cmd-injection/SKILL.md`, `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W3/exploiting-api-injection-vulnerabilities/SKILL.md`, `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/deep-dive-labs/os-command-injection/SKILL.md`.

**Similarity** sufficient. Same leaf (direct strings to OS wrappers and CLI parsers).

**Boundary** none diverges.

**New-skill proposals** none.

**Enrichment candidates**
- `AttackTechnique` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-rce/SKILL.md`: add the argument-file-expansion shape (`@file` argument expansion by a Java-style CLI, which turns argument injection into an arbitrary file read when the error text echoes the arguments) as an argument-injection sub-shape (lines 241-278). Confidence: medium.
- `PayloadPattern` <- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/web-vulnerabilities/command-injection-os-level/SKILL.md`: add the whitespace-bypass value set (field-separator variable, brace expansion, redirection instead of space, wildcard execution, quote-splitting, base64 decode-on-the-fly) and the Windows caret-escape value (lines 66-87).
- `PayloadPattern` <- `/Users/diekgbbtt/hacking-skills/skills/web/injection/cmd-injection/SKILL.md`: add the path-component substitution value (a `${PATH:0:1}`-style character extraction for a blocked slash) to the bypass block (lines 80-85).
- `AttackTechnique` <- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W3/exploiting-api-injection-vulnerabilities/SKILL.md`: add the API injection-point inventory (path, query, body, and header carriers) as the input-supply step for API-shaped targets (lines 71-90).

**References/scripts candidates** none.

### rce-pipeline-execution (leaf)

**Sources matched** `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-rce/SKILL.md` (image converters, document renderers, metadata tools, typesetting engines, and the configuration-as-code delegates).

**Similarity** sufficient for the file-mediated delegate part; the configuration-field delegates are the new-variant candidate above.

**Boundary** none diverges for the file-mediated step. The configuration-field delegate is the divergence recorded at the parent.

**New-skill proposals** none at the leaf (see the parent proposal).

**Enrichment candidates**
- `AttackTechnique` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-rce/SKILL.md`: add the policy-gate and compile-flag fallback reasoning (probe which operator family a given build evaluates, and switch family when one is confined) to the delegate-probing step, which the base leaf already names as an aspect but without the per-build probe (lines 346-360). This also answers the base open question about a delegate matrix, partially.

**References/scripts candidates** none.

---

## Group `xss`

### xss (parent)

**Sources matched**
- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-xss/SKILL.md` - the XSS superset: marker discipline, blind-XSS beacon fields, sanitizer/mXSS bypass, CSP bypass, and the chain catalogue.
- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-dom/SKILL.md` - client-side techniques: DOM clobbering, postMessage hijacking, service-worker abuse, CSS exfiltration, client-side template injection.
- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W4/testing-for-xss-vulnerabilities/SKILL.md` - reflected, stored, and DOM testing.
- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W4/performing-content-security-policy-bypass/SKILL.md` - CSP bypass families.
- `/Users/diekgbbtt/hacking-skills/skills/web/injection/xss-reflected/SKILL.md` - reflected XSS.
- `/Users/diekgbbtt/hacking-skills/skills/web/injection/xss-stored/SKILL.md` - stored XSS.
- `/Users/diekgbbtt/hacking-skills/skills/web/client-side/dom-xss/SKILL.md` - DOM XSS sources and sinks.
- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/web-vulnerabilities/xss-reflected-stored-dom/SKILL.md` - context matrix and mutation XSS.
- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/web-vulnerabilities/dom-based-cross-site-scripting-xss/SKILL.md` - DOM XSS with DOM clobbering.
- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/web-vulnerabilities/dom-based-xss/SKILL.md` - DOM XSS with the cross-navigation source.
- `/Users/diekgbbtt/hacking-skills/skills/web/client-side/cspt/SKILL.md` - client-side path traversal (chains to XSS).

**Similarity** sufficient for the reflected/stored/DOM delivery split. The DOM clobbering, CSS exfiltration, and client-side path traversal content is not sufficient to fold into the delivery split and is treated below.

**Boundary** two attributes diverge for the client-side techniques. Trust-assumption diverges (attacker markup defines a global the application trusts; CSS is treated as presentation-only; the client trusts its own concatenated fetch path) and attack-surface part family diverges (DOM structure and client request construction, not a render or execution sink reached by a reflected or stored string). Impact diverges for two of them (authentication bypass without script, and data exfiltration without script).

**New-skill proposals**
- `source: /Users/diekgbbtt/claude-bug-hunter/skills/hunt-dom/SKILL.md` (lines 47-88); corroborated by `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/web-vulnerabilities/dom-based-cross-site-scripting-xss/SKILL.md` (lines 124, 140) and `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/web-vulnerabilities/xss-reflected-stored-dom/SKILL.md`
  `[NEW] target: dom-clobbering` (a new leaf under the `xss` group)
  Rationale: the first bent step is "inject markup that defines or shadows a named element so a JavaScript global the application trusts resolves to attacker-controlled structure, then drive the clobbered value into a sink". The source is a client-only flow whose source is DOM structure, not a string, so the parent source list (URL components, referrer, message channels, storage, server data) is not exhaustive for it. The delta is the clobberable-global discovery plus the markup-only injection requirement, which no existing leaf names. Confidence: strong-medium.
- `source: /Users/diekgbbtt/hacking-skills/skills/web/client-side/cspt/SKILL.md`
  `[NEW] target: client-side-path-traversal` (CSPT)
  Rationale: the first bent step is "concatenate an attacker value into the path component of a client fetch, traverse to a gadget endpoint, and let the client follow the redirect so the attacker controls the response". The trust assumption diverges (the client trusts its own concatenated path and follows redirects), the attack-surface part family diverges (client request construction), and the impact diverges (response injection and authenticated internal-endpoint reach, not script execution in the reflected sense). It chains to XSS but is not XSS. Confidence: medium, flagged as a possible new group rather than an `xss` leaf.
- `source: /Users/diekgbbtt/claude-bug-hunter/skills/hunt-dom/SKILL.md` (lines 180-211); corroborated by `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W4/performing-content-security-policy-bypass/SKILL.md` (lines 138-165, 167-190)
  `[NEW] target: css-injection-exfiltration`
  Rationale: the first bent step is "inject CSS that uses attribute selectors to leak a token character by character to an out-of-band receiver, with no script execution". Trust-assumption diverges (styles are treated as presentation-only, not as a data channel) and impact diverges (data disclosure without execution). Confidence: medium, flagged. Decision-grade caveat: both sources tie this to CSP gating (external resource origins must be open for the leak), so if the operator prefers, this can instead be an aspect inside `information-disclosure`; the report flags both homes and recommends the operator choose one, not both.

**Enrichment candidates**
- `AttackTechnique`/`Pro Tips` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-xss/SKILL.md`: add the marker baseline-search discipline (use a unique random alphanumeric marker and search the no-marker baseline for it first, because common words in help links are reflection traps) as a false-positive killer on the reflection step (lines 14, 155).
- `PreconditionEnvironment`/`ObservableSignal` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-xss/SKILL.md`: add the blind-XSS beacon-field family (error messages, source and return-URL parameters, login username fields, User-Agent, Referer, email addresses, file names) and the browser-user-agent confirmation rule (a backend HTTP client firing is not victim execution) to the listener step (lines 61-91).
- `PayloadPattern` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-xss/SKILL.md`: add the sanitizer round-trip value set (the math-plus-style and svg-plus-style parsing-ambiguity combinations) to the sanitizer bypass block (lines 206-214, 298-304).
- `PayloadPattern` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-xss/SKILL.md`: add the client-side expression-evaluation sandbox-escape value set for the legacy expression framework (the constructor and `$eval` forms, and the no-quotes order-by form) to the client-only expression block (lines 337-347).
- `PreconditionEnvironment` <- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/web-vulnerabilities/dom-based-xss/SKILL.md`: add the cross-navigation client source (`window.name`, which survives cross-origin navigation) to the client source families (lines 27, 63-66).
- `AttackTechnique`/`Chaining Attacks` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-xss/SKILL.md`: add the self-XSS-plus-CSRF-trigger chain (a CSRF-vulnerable mutation of the field that carries the self-XSS), which converts a self-only finding into a real one and changes the False-Positives verdict (lines 391-397).
- `DefensiveControl` <- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/web-vulnerabilities/dom-based-cross-site-scripting-xss/SKILL.md`: add the Trusted-Types policy as a hardening control that forces every write to a dangerous sink through a sanitising function, beside the existing nonce/hash policy control (lines 131, 176).
- `DefensiveControl` <- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W4/performing-content-security-policy-bypass/SKILL.md`: the CSP bypass families (whitelisted-JSONP endpoint, base-uri and form-action and object-src gaps, nonce leakage and reuse, reflected-policy injection, script gadgets in allowed libraries) belong to the `defence-bypass` family's step, which the base already names. Record as an out-of-slice enrichment for `defence-bypass`, not for the `xss` body. Confidence: strong for the ownership, so no `xss` body change.

**References/scripts candidates** none. The base `xss` already ships inline scripted tests, and no source carries a generalised external script.

### xss-stored (leaf)

**Sources matched** `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-xss/SKILL.md` (blind/stored OOB gate, beacon fields, cache-to-stored chain), `/Users/diekgbbtt/hacking-skills/skills/web/injection/xss-stored/SKILL.md`, `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/web-vulnerabilities/xss-reflected-stored-dom/SKILL.md`.

**Similarity** sufficient. Same leaf (write-then-retrieve).

**Boundary** none diverges.

**New-skill proposals** none.

**Enrichment candidates**
- `PreconditionEnvironment`/`AttackTechnique` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-xss/SKILL.md`: add the blind-stored beacon-field family and the "plant early, keep the listener open, expect hours-to-days delay" discipline to the retrieval-confirmation step (lines 61-91).
- `AttackTechnique` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-xss/SKILL.md`: add the reflected-to-stored conversion via a cache layer (an unkeyed input that shapes a cached body) as a named secondary path in the retrieval matrix (lines 383-389). Ownership of the cache mechanics stays with the header-injection cache leaf.

**References/scripts candidates** none.

### xss-dom (leaf)

**Sources matched** `/Users/diekgbbtt/hacking-skills/skills/web/client-side/dom-xss/SKILL.md`, `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/web-vulnerabilities/dom-based-xss/SKILL.md`, `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-dom/SKILL.md`.

**Similarity** sufficient. Same leaf (non-persistent client-only tracing).

**Boundary** none diverges for the tracing step. DOM clobbering as a source family is the divergence recorded at the parent.

**New-skill proposals** none at the leaf (see the parent proposal for dom-clobbering).

**Enrichment candidates**
- `PreconditionEnvironment` <- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/web-vulnerabilities/dom-based-xss/SKILL.md`: add `window.name` as a client source family (it survives cross-origin navigation, so a set-once value persists) beside fragment, browser-read query, cross-document message, and client store (lines 27, 63-66).
- `AttackTechnique` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-dom/SKILL.md`: add the weak-origin-check bypass to the cross-document-message source family (a partial check by index-of, ends-with, or unanchored regex is bypassable with a look-alike host, so a weak check is still a finding) (lines 133, 267-273).
- `ObservableSignal` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-dom/SKILL.md`: add the "source reachable but sink never invoked" negative read-out, so a clobberable or sourced value that never reaches a sink is recorded as non-flow rather than blocked execution (lines 269).

**References/scripts candidates** none.

---

## Group `ssrf`

### ssrf (parent)

**Sources matched**
- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-ssrf/SKILL.md` - the SSRF superset: OOB gate, per-parameter attribution, blind-versus-full-read, cloud metadata, headless-browser sinks, DNS rebinding, filter bypasses.
- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W6/performing-blind-ssrf-exploitation/SKILL.md` - blind detection, internal enumeration, metadata, bypasses.
- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W6/exploiting-server-side-request-forgery/SKILL.md` - metadata, internal scan, filter bypass, escalation.
- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W6/performing-ssrf-vulnerability-exploitation/SKILL.md` - URL-parameter probing with encoding and rebinding checks.
- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/cloud-security/aws-imdsv2-ssrf-bypass/SKILL.md` - IMDSv2 token sequencing.
- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/cloud-security/aws-metadata-ssrf/SKILL.md`, `.../aws-metadata-ssrf-exploitation/SKILL.md`, `.../ssrf-aws-metadata-abuse/SKILL.md` - IMDSv1/v2 credential reads (three overlapping skills).
- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/web-vulnerabilities/ssrf-nextjs-server-actions/SKILL.md` - framework server-action fetch sink.
- `/Users/diekgbbtt/hacking-skills/skills/web/injection/ssrf/SKILL.md` - SSRF with render-tag sink.
- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/ai-red-teaming/model-exploitation/ai-data-extraction-via-ssrf/SKILL.md` - SSRF via an LLM browsing/tool channel.
- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-nextjs/SKILL.md` - image-optimization fetch sink.

**Similarity** sufficient. Same class; the metadata skills are the exact source of the `header-gated-cloud-credential-read` leaf.

**Boundary** none of the five attributes diverges. The headless-browser JavaScript-execution sink and the LLM-tool carrier are carrier/sink families inside the parent, not new variants: the steer-and-observe procedure is unchanged, and the parent's carrier-switching bypass already covers moving a destination between carriers.

**New-skill proposals** none. One low-confidence flag: if the operator later wants the headless-browser JavaScript-execution sink separated, its bent step would be at surface inventory (the carrier is attacker-authored script, not a URL), but on the current evidence it stays an aspect. Flagged, not proposed.

**Enrichment candidates**
- `False Positives` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-ssrf/SKILL.md`: add the error-echo false positive (a server that formats your URL into an error string has not made an outbound request), which is the single highest-value addition because it is the most common mis-report (lines 29-33, 55).
- `AttackTechnique` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-ssrf/SKILL.md`: add the per-parameter attribution procedure (one fresh token per candidate field, one request each, and record a no-callback field as evidence with a negative control) to the oracle step (lines 57-83).
- `AttackTechnique` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-ssrf/SKILL.md`: add the blind-versus-full-read settlement (fetch a known external body first and check whether the upstream body is returned) as a scoping step before severity (lines 85-105).
- `AttackTechnique` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-ssrf/SKILL.md`: add the JavaScript-execution renderer sink (the renderer executes attacker-authored script that constructs the fetch and exfiltrates by DNS-encoded subdomain) as a sink family in the inventory (lines 200-206, 287-304).
- `AttackTechnique` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-ssrf/SKILL.md`: add the trusted-internal-redirector shape (a registered internal component that returns a redirect with elevated credentials, so the aggregation layer itself fetches the interior target) to the redirect-differential block (lines 198, 460-461).
- `PayloadPattern` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-ssrf/SKILL.md`: add the wrapped/encoded destination family (a base64 blob in the path, a double-encoded host) with the rule that the number of decode passes before the fetch is the bug (lines 391-402).
- `PayloadPattern` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-ssrf/SKILL.md`: add the parser-confusion address shapes (userinfo split on `@`, fragment before host, encoded `@`, backslash before host) to the address-encoding block (lines 370-389).
- `PreconditionEnvironment` <- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/ai-red-teaming/model-exploitation/ai-data-extraction-via-ssrf/SKILL.md`: add the LLM-tool carrier (a prompt forces the model's fetch or browse tool to request an interior destination) as a carrier family, composing with the `llm-prompt-injection` class rather than restating it. Confidence: medium.

**References/scripts candidates** none.

### no-response-egress-inference (leaf)

**Sources matched** `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W6/performing-blind-ssrf-exploitation/SKILL.md`, `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-ssrf/SKILL.md`.

**Similarity** sufficient. Same leaf (inference from side channels when no body returns).

**Boundary** none diverges.

**New-skill proposals** none.

**Enrichment candidates**
- `AttackTechnique` <- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W6/performing-blind-ssrf-exploitation/SKILL.md`: add the internal-range sweep and port-scan timing loop as the concrete enumeration procedure for the port-map step, with the known-open and known-closed control points (lines 103-127).
- `ObservableSignal` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-ssrf/SKILL.md`: add the distinct-status-on-link-local signal (a 401 from the metadata address where every other target returns 200 proves reach to a non-internet-routable address) (lines 102-105).

**References/scripts candidates** none.

### scheme-translated-command-execution (leaf)

**Sources matched** `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-ssrf/SKILL.md` (gopher-to-Redis, wrapper reads), `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W6/performing-blind-ssrf-exploitation/SKILL.md` (gopher command injection).

**Similarity** sufficient. Same leaf (raw-protocol grammar and wrapper reads under a direct oracle).

**Boundary** none diverges.

**New-skill proposals** none.

**Enrichment candidates**
- `AttackTechnique` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-ssrf/SKILL.md`: add the store-to-scheduled-write pivot shape (a reachable in-memory store writes a scheduled entry that fires) as the canonical grammar-to-effect chain, which the base leaf already names but without the write-and-trigger procedure (lines 487-491).

**References/scripts candidates** none.

### header-gated-cloud-credential-read (leaf)

**Sources matched** `/Users/diekgbbtt/awsome-offensive-security-skill/skills/cloud-security/aws-imdsv2-ssrf-bypass/SKILL.md`, `.../aws-metadata-ssrf/SKILL.md`, `.../aws-metadata-ssrf-exploitation/SKILL.md`, `.../ssrf-aws-metadata-abuse/SKILL.md`, `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-ssrf/SKILL.md`.

**Similarity** sufficient and exact. This leaf was built from this technique.

**Boundary** none diverges.

**New-skill proposals** none.

**Enrichment candidates**
- `AttackTechnique` <- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/cloud-security/aws-imdsv2-ssrf-bypass/SKILL.md`: add the token-request header value (the token time-to-live header) and the role-name-then-credentials two-read step to the sequencing block, plus the negative rule that a GET-only sink cannot open the gate (lines 43-74).
- `PreconditionEnvironment`/`AttackTechnique` <- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/cloud-security/aws-metadata-ssrf-exploitation/SKILL.md`: add the instance user-data path as a metadata target (startup scripts and cloud-init material often carry secrets) beside the credential path (lines 89-125 area, description).

**References/scripts candidates** none.

---

## Out-of-slice observations (lower confidence, for operator triage)

These matched inside the slice by chainable reasoning but diverge from every slice base skill; recorded so the operator can route them, not as in-slice proposals.

- `session-management` (or `session-cookie-security`) <- `/Users/diekgbbtt/hacking-skills/skills/web/session/cookie-attacks/SKILL.md` and `/Users/diekgbbtt/hacking-skills/skills/web/session/session-fixation/SKILL.md`. A first-order class absent from the suite (cookie attribute audit, session-token rotation, logout invalidation, token entropy, SSO single-logout). Boundary divergence on trust-assumption and attack-surface part family. Confidence: low-to-medium. Caution: this is a root class, not a derivative, so the missing-baseline caution does not block it, but it is outside the header-injection class and the operator should decide whether the suite wants a session group.
- `rate-limit-bypass` (OWASP API4) <- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W5/performing-api-rate-limiting-bypass/SKILL.md`. A rate-limiting class absent from the suite. The concurrent-counter part is already an aspect of `race-conditions`; the identifier-rotation taxonomy is the new material. Confidence: low. It also overlaps `header-injection` (forwarded-address spoofing) and `weak-credential-discovery` (brute force).
- `http-parameter-pollution` <- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W9/performing-http-parameter-pollution-attack/SKILL.md`. A duplicate-parameter parsing class absent from the suite. The duplicate-header-pollution part is already a `header-injection` bypass aspect; the parameter-precedence taxonomy is the new material. Confidence: low.

---

## Slice summary

Counts:
- Base skills in slice: 24 (6 parents, 18 leaves).
- Candidate sources assessed: 57.
- Strong same-class matches: 41.
- New-skill proposals (in-slice): 6 total, 3 strong (email-header-injection; race-conditions-partial-construction; dom-clobbering) and 3 medium or flagged (client-side-path-traversal; rce-config-delegate-execution; css-injection-exfiltration). Plus 1 low-confidence flagged (http-request-smuggling-cross-protocol-desync).
- Enrichment candidates: 48.
- Out-of-slice candidates: 3 (session-management, rate-limit-bypass, http-parameter-pollution).
- References/scripts imports: 0.

Strongest findings, in order:
1. `email-header-injection` is a genuine missing class. The base `header-injection` analysis itself names it as out-of-scope "related class", and no suite group carries it. Protocol, trust assumption, and impact all diverge. Source is well-formed. Actionable now.
2. `race-conditions-partial-construction` (different-request or multi-endpoint race) is a real bent step. The parent testing step is explicitly identical-input, and three independent sources carry the different-request procedure (register-then-confirm; email-change against password-reset; email-update against checkout). This is the highest-value in-slice new variant.
3. The `rce` group's strongest enrichment is the content-type-to-parser matching rule (a JSON body against a form parser yields a silent false negative). It is cheap, generalised, and currently absent from `rce-command-injection`.
4. `ssrf`'s strongest enrichment is the error-echo false positive (a server that formats your URL into an error string has not fetched anything). It is the most common mis-report and is currently absent from the `ssrf` False Positives.
5. The `xss` client-side cluster (DOM clobbering, CSS exfiltration, client-side path traversal) is under-covered. `dom-clobbering` is the strongest of the three and belongs as a new leaf under the `xss` group; the other two need an operator decision on their home (a new client-side group versus an `information-disclosure` aspect versus an `xss` leaf).
6. The `header-injection` routing-based-SSRF content resolves cleanly to `ssrf` as a carrier, not to a new header variant. This is a deliberate non-match that prevents an over-split.
7. No source provides a generalised references/scripts example. The anthropic `scripts/agent.py` files are concrete target harnesses with hardcoded attacker values; the awsome `scripts/process.py` files are CI validation harnesses; the anthropic `references/api-reference.md` tables are concrete runtime facts. Only the race single-packet template is borderline, and it needs tool-name abstraction before any import.
