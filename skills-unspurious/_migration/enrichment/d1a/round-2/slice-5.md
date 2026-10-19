# D1a enrichment round 2 - slice 5

Groups in this slice: `header-injection`, `http-request-smuggling`, `race-conditions`, `rce`, `xss`, `ssrf`.
Base skills read: 6 parents plus 18 variant leaves (24 skill files).
Source repositories indexed: `/Users/diekgbbtt/hacking-skills/skills` (43 skills), `/Users/diekgbbtt/claude-bug-hunter/skills` (105), `/Users/diekgbbtt/anthropic-cybersecurity-skills` (accepted 82, catalog 818), `/Users/diekgbbtt/awsome-offensive-security-skill/skills` (143 files).
Algorithm run per base skill: index, match by class or chain, read candidates, assess sufficiency, apply the boundary doc, then the ontology abstraction step, then references/scripts.
Residual hunt reported in its own section.

## header-injection

Parent `skills-unspurious/header-injection/SKILL.md`; leaves `header-crlf-splitting`, `header-cache-poisoning`, `header-host-forward-spoof`, `header-method-override`, `header-request-smuggling`, `header-response-value-confusion`.

**Sources matched**
- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W6/testing-for-host-header-injection/SKILL.md` (host-header injection).
- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-host-header/SKILL.md` (host-header injection, 16 reports).
- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/web-vulnerabilities/host-header-injection-attacks/SKILL.md`.
- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-cache-poison/SKILL.md` (cache poisoning and deception).
- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W6/performing-web-cache-poisoning-attack/SKILL.md`.
- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W6/performing-web-cache-deception-attack/SKILL.md`.
- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W3/testing-for-email-header-injection/SKILL.md`.
- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/web-vulnerabilities/web-cache-poisoning-deception/SKILL.md`.

**Similarity**
Sufficient for `header-host-forward-spoof` and `header-cache-poisoning`.
The host-header sources carry the same procedure: forge the authority family, compare `Host` against its aliases, read the emitted link and the access decision.
The cache sources carry the same procedure: find unkeyed input, confirm a clean second-session replay, measure blast radius.
Both match the base variants at step level; the differences are concrete technique sub-shapes, not bent steps.

**Boundary**
- Routing-based SSRF (the `Host` header selects the upstream) is a `PreconditionEnvironment` and `AttackTechnique` value inside `header-host-forward-spoof`, not a new variant.
  The parent step "test the authority family" is accurate for it; only the sink (upstream selection versus emitted link) differs, and the boundary doc treats a runtime location folded into a sink as an aspect.
  Flag: low-confidence. If the operator reads "the fetched interior body is returned" as a bent step, this escalates to an `ssrf` variant, not a `header-injection` one.
- OIDC discovery `issuer` and endpoint reflection is a value of the same link-generation step; it is an aspect of `header-host-forward-spoof`.
- Path-normalization and delimiter cache-key discrepancies (semicolon, encoded slash, dot segments, null byte, double-encoding, case) are values of the cache-key step; they are aspects of `header-cache-poisoning`, not a variant.
- Email/SMTP header injection is the same line-break normalization primitive on a different transport. The boundary doc excludes transport from variant axes, so it stays an aspect of the parent.

**New-skill proposals**
None. Every matched difference is covered by a parent step.

