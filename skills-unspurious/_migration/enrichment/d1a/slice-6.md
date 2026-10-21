# D1a enrichment proposal, slice 6: `defence-bypass` and `proxy-techniques`

Status: REPORT ONLY, D1a, work item W7 C4-full enrichment.
This slice owns the two technique families under `skills-unspurious/`: `defence-bypass` and `proxy-techniques`, each a level-1 family parent plus its six level-2 technique leaves.
Base revision: branch `feat/w7-enrichment`.
Sources (read-only): `hacking-skills/skills`, `claude-bug-hunter/skills`, `anthropic-cybersecurity-skills` (skills under `accepted/`), `awsome-offensive-security-skill/skills`.
Normative authorities applied: `docs/design/skills-variant-boundary.md` and `docs/design/skills-ontology.md`.
The algorithm was applied literally, per base skill, in the order: index the sources, match by mechanism or by chainable technique, assess similarity, apply the boundary when similarity is insufficient, run the macro semantic content diff when it is sufficient, abstract to ontology entities, escalate a multi-entity diff that touches a boundary attribute to a new-skill proposal, then assess references and scripts.
No suite skill was modified and no git command was run.

## Slice header

- Groups: 2 (`defence-bypass`, `proxy-techniques`).
- Base skills: 14 (2 family parents plus 12 technique leaves).
- Source skill files indexed: 364 markdown skill bodies across the four repos (43 + 85 + 96 + 140).
- Source skill files read in full for this slice: 30.
- Similarity verdicts: 12 sufficient, 2 mixed (sufficient with low-confidence tail).
- New-skill proposals: 4 (1 family leaf, 3 cross-slice class candidates flagged as out of family scope).
- Enrichment candidates (ontology-entity abstractions): 38.
- References/scripts candidates: 12.

---

# Group `defence-bypass`

The parent is an umbrella, not a class. Its six leaves own the six control-agnostic mechanisms: matcher gap, decode disagreement, structural re-reading, permit enumeration, tier gap, and accounting gap.
The family attracts generic control-bypass material across all four sources, and the strongest matches are the WAF-bypass, HTTP-parameter-pollution, CSP-bypass, rate-limit-bypass, cache, host-header, and HTTP-smuggling skills.

## defence-bypass

**Sources matched**
- `anthropic-cybersecurity-skills/accepted/W9/performing-web-application-firewall-bypass/SKILL.md` - the control-agnostic WAF-bypass methodology: fingerprint the control, then encoding, method, splitting, and rule-specific bypass, plus a signature/behavioural/encoding/protocol/parameter-pollution concept table.
- `claude-bug-hunter/skills/security-arsenal/SKILL.md` - the generalised bypass tables (SQLi/XSS/path-traversal WAF bypass, command-injection keyword-filter bypass) and the "WAF evaluation order matters" operator note.
- `anthropic-cybersecurity-skills/accepted/W6/exploiting-http-request-smuggling/SKILL.md` - the front-end-versus-back-end disagreement class used as the family's structural-re-reading and tier-gap exemplar.
- `claude-bug-hunter/skills/hunt-cache-poison/SKILL.md` - the unkeyed-header/WAF-stripping bypass list, a generalised control-bypass surface.

**Similarity**: sufficient. The parent already names the matcher, pipeline, reader, permit, tier, and accounting mechanisms, so the sources are consumed by the existing leaves rather than by the parent.

**Boundary**: none. The parent is a family, and the boundary document states explicitly that `defence-bypass` is a family and not a class axis, so no boundary attribute is in play.

**New-skill proposals**
- None. The parent is well-formed and no source diff adds a seventh mechanism that the six leaves cannot hold.

**Enrichment candidates**
- `AttackTechnique` <- `anthropic-cybersecurity-skills/accepted/W9/performing-web-application-firewall-bypass/SKILL.md`: a mechanism-selection order for the "Select the mechanism" step, namely control fingerprint, then encoding, then protocol, then parser quirk, then rule-specific gap, because the parent currently selects the mechanism from the control's kind alone.
- `DefensiveControl` <- `claude-bug-hunter/skills/security-arsenal/SKILL.md`: the "WAF evaluation order matters" ordering (encoding tricks, then parser quirks, then protocol-level, then vendor-rule-specific), a generalised bypass-attempt sequence the parent's `## Bypass Techniques` lacks.
- `ObservableSignal` <- `anthropic-cybersecurity-skills/accepted/W9/performing-web-application-firewall-bypass/SKILL.md`: the control's own vendor marker in its denial signal (`cf-ray`, `x-amzn-requestid`, `AkamaiGHost`, `incap_ses`), which fingerprints the control kind before crafting.
- `Artifact` <- `anthropic-cybersecurity-skills/accepted/W9/performing-web-application-firewall-bypass/SKILL.md`: a successful bypass payload recorded against the refused original, a reusable proof pair the parent's attribution step can name.

**References/scripts candidates**
- `references/control-bypass-evaluation-order.md` <- `claude-bug-hunter/skills/security-arsenal/SKILL.md` plus `anthropic-cybersecurity-skills/accepted/W9/performing-web-application-firewall-bypass/SKILL.md`: the generalised bypass-ordering heuristic and the vendor-control families are bulky, product-neutral, and reusable across every leaf, so they belong outside the parent body.

## defence-bypass-signature-evasion

**Sources matched**
- `anthropic-cybersecurity-skills/accepted/W9/performing-web-application-firewall-bypass/SKILL.md` - the matcher-gap family: mixed case, inline and version comments, tab/newline substitution, alternative HTML tags and event handlers, and SQLMap tamper scripts.
- `claude-bug-hunter/skills/security-arsenal/SKILL.md` - keyword-filter bypass by quote obfuscation (`c'a't`, `$(printf ...)`), SQLi comment/case encoding, and the WAF evaluation order.
- `anthropic-cybersecurity-skills/accepted/W9/performing-http-parameter-pollution-attack/SKILL.md` - payload splitting across duplicate parameters, a token split across request positions the sink rejoins.
- `claude-bug-hunter/skills/hunt-api-misconfig/SKILL.md` - OData operator obfuscation (mixed-case operators, URL-encoded and double-encoded `$`, obscure sibling operators) as a literal-token matcher gap.
- `awsome-offensive-security-skill/skills/bug-hunting/web-vulnerabilities/csrf-token-bypass-techniques/SKILL.md` - token-format and token-length tampering that a presence/shape check admits (low confidence, CSRF class detail).
- `hacking-skills/skills/web/client-side/cspt/SKILL.md` - the WAF encoding-level matrix, which includes padding with dummy segments to keep a depth check non-negative while the app depth goes negative.

**Similarity**: sufficient. The leaf's three sub-mechanisms (token-boundary, separator/whitespace, equivalent-operator/alias) cover the sources' matcher-gap families.

**Boundary**: none. The control kind is the same (a matcher over a value), so no boundary attribute (vuln-specific reconnaissance, surface part family, communication protocol, trust-assumption difference, impact) diverges.

**New-skill proposals**
- None.

