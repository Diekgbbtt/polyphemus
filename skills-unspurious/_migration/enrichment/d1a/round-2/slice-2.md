# D1a enrichment, round 2, slice 2

*Round 2 is independent of round 1 by design. This report does not read the round-1 reports, proposal, or rulings. The synthesis compares the rounds afterward.*

## Slice header

**Groups (level-1 directories under `skills-unspurious/`) and their level-2 variant leaves:**

| Group (class skill) | Variant leaves | Base skills |
|---|---|---|
| `broken-function-level-authorization` | `bfla-alternate-path`, `bfla-client-identity-trust`, `bfla-deferred-execution` | 4 |
| `idor` | `idor-direct-object-swap`, `idor-collection-batch-scope`, `idor-deferred-artifact-redemption`, `idor-context-carrier-substitution`, `idor-nested-expansion-binding` | 6 |
| `information-disclosure` | `error-verbosity-disclosure`, `stored-artifact-disclosure`, `differential-oracle-disclosure` | 4 |
| `mass-assignment` | `mass-assignment-nested-relation-write`, `mass-assignment-bulk-collection-injection`, `mass-assignment-bulk-nested-relation-write` | 4 |
| `business-logic` | `concurrent-duplication`, `value-domain-manipulation`, `quota-window-slicing`, `async-boundary-abuse` | 5 |
| `two-principal-authz` | none (methodology skill, no leaves) | 1 |

**Base skills in slice: 24** (6 parents plus 18 variant leaves).
**Sources indexed: 346 skill files** across the four source repos (`hacking-skills` 43, `claude-bug-hunter` 83, `anthropic-cybersecurity-skills/accepted` 82, `awsome-offensive-security-skill` 138).
**Normative docs read:** `docs/design/skills-variant-boundary.md`, `docs/design/skills-ontology.md`. Boundary evidence also drawn from `skills-unspurious/_analysis/<class>.md` (STATE 6 and STATE 7).

**Section convention.** Each section below is one class (the group parent). Within it, the parent and each variant leaf are addressed, because the leaves are the base skills that own the bent steps. Enrichment targets name the exact leaf when a leaf owns the step, and the parent otherwise.

**Algorithm note.** For each class: matched candidates by vulnerability class or by chainable reasoning; assessed sufficiency; applied the boundary test (accurate and exhaustive); abstracted covered diffs to ontology entities as surgical enrichments; escalated only diffs that bend a step no parent step covers, or that capture several entities and at least one boundary attribute. Proposals are flagged by confidence.

---

## broken-function-level-authorization

Class signature (from `_analysis/broken-function-level-authorization.md`): D1 enforcement locus, D2 identity source, D3 execution time. Variants: `bfla-alternate-path` (D1, step S3), `bfla-client-identity-trust` (D2, step S4), `bfla-deferred-execution` (D3, step S5).

### Sources matched

- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W2/exploiting-broken-function-level-authorization/SKILL.md` (direct class match; OWASP API5 BFLA)
- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W2/testing-for-broken-access-control/SKILL.md` (A01 umbrella covering function-level checks)
- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W2/bypassing-authentication-with-forced-browsing/SKILL.md` (unprotected admin/interface discovery)
- `/Users/diekgbbtt/hacking-skills/skills/web/authz/authz-bypass/SKILL.md` (horizontal and vertical bypass; routing-header override; IP-header bypass)
- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/deep-dive-labs/access-control/SKILL.md` (PortSwigger access-control labs: Referer gate, URL override, method swap, multi-step)
- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/api-security/api-authentication-bypass/SKILL.md` (broader auth/authz bypass)
- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-shadow-api/SKILL.md` (old-version route with weaker authz)

### Similarity

Sufficient. The ACS BFLA skill and the HS authz-bypass skill are the same class at a lower abstraction (tool-specific, concrete). Macro semantic diff against the parent is mostly covered:

- Admin-endpoint discovery and method manipulation map to `bfla-alternate-path` (S3) as an aspect.
- Path-normalisation bypass set (case variation, URL encoding, dot-segment, semicolon insertion, extension addition, trailing slash) maps to `bfla-alternate-path` (permissive parser chain) as an aspect.
- API-version fallback (`/v1/`, `/beta/`, `/legacy/`) maps to `bfla-alternate-path` (shadow or legacy route) as an aspect.
- Parameter-based escalation (`role`, `is_admin`, `X-Tenant-Id`, `X-Organization`) maps to `bfla-client-identity-trust` (S4) as an aspect.
- Nothing in the ACS BFLA skill touches deferred execution, so `bfla-deferred-execution` has no competitor.

### Boundary

The parent covers the three discriminators. Forced browsing and the Referer gate are the two values that do not fully cover (see below).

### New-skill proposals

