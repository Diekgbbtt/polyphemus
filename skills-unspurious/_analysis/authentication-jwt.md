# authentication-jwt - variant decomposition analysis

## 1. Class and scope
This class covers JWT (JWS/JWE) and OIDC/OAuth2 token validation failures that enable forgery, key-control, cross-context acceptance, and lifecycle abuse leading to account takeover.
It is derived from `skills-unspurious/authentication-jwt/SKILL.md` (139 lines), with `skills/authentication-jwt/SKILL.md` consulted only for validation checklist and tooling detail, never as authority.
No outlier state occurred in STATE 1 because the class carries a six-step testing methodology (lines 108-115) and a populated vulnerability inventory (lines 36-99).

## 2. Ontology entity ledger
| Entity type | Value(s) | Source line(s) | Role |
|---|---|---|---|
| PreconditionEnvironment | JWT/OIDC authentication in use, with JWS or JWE formats and access, ID, refresh, device, PKCE, and Backchannel flows present | 12-14, 31 | Non-discriminator (class applicability condition, shared by all candidates) |
| PreconditionEnvironment | Multiple issuers with multiple consumers (first-party services, microservices, gateways, JWKS distribution) | 14, 86-90, 99 | Context for claims-confusion testing, not itself a discriminator |
| PreconditionEnvironment | JWKS caching TTL and key-rollover windows, plus mixed dev/stage/prod key environments | 52-55 | Discriminator candidate (drives key-lifecycle steps) |
| PreconditionEnvironment | Attacker holds tokens for multiple roles and token types | 111, 145 | Non-discriminator (test input, parametrises every variant) |
| TechnologyStack | JWT/JWS/JWE, OIDC/OAuth2, JWKS distribution, API gateways, mobile clients, mTLS/DPoP | 12-14, 18, 82, 93-95 | Non-discriminator (stability rule: procedure survives stack change) |
| DefensiveControl | Algorithm pinning with none-alg rejection | 40-42, 120, 146 | Falsification oracle, not a discriminator (its absence is what each forgery variant proves) |
| DefensiveControl | Issuer, audience, azp, typ, expiry, and scope enforcement | 59-62, 119, 122, 145 | Falsification oracle for claims-confusion, not a discriminator |
| DefensiveControl | Key pinning with JWKS whitelist and TLS validation | 48, 120 | Falsification oracle for key-resolution, not a discriminator |
| DefensiveControl | Refresh rotation with reuse detection and revocation, PKCE S256, state/nonce, DPoP or cnf binding | 71-76, 68-69, 82, 121, 150 | Falsification oracle for flow-lifecycle, not a discriminator |
| VulnerabilityClass | Broken JWT signature verification (algorithm confusion, none acceptance, ECDSA misuse, weak HMAC secrets) | 40-42 | Discriminator candidate (signature-trust binding) |
| VulnerabilityClass | Attacker-controlled key resolution (kid, jku, x5u, jwk, cache and fallback flaws) | 46-55 | Discriminator candidate (key-resolution binding) |
| VulnerabilityClass | Improper claims and context validation (iss, aud, azp, scope, exp, typ, token-type swap) | 59-62, 66, 86-90, 93-95 | Discriminator candidate (claims-context binding) |
| VulnerabilityClass | OIDC flow and session lifecycle weakness (mix-up, PKCE downgrade, state/nonce, device flow, refresh reuse, fixation) | 66-76 | Discriminator candidate (flow-lifecycle binding) |
| AttackGoal | Token forgery, cross-service acceptance, durable account takeover, privilege escalation, cross-tenant access | 8, 137-139 | Non-discriminator (impact, never bends a step) |
| AttackerCapability | Control of an attacker-hosted JWKS or X509 endpoint reachable by the server | 48 | Parametrises key-resolution testing, not a discriminator (same steps with or without it, fetch simply fails closed) |
| AttackerCapability | Ability to replay a bearer token from a second device or channel | 82, 150 | Parametrises lifecycle testing, not a discriminator |
| AttackTechnique | Algorithm confusion RS256 to HS256, none-alg stripping, ECDSA misuse, HMAC secret recovery | 40-42, 146 | Discriminator candidate (signature-forgery procedure) |
| AttackTechnique | kid path traversal and injection, jku/x5u remote key hosting, jwk header embedding, rotation-race and missing-kid fallback abuse | 46-55, 148 | Discriminator candidate (key-resolution procedure) |
| AttackTechnique | Claim edits across iss, aud, azp, sub, scope, exp, and typ, plus access-versus-ID swap and nested-JWT order abuse | 59-62, 66, 86-90, 93-95, 147 | Discriminator candidate (claims-confusion procedure) |
| AttackTechnique | OIDC mix-up across clients, PKCE downgrade, state/nonce omission, device-flow acceptance, refresh reuse, fixation | 66-76, 149 | Discriminator candidate (flow-lifecycle procedure) |
| PayloadPattern | Mutated `alg`, `kid`, `jku`, `x5u`, `jwk`, `b64`, and `crit` header structures | 32, 40-49, 93 | Aspect inside signature-forgery or key-resolution (payload wording, same procedure) |
| PayloadPattern | Mutated claim sets over iss, aud, azp, sub, scope, exp, nbf, iat, and typ | 33, 59-62 | Aspect inside claims-confusion (claim choice, same procedure) |
| PayloadPattern | Forged token minted under an attacker-controlled or recovered key | 48, 104 | Artifact-producing pattern inside key-resolution or signature-forgery |
| Artifact | Captured access, ID, and refresh tokens for multiple roles | 111 | Non-discriminator (runtime input to every variant) |
| Artifact | IdP metadata and JWKS documents, attacker-hosted JWKS or X509 chain, minted forged token | 24-28, 48 | Non-discriminator (consumed at runtime, minted by procedure) |
| ObservableSignal | Forged or cross-context token acceptance, ID-token acceptance at an access-token API, refresh reuse without detection, header-abuse acceptance | 117-122 | Non-discriminator (observation channel shared by all variants) |
| ObservableSignal | Owner versus non-owner response difference under identical requests differing only in token context | 128 | Non-discriminator (comparison method shared by all variants) |

