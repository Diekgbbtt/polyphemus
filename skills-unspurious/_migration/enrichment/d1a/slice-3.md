# D1a enrichment slice 3

*Report only. No suite skill is modified. No git action is taken.*

## Slice header

Groups in this slice (each a level-1 directory under `skills-unspurious/`, with the parent `SKILL.md` plus its level-2 variant leaves):

- `crypto-weakness` - 1 parent + 3 variants
- `insecure-deserialization` - 1 parent + 3 variants
- `insecure-file-uploads` - 1 parent + 5 variants
- `path-traversal-lfi-rfi` - 1 parent + 4 variants
- `graphql` - 1 parent + 0 variants (declared non-decomposing)
- `llm-prompt-injection` - 1 parent + 5 variants

Base skills examined: 26.

Source repositories indexed and searched: `/Users/diekgbbtt/hacking-skills/skills` (43), `/Users/diekgbbtt/claude-bug-hunter/skills` (105), `/Users/diekgbbtt/anthropic-cybersecurity-skills` (`accepted/` 82 skill directories plus `catalog/catalog.json` 818 entries), `/Users/diekgbbtt/awsome-offensive-security-skill/skills` (370).

Normative docs read first: `docs/design/skills-variant-boundary.md` and `docs/design/skills-ontology.md`.

The algorithm, as specified by the operator, is applied literally per base skill: match on vulnerability class or on chainable techniques; where similarity is insufficient, apply the boundary attributes; where sufficient, macro semantic diff and abstract to ontology entities; then assess references and scripts for generalised examples.

Boundary attributes used from the variant-boundary doc: vuln-specific reconnaissance, attack-surface part family, communication protocol, trust-assumption difference, impact.

Ontology entities used for enrichment (from the ontology doc): `PreconditionEnvironment`, `TechnologyStack` (NEVER in body), `DefensiveControl`, `VulnerabilityClass`, `AttackGoal`, `AttackerCapability`, `AttackTechnique`, `PayloadPattern`, `Artifact`, `ObservableSignal`.

---

## Group: crypto-weakness

## crypto-weakness (parent)

