# oauth - variant decomposition analysis

## 1. Class and scope
Source file for this analysis is `skills-unspurious/oauth/SKILL.md`, with extra methodology consulted non-authoritatively from `skills/oauth/SKILL.md`.
OAuth here is OAuth 2.0 and OIDC authorization-grant testing where the authorize-to-token chain must bind redirect, client, user intent, code, verifier, token, and audience without gap.
Scope covers redirect URI validation, authorization code handling and mix-up, state and nonce binding, PKCE enforcement, client authentication, scope and token reuse, OIDC confusion, Referer leakage, device-flow approval abuse, account linking, and mobile deep-link transport.

## 2. Ontology entity ledger
| Entity type | Value(s) | Source line(s) | Role |
|---|---|---|---|
| PreconditionEnvironment | authorization code flow with or without PKCE | 12-15, 131 | aspect (artifact and parameter variation inside variants) |
| PreconditionEnvironment | implicit and hybrid flows with token in fragment | 14, 68 | aspect (artifact-location variation inside binding variant) |
| PreconditionEnvironment | client-credentials flow with no user and no redirect | 14, 131 | aspect (vacuous authorize steps, P5-only parametrisation) |
| PreconditionEnvironment | device-authorization flow with user-code approval channel | 14, 121-123 | collapsed into signature feature (approval channel side) |
| PreconditionEnvironment | permissive redirect registration (path-prefix, subdomain wildcard, multiple URIs) | 26-28, 50-51, 64 | collapsed into signature feature (redirect-acceptance side) |
| PreconditionEnvironment | custom-scheme and universal-link dispatch registration | 28, 57, 136 | aspect (transport value inside redirect variant) |
| PreconditionEnvironment | dynamic client registration enabled | 20, 96 | aspect (client-provisioning value inside binding variant) |
| PreconditionEnvironment | Referer-leaking embedding context | 68, 118-119 | aspect (exfil-channel value inside redirect and binding variants) |
| TechnologyStack | OAuth2 and OIDC IdP product, JWKS and discovery endpoints, SPA and mobile frameworks, OS scheme handlers | 17-20, 26-30, 33-39 | non-discriminator (runtime stack, excluded axis) |
| DefensiveControl | redirect_uri strict matching and parser normalisation | 60-64, 132, 140-144 | collapsed into signature feature (redirect-check side) |
| DefensiveControl | state binding to client session and nonce binding to ID token | 78-82, 133, 140-144 | collapsed into signature feature (freshness-check side) |
| DefensiveControl | PKCE S256 requirement and code_verifier validation | 84-89, 134, 140-144 | collapsed into signature feature (verifier-check side) |
| DefensiveControl | client_secret authentication at token and introspection endpoints | 91-100, 107 | aspect (credential value inside binding variant) |
| DefensiveControl | audience, issuer, scope, refresh-rotation, and revocation enforcement | 103-114, 140-144 | aspect except token-format core which is cross-referenced to authentication-jwt |
| VulnerabilityClass | oauth redirect manipulation, code leakage, login CSRF, PKCE bypass, client misconfiguration, token confusion | 6-8, 47-114 | non-discriminator (the class itself) |
| AttackGoal | account takeover via stolen code or token | 8, 163 | non-discriminator (shared across variants) |
| AttackGoal | persistent access via refresh reuse and cross-client data access | 103-108, 152 | non-discriminator (shared outcome direction, method differs) |
| AttackerCapability | ability to lure victim through attacker page or device-approval prompt | 118-123, 133 | non-discriminator (shared lure precondition, channel value varies as aspect) |
| AttackerCapability | control of attacker callback listener for code capture | 49-57, 149 | non-discriminator (shared capture apparatus) |
| AttackerCapability | ability to register subdomain, application, or dynamic client | 64, 96 | non-discriminator (shared provisioning ability, target value is runtime) |
| AttackTechnique | redirect_uri fuzzing with encoding and parser tricks | 49-64, 132 | collapsed into signature feature (redirect-probing side) |
| AttackTechnique | state-strip and session-swap mid-flow plus nonce omission | 78-82, 133 | collapsed into signature feature (freshness-probing side) |
| AttackTechnique | PKCE downgrade to plain, verifier omission, and wrong-verifier replay | 84-89, 134 | collapsed into signature feature (verifier-probing side) |
| AttackTechnique | code injection, code replay, client_id swap, redirect_uri rebinding at token endpoint, cross-client token swap | 66-76, 135 | collapsed into signature feature (binding-probing side) |
| AttackTechnique | scope-escalation request and refresh-reuse attempt | 103-107 | aspect (parameter variation inside binding variant) |
| AttackTechnique | device-code polling with guessed codes plus approval inducement | 121-123 | collapsed into signature feature (approval-channel side) |
| AttackTechnique | Referer-harvest embedding and account-linking sequencing | 118-119, 125-127 | aspect (exfil and sequencing values inside redirect and binding variants) |
| AttackTechnique | JWT header and claim mutation (alg none, key confusion, kid, iss, aud) | 156-159 | outlier cross-referenced to authentication-jwt, not an oauth discriminator |
| PayloadPattern | redirect bypass strings with encoded slashes, at-tricks, suffixes, and query injection | 53-57 | aspect (encoding inside redirect variant) |
| PayloadPattern | redirect_uri parameter-pollution duplicate | 63 | aspect (encoding inside redirect variant) |
| PayloadPattern | downgraded code_challenge plain and absent or mismatched code_verifier | 84-89 | aspect (encoding inside PKCE variant) |
| Artifact | authorization code, access token, refresh token, ID token | 22-24, 66-76, 103-107 | non-discriminator (obtained objects parametrising whichever variant runs) |
| Artifact | discovery document, client_id inventory, redirect URI list | 33-43, 131 | non-discriminator (recon outputs feeding parametrisation) |
| ObservableSignal | full 302 redirect chain locations and callback query or fragment arrivals | 149 | non-discriminator (shared transport observation) |
| ObservableSignal | invalid-redirect_uri and unregistered-client error messages | 41-43 | non-discriminator (recon observation feeding parametrisation) |
| ObservableSignal | introspection active flag, userinfo PII return, cross-service acceptance | 103-114 | aspect (per-variant binding-confirmation signal, format core cross-referenced) |