**Enrichment candidates**
- `AttackTechnique` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-host-header/SKILL.md` (Phase 3A): add routing-based SSRF as an explicit sub-shape of the authority family, with the anti-conflation note that routing SSRF (path on the request line, `Host` steers the upstream) and path-override (real `Host` stays, `X-Original-URL` overrides the routed path) act at different layers and never compose.
- `AttackTechnique` <- same source (Phase 4): add OIDC discovery `issuer` and endpoint reflection to the link-generation sub-shapes.
- `AttackTechnique` <- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W6/performing-web-cache-deception-attack/SKILL.md` (Steps 3-4): add cache-key path-normalization discrepancy (delimiter, encoded, dot-segment, case, double-encoded) as a deception sub-shape.
- `ObservableSignal` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-cache-poison/SKILL.md` (Origin-to-ACAO section): add cached permissive or wildcard `Access-Control-Allow-Origin` as a poisoning signal.
- `AttackTechnique` <- same source (disclosed citations 2, 3): add forwarded-port and method-override (HEAD under a GET key) shapes to the cache-key-versus-content sub-shape.
- `AttackTechnique` <- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W3/testing-for-email-header-injection/SKILL.md`: add outbound-message header injection to `Key Vulnerabilities` (SMTP recipient and command injection, MIME and body override, recipient-array abuse) with the detection channel "injected recipient receives a copy".
- `ObservableSignal` <- same source (Step 6): add "raw message source carries an injected field" as the message-transport detection channel.
- `DefensiveControl` <- same source (Step 1): add the mailer that rewrites links to a fixed site URL as a non-finding exclusion.

**References/scripts candidates**
- `/Users/diekgbbtt/claude-bug-hunter/skills/security-arsenal/SKILL.md` unkeyed-header wordlist and cache-deception extension list is generalizable to a `PayloadPattern` reference. It needs de-concretization first (drop tool names and product hostnames).

## http-request-smuggling

Parent `skills-unspurious/http-request-smuggling/SKILL.md`; leaf `http-request-smuggling-h2-desync`.