**Sources matched**
- `/Users/diekgbbtt/hacking-skills/skills/web/auth/jwt-misconfig/SKILL.md` - JWT alg confusion, `alg:none`, weak HMAC secret cracking, `kid`/`jku` key-source injection; same class as `crypto-signing-key-forgery`.
- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-jwt-crypto/SKILL.md` - forgeable JWT signature flaws plus `kid`/`jku`/`jwk` injection and cross-tenant claim swap; the richest match to the signing-key variant.
- `/Users/diekgbbtt/hacking-skills/skills/web/session/cookie-attacks/SKILL.md` - session-cookie attribute audit plus token-entropy sampling; matches `crypto-predictable-token` entropy work.
- `/Users/diekgbbtt/hacking-skills/skills/web/session/session-fixation/SKILL.md` - predictable session IDs plus fixation; matches token predictability only partially.
- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-session/SKILL.md` - fixation, post-logout replay, entropy, refresh-token rotation reuse; adjacent class.
- `/Users/diekgbbtt/hacking-skills/skills/mobile/crypto/mobile-weak-crypto/SKILL.md` - weak algorithms (ECB, DES), hardcoded keys, static IV; a mobile app class.
- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W1/exploiting-jwt-algorithm-confusion-attack/SKILL.md` and `accepted/W1/performing-jwt-none-algorithm-attack/SKILL.md` - JWT forgery, procedural.
- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/apis/jwt-algorithm-confusion/SKILL.md`, `.../apis/jwt-null-signature/SKILL.md`, `.../api-security/jwt-forgery-algorithm-confusion/SKILL.md` - same JWT forgery techniques.
- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-tls-network/SKILL.md` - TLS/DNS misconfiguration (weak ciphers, HSTS, SPF/DMARC); a transport-config class.

**Similarity**
Sufficient for `jwt-misconfig` and `hunt-jwt-crypto` against `crypto-signing-key-forgery`. The signing-key variant and these sources run the same procedure: recover or remove the key basis, then mint claims.
Sufficient (aspect-level) for `cookie-attacks` entropy sampling against `crypto-predictable-token`.
Insufficient for `session-fixation` and `hunt-session` fixation/invalidation. Insufficient for `mobile-weak-crypto` (mobile static and dynamic analysis). Insufficient for `hunt-tls-network` (transport config).

**Boundary**
- `jwt-misconfig`, `hunt-jwt-crypto`: no attribute diverges. Same vulnerability class, same trust clause (the signature binds claims to a strong secret under a pinned algorithm). Treat as enrichment.
- `cookie-attacks` entropy: no attribute diverges. Token-entropy sampling is an aspect inside `crypto-predictable-token`.
- `session-fixation`, `hunt-session`: **trust-assumption difference**. The crypto class assumes the artifact value must be unpredictable. Fixation assumes the server accepts a client-chosen identifier, which is a different agreement. Reconnaissance also diverges (cookie-lifecycle testing, not offline derivation).
- `mobile-weak-crypto`: **attack-surface part family** diverges (decompiled app binary, JADX/Frida) and **trust-assumption difference** diverges (data-at-rest confidentiality, not artifact unpredictability). The source is also outside the web-testing scope the operator fixed. Non-match.
- `hunt-tls-network`: **attack-surface part family** and **trust-assumption difference** diverge (transport confidentiality, not artifact unforgeability). Non-match for this class.

**New-skill proposals**

- source: `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-session/SKILL.md` and `/Users/diekgbbtt/hacking-skills/skills/web/session/session-fixation/SKILL.md`
  - [NEW] target: `session-management`
  - Extended rationale: the base suite carries no session class. `crypto-weakness` owns artifact unpredictability, key recovery, and comparison timing. It does not own session fixation, post-logout replay, invalidation-on-credential-change, or refresh-token rotation reuse detection. The trust assumption differs at the root: the server trusts a client-supplied session identifier (fixation) or trusts that a rotated token is single-use (rotation reuse). The reconnaissance differs: cookie lifecycle and two-session flows, not offline derivation. Both sources run a full, stable procedure. Confidence: medium. Caveat: this is a new class, not a variant, and the base suite lacks the baseline it extends. The operator's example warning applies in spirit, so treat this as a class-authoring proposal, not a leaf append. The alternative is to scope it as a new variant of `crypto-weakness` on the "server-chosen-identifier" clause, but that clause is not a crypto clause.

- source: `/Users/diekgbbtt/hacking-skills/skills/mobile/crypto/mobile-weak-crypto/SKILL.md` and `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/deep-dive-labs/business-logic/SKILL.md` (Lab 11, padding oracle)
  - [NEW] target: `crypto-oracle-decryption`
  - Extended rationale: the base class's signature is (structure and randomness, key, comparison). A padding oracle or a decryption-endpoint oracle bends a fourth, uncovered clause: the ciphertext-opacity clause. The class trusts that the ciphertext is opaque and that a decryption endpoint leaks no bit of plaintext. The procedure differs: submit crafted ciphertext blocks, read a padding or MAC verdict, and flip bits position by position. It is not prediction, not key recovery, and not comparison timing. Confidence: low. The sources are thin (one lab line plus the mobile ECB and static-IV material), and the mobile source is out of scope. Flag for operator assessment. If accepted, it is a new variant of `crypto-weakness` (a fourth discriminator value) rather than a new class.

**Enrichment candidates**
- `AttackTechnique` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-jwt-crypto/SKILL.md` and `/Users/diekgbbtt/hacking-skills/skills/web/auth/jwt-misconfig/SKILL.md`: key-source injection. The verifier derives its key from attacker-controlled token input (`kid` path traversal, `jku`/`x5u` URL, embedded `jwk`). This is a third technique beside offline search and algorithm removal. Abstract as "the verifier resolves its key basis from attacker-influenced input". Flag: overlaps `authentication-jwt`, which is the natural owner of JWT-specific header injection.
- `PayloadPattern` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-jwt-crypto/SKILL.md`: claim-swap for cross-tenant access. Decode a real artifact, read the tenant and role claim names, and rewrite only those claims. Abstract as "mint the claim set that controls identity, role, or tenant".
- `AttackTechnique` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-jwt-crypto/SKILL.md`: automation-first recon. Run the forgery suite (all modes) before manual chaining. Process guidance, low value, abstract to a Pro Tip rather than a step.
- `ObservableSignal` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-session/SKILL.md`: rotation-reuse detection. Replay a superseded refresh token and watch for a reuse alarm. This is a token-lifetime signal, not a crypto signal. Flag as adjacent and route to `oauth` or `authentication-jwt`.

**References/scripts candidates**
- None. The generalised JWT payload material in `/Users/diekgbbtt/claude-bug-hunter/skills/security-arsenal/SKILL.md` (JWT attacks section) belongs to `authentication-jwt`, not to `crypto-weakness`. No crypto-weakness-specific generalised reference is present.

## crypto-predictable-token

**Sources matched**
- `/Users/diekgbbtt/hacking-skills/skills/web/session/cookie-attacks/SKILL.md` - Burp Sequencer entropy sampling over 200+ tokens.
- `/Users/diekgbbtt/hacking-skills/skills/web/session/session-fixation/SKILL.md` - predictable-ID signals (sequential, timestamp, short length).

**Similarity** Sufficient. Both are aspect-level detail inside the existing entropy and predictability work.

**Boundary** None diverges. Token-entropy measurement is an aspect, not a new axis.

**New-skill proposals** None.

**Enrichment candidates**
- `AttackTechnique` <- `/Users/diekgbbtt/hacking-skills/skills/web/session/cookie-attacks/SKILL.md`: entropy-bound adjudication. Collect a large sample, feed it to an entropy analyser, and compare the effective bits against the strong-randomness bound. The base variant already owns entropy collection. Add only the explicit "effective-bits versus bound" verdict.

**References/scripts candidates** None.

## crypto-signing-key-forgery

**Sources matched**
- `/Users/diekgbbtt/hacking-skills/skills/web/auth/jwt-misconfig/SKILL.md` - offline secret cracking, `alg:none`, key confusion.
- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-jwt-crypto/SKILL.md` - the same, plus `kid`/`jku`/`jwk` injection and weak-secret cracking.
- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/apis/jwt-algorithm-confusion/SKILL.md`, `.../apis/jwt-null-signature/SKILL.md`, `.../api-security/jwt-forgery-algorithm-confusion/SKILL.md` - same.

**Similarity** Sufficient. Same class, same procedure, richer in one clause.

**Boundary** No attribute diverges for the shared techniques. The `kid`/`jku`/`jwk` key-source injection is discussed under the parent enrichment. It does not warrant a variant because the bent step (obtain a key basis) is still the recovery step; only the key source changes.

**New-skill proposals** None.

**Enrichment candidates**
- `AttackTechnique` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-jwt-crypto/SKILL.md`: key-source injection (as under the parent). Add a third technique block beside "Offline Secret Search With Local Re-Verification" and "Algorithm Removal Acceptance". Abstract: "resolve the key basis from attacker-influenced verifier input".
- `AttackTechnique` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-jwt-crypto/SKILL.md`: local-verify-before-send discipline. Confirm each minted candidate locally before the endpoint. The base variant already states this. Low value.
- `AttackTechnique` <- `/Users/diekgbbtt/hacking-skills/skills/web/auth/jwt-misconfig/SKILL.md`: expiry and `nbf` claim manipulation. Remove `exp`, or set `nbf` past and `exp` far future. Abstract as a claim-choice aspect inside minting. Low value.

**References/scripts candidates** None.

## crypto-timing-oracle

**Sources matched**
- `/Users/diekgbbtt/hacking-skills/skills/web/auth/jwt-misconfig/SKILL.md` - weak-secret cracking is offline, not timing. No timing-oracle content.
- No source carries a comparison-timing extraction procedure beyond the base.

**Similarity** Insufficient. No source runs the baseline-calibrated prefix-extraction procedure.

**Boundary** Not applicable. No candidate is close enough to test a boundary attribute.

**New-skill proposals** None.

**Enrichment candidates** None.

**References/scripts candidates** None.

**Verdict for this group**: clean no-match for `crypto-timing-oracle`. Two new-skill proposals are raised (one medium, one low confidence). The signing-key variants have strong enrichment candidates.

---

## Group: insecure-deserialization

## insecure-deserialization (parent)

**Sources matched**
- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-deserialization/SKILL.md` - Java ysoserial, PHP object injection, pickle, .NET ViewState, Ruby Marshal, JNDI/Log4Shell, `phar://`, YAML, `node-serialize`. Strongest match.
- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W3/exploiting-insecure-deserialization/SKILL.md` - same class, procedural, with a format-signature inventory.
- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/deserialization/java-insecure-deserialization-ysoserial/SKILL.md` - Java serialized-object signatures and gadget chains.
- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/deserialization/nodejs-deserialization-rce/SKILL.md` - Node `node-serialize` IIFE.
- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/web-vulnerabilities/php-deserialization-rce/SKILL.md` - PHP object injection, PHPGGC, custom chain.
- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/deep-dive-labs/insecure-deserialization/SKILL.md` - PortSwigger labs, including `phar://`.
- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-aspnet/SKILL.md` - ViewState signed-only versus encrypted, machineKey recovery, dual-parser MAC bypass.
- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-sharepoint/SKILL.md` - ViewState and deserialization on SharePoint.

**Similarity** Sufficient. All sources run the same class: an untrusted blob reaches a decoder that instantiates attacker-influenced objects.

**Boundary** No attribute diverges for the core blob-to-decoder techniques. One candidate bends a step and is discussed below (JNDI). The rest are aspects.

**New-skill proposals**
- None firm. See the JNDI note under enrichment, flagged as a possible fourth variant rather than a firm proposal.