## 3. RDF notion map
Vuln-specific attack surface and reconnaissance: authorize, token, userinfo, introspection, revocation, logout, discovery, JWKS, dynamic registration, web and mobile clients with redirect inventories; invariant is the authorize-to-token chain, what varies is which binding check and which transport channel is exercised.
Adversarial capabilities: luring a victim through a browser flow or a device-approval prompt, capturing codes at an attacker callback, registering subdomains or clients, and polling device codes; invariant is no control over the IdP validator, what varies is only the channel value used.
Common trust assumptions: server assumes the redirect_uri, state, nonce, PKCE verifier, client identity, and token audience presented at each step belong to the same legitimate session and client; invariant is the chain-binding assumption, what varies is which link the attacker breaks.
Testing methodology: the six parent steps P1-P6 listed in section 6; invariant is the map-then-probe-each-binding spine, what varies is which probe step bends per candidate procedure.
Proxy techniques: none held by this class; the attacker page and callback listener are direct delivery and capture apparatus rather than a proxy relay.
Defence bypass techniques: parser-differential redirect bypass, state and nonce removal or reuse, PKCE downgrade and omission, secretless token calls, scope over-request, and audience cross-use; invariant is defeating the chain binding, what varies is only the check value defeated except where a distinct probe kind exists.
Techniques anti-patterns: treating redirect matching as string prefix, trusting state without session binding, accepting plain PKCE, and accepting ID tokens as access tokens; the token-format members of this list are cross-referenced to authentication-jwt rather than re-stated.
Scripted tests (references/): none shipped with this skill; validation is described inline through redirect-matrix, binding-comparison, and chain-capture guidance at lines 138-152.
False positives: consistent redirect rejection, strict S256 PKCE enforcement, enforced and bound state and nonce, correct audience and issuer validation, and ownership-proved app links; these are invariant exclusion predicates.
Chaining: open redirect or XSS on a legitimate redirect_uri to exfiltrate codes, plus analytics and log leakage of codes; chaining companions are invariant amplifiers, not variant axes.