**Sources matched**
- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W6/exploiting-http-request-smuggling/SKILL.md`.
- `/Users/diekgbbtt/hacking-skills/skills/web/injection/http-request-smuggling/SKILL.md`.
- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-http-smuggling/SKILL.md`.
- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/web-vulnerabilities/http-request-smuggling-desync/SKILL.md`.
- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/web-vulnerabilities/http-request-smuggling-te-te/SKILL.md`.
- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/web-vulnerabilities/http-request-smuggling/SKILL.md`.

**Similarity**
Sufficient.
Every source carries the parent procedure: map the hop chain, probe the length-versus-encoding pair, obfuscate the declaration, confirm with a differential, escalate to bypass, capture, or cache.
The base parent already holds the full procedure and the `h2-desync` variant holds the downgrade shape.

**Boundary**
- Front-end and version suitability tables are `TechnologyStack`, which the ontology marks NEVER. They must not enter the body.
- The "collector gadget" (aim the smuggled request at a back-end handler that echoes the full request to harvest credentials at scale) is a value of the existing cross-user capture step, not a bent step.
- Cross-protocol HTTP-to-binary translation desync (an HTTP front-end forwarding to a binary back-end that ignores the framing declaration) is a value of the existing translation-hop framing-disagreement step.
  It stays an aspect of the parent. Flag: low-confidence, because the craft is protocol-specific; if the operator reads the binary attribute encoding as a bent step it becomes a third variant.

**New-skill proposals**
None. The matched material is covered by the parent plus `http-request-smuggling-h2-desync`.

**Enrichment candidates**
- `AttackTechnique` <- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W6/exploiting-http-request-smuggling/SKILL.md` (Step 6) and `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-http-smuggling/SKILL.md` (H2 section): add the cleartext-upgrade and tunnel shapes (upgrade-request smuggling, `CONNECT`-based tunneling, connection reuse poisoning) to `Advanced Techniques`.
- `AttackTechnique` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-http-smuggling/SKILL.md` (matrix row for a binary-translation back-end): add cross-protocol binary-translation desync as a translation-hop sub-shape.
- `ObservableSignal` <- same source (collector gadget): add "a request-echoing handler returns the next user's headers to the smuggled request" as a capture signal.
- `AttackTechnique` <- `/Users/diekgbbtt/hacking-skills/skills/web/injection/http-request-smuggling/SKILL.md` (payloads): add the duplicate-encoding and folded-continuation obfuscation forms that the parent lists only as a category.

**References/scripts candidates**
- `/Users/diekgbbtt/claude-bug-hunter/skills/security-arsenal/SKILL.md` smuggling payload bank is generalizable to a `PayloadPattern` reference after de-concretization.

## race-conditions

Parent `skills-unspurious/race-conditions/SKILL.md`; leaves `idempotency-dedup-bypass`, `optimistic-guard-evasion`, `single-request-fanout`, `cross-service-consistency-race`.

**Sources matched**
- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W6/exploiting-race-condition-vulnerabilities/SKILL.md`.
- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-race-condition/SKILL.md` (10 reports, single-packet deep reference).
- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/web-vulnerabilities/race-condition-toctou-exploitation/SKILL.md`.
- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/deep-dive-labs/race-conditions-labs/SKILL.md`.

**Similarity**
Sufficient for the parent.
The parent already holds atomicity, dedup, optimistic guards, cross-service windows, envelope fanout, precision synchronization, isolation levels, lock granularity, and window widening.
The four variants cover the four broken clauses.

**Boundary**
- The "different-requests race" (partial construction: fire a list of different requests in one synchronized window so an object is usable mid-creation) is a `AttackTechnique` value inside the parent's atomicity-gap step and inside the partial-construction TOCTOU shape.
  It does not bend a step; the parent already describes "partial multi-phase workflows: success committed before validation completes". Enrichment, not a variant.
- Token-generation collision (two resets at the same timestamp yield the same token) is a value of the auth-flow step. It is an aspect of the parent, not a new variant.
- The single-packet expansion (first-sequence sync for N above the packet limit) is a value of the existing precision-synchronization step. Aspect.

**New-skill proposals**
None.

**Enrichment candidates**
- `AttackTechnique` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-race-condition/SKILL.md` (opening section): add the different-requests race shape (register-then-confirm with a blank token) to `Advanced Techniques` and `Testing Methodology`.
- `AttackTechnique` <- same source (first-sequence-sync section): add the multi-connection synchronized-first-sequence expansion to the precision-synchronization step.
- `AttackTechnique` <- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/deep-dive-labs/race-conditions-labs/SKILL.md` (Lab 5): add timestamp-token collision to the auth-flow step.
- `ObservableSignal` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-race-condition/SKILL.md` (Wireshark validation): add "the synchronized flush lands as one segment carrying every final frame" as a confirmation signal.
- `PreconditionEnvironment` <- same source (race-window estimation): add the single-versus-sequential-versus-concurrent timing triage as a reconnaissance baseline.
- `DefensiveControl` <- same source (bypass table): add per-entity rate limiting, dedup keys, unique constraints, short windows, queue serialization, and in-process mutexes as controls with their bypass shapes.

**References/scripts candidates**
- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W6/exploiting-race-condition-vulnerabilities/scripts/agent.py` is not generalizable (concrete threading runner, concrete request shapes). Do not lift.
- `/Users/diekgbbtt/claude-bug-hunter/skills/security-arsenal/SKILL.md` single-packet template is a generalizable `PayloadPattern` reference after de-concretization.

## rce

Parent `skills-unspurious/rce/SKILL.md`; leaves `rce-command-injection`, `rce-pipeline-execution`.

**Sources matched**
- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-rce/SKILL.md` (87 reports, chain catalogue).
- `/Users/diekgbbtt/hacking-skills/skills/web/injection/cmd-injection/SKILL.md`.
- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/web-vulnerabilities/command-injection-os-level/SKILL.md`.
- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/deep-dive-labs/os-command-injection/SKILL.md`.
- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W3/exploiting-template-injection-vulnerabilities/SKILL.md`.
- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W3/exploiting-insecure-deserialization/SKILL.md`.

**Similarity**
Sufficient for `rce-command-injection` and `rce-pipeline-execution`.
The base already covers wrapper and CLI discovery, shell-context probing, argument injection, converters and renderers, decoder handoff, internal-service sinks, and container escalation.