**Enrichment candidates**
- `AttackTechnique` and `PayloadPattern` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-deserialization/SKILL.md`: interpolation-triggered remote lookup (JNDI and Log4Shell). A string carrying a lookup directive in any logged field triggers a remote class fetch. Abstract as "a reference value in an ordinary field causes a remote codebase fetch". Flag: the base parent describes "attacker-controlled byte streams or structured blobs to a native unmarshal function". A JNDI lookup is not a blob. The parent's "wrapper-triggered implicit deserialization" covers reference-triggered resolution in shape, but not the remote codebase fetch over LDAP/RMI. Decision-grade call: add as an enrichment to the parent and to `deserialization-gadget-chain` first. If the remote-fetch step proves uncoverable by "reference-triggered resolution", escalate to a fourth variant `deserialization-remote-lookup`.
- `AttackTechnique` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-aspnet/SKILL.md`: dual-parser MAC bypass. Two parsers disagree on the signed region, so a signature verifies over one region while a different region executes. Enrichment to `deserialization-signed-forgery` Bypass Techniques. Abstract as "binding-region disagreement between two parsers".
- `AttackTechnique` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-aspnet/SKILL.md`: machineKey or signing-key recovery from known plaintext. Enrichment to `deserialization-signed-forgery` weak-secret recovery. It is the same step with a known-plaintext shortcut. Low value.
- `PayloadPattern` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-deserialization/SKILL.md`: `phar://` polyglot construction (valid image magic bytes plus a PHAR archive). Enrichment to `deserialization-deferred-trigger` wrapper-implicit shapes. The base already owns wrapper path references; add only the polyglot construction detail.
- `AttackTechnique` <- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/web-vulnerabilities/php-deserialization-rce/SKILL.md`: type-juggling inside a PHP serialized string (string to integer for loose comparison). Enrichment to the parent Key Vulnerabilities as an aspect. Low value.

**References/scripts candidates**
- `references/deserialization-signatures.md` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-deserialization/SKILL.md` plus `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W3/exploiting-insecure-deserialization/SKILL.md`: a generalised format-signature table (binary and base64 prefixes per runtime family, content types, cookie markers). It is generalised, stable across versions, and bulky. Good candidate.
- `references/deserialization-oracle.md` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-deserialization/SKILL.md`: the callback or delay safe-oracle workflow with bounded-effect proof discipline. Generalised. Medium candidate.

## deserialization-gadget-chain

**Sources matched**
- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-deserialization/SKILL.md` - chain selection, OOB first, session-store priority.
- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/deserialization/java-insecure-deserialization-ysoserial/SKILL.md` - signature detection plus OOB URLDNS gating.
- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W3/exploiting-insecure-deserialization/SKILL.md` - same.

**Similarity** Sufficient. Same procedure: fingerprint inventory, gate on a no-exec oracle, then assemble a matched chain.

**Boundary** No attribute diverges. Self-executing encodings and type-named construction are already owned by this variant.

**New-skill proposals** None.

**Enrichment candidates**
- `AttackTechnique` <- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/deserialization/java-insecure-deserialization-ysoserial/SKILL.md`: the `URLDNS` gadget as the canonical no-exec oracle. The base owns the no-exec oracle. Add the "DNS-only gadget as the cheapest liveness probe" detail.
- `AttackTechnique` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-deserialization/SKILL.md`: the JNDI lookup technique (as under the parent). If kept at the parent, no duplication here.

**References/scripts candidates** None beyond the parent reference.

## deserialization-signed-forgery

**Sources matched**
- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-aspnet/SKILL.md` - ViewState signed-only versus encrypted, machineKey recovery, dual-parser MAC bypass.
- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-sharepoint/SKILL.md` - ViewState handling.
- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-deserialization/SKILL.md` - weak-key and unsigned-fallback state.

**Similarity** Sufficient. Same procedure: break the binding, then mint a state blob.

**Boundary** No attribute diverges. MachineKey recovery is the same weak-secret step.

**New-skill proposals** None.

**Enrichment candidates**
- `AttackTechnique` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-aspnet/SKILL.md`: dual-parser MAC bypass (as under the parent). Best home is this variant's Bypass Techniques.
- `AttackTechnique` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-aspnet/SKILL.md`: known-plaintext machineKey recovery. Enrichment to weak-secret recovery.
- `ObservableSignal` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-aspnet/SKILL.md`: "signed-only versus encrypted" adjudication. Distinguish a signed-but-readable blob from an encrypted one before choosing strip versus recover. Enrichment to Reconnaissance.

**References/scripts candidates** None.

## deserialization-deferred-trigger

**Sources matched**
- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-deserialization/SKILL.md` - `phar://` zero-`unserialize` triggering via any file operation; second-order store-then-trigger.
- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-lfi/SKILL.md` - `phar://` object injection via an image polyglot.

**Similarity** Sufficient. Same procedure: plant at one locus, trigger at a distinct later locus.

**Boundary** No attribute diverges. Wrapper-implicit triggering and plant-then-trigger are owned by this variant.

**New-skill proposals** None.

**Enrichment candidates**
- `PayloadPattern` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-deserialization/SKILL.md`: `phar://` polyglot (image magic bytes plus archive) so the plant survives upload inspection. Enrichment to the wrapper-implicit shapes.
- `AttackTechnique` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-deserialization/SKILL.md`: trigger enumeration breadth. Any filesystem function on a `phar://` path triggers (existence check, size, copy, `getimagesize`). Enrichment to trigger mapping. Low value, the base already lists file operations.

**References/scripts candidates** None.

**Verdict for this group**: sufficient similarity throughout. No firm new-skill proposal. The JNDI lookup is the one flagged candidate that may escalate to a fourth variant.

---

## Group: insecure-file-uploads

## insecure-file-uploads (parent)

**Sources matched**
- `/Users/diekgbbtt/hacking-skills/skills/web/logic/insecure-file-upload/SKILL.md` - extension, MIME, magic-byte, polyglot, SVG, XXE-in-Office, ZIP-slip bypass table.
- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-file-upload/SKILL.md` - webshell RCE, the 10-row bypass table, ImageMagick and FFmpeg SSRF, headless-Chrome PDF SSRF, archive symlink escape, magic-byte table.
- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/deep-dive-labs/file-upload/SKILL.md` - PortSwigger lab playbook.
- `/Users/diekgbbtt/claude-bug-hunter/skills/security-arsenal/SKILL.md` - filename-injection payloads and the magic-byte reference.

**Similarity** Sufficient. Same class, same pipeline procedure.

**Boundary** No attribute diverges for the core upload techniques. One candidate (browser-engine renderer) is discussed below.

**New-skill proposals** None.

**Enrichment candidates**
- `AttackTechnique` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-file-upload/SKILL.md`: browser-engine renderer abuse. HTML-to-PDF, screenshot, and report services run a headless browser that fetches internal URLs, reads `file://` paths, and may execute JavaScript. Enrichment to `upload-toolchain-execution`. The base owns "converters that evaluate embedded operators". Add the browser-engine processor family as a second toolchain class. Flag: the fetch impact overlaps `ssrf` and the script impact overlaps `xss`; name those skills at the fetch and render steps.
- `AttackTechnique` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-file-upload/SKILL.md`: FFmpeg HLS and concat demuxer fetch. Enrichment to `upload-toolchain-execution` as a converter-fetch shape. Medium value.
- `DefensiveControl` <- `/Users/diekgbbtt/hacking-skills/skills/web/logic/insecure-file-upload/SKILL.md`: content-type sniffing when no guard header is present. The base owns "missing sniffing guard". Covered.
- `PayloadPattern` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-file-upload/SKILL.md`: polyglot families (magic-byte prefix plus interpreter content; image plus PHAR). The base owns polyglot construction. Covered.

**References/scripts candidates**
- `references/upload-bypass-matrix.md` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-file-upload/SKILL.md`, `/Users/diekgbbtt/hacking-skills/skills/web/logic/insecure-file-upload/SKILL.md`, and `/Users/diekgbbtt/claude-bug-hunter/skills/security-arsenal/SKILL.md`: a generalised extension, MIME, magic-byte, and filename-injection bypass matrix plus the magic-byte table. Generalised and stable. Good candidate.

## upload-server-execution

**Sources matched**
- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-file-upload/SKILL.md` - webshell, extension bypass, `.htaccess`/`web.config` handler re-enable.
- `/Users/diekgbbtt/hacking-skills/skills/web/logic/insecure-file-upload/SKILL.md` - same.