## 4. Runtime parametrisation
Consumed L0 and L1 runtime entities are the concrete Service under test, the Endpoint nodes for authorize, token, userinfo, introspection, revocation, and discovery, the Parameter and Header carriers for redirect_uri, client_id, state, nonce, code, code_challenge, code_verifier, scope, and tokens, the BaseURL and DataItem surfacing at those carriers, the System mechanism overlays for the IdP product and mobile dispatch, and the HTTP history showing 302 chains and token responses.
The concrete client identifiers, redirect URIs, scope strings, token literals, IdP product names, library versions, and mobile OS versions are runtime facts from the attack-surface graph, the knowledge base, and the HTTP history.
These parametrise whichever variant runs and never define a variant.
Technology stack, payload literal, library version, and target asset identity are excluded axes under STATE 6 stability.

## 5. Agent-with-skill walkthrough
The hunting circumstance is an agent holding an OAuth deployment with mapped clients and redirect URIs and needing to prove that a gap in the authorize-to-token chain yields code theft, session CSRF, verifier bypass, client confusion, or approval phishing.
Parent methodology steps with completion conditions: P1 map flows, complete when every grant type, client, and redirect URI in use is listed.
P2 redirect matrix, complete when redirect_uri validation has been fuzzed per client with encoding and parser tricks and every acceptance recorded.
P3 CSRF, complete when flows have been initiated without state, sessions swapped mid-flow, and nonce behavior recorded.
P4 PKCE, complete when codes have been replayed with wrong and missing verifiers and challenge-method downgrade attempted.
P5 token exchange, complete when codes and tokens have been swapped between clients, redirect_uri and client_id rebinding attempted, and cross-audience acceptance tested.
P6 mobile and deep links, complete when custom schemes, intent filters, and universal-link dispatch have been tested for hijack.

## 6. Feature-verdict table
| Candidate feature (entity value) | Accurate? | Exhaustive? | Verdict | Evidence |
|---|---|---|---|---|
| Grant-type label alone, code versus implicit versus hybrid versus client-credentials (PreconditionEnvironment) | No | N/A | non-discriminator | P1 maps every grant with the same kind of inventory action and P2-P5 exercise the same probe kinds with different artifact parameters. |
| Device-approval channel with polling plus inducement (PreconditionEnvironment, AttackTechnique) | Yes | No | discriminator | P5 performs token swapping while device abuse polls guessed codes and induces a victim approval, which is a different kind of action that P5 never names. |
| Redirect-acceptance strictness with parser differentials (PreconditionEnvironment, DefensiveControl, AttackTechnique) | Yes | No | discriminator | P2 names fuzzing but does not cover per-pattern normalisation differentials, pollution precedence, and wildcard-claim chaining as a matrix procedure. |
| Request-freshness binding via state and nonce (DefensiveControl, AttackTechnique) | Yes | No | discriminator | P3 names initiation without state and session swap but does not cover binding-scope escape, reuse-oracle sequencing, and nonce-replay confirmation. |
| Code-to-verifier binding via PKCE method and validation (DefensiveControl, AttackTechnique) | Yes | No | discriminator | P4 names replay and downgrade but does not cover challenge-less issuance plus any-verifier acceptance and comparison-weakness oracles. |
| Code and token-to-client binding via client_id, redirect_uri rebinding, and audience (DefensiveControl, AttackTechnique) | Yes | No | discriminator | P5 names swapping but does not cover authorize-versus-token binding comparison, mix-up sequencing, and introspection-auth probing as one procedure. |
| Mobile dispatch transport, custom scheme versus universal link (PreconditionEnvironment) | Yes | Yes | aspect | P2 plus P6 perform the same redirect-probe kind with a transport parameter and P6 already enumerates scheme, intent, and universal-link values. |
| Referer-harvest embedding context (PreconditionEnvironment, AttackTechnique) | Yes | Yes | aspect | P2 plus P5 harvest-and-replay with a channel parameter covers subresource embedding and Referer-policy dependence without a new probe kind. |
| Account-linking and email-collision sequencing (AttackTechnique) | Yes | Yes | aspect | P3 plus P5 sequencing with an identity-comparison completion covers link-without-reauth without a new probe kind. |
| Dynamic-registration provisioning value (PreconditionEnvironment) | Yes | Yes | aspect | P1 plus P5 perform the same map-then-exchange kind with a provisioned-client parameter. |
| Client-secret presence value, secretless versus secret-bearing calls (DefensiveControl) | Yes | Yes | aspect | P5 performs the same token-call kind with a credential parameter covering every secret value. |
| Scope-string and refresh-reuse values (AttackTechnique, DefensiveControl) | Yes | Yes | aspect | P5 performs the same over-request and reuse kind with scope and token parameters, with rotation semantics cross-referenced. |
| Token-format values, JWT versus opaque and claim sets (TechnologyStack, DefensiveControl, AttackTechnique) | No | N/A | non-discriminator here with cross-reference | Token-format mutation is owned by authentication-jwt and this class consumes only the confusion verdict, so no oauth step bends on format alone. |
| TechnologyStack product and version values (TechnologyStack) | No | N/A | non-discriminator | Parent steps perform the same kind of action across IdP products, SPA frameworks, and OS versions, which are excluded axes. |
| Attacker lure, callback, and registration abilities (AttackerCapability) | No | N/A | non-discriminator | Shared preconditions across all candidates with no step-kind change when the ability value varies. |
| Shared takeover and persistence goals (AttackGoal) | No | N/A | non-discriminator | Same probe kinds regardless of whether the outcome is takeover, persistence, or cross-client access. |
| Code, token, discovery, and inventory artifacts (Artifact) | No | N/A | non-discriminator | Obtained or recon-produced objects that parametrise probes rather than bending any step. |
| Redirect-chain, error-message, and acceptance signals (ObservableSignal) | No | N/A | non-discriminator | Shared observations and per-variant confirmations with no step-kind change. |

