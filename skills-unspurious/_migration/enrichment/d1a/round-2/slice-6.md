# D1a round-2 slice 6: `defence-bypass` and `proxy-techniques`

*Independent second mining round (W7, C4-full enrichment).*
*Base: `skills-unspurious/` in this worktree.*
*Sources read-only: `/Users/diekgbbtt/hacking-skills/skills` (43), `/Users/diekgbbtt/claude-bug-hunter/skills` (105), `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted` (43 accepted skills; `catalog/catalog.json` holds 818 names), `/Users/diekgbbtt/awsome-offensive-security-skill/skills` (370).*
*This round did not read `skills-unspurious/_migration/enrichment/d1a/` first-round artifacts.*
*No suite skill was modified. No git command was run.*

## Slice header

| Group | Level 1 | Leaves at level 2 |
|---|---|---|
| `defence-bypass` | `defence-bypass/SKILL.md` | signature-evasion, encoding-differential, parser-confusion, allowance-gap, edge-origin-differential, throttle-evasion |
| `proxy-techniques` | `proxy-techniques/SKILL.md` | dns-rebinding, redirect-chain, url-parser-differential, channel-wrapping, cache-deception, relay-forwarding |

Counts: 2 parent skills, 12 leaf skills, 14 base files read in full.
Both groups are **families, not class axes**, per `docs/design/skills-variant-boundary.md` ("Pitfalls": `proxy-techniques` and `defence-bypass` are families, not class axes).
The boundary test is therefore applied to the leaves, and the parents are treated as umbrellas whose job is coverage plus cross-reference.
The cross-reference in force is stated in both normative docs: consuming classes name `defence-bypass` at bypass steps and `proxy-techniques` at proxy steps.

**Sources indexed and read in full or in the relevant part for this slice** (path -> mechanism):
- `anthropic/W9/performing-web-application-firewall-bypass` -> WAF signature evasion, encoding layers, parser confusion, method/framing tricks, tamper payloads.
- `anthropic/W4/performing-content-security-policy-bypass` -> CSP permit enumeration, Trusted-Types-adjacent script-gadget and nonce leaks, base-uri/form-action gaps.
- `anthropic/W9/performing-http-parameter-pollution-attack` -> duplicate-member precedence, client-side HPP.
- `anthropic/W5/performing-api-rate-limiting-bypass` -> counted-dimension gap, header rotation, path/method/carrier variation, race on the counter.
- `anthropic/W1/exploiting-type-juggling-vulnerabilities` -> comparison folding and normalisation equivalence.
- `anthropic/W6/performing-web-cache-deception-attack` -> cache-key omission, path normalisation, two-caller read.
- `anthropic/W6/performing-web-cache-poisoning-attack` -> unkeyed header/parameter, parameter cloaking, fat GET.
- `anthropic/W6/testing-for-host-header-injection` -> relay-field families, reset poisoning, routing SSRF, path override.
- `anthropic/W6/testing-for-open-redirect-vulnerabilities` -> destination parse bypass, hop chaining, escalation.
- `anthropic/W2/bypassing-authentication-with-forced-browsing` -> path/method scoped rules, route divergence.
- `anthropic/W5/performing-graphql-depth-limit-attack` -> per-request cost amplification.
- `anthropic/W7/performing-ssl-stripping-attack` and `anthropic/N3/conducting-man-in-the-middle-attack-simulation` -> transport downgrade, interception, DNS spoof.
- `claude-bug-hunter/hunt-cache-poison` -> unkeyed reflection, WCD path appending, extension-allowlist gap, TTL, second-client proof.
- `claude-bug-hunter/hunt-host-header` -> field-family spraying, routing SSRF vs path override, OIDC issuer poisoning.
- `claude-bug-hunter/hunt-brute-force` -> four limit states incl. silent shadow-throttle, rotation, window timing.
- `claude-bug-hunter/hunt-captcha-bypass` -> the only-gate removal, token replay, concurrency window.
- `claude-bug-hunter/hunt-nextjs` -> middleware-tier skip, subrequest-assertion header, ISR cache poisoning.
- `claude-bug-hunter/hunt-nodejs` -> framework trust-proxy reaching an allowlist/rate decision.
- `claude-bug-hunter/hunt-websocket` and `awsome/.../websocket-hijacking-testing` -> second-carrier socket, guard parity, signed-message replay, handshake smuggling.
- `claude-bug-hunter/security-arsenal` -> WAF evaluation order, encoding order, smuggling payload bank.
- `claude-bug-hunter/hunt-http-smuggling` -> framing disagreement, timing-differential confirmation, modern-vector matrix.
- `awsome/.../api-rate-limit-bypass-techniques` -> identifier folding, array batching, version downgrade.
- `awsome/.../web-cache-poisoning-deception`, `awsome/.../deep-dive-labs/cache-deception`, `awsome/.../deep-dive-labs/web-cache-poisoning`, `awsome/.../deep-dive-labs/host-header` -> lab-grade payloads and delimiter sets.
- `awsome/.../csrf-token-bypass-techniques` -> permit-presence gaps, session-binding gaps, SameSite method override.
- `hacking-skills/web/client-side/cspt` -> decode-count arithmetic between checker and consumer.
- `hacking-skills/web/client-side/cors-misconfig` -> origin-permit reflection, null origin, prefix/suffix regex gap.
- `claude-bug-hunter/hunt-ssrf` and `awsome/.../ssrf-server-side-request-forgery` -> DNS rebinding as a validate-then-fetch TOCTOU.

---

# Group `defence-bypass`

## defence-bypass (parent, umbrella)

**Sources matched**: all defence-bypass leaves below; the strongest parent-level matches are `anthropic/W9/performing-web-application-firewall-bypass`, `anthropic/W4/performing-content-security-policy-bypass`, `anthropic/W9/performing-http-parameter-pollution-attack`, `anthropic/W5/performing-api-rate-limiting-bypass`, `claude-bug-hunter/security-arsenal`.

**Similarity**: coverage, not a diff.
The parent states one control-agnostic model: a control evaluates a value, a route, a tier, an enumeration, or a count, and the gap is between what it evaluates and what the sink consumes.
No source states this model as a single abstraction.
Every source is class- or product-anchored (a WAF, a CSP header, a parameter parser, a rate limiter).
The parent's six clauses (reading, enumeration, permit, tier, accounting) are the generalisation; the sources supply the concrete instances that the leaves already hold.

**Boundary**: the parent is an umbrella over six leaves, not a class with a signature.
The variant boundary explicitly lists this family as a non-class.
No discriminator is derived here; no variant set is emitted.

