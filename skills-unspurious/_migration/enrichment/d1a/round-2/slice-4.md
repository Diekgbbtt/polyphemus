# D1a enrichment, round 2, slice 4

Work item W7 (C4-full enrichment), round 2, independent.
Report only.
No suite skill was modified.
No git command was run.

## Slice scope

Six groups of the base suite (`skills-unspurious/`).

| group | parent | variant leaves | reference files |
|---|---|---|---|
| nosql-injection | 1 | 5 | 0 |
| prototype-pollution | 1 | 2 | 0 |
| sql-injection | 1 | 5 | 0 |
| ssti | 1 | 2 | 2 |
| xxe | 1 | 3 | 0 |
| weak-credential-discovery | 1 | 4 | 0 |

Totals: 6 parent skills, 21 variant leaves, 2 reference files.
The algorithm was applied per the operator's specification.
Sources are read-only.

## Sources indexed

- `/Users/diekgbbtt/hacking-skills/skills` (43 files).
- `/Users/diekgbbtt/claude-bug-hunter/skills` (105).
- `/Users/diekgbbtt/anthropic-cybersecurity-skills` (399; layout `accepted/<cluster>/<skill>/SKILL.md` plus `catalog/catalog.json`, `classifications/`, `work/TAXONOMY.md`).
- `/Users/diekgbbtt/awsome-offensive-security-skill/skills` (370).

Relevant clusters for this slice: anthropic W3 (injection and data handling) and W1 (authentication and session); awsome `bug-hunting/web-vulnerabilities`, `bug-hunting/deep-dive-labs`, `bug-hunting/api-security`; claude-bug-hunter `hunt-*` skills; hacking-skills `web/injection` and `web/auth`.

---

## nosql-injection

Base: parent plus `nosql-operator-injection`, `nosql-server-side-script-injection`, `nosql-aggregation-pipeline-injection`, `nosql-query-language-injection`, `nosql-command-protocol-smuggling`.

**Sources matched**
- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-nosqli/SKILL.md` (primary).
- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W3/exploiting-nosql-injection-vulnerabilities/SKILL.md` (primary).
- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/deep-dive-labs/nosql-injection/SKILL.md` (PortSwigger lab playbook).
- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-sqli/SKILL.md` (adjacent, ORM and NoSQL cases).

**Similarity**
High.
All four sources cover operator injection, auth bypass, blind regex extraction, and `$where` script injection, which the base already owns across its five variants.
The base is the more abstract and complete treatment: it names the store families (document, key-value, search, wide-column, graph, schema layer) and the frame/grammar/stage clauses.
No source supplies a whole procedure the base lacks.

**Boundary**
The class discriminator per the base is the failing clause (value, grammar, script-surface, stage, frame).
The sources reinforce that axis rather than bending it.
Technology stack (MongoDB, CouchDB, Redis, Elasticsearch) is a runtime fact and stays out (ontology `TechnologyStack` = NEVER).

**New-skill proposals**
None.
Every source technique maps onto one existing variant.
Proposing a sixth variant would violate parsimony because no new bent step appears.

**Enrichment candidates**
- `AttackTechnique` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-nosqli/SKILL.md`: string-context `$where` breakout.
  When the app concatenates input into a JS `$where` string rather than accepting an operator object, the tester fuzzes quote and metacharacter probes then breaks the literal with a boolean payload.
  This sits between operator embedding and script bodies.
  Target variant: `nosql-query-language-injection` (literal-binding clause), or `nosql-server-side-script-injection` if the string is a script expression.
  Confidence: medium.
- `AttackTechnique` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-sqli/SKILL.md`: ORM raw-operator bypass where a mapper forwards a nested `match`/`populate` filter into a script operator.
  Target variant: `nosql-server-side-script-injection`.
  Confidence: medium.
