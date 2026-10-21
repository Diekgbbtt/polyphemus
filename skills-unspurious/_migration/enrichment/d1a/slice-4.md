# D1a enrichment proposal, slice 4

## Slice header

**Groups (6, one base skill each):** `nosql-injection`, `prototype-pollution`, `sql-injection`, `ssti`, `xxe`, `weak-credential-discovery`.

**Skill counts:** 6 parents plus 21 variant leaves (nosql 5, prototype-pollution 2, sql-injection 5, ssti 2, xxe 3, weak-credential-discovery 4).

**Report only.** No suite skill was modified. No git command was run.

**Base:** the suite in this worktree (`skills-unspurious/`).
**Sources (read-only):** `/Users/diekgbbtt/hacking-skills/skills`, `/Users/diekgbbtt/claude-bug-hunter/skills`, `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted`, `/Users/diekgbbtt/awsome-offensive-security-skill/skills`.
**Normative docs read:** `docs/design/skills-variant-boundary.md` (the boundary attributes and the variant algorithm), `docs/design/skills-ontology.md` (the ordered notions and the ten methodology entities).

## The algorithm (verbatim, the operator's specification)

> establish the base from the purple-swan/skills --> iterate sequentially on each purple-swann/skills by finding relevant skills in the other source repositories by matching on the vulnerability class or reasoning on techniques that can be chained to the skill in object to achieve stronger capabilities in order to enable/simplify/amplify the specific technique --> if the similarity is not sufficient, it reads the skills decomposition strategy that cites the boundary among variants and assess if any of the mentioned attributes diverges from any of the most similar skills matched, if so it writes a new skill proposal into a report document that we will assess afterward, featuring source and [NEW] target skill and extended rationale on the decision (one example that should not match is a second-order IDOR which is missing the baseline skills suite) --> if instead there was sufficient similariy to one skill, macro semantic content diff check --> if any, the resulted diffed content in source skills can be abstracted to one of the skills ontology entities and written cohesively chirurgucally --> if the diff is quite big and captures multiple entities of the ontology, including at least one mentioned in the variants boundary, that could yield a new skill, this assessment must be done as in the previosu step --> finally, move on to references/scripts, assess if sufficiently generalised, if so write them off as examples in references [this is a multiple iteration work, write literally the algorithm as I specified it]

## Boundary discriminators in force for this slice

Taken from `skills-unspurious/_analysis/<class>.md` and `docs/design/skills-variant-boundary.md`.

- `nosql-injection`: discriminated by **query-interpretation family** (value clause, script-surface clause, stage clause, grammar clause, frame clause). Store label is a non-discriminator.
- `prototype-pollution`: discriminated by **exploitation-sink family** (client consumer, server consumer). Library, payload shape, delivery channel, and second-order timing are non-discriminators.
- `sql-injection`: discriminated by **extraction channel** (rendering, shaping, truth-differencing, timing, egress). DBMS product is a non-discriminator.
- `ssti`: discriminated by **evaluation observability** (same-response reflection, deferred or absent reflection). Engine name is a non-discriminator.
- `xxe`: discriminated by the **failing clause** (external-resolution clause, transclusion clause, bounded-expansion clause). The analysis also names `PreconditionEnvironment` external-DTD-fetch enabled versus disabled as a discriminator.
- `weak-credential-discovery`: discriminated by **mechanism** (exposure, replay, oracle, decode). Runtime stack is a non-discriminator.

---

## nosql-injection

Base variants: `nosql-operator-injection`, `nosql-server-side-script-injection`, `nosql-aggregation-pipeline-injection`, `nosql-query-language-injection`, `nosql-command-protocol-smuggling`.

**Sources matched**

- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-nosqli/SKILL.md` - operator injection, `$where` timing, a string-context syntax breakout, and a Redis-via-SSRF chain; the richest operator-family source.
- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W3/exploiting-nosql-injection-vulnerabilities/SKILL.md` - operator and `$where` families, BSON mention, automation; largely restates the parent.
- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/deep-dive-labs/nosql-injection/SKILL.md` - lab payloads plus unknown-field enumeration through a document-introspection primitive.
- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W3/exploiting-api-injection-vulnerabilities/SKILL.md` - API-layer SQL plus NoSQL survey; no new NoSQL step.