**New-skill proposals**: none at parent level.

**Enrichment candidates**:
- `DefensiveControl` <- `claude-bug-hunter/security-arsenal` (line ~868): the evaluation order a bypass should follow (encoding, then parser-quirk, then protocol-level, then vendor rule gaps), which names the control-kind axis the parent lists but does not order.
- `ObservableSignal` <- `claude-bug-hunter/security-arsenal` (line ~862): fingerprint the front-end from its own `Server`/`Via` markers before selecting a mechanism, so the mechanism follows the control rather than the payload.

**References/scripts candidates**: none generalisable at parent level (all sources are concrete payload banks; see leaf entries).

---

## defence-bypass-signature-evasion

**Sources matched**:
- `anthropic/W9/performing-web-application-firewall-bypass` (Step 2 encoding, Step 6 XSS case/event/alias, Key Concepts "Signature Evasion").
- `claude-bug-hunter/security-arsenal` (section "WAF Bypass", line ~166; "WAF evaluation order", line ~868).
- `awsome/.../advanced-sql-injection-sqli` (WAF bypass framing).
- `claude-bug-hunter/hunt-cache-poison` (line ~233): header-variant case/encoding bypass of a WAF that blocks known poison headers.

**Similarity**: sufficient.
The source mechanism is identical to the leaf: a matcher keys off literal shapes, and the sink accepts more shapes than the list carries.
The source's concrete axes (mixed case, inline comments, version comments, separator substitutes, sibling tags/events, aliases) are the leaf's own axes.
Macro semantic diff: the sources carry concrete product payloads (specific tags, specific SQL comments, specific header names), which the abstractness rule excludes from the body.
The generalisable residue is small and already present, except for two additions below.

**Boundary**: no bent step.
The leaf's steps (locate matcher, baseline refusal, probe axes, craft, confirm at sink, attribute) cover every source action.
The source's "list grows between attempts" is already the leaf's Pro Tip 4.
Verdict: stays a variant; the difference is aspect-level (which control kind the matcher belongs to is `TechnologyStack`, a non-discriminator).

**New-skill proposals**: none.

**Enrichment candidates**:
- `DefensiveControl` <- `anthropic/W9/performing-web-application-firewall-bypass` (Key Concepts table): the control-kind axis signature-based versus behavioural/anomaly detection, because a rule-set gap is only defined against a signature matcher, and an anomaly matcher needs a different axis set.
- `PayloadPattern` <- `claude-bug-hunter/security-arsenal` (WAF evaluation order, line ~872): the ordered axis list (case variation, single encode, double encode, unicode escape, HTML entity, UTF-8 overlong) as the probe order for the axis sweep.
- `ObservableSignal` <- `claude-bug-hunter/security-arsenal` (line ~862): the front-end fingerprint that tells the tester whether the rule set is a signature matcher or a parser-strict front, before the axis sweep.

**References/scripts candidates**:
- `claude-bug-hunter/security-arsenal` "WAF Bypass" block and `anthropic/W9/performing-web-application-firewall-bypass` payload tables are a bulky proof bank (PayloadPattern + Artifact). They are concrete (product-specific), so they are **not** generalised to a body section; a curated, de-productised subset could live in `references/`. Flag as medium confidence.

---

## defence-bypass-encoding-differential

**Sources matched**:
- `hacking-skills/web/client-side/cspt` (WAF encoding-level matrix, lines ~56-97): a decode-count disagreement between the WAF's decode level and the app/browser decode level, plus the padding arithmetic that keeps the checker's depth non-negative while the consumer's goes negative.
- `anthropic/W1/exploiting-type-juggling-vulnerabilities`: folding and normalisation equivalence (loose comparison maps two spellings onto one value; `0e`-magic strings, `null`/empty, type substitution).
- `anthropic/W9/performing-web-application-firewall-bypass` (double and unicode encoding, overlong).
- `claude-bug-hunter/hunt-http-smuggling` (TE obfuscation as a decode-count variant on the framing token).
- `anthropic/W6/performing-web-cache-deception-attack` (encoded and double-encoded path forms that one side resolves and the other does not).

**Similarity**: sufficient.
The leaf's decode-count clause is exactly the CSPT mechanism: the checking side decodes a different number of times than the consuming side.
The leaf's folding clause is exactly the type-juggling mechanism: a comparison that folds admits a spelling the sink treats as distinct.
Both land on existing Key Vulnerabilities (Decode-Count Gaps, Folding and Normalisation Gaps).
Macro diff: the CSPT padding arithmetic and the type-juggling coercion families are concrete procedures the leaf does not spell out.

**Boundary**: no bent step.
Decode-count and folding are the leaf's own clauses.
The type-juggling reader pair (comparison operator versus sink) is a second reader of one value, which the leaf's decode-count clause already covers as "two readings of one byte string".
Verdict: stays a variant.
Grey point: if the comparison-coercion procedure is judged to own a step the leaf cannot describe (a language-semantics step rather than a decode step), it would escalate; my reading is that it does not, and it is an aspect.

**New-skill proposals**: none.

**Enrichment candidates**:
- `AttackTechnique` <- `hacking-skills/web/client-side/cspt` (lines ~62-66): keep the checker's count inside its bound while pushing the consumer's count outside it, by padding the value with segments the checker decodes away.
- `PayloadPattern` <- `anthropic/W1/exploiting-type-juggling-vulnerabilities` (Step 3, Step 5): coercion-equivalent forms of one value (magic-hash spellings, null/empty, boolean/array/zero) as folding equivalents, stripped of the language name.
- `DefensiveControl` <- `anthropic/W1/exploiting-type-juggling-vulnerabilities` (Key Concepts): loose versus strict comparison as the folding rule a comparison applies, so the leaf can state which folding behaviour it probes.

**References/scripts candidates**:
- `hacking-skills/web/client-side/cspt` WAF encoding-level matrix (lines ~56-97) is compact and mechanism-level; it generalises to a reference table for the decode-count probe order. Medium confidence.
- `anthropic/W1/exploiting-type-juggling-vulnerabilities` payload table is concrete (product/language payloads); not generalised.

---

## defence-bypass-parser-confusion