**Proposal 1 (medium confidence).** `source`: `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/deep-dive-labs/access-control/SKILL.md` (Lab 13, Referer-based access control); secondary `source`: `/Users/diekgbbtt/hacking-skills/skills/web/authz/authz-bypass/SKILL.md` (routing-header override) and `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W2/bypassing-authentication-with-forced-browsing/SKILL.md` (unprotected-interface reach).
`[NEW] target`: `bfla-client-hint-authorization-trust` (a fourth BFLA variant).
Rationale: the service derives the authorization verdict from a client-supplied request value that is not the actor credential. The Referer header is navigation provenance, not an identity source, so `bfla-client-identity-trust` (D2 "whose identity") does not cover it. The routing-header override (`X-Original-URL`, `X-Rewrite-URL`) and the IP-origin header (`X-Forwarded-For`) are the same kind of value: a client-supplied hint that decides the verdict. The boundary attribute that diverges is the trust-assumption difference: the service assumes a hint proves entitlement. Two ontology entities are captured beyond the covered diff (`PreconditionEnvironment`: a gate keyed on a client-supplied hint; `AttackTechnique`: contradict the hint while holding the credential). The baseline fits: the suite has BFLA plus the `two-principal-authz` role ladder.
Boundary caveat: the synthesis may prefer to fold the Referer gate into `bfla-client-identity-trust` as an aspect, because the parent step "trace the actor value from the edge inward" is close. The routing-header override is already an aspect of `bfla-alternate-path`. Flag for ruling.

### Enrichment candidates

- `AttackTechnique` and `DefensiveControl` <- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W2/exploiting-broken-function-level-authorization/SKILL.md`: the path-normalisation bypass set (case, URL encoding, dot-segment, semicolon, extension addition, trailing slash) and the API-version fallback list. Target leaf `bfla-alternate-path` (the parent Bypass section names route shadowing but not the normalisation set).
- `AttackTechnique` <- `/Users/diekgbbtt/hacking-skills/skills/web/authz/authz-bypass/SKILL.md`: the spoofable forwarding-header family (`X-Forwarded-For`, `X-Forwarded-For` misspelling, `X-Remote-IP`, `X-Originating-IP`, `X-Remote-Addr`, `X-Client-IP`) used to defeat a network-origin allowlist. Target leaf `bfla-client-identity-trust` (a hint source beyond gateway identity headers).
- `AttackTechnique` <- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/deep-dive-labs/access-control/SKILL.md` (Lab 12): a multi-step workflow whose authorization is missing on one step (skip to the confirmation step). Target parent and `bfla-deferred-execution` (the deferred clause is adjacent but the missing-step-on-one-transition case is a distinct sub-block).
- `PreconditionEnvironment` <- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W2/bypassing-authentication-with-forced-browsing/SKILL.md`: an unlinked administrative or debug interface reachable without an actor. Target parent `## Attack Surface` and `## Reconnaissance`.

### References/scripts candidates

- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W2/exploiting-broken-function-level-authorization/SKILL.md`: the role-matrix harness (`ROLE_MATRIX` loop over unauthenticated, regular, moderator, admin) plus the admin-path and admin-function wordlists. Sufficiently generalised once product names are stripped: the loop is class-shaped (subject x action x expected-minimum-role), not product-shaped. Candidate for `references/role-matrix-harness.md`.
- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W2/testing-for-broken-access-control/SKILL.md`: the endpoint x role access-control matrix workflow and the Authorize-style replay configuration. Generalisable. Candidate for the same reference.
- `/Users/diekgbbtt/hacking-skills/skills/web/authz/authz-bypass/SKILL.md`: the forwarding-header probe loop. Generalisable. Candidate for `references/hint-header-probes.md`.

---

## idor

Class signature (from `_analysis/idor.md`): D1 authorization cardinality (singleton versus set), D2 storage-bound deferred redemption, D3 identity carrier (reference versus context channel), D4 binding depth (single hop versus nested). Variants: `idor-direct-object-swap`, `idor-collection-batch-scope` (D1), `idor-deferred-artifact-redemption` (D2), `idor-context-carrier-substitution` (D3), `idor-nested-expansion-binding` (D4).

### Sources matched