- `AttackTechnique` <- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/deep-dive-labs/nosql-injection/SKILL.md`: unknown-field enumeration through a script predicate over the document key set.
  Target variant: `nosql-server-side-script-injection` blind extraction.
  Confidence: medium.
- `PayloadPattern` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-nosqli/SKILL.md`: array-notation carrier (`param[$gt]=`) and set-membership operator (`$in`) as alternate operator delivery.
  Already covered by the parent Bypass "Type Coercion" and "Operator Alternatives"; keep as an aspect, not a new entry.
  Confidence: high (no change needed).

**References/scripts candidates**
None.
The nosql-injection analysis marks scripted tests absent, and the sources add only concrete tool commands (nosqlmap) and concrete payload literals, which the abstractness rule excludes from the body and from references.

---

## prototype-pollution

Base: parent plus `prototype-pollution-client-side`, `prototype-pollution-server-side`.

**Sources matched**
- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W3/exploiting-prototype-pollution-in-javascript/SKILL.md` (primary).
- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/web-vulnerabilities/javascript-prototype-pollution/SKILL.md` (primary).
- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/web-vulnerabilities/prototype-pollution-rce/SKILL.md`.
- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/deep-dive-labs/prototype-pollution/SKILL.md`.
- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-nodejs/SKILL.md` (adjacent, Node gadget chains).
- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-api-misconfig/SKILL.md` (adjacent).

**Similarity**
High.
All sources present the same two-consumer shape the base owns: browser consumers (routing, auth state, rendering) and server consumers (template and process-spawning sinks).
The base already carries the merge-point discovery, the baseline canary, key shaping, and carrier switching.

**Boundary**
The class discriminator per the base is the consumer side (browser versus server), which the sources confirm.
Version and library identity are runtime facts and stay out (ontology `TechnologyStack` = NEVER).
Trust assumption is explicitly irrelevant as an axis for this class per the variant-boundary pitfalls, and no source bends that.

**New-skill proposals**
None.
No source introduces a consumer that bends a step beyond client and server.
A third variant would need its own bent step and would fail the divergence-delta criterion.

**Enrichment candidates**
- `AttackTechnique` <- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W3/exploiting-prototype-pollution-in-javascript/SKILL.md`: validation-schema bypass consumer.
  A polluted property that a schema validator reads (for example a permissive additional-properties flag) turns pollution into an input-validation bypass.
  Target variant: `prototype-pollution-server-side` Key Vulnerabilities (a third server consumer beside template and process sinks).
  Confidence: medium.
- `AttackTechnique` <- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W3/exploiting-prototype-pollution-in-javascript/SKILL.md`: coercion-crash denial of service through polluting a primitive-coercion method.
  Target variant: `prototype-pollution-server-side` or client-side; it is a consumer effect, not a new variant.
  Confidence: medium.
- `ObservableSignal` <- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W3/exploiting-prototype-pollution-in-javascript/SKILL.md`: status-code reflection as a pollution detector (pollute a status property and read the returned code).
  The parent Detection Channels already lists "Response deltas ... status codes"; keep as an aspect.
  Confidence: high (no change needed).
- `Artifact` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-nodejs/SKILL.md`: per-package gadget inventory.
  The base server-side variant already states "Gadget availability is inventory-specific"; keep as an aspect.
  Confidence: high (no change needed).

**References/scripts candidates**
None.
The prototype-pollution analysis marks scripted tests absent.
The sources add tool names (DOM Invader, ppfuzz, nuclei) which are runtime tooling facts, not a bulky proof to move into `references/`.

---

## sql-injection

Base: parent plus `sqli-union-extraction`, `sqli-error-based-extraction`, `sqli-boolean-blind-extraction`, `sqli-time-blind-extraction`, `sqli-oast-exfiltration`.