**Similarity:** sufficient. Every source maps onto an existing interpretation family; the parent already carries operator, script, aggregation, grammar, and frame families.

**Boundary:** none diverges. Store names in the sources (MongoDB, CouchDB, Redis, Elasticsearch, Neo4j) are the non-discriminator `TechnologyStack`; the analysis explicitly excludes store label as an axis.

**New-skill proposals**

None for a NoSQL variant. Two adjacent classes are absent from the suite and were considered, then rejected as out-of-slice class gaps rather than NoSQL variants:

- LDAP and XPath filter injection (`/Users/diekgbbtt/claude-bug-hunter/skills/hunt-ldap/SKILL.md`) share the grammar-injection bent step but differ in `VulnerabilityClass`, protocol, and attack-surface family. They are new classes, not variants of `nosql-injection`; a proposal would require the boundary algorithm run against its own baseline. Flagged as an observation, not a proposal (low confidence for this slice).

**Enrichment candidates**

- `AttackTechnique` <- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/deep-dive-labs/nosql-injection/SKILL.md`: blind **field-name and schema enumeration** through a document-introspection primitive character by character, distinct from value extraction; the parent's blind extraction covers values only.
- `AttackTechnique` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-nosqli/SKILL.md`: **string-context syntax breakout** into a concatenated script predicate (fuzz the metacharacter set, then break with an always-true fragment and a boolean character-exfil oracle), where operator objects are not accepted; extend the grammar clause's families beyond graph, search, and statement grammars (medium confidence, the grammar clause may already cover it).
- `AttackTechnique` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-nosqli/SKILL.md`: the key-value store reach through an SSRF or proxy relay to its command port is a chain step; route it to the `ssrf` and `proxy-techniques` families at the frame clause rather than restating relay mechanics.

**References/scripts candidates**

- None generalised. `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W3/exploiting-nosql-injection-vulnerabilities/scripts/process.py` and `scripts/agent.py` hardcode concrete operators and endpoints; they are technology-concrete examples, not generalised, and do not meet the `references/` bar.

---

## prototype-pollution

Base variants: `prototype-pollution-client-side`, `prototype-pollution-server-side`.

**Sources matched**

- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W3/exploiting-prototype-pollution-in-javascript/SKILL.md` - client and server sinks plus reflection-free detection and DoS via coercion.
- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/deep-dive-labs/prototype-pollution/SKILL.md` - lab variants including detection without reflection and data exfiltration through serialization-shaping properties.
- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/web-vulnerabilities/prototype-pollution-rce/SKILL.md` - the server sink chain to process spawn; duplicates the parent server variant.
- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/web-vulnerabilities/javascript-prototype-pollution/SKILL.md` - client and server gadget framing; duplicates the parent.
- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-nodejs/SKILL.md` - Node pollution to RCE sink catalogue; library-specific, `TechnologyStack`.

**Similarity:** sufficient. Every source lands in the client or server sink family.

**Boundary:** none diverges. Library names and gadget bodies are `TechnologyStack` and `PayloadPattern`, both non-discriminators; the analysis already folds second-order timing into an aspect.

**New-skill proposals**

None. DoS and data exfiltration are downstream goals reachable through the existing sink variants, and pure impact bends no step by itself (`docs/design/skills-variant-boundary.md`, pitfalls).

**Enrichment candidates**