**Boundary**
- The template, decoder, deserialization, and container sinks are owned by the `ssti`, `insecure-deserialization`, and `rce` container step. The anthropic template and deserialization skills map to those classes, not to a new `rce` variant.
- Config-as-code injection (an admin UI field written into a privileged daemon configuration that later interprets it) is a value of the internal-service-sink step and the privileged-context root cause.
  It is an aspect of `rce-command-injection`, not a new variant. Flag: medium-confidence, because the delegate is a daemon rather than a CLI; the two-half test still passes on the "delimiter breaks quoting" step.
- Argument-file expansion (`@file` reads a file into the argument list, errors echo it back) is a value of the argument-injection step. Aspect.

**New-skill proposals**
None. Every matched technique reaches an existing sink step.

**Enrichment candidates**
- `AttackTechnique` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-rce/SKILL.md` (config-as-code root cause): add privileged-daemon configuration injection (log destinations, metric plugins, job templates) to `Internal Service Sinks`.
- `AttackTechnique` <- same source (args4j section): add argument-file expansion with error-echo file read to the argument-injection sub-shape.
- `AttackTechnique` <- same source (Spring routing-expression section): add header-delivered expression injection that runs before the auth filter to the evaluation-sink sub-shape.
- `PayloadPattern` <- same source (SpEL array form): add the array-argument form that avoids shell quoting.
- `AttackTechnique` <- `/Users/diekgbbtt/hacking-skills/skills/web/injection/cmd-injection/SKILL.md` and `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/web-vulnerabilities/command-injection-os-level/SKILL.md`: add the shell-bypass shapes (input-field separator, brace expansion, redirection-as-space, quote and wildcard word splitting, base64 decode-to-shell) to `Bypass Techniques`.
- `ObservableSignal` <- same sources: add "error text echoes an argument-derived file line" and "output redirected to a fetchable path" as signals.
- `Artifact` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-rce/SKILL.md` (Chains section): add the two-halves framing (a primitive that puts bytes on the host plus a gadget that interprets them) to `Chaining Attacks`, naming the `sql-injection`, `insecure-file-uploads`, `prototype-pollution`, and `xxe` classes at their steps.

**References/scripts candidates**
- `/Users/diekgbbtt/claude-bug-hunter/skills/security-arsenal/SKILL.md` command-injection and template-injection payload banks are generalizable after de-concretization.
- The anthropic `agent.py` scripts for template injection and deserialization are not generalizable (concrete tool runners).

## xss

Parent `skills-unspurious/xss/SKILL.md`; leaves `xss-stored`, `xss-dom`.