## 3. RDF notion map
Vuln-specific attack surface and reconnaissance: web, mobile, and API authentication over JWT and OIDC with gateways, JWKS distribution, and per-flow endpoints (lines 10-34) is invariant across variants.
Adversarial capabilities: multi-role token possession plus an attacker-hosted key endpoint plus replay position (lines 48, 82, 111) vary only as runtime parametrisation, never as procedure.
Common trust assumptions: server-side binding of each token to its issuer, audience, key, algorithm, and client context (lines 8, 139) is the invariant that every variant falsifies at a different binding.
Testing methodology: the six parent steps P1 to P6 (lines 110-115) are invariant as labelled, but P4 and P5 each lump genuinely different procedures and therefore fail the step test.
Proxy techniques: none are described in this class, so nothing is pinned here.
Defence bypass techniques: algorithm, claim, key-pinning, rotation, PKCE, and binding checks (lines 40-82, 144-150) are the per-variant oracles, and each variant bypasses a different one.
Techniques anti-patterns: none are named in this class, so nothing is pinned here.
Scripted tests: none exist in the spurious skill (no `references/` directory), which is recorded as a gap rather than a discriminator.
False positives: strict issuer, audience, key-pinning, rotation, revocation, and token-type enforcement (lines 117-122) are invariant rejection signals shared by all variants.
Chaining: XSS theft, SSRF-assisted key theft, redirect poisoning, and IDOR-minted tokens (lines 101-106) are invariant entry and exit edges owned by other skills, never variant axes here.

## 4. Runtime parametrisation
The concrete Service under test, the System mechanism it lies on (gateway, mobile client, worker, WebSocket, gRPC), and the Endpoint, Parameter, Header, BaseURL, and DataItem loci where tokens are presented are supplied at runtime from the attack-surface graph.
The knowledge base supplies library identity, JWKS URLs, rotation policy, token lifetimes, and HMAC-secret candidates as runtime facts.
The HTTP history supplies captured tokens, claim sets, JWKS documents, and prior acceptance or rejection observations.
Token kind labels (access versus ID versus refresh), role identities, tenant names, issuer strings, and audience strings parametrise a variant and never define one.
Technology stack differences (web versus mobile versus gateway verification, lines 134 and 152) change where the agent looks, never which variant procedure it runs.