- `/Users/diekgbbtt/hacking-skills/skills/web/authz/bola-idor/SKILL.md` (direct class match; second-order, JSON globbing, deprecated version)
- `/Users/diekgbbtt/hacking-skills/skills/web/logic/graphql-idor-via-introspection-leak/SKILL.md` (resolver-hop and node-GID)
- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W2/testing-api-for-broken-object-level-authorization/SKILL.md` (BOLA harness; batch, nested, method)
- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W2/exploiting-idor-vulnerabilities/SKILL.md` (non-obvious locations)
- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-idor/SKILL.md` (rich; six named chains; soft-delete persistence)
- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-fintech-graphql/SKILL.md` (asymmetric source/destination authorization)
- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/api-security/broken-object-level-authorization/SKILL.md` (two-account discipline; bypass set)
- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/web-vulnerabilities/idor-vulnerability-hunting/SKILL.md` (eight advanced techniques)
- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/apis/graphql-idor/SKILL.md` (node ID, aliases, mutations)

### Similarity

Sufficient and strong. The class is the same and the source variants map almost one-to-one onto the suite's five leaves. Macro semantic diff:

- JSON globbing, wildcard, array, and type-swapped identifier forms map to the parent reference-form aspect (the analysis records identifier form as a non-discriminator aspect for corpus building).
- Second-order or async-job IDOR maps to `idor-deferred-artifact-redemption`.
- GraphQL node or relay traversal and fragment overfetch map to `idor-nested-expansion-binding`.
- Batch or array-of-IDs and import paths map to `idor-collection-batch-scope`.
- Deprecated API-version fallback, extension append (`.json`), static-keyword swap (`me` to numeric), and nested-JSON wrapper are defeat aspects, not bent steps.

### Boundary

No new-skill proposal for this class. Every source diff bends a step a parent step already covers, or is an aspect. The one value worth explicit boundary reasoning is the asymmetric source/destination authorization probe (below), which folds into `idor-direct-object-swap`.

### New-skill proposals

None.

Boundary reasoning recorded for the synthesis: `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-fintech-graphql/SKILL.md` (step 5) and `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/logic-flaws/business-logic-bypass/SKILL.md` (Phase 5) describe an asymmetric authorization probe: the destination argument is validated while the source argument is not. The parent step "swap object references between principals using the same token" covers a source-argument swap accurately and exhaustively, so this is an aspect, not a variant. It captures no boundary attribute (cardinality, timing, carrier, and depth are unchanged). Classified as enrichment, not a proposal.

### Enrichment candidates

- `AttackTechnique` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-fintech-graphql/SKILL.md`: the asymmetric-argument probe (identify which member of a paired object argument carries the check, then target the unchecked member). Target leaf `idor-direct-object-swap`.
- `AttackTechnique` <- `/Users/diekgbbtt/hacking-skills/skills/web/authz/bola-idor/SKILL.md` and `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/web-vulnerabilities/idor-vulnerability-hunting/SKILL.md`: deprecated API-version fallback, extension append, and static-keyword swap (`me` to numeric) as binding-bypass paths. Target parent `## Bypass Techniques` (the parent names content-type switching, method tunnelling, and parameter pollution but not version fallback or extension append).
- `AttackTechnique` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-idor/SKILL.md` (Chain 5): soft-delete persistence, where a removed principal's session or personal-access token still passes. Target parent `## Key Vulnerabilities` as a temporal binding sub-block. Low confidence that it belongs to IDOR rather than to session revocation in `authentication-jwt`; flag for ruling.
- `Chaining Attacks` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-idor/SKILL.md`: the six named IDOR chains (email-change to reset to ATO; download to filename-controlled header to session theft; GraphQL node relay; team-member mass-assignment to owner; soft-delete persistence; double-IDOR refund). Target parent `## Chaining Attacks` (the parent has four bullets; the source taxonomy is more precise about the terminal state-change primitive).

### References/scripts candidates

- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W2/testing-api-for-broken-object-level-authorization/SKILL.md`: the BOLA harness (baseline capture, swap loop, batch, nested, method, Autorize configuration) plus the identifier-predictability table. Sufficiently generalised once product names and endpoints are parameterised. Candidate for `references/bola-control-pair-harness.md`.
- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-idor/SKILL.md`: the ID-enumeration and JavaScript-scrape patterns, and the Gate 0 validation gate. Generalisable. Candidate for `references/identifier-harvesting.md`.
- `/Users/diekgbbtt/hacking-skills/skills/web/authz/bola-idor/SKILL.md`: the JSON-globbing payload block. Generalisable as an example payload set.

---

## information-disclosure

Class signature (from `_analysis/information-disclosure.md`): three mechanism discriminators (verbosity, shared artifact, oracle). Variants: `error-verbosity-disclosure` (P3), `stored-artifact-disclosure` (P4), `differential-oracle-disclosure` (P2).

### Sources matched

- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W5/exploiting-excessive-data-exposure-in-api/SKILL.md` (property-level read over-exposure)
- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W5/testing-for-sensitive-data-exposure/SKILL.md` (client-side secrets, browser storage, masking)
- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W5/detecting-broken-object-property-level-authorization/SKILL.md` (BOPLA read half)
- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-source-leak/SKILL.md` (source maps, `.git`, `.env`, build artifacts)
- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-exceptional-conditions/SKILL.md` (verbose-error signatures)
- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-springboot/SKILL.md`, `hunt-laravel/SKILL.md`, `hunt-aspnet/SKILL.md` (framework debug surfaces)
- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-ntlm-info/SKILL.md` (authentication-challenge metadata)
- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/deep-dive-labs/info-disclosure/SKILL.md` (PortSwigger info-disclosure labs)
- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/web-vulnerabilities/spring-boot-actuator-abuse/SKILL.md`

### Similarity

Sufficient. Macro semantic diff:

- Debug and profiler surface enumeration (phpinfo, actuator env/heapdump/loggers/mappings, Telescope/Horizon, trace.axd, elmah.axd) maps to `error-verbosity-disclosure` (P3). Covered; framework names abstract out.
- Source-map reconstruction, `.git` dump, `.env` and build-info exposure map to `stored-artifact-disclosure` (P4). Covered.
- Live schema and introspection enumeration maps to `stored-artifact-disclosure` (P4). Covered.
- Cross-channel and method or conditional differentials map to `differential-oracle-disclosure` (P2). Covered.
- Excessive data exposure (the API returns fields the UI does not render, for the caller's own object) does not map to any parent step. See below.
- NTLM or Negotiate challenge metadata is a fourth mechanism. See Residual candidates.

### Boundary

Two values diverge from the parent. Excessive data exposure diverges on the trust-assumption attribute (field-scope entitlement versus identity-scope entitlement) and on the reconnaissance attribute (field-family enumeration versus surface enumeration). The protocol-challenge mechanism diverges on the mechanism attribute but needs a protocol baseline the suite lacks, so it is reported as a residual rather than a formal proposal.

### New-skill proposals

**Proposal 2 (medium confidence).** `source`: `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W5/exploiting-excessive-data-exposure-in-api/SKILL.md`; secondary `source`: `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W5/detecting-broken-object-property-level-authorization/SKILL.md` (read half) and `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W5/testing-for-sensitive-data-exposure/SKILL.md`.
`[NEW] target`: `excessive-field-disclosure` (a fourth `information-disclosure` variant).
Rationale: the caller's own resource renders fields the caller is not entitled to see (password hash, SSN, internal notes, risk score, staff metadata). No parent step covers "compare the raw response field set against the rendered field set for one identity and classify the excess by sensitivity". The parent's differential harness compares identities (anonymous, owner, non-owner), not the raw response against the rendered representation. The parent's `stored-artifact-disclosure` fetches deployables; this technique reads a live response schema. The trust-assumption clause that fails is the field-scope clause: the agreement "every channel renders exactly what the caller is entitled to see" is broken by field scope rather than by identity scope. Multiple ontology entities are captured: `AttackTechnique` (field-set diff plus sensitive-field pattern scan), `PreconditionEnvironment` (a serializer that emits the full model), `ObservableSignal` (excess sensitive fields), and `PayloadPattern` (sensitive-field name and value families). The baseline fits: `information-disclosure` plus the `two-principal-authz` identity core exist.
Boundary caveat: `differential-oracle-disclosure` already covers "per-channel field extras where parallel representations of one object disagree on fields". The UI-versus-raw comparison is close to a representation delta, so the synthesis may fold this in as an aspect. The distinguishing fact is that this variant does not need a second representation and does not rely on a delta; it scans one response for fields no representation should carry. Flag for ruling.

### Enrichment candidates

- `AttackTechnique` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-springboot/SKILL.md`, `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-laravel/SKILL.md`, `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-aspnet/SKILL.md`, and `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/web-vulnerabilities/spring-boot-actuator-abuse/SKILL.md`: the debug-surface families (environment dump, heap dump, logger control, route mappings, trace and error endpoints, diagnostic consoles). Target leaf `error-verbosity-disclosure` (abstracted to families, product names stripped).
- `AttackTechnique` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-source-leak/SKILL.md`: content-hashed artifact re-verification (a 404 at the recorded hashed URL is a new build, not remediation) and source-map reconstruction. Target leaf `stored-artifact-disclosure`.
- `AttackTechnique` <- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W5/testing-for-sensitive-data-exposure/SKILL.md`: client-side secret scanning (bundle and browser storage) and data-masking and redaction checks. Target leaf `stored-artifact-disclosure` and parent `## Attack Surface`.
- `Chaining Attacks` <- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/deep-dive-labs/info-disclosure/SKILL.md` (Lab 4): a disclosure that names an authorization header (`X-Custom-IP-Authorization`) which then grants admin. Target parent `## Chaining Attacks` (disclosure to BFLA chain).
- `ObservableSignal` <- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/deep-dive-labs/info-disclosure/SKILL.md` (Lab 7): data returned in the response body before a redirect fires. Target leaf `differential-oracle-disclosure` and parent `## Detection Channels`.

### References/scripts candidates

- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-source-leak/SKILL.md`: the quick-win path list, the source-map extraction script, the Swagger or OpenAPI parse, the `.git` dumper, and the chunk-secret grep. Highly generalised (paths and regexes are reusable as examples). Candidate for `references/artifact-harvesting.md`.
- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-exceptional-conditions/SKILL.md`: the cross-framework error-signature list (Sequelize, PHP, Python, Java, .NET). Generalisable as a detection reference. Candidate for `references/error-signatures.md`.

---

## mass-assignment

Class signature (from `_analysis/mass-assignment.md`): D1 binding depth (flat versus nested), D2 binding cardinality (singleton versus bulk). Variants: `mass-assignment-nested-relation-write` (D1), `mass-assignment-bulk-collection-injection` (D2), `mass-assignment-bulk-nested-relation-write` (D1 x D2).

### Sources matched