**Enrichment candidates**
- `AttackTechnique` <- `claude-bug-hunter/skills/hunt-api-misconfig/SKILL.md`: a query-language operator obfuscation procedure (mixed case, encoded metacharacter, obscure sibling operator) where the sink normalises the operator before evaluation, extending "Equivalent Operator and Alias Gaps" beyond a fixed command grammar.
- `PayloadPattern` <- `claude-bug-hunter/skills/security-arsenal/SKILL.md`: the quote-insertion keyword-splitting family (`c'a't`, `c"a"t`, `$(printf '\x63\x61\x74')`) as a reassembly pattern, because the leaf names token splitting but not the quote-insertion spelling.
- `AttackTechnique` <- `hacking-skills/skills/web/client-side/cspt/SKILL.md`: the "pad with dummy segments so the matcher's depth stays non-negative while the app depth goes negative" procedure, a matcher-gap technique for a depth-counting rule.
- `AttackTechnique` <- `anthropic-cybersecurity-skills/accepted/W9/performing-web-application-firewall-bypass/SKILL.md`: an alternative event-handler and tag-name enumeration over a DOM grammar as an alias family (low confidence, borders on the `xss` class detail).
- `ObservableSignal` <- `claude-bug-hunter/skills/security-arsenal/SKILL.md`: a rule that grows between attempts (a second spelling refused after the first passed) as the signal that the rule set is being extended, which the leaf's false-positive list already names and the detection channels should carry.

**References/scripts candidates**
- `references/matcher-axis-matrix.md` <- `anthropic-cybersecurity-skills/accepted/W9/performing-web-application-firewall-bypass/SKILL.md`, `hacking-skills/skills/web/client-side/cspt/SKILL.md`, `claude-bug-hunter/skills/security-arsenal/SKILL.md`: the axis list (casing, separators, whitespace, comments, token boundaries, operators, encoding layers) is generalised across control kinds and is a reusable table.
- `scripts/axis-probe.sh` <- `anthropic-cybersecurity-skills/accepted/W9/performing-web-application-firewall-bypass/SKILL.md`: the one-axis-per-attempt probe loop is a generalised scripted test that fits the leaf's testing methodology.

## defence-bypass-encoding-differential

**Sources matched**
- `anthropic-cybersecurity-skills/accepted/W9/performing-web-application-firewall-bypass/SKILL.md` - single/double/Unicode/HTML-entity encoding, null bytes, tab and newline substitution, and the `charset` parameter switch.
- `hacking-skills/skills/web/client-side/cspt/SKILL.md` - the WAF encoding-level matrix with explicit depth reasoning: equal-level encode, over-encode the slash, pad to keep the matcher's depth non-negative.
- `claude-bug-hunter/skills/security-arsenal/SKILL.md` - the WAF evaluation order's encoding step and the SSRF address-notation bypass family (decimal, octal, hex, short form, IPv4-mapped IPv6).
- `claude-bug-hunter/skills/hunt-api-misconfig/SKILL.md` - the double-encoded OData operator (`%2524filter`) as a decode-count gap on one value.
- `anthropic-cybersecurity-skills/accepted/W6/performing-web-cache-deception-attack/SKILL.md` - double-encoded path segments and dot-segment normalisation as decode/fold differentials between two readers.

**Similarity**: sufficient. The leaf's decode-count, folding/normalisation, and overlong/truncation sub-mechanisms cover the sources.

**Boundary**: none. The control kind is a decoding/normalising comparison, and no boundary attribute diverges.

**New-skill proposals**
- None.

**Enrichment candidates**
- `AttackTechnique` <- `claude-bug-hunter/skills/security-arsenal/SKILL.md`: an address-notation folding family (decimal, octal, hex, IPv4-mapped IPv6, short form, trailing dot) as a value family where one side folds the notation and the other does not, extending the leaf's case/width/normalisation equivalents.
- `AttackTechnique` <- `hacking-skills/skills/web/client-side/cspt/SKILL.md`: depth-relative encoding selection (equal-level, over-encode, pad-to-depth) where the checking side itself has a decode depth, refining the leaf's decode-count procedure.
- `PayloadPattern` <- `anthropic-cybersecurity-skills/accepted/W9/performing-web-application-firewall-bypass/SKILL.md`: the declared-charset differential (`charset=ibm037`) as a carrier that makes the checking side read a different byte string than the sink (low confidence, borderline carrier substitution).
- `ObservableSignal` <- `anthropic-cybersecurity-skills/accepted/W9/performing-web-application-firewall-bypass/SKILL.md`: the control's own normalisation-before-rule-evaluation behaviour as the observable that localises the decode step where the two readings diverge.

**References/scripts candidates**
- `references/encoding-layer-matrix.md` <- `hacking-skills/skills/web/client-side/cspt/SKILL.md`, `anthropic-cybersecurity-skills/accepted/W9/performing-web-application-firewall-bypass/SKILL.md`, `claude-bug-hunter/skills/security-arsenal/SKILL.md`: the encode-depth and notation-equivalence tables are generalised, bulky, and reusable.
- `scripts/decode-count-probe.sh` <- `hacking-skills/skills/web/client-side/cspt/SKILL.md`: the layer-one-step-at-a-time probe with a depth guard is a generalised scripted test.

## defence-bypass-parser-confusion

**Sources matched**
- `anthropic-cybersecurity-skills/accepted/W6/exploiting-http-request-smuggling/SKILL.md` - CL/TE framing reading, H2.CL/H2.TE downgrade, and front-end-versus-back-end member disagreement.
- `claude-bug-hunter/skills/hunt-http-smuggling/SKILL.md` - the CL.TE/TE.CL/H2.CL/H2.TE matrix plus a front-end fingerprint matrix that maps which tier reads which framing.
- `hacking-skills/skills/web/injection/http-request-smuggling/SKILL.md` and `awsome-offensive-security-skill/skills/bug-hunting/web-vulnerabilities/http-request-smuggling-desync/SKILL.md` - TE.TE framing obfuscation (space before colon, tab, line folding, mixed case, duplicate TE headers).
- `anthropic-cybersecurity-skills/accepted/W9/performing-http-parameter-pollution-attack/SKILL.md` - the duplicate-parameter precedence matrix (first, last, array, concatenated per stack).
- `anthropic-cybersecurity-skills/accepted/W2/bypassing-authentication-with-forced-browsing/SKILL.md` - verb and location re-reading through `X-HTTP-Method-Override`, `X-Original-Method`, and `X-Rewrite-URL`.
- `claude-bug-hunter/skills/hunt-api-misconfig/SKILL.md` - HTTP verb tampering and the method override member.
- `awsome-offensive-security-skill/skills/bug-hunting/web-vulnerabilities/csrf-token-bypass-techniques/SKILL.md` - method change and method override to skip a POST-only token check.
- `claude-bug-hunter/skills/hunt-cache-poison/SKILL.md` - the GitLab case where `X-HTTP-Method-Override: HEAD` stored an empty body under the canonical GET key.

**Similarity**: sufficient. The leaf's duplicate-member, representation/framing, and verb/location sub-mechanisms cover the sources.

**Boundary**: none. The control kind is "two readers of one request disagree", and no boundary attribute diverges.

**New-skill proposals**
- None.