## 5. Agent-with-skill walkthrough
The hunting circumstance is an application that authenticates API calls with JWTs issued by an OIDC provider, fronted by a gateway, consumed by several internal services, and accompanied by refresh and PKCE flows.
The agent inventories issuers and consumers first, and the step is complete when every verification party and its trust source is named.
The agent captures access, ID, and refresh tokens for at least two roles next, and the step is complete when header, claims, and signature structure are recorded per token type.
The agent maps verification endpoints (well-known metadata and JWKS) next, and the step is complete when key sources, rotation behaviour, and pinning posture are known.
The agent builds the Token Type by Audience by Service matrix and attempts cross-use next, and the step is complete when every cross-context acceptance or rejection is recorded.
The agent mutates headers, claims, and signatures next, and the step is complete when each mutation class has an acceptance verdict.
The agent verifies what is actually enforced versus assumed last, and the step is complete when each missing binding is tied to a reproducible acceptance proof.
STATE 2 finding preview: the matrix step cannot describe multi-step flow driving, and the mutate step cannot describe offline secret recovery, remote key hosting with fetch observation, rotation-race timing, or lifecycle oracle sequences.

## 6. Feature-verdict table
| Candidate feature | Accurate? | Exhaustive? | Verdict | Evidence |
|---|---|---|---|---|
| Signature algorithm trust (confusion, none, ECDSA, weak HMAC) | No | No | Discriminator | P5 assumes a presented mutated signature, while none-alg removes the signature layer entirely and HMAC recovery adds an offline cracking step no parent step names |
| Key resolution control (kid, jku, x5u, jwk, cache, fallback) | No | No | Discriminator | P5 describes single-request header mutation, while this feature requires hosting a remote key endpoint, observing server-side fetch, and timing rotation windows and fallback behaviour |
| Claims and context acceptance (iss, aud, azp, scope, exp, typ, token swap) | Partly (matrix cross-use) | No | Discriminator | P4 covers cross-service cross-use only, while single-service claim edits (expired tokens, inflated scope) and nested-JWT order abuse fall outside any matrix cell |
| OIDC flow and token lifecycle (mix-up, PKCE, state/nonce, device flow, refresh, fixation) | No | No | Discriminator | No parent step drives a multi-step authorize-callback-token flow or sequences rotation, reuse-detection, and revocation oracles |
| Technology stack (library, gateway, mobile versus web) | Yes | Yes | Non-discriminator | Same procedure replays on every stack per lines 134 and 152, so the stack parametrises rather than bends any step |
| Token kind (access versus ID versus refresh as labels) | Yes | Yes | Aspect | Token kind selects which matrix cell or lifecycle oracle applies, while the procedure kind stays unchanged |
| kid payload family (traversal versus SQL versus command versus file path) | Yes | Yes | Aspect | Payload wording changes inside the identical key-resolution procedure, so this is a payload aspect of the key-resolution variant |
| Clock-skew and lifetime magnitudes | Yes | Yes | Aspect | Tolerance size is a continuous value inside the identical expiry-enforcement probe, so it cannot partition variants (branch 3b) |
| HMAC secret value and key material | Yes | Yes | Non-discriminator | Secret identity is a runtime KB fact per the version-and-secret exclusion, never a procedure difference |
| Attack goal and impact (takeover, escalation, cross-tenant) | Yes (no step changes kind) | N/A | Non-discriminator | Impact never changes which action the agent performs, so Question A fails immediately |
| Observation channel (status code, response diff, error text) | Yes | Yes | Non-discriminator | All variants read the same acceptance signals, so no step bends on channel |
| Transport and storage theft (XSS exfiltration, CORS, cookie flags, mobile plaintext storage) | N/A | N/A | Out of scope, owned elsewhere | Theft and exfiltration steps belong to XSS, CORS, and transport skills and are named as cross-references, never as variants here |