**Sources matched**
- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-xss/SKILL.md` (174 reports).
- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-dom/SKILL.md` (DOM clobbering, postMessage, service worker, CSS exfiltration).
- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W4/performing-content-security-policy-bypass/SKILL.md`.
- `/Users/diekgbbtt/hacking-skills/skills/web/client-side/dom-xss/SKILL.md`.
- `/Users/diekgbbtt/hacking-skills/skills/web/client-side/cspt/SKILL.md`.
- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/web-vulnerabilities/xss-reflected-stored-dom/SKILL.md`.
- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/web-vulnerabilities/dom-based-xss/SKILL.md`.
- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/web-vulnerabilities/dom-based-cross-site-scripting-xss/SKILL.md`.
- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/deep-dive-labs/xss/SKILL.md`.

**Similarity**
Sufficient for the parent, `xss-stored`, and `xss-dom`.
The base already covers delivery shapes, context classification, sanitizer round-trip, stored retrieval, client-only source-to-sink flow, computed expressions, restricted renderers, and the runtime-policy bypass family.

**Boundary**
- DOM clobbering (markup-only injection overwrites a JavaScript global that later reaches a sink) has no covering step.
  The `xss-dom` source list is "fragment identifier, query string, cross-document message, client store"; a DOM-named element is not in it.
  This is a bent step. See proposals.
- postMessage hijacking is covered: the `xss-dom` source list already names cross-document messages. It is an enrichment (weak-origin-check bypass, sender wildcard leak, handler race), not a variant.
- Service-worker abuse requires same-origin script execution first and adds persistence and request interception. It is a post-exploitation step and belongs in `Chaining Attacks` and `Advanced Techniques`, not a variant.
- CSS injection and exfiltration executes no JavaScript and is not XSS. It has no home in the suite. See Residual candidates.
- Client-side path traversal (`fetch` path concatenation) is not XSS. It has no home. See Residual candidates.

**New-skill proposals**
- `source`: `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-dom/SKILL.md` (Phase 1), `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W4/performing-content-security-policy-bypass/SKILL.md` (Step 5, DOM-clobbering nonce override).
  `[NEW] target`: `xss-dom-clobbering` (a third `xss` variant).
  `rationale`: the injection is markup only, no script context is needed; a named element shadows a global the application later feeds into a URL, `innerHTML`, `eval`, or `script.src`. No parent step covers a client-side source that is a clobbered DOM global. Baseline fit: the `xss` baseline holds. Delta: markup-only injection plus a global-read-to-sink trace plus the clobbering namespace shapes. Flag: medium-confidence, because the delivery can be stored or reflected, so the operator may prefer a delivery-independent class over a variant.

**Enrichment candidates**
- `AttackTechnique` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-dom/SKILL.md` (Phase 2): add postMessage listener and sender shapes to `Client-Only Flow`, including the weak-origin-check bypass and the handler race.
- `AttackTechnique` <- same source (Phase 3): add same-origin service-worker registration and fetch interception to `Chaining Attacks` with the persistence note.
- `AttackTechnique` <- same source (Phase 5) and `/Users/diekgbbtt/hacking-skills/skills/web/client-side/dom-xss/SKILL.md` (payloads): add the framework sink catalogue (innerHTML-family, jQuery prefilter mutation, framework unsafe-HTML bindings) to `Client-Only Flow`.
- `AttackTechnique` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-xss/SKILL.md` (sanitizer bypass): add the mutation-XSS tag-combination shapes and the markdown and diagram-renderer injection shapes to `Sanitizer Round Trip` and `Restricted Renderers`.
- `ObservableSignal` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-xss/SKILL.md` (OOB gate): add the out-of-band execution confirmation for blind and stored delivery, with the browser-user-agent distinction.
- `ObservableSignal` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-dom/SKILL.md` (CSS exfiltration validation): add "one out-of-band hit per correct character" as the token-exfiltration signal (if CSS exfiltration is admitted).
- `DefensiveControl` <- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W4/performing-content-security-policy-bypass/SKILL.md`: add report-only mode, reflected policy header, missing `base-uri`, and missing `object-src` to `Bypass Techniques`.

**References/scripts candidates**
- `/Users/diekgbbtt/claude-bug-hunter/skills/security-arsenal/SKILL.md` XSS payload bank and source and sink lists are generalizable to a `PayloadPattern` reference after de-concretization.
- The `xss` class ships scripted tests inline per the ontology; no external script candidate here.

## ssrf

Parent `skills-unspurious/ssrf/SKILL.md`; leaves `no-response-egress-inference`, `scheme-translated-command-execution`, `header-gated-cloud-credential-read`.

**Sources matched**
- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-ssrf/SKILL.md` (34 reports).
- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W6/performing-blind-ssrf-exploitation/SKILL.md`.
- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W6/performing-ssrf-vulnerability-exploitation/SKILL.md`.
- `/Users/diekgbbtt/hacking-skills/skills/web/injection/ssrf/SKILL.md`.
- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/web-vulnerabilities/ssrf-server-side-request-forgery/SKILL.md`.
- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/web-vulnerabilities/ssrf-nextjs-server-actions/SKILL.md`.
- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/cloud-security/aws-imdsv2-ssrf-bypass/SKILL.md`.
- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/cloud-security/aws-metadata-ssrf/SKILL.md`, `aws-metadata-ssrf-exploitation`, `ssrf-aws-metadata-abuse`.
- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/deep-dive-labs/ssrf/SKILL.md`.