## 7. Step-coverage falsification
Redirect-acceptance strictness: parent step P2 says for each client fuzz redirect_uri validation with encoding and parser tricks.
The uncovered reality is per-pattern normalisation differentials between validator and consumer, first-versus-last pollution precedence, wildcard-subdomain claiming chains, and scheme-downgrade acceptance, which need a matrix-per-client plus consumer-confirmation procedure that P2 never names.
Request freshness: parent step P3 says initiate OAuth without state and swap sessions mid-flow.
The uncovered reality is proving state-to-session and state-to-verifier binding scope, cross-request and cross-session reuse oracles, fixation-shaped login CSRF, and OIDC nonce injection and replay, which need a bind-and-reuse-oracle procedure that P3 never names.
PKCE binding: parent step P4 says replay codes with wrong or missing verifier and downgrade the challenge method.
The uncovered reality is authorization codes issued without any challenge combined with token endpoints accepting any verifier, plus comparison-weakness oracles such as case-insensitive or truncated matching, which need an issuance-without-challenge plus verifier-oracle procedure that P4 never names.
Client binding: parent step P5 says swap codes and tokens between clients and test cross-audience acceptance.
The uncovered reality is comparing authorize-step versus token-step binding of redirect_uri, client_id, and PKCE, sequencing attacker-initiated and victim-completed mix-up flows, probing token and introspection endpoints with secretless and client-only authentication, and over-requesting scope, which need a compare-bindings plus mix-up-sequence procedure that P5 never names.
Device channel: parent step P5 says swap codes and tokens between clients.
The uncovered reality is polling the device-code endpoint with guessed codes under slow rate limits and inducing a victim to approve an attacker-initiated login, which is a poll-and-induce-approval procedure that P5 never names.
Mobile transport: no falsification holds because P2 with a custom-scheme redirect value plus P6 dispatch-hijack confirmation covers scheme, intent-filter, and universal-link values.
Referer channel: no falsification holds because P2 plus P5 harvesting with an embedding parameter covers subresource mounting and policy-dependent capture.
Account linking: no falsification holds because P3 plus P5 sequencing with identity comparison covers link-without-reauth and email collision.
Dynamic registration: no falsification holds because P1 inventory plus P5 exchange with a provisioned-client parameter covers attacker-controlled redirect registration.
Secret presence: no falsification holds because P5 token calls with a credential parameter cover secretless, client-only, query-carried, and leaked-secret values.
Scope and refresh values: no falsification holds because P5 over-request and reuse attempts with scope and token parameters cover escalation and rotation probing, with rotation semantics cross-referenced.
Grant-type label alone: no falsification holds because P1 enumerates every grant and P2-P5 parametrise artifact location and vacuous steps without a new probe kind.
Token format: no falsification holds inside this class because header and claim mutation is owned by authentication-jwt and this class only consumes the acceptance verdict.

