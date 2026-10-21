# Slice 3 - round 2 enrichment report

Work item W7, C4-full enrichment, mining round 2.
This report is independent of round 1. I did not read `d1a/` round-1 artefacts.

## Slice header

Base suite root: `skills-unspurious/`.
Slice groups (6): `crypto-weakness`, `insecure-deserialization`, `insecure-file-uploads`, `path-traversal-lfi-rfi`, `graphql`, `llm-prompt-injection`.
Base skills in slice: 26 (6 parents plus 20 variant leaves).
Base file count: 26 `SKILL.md` files.

Source repositories indexed (read-only):

| Source root | Files | Layout |
|---|---|---|
| `/Users/diekgbbtt/hacking-skills/skills` | 43 | `domain/topic/skill/SKILL.md` |
| `/Users/diekgbbtt/claude-bug-hunter/skills` | 105 | `hunt-*/SKILL.md`, plus `offensive-osint/` with `references/` and `scripts/` |
| `/Users/diekgbbtt/anthropic-cybersecurity-skills` | 399 | `accepted/W*/<skill>/{SKILL.md,references/,scripts/}` plus `catalog/catalog.json` (818 entries, name/subdomain/tags/desc) |
| `/Users/diekgbbtt/awsome-offensive-security-skill/skills` | 370 | `domain/subdomain/skill/{SKILL.md,scripts/process.py,evals/}` |

Method note: I matched on vulnerability class first, then on chainable technique.
I read the strongest candidates in full and index-level descriptions for the rest.
Low-confidence items are flagged in place.

## The algorithm (verbatim, as specified by the operator)

> establish the base from the purple-swan/skills --> iterate sequentially on each purple-swann/skills by finding relevant skills in the other source repositories by matching on the vulnerability class or reasoning on techniques that can be chained to the skill in object to achieve stronger capabilities in order to enable/simplify/amplify the specific technique --> if the similarity is not sufficient, it reads the skills decomposition strategy that cites the boundary among variants and assess if any of the mentioned attributes diverges from any of the most similar skills matched, if so it writes a new skill proposal into a report document that we will assess afterward, featuring source and [NEW] target skill and extended rationale on the decision (one example that should not match is a second-order IDOR which is missing the baseline skills suite) --> if instead there was sufficient similariy to one skill, macro semantic content diff check --> if any, the resulted diffed content in source skills can be abstracted to one of the skills ontology entities and written cohesively chirurgucally --> if the diff is quite big and captures multiple entities of the ontology, including at least one mentioned in the variants boundary, that could yield a new skill, this assessment must be done as in the previosu step --> finally, move on to references/scripts, assess if sufficiently generalised, if so write them off as examples in references [this is a multiple iteration work, write literally the algorithm as I specified it]

## crypto-weakness

Group: parent `crypto-weakness` plus `crypto-predictable-token`, `crypto-signing-key-forgery`, `crypto-timing-oracle`.

**Sources matched**

- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-jwt-crypto/SKILL.md` (alg:none, RS256 to HS256 key confusion, kid/jku/x5u/jwk header injection, weak HMAC cracking, expiry and claim manipulation).
- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W1/exploiting-jwt-algorithm-confusion-attack/SKILL.md`, `accepted/W1/performing-jwt-none-algorithm-attack/SKILL.md`, `accepted/W1/testing-jwt-token-security/SKILL.md`.
- `/Users/diekgbbtt/anthropic-cybersecurity-skills/catalog/catalog.json` entries `performing-cryptographic-audit-of-application`, `performing-hash-cracking-with-hashcat`.
- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/apis/jwt-algorithm-confusion/SKILL.md`, `.../apis/jwt-null-signature/SKILL.md`, `.../api-security/jwt-forgery-algorithm-confusion/SKILL.md`.
- `/Users/diekgbbtt/hacking-skills/skills/mobile/crypto/mobile-weak-crypto/SKILL.md` (ECB mode, static and predictable IV, non-CSPRNG key/IV generation, hardcoded key material).
- `/Users/diekgbbtt/hacking-skills/skills/web/auth/jwt-misconfig/SKILL.md` (index-level).

**Similarity**

Sufficient for `crypto-signing-key-forgery`.
The `alg:none` family is keyless signature acceptance, which is the variant's removal clause.
The weak HMAC secret family is the variant's offline secret search with local re-verification.
The JWT payload and expiry edits are claim aspects inside that variant.
`crypto-predictable-token` and `crypto-timing-oracle` have no strong source match. The token-prediction sources are thin.
`mobile-weak-crypto` matches only the parent's at-rest key bullet, not a variant.

**Boundary**

The `crypto-weakness` signature is the cryptographic trust property the test breaks: token unpredictability, signing-key trust, or comparison-timing independence.
JWT alg-confusion and none-algorithm map onto signing-key trust, so they are aspects inside `crypto-signing-key-forgery`, not a new axis.
Two source clusters do not map onto any of the three clauses.
First, cipher-mode and IV weaknesses (ECB pattern leak, static or predictable IV, non-CSPRNG generation) break a ciphertext-confidentiality property the signature does not hold.
Second, key-reference resolution (kid, jku, x5u, jwk) lets the verifier resolve a key from an attacker-named path, URL, or embedded key; the binding is neither weak nor removable, it is attacker-chosen.
Both clusters diverge from the parent and from all three variants on the trust-assumption and impact boundary attributes.

**New-skill proposals**

1. `source`: `/Users/diekgbbtt/hacking-skills/skills/mobile/crypto/mobile-weak-crypto/SKILL.md` (reinforced by catalog `performing-cryptographic-audit-of-application`).
   `[NEW] target`: `crypto-cipher-mode-weakness` (proposed variant of `crypto-weakness`).
   Rationale: the failing clause is ciphertext confidentiality under a weak mode or a weak IV, not bearer-token authorization. ECB pattern leak, static IV, and predictable-IV recovery need steps the parent does not name: obtain ciphertext samples, detect mode and IV reuse, recover plaintext structure, and search the IV seed space. The suite baseline is present: the parent `## Attack Surface` already lists "At-rest material: stored digests, embedded keys, seeded secrets, static placeholders", and the parent `## Key Vulnerabilities` has "Guessable Signing Secrets". Confidence: medium. Caveat: the parent class is defined by value-as-authorization, so a reviewer may prefer a new class rather than a variant. Flag for the synthesis ruling.

2. `source`: `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-jwt-crypto/SKILL.md` (kid, jku, x5u, jwk header injection), reinforced by `/Users/diekgbbtt/anthropic-cybersecurity-skills/catalog/catalog.json` entry `exploiting-jwt-algorithm-confusion-attack`.
   `[NEW] target`: `crypto-key-reference-injection` (proposed variant of `crypto-weakness`).
   Rationale: the failing clause is key-source trust. The verifier resolves the verification key from a reference the attacker controls, so no secret search and no algorithm removal is needed. This is a distinct bent step: craft the reference, and where the lookup reaches a file path, a query, or a URL, chain to the path-traversal or query-language family. Baseline is present (a keyed-checksum artifact with a key reference). Confidence: medium. Caveat: the suite has a separate `authentication-jwt` group outside this slice, which may be the better home for the JWT-shaped part.

**Enrichment candidates**