**Sources matched**
- `/Users/diekgbbtt/hacking-skills/skills/web/injection/sql-injection/SKILL.md` (primary).
- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-sqli/SKILL.md` (primary).
- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W3/exploiting-sql-injection-vulnerabilities/SKILL.md`.
- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W3/exploiting-sql-injection-with-sqlmap/SKILL.md`.
- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W3/performing-second-order-sql-injection/SKILL.md` (primary for the proposal).
- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W3/exploiting-api-injection-vulnerabilities/SKILL.md`.
- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/web-vulnerabilities/advanced-sql-injection-sqli/SKILL.md`.
- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/web-vulnerabilities/django-sql-injection/SKILL.md`.
- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/web-vulnerabilities/sqli-manual-and-automated/SKILL.md`.
- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/deep-dive-labs/sql-injection/SKILL.md`.

**Similarity**
High for the five extraction channels (union, error, boolean-blind, time-blind, oast), which the base owns and the sources restate at a lower abstraction level.
The base is the more abstract treatment and already names query builders, document operators, write and control primitives, and channel fallback.

**Boundary**
The class discriminator per the base is the extraction channel (rendering, shaping, truth-differencing, timing, egress).
The sources do not bend that axis.
They do surface one technique with its own bent step: second-order injection, which the base keeps only as an Advanced-Technique paragraph.

**New-skill proposals**

1. `source`: `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W3/performing-second-order-sql-injection/SKILL.md`, corroborated by `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/web-vulnerabilities/advanced-sql-injection-sqli/SKILL.md` (Phase 4) and `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-sqli/SKILL.md` (Salesforce SOQL second-order, Mozilla invite-code case).
   `[NEW] target`: `sqli-second-order-injection` (variant leaf under `sql-injection`).
   Rationale: second-order injection owns a bent step no parent step covers.
   The parent methodology is single-request: identify the query shape, confirm the class, establish the channel.
   Second-order requires a two-operation sequence: plant a shaped value through a normal write, then trigger the operation that interpolates the stored value.
   The completion criterion is a correlated pair of operations, which the parent channels (union, error, boolean, timing, egress) cannot describe because the payload is inert at injection time and fires at a later, different operation, often in another identity's context.
   The trust assumption differs on a boundary attribute: the failing clause is "stored data is safe to interpolate", a clause none of the five existing variants own.
   The source needs no baseline the suite lacks: `sql-injection` is the parent and the variant is a leaf under it.
   Confidence: high.
   Note: the base already carries second-order as an Advanced-Technique paragraph, so this is an under-splitting correction, not a foreign import.

**Enrichment candidates**
- `AttackTechnique` <- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W3/performing-second-order-sql-injection/SKILL.md`: storage-point and trigger-point mapping, including cross-context trigger where one identity's stored value executes in another identity's operation.
  Target: the proposed `sqli-second-order-injection` body.
  Confidence: high.
- `AttackTechnique` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-sqli/SKILL.md`: ORM raw-fragment and alias injection.
  A JSON-path key used as a column alias, and a mapper filter forwarded into a script operator, are identifier-interpolation variants.
  Target: parent Key Vulnerabilities "Query Builders and Object Mappers".
  Confidence: medium.
- `AttackTechnique` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-sqli/SKILL.md`: time-based blind channel inside a GraphQL resolver.
  Target variant: `sqli-time-blind-extraction`.
  Confidence: low (surface-specific, may fold into the graphql skill).