## 7. Step-coverage falsification
For the signature-algorithm value, parent step P5 (mutate components, line 114) is neither accurate nor exhaustive because dropping the signature to `alg:none` performs signature removal rather than signature mutation, and recovering a weak HMAC secret requires an offline cracking step that P5 never names.
For the ECDSA misuse value, P5 is not exhaustive because accepting non-canonical signatures is a verifier-strictness property, not a header value the agent mutates, so no mutation enumeration covers it.
For the remote key-hosting value (jku/x5u), P5 is neither accurate nor exhaustive because the procedure kind is infrastructure manipulation (host a key endpoint, induce and observe a server-side fetch, mint under the fetched key) rather than request mutation, and P5 names no fetch-observation or mint-under-fetched-key step.
For the cache, rotation-race, and missing-kid-fallback values, P5 and P6 are not exhaustive because timing-dependent replay of retired keys and kid-absent fallback probing are temporal and behavioural oracles, while P5 describes timeless single-request mutation and P6 names no oracle sequence.
For the single-service claim-edit value (expired token, inflated scope against one service), P4 (matrix cross-use, line 113) is not exhaustive because a one-service acceptance verdict occupies no Token Type by Audience by Service cross-use cell.
For the nested-JWT order value, P5 is not exhaustive because verification-order confusion between outer and inner tokens is a compositional property, not a component value the agent mutates.
For the OIDC mix-up value, no parent step is accurate because redeeming Client A tokens at Client B requires driving two clients through authorize, callback, and token steps, while every parent step assumes already-captured tokens.
For the PKCE, state, and nonce-downgrade values, no parent step is exhaustive because flow-variant driving (plain versus S256 versus absent verifier, predictable versus missing state) is a protocol-execution sequence that token mutation cannot express.
For the refresh rotation, reuse-detection, and revocation values, no parent step is accurate because the procedure kind is a lifecycle oracle sequence (use, reuse, logout, replay), not a token mutation.
Branch 3a check: no two signature features always co-vary, since algorithm trust, key resolution, claim context, and flow lifecycle each fail independently in the wild.
Branch 3b check: clock-skew tolerance and HMAC-secret strength are continuous or overlapping values, so they are recorded as aspects inside claims-confusion and signature-forgery respectively, never as variant axes.

## 8. Hypotheses
H1 (single-feature): if the discrimination feature is which token-validity binding the test breaks (signature-algorithm versus key-resolution versus claims-context versus flow-lifecycle), then the class yields exactly four variants, and H1 is falsified if any variant lacks its own non-coverable step or if two variants share one.
H2 (combined-feature): if binding stage is crossed with protocol role (single-acceptance judgment versus multi-step flow execution), then refresh and OIDC behaviour splits off a fifth combined variant with its own flow-driving step beyond H1, and H2 is falsified if that fifth set adds no non-coverable step over H1.
H3 (minimal two-way): if the only real split is cryptographic validity (signature plus key) versus contextual validity (claims plus flow), then two variants suffice, and H3 is falsified if signature-forgery and key-resolution procedures, or claims-confusion and flow-lifecycle procedures, each demand a distinct non-coverable step.
Branch 4a note: H3 is discarded if the STATE 5 derivation shows key-resolution needs remote-hosting and timing steps that signature mutation never performs, because then the two-way merge leaves non-coverable steps homeless.

## 9. Variant sets per hypothesis
| Hypothesis | Variant | First non-coverable step (methodology order) | Secondary divergences carried inside |
|---|---|---|---|
| H1 | jwt-signature-forgery | Forge or strip signature validity (confuse RS256 to HS256 with the RSA public key, drop to none, abuse ECDSA verification, recover a weak HMAC secret offline) | Choice of confusion versus none versus ECDSA versus cracking is a technique aspect, and secret strength is a continuous aspect |
| H1 | jwt-key-resolution | Seize key selection (inject kid to read or select keys, host jku/x5u for server fetch with SSRF observation, embed jwk, race rotation windows, trigger missing-kid fallback) | kid payload family (traversal, SQL, command, file) is a payload aspect, and SSRF reach is a secondary effect, not a new variant |
| H1 | jwt-claims-confusion | Prove cross-context acceptance (replay across issuers, audiences, services, and token types; edit scope and expiry against one service; abuse nested-JWT order) | Specific claim choice and matrix cell are aspects, and microservice versus gateway acceptance path is runtime parametrisation |
| H1 | jwt-flow-lifecycle | Drive and corrupt the protocol lifecycle (OIDC mix-up across clients, PKCE downgrade, state/nonce omission, device-flow misuse, refresh reuse without detection, revocation bypass, fixation) | Client identity and code-verifier shape are aspects, and DPoP or mTLS replay position parametrises the lifecycle oracles |
| H2 | Same four as H1 plus jwt-refresh-oidc-combined | Same first steps as H1, with the fifth variant predicted to own refresh-scoped flow driving | STATE 5 branch 5a test: the fifth candidate reuses the flow-lifecycle driving step and adds no step of its own, so it collapses back into jwt-flow-lifecycle |
| H3 | jwt-crypto-validity (signature plus key merged) | First non-coverable step is ambiguous between forging signature validity and seizing key selection | STATE 5 derivation fails: remote key hosting with fetch observation and rotation timing cannot be performed by signature mutation, so coverage fails |
| H3 | jwt-context-validity (claims plus flow merged) | First non-coverable step is ambiguous between proving cross-context acceptance and driving the protocol lifecycle | STATE 5 derivation fails: multi-step flow driving cannot be performed by single-token replay, so coverage fails |