**Enrichment candidates**
- `AttackTechnique` <- `hacking-skills/skills/web/injection/http-request-smuggling/SKILL.md` and `claude-bug-hunter/skills/hunt-http-smuggling/SKILL.md`: a framing-header obfuscation family (space before colon, tab, line folding, mixed case, duplicate framing headers) that defeats a normalising front end, extending "Representation and Framing Reading".
- `AttackTechnique` <- `anthropic-cybersecurity-skills/accepted/W9/performing-http-parameter-pollution-attack/SKILL.md`: a per-reader precedence matrix (first-wins, last-wins, array, concatenation) as the reconnaissance procedure that establishes duplicate-member precedence rather than assuming it.
- `AttackTechnique` <- `claude-bug-hunter/skills/hunt-api-misconfig/SKILL.md` and `anthropic-cybersecurity-skills/accepted/W2/bypassing-authentication-with-forced-browsing/SKILL.md`: the override-member family (`X-HTTP-Method-Override`, `X-Original-Method`, `X-Rewrite-URL`, `_method`) as the verb/location re-reading set.
- `ObservableSignal` <- `claude-bug-hunter/skills/hunt-cache-poison/SKILL.md`: a response stored under a different method's key (a HEAD body under a GET key) as the observable that the executor applied an override member.
- `AttackTechnique` <- `claude-bug-hunter/skills/hunt-http-smuggling/SKILL.md`: the front-end fingerprint matrix as the reader-inventory procedure, because the leaf inventories readers but does not rank them by parser strictness.

**References/scripts candidates**
- `references/framing-obfuscation-table.md` <- `hacking-skills/skills/web/injection/http-request-smuggling/SKILL.md`, `claude-bug-hunter/skills/security-arsenal/SKILL.md`, `anthropic-cybersecurity-skills/accepted/W6/exploiting-http-request-smuggling/SKILL.md`: the TE.TE obfuscation variants and the CL/TE payload bank are bulky and generalised.
- `references/parameter-precedence-matrix.md` <- `anthropic-cybersecurity-skills/accepted/W9/performing-http-parameter-pollution-attack/SKILL.md`: the per-stack duplicate-precedence table is a reusable reference.

## defence-bypass-allowance-gap

**Sources matched**
- `anthropic-cybersecurity-skills/accepted/W4/performing-content-security-policy-bypass/SKILL.md` - CSP permit enumeration: allowlisted JSONP endpoints, base-uri and form-action gaps, object-src gaps, allowed script gadgets, nonce leak and reuse.
- `anthropic-cybersecurity-skills/accepted/W4/testing-cors-misconfiguration/SKILL.md`, `hacking-skills/skills/web/client-side/cors-misconfig/SKILL.md`, `claude-bug-hunter/skills/hunt-cors/SKILL.md` - the CORS permit: origin reflection, null origin, subdomain-regex class bypass, prefix/suffix match, insecure HTTP origin.
- `anthropic-cybersecurity-skills/accepted/W2/bypassing-authentication-with-forced-browsing/SKILL.md` - a protected route the permit never enumerated, plus path-normalisation bypass of a path-based permit.
- `awsome-offensive-security-skill/skills/bug-hunting/web-vulnerabilities/csrf-token-bypass-techniques/SKILL.md` - referer/origin prefix-match allowlist bypass and presence-gated token validation.
- `claude-bug-hunter/skills/hunt-api-misconfig/SKILL.md` - `$orderby`/`$select` column-ACL divergence and `$expand` navigation-property access as routes an ACL enumeration omits (low confidence, IDOR class detail).

**Similarity**: sufficient. The leaf's policy-allowance, sanitiser-enumeration, and confinement/substitution sub-mechanisms cover the permit-enumeration sources.

**Boundary**: none for the family. The permit-enumeration step covers CSP, CORS, path ACLs, and token checks alike, because the family is control-agnostic.
The CSP and CORS classes are separate suite skills the suite lacks, which is a cross-slice observation, not a family variant.

**New-skill proposals**
- source: `anthropic-cybersecurity-skills/accepted/W4/testing-cors-misconfiguration/SKILL.md`, `hacking-skills/skills/web/client-side/cors-misconfig/SKILL.md`, `claude-bug-hunter/skills/hunt-cors/SKILL.md`.
  `[NEW] target: cors-misconfiguration` (cross-slice, class group, flagged out of family scope).
  Rationale: the trust-assumption boundary attribute diverges, because the class definition is the browser's same-origin read model and the credentialed cross-origin read, not the generic permit-enumeration mechanic; the impact also requires a browser PoC, which bends a step (the family's permit step has no browser-enforcement step). Baseline web-vulnerability-testing is present. Confidence medium. Flag: this belongs to the class groups, not to `defence-bypass`, and the operator should route it to the class-slice owner.

**Enrichment candidates**
- `AttackTechnique` <- `anthropic-cybersecurity-skills/accepted/W4/performing-content-security-policy-bypass/SKILL.md`: allowed-script-gadget and allowlisted-JSONP-callback enumeration as combinations of permitted primitives that reach the withheld capability, extending "Sanitiser Enumeration Gaps".
- `AttackTechnique` <- `anthropic-cybersecurity-skills/accepted/W4/performing-content-security-policy-bypass/SKILL.md`: nonce/hash leak and reuse (CSS attribute-selector leak, cross-page nonce reuse, DOM clobbering of the nonce) as a permit whose enumerable value is meant to be secret.
- `AttackTechnique` <- `claude-bug-hunter/skills/hunt-cors/SKILL.md`: the allowlist regex-class bypass procedure (missing dot separator, missing end anchor, unescaped dot, prefix-only, browser-emitted special characters) as the route inventory for an origin allowlist.
- `AttackTechnique` <- `anthropic-cybersecurity-skills/accepted/W2/bypassing-authentication-with-forced-browsing/SKILL.md`: path-normalisation bypass of a path-based permit (case, dot-segments, encoded slash, `;`, `..;/`, trailing characters) as unlisted routes to a protected path.
- `DefensiveControl` <- `awsome-offensive-security-skill/skills/bug-hunting/web-vulnerabilities/csrf-token-bypass-techniques/SKILL.md`: a presence-gated check (a control that validates only when the member is present) and a referer/origin prefix-match allowlist, both permit kinds the family's `## Bypass Techniques` does not name.
- `PreconditionEnvironment` <- `anthropic-cybersecurity-skills/accepted/W4/performing-content-security-policy-bypass/SKILL.md`: the capability is a browser-confined effect (script execution or a cross-origin read) gated by a declarative permit, which the leaf states as a surface but not as an applicability condition.

**References/scripts candidates**
- `references/permit-enumeration-matrix.md` <- `anthropic-cybersecurity-skills/accepted/W4/performing-content-security-policy-bypass/SKILL.md`, `claude-bug-hunter/skills/hunt-cors/SKILL.md`, `anthropic-cybersecurity-skills/accepted/W2/bypassing-authentication-with-forced-browsing/SKILL.md`: the route-inventory matrix (directives, sources, elements, origins, paths, methods, tokens) is generalised across permit kinds.
- `references/csp-permit-gaps.md` <- `anthropic-cybersecurity-skills/accepted/W4/performing-content-security-policy-bypass/SKILL.md`: the directive-level gap list is bulky, product-neutral, and reusable by any consuming class that names the family at its permit step.

## defence-bypass-edge-origin-differential