- `PayloadPattern` <- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/web-vulnerabilities/advanced-sql-injection-sqli/SKILL.md`: explicit channel-selection decision order (error, then union, then boolean, then time, then oast).
  The parent Advanced Techniques already states the channel preference; keep as an aspect.
  Confidence: high (no change needed).

**References/scripts candidates**
- Low confidence: a channel-selection decision tree plus the per-engine function dictionaries the parent Pro Tip mentions could live in `references/`.
  The sql-injection analysis marks scripted tests absent, so this is not recommended.

---

## ssti

Base: parent plus `ssti-reflected-evaluation`, `ssti-blind-evaluation`; references `ssti/references/blind-probe-signals.md` and `ssti/ssti-blind-evaluation/references/blind-oracles.md`.

**Sources matched**
- `/Users/diekgbbtt/hacking-skills/skills/web/injection/ssti/SKILL.md` (primary).
- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-ssti/SKILL.md` (primary).
- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W3/exploiting-template-injection-vulnerabilities/SKILL.md`.
- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/deep-dive-labs/ssti/SKILL.md`.
- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/web-vulnerabilities/server-side-template-injection/SKILL.md`.

**Similarity**
High.
All sources cover the arithmetic probe grammar, engine fingerprinting, namespace enumeration, sandbox escape, and control reach, which the base owns.
The base already separates reflected (same-response arithmetic proof) from blind (deferred or silent render) observability.

**Boundary**
The class discriminator per the base is the observability of evaluation (same-response proof versus deferred or silent render).
The sources confirm this axis and do not bend it.
Template engine identity is a runtime fact and stays out (ontology `TechnologyStack` = NEVER).
Client-side template injection is deliberately outside the class; the base False Positives already excludes it as markup injection rather than host execution.

**New-skill proposals**
None.
No source introduces a third observability.
The engine-specific gadget chains are runtime knowledge-base facts.

**Enrichment candidates**
- `AttackTechnique` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-ssti/SKILL.md`: staged gadget-index enumeration under a length-constrained field.
  When the injectable field caps input length, confirm with a short probe then dump the class list and enumerate the gadget index in stages.
  Target variant: `ssti-reflected-evaluation` (and blind when the sink is an outbound message).
  Confidence: high.
- `AttackTechnique` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-ssti/SKILL.md`: authenticated template-editor preview/save loop.
  The record identifier is a query parameter, the body carries the template plus a preview or save action, and a fresh token is refetched per iteration; preview renders without persisting.
  Target variant: `ssti-reflected-evaluation` (the base already names template-editor surfaces and preview panes).
  Confidence: medium.
- `PayloadPattern` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-ssti/SKILL.md`: the Jinja2-versus-Twig discriminator (string repetition versus numeric coercion) inside the delimiter-family probe grammar.
  Target: parent Reconnaissance "Probe Grammar".
  Confidence: medium.
- `ObservableSignal` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-ssti/SKILL.md`: an outbound message (confirmation mail) as the deferred reflection sink rather than the page.
  The base already lists "a stored probe that evaluates on a different endpoint, view, report, or document"; a message is an instance, not a new signal.
  Confidence: high (no change needed).

**References/scripts candidates**
- Low confidence: the staged gadget-index enumeration and the template-editor preview loop are procedural and could extend `ssti/ssti-blind-evaluation/references/`.
  ssti is the one class the analysis marks with references present and no absent notion, so any addition must be genuinely bulky to justify a new file.

---

## xxe

Base: parent plus `blind-parameter-entity-oob-exfiltration`, `transclusion-without-entity-resolution`, `entity-expansion-denial-of-service`.

**Sources matched**
- `/Users/diekgbbtt/hacking-skills/skills/web/injection/xxe/SKILL.md` (primary).
- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-xxe/SKILL.md` (primary).
- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W3/testing-for-xxe-injection-vulnerabilities/SKILL.md`.
- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W3/testing-for-xml-injection-vulnerabilities/SKILL.md`.
- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/web-vulnerabilities/xxe-xml-external-entity-injection/SKILL.md`.
- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/deep-dive-labs/xxe/SKILL.md`.

**Similarity**
High.
All sources cover external resolution, file disclosure, parameter-entity OOB, transclusion (include and stylesheet), and expansion, which the base owns.
The base is the more abstract treatment and already names parse-before-verify, parse-setting parity, and container documents.