**Sources matched**:
- `anthropic/W9/performing-http-parameter-pollution-attack` (Step 1 precedence matrix: first-wins, last-wins, array, comma-concat; Step 2/4 duplicate-parameter splitting).
- `claude-bug-hunter/hunt-http-smuggling` (framing disagreement: front-end uses one boundary rule, back-end another; timing-differential confirmation; modern-vector matrix) and `anthropic/W6/exploiting-http-request-smuggling`, `awsome/.../http-request-smuggling-desync`, `awsome/.../http-request-smuggling-te-te`, `hacking-skills/web/injection/http-request-smuggling`.
- `anthropic/W6/testing-for-host-header-injection` (duplicate Host header: backend uses the second, cache keys on the first).
- `awsome/.../deep-dive-labs/host-header` (Lab 3 ambiguous request: duplicate Host).
- `anthropic/W2/bypassing-authentication-with-forced-browsing` (Step 4: `X-HTTP-Method-Override` and `X-Original-Method` restate the verb).
- `claude-bug-hunter/security-arsenal` (smuggling payload bank, line ~449).

**Similarity**: sufficient.
HPP is the leaf's Duplicate Member Precedence clause in another vocabulary.
Smuggling is the leaf's Representation and Framing Reading clause: two readers re-derive the request boundary differently.
Method override is the leaf's Verb and Location Re-reading clause.
Macro diff: the smuggling sources add a timing-differential confirmation method and the modern-vector matrix.

**Boundary**: no bent step.
The suite already owns the desync class (`http-request-smuggling`), which owns the framing-desync procedure; this family must name that class, not restate it, and the leaf already does so at its chaining step.
The leaf's framing clause covers re-derivation at a transit tier.
Verdict: stays a variant; the smuggling class is the owner of the desync procedure, so no restatement and no proposal.

**New-skill proposals**: none.

**Enrichment candidates**:
- `PayloadPattern` <- `anthropic/W9/performing-http-parameter-pollution-attack` (Step 1): the duplicate-member precedence shapes (first-wins, last-wins, array, comma-concat) as the probe set for one member.
- `ObservableSignal` <- `claude-bug-hunter/hunt-http-smuggling` (Detection): the timing differential as the confirmation signal for a boundary disagreement, kept at mechanism level.
- `AttackTechnique` <- `anthropic/W2/bypassing-authentication-with-forced-browsing` (Step 4): an override member that restates the verb, so the gate reads the declared verb and the executor applies the override.
- `ObservableSignal` <- `awsome/.../deep-dive-labs/host-header` (Lab 3): the duplicate-member case where one reader keys on the first occurrence and another consumes the second.

**References/scripts candidates**:
- `claude-bug-hunter/security-arsenal` smuggling payload bank and `claude-bug-hunter/hunt-http-smuggling` vector matrix are bulky and concrete (product/front-end names). Not generalised to a body section; a de-productised desync probe set could live in `references/`. Low-medium confidence.

---

## defence-bypass-allowance-gap

**Sources matched**:
- `anthropic/W4/performing-content-security-policy-bypass` (Step 2 unsafe-inline/unsafe-eval, Step 3 whitelisted-JSONP and CDN library, Step 4 base-uri/form-action/object-src, Step 5 nonce leak via CSS attribute selectors, DOM clobbering, script gadgets, policy injection via a reflected directive).
- `hacking-skills/web/client-side/cors-misconfig` and `claude-bug-hunter/hunt-cors` and `anthropic/W4/testing-cors-misconfiguration` and `awsome/.../cors-misconfiguration-exploitation` (origin-permit reflection, null origin, prefix/suffix regex gap, missing `Vary`).
- `awsome/.../csrf-token-bypass-techniques` (token validated only if present, token not session-bound, double-submit cookie, Referer/Origin pattern-match weakness, SameSite method override).
- `awsome/.../logic-flaws/oauth-state-parameter-abuse` (a state parameter absent or not validated).

**Similarity**: sufficient for the CSP and CORS cases.
CSP is the leaf's Policy Allowance Gaps clause: the permit (the policy) enumerates sources, and every route to execution outside the list (JSONP on a whitelisted domain, base-uri hijack, script gadget, nonce leak) is the omission.
CORS is the same clause with the source list being trusted origins.
The leaf's Sanitiser Enumeration Gaps clause covers combinations of individually allowed elements.
Macro diff: CSP adds three concrete procedures (nonce leak via a CSS attribute-selector oracle, DOM clobbering to override a nonce, policy injection through a reflected directive) that generalise to "a permitted primitive combines into the withheld effect" and "the permit's own text is attacker-influenced".
CSRF-token bypass is a weaker fit (see Boundary).

**Boundary**: no bent step for CSP and CORS.
Both are permit-enumeration gaps and land on the leaf's Policy Allowance Gaps clause.
CSRF-token bypass is split: "token validated only if present" is a matcher gap (signature-evasion) and "token not session-bound" is a permit enumeration gap; my reading places the session-binding case here and the presence case in signature-evasion. Flagged as low confidence.
Grey point: CORS could be argued to own a bent step (a browser-side credentialed cross-origin read proof). If so it escalates; see Residual candidates.

**New-skill proposals**: none.

**Enrichment candidates**:
- `AttackTechnique` <- `anthropic/W4/performing-content-security-policy-bypass` (Step 5): leak a nonce through an attribute-selector oracle, and override a nonce through a markup-clobbering primitive, so the permit's own key becomes attacker-known.
- `AttackTechnique` <- `anthropic/W4/performing-content-security-policy-bypass` (Step 5, policy injection): the permit's directive text is attacker-influenced through a reflected value, so the permit admits a route it never listed.
- `AttackTechnique` <- `hacking-skills/web/client-side/cors-misconfig` (Bypass Techniques): a null-origin value and a prefix/suffix regex gap are routes the origin permit's list does not cover.
- `DefensiveControl` <- `anthropic/W4/performing-content-security-policy-bypass` (Step 1): a report-only permit is a restriction declared but not enforced, which the leaf's False Positives already name as a control gap rather than a bypass.
- `PayloadPattern` <- `awsome/.../csrf-token-bypass-techniques` (Phase 2): omitted, presence-only, and permissively-formatted token values as permit probes. Low confidence on placement (may belong to signature-evasion).

**References/scripts candidates**:
- `anthropic/W4/performing-content-security-policy-bypass` bypass list and `hacking-skills/web/client-side/cors-misconfig` PoC set are concrete but mechanism-level; a de-productised permit-probe table could live in `references/`. Medium confidence.

---

## defence-bypass-edge-origin-differential