- `/Users/diekgbbtt/hacking-skills/skills/web/authz/mass-assignment/SKILL.md` (direct class match)
- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W5/exploiting-mass-assignment-in-rest-apis/SKILL.md`
- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W5/testing-api-for-mass-assignment-vulnerability/SKILL.md`
- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W5/detecting-broken-object-property-level-authorization/SKILL.md` (write half)
- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/api-security/api-mass-assignment-exploitation/SKILL.md`
- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/apis/mass-assignment-exploitation/SKILL.md`
- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-api-misconfig/SKILL.md` (mass-assignment section)
- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/deep-dive-labs/access-control/SKILL.md` (Lab 4, role field in profile update)

### Similarity

Sufficient and strong. Macro semantic diff:

- Duplicate-key parameter pollution (`role=user&role=admin`) maps to the parent `## Bypass Techniques` (duplicate keys) as an aspect.
- Content-type switching, XML body, and key-path reshaping map to the parent bypass and name the `defence-bypass` family. Covered.
- Schema-derived field enumeration (OpenAPI `components.schemas`, GraphQL input types) maps to parent `## Reconnaissance` (interface descriptions and client bundles). Covered.
- Hidden-parameter discovery (Arjun, param-miner) maps to parent `## Reconnaissance`. Covered.
- Registration-time binding and order or financial object binding map to parent `## Key Vulnerabilities`. Covered.
- Property-level read over-exposure (the BOPLA read half) belongs to `information-disclosure` (see Proposal 2), not here.

### Boundary

No new-skill proposal. Every source diff bends a step the parent covers (S6 nested, S6 bulk) or is a shared defeat aspect. No boundary attribute diverges.

### New-skill proposals

None.

### Enrichment candidates

- `AttackTechnique` <- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W5/exploiting-mass-assignment-in-rest-apis/SKILL.md`: explicit registration-path and order-object binding emphasis, and the create-path versus update-path distinction. Target parent `## Key Vulnerabilities`.
- `AttackTechnique` <- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/apis/mass-assignment-exploitation/SKILL.md`: the blind-field-fuzzing candidate wordlist (privilege, verification, financial, ownership families). Target parent `## Reconnaissance`.
- `AttackTechnique` <- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W5/detecting-broken-object-property-level-authorization/SKILL.md`: the "restore original value after the probe" discipline for a destructive update path. Target parent `## Pro Tips` and `## False Positives`. Low confidence (minor).

### References/scripts candidates

- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W5/testing-api-for-mass-assignment-vulnerability/SKILL.md`: the field-injection plus state-verification harness and the framework-specific testing matrix (Rails, Django, Laravel, Spring). Generalisable once framework names abstract to binder families. Candidate for `references/binding-probe-harness.md`.
- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W5/detecting-broken-object-property-level-authorization/SKILL.md`: the sensitive-property pattern map and the injected-field list. Generalisable as an example payload set.

---

## business-logic

Class signature (from `_analysis/business-logic.md`): one discriminator, `AttackTechnique`, with four values (sequential transition manipulation is the parent core). Variants: `concurrent-duplication`, `value-domain-manipulation`, `quota-window-slicing`, `async-boundary-abuse`.

### Sources matched

- `/Users/diekgbbtt/hacking-skills/skills/web/logic/business-logic-flaws/SKILL.md` (direct class match)
- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W6/testing-for-business-logic-vulnerabilities/SKILL.md`
- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-business-logic/SKILL.md` (rich; 12 disclosed cases; rate-limit bypass; forged webhook)
- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-fintech-graphql/SKILL.md` (ledger, idempotency, rounding)
- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/logic-flaws/business-logic-bypass/SKILL.md`
- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/deep-dive-labs/business-logic/SKILL.md` (PortSwigger labs: infinite money, coupon alternation, dual-use endpoint)
- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W5/performing-api-rate-limiting-bypass/SKILL.md` (header-rotation counter evasion)

### Similarity

Sufficient and strong. Macro semantic diff:

- Coupon stacking and alternating-code abuse map to parent `## Key Vulnerabilities` (Commerce Flows, discount stacking). Covered.
- Negative quantity, integer overflow, and currency or type mismatch map to `value-domain-manipulation`. Covered.
- Workflow step skip, out-of-order transitions, and the flawed state machine map to the parent core (State Machine Abuse). Covered.
- Idempotency-key replay and double-spend map to `concurrent-duplication` and `async-boundary-abuse`. Covered.
- Rounding, sub-cent drift, and cross-currency arbitrage map to `value-domain-manipulation`. Covered.
- Instrument arbitrage loops and header-rotation counter evasion are the two values that need boundary reasoning (below).

### Boundary

Two candidate values were tested. Both fail the variant test and resolve to enrichments, because the parent already covers the step.