**Similarity**
Sufficient for the parent and for all three variants.
The base parent already holds surface inventory, oracle setup, interior addressing, handler variation, parser differentials, redirects, request shaping, high-value targeting, and blind mapping.
The three variants cover the observability clause, the plain-protocol clause, and the plain-header clause.

**Boundary**
- Headless-renderer SSRF (the caller injects executable markup that the renderer runs to fetch, read, and exfiltrate interior content) is not covered by the parent request-shaping step.
  The parent describes a single fetch the caller shapes; the renderer executes arbitrary caller code with response reading.
  This is a bent step. See proposals.
- Cloud metadata host names and token headers are `TechnologyStack`. They stay runtime knowledge-base facts and must not enter the body.
- The token-then-read method and header pair is already the `header-gated-cloud-credential-read` variant. Enrichment only.
- DNS rebinding and destination parse differentials are owned by the `proxy-techniques` family. The base already names it. No proposal.

**New-skill proposals**
- `source`: `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-ssrf/SKILL.md` (Scenario A, disclosed citations 3 and 4), `/Users/diekgbbtt/hacking-skills/skills/web/injection/ssrf/SKILL.md` (PDF generator injection), `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W6/performing-blind-ssrf-exploitation/SKILL.md` (Step 3).
  `[NEW] target`: `ssrf-renderer-script-ssrf` (a fourth `ssrf` variant).
  `rationale`: the sink is a renderer or headless browser that executes injected markup; the caller supplies code, not a destination. The bent step is "inject executable content the renderer runs, read the interior response, and exfiltrate it out of band". No parent step covers response reading plus arbitrary egress from inside the fetcher. Baseline fit: the `ssrf` baseline (a fetch sink that consumes caller-influenced content) holds. Flag: medium-confidence. Branch 5a applies: blind renderer cases fold into `no-response-egress-inference`; direct renderer cases stand alone only if the response-reading step is read as uncovered.

**Enrichment candidates**
- `ObservableSignal` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-ssrf/SKILL.md` (blind-versus-full-read section): add the one-request blind-versus-full-read decision and the distinct-status-on-link-local signal.
- `AttackTechnique` <- same source (attribution discipline): add one fresh token per candidate parameter plus the negative control to `Testing Methodology`.
- `AttackTechnique` <- same source (app-layer encoding bypass): add the wrapper-decoding carrier (encoded or base64 destination decoded before fetch, decode-pass count as the bug) to `Bypass Techniques`.
- `AttackTechnique` <- same source (path-normalization bypass): add the edge-versus-origin path-confusion carrier, naming the `proxy-techniques` family.
- `AttackTechnique` <- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/cloud-security/aws-imdsv2-ssrf-bypass/SKILL.md`: add the environment-derived credential path and the token-then-read method and header pair to `Gated Destinations` as an abstract shape.
- `PreconditionEnvironment` <- same source (Phase 2 note): add the GET-only-versus-method-control precondition as a false-positive exclusion for gated reads.