## 8. Hypotheses
H1 (single-feature, chain-binding check): if the class is partitioned by which authorize-to-token binding check bends its probe step into redirect validation, request freshness, PKCE verifier binding, and code-to-client binding, then each partition owns a distinct first non-coverable step and jointly covers the four falsifications above excluding device.
This hypothesis is falsified if any partition lacks its own non-coverable step or if two partitions claim the same falsification.
H2 (combined-feature, binding check crossed with approval channel): if H1 is extended with a device-approval-channel partition that adds poll-and-induce-approval over P5, then the set covers the device falsification with no overlap against the four H1 partitions.
This hypothesis is falsified if device polling turns out to be the same swap kind as P5 or if its approval step collapses into login CSRF without its own non-coverable step.
H3 (single-feature, grant-type flow split): if the class is partitioned by flow label into code, implicit, hybrid, device, client-credentials, and refresh partitions, then each flow partition adds its own non-coverable step.
This hypothesis is falsified if flow labels only swap artifact parameters and leave probe kinds unchanged, which the step test in section 7 confirms for every flow except the device channel.
H4 (combined-feature, binding check crossed with token format): if each H1 partition is further split by JWT versus opaque token format, then each format cell adds its own non-coverable mutation step.
This hypothesis is falsified if token-format mutation is owned by authentication-jwt and no oauth parent step bends on format alone, which section 7 confirms.

## 9. Variant sets per hypothesis
| Hypothesis | Variant | First non-coverable step |
|---|---|---|
| H1 | oauth-redirect-uri-validation | P2 redirect matrix extended into per-pattern normalisation-differential plus consumer-confirmation matrix. |
| H1 | oauth-state-nonce-csrf | P3 CSRF probe extended into binding-scope plus reuse-oracle and nonce-replay confirmation. |
| H1 | oauth-pkce-enforcement | P4 PKCE probe extended into issuance-without-challenge plus verifier-oracle probing. |
| H1 | oauth-code-client-binding | P5 token exchange extended into authorize-versus-token binding comparison plus mix-up sequencing. |
| H2 | H1 four plus oauth-device-approval | P5 token exchange fails further into device-code polling plus approval-inducement procedure. |
| H3 | oauth-code-flow, oauth-implicit-flow, oauth-hybrid-flow, oauth-device-flow, oauth-client-credentials-flow, oauth-refresh-flow | No distinct first step per flow except device, which repeats the H2 device step. |
| H4 | H1 four each split by JWT versus opaque format | No distinct first step per format cell, since mutation steps live in authentication-jwt. |