- Instrument arbitrage loop (buy with a discount, redeem the instrument, net positive, repeat): the parent core covers "repetition" of a valid transition sequence, and the parent `## Reconnaissance` already lists conservation of value as an invariant. No new bent step. Enrichment.
- Header-rotation counter evasion (`X-Forwarded-For` rotation to obtain a fresh per-principal counter): the accounting clause is owned by `defence-bypass` (`defence-bypass-throttle-evasion`, "move the effect across the dimension a limit does not count"). `quota-window-slicing` owns only the atomic-reset clause. So this is a `defence-bypass` instance, not a business-logic variant. Enrichment that names the family at the counter step.

### New-skill proposals

None.

Rationale recorded for the synthesis: both candidate proposals were falsified by the boundary test. The instrument loop is the parent's sequential-transition core; the counter-key evasion is the `defence-bypass` accounting clause. Neither captures a boundary attribute beyond the existing signature.

### Enrichment candidates

- `AttackTechnique` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-business-logic/SKILL.md` and `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/deep-dive-labs/business-logic/SKILL.md` (Lab 10): the instrument arbitrage loop (cycle value between a purchase instrument and a redemption instrument so the cycle nets positive while each step is individually valid). Target parent `## Key Vulnerabilities` (Commerce Flows) and `value-domain-manipulation`.
- `DefensiveControl` and `AttackTechnique` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-business-logic/SKILL.md` and `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W5/performing-api-rate-limiting-bypass/SKILL.md`: header-rotation counter evasion, where the counter's principal key is derived from a client-supplied forwarding header. Target leaf `quota-window-slicing` `## Bypass Techniques`, naming the `defence-bypass` throttle-evasion family at the counter step.
- `AttackTechnique` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-fintech-graphql/SKILL.md`: the `Money` or `Decimal` scalar edge cases (scientific notation, oversized string, negative amount) and the alias-batched double-spend probe. Target leaf `value-domain-manipulation` and `concurrent-duplication`.
- `AttackTechnique` <- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W6/testing-for-business-logic-vulnerabilities/SKILL.md`: referral and reward-system abuse (self-referral, multi-account reward farming). Target parent `## Attack Surface` (Account lifecycle) as an aspect.
- `AttackTechnique` <- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/deep-dive-labs/business-logic/SKILL.md` (Lab 7): a dual-use endpoint where the server does not require the current credential for the privileged branch. Target parent and `two-principal-authz` (authorization-principal step). Low confidence (overlaps BFLA).

### References/scripts candidates

- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/logic-flaws/business-logic-bypass/SKILL.md`: the concurrent coupon-application race script and the step-skip script. Generalisable once endpoints parameterise. Candidate for `references/logic-probe-scripts.md`.
- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-business-logic/SKILL.md`: the disclosed-case citation table with root cause and payload subclass per case. Generalisable as an example corpus (strip concrete product names). Candidate for `references/logic-case-corpus.md`.

---

## two-principal-authz

This group is a methodology skill with no variant leaves. It carries the shared authorization agreement that `idor`, `broken-function-level-authorization`, and the other authorization classes reference at the principal step.

### Sources matched

- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W2/testing-for-broken-access-control/SKILL.md` (endpoint x role matrix, control pair)
- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W2/testing-api-for-broken-object-level-authorization/SKILL.md` (two-account control pair, baseline capture)
- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/api-security/broken-object-level-authorization/SKILL.md` (two-account discipline, "never test arbitrary IDs blindly")
- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-idor/SKILL.md` (two-account setup, Gate 0)
- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-spa-api/SKILL.md` (a gated sibling endpoint as a same-stack control)

### Similarity

Sufficient. The sources implement the same two-principal discipline the skill states. Macro semantic diff:

- Two-account control pair under identical shaping maps to the parent `## Advanced Techniques` (Matrix Discipline). Covered.
- Baseline capture of the owner's identifiers maps to the parent `## Reconnaissance` (Object Harvesting). Covered.
- Grant or token tested alone and with the session maps to the parent `## Bypass Techniques`. Covered.
- Selecting a gated sibling endpoint as a same-stack control does not map to a parent step. Enrichment.

### Boundary

No new-skill proposal. The skill is the shared baseline; the sources refine its apparatus rather than adding a variant.

### New-skill proposals

None.

### Enrichment candidates

- `AttackTechnique` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-spa-api/SKILL.md` (step 3): establish the control from a gated sibling endpoint on the same stack, so a differing response attributes to the binding rather than to the stack. Target parent `## Advanced Techniques` (Control Pair and Differential discipline).
- `AttackTechnique` <- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W2/testing-for-broken-access-control/SKILL.md`: the explicit expected-outcome matrix per role before testing, recorded as a reusable artifact. Target parent `## Reconnaissance` (Baseline Matrix). Low confidence (largely present).

### References/scripts candidates

- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/api-security/broken-object-level-authorization/SKILL.md`: the two-account setup and manipulation walkthrough. Generalisable as an example procedure.

---

## Residual candidates

Source material with no adequate home in the current suite. Ordered by confidence that the gap is real and in scope.

1. **Shadow or zombie API inventory and behavioral version diff (high confidence absent).**
   `source`: `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-shadow-api/SKILL.md`; `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W8/detecting-shadow-api-endpoints/SKILL.md`; `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W8/performing-api-inventory-and-discovery/SKILL.md`.
   `[NEW] class` (proposed): `api-inventory-shadow`.
   The technique is not one endpoint but the delta between what an old API version enforces and what the current version enforces on the same operation: enumerate the version surface, pull every reachable spec (including archived), then behavioral-diff auth, rate-limit, and validation strength. No suite class owns version-inventory or behavioral regression. It is adjacent to `bfla-alternate-path` (which owns the legacy route as one alternate path) and `information-disclosure` (which owns spec exposure), but neither owns the diff workflow. Boundary attributes that diverge: vulnerability-specific reconnaissance (version inventory and spec diff) and attack-surface part family (the version surface). The baseline fits: the suite has the route and spec surfaces.

2. **Forced browsing and unprotected-interface discovery (medium-high confidence absent).**
   `source`: `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W2/bypassing-authentication-with-forced-browsing/SKILL.md`; `/Users/diekgbbtt/hacking-skills/skills/web/auth/auth-bypass/SKILL.md`; `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/deep-dive-labs/access-control/SKILL.md` (Lab 1 and Lab 2).
   `[NEW] class or BFLA variant` (proposed): `forced-browsing`.
   The bent step is discovery of an unlinked administrative or debug interface and reaching it with no actor at all. The class trust assumption is different from BFLA: the interface is assumed unreachable (security by obscurity), not actor-checked. The suite's BFLA reconnaissance names admin consoles, but no parent step owns the discovery-plus-reach procedure, and the class presupposes a role ladder that forced browsing does not need. This overlaps Proposal 1 (client-hint authorization); the two may be one class or two variants.

3. **SPA backend-API route mapping from the JavaScript bundle (medium confidence).**
   `source`: `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-spa-api/SKILL.md`.
   `[NEW] technique leaf` (proposed): a reconnaissance procedure that maps a single-page app's backend hosts and routes from its bundle, then tests each route family unauthenticated against a gated control. The suite's `information-disclosure` names client bundles and source maps as surfaces, and BFLA names mobile clients as endpoint revealers, but no skill owns the bundle-to-route-to-authz-gap workflow. It chains `information-disclosure` (artifact harvest) into BFLA and IDOR. Boundary attribute: vulnerability-specific reconnaissance.

4. **Authentication-challenge metadata disclosure (medium confidence).**
   `source`: `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-ntlm-info/SKILL.md`.
   `[NEW] information-disclosure variant` (proposed): `protocol-challenge-disclosure`. An anonymous authentication handshake (NTLM or Negotiate Type-2 challenge) leaks NetBIOS domain, internal DNS forest, computer name, and directory timestamp. This is a fourth mechanism beyond verbosity, artifact, and oracle: the leak is elicited from a protocol negotiation, not a rendered failure or a fetched file. Baseline caution: the suite has no NTLM or Negotiate baseline, and the operator rule rejects a proposal that needs a baseline the suite lacks. Reported as a residual for that reason, not as a formal proposal. Confidence that it is a real gap: medium.

5. **Forged external confirmation (unsigned callback or webhook) (medium-low confidence).**
   `source`: `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-business-logic/SKILL.md` (Scenario 2 and root cause 4).
   `[NEW] business-logic variant` (proposed, low confidence): the attacker supplies a fake success confirmation to a payment callback with no signature validation. `async-boundary-abuse` owns compensation without origin success, which is the inverse direction. `csrf` owns forged cross-site requests but not unsigned server-to-server callbacks. The bent step is "accept an unauthenticated external confirmation as authoritative". Flag for ruling.

6. **MFA or 2FA bypass taxonomy (medium-high confidence absent).**
   `source`: `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-mfa-bypass/SKILL.md`; `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/logic-flaws/2fa-bypass/SKILL.md`.
   `[NEW] class` (proposed): `mfa-bypass`. Seven patterns (no rate limit on OTP, OTP not invalidated, response manipulation, MFA-step skip, race on verification, backup-code brute force, remember-this-device trust escalation). No suite class owns the second-factor flow. It is adjacent to `authentication-jwt` and `weak-credential-discovery` but distinct. Boundary attribute: vulnerability-specific reconnaissance and trust-assumption difference (the second factor is assumed enforced on every sensitive step).

7. **Account-takeover taxonomy as a chaining reference (medium confidence).**
   `source`: `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-ato/SKILL.md`.
   `[NEW] chaining reference or technique leaf` (proposed): eleven ATO paths. This is a cross-class chaining corpus rather than a class. It overlaps `authentication-jwt`, `oauth`, `open-redirect`, `weak-credential-discovery`, and `csrf`. Best treated as a `references/` chaining document on the relevant classes, not a new class.

8. **CORS misconfiguration (high confidence absent).**
   `source`: `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W4/testing-cors-misconfiguration/SKILL.md`; `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/web-vulnerabilities/cors-misconfiguration-exploitation/SKILL.md`; `/Users/diekgbbtt/hacking-skills/skills/web/client-side/cors-misconfig/SKILL.md`.
   `[NEW] class` (proposed): `cors-misconfiguration`. The suite mentions CORS only incidentally inside `csrf` and `authentication-jwt`. Not near this slice; recorded because it is a clear absent class.

9. **HTTP parameter pollution (medium confidence).**
   `source`: `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W9/performing-http-parameter-pollution-attack/SKILL.md`.
   `[NEW] class or `defence-bypass` variant` (proposed): client-side and server-side parameter pollution. The suite treats duplicate-key pollution as a shared defeat aspect inside `idor` and `mass-assignment`. A standalone class is defensible when server-side URL construction is in scope (see item 10).

10. **Server-side parameter pollution in backend URL construction (medium confidence).**
    `source`: `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-api-misconfig/SKILL.md` (server-side parameter pollution section).
    `[NEW] class or technique leaf` (proposed): the server interpolates user input into a backend URL path or query (`/field/passwordResetToken#`), enabling account takeover. Distinct from client-side HPP and from `ssrf` (the target is a server-side API call, not an arbitrary fetch). Boundary attribute: vulnerability-specific reconnaissance (routing feedback from errors).