**Sources matched**
- `anthropic-cybersecurity-skills/accepted/W6/exploiting-http-request-smuggling/SKILL.md` - front-end ACL versus back-end service as the tier gap.
- `claude-bug-hunter/skills/hunt-http-smuggling/SKILL.md` - smuggling past a front-end ACL and the front-end fingerprint matrix as tier mapping.
- `anthropic-cybersecurity-skills/accepted/W2/bypassing-authentication-with-forced-browsing/SKILL.md` - a sibling route that skips the current chain and a method that skips authentication.
- `claude-bug-hunter/skills/hunt-api-misconfig/SKILL.md` - shadow and deprecated API versions (`/v1` versus `/v3`, mobile subdomains) as sibling routes with no current chain.
- `anthropic-cybersecurity-skills/accepted/W5/performing-api-rate-limiting-bypass/SKILL.md` and `awsome-offensive-security-skill/skills/bug-hunting/api-security/api-rate-limit-bypass-techniques/SKILL.md` - API-version downgrade and path variation where the serving tier never consulted the enforcing tier.
- `claude-bug-hunter/skills/hunt-cache-poison/SKILL.md` - a stored verdict or response reused across a changed request.

**Similarity**: sufficient. The leaf's route/chain divergence, verdict reuse, and scope divergence sub-mechanisms cover the sources.

**Boundary**: none. The control kind is a tier gap, and no boundary attribute diverges.

**New-skill proposals**
- None.

**Enrichment candidates**
- `AttackTechnique` <- `claude-bug-hunter/skills/hunt-api-misconfig/SKILL.md` and `awsome-offensive-security-skill/skills/bug-hunting/api-security/api-rate-limit-bypass-techniques/SKILL.md`: a shadow/deprecated-route enumeration family (version downgrade, mobile subdomain, legacy path) where the sibling route carries no current chain, extending "Route and Chain Divergence".
- `AttackTechnique` <- `anthropic-cybersecurity-skills/accepted/W2/bypassing-authentication-with-forced-browsing/SKILL.md`: method-scope divergence (a route enforces the rule for one verb only, and a method override reaches the unprotected path) as a scope gap between tiers.
- `ObservableSignal` <- `claude-bug-hunter/skills/hunt-cache-poison/SKILL.md`: a stored verdict reused across a changed method (a HEAD body served under a GET key) as the observable that the verdict was not recomputed.
- `DefensiveControl` <- `anthropic-cybersecurity-skills/accepted/W2/bypassing-authentication-with-forced-browsing/SKILL.md`: the unauthenticated-versus-authenticated response comparison as the procedure that reads each tier's verdict.

**References/scripts candidates**
- `references/tier-route-inventory.md` <- `claude-bug-hunter/skills/hunt-api-misconfig/SKILL.md`, `anthropic-cybersecurity-skills/accepted/W2/bypassing-authentication-with-forced-browsing/SKILL.md`: the sibling-route and shadow-version inventory is a generalised reference.

## defence-bypass-throttle-evasion

**Sources matched**
- `anthropic-cybersecurity-skills/accepted/W5/performing-api-rate-limiting-bypass/SKILL.md` - header-based IP rotation, path variation, method/content-type switching, account rotation, parameter pollution, and concurrent bursts.
- `claude-bug-hunter/skills/hunt-brute-force/SKILL.md` - the four rate-limit states (hard lockout, soft IP throttle, CAPTCHA injection, silent shadow-throttle) and the shadow-throttle detector.
- `awsome-offensive-security-skill/skills/bug-hunting/api-security/api-rate-limit-bypass-techniques/SKILL.md` - identifier mutation (case, whitespace, null byte), path modifiers, and the array-payload batching bypass.
- `awsome-offensive-security-skill/skills/bug-hunting/api-security/graphql-batching-attacks/SKILL.md` - array batching and alias batching, where one HTTP request carries many logical attempts.
- `claude-bug-hunter/skills/hunt-captcha-bypass/SKILL.md` - a throughput-gated challenge and the sliding-window concurrency note (sequential pacing cannot satisfy a "N within T seconds" check).
- `claude-bug-hunter/skills/hunt-api-misconfig/SKILL.md` - OData `$batch` `multipart/mixed`, where a per-request limiter or WAF does not count the inner operations.

**Similarity**: sufficient for the spread, window, and partial-limit sub-mechanisms. Insufficient for one source mechanism, the attempt-batching collapse, which is escalated below.

**Boundary**: the batch-collapse mechanism is a bent step. The parent's steps are baseline, probe each path, enumerate dimensions, spread one dimension, time the window and counter, measure accumulation, and attribute. None covers "construct one counted request that the backend expands into many logical operations". The diverging boundary attribute is `AttackTechnique` (a new bent step, not a value of an existing axis), so this is a new variant, not an aspect.

**New-skill proposals**
- source: `awsome-offensive-security-skill/skills/bug-hunting/api-security/api-rate-limit-bypass-techniques/SKILL.md`, `awsome-offensive-security-skill/skills/bug-hunting/api-security/graphql-batching-attacks/SKILL.md`, `claude-bug-hunter/skills/security-arsenal/SKILL.md`, `claude-bug-hunter/skills/hunt-api-misconfig/SKILL.md`.
  `[NEW] target: defence-bypass-attempt-batching` (new level-2 leaf under `defence-bypass`).
  Rationale: the mechanism collapses many logical attempts into one counted request through an array body, a GraphQL alias set, a `multipart/mixed` batch, or a fat request the limiter counts once and the backend iterates. The parent's `spread one dimension` step covers distributing one effect across an uncounted lane and cannot describe collapsing many attempts into one counted unit, so the step is bent. The variant is disjoint from `throttle-evasion`, which spreads across lanes, because batching reduces the counted request count rather than moving the effect to another lane. The discriminator is the limiter's counting unit (request versus logical operation), which is a value of `AttackTechnique`. Coverage holds because every batching carrier (array, alias, multipart, fat request) shares the one bent step. Stability holds across frameworks and payloads. Baseline web-vulnerability-testing is present. Confidence medium-high.

**Enrichment candidates**
- `ObservableSignal` <- `claude-bug-hunter/skills/hunt-brute-force/SKILL.md`: the silent shadow-throttle (status unchanged while latency rises or the body changes and a known-good value stops authenticating under load) as a limit verdict that is not a refusal, because without it the leaf's detection channels false-negative a live limit as "no limit".
- `DefensiveControl` <- `claude-bug-hunter/skills/hunt-brute-force/SKILL.md`: the four-state limit classification (hard lockout, soft IP throttle, CAPTCHA injection, silent shadow-throttle) as the family's control taxonomy at the accounting-baseline step.
- `AttackTechnique` <- `claude-bug-hunter/skills/hunt-captcha-bypass/SKILL.md`: sliding-window concurrency (fire N attempts concurrently to satisfy an "N within T seconds" check) as a window-gap procedure, because the leaf times attempts against the window but does not name concurrency as the instrument.
- `AttackTechnique` <- `awsome-offensive-security-skill/skills/bug-hunting/api-security/api-rate-limit-bypass-techniques/SKILL.md`: identifier-key canonicalisation gaps (case, whitespace, null byte, `+tag`) where the limiter keys on the literal identifier while the backend canonicalises it, extending "Counted-Dimension Gaps" to key-canonicalisation.
- `AttackTechnique` <- `claude-bug-hunter/skills/hunt-api-misconfig/SKILL.md`: `multipart/mixed` batching as a carrier the per-request limiter does not count, a counted-dimension gap at the carrier level.
- `PreconditionEnvironment` <- `claude-bug-hunter/skills/hunt-brute-force/SKILL.md`: the endpoint's own required-field validation must be satisfied before a concurrent payload reaches the counting middleware, an applicability condition the leaf omits.