- `AttackTechnique` <- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W3/exploiting-prototype-pollution-in-javascript/SKILL.md`: **denial of service through coercion-primitive pollution** (`toString`/`valueOf`), which the parent names in its intro but carries no step for.
- `AttackTechnique` <- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/deep-dive-labs/prototype-pollution/SKILL.md`: **data exfiltration through response-shaping properties** (pollute serialization options such as spacing and content type, then read a reflected surface that leaks data), a server-side consumer the parent does not name.
- `ObservableSignal` <- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/deep-dive-labs/prototype-pollution/SKILL.md` and `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W3/exploiting-prototype-pollution-in-javascript/SKILL.md`: **reflection-free confirmation** by polluting a property with a deliberate observable side effect (a status-code change or a serialization-spacing change) when no unrelated read echoes the marker; the parent lists response deltas but not the technique of choosing a side-effecting probe property.

**References/scripts candidates**

- None generalised. The source payload sets are `PayloadPattern` values and library-specific gadget bodies, both non-discriminators, and none ships a reusable artefact.

---

## sql-injection

Base variants: `sqli-union-extraction`, `sqli-error-based-extraction`, `sqli-boolean-blind-extraction`, `sqli-time-blind-extraction`, `sqli-oast-exfiltration`.

**Sources matched**

- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-sqli/SKILL.md` - channel selection discipline, ORM raw-fragment and column-alias cases, header carriers, authenticated-only surfaces.
- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W3/exploiting-sql-injection-vulnerabilities/SKILL.md` - channel detection and DBMS fingerprinting; fully covered by the parent.
- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W3/exploiting-sql-injection-with-sqlmap/SKILL.md` - tooling workflow; `TechnologyStack`, no new step.
- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W3/performing-second-order-sql-injection/SKILL.md` - storage-point and trigger-point mapping with cross-context execution.
- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/web-vulnerabilities/advanced-sql-injection-sqli/SKILL.md` - channel decision tree plus second-order password-change case.
- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/web-vulnerabilities/django-sql-injection/SKILL.md` - ORM raw-fragment and column-alias cases; covered by the parent.
- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/web-vulnerabilities/sqli-manual-and-automated/SKILL.md` - detection and WAF bypass; covered by the parent.
- `/Users/diekgbbtt/hacking-skills/skills/web/injection/sql-injection/SKILL.md` - classic detection and fix patterns; covered by the parent.

**Similarity:** sufficient. The five channels are present in the parent and repeated in every source.

**Boundary:** none diverges. DBMS dialects, tamper scripts, and tools are non-discriminators.

**New-skill proposals**

None. **Second-order SQL injection is correctly not a variant.** It is a delivery-timing difference orthogonal to the channel axis; the parent already carries it as an Advanced Technique, and branch 5b of the boundary algorithm keeps a secondary divergence inside the parent rather than promoting it. This is the same shape as the operator's "second-order IDOR missing its baseline" example: the diff is real but does not own a new bent step on the class axis.

**Enrichment candidates**

- `AttackTechnique` <- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W3/performing-second-order-sql-injection/SKILL.md` and `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/web-vulnerabilities/advanced-sql-injection-sqli/SKILL.md`: expand the two-line second-order advanced technique into **storage-point and trigger-point mapping plus cross-context execution**, where a value stored by one principal is interpolated in another principal's or an administrator's query and executes deferred.
- `PreconditionEnvironment` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-sqli/SKILL.md`: **authenticated-only injection surfaces** as a recon target, where internal tooling carries an over-privileged database account and WAFs often whitelist authenticated traffic (medium confidence; a pro-tip-shaped addition).

**References/scripts candidates**

- None generalised. The anthropic `scripts/agent.py` files for this class are per-target harnesses with concrete payload literals; they do not meet the `references/` bar.

---

## ssti

Base variants: `ssti-reflected-evaluation`, `ssti-blind-evaluation` (the parent ships `references/`).

**Sources matched**

- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-ssti/SKILL.md` - code-context break-out, length-constrained field staging, template-editor preview workflow, engine gadget chains.
- `/Users/diekgbbtt/hacking-skills/skills/web/injection/ssti/SKILL.md` - engine payload grammar and bypass; `TechnologyStack` and `PayloadPattern`.
- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W3/exploiting-template-injection-vulnerabilities/SKILL.md` - engine payloads plus a client-side template injection section.
- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/web-vulnerabilities/server-side-template-injection/SKILL.md` - engine exploitation; covered by the parent.
- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/deep-dive-labs/ssti/SKILL.md` - lab payloads including the code-context break-out.

**Similarity:** sufficient. The two variants are observability splits; the sources restate both.

**Boundary:** none diverges. Engine names and payload literals are non-discriminators by instruction.

**New-skill proposals**