**Sources matched**:
- `claude-bug-hunter/hunt-nextjs` (Phase 3: middleware auth bypass via a static-asset path prefix, `/_next/data/` bypass, and the subrequest-assertion header `x-middleware-subrequest` that makes the enforcing tier skip the request entirely; Phase 6: ISR cache poisoning).
- `anthropic/W2/bypassing-authentication-with-forced-browsing` (Step 3 unauthenticated-versus-authenticated comparison; Step 4 method-scoped enforcement; Step 5 path-normalisation and encoded-path bypass of a path-scoped rule).
- `claude-bug-hunter/hunt-host-header` (Phase 3B: `X-Original-URL`/`X-Rewrite-URL` override the routed path, reaching a route the edge ACL blocked).
- `awsome/.../deep-dive-labs/host-header` (Lab 2: `Host: localhost` reaches an auth-gated route).
- `anthropic/W5/performing-api-rate-limiting-bypass` (Step 3: version downgrade `/api/v1` versus `/api/v3` resets the rule) and `awsome/.../api-rate-limit-bypass-techniques` (Phase 4: deprecated endpoints).
- `claude-bug-hunter/hunt-api-misconfig` (verb tampering as a route that skips the method-scoped rule).

**Similarity**: sufficient.
Route divergence is exact: Next.js middleware matcher exclusions and forced-browsing path normalisation are both "a route to one effect that does not carry the current chain".
Scope divergence is exact: the front tier covers the path or the method while the serving tier applies the identity-bound rule.
Macro diff: the subrequest-assertion header is a distinct mechanism (the control is skipped when a header claims the request is internal), and the path-override field is a distinct route-suppression mechanism.

**Boundary**: no bent step.
The subrequest-assertion header is a route/chain divergence: the request is routed past the chain, which the leaf's Route and Chain Divergence clause covers.
The path-override field is the same clause.
Verdict-reuse (a stored verdict outliving its request) is the leaf's own clause; the cache-verdict case stays here, the cache-body case stays in `proxy-techniques-cache-deception`.
Verdict: stays a variant.

**New-skill proposals**: none.

**Enrichment candidates**:
- `AttackTechnique` <- `claude-bug-hunter/hunt-nextjs` (Phase 3, CVE-2025-29927): a transit header that asserts an internal subrequest makes the enforcing tier skip the chain, so the serving tier answers without the verdict.
- `AttackTechnique` <- `anthropic/W2/bypassing-authentication-with-forced-browsing` (Step 5): a path-normalisation or encoded-path form that the path-scoped rule does not match while the router still resolves it.
- `AttackTechnique` <- `anthropic/W2/bypassing-authentication-with-forced-browsing` (Step 4): a method-scoped rule is bypassed by a sibling verb that reaches the same handler.
- `AttackTechnique` <- `claude-bug-hunter/hunt-host-header` (Phase 3B): a path-override field reaches a route the enforcing tier denied.
- `ObservableSignal` <- `claude-bug-hunter/hunt-nextjs` (Phase 3): the enforcing tier's own marker is absent while the serving tier answers, which localises the tier gap.

**References/scripts candidates**: none bulky (all sources are inline probes).

---

## defence-bypass-throttle-evasion

**Sources matched**:
- `claude-bug-hunter/hunt-brute-force` (the four-state classifier: hard lockout, soft IP throttle, CAPTCHA injection, silent shadow-throttle; the shadow-throttle seed test; Phase 4 header/source rotation; window and code-lifetime arithmetic; concurrent burst).
- `anthropic/W5/performing-api-rate-limiting-bypass` (Step 2 header rotation, Step 3 path variation, Step 4 method/content-type switching, Step 5 identifier rotation and parameter pollution, Step 6 concurrent burst on a non-atomic counter).
- `awsome/.../api-rate-limit-bypass-techniques` (Phase 1 IP header spoofing, Phase 2 identifier folding by case/whitespace/null, Phase 3 array batching, Phase 4 version downgrade).
- `claude-bug-hunter/hunt-captcha-bypass` (Pattern 5: a throughput-gated challenge counts requests reaching the route, not outcomes; concurrency-window note; the gate is the only rate limit).
- `anthropic/W5/performing-graphql-depth-limit-attack` (alias amplification, batch query) and `awsome/.../graphql-batching-attacks` (one request carries many attempts).
- `awsome/.../websocket-hijacking-testing` (Phase 4) and `claude-bug-hunter/hunt-websocket` (Phase 3): a second carrier bypasses the per-request counter.

**Similarity**: sufficient, and the strongest of the group.
Counted-dimension gap is exact: the counter observes one dimension and the effect moves in another (identifier folding, path/version variation, carrier substitution).
Propagation/window gap is exact: a burst inside the counter's propagation gap or at a window edge.
Partial-limit gap is close: throttle without block.
Macro diff: three generalisable additions.