11. **API rate-limit bypass via counter-key rotation (low confidence, likely owned).**
    `source`: `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W5/performing-api-rate-limiting-bypass/SKILL.md`; `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/api-security/api-rate-limit-bypass-techniques/SKILL.md`.
    Likely owned by `defence-bypass-throttle-evasion` (the accounting clause). Recorded as a residual only if the synthesis rules that the counter-identity failure is a class-specific gap rather than a control defeat. See the business-logic enrichment that names the family.

12. **Framework-specific debug-surface families (low confidence as a class; enrichment only).**
    `source`: `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-springboot/SKILL.md`, `hunt-laravel/SKILL.md`, `hunt-aspnet/SKILL.md`, `hunt-nextjs/SKILL.md`.
    These are product-specific instances of `error-verbosity-disclosure`. The abstraction rule strips product names, so the value is the debug-surface family list, not a class. Kept as enrichment (see information-disclosure section).

---

## Slice summary

**Coverage.** 24 base skills across 6 groups assessed. 4 groups matched directly to same-class sources (`broken-function-level-authorization`, `idor`, `information-disclosure`, `mass-assignment`, `business-logic`; 5 groups plus the `two-principal-authz` methodology). Sources were found in all four repositories for every group.

**Sufficiency pattern.** The sources are strongly similar to the suite but at a lower abstraction (tool-specific, concrete, product-named). Most diffs are covered by a parent step or are aspects. This is the expected pattern: the suite is a normalised, abstracted version of the same class.

**Formal new-skill proposals: 2.**
- Proposal 1 (medium): `bfla-client-hint-authorization-trust`, from the Referer, routing-header, and IP-origin gates (AWS access-control Lab 13; HS authz-bypass; ACS forced-browsing). Boundary: a client-supplied hint decides the authorization verdict, which is not an identity source.
- Proposal 2 (medium): `excessive-field-disclosure`, from excessive data exposure and BOPLA read (ACS excessive-data-exposure; ACS BOPLA). Boundary: field-scope entitlement versus identity-scope entitlement, and a sensitive-field scan rather than a representation delta.

Both proposals carry explicit boundary caveats and are flagged for ruling; either may fold into an existing leaf as an aspect.

**Falsified proposals: 2.**
- The IDOR asymmetric-argument probe folds into `idor-direct-object-swap` (the parent covers a source-argument swap).
- The business-logic instrument-arbitrage loop is the parent's sequential-transition core, and the header-rotation counter evasion is the `defence-bypass` accounting clause, so neither is a business-logic variant.

**Enrichment candidates: 18** across the groups, each mapped to an ontology entity and a target leaf. The strongest are the BFLA path-normalisation and hint-header sets, the IDOR asymmetric-argument and version-fallback techniques, the information-disclosure debug-surface families and content-hashed artifact discipline, the business-logic instrument-loop and counter-key naming, and the two-principal-authz gated-control selection.

**References/scripts candidates: 9**, each assessed as sufficiently generalised once product names and concrete endpoints are parameterised. The strongest are the BFLA role-matrix harness, the BOLA control-pair harness, and the artifact-harvesting and error-signature references.

**Residual candidates: 12.** The strongest, in-slice-adjacent gaps are the shadow or zombie API version diff, forced browsing, the SPA bundle-to-route-to-authz workflow, the authentication-challenge disclosure, and the MFA bypass taxonomy. Two residual gaps are clear suite-wide absences (CORS misconfiguration, HTTP parameter pollution). One residual (authentication-challenge disclosure) is reported as a residual rather than a proposal because it needs a protocol baseline the suite lacks.

**Low-confidence flags.** Proposal 1 boundary (Referer as aspect versus variant), Proposal 2 boundary (delta versus field scan), the soft-delete temporal IDOR placement, the forged external confirmation, the framework debug-surface class, and the counter-key residual.