**References/scripts candidates**
- `references/rate-limit-state-classifier.md` <- `claude-bug-hunter/skills/hunt-brute-force/SKILL.md`: the four-state table and the shadow-throttle seed detector are generalised and bulky.
- `references/batching-carriers.md` <- `awsome-offensive-security-skill/skills/bug-hunting/api-security/graphql-batching-attacks/SKILL.md`, `claude-bug-hunter/skills/hunt-api-misconfig/SKILL.md`, `awsome-offensive-security-skill/skills/bug-hunting/api-security/api-rate-limit-bypass-techniques/SKILL.md`: the array, alias, multipart, and fat-request carriers are a reusable catalogue for the proposed leaf.

---

# Group `proxy-techniques`

The parent is an umbrella. Its six leaves own the six intermediary mechanisms: resolution rebinding, redirect carry, destination parse disagreement, carrier substitution, shared-cache keying, and relay-field trust.
The family attracts generic intermediary material: cache poisoning and deception, host-header injection, open redirect, HTTP parameter pollution, HTTP smuggling, CORS, CSP, and client-side path traversal.

## proxy-techniques

**Sources matched**
- `claude-bug-hunter/skills/hunt-cache-poison/SKILL.md` - the direct-route versus intermediary-route paired baseline, the cache-buster requirement, and the second-client read.
- `claude-bug-hunter/skills/hunt-host-header/SKILL.md` - the reflected-versus-cached attribution rule.
- `anthropic-cybersecurity-skills/accepted/W6/performing-web-cache-poisoning-attack/SKILL.md` - the cache-buster isolation procedure.
- `anthropic-cybersecurity-skills/accepted/W6/exploiting-http-request-smuggling/SKILL.md` - the intermediary chain and hop-by-hop mechanics.

**Similarity**: sufficient. The parent already names the resolver, forwarder, relay, cache, carrier, and consumer-library roles, so the sources are consumed by the leaves.

**Boundary**: none. The parent is a family, and the boundary document states that `proxy-techniques` is a family, not a class axis.

**New-skill proposals**
- None.

**Enrichment candidates**
- `AttackTechnique` <- `claude-bug-hunter/skills/hunt-cache-poison/SKILL.md`: cache-buster isolation (probe under a throwaway key, never store under the live key) as a safety-and-attribution procedure for the "Craft the carrier" step.
- `ObservableSignal` <- `claude-bug-hunter/skills/hunt-host-header/SKILL.md`: the reflected-is-not-trusted and cached-for-you-is-not-cached-for-others attribution rules, which the parent states as false positives and should also carry as detection-channel guards.
- `Artifact` <- `claude-bug-hunter/skills/hunt-cache-poison/SKILL.md`: the cache-status header set (`X-Cache`, `CF-Cache-Status`, `Age`, `Via`) as a reusable evidence artifact that names the cache and its TTL.

**References/scripts candidates**
- `references/intermediary-role-map.md` <- `claude-bug-hunter/skills/hunt-cache-poison/SKILL.md`, `anthropic-cybersecurity-skills/accepted/W6/exploiting-http-request-smuggling/SKILL.md`: the intermediary role map (resolver, forwarder, relay, cache, carrier) with each role's caller-influenced inputs is generalised and reusable.

## proxy-techniques-dns-rebinding

**Sources matched**
- `claude-bug-hunter/skills/security-arsenal/SKILL.md` - the SSRF IP-bypass block names DNS rebinding explicitly ("A to external, then resolves to internal after the allowlist check") and the redirect-chain Vercel pattern.
- `hacking-skills/skills/web/client-side/open-redirect/SKILL.md` - names DNS rebinding tricks as an open-redirect filter bypass (low confidence, one clause).
- `anthropic-cybersecurity-skills/accepted/W8/performing-dns-enumeration-and-zone-transfer/SKILL.md` - DNS reconnaissance only; low relevance.
- `awsome-offensive-security-skill/skills/network/ipv6-dns-takeover-mitm/SKILL.md` - DHCPv6/DNS spoofing and NTLM relay; a clean non-match (network baseline absent).

**Similarity**: sufficient for `claude-bug-hunter/skills/security-arsenal/SKILL.md` at the level of naming the mechanism, and insufficient for the remainder, which either mention rebinding in one clause or operate at the network layer.

**Boundary**: none. No boundary attribute diverges, and the source that mentions rebinding is a payload library, not a competing class.

**New-skill proposals**
- None.

**Enrichment candidates**
- `PayloadPattern` <- `claude-bug-hunter/skills/security-arsenal/SKILL.md`: the rebinding payload shape (a name whose first answer is benign and whose second answer is the interior address) is the leaf's core, so this is a consolidation rather than new content (low value, recorded for completeness).
- `AttackTechnique` <- `claude-bug-hunter/skills/security-arsenal/SKILL.md`: the redirect-chain rebinding combination (a second answer that is itself a redirecting destination) is already the leaf's chaining note.

**References/scripts candidates**
- `references/dns-rebinding-setup.md` <- `claude-bug-hunter/skills/security-arsenal/SKILL.md`: the rebinding-plus-notation-bypass block is a marginal generalisation candidate, flagged low value because the leaf already owns the procedure.

## proxy-techniques-redirect-chain

**Sources matched**
- `anthropic-cybersecurity-skills/accepted/W6/testing-for-open-redirect-vulnerabilities/SKILL.md` - the redirect-validation bypass table, the OAuth chain, and the redirect_uri chain.
- `hacking-skills/skills/web/client-side/open-redirect/SKILL.md` - the bypass table (protocol-relative, backslash, `@`, double-encode, null, fragment, subdomain, IDN homograph, `javascript:`).
- `claude-bug-hunter/skills/hunt-open-redirect/SKILL.md` - the bypass table, DOM-based open redirect, and server-side redirect as an SSRF escalation.
- `hacking-skills/skills/web/client-side/cspt/SKILL.md` - `fetch()` auto-follows redirects by default and can be chained to a gadget endpoint.
- `anthropic-cybersecurity-skills/accepted/W7/performing-ssl-stripping-attack/SKILL.md` - scheme downgrade at a hop; a clean non-match (network baseline absent).

**Similarity**: sufficient. The leaf's hop-approval, nested-hop, and scheme-switch sub-mechanisms cover the redirect sources.

**Boundary**: none. Open redirect is a class the suite already holds (`open-redirect`), and the family leaf owns the generic hop-carry mechanism, so no boundary attribute diverges.