None. **Client-side template injection is correctly excluded**: its `VulnerabilityClass` is markup injection and its impact is browser-side, which the parent already lists under False Positives; the source's CSTI section is a non-match, not a variant.

**Enrichment candidates**

- `AttackTechnique` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-ssti/SKILL.md` and `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/deep-dive-labs/ssti/SKILL.md`: **expression-context break-out**, where the injected value lands inside an existing expression rather than at a syntax boundary and the payload closes the surrounding context before opening its own; the parent covers "a value lands where the engine parses syntax" but not this break-out kind.
- `AttackTechnique` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-ssti/SKILL.md`: **length-constrained field staging**, where a capped input field is confirmed with a short probe, the exposed object list is dumped, and the execution index is selected in a second probe; generalised to any length-capped reflection.
- `AttackTechnique` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-ssti/SKILL.md`: the deferred sink is frequently an **outbound message or generated document** rather than a page; the parent covers deferred render, so this only sharpens the sweep target (low confidence, likely already covered).

**References/scripts candidates**

- None new. The engine-specific RCE gadget trees in the sources are `TechnologyStack` and `PayloadPattern` values; the parent already carries the generalised blind-oracle shapes in `ssti/ssti-blind-evaluation/references/blind-oracles.md`. A concrete gadget-index reference would sit in tension with the abstractness rule and is not proposed.

---

## xxe

Base variants: `blind-parameter-entity-oob-exfiltration`, `transclusion-without-entity-resolution`, `entity-expansion-denial-of-service`.

**Sources matched**

- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-xxe/SKILL.md` - error-based exfiltration by repurposing an on-disk DTD, XSLT-extension RCE, content-type negotiation probe, and an inline-entity pre-flight gate.
- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W3/testing-for-xxe-injection-vulnerabilities/SKILL.md` - consumer inventory, content-type swap, OOB chain, wrapper file reads.
- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W3/testing-for-xml-injection-vulnerabilities/SKILL.md` - XXE plus XPath injection plus expansion bombs.
- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/web-vulnerabilities/xxe-xml-external-entity-injection/SKILL.md` - content-type fuzzing, OOB chain, container uploads, SSRF pivot.
- `/Users/diekgbbtt/hacking-skills/skills/web/injection/xxe/SKILL.md` - declaration and encoding variants, XInclude and tag-injection fallbacks.
- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/deep-dive-labs/xxe/SKILL.md` - lab payloads; covered by the parent.

**Similarity:** sufficient for the external-resolution and transclusion clauses; the error-based local-DTD case diverges (below).

**Boundary:** `PreconditionEnvironment` external-DTD-fetch enabled versus disabled diverges. The parent blind variant presupposes an attacker-hosted external DTD that the parser fetches. The source's local-DTD repurposing technique applies when external DTD fetch is disabled but a DTD already on disk is still processed, and it exfiltrates through parse-error text with zero network egress. The parent blind variant cannot describe that step, so it is a genuine new bent step.

**New-skill proposals**

- `source: /Users/diekgbbtt/claude-bug-hunter/skills/hunt-xxe/SKILL.md`
  `[NEW] target: xxe-local-dtd-error-exfiltration`
  Rationale: the base blind variant `blind-parameter-entity-oob-exfiltration` requires attacker-hosted external resolution plus a callback destination. When external DTD fetch is disabled but a locally installed DTD is still processed, a distinct bent step exists: locate an on-disk DTD, redefine one of its internal entities, and force a read file into a parse-error message with no egress. The boundary attribute `PreconditionEnvironment` external-DTD-fetch enabled versus disabled diverges from the blind variant, and the observable channel is error text rather than a callback. This captures multiple ontology entities (PreconditionEnvironment, AttackTechnique, ObservableSignal, PayloadPattern) and at least one boundary attribute, so it escalates to a new variant per the algorithm. Confidence: high. The suite must also carry the corresponding reference (below).

**Enrichment candidates**