**Similarity** Sufficient.

**Boundary** No attribute diverges.

**New-skill proposals** None.

**Enrichment candidates**
- `AttackTechnique` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-file-upload/SKILL.md`: configuration-file upload to re-enable handlers (`.htaccess`, `web.config`). The base owns "configuration files that map extensions". Covered, no new content.
- `AttackTechnique` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-file-upload/SKILL.md`: extension-alternate lists (`.phtml`, `.phar`, `.php5`, `.pht`). Abstract as "alternate interpreter-mapped extensions". Low value.

**References/scripts candidates** None beyond the parent reference.

## upload-client-execution

**Sources matched**
- `/Users/diekgbbtt/hacking-skills/skills/web/logic/insecure-file-upload/SKILL.md` - SVG `onload` XSS.
- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-file-upload/SKILL.md` - SVG and HTML stored XSS, DOCX XXE.

**Similarity** Sufficient.

**Boundary** No attribute diverges.

**New-skill proposals** None.

**Enrichment candidates**
- `ObservableSignal` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-file-upload/SKILL.md`: same-origin serving as the deciding signal. The base owns "script fire in the browser under the served context". Covered. Add only the explicit "same origin versus sandboxed" adjudication if absent.

**References/scripts candidates** None.

## upload-archive-extraction

**Sources matched**
- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-file-upload/SKILL.md` - ZIP-slip via `evilarc`, tar symlink attack, symlink to a sensitive file.
- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-lfi/SKILL.md` - Zip Slip and tar-symlink escape confirmed by an outside canary.
- `/Users/diekgbbtt/hacking-skills/skills/web/logic/insecure-file-upload/SKILL.md` - ZIP-slip.

**Similarity** Sufficient.

**Boundary** No attribute diverges. Link handling and traversal entries are owned by this variant.

**New-skill proposals** None.

**Enrichment candidates**
- `AttackTechnique` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-lfi/SKILL.md`: outside-write canary confirmation. Write a unique canary outside the extraction directory and read it back. The base owns "outside-write evidence" and "follow-up read". Covered.
- `AttackTechnique` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-file-upload/SKILL.md`: compression-ratio exhaustion. The base owns "compression-ratio abuse". Covered.

**References/scripts candidates** None.

## upload-toolchain-execution

**Sources matched**
- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-file-upload/SKILL.md` - ImageMagick MVG/SVG SSRF and file read, FFmpeg HLS/concat fetch, headless-Chrome PDF SSRF and file read.
- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-lfi/SKILL.md` - ImageMagick MSL/MVG coder read-sink (ImageTragick family).

**Similarity** Sufficient for converter-embedded-operator execution. The browser-engine family is a new processor class within the same step.

**Boundary** No attribute diverges. The step "a converter evaluates embedded operators or reads local files" covers ImageMagick and FFmpeg. The browser engine is discussed under the parent enrichment as a possible second toolchain class.

**New-skill proposals** None.

**Enrichment candidates**
- `AttackTechnique` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-file-upload/SKILL.md`: browser-engine renderer abuse (as under the parent). Best home is this variant.
- `AttackTechnique` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-lfi/SKILL.md`: pseudo-protocol coders (`msl:`, `ephemeral:`, `label:@`) as a read-sink without a file parameter. Enrichment to the file-read operator block. Medium value.

**References/scripts candidates** None beyond the parent reference.

## upload-pipeline-deferred-trust

**Sources matched**
- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-file-upload/SKILL.md` - client-set headers on presigned uploads, pre-verdict fetching, finalize swaps.
- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/deep-dive-labs/file-upload/SKILL.md` - race-condition upload lab.

**Similarity** Sufficient.

**Boundary** No attribute diverges. Late control points and the pre-verdict window are owned by this variant.

**New-skill proposals** None.

**Enrichment candidates**
- `AttackTechnique` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-file-upload/SKILL.md`: metadata swap between initiation and completion. The base owns "finalize swaps". Covered.

**References/scripts candidates** None.

**Verdict for this group**: strong coverage. One enrichment family (browser-engine renderers) and one generalised reference candidate. No new-skill proposal.

---

## Group: path-traversal-lfi-rfi

## path-traversal-lfi-rfi (parent)

**Sources matched**
- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-lfi/SKILL.md` - PHP filter-chain to RCE (Synacktiv), log poisoning, wrappers, RFI, `phar://`, Zip Slip, ImageMagick read-sink, OOB and blind confirmation. Strongest match.
- `/Users/diekgbbtt/hacking-skills/skills/web/authz/path-traversal/SKILL.md` - traversal encodings, wrappers, log poisoning, RFI.
- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W6/performing-directory-traversal-testing/SKILL.md` - procedural traversal, LFI to RCE, high-value file list.
- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/deep-dive-labs/path-traversal/SKILL.md` - PortSwigger labs.
- `/Users/diekgbbtt/claude-bug-hunter/skills/security-arsenal/SKILL.md` - PATH TRAVERSAL PAYLOADS section.

**Similarity** Sufficient for traversal, encoding, wrapper, RFI, and archive techniques.

**Boundary** No attribute diverges for the shared techniques. The PHP filter-chain is discussed below as the strongest enrichment candidate and as a possible fifth variant.

**New-skill proposals**
- source: `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-lfi/SKILL.md` (Phase 4)
  - [NEW] target: `lfi-filter-chain-execution` (a proposed fifth variant of `path-traversal-lfi-rfi`)
  - Extended rationale: a bare `php://filter` read primitive is upgraded to execution by chaining `iconv` charset conversions that synthesise an arbitrary PHP payload in memory. No upload, no log access, and no writable path are required. The base `lfi-include-execution` variant owns "filter shapes that return transformed local content" and "poison-then-include with execution proof". Its step description implies reading existing content, not synthesising new content. The bent step is payload synthesis from a read-only primitive. If the operator judges "filter transformation" exhaustive over synthesis, this collapses to an enrichment. Confidence: medium. Decision-grade call: it owns a bent step (content synthesis), so it is raised as a variant proposal, with the enrichment alternative stated.

**Enrichment candidates**
- `AttackTechnique` and `PayloadPattern` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-lfi/SKILL.md`: PHP filter-chain payload synthesis (as above). If not a variant, it is the top enrichment to `lfi-include-execution`.
- `ObservableSignal` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-lfi/SKILL.md`: blind-read confirmation via an out-of-band callback with a unique sub-tag per sink, plus a triple-confirmed timing or length delta. Enrichment to `traversal-read` Detection Channels. The base owns "masked-content shift" by length and entity tag; add the OOB confirmation channel.
- `AttackTechnique` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-lfi/SKILL.md`: read the log plainly before poisoning it, to confirm readability. Enrichment to `lfi-include-execution` Reconnaissance. Low value.
- `AttackTechnique` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-lfi/SKILL.md`: non-parameter traversal surfaces (archive extract and image-coder read-sinks with no `?file=` parameter). Enrichment to Reconnaissance sink discovery. Medium value.

**References/scripts candidates**
- `references/traversal-encoding-matrix.md` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-lfi/SKILL.md`, `/Users/diekgbbtt/claude-bug-hunter/skills/security-arsenal/SKILL.md`, and `/Users/diekgbbtt/hacking-skills/skills/web/authz/path-traversal/SKILL.md`: a generalised encoding and bypass table (single, double, overlong, null byte, dot folding, separator alternation) plus the high-value file list. Generalised and stable. Good candidate.
- `references/php-filter-chain.md` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-lfi/SKILL.md`: the filter-chain generation workflow, prerequisites, length caveats, and blind-target variant. Generalised technique, bulky. Good candidate.