**New-skill proposals**
- source: `hacking-skills/skills/web/client-side/cspt/SKILL.md`.
  `[NEW] target: proxy-techniques-client-side-path-traversal` (new level-2 leaf under `proxy-techniques`, confidence medium).
  Rationale: the caller's input lands in the path segment of a URL a client library builds and completes against its own base, and the client then follows a redirect to a gadget endpoint. The leaf's hop-approval step covers a server-side destination check applied before a follow, and does not describe a client-side relative-path completion plus traversal to a gadget endpoint, so the step is bent. The diverging boundary attribute is `AttackTechnique`. The variant is disjoint from `redirect-chain` because it relocates the request path client-side rather than carrying an approved operation to a second destination, and disjoint from `url-parser-differential` because the two readers are not competing for one destination value. Baseline web-vulnerability-testing is present (`path-traversal-lfi-rfi`, `open-redirect`, `xss`). Alternative considered: fold into `redirect-chain` as the `Consumer Libraries` aspect; rejected because the client-side relative-base completion is a distinct step the aspect list does not hold.

**Enrichment candidates**
- `AttackTechnique` <- `hacking-skills/skills/web/client-side/cspt/SKILL.md`: the client-side `fetch()` auto-follow as a follower the caller does not control, and the traversal-to-gadget chain, extending the leaf's follower kinds.
- `AttackTechnique` <- `claude-bug-hunter/skills/hunt-open-redirect/SKILL.md`: the DOM-based redirect (a client-side navigation sink fed by a URL source) as a follower that emits no server-side `Location` header.
- `PayloadPattern` <- `anthropic-cybersecurity-skills/accepted/W6/testing-for-open-redirect-vulnerabilities/SKILL.md`: the redirect-validation bypass table (`@`, protocol-relative, backslash, double-encode, null, fragment, subdomain) as the destination-shaping family.
- `AttackTechnique` <- `anthropic-cybersecurity-skills/accepted/W6/testing-for-open-redirect-vulnerabilities/SKILL.md`: the continuation-value rule divergence (a logout or post-action continuation whose rule is weaker than the primary check) is already in the leaf's bypass list; record as a consolidation.

**References/scripts candidates**
- `references/redirect-bypass-table.md` <- `hacking-skills/skills/web/client-side/open-redirect/SKILL.md`, `claude-bug-hunter/skills/hunt-open-redirect/SKILL.md`: the destination-validation bypass table is generalised and bulky.
- `references/cspt-gadget-chain.md` <- `hacking-skills/skills/web/client-side/cspt/SKILL.md`: the fetch-traversal-to-gadget procedure is a reusable worked chain.

## proxy-techniques-url-parser-differential

**Sources matched**
- `claude-bug-hunter/skills/hunt-api-misconfig/SKILL.md` - server-side parameter pollution in backend URL and REST URL construction, fragment termination of the original backend path, and path traversal inside a server-side URL.
- `anthropic-cybersecurity-skills/accepted/W6/testing-for-open-redirect-vulnerabilities/SKILL.md` and `hacking-skills/skills/web/client-side/open-redirect/SKILL.md` - URL-parsing inconsistency, userinfo abuse, backslash, subdomain confusion, and the notation family.
- `hacking-skills/skills/web/client-side/cspt/SKILL.md` - client-side path traversal and the encoding-level matrix for a URL-normalisation disagreement.
- `claude-bug-hunter/skills/hunt-cache-poison/SKILL.md` - cache-versus-origin path normalisation discrepancies (delimiters, encoded segments).
- `anthropic-cybersecurity-skills/accepted/W6/performing-web-cache-deception-attack/SKILL.md` - CDN-versus-origin path-normalisation discrepancy.

**Similarity**: sufficient. The leaf's authority-boundary, duplicate-precedence, and notation/relative-folding sub-mechanisms cover the sources, and its `Consumer Libraries` surface already names components that complete a value against their own base.

**Boundary**: none. The mechanism is two readers of one destination value, and no boundary attribute diverges. Server-side URL construction is coverable as an aspect because the leaf's `Consumer Libraries` surface already holds "components that complete a relative value against their own base".

**New-skill proposals**
- None.