- `AttackTechnique` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-xxe/SKILL.md`: **XSLT-extension execution**, where a reachable transform processor exposes an extension that runs host code or a wrapper scheme reaches a process; the parent names XSLT transclusion but not transform-time execution.
- `PreconditionEnvironment` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-xxe/SKILL.md` and `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W3/testing-for-xxe-injection-vulnerabilities/SKILL.md`: **content-type negotiation probing**, where a JSON-accepting endpoint is retried as XML or with a mismatched content type to expose a hidden parser; the parent's carriers do not name this recon step.
- `AttackTechnique` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-xxe/SKILL.md`: the **inline-entity pre-flight gate** (define an internal entity, reference it, and confirm expansion before investing in SYSTEM reads) as the cheapest capability probe; the parent has declaration acceptance and resolution probes but not this gate (medium confidence).

**References/scripts candidates**

- `references/local-dtd-repurposing.md` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-xxe/SKILL.md`: the generalised recipe for zero-egress error-based exfiltration through a pre-existing on-disk DTD, including the enumeration of local DTD locations; belongs with the proposed `xxe-local-dtd-error-exfiltration` variant.
- Flagged, low confidence: `references/parser-capability-matrix.md` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-xxe/SKILL.md`. The parser-versus-ecosystem hardening matrix is `TechnologyStack`, which the ontology marks NEVER in a body; it would only be admissible as a runtime knowledge-base example, not as a suite reference.

---

## weak-credential-discovery

Base variants: `exposed-secret-extraction`, `default-credential-replay`, `username-enumeration-oracle`, `session-token-authority-decode`.

**Sources matched**

- `/Users/diekgbbtt/claude-bug-hunter/skills/offensive-osint/references/secret-patterns.md` - a typed 48-pattern credential-shape catalogue.
- `/Users/diekgbbtt/claude-bug-hunter/skills/offensive-osint/references/secret-validators.md` - read-only liveness and scope validators with a detectability tag.
- `/Users/diekgbbtt/claude-bug-hunter/skills/offensive-osint/references/breach-and-credentials.md` - breach-corpus lookup and credential-stuffing material.
- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-source-leak/SKILL.md` - source-map, asset-manifest, and API-specification artifact families with a reconstruction recipe.
- `/Users/diekgbbtt/hacking-skills/skills/web/auth/default-credentials/SKILL.md` - default pair testing and client-side-only lockout bypass.
- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-brute-force/SKILL.md` - the four rate-limit states and username-enumeration oracles.
- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W1/testing-api-authentication-weaknesses/SKILL.md` - API credential and token-lifecycle testing; mostly the token class.
- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/api-security/api-authentication-bypass/SKILL.md` - JWT and OAuth attacks; the token class.

**Similarity:** sufficient for the exposure, replay, and oracle mechanisms.

**Boundary:** none diverges for the four mechanisms. The session-token variant correctly defers signature and validation to the token class, and the brute-force source's throttle states are the `defence-bypass` family's step, which the parent already names.

**New-skill proposals**

- None. **Breach-corpus lookup and credential stuffing must not be proposed** (`/Users/diekgbbtt/claude-bug-hunter/skills/offensive-osint/references/breach-and-credentials.md`). The boundary attributes diverge (the material is not served by the application, and the capability is external OSINT collection), but the technique needs an OSINT baseline the suite does not carry. This is the same shape as the operator's second-order-IDOR example: insufficient similarity plus a missing baseline yields a non-match, not a proposal. Clean verdict: no match.

**Enrichment candidates**

- `AttackTechnique` <- `/Users/diekgbbtt/claude-bug-hunter/skills/offensive-osint/references/secret-validators.md`: **credential liveness and scope validation** against the issuing service's read-only identity endpoint, which turns a credential-shaped string into a proven usable credential and reads the scope it grants; the parent states reuse as the bar but carries no validation step.
- `AttackTechnique` <- `/Users/diekgbbtt/claude-bug-hunter/skills/offensive-osint/references/secret-validators.md`: weigh the **detectability cost** of validating a credential before confirming it, and prefer low-detectability validators; the parent has no detectability notion.
- `PreconditionEnvironment` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-source-leak/SKILL.md`: extend the deployable-artifact family with **build and bundle artifacts** (source maps, asset manifests, API specification documents, build-info files) that reconstruct source or enumerate routes and embedded secrets; the parent lists environment, configuration, version-control, backup, and debug artifacts only.
- `AttackTechnique` <- `/Users/diekgbbtt/hacking-skills/skills/web/auth/default-credentials/SKILL.md`: **client-side-only lockout bypass**, where a JavaScript-enforced lockout is skipped by sending requests directly (medium confidence; the parent defers the throttle step to `defence-bypass`, so this may belong there instead).