**Boundary**
The class discriminator per the base is the failing clause (external-resolution, transclusion, bounded-expansion).
The sources confirm this axis.
Parser ecosystem identity and per-language defaults are runtime facts and stay out (ontology `TechnologyStack` = NEVER).

**New-skill proposals**
None.
One candidate was tested and rejected on the boundary test (see below).

**Boundary note (rejected proposal)**
`/Users/diekgbbtt/claude-bug-hunter/skills/hunt-xxe/SKILL.md` and `/Users/diekgbbtt/hacking-skills/skills/web/injection/xxe/SKILL.md` both carry error-based exfiltration with no network egress, using a repurposed local DTD.
The candidate variant `xxe-error-based-local-dtd-exfiltration` was assessed and rejected as a variant.
The two-half test shows a bent step (repurpose a local DTD and force a parse error to carry the value), but the variant-boundary attributes do not diverge: the failing clause is still external resolution, the impact is the same, and the surface and protocol are unchanged.
It is therefore an aspect inside the external-resolution variant, recorded as an enrichment below.

**Enrichment candidates**
- `AttackTechnique` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-xxe/SKILL.md` (corroborated by `/Users/diekgbbtt/hacking-skills/skills/web/injection/xxe/SKILL.md`): error-based exfiltration through a repurposed local DTD.
  When outbound fetch is blocked, reference a DTD already on disk and redefine one internal entity so the target file leaks in the parse error, with zero network egress.
  Target variant: `blind-parameter-entity-oob-exfiltration` Advanced Techniques and Detection Channels (an alternate oracle when egress is closed).
  Confidence: medium.
- `AttackTechnique` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-xxe/SKILL.md`: inline-entity pre-severity gate.
  Probe a harmless internal entity first; if it does not expand, entity expansion is disabled and external resolution will not work either.
  Target: parent Reconnaissance "Capability Probes".
  Confidence: medium.
- `PayloadPattern` <- `/Users/diekgbbtt/hacking-skills/skills/web/injection/xxe/SKILL.md`: PUBLIC-entity form as a fallback when SYSTEM is blocked.
  Target: parent Bypass Techniques "Declaration Variants".
  Confidence: medium.
- `AttackTechnique` <- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W3/testing-for-xxe-injection-vulnerabilities/SKILL.md`: interior port probing with a distinct entity per port and timing or error class as the oracle.
  Target: parent Key Vulnerabilities "External Resolution" interior fetch.
  Confidence: medium.
- `AttackTechnique` <- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W3/testing-for-xml-injection-vulnerabilities/SKILL.md`: XPath injection and XML tag injection where DOCTYPE is stripped.
  The base parent mentions XInclude and markup injection only at the edges; XPath injection is a different interpreter.
  Target: see Residual candidates (XPath has no adequate home).
  Confidence: low as an xxe enrichment; see residual.

**References/scripts candidates**
- Low confidence: the external definition document plus a multi-line capture listener is a bulky two-part proof that could live in `references/`.
  The xxe analysis marks scripted tests absent, so this is not recommended.

---

## weak-credential-discovery

Base: parent plus `exposed-secret-extraction`, `default-credential-replay`, `username-enumeration-oracle`, `session-token-authority-decode`.