**Boundary**: no bent step for the additions I accept.
Per-request cost amplification (array/batch/alias) is the counted-dimension gap: the counter counts requests, the effect moves in attempts.
Carrier substitution that resets the counter is the counted-dimension gap plus the family's `channel-wrapping` cross-reference.
Identifier folding is the counted-dimension gap: the counter keys on the raw string, the backend resolves the folded value.
The silent shadow-throttle is the one genuine grey point: the leaf's Partial-Limit Gaps clause describes a limit that slows without blocking, but not a limit that returns an admit signal while the effect stops being produced.
My reading is that this is the same accounting clause (the limit's answer no longer reflects the effect), so it is an enrichment (an observable and a false-positive predicate), not a variant.
Flagged: if the shadow-throttle is judged to own a step the leaf cannot describe (a success-signal-versus-effect divergence), it escalates.

**New-skill proposals**: none.

**Enrichment candidates**:
- `ObservableSignal` <- `claude-bug-hunter/hunt-brute-force` (CRITICAL four-state table): classify the limit before concluding, because an admit status alone does not mean no limit; the four states are hard lockout, soft per-source throttle, injected challenge, and silent throttle.
- `ObservableSignal` <- `claude-bug-hunter/hunt-brute-force` (shadow-throttle detector): the limit returns an admit signal while the known-good effect stops being produced, which is the primary signal that the accounting dimension is unwatched in the admit direction.
- `AttackTechnique` <- `anthropic/W5/performing-graphql-depth-limit-attack` (alias amplification, batch query) plus `awsome/.../api-rate-limit-bypass-techniques` (Phase 3 array batching): one counted request carries many attempts, so the counter observes one while the effect moves many.
- `AttackTechnique` <- `awsome/.../api-rate-limit-bypass-techniques` (Phase 2): fold the identifier (case, whitespace, encoding) so the counter keys a new string while the backend resolves the same entity.
- `ObservableSignal` <- `claude-bug-hunter/hunt-brute-force` (Phase 4 confirmation): the delta between the rotated and the un-rotated run is the proof, not one fast run.

**References/scripts candidates**:
- `anthropic/W5/performing-api-rate-limiting-bypass` carries a generalisable async burst harness (a de-productised load/rotation script). Medium confidence as a `references/` scripted test.
- `anthropic/W5/performing-graphql-depth-limit-attack` carries a self-contained Python depth/alias tester; mechanism-level and generalisable. Medium confidence.

---

# Group `proxy-techniques`

## proxy-techniques (parent, umbrella)

**Sources matched**: all proxy-techniques leaves below; the strongest parent-level matches are `claude-bug-hunter/hunt-host-header`, `anthropic/W6/performing-web-cache-poisoning-attack`, `anthropic/W6/performing-web-cache-deception-attack`, `claude-bug-hunter/hunt-cache-poison`.

**Similarity**: coverage, not a diff.
The parent states one path model: a component resolves, forwards, redirects, caches, or re-presents, and each component trusts the one before it.
No source states this model as one abstraction; each source is component- or product-anchored.
The parent's six clauses (resolution, forwarding, parse, carrier, cache-key, relay-field) generalise the instances the leaves hold.

**Boundary**: umbrella, not a class.
The variant boundary lists this family as a non-class.

**New-skill proposals**: none at parent level.

**Enrichment candidates**:
- `AttackTechnique` <- `claude-bug-hunter/hunt-host-header` (Phase 3): separate routing-based effects from path-override effects, because the two act at different layers and never compose into one request; the parent should state the layering rule so a consumer does not conflate them.
- `AttackGoal` <- `anthropic/N3/conducting-man-in-the-middle-attack-simulation` (Key Concepts): interception and re-presentation is an `AttackGoal` the family serves, distinct from a single hop's destination.

**References/scripts candidates**: none generalisable at parent level.

---

## proxy-techniques-dns-rebinding

**Sources matched**:
- `claude-bug-hunter/hunt-ssrf` (DNS rebinding: validate-then-fetch TOCTOU, 0-TTL rotation, rebinding-service names, "win the race over 2-3 requests"; disclosed cases Concrete CMS, GitLab UrlBlocker, Azure DevOps endpointproxy).
- `awsome/.../ssrf-server-side-request-forgery` (rebinding-service name families).
- `anthropic/W6/performing-blind-ssrf-exploitation`, `anthropic/W6/exploiting-server-side-request-forgery`, `anthropic/W6/performing-ssrf-vulnerability-exploitation` (rebinding as a filter bypass).
- `anthropic/N3/conducting-man-in-the-middle-attack-simulation` and `awsome/.../network/ipv6-dns-takeover-mitm` (a rogue answer controls resolution).

**Similarity**: sufficient.
Lookup-count gap is exact: the check resolves once, the fetch re-resolves.
Record-lifetime control is exact: a short lifetime changes the answer between the two lookups.
Address-family answers is exact: the second answer points at a different reach.
Macro diff: the sources frame the mechanism as an SSRF-filter bypass and add the TOCTOU/race framing and 0-TTL rotation.

**Boundary**: no bent step.
The TOCTOU/race framing is the lookup-count gap: the gap between check and connect is the mechanism.
The SSRF-filter context is the consuming class's detail, which `ssrf` owns; the family owns the generic rebinding mechanic.
Verdict: stays a variant.

**New-skill proposals**: none.

**Enrichment candidates**:
- `AttackTechnique` <- `claude-bug-hunter/hunt-ssrf` (line ~362, ~420): rotate the answer across a validate-then-fetch TOCTOU, with a lifetime short enough to expire inside the lookup gap, repeated until the race is won.
- `PayloadPattern` <- `claude-bug-hunter/hunt-ssrf` (line ~365): the answer-name families a rebind is built from, kept as a pattern rather than a concrete service name.
- `ObservableSignal` <- `anthropic/N3/conducting-man-in-the-middle-attack-simulation` (Step 4): a second resolution served by operated infrastructure proves the connector used the second answer.

**References/scripts candidates**: none bulky.

---

## proxy-techniques-redirect-chain

**Sources matched**:
- `anthropic/W6/testing-for-open-redirect-vulnerabilities` (Step 3 validation bypasses, Step 4 parameter pollution for the destination, Step 5 chaining with OAuth token theft and SSRF-filter bypass and XSS).
- `awsome/.../open-redirect-chaining-attacks` (Phase 2 filter bypass; Phase 3 escalation: OAuth `redirect_uri`, SSRF-filter bypass because the fetch follows the hop, `javascript:` for XSS).
- `claude-bug-hunter/hunt-open-redirect`, `hacking-skills/web/client-side/open-redirect` (redirect chains, `fetch()` follows the hop).

**Similarity**: sufficient.
Hop-approval gap is exact: the check runs before the follow, so the approved first destination forwards onward.
Nested and chained hops is exact.
Scheme and family switching at a hop is exact.
Macro diff: the sources add the escalation targets and the fact that the approved hop can be the destination-check's own trusted value (the OAuth `redirect_uri` case) or can cross a downstream destination filter (the SSRF-filter case).

**Boundary**: no bent step.
The escalation cases are the leaf's Chaining Attacks: hand the arrival to the class that owns the effect.
The "approved hop is the destination-check's own trusted value" is the hop-approval gap.
Verdict: stays a variant.

**New-skill proposals**: none.

**Enrichment candidates**:
- `AttackTechnique` <- `awsome/.../open-redirect-chaining-attacks` (Escalation 1): place the approved redirect endpoint as the destination-check's own trusted value, so the approval covers the hop and the arrival is elsewhere.
- `AttackTechnique` <- `awsome/.../open-redirect-chaining-attacks` (Escalation 2): a fetch-capable consumer follows the approved hop past its own destination filter, because the filter cleared the first destination.
- `PayloadPattern` <- `anthropic/W6/testing-for-open-redirect-vulnerabilities` (Step 2, Step 3): the hop shapes (userinfo `@`, backslash, protocol-relative, mixed-case scheme, null byte, encoding) as the destination-value probe set.
- `AttackTechnique` <- `anthropic/W6/testing-for-open-redirect-vulnerabilities` (Step 4): a duplicate destination member where each hop resolves precedence for itself.
- `AttackTechnique` <- `anthropic/W6/testing-for-open-redirect-vulnerabilities` (Bypass Techniques, line ~79): a post-action or logout continuation whose rule is weaker than the primary check.

**References/scripts candidates**: none bulky.

---

## proxy-techniques-url-parser-differential

**Sources matched**:
- `anthropic/W6/testing-for-open-redirect-vulnerabilities` (Key Concepts "URL Parsing Inconsistency"; userinfo, backslash, protocol-relative, fragment, case).
- `hacking-skills/web/client-side/cspt` (a path-concatenated value completed against the consumer's own base; the reader inventory).
- `anthropic/W6/performing-web-cache-deception-attack` (Step 3/4: delimiter and normalisation discrepancies: `;`, `%2f`, `%3b`, `%00`, `#`, dot-segments, double-encoded).
- `awsome/.../deep-dive-labs/cache-deception` (Labs 2-4: path delimiters, origin-versus-cache normalisation).
- `anthropic/W2/bypassing-authentication-with-forced-browsing` (Step 5: encoded-path forms).
- `anthropic/W9/performing-http-parameter-pollution-attack` (duplicate destination member precedence).
- `awsome/.../ssrf-server-side-request-forgery` (numeric/octal/short-form address notation).

**Similarity**: sufficient.
Authority-boundary gap is exact: userinfo, separator substitutes, mixed slashes, control/whitespace characters.
Duplicate destination precedence is exact.
Notation and relative folding is exact: trailing dots, case, width variants, numeric address forms, encoded separators, relative values completed against the consumer's base.
Macro diff: the sources add the concrete delimiter set and the numeric-address notation family.

**Boundary**: no bent step.
The cache-versus-origin path normalisation is the same authority/parse disagreement; the cache-key consequence belongs to `proxy-techniques-cache-deception`, and the value parse belongs here, which the leaf already states.
Verdict: stays a variant.

**New-skill proposals**: none.

**Enrichment candidates**:
- `AttackTechnique` <- `hacking-skills/web/client-side/cspt` (Methodology, step 6): complete a relative or path-concatenated value against the consumer's own base, so the approver and the consumer derive different targets.
- `PayloadPattern` <- `awsome/.../ssrf-server-side-request-forgery` (lines ~127-134): numeric, octal, short-form, and encoded-dot address notation that one reader resolves to the approver's value and the other to a different reach.
- `PayloadPattern` <- `anthropic/W6/performing-web-cache-deception-attack` (Step 3): the delimiter and encoded-path families (`;`, `%2f`, `%3b`, `%00`, `#`, dot-segments, trailing dot, case) as the per-element probe set.

**References/scripts candidates**:
- `awsome/.../deep-dive-labs/cache-deception` and `awsome/.../deep-dive-labs/host-header` are compact lab playbooks; the delimiter/normalisation lab list generalises to a reference table. Medium confidence.

---

## proxy-techniques-channel-wrapping

**Sources matched**:
- `claude-bug-hunter/hunt-websocket` (Phase 2 CSWSH: a cookie-authenticated second channel with no per-connection token and no Origin enforcement; Phase 3 signed-message replay across sessions/time windows; Phase 5 namespace/room authz; Phase 6 handshake-Upgrade smuggling).
- `awsome/.../websocket-hijacking-testing` (Phase 2 CSWSH; Phase 3 message tampering; Phase 4: the socket carrier bypasses the per-request WAF and rate accounting).
- `anthropic/W5/exploiting-websocket-vulnerabilities`, `anthropic/W5/testing-websocket-api-security` (handshake auth, per-message auth, Origin).
- `anthropic/W5/performing-api-rate-limiting-bypass` (Step 4: method and content-type switching as a carrier with a weaker check) and `awsome/.../api-rate-limit-bypass-techniques` (Phase 4: a mobile subdomain as a second carrier).
- `anthropic/W9/performing-http-parameter-pollution-attack` (Step 4: duplicate forwarding header as a second carrier).

**Similarity**: sufficient.
Carrier substitution is exact: a sibling content type, verb, transport, endpoint, session, or device reaches the same operation.
Guard parity gap is exact: the sibling carrier carries a weaker check (the socket's handshake lacks the per-request CSRF/Origin guard).
Second-channel replay is exact: a captured request re-presented on a channel where the identity binding is carrier-specific.
Macro diff: the sources add the persistent full-duplex carrier and the signed-message replay-across-sessions case.

**Boundary**: no bent step.
The persistent socket is a carrier whose guard differs from the HTTP carrier's, which is carrier substitution plus guard parity.
Signed-message replay across sessions is the second-channel replay clause (the binding is not carried).
Message-level authorization and tampering are a distinct class concern, not a carrier mechanism; see Residual candidates for WebSocket.
Verdict: stays a variant.

**New-skill proposals**: none.

**Enrichment candidates**:
- `AttackTechnique` <- `claude-bug-hunter/hunt-websocket` (Phase 3, signed-message replay): replay a captured signed message across a time window and across a second session where the signature is not bound to the principal or the freshness window.
- `AttackTechnique` <- `awsome/.../websocket-hijacking-testing` (Phase 4): a persistent socket carrier bypasses both the per-request carrier's guard and its rate accounting, because the inspecting component watches requests, not the socket.
- `ObservableSignal` <- `claude-bug-hunter/hunt-websocket` (Phase 2 false-positive killers): the second carrier returns another principal's data while the primary carrier stays refused, which is the primary wrap signal.
- `AttackTechnique` <- `claude-bug-hunter/hunt-websocket` (Phase 6): a handshake that the front tier and the origin read differently opens a carrier the front tier stops parsing, which is carrier substitution at the upgrade boundary.

**References/scripts candidates**:
- The CSWSH PoC HTML in `claude-bug-hunter/hunt-websocket` (Phase 2) is mechanism-level and generalisable as a `references/` scripted test. Medium confidence.

---

## proxy-techniques-cache-deception

**Sources matched**:
- `anthropic/W6/performing-web-cache-deception-attack` (Step 2 extension trick, Step 3 delimiters, Step 4 normalisation, Step 5 key manipulation, Step 6 two-caller verification).
- `awsome/.../web-cache-poisoning-deception` (unkeyed inputs and WCD; the `.css` path-append case).
- `claude-bug-hunter/hunt-cache-poison` (unkeyed-header reflection, WCD path appending, cache-key components, TTL, second-client proof, the extension-allowlist gap `.avif`, error-response caching for DoS, the Origin-to-ACAO cached case).
- `anthropic/W6/performing-web-cache-poisoning-attack` (Step 2 unkeyed headers, Step 3 poisoning, Step 5 parameter cloaking and fat GET, cache-key normalisation).
- `awsome/.../deep-dive-labs/cache-deception` (Labs 1-5) and `awsome/.../deep-dive-labs/web-cache-poisoning` (Labs 1-8: unkeyed header, unkeyed cookie, unkeyed query string, unkeyed parameter, parameter cloaking, fat GET).
- `claude-bug-hunter/hunt-host-header` (Phase 2: a forwarded host reflected into a cached response) and `claude-bug-hunter/hunt-cors` (an Origin value cached into the allow-origin header).

**Similarity**: sufficient, and the strongest of the group.
Unkeyed input to a keyed response is exact: a selector shapes the body while the key omits it.
Key normalisation and fragmentation is exact: separators, casing, suffixes, address tails that collapse or change an entry.
Stored-response reads across callers is exact: an entry outlives the session that produced it.
Macro diff: the sources add parameter cloaking, fat GET, unkeyed cookies, and the extension-allowlist gap.

**Boundary**: no bent step for the accepted additions.
Parameter cloaking and fat GET are the unkeyed-input clause (a selector the parser reads and the key omits).
The unkeyed cookie is the same clause.
The extension-allowlist gap is key normalisation/fragmentation (a suffix that changes storage eligibility or reach).
Grey point: cache poisoning (attacker content served to all) versus cache deception (victim content read by the attacker) differ in who reads the entry, not in the steps; the leaf's step "read as a second caller" covers both directions, so both stay aspects. Flagged for the synthesis, because a reader could argue poisoning owns a bent step (mass delivery).
Verdict: stays a variant, with the poisoning direction carried as an aspect.

**New-skill proposals**: none.

**Enrichment candidates**:
- `AttackTechnique` <- `awsome/.../deep-dive-labs/web-cache-poisoning` (Lab 7, Lab 8): parameter cloaking, where the parser reads a later duplicate the key omits, and a fat GET whose body parameters the key ignores.
- `AttackTechnique` <- `claude-bug-hunter/hunt-cache-poison` (Bypass Techniques, extension list): a static suffix the key's allowlist omits changes storage eligibility for a dynamic response.
- `AttackTechnique` <- `claude-bug-hunter/hunt-cache-poison` (Step 3, cache-buster discipline): land the probe on a throwaway key first, so a live entry is not poisoned before the mechanism is proven.
- `AttackTechnique` <- `claude-bug-hunter/hunt-cache-poison` (Step 5): a response that carries an error class is stored, so a later caller reaches a failed response for a healthy request.
- `ObservableSignal` <- `claude-bug-hunter/hunt-cache-poison` (Step 8, Step 7): the storage window from the entry's lifetime, and the second-client read, are the reach proof.
- `AttackTechnique` <- `claude-bug-hunter/hunt-cors` (line ~210): a cached allow-origin value produced for a shaping origin reaches later callers, which is the unkeyed-input clause on a header selector.

**References/scripts candidates**:
- `awsome/.../deep-dive-labs/web-cache-poisoning` and `awsome/.../deep-dive-labs/cache-deception` lab playbooks, and the unkeyed-header wordlist in `claude-bug-hunter/hunt-cache-poison` (line ~193), are bulky and generalisable to a `references/` probe set. Medium confidence.

---

## proxy-techniques-relay-forwarding

**Sources matched**:
- `claude-bug-hunter/hunt-host-header` (field-family list; Phase 1 reset-link construction; Phase 3A routing-based SSRF; Phase 3B path override; Phase 4 OIDC issuer and discovery poisoning; trailing-port/userinfo forms).
- `anthropic/W6/testing-for-host-header-injection` (Step 1 field families and port/userinfo injection, Step 2 reset poisoning, Step 3 cache poisoning, Step 4 routing SSRF, Step 5 virtual-host routing).
- `awsome/.../host-header-injection-attacks`, `awsome/.../deep-dive-labs/host-header` (lab payloads).
- `anthropic/W6/performing-web-cache-poisoning-attack` (Step 2/3: `X-Forwarded-Host`, `X-Forwarded-Proto`, `X-Original-URL` reflected into construction).
- `claude-bug-hunter/hunt-nodejs` (Phase 4: a framework trust-proxy setting makes the client-address field reach an allowlist or rate decision).
- `anthropic/N3/conducting-man-in-the-middle-attack-simulation` (a transparent proxy re-presents the request with its own view).

**Similarity**: sufficient, and the strongest of the group.
Forwarded-value trust is exact: a supplied authority, client address, or scheme is read where the origin should read its own observation.
Field-family spraying is exact: the same value under every name a layer might read.
Relay rewrite and override is exact: an override reaches a decision made before the rewrite.
Macro diff: the sources add the construction-decision targets (reset link, canonical/og:url, OIDC issuer/discovery) and the framework trust-proxy precondition.

**Boundary**: no bent step.
The construction-decision targets are the leaf's "a decision the supplied value reaches".
The trust-proxy precondition is the leaf's forwarded-value clause reaching an allowlist/rate decision.
Verdict: stays a variant.

**New-skill proposals**: none.

**Enrichment candidates**:
- `AttackTechnique` <- `claude-bug-hunter/hunt-host-header` (Phase 1, Phase 4): the supplied value reaches a construction decision (a reset link, a canonical or share URL, an issuer or discovery document), so the effect is a link or document the origin built.
- `AttackTechnique` <- `claude-bug-hunter/hunt-nodejs` (Phase 4): a framework setting that trusts the forwarded client-address makes that field reach an allowlist or a rate decision, so the decision is made on an observation the caller authored.
- `AttackTechnique` <- `anthropic/W6/testing-for-host-header-injection` (Step 1): trailing-port and userinfo forms split the value on one reader and resolve to the approved host on another.
- `ObservableSignal` <- `claude-bug-hunter/hunt-host-header` (Phase 3A blind case): an out-of-band fetch of the injected host proves the origin resolved the supplied value even when the response reflects nothing.

**References/scripts candidates**:
- The field-family wordlist and header-fuzzing loop in `claude-bug-hunter/hunt-host-header` (Phase 5) are compact and generalisable to a `references/` probe set. Medium confidence.

---

# Residual candidates

These are source materials whose mechanism is adjacent to this slice and which have **no adequate home** in the current suite.
They are reported for the synthesis; none is proposed as a suite edit here.

1. **CORS misconfiguration as a class or as a new `allowance-gap` variant** (medium confidence).
   Sources: `hacking-skills/web/client-side/cors-misconfig`, `claude-bug-hunter/hunt-cors`, `anthropic/W4/testing-cors-misconfiguration`, `awsome/.../cors-misconfiguration-exploitation`.
   The suite has no CORS skill.
   The mechanism (a permit enumerates trusted origins; reflection, null origin, and prefix/suffix regex are routes the list omits) fits `defence-bypass-allowance-gap`.
   The candidate bent step is "prove a credentialed cross-origin read from a browser", which the allowance-gap variant does not describe.
   If that step is real, CORS is a new class or a new allowance-gap variant; if it is an aspect, it is an enrichment (already listed under `allowance-gap`).

2. **Web cache poisoning as a class** (medium confidence).
   Sources: `anthropic/W6/performing-web-cache-poisoning-attack`, `awsome/.../web-cache-poisoning-deception`, `awsome/.../deep-dive-labs/web-cache-poisoning`, `claude-bug-hunter/hunt-cache-poison`.
   The suite has no cache class.
   The mechanism (an unkeyed selector stores attacker content that later callers receive) fits `proxy-techniques-cache-deception` as an aspect (already listed).
   The candidate bent step is mass delivery: the stored body is served to every later caller rather than read by one attacker.
   If that step is real, poisoning is a class that consumes the cache-key variant; if not, it stays an aspect of `cache-deception`.

3. **WebSocket security as a class** (medium confidence).
   Sources: `claude-bug-hunter/hunt-websocket`, `awsome/.../websocket-hijacking-testing`, `anthropic/W5/exploiting-websocket-vulnerabilities`, `anthropic/W5/testing-websocket-api-security`.
   The suite has no WebSocket skill.
   The carrier mechanism (a persistent second channel whose guard differs) fits `proxy-techniques-channel-wrapping` (already listed).
   The candidate bent steps are message-level authorization and signed-message replay, which are not carrier steps.
   If those steps are real, WebSocket is a class that consumes the carrier variant.

4. **Type juggling / loose-comparison coercion** (low-medium confidence).
   Source: `anthropic/W1/exploiting-type-juggling-vulnerabilities`.
   No home in the suite.
   The folding mechanism fits `defence-bypass-encoding-differential` (already listed).
   The candidate bent step is a language-semantics comparison step rather than a decode step; the other candidate homes are `crypto-weakness` (a comparison weakness) or `authentication-jwt` (a token-verification bypass).

5. **CAPTCHA bypass** (low-medium confidence).
   Source: `claude-bug-hunter/hunt-captcha-bypass`.
   No home.
   The gate-removal and token-replay mechanisms fit `defence-bypass-throttle-evasion` and `weak-credential-discovery`.
   The candidate bent step is "the gate is client-side-only or not bound to the action", which is closer to `allowance-gap` than to `throttle-evasion`.

6. **Clickjacking / UI redressing** (low confidence, outside this slice's mechanism scope).
   Sources: `claude-bug-hunter/hunt-clickjacking`, `anthropic/W4/performing-clickjacking-attack-test`, `awsome/.../clickjacking-ui-redressing`.
   No home; no defence-bypass or proxy mechanism (the control is a framing directive, not a matcher, decode, tier, enumeration, or count).
   Reported only so the synthesis does not read its absence as an oversight.

7. **postMessage origin-check weakness** (low confidence).
   Sources: `claude-bug-hunter/hunt-dom`, `claude-bug-hunter/hunt-cors` (postMessage mention).
   No home.
   The mechanism (a message channel whose origin check is missing or loose) is a candidate new `channel-wrapping` carrier, or a client-side class.

8. **Network-layer interception and transport downgrade** (out of suite scope; reported for completeness).
   Sources: `anthropic/N3/conducting-man-in-the-middle-attack-simulation`, `anthropic/W7/performing-ssl-stripping-attack`, `awsome/.../network/ipv6-dns-takeover-mitm`, `awsome/.../network/ntlm-relay-smb-signing-bypass`, `awsome/.../network/bgp-hijacking-concepts`, `awsome/.../network/smtp-open-relay-abuse`.
   The suite is web-application scoped (see `skills-unspurious/INVENTORY.md`, the discard rule: network-based bypass and proxy techniques are kept only where they are web-relevant).
   The scheme-switch hop is already `proxy-techniques-redirect-chain`; the rest is out of scope.
   No proposal.

9. **HSTS and security-headers audit** (out of family).
   Source: `anthropic/W4/performing-security-headers-audit`, `claude-bug-hunter/hunt-tls-network`.
   Not a bypass or proxy mechanism; no home; no proposal.

**Not residual (adequate home exists)**:
- HTTP parameter pollution -> `defence-bypass-parser-confusion` (enrichment listed).
- HTTP request smuggling -> the suite class `http-request-smuggling` owns the desync procedure; this family names it.
- Host header injection -> the suite class `header-injection`; this family owns the relay-field mechanism.
- Open redirect -> the suite class `open-redirect`; this family owns the hop-carry mechanism.
- Forced browsing and content discovery -> `information-disclosure` and `broken-function-level-authorization`.
- GraphQL depth and batching -> the suite class `graphql`; the amplification is a `throttle-evasion` enrichment.
- DNS rebinding -> `proxy-techniques-dns-rebinding` (enrichment listed).
- Rate limiting and brute force -> the suite class `weak-credential-discovery`; the bypass is `throttle-evasion`.

---

# Slice summary

- **Parents**: both are umbrellas, not class axes; no proposals at parent level; one parent-level enrichment each (`defence-bypass`: the control-kind ordering and front-end fingerprint; `proxy-techniques`: the routing-versus-path-override layering rule).
- **Leaves**: all 12 reach sufficient similarity to at least one source; **no leaf needs a new skill**, and **no leaf is over-split**.
- **New-skill proposals from per-leaf matching**: none.
- **Strongest matches** (high confidence): `throttle-evasion` (four-state classifier and per-request amplification), `cache-deception` (unkeyed input, cloaking, fat GET), `relay-forwarding` (field families and construction decisions), `allowance-gap` (CSP permit enumeration), `channel-wrapping` (socket carrier and signed-message replay).
- **Weakest matches** (flagged): `signature-evasion` (the sources are concrete payload banks; little abstract residue), `edge-origin-differential` (the sources are product-anchored, though the mechanism matches).
- **Grey points for the synthesis**:
  1. `throttle-evasion`: is the silent shadow-throttle (an admit signal while the effect stops) an aspect or a variant?
  2. `cache-deception`: is cache poisoning (mass delivery) an aspect or a class?
  3. `allowance-gap`: is CORS a permit aspect or a class?
  4. `encoding-differential`: is comparison coercion an aspect or a distinct step?
  5. `parser-confusion`: CSRF-token presence-only validation sits between `signature-evasion` and `allowance-gap`.
- **Residual candidates** (dedicated section): CORS, cache poisoning, WebSocket, type juggling, CAPTCHA bypass, clickjacking, postMessage; plus the out-of-scope network set.
- **References/scripts candidates**: the most generalisable are the cache lab playbooks, the unkeyed-header wordlist, the CSWSH PoC, the rate-limit burst harness, and the GraphQL depth/alias tester; all other payload banks are concrete and should not enter a body section.
- **Confidence**: per-leaf similarity and boundary verdicts are high confidence except where flagged; the residual candidates are low-to-medium and are offered for the synthesis to rule on.