- `AttackTechnique` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-jwt-crypto/SKILL.md`: alg:none with case variants, RS256 to HS256 key confusion from a public PEM, expiry and nbf removal, cross-tenant claim swap. Fits `crypto-signing-key-forgery` `## Advanced Techniques` and `## Bypass Techniques`.
- `AttackTechnique` <- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W1/testing-jwt-token-security/SKILL.md`: signature-strip with trailing dot, key confusion via JWK-to-PEM conversion, offline crack with hashcat mode 16500. Fits `crypto-signing-key-forgery`.
- `DefensiveControl` <- `/Users/diekgbbtt/hacking-skills/skills/mobile/crypto/mobile-weak-crypto/SKILL.md`: ECB mode, DES/3DES/RC4, static IV, `java.util.Random` and `arc4random` misuse. Feeds the proposed `crypto-cipher-mode-weakness` `## Bypass Techniques`.
- `ObservableSignal` <- catalog `performing-hash-cracking-with-hashcat`: recovered plaintext from an offline crack. Fits `crypto-signing-key-forgery` `## Detection Channels`.
- `AttackerCapability` <- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W1/exploiting-jwt-algorithm-confusion-attack/SKILL.md`: hold the public key and re-sign under the confused algorithm. Fits `crypto-signing-key-forgery`.

**References/scripts candidates**

None. The crypto sources carry inline commands only. No source `references/` or `scripts/` file in this group is generalisable.

## insecure-deserialization

Group: parent `insecure-deserialization` plus `deserialization-gadget-chain`, `deserialization-signed-forgery`, `deserialization-deferred-trigger`.

**Sources matched**

- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-deserialization/SKILL.md` (Java, PHP, pickle, .NET, Ruby, JNDI; magic bytes; PHP phar://; Python YAML; node-serialize).
- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-aspnet/SKILL.md` (ViewState signed-only, machineKey recovery, dual-parser MAC-before-parse differential, Telerik).
- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/deserialization/java-insecure-deserialization-ysoserial/SKILL.md`, `.../deserialization/nodejs-deserialization-rce/SKILL.md`, `.../web-vulnerabilities/php-deserialization-rce/SKILL.md`, `.../deep-dive-labs/insecure-deserialization/SKILL.md`.
- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W3/exploiting-insecure-deserialization/SKILL.md`.
- Index-level: `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-sharepoint/SKILL.md`, `hunt-laravel`, `hunt-springboot`, `hunt-nextjs` (framework-specific sinks).

**Similarity**

Strong.
Unsigned object graphs, type-tagged documents, self-executing encodings, and the callback-first safe oracle match `deserialization-gadget-chain`.
ViewState signed-only, machineKey recovery, and re-sign under a recovered secret match `deserialization-signed-forgery`.
PHP phar:// metadata reads and stored-then-triggered blobs match `deserialization-deferred-trigger`.

**Boundary**

The signature is the failing clause: type-resolution, integrity, or timing.
Most source material lands inside one of the three variants.
Two source clusters do not map onto a variant.
First, the ASP.NET dual-parser differential: XML-shaped and LosFormatter-shaped payloads reach a legacy parser before MAC validation. The binding is present and strong, but its evaluation order differs by shape. That is a fourth failing clause.
Second, JNDI and log-interpolation class loading: a lookup string reaches a class-loading sink with no serialized object graph. That is a lookup-triggered remote load, not a rehydration clause.

**New-skill proposals**

1. `source`: `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-aspnet/SKILL.md` (Section 4 dual-parser differential and Section 6 root cause 6).
   `[NEW] target`: `deserialization-parser-order-bypass` (proposed variant of `insecure-deserialization`).
   Rationale: the verifier evaluates the integrity binding after a partial parse on some payload shapes, so acceptance does not require key recovery or removal. The parent steps (find sinks, confirm format, safe oracle, chain selection) do not name a parser-selection probe with a response-class differential. Baseline is present (integrity-gated state blobs are in the parent `## Attack Surface`). Confidence: low to medium. Caveat: the divergence delta may be a bypass technique inside `deserialization-signed-forgery` rather than a variant with its own step. Flag for the synthesis ruling.

2. `source`: `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-deserialization/SKILL.md` Phase 5 (JNDI and Log4Shell).
   `[NEW] target`: `deserialization-lookup-triggered-class-load` (proposed variant) or a separate `lookup-injection` class.
   Rationale: an interpolated lookup string reaches a remote class loader and executes attacker classes. The bent step is crafting the lookup and hosting the remote class, not rehydrating a local graph. Baseline is weak: this presupposes a JNDI-capable or expression-interpolation sink, which the suite does not hold as a class. Confidence: low. Flag for the synthesis ruling.

**Enrichment candidates**

- `AttackTechnique` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-deserialization/SKILL.md` Phase 3b: PHP phar:// metadata read with no `unserialize()` call, reached through any file operation. Fits `deserialization-deferred-trigger` `## Key Vulnerabilities`.
- `PayloadPattern` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-deserialization/SKILL.md` and `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W3/exploiting-insecure-deserialization/SKILL.md`: magic prefixes (`rO0AB`, `AC ED 00 05`, `/wE`, `\x80`), node-serialize `_$$ND_FUNC$$_` IIFE, PyYAML `!!python/object/apply`, pickle `__reduce__`. Fits `deserialization-gadget-chain`.
- `AttackTechnique` <- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W3/exploiting-insecure-deserialization/SKILL.md`: ViewState signed-only detection, machineKey recovery, ysoserial.net chains. Fits `deserialization-signed-forgery`.
- `AttackTechnique` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-aspnet/SKILL.md`: the parser-error differential probe with seven payload shapes. Fits `deserialization-signed-forgery` `## Bypass Techniques`.
- `DefensiveControl` <- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/deserialization/java-insecure-deserialization-ysoserial/SKILL.md`: ObjectInputFilter allow-list (JEP 290), WAF signatures, JSON or protobuf refactor. Fits parent `## Bypass Techniques` and `## False Positives`.
- `ObservableSignal` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-aspnet/SKILL.md`: "Validation of viewstate MAC failed" versus "state information is invalid" response classes. Fits `## Detection Channels`.

**References/scripts candidates**

- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W3/exploiting-insecure-deserialization/scripts/agent.py` (178 lines): a serialized-format fingerprint scanner with magic-prefix and cookie scanning. Generalisable to an abstract detection helper. Candidate example in `references/`. Confidence: medium. It names concrete prefixes and formats, so adaptation is required.

## insecure-file-uploads

Group: parent `insecure-file-uploads` plus `upload-server-execution`, `upload-client-execution`, `upload-archive-extraction`, `upload-toolchain-execution`, `upload-pipeline-deferred-trust`.

**Sources matched**

- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-file-upload/SKILL.md` (extension and MIME bypass table, magic bytes, SVG XSS, DOCX XXE, ZIP slip and symlink, ImageMagick and FFmpeg SSRF, headless-Chrome PDF SSRF).
- `/Users/diekgbbtt/hacking-skills/skills/web/logic/insecure-file-upload/SKILL.md`.
- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/deep-dive-labs/file-upload/SKILL.md`.
- Index-level cross-reference: `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-xxe/SKILL.md` (office and SVG upload XXE).
- Anthropic: no catalog or accepted file-upload skill exists.

**Similarity**

Strong across all five variants.
The extension and magic-byte bypasses match `upload-server-execution`.
Same-origin serving and sniffing-guard state match `upload-client-execution`.
ZIP slip and symlink escape match `upload-archive-extraction`.
Converter and metadata-parser execution match `upload-toolchain-execution`.
Finalize swaps, presigned header control, and pre-verdict fetch match `upload-pipeline-deferred-trust`.

**Boundary**

The signature is the failing pipeline clause: placement, render, extraction, toolchain, or gate-timing.
The sources add no new clause.
ImageMagick, FFmpeg, and headless-Chrome SSRF and file reads are the toolchain clause, because the converter reaches external IO. The parent already names file-read operators and external resources.
Office-document XXE is the `xxe` class, not this class. Cross-reference only.

**New-skill proposals**

None. No source material diverges from the five-clause signature.

**Enrichment candidates**

- `PayloadPattern` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-file-upload/SKILL.md` and `/Users/diekgbbtt/hacking-skills/skills/web/logic/insecure-file-upload/SKILL.md`: magic-byte prefixes, `GIF89a` polyglot, double and null extensions, MIME spoof, `.htaccess` and `web.config` upload. Fits `upload-server-execution` `## Bypass Techniques`.
- `AttackTechnique` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-file-upload/SKILL.md`: converter SSRF via MVG, SVG `xlink:href`, FFmpeg HLS and concat, and headless-Chrome PDF `iframe` and `@import`. Fits `upload-toolchain-execution` `## Key Vulnerabilities`.
- `AttackTechnique` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-file-upload/SKILL.md`: symlink and TAR symlink archive escape. Fits `upload-archive-extraction`.
- `ObservableSignal` <- `/Users/diekgbbtt/hacking-skills/skills/web/logic/insecure-file-upload/SKILL.md`: same-origin versus separate-domain serving check. Fits `upload-client-execution` `## Detection Channels`.
- `PreconditionEnvironment` <- `/Users/diekgbbtt/hacking-skills/skills/web/logic/insecure-file-upload/SKILL.md`: office documents are ZIP plus XML internally. Fits the parent `## Attack Surface` and the `xxe` cross-reference.

**References/scripts candidates**

None. `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/deep-dive-labs/file-upload/scripts/process.py` is a skill-structure validator, not a test harness.

## path-traversal-lfi-rfi

Group: parent `path-traversal-lfi-rfi` plus `traversal-read`, `lfi-include-execution`, `rfi-remote-include`, `archive-zipslip-write`.

**Sources matched**

- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-lfi/SKILL.md` (PHP filter-chain RCE, wrappers, log and session poisoning, phar, zip slip, ImageMagick coder read, blind OOB gate, Apache and PHP-CGI CVEs).
- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W6/performing-directory-traversal-testing/SKILL.md`.
- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/deep-dive-labs/path-traversal/SKILL.md`.
- `/Users/diekgbbtt/hacking-skills/skills/web/authz/path-traversal/SKILL.md`.

**Similarity**

Strong across all four variants.
Traversal encodings and masked-content adjudication match `traversal-read`.
Wrapper invocation and poison-then-include match `lfi-include-execution`.
Scheme-qualified names and outbound callbacks match `rfi-remote-include`.
Traversal entries and symlink escape match `archive-zipslip-write`.

**Boundary**

The signature is file-operation locus crossed with effect oracle.
One source technique does not map onto a variant.
PHP filter-chain code execution forges an arbitrary include payload in memory through chained charset conversions.
It needs no upload, no writable path, and no poisoned state.
`lfi-include-execution` owns poisoning plus wrapper handler invocation, and no parent step names conversion-chain byte forging.
This diverges on the trust-assumption and impact boundary attributes.

**New-skill proposals**

1. `source`: `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-lfi/SKILL.md` Phase 4 (PHP filter-chain to RCE, Synacktiv 2022).
   `[NEW] target`: `lfi-filter-chain-code-execution` (proposed variant of `path-traversal-lfi-rfi`).
   Rationale: the bent step is forging a full include payload from conversion-chain output, so a bare file-read primitive upgrades to execution without poisoning. The parent baseline is present: a `php://filter` read sink sits inside `lfi-include-execution`. The variant owns its own proof: the forged payload executes and the output confirms. Confidence: medium-high. This is the strongest proposal in the slice.

**Enrichment candidates**

- `AttackTechnique` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-lfi/SKILL.md` Phase 8b: ImageMagick coder read (`msl:`, `label:@`), and zip or tar symlink escape. Fits `traversal-read` and `archive-zipslip-write`.
- `AttackTechnique` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-lfi/SKILL.md`: the blind-LFI OOB confirmation gate, and the false-positive rule that an echoed path is not a read. Fits `## Detection Channels` and `## False Positives`.
- `PayloadPattern` <- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W6/performing-directory-traversal-testing/SKILL.md` and `hunt-lfi`: separator and encoding sets, wrapper URIs, session and log poisoning paths. Fits `traversal-read` and `lfi-include-execution` `## Bypass Techniques`.
- `DefensiveControl` <- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W6/performing-directory-traversal-testing/SKILL.md`: canonical-path resolution with allow-list, and disabled wrappers. Fits the parent `## Bypass Techniques`.
- `ObservableSignal` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-lfi/SKILL.md`: base64 source that decodes to valid source, as read proof. Fits `traversal-read` `## Detection Channels`.

**References/scripts candidates**

- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W6/performing-directory-traversal-testing/scripts/agent.py`: a traversal payload harness with in-root indicator matching (`root:x:`, `[fonts]`). Generalisable with adaptation. Candidate example in `references/`. Confidence: medium.

## graphql

Group: parent `graphql`. The class does not decompose, so there are no leaves.

**Sources matched**

- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-graphql/SKILL.md` (REST and GraphQL dual-write desync, node and GID IDOR, subscriptions, alias batching resolver model, negative query cost, field-level authz).
- `/Users/diekgbbtt/hacking-skills/skills/web/logic/graphql-idor-via-introspection-leak/SKILL.md`.
- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W5/performing-graphql-security-assessment/SKILL.md`, `accepted/W5/performing-graphql-depth-limit-attack/SKILL.md`, `accepted/W5/performing-graphql-introspection-attack/SKILL.md`.
- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/apis/graphql-idor/SKILL.md`, `.../apis/graphql-introspection-abuse/SKILL.md`, `.../api-security/graphql-batching-attacks/SKILL.md`, `.../api-security/graphql-injection-introspection/SKILL.md`, `.../deep-dive-labs/graphql-labs/SKILL.md`.
- Index-level: `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-fintech-graphql/SKILL.md`.

**Similarity**

Sufficient.
The sources restate the parent's introspection, injection, DoS, authorization, batching, and error steps with concrete payloads.
No source proposes a class axis the analysis did not already test.

**Boundary**

The `graphql` analysis exits at STATE 2 branch 2a with zero discriminators, so the class emits one skill.
Every source feature is either covered by its own parent step or owned procedurally by another skill (injection by the sink classes, authorization by the two-principal skill).
One source surface is absent from the base body: GraphQL subscriptions over a WebSocket push channel.
The parent body and the analysis technique ledger do not name subscriptions.
Subscriptions could bend a step if subscribing to another user's channel is a different kind of action than requesting a foreign object. The analysis treated transport and capability as aspects. Confidence: low. Flag as a possible variant and a certain enrichment.

**New-skill proposals**

1. `source`: `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-graphql/SKILL.md` (subscription hijacking section).
   `[NEW] target`: `graphql-subscription-hijack` (proposed variant of `graphql`).
   Rationale: a push channel carries its own authorization step (channel and topic scope) that no request-time resolver step names. If that step is not coverable by the parent's object-level sweep, it is a variant. Confidence: low. The analysis ruled the class non-decomposing, so a reviewer may prefer enrichment into the base body. Flag for the synthesis ruling.

**Enrichment candidates**

- `AttackTechnique` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-graphql/SKILL.md`: REST and GraphQL dual-write desync with a revocation sequence, the alias-batching resolver-model decision table, and negative query-cost abuse. Fits `## Advanced Techniques` and `## Key Vulnerabilities`.
- `AttackTechnique` <- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W5/performing-graphql-security-assessment/SKILL.md`: fragment-spread depth bypass, fragment circular reference, batch login and OTP brute force, directive injection. Fits the DoS and batching sections.
- `AttackTechnique` <- `/Users/diekgbbtt/hacking-skills/skills/web/logic/graphql-idor-via-introspection-leak/SKILL.md`: relay node decode and re-encode, field-alias introspection bypass. Fits `## Reconnaissance` and `## Bypass Techniques`.
- `ObservableSignal` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-graphql/SKILL.md`: suggestion text, unknown-field versus unauthorized-field differential, foreign PII in `data`. Fits `## Detection Channels`.

**References/scripts candidates**

- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W5/performing-graphql-security-assessment/scripts/agent.py`: a GraphQL assessment harness for introspection, authz, depth, and injection. Generalisable with adaptation. Candidate example in `references/`. Confidence: medium.
- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W5/performing-graphql-security-assessment/references/api-reference.md`: a test-and-expected-response table. Useful shape, but concrete. Adaptation required.

## llm-prompt-injection

Group: parent `llm-prompt-injection` plus `direct-injection-override`, `indirect-injection-plant`, `context-leakage`, `tool-abuse`, `output-handling`.

**Sources matched**

- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-llm-ai/SKILL.md` (false-positive gate, ASCII and Unicode tag smuggling, markdown-image and tool-use exfil, IDOR-via-AI, multimodal injection, backend fingerprinting, code-sabotage).
- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-rag-vector/SKILL.md` (vector-store IDOR, persistent corpus poisoning, source-text leak, retrieval hijack).
- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/ai-red-teaming/llm-attacks/llm-direct-prompt-injection/SKILL.md`, `.../llm-attacks/llm-indirect-prompt-injection/SKILL.md`, `.../model-exploitation/ai-prompt-leaking/SKILL.md`, `.../model-exploitation/ai-jailbreak-obfuscation-ciphers/SKILL.md`, `.../agent-security/ai-agent-tool-abuse-and-privilege-escalation/SKILL.md`, `.../agent-security/mcp-protocol-exploitation/SKILL.md`, `.../model-extraction/model-inversion-attacks/SKILL.md`, `.../model-exploitation/data-extraction-training-data/SKILL.md`, `.../ml-security/rag-poisoning-and-data-exfiltration/SKILL.md`.
- `/Users/diekgbbtt/anthropic-cybersecurity-skills/catalog/catalog.json` entries `detecting-ai-model-prompt-injection-attacks`, `detecting-indirect-prompt-injection`, `testing-prompt-injection-in-rag-pipelines`, `testing-for-system-prompt-leakage`, `red-teaming-llms-with-garak`, `orchestrating-llm-attacks-with-pyrit`, `assessing-vector-and-embedding-weaknesses`, `continuous-llm-red-teaming-with-promptfoo`.

**Similarity**

Strong for the five variants.
Encoding and wrapper jailbreaks and authority claims match `direct-injection-override`.
Hidden placement, corpus seeding, and victim trigger match `indirect-injection-plant`.
Verbatim-repeat extraction and schema disclosure match `context-leakage`.
Tool steering and argument injection match `tool-abuse`.
Markup emission and exfil channels match `output-handling`.

**Boundary**

The signature is entry channel crossed with proving sink.
The sources confirm the five variants and add no new axis inside that signature.
Three source clusters break clauses outside the prompt-context boundary.
First, training-data extraction, model inversion, and membership inference reproduce memorized weights, not hidden prompt context.
Second, the vector store and retrieval layer has storage and isolation clauses that no prompt step owns.
Third, the MCP tool server exposes tool endpoints directly, so server-side permission enforcement differs from steering the model through a prompt.

**New-skill proposals**

1. `source`: `/Users/diekgbbtt/awsome-offensive-security-skill/skills/ai-red-teaming/model-extraction/model-inversion-attacks/SKILL.md`, `.../model-exploitation/data-extraction-training-data/SKILL.md`, `.../model-exploitation/llm-training-data-extraction/SKILL.md`, `.../model-exploitation/prompt-leaking-system-prompts/SKILL.md`, reinforced by catalog `testing-for-system-prompt-leakage`.
   `[NEW] target`: `llm-training-data-extraction` (proposed new class).
   Rationale: the trust assumption is that the model does not reproduce memorized training records. The bent steps are prefix-completion probing, mode-collapse forcing, and membership inference through log-probability. `context-leakage` owns only hidden prompt context, so no variant covers this. Baseline is present (an LLM-backed feature). Confidence: medium.

2. `source`: `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-rag-vector/SKILL.md`, reinforced by catalog `testing-prompt-injection-in-rag-pipelines` and `assessing-vector-and-embedding-weaknesses`, and `/Users/diekgbbtt/awsome-offensive-security-skill/skills/ai-red-teaming/ml-security/rag-poisoning-and-data-exfiltration/SKILL.md`.
   `[NEW] target`: `rag-vector-store-weakness` (proposed new class, or a variant of `llm-prompt-injection`).
   Rationale: the storage and retrieval layer has its own bent steps: unauthenticated vector-database read, cross-tenant namespace access, source-text and metadata leak, and retrieval hijack. These hold with no injection payload at all. Baseline is present (a RAG-backed feature). Confidence: medium.

3. `source`: `/Users/diekgbbtt/awsome-offensive-security-skill/skills/ai-red-teaming/agent-security/mcp-protocol-exploitation/SKILL.md`.
   `[NEW] target`: `mcp-tool-server` (proposed new class, or a variant of `tool-abuse`).
   Rationale: the MCP server exposes tool endpoints directly, so tool listing, server-side permission enforcement, and cross-tool chains are server-surface tests, not prompt steering. Baseline is present (a reachable tool layer). Confidence: medium.

**Enrichment candidates**

- `AttackTechnique` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-llm-ai/SKILL.md`: ASCII and Unicode Tags-block smuggling (U+E0000 to U+E007F), zero-width and bidi and homoglyph variants, and multimodal image-embedded instructions. Fits `direct-injection-override` and `output-handling` `## Bypass Techniques`.
- `AttackTechnique` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-llm-ai/SKILL.md`: markdown-image zero-click exfil, tool-use exfil, and DNS-only exfil. Fits `output-handling` and `tool-abuse`.
- `ObservableSignal` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-llm-ai/SKILL.md`: run-twice reproducibility, anchor-to-known-secret, and OOB callback proof. Fits `## Detection Channels` and `## False Positives`.
- `PayloadPattern` <- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/ai-red-teaming/model-exploitation/ai-jailbreak-obfuscation-ciphers/SKILL.md`: base64, ROT13, and leetspeak wrappers. Fits `direct-injection-override` `## Bypass Techniques`.
- `AttackTechnique` <- catalog `orchestrating-llm-attacks-with-pyrit`: multi-turn gradual escalation and tree-of-attacks search. Fits `direct-injection-override` `## Advanced Techniques`.
- `AttackerCapability` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-rag-vector/SKILL.md`: hold a second clean session to prove persistent poisoning. Fits `indirect-injection-plant` `## Adversarial Capabilities`.

**References/scripts candidates**

None generalisable. The LLM sources carry inline payload packs and tool commands only. No source `references/` or `scripts/` file in this group is a reusable test asset.

## Residual candidates

Residual material has no adequate home in the current suite. Each item names the new class, new variant, or new technique leaf.

1. `llm-training-data-extraction` (new class). Source: `/Users/diekgbbtt/awsome-offensive-security-skill/skills/ai-red-teaming/model-extraction/model-inversion-attacks/SKILL.md`, `.../model-exploitation/data-extraction-training-data/SKILL.md`, `.../model-exploitation/llm-training-data-extraction/SKILL.md`. Memorized-record regurgitation and membership inference. No base home. Confidence: medium. (Also proposed under `llm-prompt-injection`.)

2. `rag-vector-store-weakness` (new class). Source: `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-rag-vector/SKILL.md`, catalog `assessing-vector-and-embedding-weaknesses`, `.../ml-security/rag-poisoning-and-data-exfiltration/SKILL.md`. Vector-store isolation, metadata leak, and retrieval hijack. Confidence: medium. (Also proposed under `llm-prompt-injection`.)

3. `mcp-tool-server` (new class). Source: `/Users/diekgbbtt/awsome-offensive-security-skill/skills/ai-red-teaming/agent-security/mcp-protocol-exploitation/SKILL.md`. Direct MCP tool-endpoint testing. Confidence: medium. (Also proposed under `llm-prompt-injection`.)

4. `crypto-cipher-mode-weakness` (new variant). Source: `/Users/diekgbbtt/hacking-skills/skills/mobile/crypto/mobile-weak-crypto/SKILL.md`. ECB, static IV, predictable IV, non-CSPRNG. Confidence: medium. (Also proposed under `crypto-weakness`.)

5. `crypto-key-reference-injection` (new variant). Source: `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-jwt-crypto/SKILL.md` (kid, jku, x5u, jwk). Confidence: medium. (Also proposed under `crypto-weakness`.)

6. `lfi-filter-chain-code-execution` (new variant). Source: `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-lfi/SKILL.md` Phase 4. Confidence: medium-high. (Also proposed under `path-traversal-lfi-rfi`.)

7. `deserialization-parser-order-bypass` (new variant). Source: `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-aspnet/SKILL.md`. Dual-parser MAC-before-parse. Confidence: low. (Also proposed under `insecure-deserialization`.)

8. `lookup-injection` (new class). Source: `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-deserialization/SKILL.md` Phase 5 (JNDI, Log4Shell). Interpolation reaches a remote class loader. Confidence: low.

9. `graphql-subscription-hijack` (new variant). Source: `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-graphql/SKILL.md`. Cross-user push-channel subscription. Confidence: low. (Also proposed under `graphql`.)

10. `llm-model-poisoning` (new class). Source: `/Users/diekgbbtt/awsome-offensive-security-skill/skills/ai-red-teaming/model-exploitation/ai-data-poisoning/SKILL.md`, `.../ml-security/data-poisoning-and-backdoors/SKILL.md`, `.../supply-chain-analysis/llm-supply-chain-poisoning/SKILL.md`, `.../adversarial-ml/ai-data-poisoning-model-skewing/SKILL.md`. Training-time and supply-chain poisoning. Confidence: low. This may be out of scope for a live-target testing suite, because the target is a training pipeline, not a reachable endpoint.

11. `llm-overreliance-hallucination` (no home). Source: `/Users/diekgbbtt/awsome-offensive-security-skill/skills/ai-red-teaming/model-exploitation/llm-overreliance-hallucination/SKILL.md`. Confidence: low. Impact depends on user trust, so it may not be a testable weakness class.

12. AI code-completion sabotage (technique leaf). Source: `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-llm-ai/SKILL.md` (code-review and completion sabotage section). No base home. Confidence: low.

13. `ai-data-extraction-via-ssrf` (cross-reference). Source: `/Users/diekgbbtt/awsome-offensive-security-skill/skills/ai-red-teaming/model-exploitation/ai-data-extraction-via-ssrf/SKILL.md`. Likely belongs to `ssrf` plus the model-data layer. Confidence: low.

## Slice summary

Groups: 6. Base skills: 26. Source skills read in full: 20. Source skills indexed only: about 30.

Similarity outcome per group:

| Group | Similarity | New-skill proposals | Enrichment candidates | References/scripts |
|---|---|---|---|---|
| crypto-weakness | strong to signing-forgery; partial elsewhere | 2 | 5 | 0 |
| insecure-deserialization | strong | 2 | 6 | 1 |
| insecure-file-uploads | strong | 0 | 5 | 0 |
| path-traversal-lfi-rfi | strong | 1 | 5 | 1 |
| graphql | sufficient; class does not decompose | 1 (low confidence) | 4 | 2 |
| llm-prompt-injection | strong | 3 | 6 | 0 |

Totals: 9 new-skill proposals, 31 enrichment candidates, 4 references/scripts candidates, 13 residual candidates.

Highest-confidence proposal: `lfi-filter-chain-code-execution`, from `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-lfi/SKILL.md` Phase 4.

Proposals to rule first, because they may collapse into an existing variant or into the separate `authentication-jwt` group: `crypto-cipher-mode-weakness`, `crypto-key-reference-injection`, `deserialization-parser-order-bypass`, `graphql-subscription-hijack`.

Low-confidence residual items to rule out or defer: `llm-model-poisoning`, `llm-overreliance-hallucination`, `lookup-injection`, AI code-completion sabotage, `ai-data-extraction-via-ssrf`.

No suite file was modified. No git command was run.