**References/scripts candidates**

- `references/secret-pattern-catalog.md` <- `/Users/diekgbbtt/claude-bug-hunter/skills/offensive-osint/references/secret-patterns.md`: a generalised, ordered, typed credential-shape catalogue with severity and false-positive notes; directly reusable as an example reference for the exposure variant.
- `references/secret-validators.md` <- `/Users/diekgbbtt/claude-bug-hunter/skills/offensive-osint/references/secret-validators.md`: generalised read-only liveness and scope validators; directly reusable.
- `scripts/secret-scan.py` <- `/Users/diekgbbtt/claude-bug-hunter/skills/offensive-osint/scripts/secret_scan.py`: a generalised, dependency-free scanner that mirrors the catalogue and emits one JSON record per match; a strong `scripts/` candidate.
- Flagged, low confidence: `references/build-artifact-paths.md` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-source-leak/SKILL.md`: generalised artifact-path families plus the reconstruction recipe; partially overlaps the enrichment above.

---

## Slice summary

**Counts**

- Groups analysed: 6. Base skills read: 6 parents plus 21 leaves.
- Source skills matched and read: 28 (4 hacking-skills, 9 claude-bug-hunter including 3 references and 1 script, 9 anthropic accepted, 8 awsome).
- New-skill proposals: 1 firm (`xxe-local-dtd-error-exfiltration`), 1 rejected with rationale (breach-corpus credential source), 2 flagged out-of-slice class gaps (LDAP injection, XPath injection).
- Enrichment candidates: 15 (nosql 3, prototype-pollution 3, sql-injection 2, ssti 3, xxe 3, weak-credential-discovery 4, minus one low-confidence dedupe).
- References/scripts candidates: 4 firm (`secret-pattern-catalog.md`, `secret-validators.md`, `secret-scan.py`, `local-dtd-repurposing.md`), 2 flagged low confidence.

**Strongest findings**

1. **`xxe` gains a fourth variant, `xxe-local-dtd-error-exfiltration`.** The source's local-DTD repurposing technique bends a step on the `PreconditionEnvironment` external-DTD-fetch axis that the parent blind variant cannot cover: zero-egress exfiltration through parse-error text when an on-disk DTD is processed. This is the only firm new-skill proposal in the slice.
2. **`weak-credential-discovery` has the largest enrichment yield, and its strongest candidates are references plus scripts.** The typed secret catalogue, the read-only validators, and the stdlib scanner from `offensive-osint` are generalised and directly reusable; the body enrichment is credential liveness and scope validation, which the parent lacks.
3. **`sql-injection` is the cleanest no-change verdict.** Every source restates an existing channel, and second-order injection is correctly a secondary divergence inside the parent, exactly matching the operator's "missing baseline" caution.
4. **`prototype-pollution`, `ssti`, and `nosql-injection` each carry a real, small body gap**: coercion-primitive DoS and response-shaping data exfiltration for pollution; expression-context break-out and length-constrained staging for SSTI; blind field-name enumeration for NoSQL.
5. **Two suite class gaps surfaced but were not proposed**: LDAP filter injection and XPath injection are distinct `VulnerabilityClass` values, not variants of `nosql-injection` or `xxe`. They are recorded for a separate boundary run.

**Low-confidence flags to resolve in assessment**

- NoSQL string-context syntax breakout may already be covered by the grammar clause.
- The SSTI deferred-sink sharpening is likely already covered by the parent deferred-render text.
- The SQL authenticated-only-surface addition is pro-tip-shaped, not a step.
- The weak-credential client-side-lockout bypass may belong to `defence-bypass`.
- The XXE parser-capability matrix is `TechnologyStack` (NEVER in a body); only a reference example could hold it.