## traversal-read

**Sources matched**
- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-lfi/SKILL.md` - blind and OOB confirmation discipline, high-value files.
- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W6/performing-directory-traversal-testing/SKILL.md` - encoding bypasses and high-value files.
- `/Users/diekgbbtt/claude-bug-hunter/skills/security-arsenal/SKILL.md` - traversal payloads.

**Similarity** Sufficient.

**Boundary** No attribute diverges. The masked-read adjudication is owned by this variant.

**New-skill proposals** None.

**Enrichment candidates**
- `ObservableSignal` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-lfi/SKILL.md`: OOB blind-read confirmation (as under the parent). Best home is this variant's Detection Channels.
- `AttackTechnique` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-lfi/SKILL.md`: the false-positive gate for reflected paths and lone status changes. The base owns "error echo" and "masked-content shift". Add the explicit retraction rule for echoed input and single status-code changes. Medium value.

**References/scripts candidates** None beyond the parent reference.

## lfi-include-execution

**Sources matched**
- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-lfi/SKILL.md` - filter-chain, log poisoning, wrappers, session poisoning, `phar://`.
- `/Users/diekgbbtt/hacking-skills/skills/web/authz/path-traversal/SKILL.md` - wrappers and log poisoning.

**Similarity** Sufficient for handler invocation, poison-then-include, and wrapper shapes.

**Boundary** The filter-chain synthesis is the one candidate bent step. Discussed under the parent.

**New-skill proposals** None here (raised at the parent level).

**Enrichment candidates**
- `AttackTechnique` and `PayloadPattern` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-lfi/SKILL.md`: filter-chain payload synthesis. Primary enrichment to this variant.
- `AttackTechnique` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-lfi/SKILL.md`: code-execution wrapper prerequisites (`data://`, `php://input`, `expect://` each require an enablement flag). The base owns "inline-data and command-expectation shapes". Add the per-wrapper enablement check. Low value.

**References/scripts candidates**
- `references/php-filter-chain.md` (as under the parent). Best placed with this variant.

## rfi-remote-include

**Sources matched**
- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-lfi/SKILL.md` - RFI detection via a Collaborator callback, `allow_url_include` prerequisite, extension-truncation bypass.
- `/Users/diekgbbtt/hacking-skills/skills/web/authz/path-traversal/SKILL.md` - RFI webshell.
- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W6/performing-directory-traversal-testing/SKILL.md` - RFI.

**Similarity** Sufficient. Same procedure: host minimal content, confirm the outbound fetch, then confirm evaluation.

**Boundary** No attribute diverges. Scheme policy and outbound proof are owned by this variant.

**New-skill proposals** None.

**Enrichment candidates**
- `AttackTechnique` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-lfi/SKILL.md`: fetch-only confirmation when execution is blocked. A callback proves the fetch even when evaluation is disabled. Enrichment to Detection Channels. The base owns "outbound fetch receipt". Covered, low value.
- `AttackTechnique` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-lfi/SKILL.md`: appended-extension truncation (`?` or `#`) for RFI paths. Enrichment to Bypass Techniques. Low value.

**References/scripts candidates** None.

## archive-zipslip-write

**Sources matched**
- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-lfi/SKILL.md` - Zip Slip and tar-symlink escape with an outside canary.
- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-file-upload/SKILL.md` - ZIP-slip and symlink archive construction.

**Similarity** Sufficient.

**Boundary** No attribute diverges. Entry names, rooted names, and link shapes are owned by this variant.

**New-skill proposals** None.

**Enrichment candidates**
- `AttackTechnique` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-lfi/SKILL.md`: tar preserves symlinks, so a symlink entry plus a follow-on write escapes where zip entries may be sanitised. Enrichment to link shapes. Medium value.
- `AttackTechnique` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-file-upload/SKILL.md`: write to a cron or template location for persistence. The base owns "outside writes reach served directories, configuration, and templates". Covered.

**References/scripts candidates** None.

**Verdict for this group**: sufficient similarity. One medium-confidence new-skill proposal (filter-chain execution) and two strong enrichment candidates plus two generalised reference candidates.

---

## Group: graphql

## graphql (parent, non-decomposing)

**Sources matched**
- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-graphql/SKILL.md` - node/GID IDOR, mutation IDOR, cross-tenant IDOR, SSRF via argument, batching DoS, query-cost bypass (negative `first`), dual-write REST/GraphQL desync, subscription hijacking, persisted-query fallback. Strongest match.
- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-fintech-graphql/SKILL.md` - money-movement mutations and ledger or balance IDOR.
- `/Users/diekgbbtt/hacking-skills/skills/web/logic/graphql-idor-via-introspection-leak/SKILL.md` - introspection-led IDOR, alias batching, relay node probe.
- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W5/performing-graphql-introspection-attack/SKILL.md` - introspection, batching, subscriptions, and "subscriptions may have different authentication requirements".
- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W5/performing-graphql-depth-limit-attack/SKILL.md` - depth DoS.
- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W5/performing-graphql-security-assessment/SKILL.md` - WebSocket GraphQL subscription discovery.
- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/apis/graphql-introspection-abuse/SKILL.md`, `.../apis/graphql-idor/SKILL.md`, `.../api-security/graphql-injection-introspection/SKILL.md`, `.../api-security/graphql-batching-attacks/SKILL.md`, `.../bug-hunting/deep-dive-labs/graphql-labs/SKILL.md` - introspection, graph-traversal authorization bypass, batching, cost analysis, PortSwigger labs.

**Similarity** Sufficient for the query and mutation core. The subscription surface is not covered by the base.

**Boundary**
- Subscriptions: **attack-surface part family** diverges (a persistent stream versus request and response), **communication protocol** diverges (WebSocket versus HTTP), and **trust-assumption difference** diverges (per-channel and per-message authorization over a long-lived connection versus per-request resolver authorization). The base trust statement says each operation is authorized at the field or resolver that resolves it. A subscription adds a channel-scoping and persistent-connection authorization clause that no base step covers.
- Dual-write REST and GraphQL desync: the base owns chaining with `idor` and `business-logic`, but not the cross-API state-reconciliation step. Discussed as enrichment.
- Query-cost abuse: the base owns amount DoS but not the negative-cost refill. Enrichment.

**New-skill proposals**
- source: `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-graphql/SKILL.md` (subscription hijacking) and `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/W5/performing-graphql-introspection-attack/SKILL.md` (subscriptions may use different authentication)
  - [NEW] target: `graphql-subscription-hijack`
  - Extended rationale: the base `graphql` skill is declared non-decomposing and owns queries and mutations. A subscription is a third operation type carried over a persistent WebSocket connection. It owns a bent step: authorize a stream subscription per channel and per message, and keep that authorization valid for the life of the connection. The base methodology has an object-level sweep per identifier-taking query and a function-level sweep per mutation; neither covers a channel subscription. The trust clause differs: the server trusts that the connection identity stays bound to every pushed event. Both sources carry the technique and the base carries none. Confidence: medium-high. If the operator prefers to keep `graphql` non-decomposing, the alternative is a bounded enrichment (a subscription block inside `## Key Vulnerabilities` and a subscription step in `## Testing Methodology`), but the bent step argues for a leaf.