## 10. Well-formedness evaluation
Coverage is critical: H1 places every genuine non-coverable step (signature stripping and cracking, remote key hosting with timing, single-service claim acceptance, flow driving with lifecycle oracles) in exactly one variant.
Disjointness is critical: H1 variants never share a technique, since a forged signature, an attacker-resolved key, a mis-scoped but validly signed token, and a corrupted flow each occupy one variant.
Divergence delta is high: each H1 variant adds a named non-coverable step over P4-P6, while the H2 fifth variant adds none and is therefore deleted under branch 5a.
Stability is high: all H1 variants survive changes of JWT library, gateway, mobile versus web stack, payload wording, and runtime asset identity.
Parsimony is medium: H1 uses one four-valued feature, H2 uses two features for the same coverage, and H3 uses fewer features but fails coverage.
H1 is the winner with full marks on coverage, disjointness, delta, and stability, plus the best parsimony among covering sets.
H2 loses on parsimony and delta because its combined variant contributes no step of its own.
H3 loses on coverage and disjointness because each merged variant harbours two distinct non-coverable steps.
No return to STATE 3 is needed because the winner passes both critical criteria.

## 11. Recommended set
The class-specific discrimination function is: split authentication-jwt by which token-validity binding the test breaks, namely signature-algorithm trust, key-resolution control, claims-context acceptance, or protocol flow and token lifecycle.
Recommended variant `jwt-signature-forgery`: first non-coverable step is forging or stripping signature validity, and its divergence delta over P5 is the signature-removal plus offline secret-recovery procedure that mutation alone cannot express.
Recommended variant `jwt-key-resolution`: first non-coverable step is seizing key selection, and its divergence delta over P5 is the remote key-hosting, fetch-observation, rotation-timing, and fallback-triggering procedure.
Recommended variant `jwt-claims-confusion`: first non-coverable step is proving cross-context acceptance, and its divergence delta over P4 is the single-service claim-edit and nested-order verdicts that no cross-use matrix cell holds.
Recommended variant `jwt-flow-lifecycle`: first non-coverable step is driving and corrupting the protocol lifecycle, and its divergence delta over P1-P6 is the multi-step flow-execution plus rotation, reuse-detection, and revocation oracle sequence that no token-mutation step describes.
Non-discriminators are TechnologyStack in full, concrete Service, System, Endpoint, Parameter, Header, BaseURL, DataItem, HTTP history, token-kind labels, role and tenant identity, HMAC-secret and key material values, attack goal and impact, observation channel, and attacker capability level, each for the reasons recorded in section 6.
Aspects (not variants) are kid payload family inside key-resolution, claim and cell choice inside claims-confusion, confusion-versus-none-versus-ECDSA-versus-cracking inside signature-forgery, client and verifier shape inside flow-lifecycle, and clock-skew magnitude inside claims-confusion.
Cross-references owned elsewhere are token theft and exfiltration (XSS, CORS, transport skills), kid-injection payloads that mature into full SQL or command injection (those skills), authorization consequences of inflated scope (two-principal-authz), and proxy or gateway session mechanics, where the carrier step belongs to the `proxy-techniques` family and the cached-verdict step to the `defence-bypass` family.
Open questions: whether JWE decryption and content-confusion (as opposed to JWS validation) deserves a fifth variant once the class documents a JWE methodology, since the current skill names JWE once without a procedure.
Grey points: ECDSA misuse sits inside signature-forgery by verifier-strictness affinity, though a strict reading could place it with library-misuse aspects; kid-originated SQL or command execution stays inside key-resolution until the injection outgrows key selection, at which point the finding hands off; session fixation sits inside flow-lifecycle, though a future session-management skill could own its lifecycle half; DPoP and mTLS binding replay stays inside flow-lifecycle as a binding oracle, not a transport variant.
FAIL-level uncertainty: none, since every recommended variant traces to a named ontology value and a named failing parent step with positive divergence delta.