**Sources matched**
- `/Users/diekgbbtt/hacking-skills/skills/web/auth/default-credentials/SKILL.md` (primary).
- `/Users/diekgbbtt/hacking-skills/skills/web/auth/password-reset-flaws/SKILL.md` (primary for residual).
- `/Users/diekgbbtt/hacking-skills/skills/web/auth/auth-bypass/SKILL.md`.
- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-brute-force/SKILL.md` (primary).
- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-forgot-password/SKILL.md` (primary for residual).
- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-source-leak/SKILL.md` (primary).
- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-ato/SKILL.md` (adjacent).
- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-mfa-bypass/SKILL.md` (adjacent).
- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W1/testing-api-authentication-weaknesses/SKILL.md`.
- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/api-security/api-authentication-bypass/SKILL.md`.

**Similarity**
High for `exposed-secret-extraction` (source-leak holders), `default-credential-replay` (default pairs), and `username-enumeration-oracle` (response deltas under one fixed secret).
Medium for the class as a whole: several sources reach beyond the base's four clauses into rate limiting, recovery flows, and token prediction.

**Boundary**
The class discriminator per the base is the failing clause (exposure, default-credential, response-uniformity, artifact-authority).
Three source families press on the boundary:
- Rate limiting and brute force is a different class; the base explicitly defers the throttle step to the defence-bypass family.
- Recovery-flow weaknesses (token replay, no expiry, no binding) are not owned by any base clause.
- Token prediction and brute force presses on the artifact clause but adds a distinct step.

**New-skill proposals**

1. `source`: `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-brute-force/SKILL.md` (Phase 5, token entropy) and `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-forgot-password/SKILL.md` (weak or predictable reset tokens) and `/Users/diekgbbtt/hacking-skills/skills/web/auth/password-reset-flaws/SKILL.md`.
   `[NEW] target`: `predictable-token-brute-force` (variant leaf under `weak-credential-discovery`).
   Rationale: the base artifact-authority clause covers tokens whose claims the client can read or influence; it does not cover tokens the client can guess.
   A predictable token owns a bent step: measure token entropy (structure, sequence, timestamp correlation) then brute the token space within the validity window, often with source rotation to defeat per-source limits.
   The trust assumption differs on a boundary attribute: the failing clause is "issued artifacts are unguessable", a clause none of the four existing variants own.
   The source needs no baseline the suite lacks: `weak-credential-discovery` is the parent.
   Confidence: medium.
   Alternative (lower cost): fold the entropy-measurement step into `exposed-secret-extraction` as an aspect and keep no new variant.
   The entropy measurement plus the brute step is what argues for separation.

**Enrichment candidates**
- `AttackTechnique` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-source-leak/SKILL.md`: source-map reconstruction and API-specification discovery as secret holders.
  A published source map reconstructs the client source, and a published interface description enumerates endpoints; both are holders beyond the base's "served client source" and "guessable deployable locations".
  Target variant: `exposed-secret-extraction` Attack Surface and Key Vulnerabilities.
  Confidence: high.
- `AttackTechnique` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-brute-force/SKILL.md`: token-entropy measurement as a verdict step (entropy estimate, decode structure, sequence or timestamp correlation).
  Target: the proposed `predictable-token-brute-force`, or `session-token-authority-decode` if the proposal is declined.
  Confidence: medium.
- `ObservableSignal` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-brute-force/SKILL.md`: the silent-shadow-throttle signal.
  A response that stays uniform while genuinely correct submissions stop being accepted reads as a throttle, not as an open endpoint.
  Target: parent False Positives (avoid the "no oracle" false negative).
  Confidence: medium.
- `AttackTechnique` <- `/Users/diekgbbtt/hacking-skills/skills/web/auth/default-credentials/SKILL.md`: client-side-only lockout bypass and source-header rotation to defeat per-source limits.
  The base Bypass already defers the throttle step to the defence-bypass family; keep as a named cross-reference.
  Confidence: high (no change needed).

**References/scripts candidates**
None.
The weak-credential-discovery analysis marks scripted tests absent, and the sources add concrete wordlists and tool invocations rather than a bulky abstract proof.

---

## Residual candidates

These are source materials with no adequate home in the current suite.
They are reported, not proposed as variants of an existing group.

1. LDAP and XPath injection (new class).
   Source: `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-ldap/SKILL.md`.
   Corroboration: `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W3/testing-for-xml-injection-vulnerabilities/SKILL.md` (XPath portion).
   No suite group covers directory-service filter injection or XPath expression injection.
   The class has its own grammar (RFC 4515 filters), its own trust boundary (the directory bind), its own oracles, and its own exfiltration (attribute read and DN injection).
   It does not fold into `sql-injection` or `nosql-injection` because the interpreter and the escape rules differ.
   Confidence: high.