**Enrichment candidates**
- `AttackTechnique` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-graphql/SKILL.md`: cross-API dual-write state desync. Revoke access through the REST API, then re-assert it through the GraphQL mutation, and show the privilege persists. Abstract as "two APIs disagree on ground truth; the revocation is not reconciled". Enrichment to `## Chaining Attacks` and `## Advanced Techniques`. Flag: overlaps `business-logic` and `race-conditions`.
- `DefensiveControl` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-graphql/SKILL.md`: query-cost-calculator abuse. A negative list argument contributes a negative cost and refills the request budget. Abstract as "a cost function that does not floor at zero lets one request refill its own budget". Enrichment to `## Bypass Techniques`.
- `AttackTechnique` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-graphql/SKILL.md`: subscription hijack (if not a leaf). Enrichment alternative to the new-skill proposal.
- `AttackTechnique` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-fintech-graphql/SKILL.md`: money-movement mutation sweep. Enumerate transfer, redemption, and withdrawal mutations, and test foreign identifiers per mutation. Enrichment to the function-level sweep in `## Testing Methodology`. Medium value.
- `AttackTechnique` <- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/bug-hunting/api-security/graphql-injection-introspection/SKILL.md`: backward graph traversal to a guarded field through a public parent. The base owns "nested selections that reach a guarded field through an allowed parent". Covered.
- `ObservableSignal` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-graphql/SKILL.md`: alias-batching race adjudication (aliases win only under concurrent resolver execution). Enrichment to the batching technique. Medium value, and it overlaps `race-conditions`.

**References/scripts candidates**
- `references/graphql-payloads.md` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-graphql/SKILL.md` and `/Users/diekgbbtt/claude-bug-hunter/skills/security-arsenal/SKILL.md`: generalised introspection query, field-suggestion probe, alias-batch template, depth-bomb template, and batch-array template. Generalised and stable. Good candidate.

**Verdict for this group**: sufficient for the core; one medium-high-confidence new-skill proposal (subscriptions) plus three enrichment candidates.

---

## Group: llm-prompt-injection

## llm-prompt-injection (parent)

**Sources matched**
- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-llm-ai/SKILL.md` - direct and indirect injection, ASCII and Unicode Tags smuggling, markdown-image zero-click exfil, tool-use exfil, IDOR-via-AI, ASI01-10 agentic map, code-completion sabotage, backend fingerprinting, false-positive gate. Strongest match.
- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-rag-vector/SKILL.md` - vector-store IDOR, persistent corpus poisoning, source-text leakage, retrieval hijack, vector-DB reachability probes.
- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/ai-red-teaming/llm-attacks/llm-direct-prompt-injection/SKILL.md` - direct injection, system-prompt extraction, tool abuse.
- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/ai-red-teaming/llm-attacks/llm-indirect-prompt-injection/SKILL.md` - indirect surfaces, hidden placements, exfil.
- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/ai-red-teaming/agent-security/mcp-protocol-exploitation/SKILL.md` - MCP tool-server reconnaissance, tool injection, parameter injection, server-level auth and validation testing, cross-tool chains.
- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/ai-red-teaming/agent-security/ai-agent-tool-abuse-and-privilege-escalation/SKILL.md` - tool abuse, multi-step chains, implicit trust in tool responses, capability boundary testing.
- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/ai-red-teaming/ml-security/rag-poisoning-and-data-exfiltration/SKILL.md` - RAG poisoning, cross-tenant leakage, source-metadata leakage.
- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/ai-red-teaming/model-exploitation/prompt-leaking-system-prompts/SKILL.md` - system-prompt and tool-schema extraction, encoding evasion.
- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/ai-red-teaming/model-exploitation/ai-jailbreak-obfuscation-ciphers/SKILL.md` - cipher and obfuscation filter bypass.
- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/...` ai-security entries (`red-teaming-llms-with-garak`, `orchestrating-llm-attacks-with-pyrit`, `testing-prompt-injection-in-rag-pipelines`, `testing-for-system-prompt-leakage`, `detecting-indirect-prompt-injection`) - mostly defensive and procedural.

**Similarity** Sufficient for direct injection, indirect injection, leakage, and output handling. Insufficient for the MCP tool server as a directly reachable surface. Insufficient for the vector-store layer as a directly reachable data store.

**Boundary**
- MCP tool server: **attack-surface part family** diverges (a protocol tool-call endpoint versus a chat feature), **trust-assumption difference** diverges (the tool server must enforce caller identity and parameter validation independently of the model, whereas the base trusts the model to separate instructions from data), and the model can be bypassed entirely.
- Vector store: **trust-assumption difference** diverges (per-tenant scoping must hold at the retrieval layer, not only at the chat API). The retrieval-hijack technique is an amplification of indirect injection, not a new class.

**New-skill proposals**
- source: `/Users/diekgbbtt/awsome-offensive-security-skill/skills/ai-red-teaming/agent-security/mcp-protocol-exploitation/SKILL.md` and `/Users/diekgbbtt/awsome-offensive-security-skill/skills/ai-red-teaming/agent-security/ai-agent-tool-abuse-and-privilege-escalation/SKILL.md`
  - [NEW] target: `mcp-tool-server-abuse`
  - Extended rationale: the base `tool-abuse` variant treats the model as the actuator and requires a logged model-steered call. The MCP tool server is a directly reachable API. Its surface is tool enumeration, unauthenticated tool calls, path traversal in a file tool, command injection in an execution tool, URL fetch through a fetch tool, and tool-permission gaps where the server trusts the model to respect permissions. The model is bypassed. The trust assumption differs: the tool server must enforce identity and parameter validation itself. The reconnaissance differs: enumerate `tools/list`, read input schemas, map destructive tools. Both sources carry a full, stable procedure. Confidence: medium-high. Flag: this is an AI-agent surface, so confirm it is inside the operator's web-testing scope before authoring.

- source: `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-rag-vector/SKILL.md` and `/Users/diekgbbtt/awsome-offensive-security-skill/skills/ai-red-teaming/ml-security/rag-poisoning-and-data-exfiltration/SKILL.md`
  - [NEW] target: `rag-vector-store-abuse`
  - Extended rationale: the base class covers injection through ingested content. It does not cover the vector store as a directly reachable data store: unauthenticated corpus reads, cross-tenant vector IDOR through a controlled namespace or document ID, and source-text or metadata leakage in similarity results. The trust assumption differs: tenant isolation must hold at the vector database, not only at the chat API. Confidence: medium. Flag: the direct-read half is arguably an `idor` or `information-disclosure` case, and the persistent-poisoning half is already owned by `indirect-injection-plant`. If the operator judges the direct-read half to belong to `idor`, this reduces to an enrichment of `indirect-injection-plant` (retrieval hijack) plus an out-of-slice note for `idor`.

**Enrichment candidates**
- `PayloadPattern` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-llm-ai/SKILL.md`: Unicode Tags-block smuggling (U+E0000 to U+E007F, invisible to humans, tokenized by the model) plus zero-width and bidi variants. Enrichment to `## Bypass Techniques`. The base owns "invisible characters"; add the concrete Tags-block family and the encoder or decoder shape.
- `AttackTechnique` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-llm-ai/SKILL.md` and `/Users/diekgbbtt/awsome-offensive-security-skill/skills/ai-red-teaming/llm-attacks/llm-indirect-prompt-injection/SKILL.md`: multimodal image-embedded instructions (low-contrast text, EXIF, metadata, a screenshot the model describes). Enrichment to `indirect-injection-plant` placements. The base parent lists "image descriptions" as a surface but not instruction text inside an image.
- `AttackTechnique` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-llm-ai/SKILL.md`: DNS-only exfil (base32 label) when HTTP egress is filtered, plus tool-use fetch to cloud metadata. Enrichment to `tool-abuse` and `output-handling`.
- `AttackTechnique` <- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/ai-red-teaming/agent-security/ai-agent-tool-abuse-and-privilege-escalation/SKILL.md`: implicit trust in tool responses. A poisoned file, database field, or API response the agent reads carries instructions the agent follows. Enrichment to `indirect-injection-plant` as a second-order ingestion source.
- `AttackTechnique` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-rag-vector/SKILL.md`: retrieval hijack by embedding-proximity dominance. Density of query vocabulary in one chunk out-competes genuine content in top-k retrieval. Enrichment to `indirect-injection-plant` corpus seeding.
- `AttackTechnique` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-llm-ai/SKILL.md`: AI code-completion sabotage. Steer a code-generation feature into emitting insecure code. New surface. Enrichment to `tool-abuse` or a possible new variant. Flag: low confidence, thin evidence, and it may be its own class.
- `AttackTechnique` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-llm-ai/SKILL.md`: ASI01 to ASI10 agentic mapping. Enrichment to `tool-abuse` and `## Chaining Attacks` as an abstract capability map. Flag: naming the ASI codes would leak a concrete framework; abstract to capability classes only.
- `PayloadPattern` <- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/ai-red-teaming/model-exploitation/ai-jailbreak-obfuscation-ciphers/SKILL.md`: cipher and encoding bypass (Base64, ROT13, leetspeak) of keyword classifiers. Enrichment to `## Bypass Techniques`. The base owns "alternate alphabets, homoglyphs, invisible characters, translation". Add cipher-encoding as a sibling.
- `AttackTechnique` <- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/ai-red-teaming/model-exploitation/prompt-leaking-system-prompts/SKILL.md`: output-encoding evasion for extraction (ask for the hidden text Base64-encoded to bypass output filters). Enrichment to `context-leakage` Bypass Techniques. Low-medium value.
- `AttackTechnique` <- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/ai-red-teaming/agent-security/mcp-protocol-exploitation/SKILL.md`: tool-permission enforcement gap and cross-tool chain. Enrichment to `tool-abuse` (if the MCP leaf is not created).