**References/scripts candidates**
- `/Users/diekgbbtt/claude-bug-hunter/skills/security-arsenal/SKILL.md` SSRF IP-bypass table is generalizable to a `PayloadPattern` reference after de-concretization.
- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W6/performing-blind-ssrf-exploitation/scripts/agent.py` is not generalizable.

## Residual candidates

These are source techniques with no adequate home in the current suite.
Each is reported as a candidate for a new class or a new variant, with the baseline question stated.

1. **Client-side path traversal (CSPT)**.
   `source`: `/Users/diekgbbtt/hacking-skills/skills/web/client-side/cspt/SKILL.md`.
   `[NEW] target`: `client-side-path-traversal`.
   `rationale`: caller input concatenated into the path of a client-side `fetch` or XHR traverses to a different endpoint, then chains to response injection, XSS, or internal-endpoint access. The suite's `path-traversal-lfi-rfi` is server-side (file read, include execution); its steps do not cover a client-side request-path traversal. No baseline exists, so a class is required, not a variant. Flag: medium-confidence; the operator may fold it into `path-traversal-lfi-rfi` as a client-side variant if that class's baseline is read as transport-independent.

2. **CSS injection and exfiltration**.
   `source`: `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-dom/SKILL.md` (Phase 4), `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W4/performing-content-security-policy-bypass/SKILL.md` (Steps 5-6).
   `[NEW] target`: `css-injection-exfiltration`.
   `rationale`: attribute-selector rules leak a token character by character to an out-of-band host with no JavaScript. This executes no script, so `xss` does not own it. `information-disclosure` variants are error, stored-artifact, and differential-oracle, none of which describes a stylesheet oracle. No baseline exists. Flag: low-confidence on naming; the technique is real and the suite is silent on it.

3. **WebSocket security and CSWSH**.
   `source`: `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/web-vulnerabilities/websocket-hijacking-testing/SKILL.md`, `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-websocket/SKILL.md`, `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W5/testing-websocket-api-security/SKILL.md`.
   `[NEW] target`: `websocket-security`.
   `rationale`: handshake authentication, per-message authorization, message injection, and hijacking are not covered. The suite holds only `csrf-websocket-handshake` (the CSRF-shaped handshake) and mentions. A class is required.

4. **Clickjacking and UI redressing**.
   `source`: `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/web-vulnerabilities/clickjacking-ui-redressing/SKILL.md`, `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-clickjacking/SKILL.md`, `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W4/performing-clickjacking-attack-test/SKILL.md`.
   `[NEW] target`: `clickjacking`.
   `rationale`: framing-based UI redressing has no home. The suite mentions it only inside `csrf`. A class is required.

5. **CORS misconfiguration**.
   `source`: `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/web-vulnerabilities/cors-misconfiguration-exploitation/SKILL.md`, `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-cors/SKILL.md`, `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W4/testing-cors-misconfiguration/SKILL.md`.
   `[NEW] target`: `cors-misconfiguration`.
   `rationale`: origin-reflection, null-origin trust, and subdomain-regex bypass cross-origin data reads have no home. The suite mentions CORS only inside `csrf` and `authentication-jwt`. A class is required.

6. **HTTP parameter pollution**.
   `source`: `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W9/performing-http-parameter-pollution-attack/SKILL.md`.
   `[NEW] target`: `http-parameter-pollution`.
   `rationale`: duplicate-parameter precedence differences between front-end and back-end bypass validation and WAF rules. The suite mentions it only inside `idor`. The `defence-bypass` family covers signature evasion, not duplicate-parameter precedence. Candidate as a new class or as a `defence-bypass` leaf; the operator decides. Flag: medium-confidence.

7. **LDAP and XPath injection**.
   `source`: `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-ldap/SKILL.md`.
   `[NEW] target`: `ldap-xpath-injection`.
   `rationale`: a directory-filter and XML-query interpreter family with auth bypass and blind attribute exfiltration. The `nosql-injection` class owns operator, script, aggregation, query-language, and command-protocol variants for document stores; it does not cover directory or XPath grammars. Candidate as a new class or a `nosql-injection` sibling. Flag: medium-confidence.

8. **SAML and SSO assertion attacks**.
   `source`: `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-saml/SKILL.md`.
   `[NEW] target`: `saml-sso-attacks`.
   `rationale`: XML signature wrapping, assertion comment injection, and parser-differential SSO bypass. The suite has `oauth` and `authentication-jwt`; neither covers XML assertion signing. Candidate as a new class or an `authentication-jwt` sibling. Flag: medium-confidence.

9. **Email and SMTP header injection**.
   `source`: `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W3/testing-for-email-header-injection/SKILL.md`.
   `[NEW] target`: none proposed as a class.
   `rationale`: the technique is the parent `header-injection` line-break primitive on a different transport, so it is reported as enrichment above. It is listed here only to record that a class was considered and rejected for baseline fit.

10. **Supply chain and CI/CD pipeline attacks**.
    `source`: `/Users/diekgbbtt/claude-bug-hunter/skills/supply-chain-attack-recon/SKILL.md`, `hunt-cicd`, `/Users/diekgbbtt/hacking-skills/skills/cicd/*`.
    `[NEW] target`: `supply-chain-cicd`.
    `rationale`: dependency confusion, workflow injection, and runner poisoning have no home in the suite. Out of this slice's thematic reach but a genuine suite gap.

11. **Cloud IAM and identity attacks**.
    `source`: `/Users/diekgbbtt/claude-bug-hunter/skills/cloud-iam-deep/SKILL.md`, `m365-entra-attack`, `okta-attack`, `hunt-cloud-misconfig`, `/Users/diekgbbtt/awsome-offensive-security-skill/skills/cloud-security/*`.
    `[NEW] target`: `cloud-iam-privilege-escalation`.
    `rationale`: cloud IAM enumeration and privilege escalation is a large source area with no suite home. Out of this slice's thematic reach but a genuine suite gap.

12. **MFA and account-recovery bypass**.
    `source`: `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-mfa-bypass/SKILL.md`, `hunt-forgot-password`, `hunt-ato`.
    `[NEW] target`: `mfa-recovery-bypass`.
    `rationale`: MFA-step skip, recovery-token abuse, and the account-takeover taxonomy have no dedicated home. `authentication-jwt` covers token and flow, and `weak-credential-discovery` covers default credentials and enumeration, but neither covers MFA enforcement gaps. Flag: low-confidence, because `business-logic` and `authentication-jwt` partly overlap.

## Slice summary

- Groups covered: 6. Base skills read: 24 (6 parents, 18 variants).
- Sufficient similarity found for every base skill. No source was matched at a higher similarity than its base counterpart, so no cross-source merge is warranted.
- New-skill proposals: 2.
  - `[NEW] xss-dom-clobbering` (source `hunt-dom` and the anthropic CSP skill; medium-confidence).
  - `[NEW] ssrf-renderer-script-ssrf` (source `hunt-ssrf`, `hacking-skills` ssrf, and the anthropic blind-ssrf skill; medium-confidence, branch 5a applies).
- Enrichment candidates: 42 across the six groups, mapped to ontology entities (`AttackTechnique`, `ObservableSignal`, `DefensiveControl`, `PreconditionEnvironment`, `PayloadPattern`, `Artifact`).
  Highest-value: routing-based SSRF and OIDC issuer reflection in `header-injection`; cleartext-upgrade and tunnel shapes in `http-request-smuggling`; the different-requests race and first-sequence-sync in `race-conditions`; privileged-daemon config injection and argument-file expansion in `rce`; postMessage, service-worker, and mutation-XSS shapes in `xss`; blind-versus-full-read and attribution discipline in `ssrf`.
- References/scripts candidates: the `security-arsenal` payload banks are generalizable after de-concretization for `header-injection`, `http-request-smuggling`, `race-conditions`, `rce`, `xss`, and `ssrf`. The anthropic `agent.py` scripts are not generalizable.
- Residual candidates: 12 reported.
  Strongest with no baseline and a clear bent step: client-side path traversal, CSS injection and exfiltration, WebSocket and CSWSH, clickjacking, CORS misconfiguration.
  Operator-decision residuals: HTTP parameter pollution, LDAP and XPath injection, SAML and SSO, supply chain and CI/CD, cloud IAM, MFA and recovery bypass.
- Low-confidence flags recorded inline: routing SSRF placement, binary-translation desync, config-as-code injection, DOM-clobbering as variant versus class, renderer-script SSRF, and the naming of CSS injection and HTTP parameter pollution.
- Boundary discipline applied: every proposal was checked against the suite baseline and against `docs/design/skills-variant-boundary.md`. Technology-stack and version tables were rejected as ontology NEVER. No suite skill was edited and no git command was run.