## 10. Well-formedness evaluation
Weights in order are coverage (critical), disjointness (critical), divergence delta (high), stability (high), parsimony (medium).
H1 scores coverage partial pass because it covers the four chain-binding falsifications but leaves the device-channel falsification without an owner.
H1 scores disjointness pass because redirect-matrix, freshness-oracle, verifier-oracle, and binding-comparison procedures claim disjoint probe sequences and completions.
H1 scores divergence-delta pass because each of its four variants adds the non-coverable step named in section 9 over P2, P3, P4, and P5 respectively.
H1 scores stability pass because swapping IdP product, client platform, payload literal, or runtime asset leaves each binding procedure intact.
H1 scores parsimony pass with one collapsed binding-check feature and four variants, subject only to missing device coverage.
H2 scores coverage pass because its fifth variant owns the device falsification while retaining the four H1 owners.
H2 scores disjointness pass because poll-and-induce-approval completes on attacker-session approval rather than redirect acceptance, freshness reuse, verifier acceptance, or swap acceptance.
H2 scores divergence-delta pass because the device variant adds polling plus inducement over P5, which never names either action.
H2 scores stability pass because IdP product, rate-limit tuning, and user-code alphabet are runtime parameters that leave polling plus inducement intact.
H2 scores parsimony pass with five variants under a binding-check plus approval-channel signature, which is the fewest set achieving full coverage.
H3 fails coverage, divergence delta, and parsimony because five of its six flow cells repeat H1 steps with swapped artifact parameters and add no non-coverable step, so H3 is discarded per STATE 4 branch 4a.
H4 fails divergence delta, stability, and parsimony because format cells duplicate authentication-jwt mutation steps and multiply variants by technology, so H4 is discarded per STATE 4 branch 4a.
Winner is H2 with losing reason for H1 being incomplete device coverage, for H3 being flow-label parametrisation with zero delta, and for H4 being out-of-scope token-format duplication.
No return to STATE 3 is needed because the winner passes coverage and disjointness.
STATE 1 completed with six parent steps P1-P6 and a full ten-type entity inventory and no malformed-class outlier.
STATE 2 completed with the verdicts recorded in section 6, separating five discriminator values from aspects and non-discriminators.
STATE 3 collapsed co-varying redirect, freshness, verifier, binding, and channel values per branch 3a and kept transport, Referer, scope, secret, and registration values as aspects per branch 3b.
STATE 4 stated two single-feature hypotheses plus two combined-or-flow hypotheses with explicit falsifiers, and STATE 5 derived each set with first non-coverable steps and secondary divergences folded inside variants.

## 11. Recommended set
Discrimination function in one sentence: OAuth decomposes by which authorize-to-token binding check bends its probe step, namely redirect-uri validation, request freshness via state and nonce, code-to-verifier binding via PKCE, code-and-token-to-client binding, plus the device-approval channel.
Recommended variant oauth-redirect-uri-validation diverges by running a per-pattern normalisation-differential plus consumer-confirmation matrix over parent step P2, which never names pollution precedence, validator-versus-consumer differentials, or wildcard-claim chaining.
Recommended variant oauth-state-nonce-csrf diverges by running binding-scope plus reuse-oracle and nonce-replay confirmation over parent step P3, which never names binding escape, cross-session reuse oracles, or injection sequencing.
Recommended variant oauth-pkce-enforcement diverges by running issuance-without-challenge plus verifier-oracle probing over parent step P4, which never names challenge-less issuance with any-verifier acceptance or comparison-weakness oracles.
Recommended variant oauth-code-client-binding diverges by running authorize-versus-token binding comparison plus mix-up sequencing with secretless and scope probing over parent step P5, which never names rebinding comparison, attacker-initiated mix-up order, or introspection-auth probing.
Recommended variant oauth-device-approval diverges by running device-code polling plus approval inducement over parent step P5, which describes only code and token swapping and never names guessing plus victim-approval sequencing.
Non-discriminators are grant-type labels except the device channel, technology stack with versions, attacker lure and callback and registration abilities, shared takeover and persistence goals, code and token and inventory artifacts, redirect-chain and error and acceptance signals, and token-format mutation which is cross-referenced to authentication-jwt.
Open questions: none at FAIL level; the analysis leaves no uncovered falsification and no skipped state.
Grey points: mobile custom-scheme and universal-link dispatch rides inside oauth-redirect-uri-validation as a transport parameter, which holds only while OS hijack needs no probe beyond redirect acceptance plus dispatch confirmation.
Grey points: Referer-harvest embedding rides inside redirect and binding variants as an exfil-channel parameter, which holds only while capture needs no standalone oracle beyond harvest-and-replay.
Grey points: dynamic registration, secretless calls, scope over-request, refresh reuse, and account linking ride inside oauth-code-client-binding as secondary divergences, which holds only while none of them grows its own non-coverable step.
Grey points: client-credentials testing reduces to the binding variant with vacuous P2-P4, which holds only while scope and audience probing stays the same token-exchange kind without a user session.
Grey points: ID-token versus access-token confusion verdicts are consumed from authentication-jwt and never re-proven here, which holds only while the loader cross-reference stays authoritative.