**References/scripts candidates**
- `scripts/ascii-smuggle.py` (or `references/ascii-smuggling.md`) <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-llm-ai/SKILL.md`: the Tags-block encoder and decoder. Generalised, small, and reusable. Good candidate.
- `references/llm-injection-payloads.md` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-llm-ai/SKILL.md` and `/Users/diekgbbtt/awsome-offensive-security-skill/skills/ai-red-teaming/llm-attacks/llm-direct-prompt-injection/SKILL.md`: generalised extraction and override phrases, delimiter-breakout shapes, and exfil templates. Generalised. Good candidate.
- `references/rag-vector-probes.md` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-rag-vector/SKILL.md`: vector-DB reachability probes and namespace or document-ID IDOR templates. Good candidate if the `rag-vector-store-abuse` leaf is created.

## direct-injection-override

**Sources matched**
- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/ai-red-teaming/llm-attacks/llm-direct-prompt-injection/SKILL.md` - override, delimiter breakout, multi-turn escalation, roleplay, token smuggling.
- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-llm-ai/SKILL.md` - direct injection framings.
- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/ai-red-teaming/model-exploitation/ai-jailbreak-obfuscation-ciphers/SKILL.md` - encoding bypass.

**Similarity** Sufficient. Same procedure: break the delimiter framing and smuggle instructions past the filter.

**Boundary** No attribute diverges. Delivery is direct chat.

**New-skill proposals** None.

**Enrichment candidates**
- `PayloadPattern` <- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/ai-red-teaming/llm-attacks/llm-direct-prompt-injection/SKILL.md`: JSON-role and XML-tag framing (`{"role":"system",...}`) to match the target templating. Enrichment to the override shapes.
- `PayloadPattern` <- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/ai-red-teaming/model-exploitation/ai-jailbreak-obfuscation-ciphers/SKILL.md`: cipher and encoding bypass. Enrichment to `## Bypass Techniques`.
- `AttackTechnique` <- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/ai-red-teaming/llm-attacks/llm-direct-prompt-injection/SKILL.md`: context-window flush (long filler then extraction). Enrichment to multi-turn laundering. Low value.

**References/scripts candidates** None.

## indirect-injection-plant

**Sources matched**
- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-llm-ai/SKILL.md` - hidden placements, corpus seeding, victim trigger, cross-tenant memory poisoning.
- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-rag-vector/SKILL.md` - persistent poisoning reaching a second clean session, retrieval hijack.
- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/ai-red-teaming/llm-attacks/llm-indirect-prompt-injection/SKILL.md` - web, email, document, database, and API injection surfaces.
- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/ai-red-teaming/prompt-injection/indirect-prompt-injection/SKILL.md` and `/Users/diekgbbtt/awsome-offensive-security-skill/skills/ai-red-teaming/model-exploitation/llm-prompt-injection-indirect/SKILL.md` - indirect variants.
- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/ai-red-teaming/ml-security/rag-poisoning-and-data-exfiltration/SKILL.md` - RAG document injection.
- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/ai-red-teaming/agent-security/ai-agent-tool-abuse-and-privilege-escalation/SKILL.md` - implicit trust in tool responses.

**Similarity** Sufficient. Same procedure: author retrievable content, seed the corpus, trigger through a victim action.

**Boundary** No attribute diverges. Hidden placement, corpus seeding, and victim-triggered detonation are owned by this variant. The vector-store direct read is a separate class (discussed under the parent).

**New-skill proposals** None.

**Enrichment candidates**
- `AttackTechnique` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-llm-ai/SKILL.md`: multimodal image placements (as under the parent). Best home is this variant's Hidden Placement.
- `AttackTechnique` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-rag-vector/SKILL.md`: retrieval hijack and embedding-surface maximisation (as under the parent). Best home is Corpus Seeding.
- `AttackTechnique` <- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/ai-red-teaming/agent-security/ai-agent-tool-abuse-and-privilege-escalation/SKILL.md`: implicit trust in tool responses (as under the parent). Best home is Hidden Placement as a second-order source.
- `PayloadPattern` <- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/ai-red-teaming/llm-attacks/llm-indirect-prompt-injection/SKILL.md`: HTML-comment, hidden-div, and markdown-comment placements. The base owns "comments, annotations, metadata fields". Mostly covered. Low value.
- `AttackTechnique` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-llm-ai/SKILL.md`: second-session verification rule (a clean session must inherit the poison). Enrichment to the confirmation step. Medium value.

**References/scripts candidates** None beyond the parent reference.

## context-leakage

**Sources matched**
- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-llm-ai/SKILL.md` - system-prompt and tool-schema extraction, cross-tenant reads, run-twice and anchor rules.
- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/ai-red-teaming/model-exploitation/prompt-leaking-system-prompts/SKILL.md` - extraction payloads, tool-schema extraction, chaining to SSRF or RCE.
- `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/...` `testing-for-system-prompt-leakage` - procedural.

**Similarity** Sufficient. Same procedure: repeat-shaped probes, schema requests, cross-boundary reads, matched against ground truth.

**Boundary** No attribute diverges. Verbatim extraction, schema disclosure, and cross-boundary reads are owned by this variant.