2. Type juggling and loose-comparison authentication bypass (new class).
   Source: `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W1/exploiting-type-juggling-vulnerabilities/SKILL.md`.
   The class covers coercion-based comparison bypass, magic-hash collisions, and array or null bypass of a comparison primitive.
   No suite group owns it; it is not injection into a query and not a weak default.
   It has its own bent step (control the input type through a structured carrier) and its own trust clause (the comparison is type-safe).
   Confidence: high.

3. Rate limiting and brute-force resistance (new class).
   Sources: `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-brute-force/SKILL.md`, `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-forgot-password/SKILL.md`, `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W1/testing-api-authentication-weaknesses/SKILL.md`.
   No suite group owns rate-limit testing.
   The base weak-credential-discovery defers the throttle step to the defence-bypass family, but that family is a bypass helper, not a class.
   The sources carry a full procedure: the four-state classification (hard lockout, soft source throttle, challenge injection, silent shadow-throttle), the shadow-throttle detector, source rotation, and the reachability math.
   This is a candidate new class, not a variant.
   Confidence: medium (overlaps the defence-bypass family; needs a scope ruling).

4. Account-recovery and password-reset flow weaknesses (new class or new variant).
   Sources: `/Users/diekgbbtt/hacking-skills/skills/web/auth/password-reset-flaws/SKILL.md`, `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-forgot-password/SKILL.md`, `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-ato/SKILL.md`.
   The material covers token replay after use, missing expiry, missing session or address binding, token exposure in the response, and referrer leakage of the reset link.
   The base weak-credential-discovery references recovery flows in Chaining Attacks but owns none of these steps.
   Decision needed: a new recovery-flow class, or a new variant under weak-credential-discovery.
   Confidence: medium.

5. XML injection without external entities (weak residual).
   Source: `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W3/testing-for-xml-injection-vulnerabilities/SKILL.md`, partially `/Users/diekgbbtt/hacking-skills/skills/web/injection/xxe/SKILL.md`.
   Tag injection and CDATA-structure manipulation where DOCTYPE is stripped have no clean home; they are neither XXE nor header injection.
   Likely folds into `xxe` as a documented aspect rather than a new class.
   Confidence: low.

6. Message-protocol or wire-format injection beyond the covered stores (weak residual).
   Source: `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W3/exploiting-nosql-injection-vulnerabilities/SKILL.md` (binary serialization manipulation at the wire protocol).
   The nosql-injection command-protocol-smuggling variant covers key-value command framing but not a binary wire-protocol shape.
   Confidence: low (likely a runtime fact, not a class).

---

## Slice summary

- Groups assessed: 6.
- Base parents: 6; variant leaves: 21; reference files: 2.
- New-skill proposals: 2.
  - `sqli-second-order-injection` (high confidence), an under-splitting correction the base already hints at in one paragraph.
  - `predictable-token-brute-force` (medium confidence), with a documented lower-cost alternative to fold into `exposed-secret-extraction`.
- Rejected proposal: `xxe-error-based-local-dtd-exfiltration`, rejected on the boundary test (no boundary attribute diverges); recorded as an aspect enrichment.
- Enrichment candidates: 17 across the six groups, the highest-value being source-map and interface-description holders for `exposed-secret-extraction`, the second-order store and trigger mapping for `sql-injection`, and the string-context script breakout for `nosql-injection`.
- References/scripts candidates: none recommended; the analyses mark scripted tests absent in five of the six groups, and ssti already carries its references.
- Residual candidates: 4 strong or medium (LDAP and XPath injection, type juggling, rate limiting and brute force, account-recovery flows) plus 2 weak.
- Boundary discipline: no proposal imports a technology stack or a version as a discriminator; all proposals fit an existing suite baseline.