**Enrichment candidates**
- `AttackTechnique` <- `claude-bug-hunter/skills/hunt-api-misconfig/SKILL.md`: the server-side URL builder as a second reader (the server interpolates the caller's value into a backend URL path or query, `#`/`%23` terminates the original backend path, and path traversal moves within the backend URL), which is the strongest single enrichment in this slice because it adds a reader kind the leaf's surface names only for client libraries.
- `ObservableSignal` <- `claude-bug-hunter/skills/hunt-api-misconfig/SKILL.md`: an API-definition or `Invalid route` error as the observable that the value reached a server-side URL router rather than a text validator.
- `AttackTechnique` <- `claude-bug-hunter/skills/hunt-cache-poison/SKILL.md`: cache-versus-origin path-normalisation disagreement as a two-reader parse gap, a cache-specific instance of the parse clause.
- `AttackTechnique` <- `anthropic-cybersecurity-skills/accepted/W6/testing-for-open-redirect-vulnerabilities/SKILL.md`: the userinfo, backslash, mixed-slash, trailing-dot, and fragment notation family as the authority-boundary shaping set (consolidation of the leaf's existing list).

**References/scripts candidates**
- `references/url-parse-differential-matrix.md` <- `anthropic-cybersecurity-skills/accepted/W6/testing-for-open-redirect-vulnerabilities/SKILL.md`, `claude-bug-hunter/skills/hunt-api-misconfig/SKILL.md`, `claude-bug-hunter/skills/hunt-cache-poison/SKILL.md`: the notation family (userinfo, separators, dots, case, encoding, fragment, relative base) across readers is a generalised matrix.

## proxy-techniques-channel-wrapping

**Sources matched**
- `anthropic-cybersecurity-skills/accepted/W9/performing-web-application-firewall-bypass/SKILL.md` - protocol-version and framing carriers (HTTP/0.9 no-headers, chunked transfer, method switch) and unusual parameter locations (a value carried in an uninspected header).
- `anthropic-cybersecurity-skills/accepted/W9/performing-http-parameter-pollution-attack/SKILL.md` - carrier variants and header pollution.
- `claude-bug-hunter/skills/hunt-http-smuggling/SKILL.md` - H2.CL/H2.TE protocol downgrade as a second carrier.
- `claude-bug-hunter/skills/hunt-api-misconfig/SKILL.md` - OData `$batch` `multipart/mixed` as a carrier the guard does not parse.
- `anthropic-cybersecurity-skills/accepted/W2/bypassing-authentication-with-forced-browsing/SKILL.md` and `awsome-offensive-security-skill/skills/bug-hunting/web-vulnerabilities/csrf-token-bypass-techniques/SKILL.md` - verb and content-type substitution that skips a carrier-specific check.
- `anthropic-cybersecurity-skills/accepted/W5/performing-api-rate-limiting-bypass/SKILL.md` - method and content-type switching that resets the accounting.
- `hacking-skills/skills/web/client-side/cspt/SKILL.md` - fetch redirect modes as a carrier behaviour.

**Similarity**: sufficient. The leaf's carrier-substitution, guard-parity, second-channel-replay, and capture sub-mechanisms cover the sources.

**Boundary**: none. The mechanism is carrier substitution, and no boundary attribute diverges.

**New-skill proposals**
- None.

**Enrichment candidates**
- `AttackTechnique` <- `anthropic-cybersecurity-skills/accepted/W9/performing-web-application-firewall-bypass/SKILL.md`: the protocol-version carrier (HTTP/0.9 with no headers, HTTP/2 versus HTTP/1.1, chunked framing) where the guard inspects one protocol version only, extending the leaf's carrier list beyond content type, verb, transport, endpoint, session, and device.
- `AttackTechnique` <- `claude-bug-hunter/skills/hunt-api-misconfig/SKILL.md`: the `multipart/mixed` sub-request carrier, where the guard does not parse the inner operations.
- `AttackTechnique` <- `anthropic-cybersecurity-skills/accepted/W9/performing-web-application-firewall-bypass/SKILL.md`: the unusual-location carrier (a value carried in a header the guard does not inspect, such as `X-Forwarded-For` or `Referer`).
- `AttackTechnique` <- `awsome-offensive-security-skill/skills/bug-hunting/web-vulnerabilities/csrf-token-bypass-techniques/SKILL.md`: a multipart carrier that skips a token check bound to one content type.
- `ObservableSignal` <- `claude-bug-hunter/skills/hunt-http-smuggling/SKILL.md`: a front-end that accepts HTTP/2 but downgrades to HTTP/1.1 for the origin as the observable that a protocol carrier exists.

**References/scripts candidates**
- `references/carrier-substitution-matrix.md` <- `anthropic-cybersecurity-skills/accepted/W9/performing-web-application-firewall-bypass/SKILL.md`, `claude-bug-hunter/skills/hunt-http-smuggling/SKILL.md`, `awsome-offensive-security-skill/skills/bug-hunting/web-vulnerabilities/csrf-token-bypass-techniques/SKILL.md`: the carrier family table (content type, verb, protocol version, framing, transport, endpoint, session, device, multipart) is generalised and reusable.

## proxy-techniques-cache-deception

**Sources matched**
- `anthropic-cybersecurity-skills/accepted/W6/performing-web-cache-deception-attack/SKILL.md` - path-based deception, delimiter discrepancies, normalisation, key manipulation, and the second-caller read.
- `anthropic-cybersecurity-skills/accepted/W6/performing-web-cache-poisoning-attack/SKILL.md` - unkeyed input, cache-key construction, and the WCD section.
- `claude-bug-hunter/skills/hunt-cache-poison/SKILL.md` - unkeyed-input discovery, the WCD path-extension list, the Cloudflare `.avif` Cache-Deception-Armor bypass, the Kettle path-normalisation WCD, the second-client read, and Origin-to-ACAO cache poisoning.
- `awsome-offensive-security-skill/skills/bug-hunting/web-vulnerabilities/web-cache-poisoning-deception/SKILL.md` - unkeyed inputs and WCD.
- `awsome-offensive-security-skill/skills/bug-hunting/deep-dive-labs/cache-deception/SKILL.md` - path mapping, delimiters, origin-versus-cache normalisation, and the exact-match-rule plus `X-Custom` miss trick.

**Similarity**: sufficient. The leaf's unkeyed-input, key-normalisation/fragmentation, and cross-caller read sub-mechanisms cover both cache poisoning and cache deception.

**Boundary**: none for a new variant. Cache poisoning and cache deception are two clauses of one agreement, and the leaf's `## Trust Assumptions` already states both the cache-key clause and the produced-for-caller clause; the leaf's `## Key Vulnerabilities` already holds `Unkeyed Input to a Keyed Response` and `Stored-Response Reads Across Callers`. The only differing boundary attribute would be impact, and the boundary document states that impact alone is not a discriminator.
Cross-slice observation: a dedicated `cache-poisoning` class may be warranted for the suite, but that is a class-group question, not a family variant, and it is flagged, not proposed here.

**New-skill proposals**
- None in this family.

**Enrichment candidates**
- `AttackTechnique` <- `claude-bug-hunter/skills/hunt-cache-poison/SKILL.md`: error-response caching (a 4xx/5xx produced from attacker input is stored and served to later callers) as a stored-response class, extending the leaf beyond a shaped success body.
- `AttackTechnique` <- `claude-bug-hunter/skills/hunt-cache-poison/SKILL.md`: Origin-to-ACAO cache poisoning (a cached permissive or attacker `Access-Control-Allow-Origin`) as a cross-caller read through a cached header.
- `AttackTechnique` <- `claude-bug-hunter/skills/hunt-cache-poison/SKILL.md`: extension-allowlist bypass (the Cloudflare Cache-Deception-Armor `.avif` case) and the WCD path-extension list (`.css`, `.js`, `;.css`, `%2e%2ecss`) as key-eligibility and key-identity gaps.
- `AttackTechnique` <- `awsome-offensive-security-skill/skills/bug-hunting/deep-dive-labs/cache-deception/SKILL.md`: the exact-match-rule plus forced-miss trick (add a header such as `X-Custom: 1` to force a miss, then have the victim's cached response served to the attacker) as a key-shaping procedure.
- `AttackTechnique` <- `anthropic-cybersecurity-skills/accepted/W6/performing-web-cache-deception-attack/SKILL.md`: the delimiter-discrepancy family (`;`, `?`, `#`, `%2F`, `%3B`, null byte, dot-segment) between cache and origin as the key-shaping set.
- `ObservableSignal` <- `claude-bug-hunter/skills/hunt-cache-poison/SKILL.md`: the cache-status header set (`X-Cache`, `CF-Cache-Status`, `Age`, `Via`) as the signal that localises the cache and its TTL.
- `DefensiveControl` <- `claude-bug-hunter/skills/hunt-cache-poison/SKILL.md`: `Vary`-header completeness as the control to defeat, named explicitly as the cache's key-coverage declaration.

**References/scripts candidates**
- `references/cache-key-shaping-matrix.md` <- `anthropic-cybersecurity-skills/accepted/W6/performing-web-cache-deception-attack/SKILL.md`, `claude-bug-hunter/skills/hunt-cache-poison/SKILL.md`, `awsome-offensive-security-skill/skills/bug-hunting/deep-dive-labs/cache-deception/SKILL.md`: the key-shaping matrix (unkeyed selectors, delimiters, extensions, normalisation, eligibility) is generalised and bulky.

## proxy-techniques-relay-forwarding

**Sources matched**
- `claude-bug-hunter/skills/hunt-host-header/SKILL.md` - forwarded-value trust, field-family spraying, the routing-SSRF versus path-override layer distinction (`X-Original-URL`/`X-Rewrite-URL`), dual-Host precedence, and OAuth/OIDC issuer poisoning.
- `anthropic-cybersecurity-skills/accepted/W6/testing-for-host-header-injection/SKILL.md` - forwarding headers, password-reset poisoning, cache poisoning via host, and SSRF via host.
- `awsome-offensive-security-skill/skills/bug-hunting/web-vulnerabilities/host-header-injection-attacks/SKILL.md` - reflection, reset poisoning, `X-Forwarded-Host` bypass, and internal routing.
- `anthropic-cybersecurity-skills/accepted/W6/performing-web-cache-poisoning-attack/SKILL.md` - `X-Forwarded-Host` reflection into a cached body.
- `anthropic-cybersecurity-skills/accepted/W5/performing-api-rate-limiting-bypass/SKILL.md`, `claude-bug-hunter/skills/hunt-brute-force/SKILL.md`, `awsome-offensive-security-skill/skills/bug-hunting/api-security/api-rate-limit-bypass-techniques/SKILL.md` - the limiter trusting a client-supplied source header, a relay-field-trust instance.
- `claude-bug-hunter/skills/hunt-cache-poison/SKILL.md` - `X-Forwarded-Host` and `X-HTTP-Method-Override` as forwarded/unkeyed fields.

**Similarity**: sufficient. The leaf's forwarded-value, field-family-spraying, and relay-rewrite/override sub-mechanisms cover the sources.

**Boundary**: none. The mechanism is relay-field trust, and no boundary attribute diverges.

**New-skill proposals**
- None.

**Enrichment candidates**
- `AttackTechnique` <- `claude-bug-hunter/skills/hunt-host-header/SKILL.md`: the explicit two-layer disambiguation of routing SSRF (the Host header selects the upstream) from path override (`X-Original-URL`/`X-Rewrite-URL` overrides the routed path), because the two act at different layers and must not be composed; the leaf names override fields but not this disambiguation.
- `AttackTechnique` <- `claude-bug-hunter/skills/hunt-host-header/SKILL.md`: OAuth/OIDC issuer and discovery poisoning (the forwarded host drives `redirect_uri` or the OIDC issuer), a decision the forwarded value reaches, extending the leaf's "an allowlist, a secure-transport check, or a link the origin builds".
- `AttackTechnique` <- `claude-bug-hunter/skills/hunt-host-header/SKILL.md`: dual-Host and second-Host precedence (some stacks read the second `Host` header), a parser-confusion flavour inside relay-field trust, with a cross-link to `defence-bypass-parser-confusion`.
- `ObservableSignal` <- `claude-bug-hunter/skills/hunt-host-header/SKILL.md`: the reflected-is-not-trusted guard (a reflected Host string is not SSRF unless the response content came from the internal target or the out-of-band callback fired).
- `DefensiveControl` <- `awsome-offensive-security-skill/skills/bug-hunting/api-security/api-rate-limit-bypass-techniques/SKILL.md`: the rate limiter trusting a client-supplied source header as a relay-field-trust instance the leaf's detection channels can name.

**References/scripts candidates**
- `references/forwarded-field-families.md` <- `claude-bug-hunter/skills/hunt-host-header/SKILL.md`, `anthropic-cybersecurity-skills/accepted/W6/testing-for-host-header-injection/SKILL.md`, `claude-bug-hunter/skills/security-arsenal/SKILL.md`: the forwarded-field family list and the layer disambiguation are generalised and bulky.

---

# Slice summary

## Counts

- Base skills analysed: 14 (2 parents, 12 leaves).
- Source skill files read in full: 30.
- Similarity verdicts: 12 sufficient; 2 mixed (`dns-rebinding` sufficient on one library source and insufficient on the remainder; `throttle-evasion` sufficient except for the escalated batch-collapse mechanism).
- New-skill proposals: 4 total. One in-family leaf (`defence-bypass-attempt-batching`) and one in-family leaf (`proxy-techniques-client-side-path-traversal`) are family variants. Two cross-slice class candidates are flagged (`cors-misconfiguration`, and a noted but not proposed `cache-poisoning`).
- Enrichment candidates: 38 across the 12 leaves and 2 parents.
- References/scripts candidates: 12.
- Clean no-match verdicts recorded: second-order SQL injection, SSL stripping, IPv6 DNS takeover, AWS IMDSv2 SSRF bypass, DNS enumeration.

## Strongest findings

1. `defence-bypass-throttle-evasion` -> new leaf `defence-bypass-attempt-batching`.
   The array, GraphQL-alias, `multipart/mixed`, and fat-request carriers collapse many logical attempts into one counted request. This is a bent step the parent's spread step cannot cover, and it is disjoint from `throttle-evasion`. Sources: `awsome-offensive-security-skill/skills/bug-hunting/api-security/graphql-batching-attacks/SKILL.md`, `awsome-offensive-security-skill/skills/bug-hunting/api-security/api-rate-limit-bypass-techniques/SKILL.md`, `claude-bug-hunter/skills/hunt-api-misconfig/SKILL.md`. Confidence medium-high.

2. `defence-bypass-throttle-evasion` -> the silent shadow-throttle observable.
   `claude-bug-hunter/skills/hunt-brute-force/SKILL.md` supplies a limit verdict that is not a refusal (status unchanged, latency and body change, the known-good value stops authenticating under load). Without it the leaf false-negatives a live limit as "no limit". This is the single highest-value enrichment for correctness.

3. `defence-bypass-allowance-gap` -> CSP and CORS permit-enumeration abstractions, and a flagged cross-slice `cors-misconfiguration` class.
   `anthropic-cybersecurity-skills/accepted/W4/performing-content-security-policy-bypass/SKILL.md` and `claude-bug-hunter/skills/hunt-cors/SKILL.md` supply the route-inventory procedures (script gadgets, JSONP callbacks, nonce leak, origin regex-class bypass, path-normalisation bypass) that generalise "an unlisted route to the capability".

4. `proxy-techniques-url-parser-differential` -> server-side URL construction as a second reader.
   `claude-bug-hunter/skills/hunt-api-misconfig/SKILL.md` supplies the server-side parameter-pollution mechanism (the server interpolates the caller's value into a backend URL, `#` terminates the original path, traversal moves within it). The leaf's `Consumer Libraries` surface names this reader kind only for client libraries.

5. `proxy-techniques-redirect-chain` -> new leaf `proxy-techniques-client-side-path-traversal`.
   `hacking-skills/skills/web/client-side/cspt/SKILL.md` supplies the client-side fetch traversal and redirect-follow chain, a bent step the hop-approval step does not cover. Confidence medium.

## Low-confidence and non-match notes

- `anthropic-cybersecurity-skills/accepted/W3/performing-second-order-sql-injection/SKILL.md` is a confirmed non-match, exactly as the operator's example predicts: it is an SQL-injection class variant whose baseline is the SQL-injection suite, and it carries no bypass or proxy mechanic the families own.
- `anthropic-cybersecurity-skills/accepted/W7/performing-ssl-stripping-attack/SKILL.md` and `awsome-offensive-security-skill/skills/network/ipv6-dns-takeover-mitm/SKILL.md` are clean non-matches: both operate at the network layer, and the suite baseline is web-vulnerability-testing, which lacks the network exploitation baseline.
- `awsome-offensive-security-skill/skills/cloud-security/aws-imdsv2-ssrf-bypass/SKILL.md` is a non-match for the family: its PUT-then-GET token flow is the `ssrf` class's own technique, which the family names at its step rather than restates.
- `anthropic-cybersecurity-skills/accepted/W8/performing-dns-enumeration-and-zone-transfer/SKILL.md` is low relevance to `dns-rebinding`: it is reconnaissance only.
- The `anthropic-cybersecurity-skills` layout note: its accepted skills sit under `accepted/W1`..`W9` and `accepted/N1`..`N3` by attack-surface family, and the generic technique material for this slice concentrates in `W4` (CSP, CORS), `W5` (rate limiting), `W6` (cache, host, smuggling, redirect), and `W9` (WAF bypass, HTTP parameter pollution).