**New-skill proposals** None.

**Enrichment candidates**
- `AttackTechnique` <- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/ai-red-teaming/model-exploitation/prompt-leaking-system-prompts/SKILL.md`: output-encoding evasion (request the hidden text Base64 or ROT13 encoded to bypass output filters). Enrichment to `## Bypass Techniques`.
- `AttackTechnique` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-llm-ai/SKILL.md`: anchor to a non-guessable string to defeat confabulation. The base owns "match against ground truth". Add the explicit anchor rule. Low value.
- `AttackTechnique` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-llm-ai/SKILL.md`: tool-schema extraction as the entry to SSRF or command injection. Enrichment to `## Chaining Attacks`. Medium value.

**References/scripts candidates** None beyond the parent reference.

## tool-abuse

**Sources matched**
- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-llm-ai/SKILL.md` - tool-use exfil, tool steering, ASI02 and ASI03.
- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/ai-red-teaming/agent-security/mcp-protocol-exploitation/SKILL.md` - tool injection, parameter injection, cross-tool chains, permission gaps.
- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/ai-red-teaming/agent-security/ai-agent-tool-abuse-and-privilege-escalation/SKILL.md` - tool abuse, multi-step chains, capability boundary testing.
- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/ai-red-teaming/llm-attacks/llm-direct-prompt-injection/SKILL.md` - forced tool invocation.

**Similarity** Sufficient for model-steered tool abuse. Insufficient for the MCP tool server as a direct surface.

**Boundary** No attribute diverges for model-steered abuse. The MCP direct-call case diverges (see the parent new-skill proposal).

**New-skill proposals** None here (raised at the parent level).

**Enrichment candidates**
- `AttackTechnique` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-llm-ai/SKILL.md`: tool-use fetch to cloud metadata (an SSRF primitive with an elevated network position). Enrichment to `## Chaining Attacks`.
- `AttackTechnique` <- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/ai-red-teaming/agent-security/mcp-protocol-exploitation/SKILL.md`: tool-permission enforcement gap and capability leak. Enrichment to the tool inventory step. Medium value.
- `AttackTechnique` <- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/ai-red-teaming/agent-security/ai-agent-tool-abuse-and-privilege-escalation/SKILL.md`: progressive escalation and capability boundary testing. Enrichment to the steering step. Low-medium value.
- `AttackTechnique` <- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/ai-red-teaming/agent-security/ai-agent-tool-abuse-and-privilege-escalation/SKILL.md`: persistence through the agent (scheduled task, key placement). Enrichment to `## Chaining Attacks`. Low value.

**References/scripts candidates** None beyond the parent reference.

## output-handling

**Sources matched**
- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-llm-ai/SKILL.md` - markdown-image zero-click exfil, tool-use exfil, DNS-only exfil.
- `/Users/diekgbbtt/awsome-offensive-security-skill/skills/ai-red-teaming/llm-attacks/llm-indirect-prompt-injection/SKILL.md` - image, link, and pixel exfil.

**Similarity** Sufficient. Same procedure: coax a sink-bearing shape and prove rendering or execution.

**Boundary** No attribute diverges. Markup, query, and link sinks are owned by this variant.

**New-skill proposals** None.

**Enrichment candidates**
- `AttackTechnique` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-llm-ai/SKILL.md`: DNS-only exfil (base32 label) when HTTP egress is filtered. Enrichment to Detection Channels. Medium value.
- `AttackTechnique` <- `/Users/diekgbbtt/claude-bug-hunter/skills/hunt-llm-ai/SKILL.md`: per-sink sub-tagged callbacks so the firing feature is attributable. Enrichment to the proof discipline. Low value.

**References/scripts candidates** None.

**Verdict for this group**: sufficient for the core. Two new-skill proposals (MCP tool server, medium-high; RAG vector store, medium) plus a rich set of enrichment candidates and three reference or script candidates.

---

## Slice summary

### Counts

- Base skills examined: 26 across 6 groups.
- Source skills read or indexed in depth for this slice: 34 (12 hacking-skills, 8 claude-bug-hunter, 6 anthropic accepted, 8 awsome plus the four repos' indexes).
- Similarity sufficient: 22 base skills.
- Similarity insufficient (clean no-match or new-class): 4 base skills (`crypto-timing-oracle`, and the three crypto or session areas that drove proposals).
- New-skill proposals: 6.
  - `session-management` (medium; new class, baseline absent).
  - `crypto-oracle-decryption` (low; possibly a fourth crypto variant).
  - `lfi-filter-chain-execution` (medium; possibly an enrichment of `lfi-include-execution`).
  - `graphql-subscription-hijack` (medium-high).
  - `mcp-tool-server-abuse` (medium-high).
  - `rag-vector-store-abuse` (medium; may reduce to `idor` plus an enrichment).
- Enrichment candidates: 74, of which the strongest are listed below.
- References or scripts candidates: 10.

### Strongest findings

1. `graphql-subscription-hijack` (new leaf). The base `graphql` skill owns queries and mutations and is declared non-decomposing, yet subscriptions carry a bent step: per-channel and per-message authorization over a persistent WebSocket. Three sources carry the technique; the base carries none. Highest-confidence structural gap in this slice.
2. `mcp-tool-server-abuse` (new leaf). The base `tool-abuse` variant requires a logged model-steered call. The MCP tool server is a directly reachable API with its own auth and validation duties, and the model is bypassed. Two awsome sources carry a full procedure.
3. PHP filter-chain to RCE (enrichment or `lfi-filter-chain-execution`). It converts a read-only `php://filter` primitive into execution by synthesising a payload in memory, with no upload and no writable path. This is the single most impactful path-traversal technique in the sources and is not explicitly owned by `lfi-include-execution`.
4. JWT key-source injection (`kid`, `jku`, `x5u`, embedded `jwk`). A third signing-key technique beside offline search and algorithm removal. Strong enrichment to `crypto-signing-key-forgery`, with the note that `authentication-jwt` is the natural JWT-specific owner.
5. Cross-API dual-write desync (enrichment to `graphql`) and the query-cost-calculator abuse. Both are concrete bypass techniques the base does not name.

### Other notable findings

- JNDI and Log4Shell (interpolation-triggered remote lookup) is flagged as an enrichment that may escalate to a fourth `insecure-deserialization` variant.
- Browser-engine renderer abuse (HTML-to-PDF and screenshot services) is the one new processor family for `insecure-file-uploads`.
- `crypto-timing-oracle` is a clean no-match: no source runs a baseline-calibrated prefix-extraction procedure.
- `mobile-weak-crypto` and `hunt-tls-network` are non-matches for `crypto-weakness` on both reconnaissance and trust-assumption grounds; both are outside the fixed web-testing scope.
- `session-management` is proposed with a caveat: it is a new class, not a variant, and the base suite lacks the baseline it extends.

### Cross-slice and out-of-slice notes

- The vector-store direct read (unauthenticated corpus read, cross-tenant vector IDOR) may belong to `idor` or `information-disclosure` rather than `llm-prompt-injection`. Recorded for the slice that owns `idor`.
- JWT header injection belongs naturally to `authentication-jwt`. The crypto-weakness enrichment should be authored in coordination with that group.
- The `hunt-session` rotation-reuse signal routes to `oauth` or `authentication-jwt`.
- Several enrichment candidates overlap `business-logic`, `race-conditions`, `ssrf`, and `xss`; each names the owning skill at its step instead of restating the mechanics.
