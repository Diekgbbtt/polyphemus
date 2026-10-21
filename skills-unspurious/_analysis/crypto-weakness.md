# crypto-weakness - variant decomposition analysis

## 1. Class and scope
This class covers weak cryptographic implementations in session management, token generation, and data storage that enable forgery, prediction, and side-channel recovery leading to authentication bypass and account takeover.
It is derived from `skills-unspurious/crypto-weakness/SKILL.md` (180 lines), with `skills/crypto-weakness/SKILL.md` consulted only for tooling detail, never as authority.
No outlier state occurred in STATE 1 because the class carries six methodology steps (Session Token Analysis, Weak Hash Exploitation, JWT Secret Brute-Force, Token Forgery, Timing Attack, Entropy Analysis) and a populated weakness inventory (lines 8, 33-37, 179).

## 2. Ontology entity ledger
| Entity type | Value(s) | Source line(s) | Role |
|---|---|---|---|
| PreconditionEnvironment | Tokenised session or recovery mechanism in use (session tokens, password resets, CSRF tokens, remember-me cookies) | 8 | Non-discriminator (class applicability condition shared by all candidates) |
| PreconditionEnvironment | Token derived from guessable input, weak PRNG, sequential counter, embedded timestamp or user id, or short sub-128-bit value | 33-37, 167-169, 179-180 | Discriminator candidate (drives unpredictability testing) |
| PreconditionEnvironment | Token integrity depends on a guessable HMAC or cookie signing secret, or on unchecked algorithm acceptance | 98-105, 179 | Discriminator candidate (drives signing-trust testing) |
| PreconditionEnvironment | Token comparison executes in non-constant time with attacker-measurable response timing | 131-133 | Discriminator candidate (drives timing-oracle testing) |
| TechnologyStack | Flask and itsdangerous cookie sessions, JWT with HS256, MD5 and SHA1 hashes, reset and remember-me token endpoints | 15-31, 35, 98-105, 112-129 | Non-discriminator (stability rule: procedure survives stack change) |
| DefensiveControl | Cryptographically strong random token generation at 128 bits or above | 36, 179-180 | Falsification oracle, not a discriminator (its absence is what prediction proves) |
| DefensiveControl | Strong unguessable signing secret with algorithm pinning and none-alg rejection | 179 | Falsification oracle for signing forgery, not a discriminator |
| DefensiveControl | Constant-time token comparison | 131-133 | Falsification oracle for timing oracle, not a discriminator |
| VulnerabilityClass | Predictable or low-entropy token including hash-of-known-input derivation | 33-37, 41-76 | Discriminator candidate (unpredictability binding) |
| VulnerabilityClass | Weak signing trust (guessable HMAC secret, Flask default secret, missing none-alg rejection) | 80-105, 179 | Discriminator candidate (signing-trust binding) |
| VulnerabilityClass | Timing side channel in token comparison | 131-152 | Discriminator candidate (comparison-independence binding) |
| AttackGoal | Authentication bypass, account takeover, and privilege escalation | 8 | Non-discriminator (impact never bends a step) |
| AttackerCapability | Ability to collect multiple tokens for one or more accounts through repeated reset or session issuance | 157-170, 181 | Parametrises prediction testing, not a discriminator (collection volume changes confidence, never procedure kind) |
| AttackerCapability | Ability to issue repeated timed verification requests and compute statistics over samples | 136-152 | Parametrises timing testing, not a discriminator (sample count changes signal, never procedure kind) |
| AttackerCapability | Knowledge of victim identifiers (username, email, phone) usable as known plaintext | 46-55, 71-76 | Parametrises hash recomputation, not a discriminator (identifier choice changes candidate, never procedure kind) |
| AttackTechnique | Decode and inspect token structure (base64 and JSON and JWT claim read) | 10-31, 173 | Non-discriminator (shared opening step owned by every variant) |
| AttackTechnique | Entropy collection with sequence and timestamp pattern analysis | 154-170, 181 | Discriminator candidate (prediction procedure) |
| AttackTechnique | Hash recomputation over known plaintexts plus rainbow or online lookup | 41-76, 177 | Discriminator candidate (prediction procedure) |
| AttackTechnique | Offline HMAC and cookie-secret brute force over a wordlist with constant-time-safe verify | 80-105 | Discriminator candidate (signing-recovery procedure) |
| AttackTechnique | Elevated token minting under a recovered secret plus alg-none stripping | 107-129, 179, 182 | Discriminator candidate (forgery procedure) |
| AttackTechnique | Iterative prefix timing oracle with baseline comparison and statistical averaging | 131-152 | Discriminator candidate (timing procedure) |
| PayloadPattern | Forged claim set with elevated role markers (`role admin`, `is_admin true`, `user_id 1`) | 182 | Aspect inside signing forgery (claim choice, same minting procedure) |
| PayloadPattern | Hash candidate variants (case folding, algorithm swap across MD5 and SHA1 and SHA256) | 50-58, 71-76 | Aspect inside predictable-token recovery (derivation wording, same recompute procedure) |
| PayloadPattern | Timing prefix candidates over hex alphabet with baseline padding | 146-151 | Aspect inside timing oracle (prefix choice, same measurement procedure) |
| Artifact | Captured session cookies, reset tokens, and decoded claim sets | 15-31, 157-170 | Non-discriminator (runtime input to every variant) |
| Artifact | Recovered signing secret and minted elevated Flask or JWT token | 80-105, 107-129 | Non-discriminator (minted by procedure, consumed at runtime) |
| Artifact | Cracked hash-to-plaintext mapping from recomputation or online lookup | 63-76 | Produced inside predictable-token variant, consumed at runtime thereafter |
| ObservableSignal | Accepted forged or predicted token (valid reset, authenticated session, elevated role) | 54-58, 117-129 | Non-discriminator (acceptance channel shared by prediction and forgery) |
| ObservableSignal | Decoded predictable fields, duplicate tokens, short lengths, or hex-only fixed-length structure | 33-37, 163-169 | Non-discriminator (inspection signal shared as entry evidence) |
| ObservableSignal | Timing differential of a correct prefix over baseline with statistical separation | 146-151 | Used only inside timing oracle, still an observation channel rather than a procedure difference in itself |

## 3. RDF notion map
Vuln-specific attack surface and reconnaissance: session cookies, JWTs, password-reset endpoints, CSRF tokens, and remember-me cookies (lines 8, 10-31) is invariant across variants.
Adversarial capabilities: multi-token collection position plus known-identifier knowledge plus repeated timed-request position (lines 46-55, 136-170) vary only as runtime parametrisation, never as procedure.
Common trust assumptions: each token is unpredictable, each signature binds claims to a strong secret under a pinned algorithm, and each comparison leaks no timing (lines 8, 33-37, 131-133, 179) is the invariant that every variant falsifies at a different binding.
Testing methodology: the six parent steps P1 to P6 (section 5) are invariant as labelled, but a coarse reading of P2 plus P3 as one generic randomness check and P4 plus P5 as one generic crack-and-forge step lumps genuinely different procedures and therefore fails the step test.
Proxy techniques: none are described in this class, so nothing is pinned here.
Defence bypass techniques: weak-secret guessing, none-alg acceptance, and statistical timing separation (lines 80-105, 131-152, 179) are the per-variant oracles, and each variant bypasses a different control.
Techniques anti-patterns: none are named in this class, so nothing is pinned here.
Scripted tests (`references/`): none exist in the spurious skill (no `references/` directory), which is recorded as a gap rather than a discriminator.
False positives: strong random tokens with full uniqueness, rejected forged claims, and flat timing distributions (lines 163-169, 146-151) are invariant rejection signals shared by all variants.
Chaining: use of a forged or predicted token for account takeover and privilege escalation (line 8) is an invariant exit edge owned by auth and session-management consumers, never a variant axis here.

## 4. Runtime parametrisation
The concrete Service under test, the System mechanism it lies on (web session layer, API gateway, mobile client), and the Endpoint, Parameter, Header, BaseURL, and DataItem loci where tokens are issued and presented are supplied at runtime from the attack-surface graph.
The knowledge base supplies token endpoint identity, hash algorithm facts, HMAC-secret candidates including application and domain names, token lifetimes, and comparison implementation facts as runtime data.
The HTTP history supplies captured cookies, reset tokens, decoded claims, prior acceptance or rejection observations, and timing samples.
Token kind labels (session versus reset versus CSRF versus remember-me), role identities, victim identifiers, secret string values, and claim values parametrise a variant and never define one.
Technology stack differences (Flask versus JWT versus opaque reset token, MD5 versus SHA1 versus SHA256, python inline HMAC versus flask-unsign versus hashcat) change tooling and encoding, never which variant procedure the agent runs.

## 5. Agent-with-skill walkthrough
The hunting circumstance is an application that maintains sessions and account-recovery flows with opaque or structured tokens whose generation, signing, and comparison the agent cannot see.
The agent decodes and inspects every captured token first (P1), and the step is complete when structure, claims, and encoding are recorded per token.
The agent collects multiple tokens and assesses entropy and embedded patterns next (P2), and the step is complete when lengths, uniqueness, and sequence or timestamp structure are judged.
The agent recomputes weak hashes over known plaintexts and queries lookup sources next (P3), and the step is complete when each candidate derivation has an acceptance verdict.
The agent recovers the signing secret by offline brute force next (P4), and the step is complete when the secret is confirmed by local HMAC re-verification.
The agent forges elevated tokens under the recovered secret or with stripped algorithm next (P5), and the step is complete when each forged token has an acceptance verdict.
The agent measures comparison timing with a statistical prefix oracle last (P6), and the step is complete when each prefix hypothesis is confirmed or refuted by timing separation.
STATE 2 finding preview: a generic crack-and-forge description cannot describe statistical timing measurement, and a generic randomness description cannot describe offline HMAC search or signature-layer removal.

## 6. Feature-verdict table
| Candidate feature | Accurate? | Exhaustive? | Verdict | Evidence |
|---|---|---|---|---|
| Token unpredictability (sequence, timestamp, known-input hash, short length) | No | No | Discriminator | Generic randomness language assumes statistical collection, while hash recomputation performs deterministic re-derivation plus online reset acceptance and lookup that collection alone never names |
| Signing trust (secret guessability, Flask defaults, none acceptance) | No | No | Discriminator | Generic crack-and-forge assumes secret recovery then minting, while alg-none performs signature removal with no recovery and offline HMAC search adds a local verify loop no forge step names |
| Comparison-timing independence (constant-time versus early-exit) | No | No | Discriminator | No validity-testing step performs repeated measurement with baseline statistics, since the procedure kind is side-channel inference rather than token validity submission |
| Technology stack (Flask versus JWT versus opaque token, MD5 versus SHA1) | Yes | Yes | Non-discriminator | Same procedure replays across stacks with only encoding and tooling changed, so the stack parametrises rather than bends any step |
| Token kind (session versus reset versus CSRF versus remember-me) | Yes | Yes | Aspect | Token kind selects which endpoint issues and accepts the token, while the recovery or forgery procedure kind stays unchanged |
| Hash derivation wording (case folding, algorithm swap) | Yes | Yes | Aspect | Derivation choice changes inside the identical recompute-and-test procedure, so this is a payload aspect of the predictable-token variant |
| Weak-secret value and wordlist composition | Yes | Yes | Non-discriminator | Secret identity is a runtime KB fact per the version-and-secret exclusion, never a procedure difference |
| Forged claim choice (admin role markers) | Yes | Yes | Aspect | Claim choice changes inside the identical minting procedure, so this is a payload aspect of the signing-forgery variant |
| Timing sample count and threshold magnitude | Yes | Yes | Aspect | Sample depth and separation ratio are continuous values inside the identical measurement procedure, so they cannot partition variants (branch 3b) |
| Attack goal and impact (bypass, takeover, escalation) | Yes (no step changes kind) | N/A | Non-discriminator | Impact never changes which action the agent performs, so Question A fails immediately |
| Observation channel (status code, response text, timing value) | Yes | Yes | Non-discriminator | Acceptance reading is shared machinery, while timing values are the oracle inside one variant rather than a cross-class axis |
| Tester tooling (inline python versus flask-unsign versus hashcat versus online lookup) | Yes | Yes | Non-discriminator | Tool choice replays the same procedure, so tooling never discriminates |

## 7. Step-coverage falsification
For the known-input-hash value, parent step P2 (assess entropy over collected tokens) is neither accurate nor exhaustive because deterministic recomputation of MD5 or SHA1 over usernames and emails plus online reset acceptance is re-derivation rather than statistical pattern analysis, and P2 names no recomputation or lookup step.
For the sequential-counter and embedded-timestamp values, P2 is accurate but only jointly exhaustive with P3 verdicts, and the combined collect-plus-predict procedure still diverges from offline secret search and from timing measurement, so the unpredictability group holds one non-coverable step.
For the weak-HMAC-secret value, parent step P5 (forge elevated tokens) is not exhaustive because local brute force with HMAC re-verification is a recovery loop that minting alone cannot express, so P4 is required as its own non-coverable step.
For the alg-none value, parent step P4 plus P5 (recover secret then forge) is neither accurate nor exhaustive because stripping the signature performs validation-layer removal with no secret recovery, and no recover-then-mint description covers acceptance without a key.
For the Flask-versus-JWT minting difference, P5 remains accurate and exhaustive because only serialization and library calls change, so this difference is an aspect rather than a falsification.
For the timing-prefix value, no parent validity step (P1 through P5) is accurate because iterative baseline measurement with statistical averaging is side-channel inference rather than token submission, and no acceptance verdict step names a timing oracle sequence.
Branch 3a check: unpredictability, signing trust, and timing independence do not co-vary, since predictable tokens, guessable secrets, and leaky comparisons each fail independently in the wild.
Branch 3b check: token length and entropy magnitude, secret strength and wordlist size, and timing thresholds and sample counts are continuous or overlapping values, so they are recorded as aspects inside the nearest variant, never as variant axes.

## 8. Hypotheses
H1 (single-feature): if the discrimination feature is which cryptographic trust property the test breaks (unpredictability versus signing trust versus comparison-timing independence), then the class yields exactly three variants, and H1 is falsified if any variant lacks its own non-coverable step or if two variants share one.
H2 (combined-feature): if trust property is crossed with token form (structured signed token versus opaque short token), then opaque-token prediction splits off a fourth combined variant with its own short-token brute-force step beyond H1, and H2 is falsified if that fourth set adds no non-coverable step over the predictable-token variant.
H3 (minimal two-way): if the only real split is offline cryptographic recovery (prediction plus secret search) versus interactive oracle exploitation (forgery acceptance plus timing), then two variants suffice, and H3 is falsified if prediction and signing recovery each demand a distinct non-coverable step that one merged recovery step cannot perform.
Branch 4a note: H3 is discarded if the STATE 5 derivation shows hash recomputation with online reset acceptance and HMAC search with local re-verification are different oracle kinds, because then the two-way merge leaves a non-coverable step homeless.

## 9. Variant sets per hypothesis
| Hypothesis | Variant | First non-coverable step (methodology order) | Secondary divergences carried inside |
|---|---|---|---|
| H1 | crypto-predictable-token | Prove token predictability (collect N tokens, judge uniqueness and embedded sequence or timestamp, recompute MD5 or SHA1 over known identifiers, query rainbow or online lookup, test predicted token at the accepting endpoint) | Hash derivation wording, token-kind selection, and length thresholds are aspects, and lookup tooling is runtime choice |
| H1 | crypto-signing-key-forgery | Break signing trust (brute-force HMAC or cookie secret offline with local re-verification, strip algorithm to none where accepted, mint elevated Flask or JWT claims under the recovered or empty key) | Flask versus JWT serialization, claim choice, and wordlist composition are aspects, and secret value is runtime KB fact |
| H1 | crypto-timing-oracle | Extract the token through comparison timing (establish timing baseline, iterate prefix candidates with repeated samples, confirm by statistical separation) | Prefix alphabet, sample count, and threshold ratio are aspects, and network jitter handling is measurement robustness rather than a new step |
| H2 | Same three as H1 plus crypto-short-token-brute-force | Same first steps as H1, with the fourth variant predicted to own exhaustive short-token search | STATE 5 branch 5a test: short-token search reuses the predict-and-test step of the predictable-token variant and adds no step of its own, so it collapses back into crypto-predictable-token |
| H3 | crypto-offline-recovery (prediction plus secret search merged) | First non-coverable step is ambiguous between proving predictability and recovering the signing secret | STATE 5 derivation fails: online reset acceptance of a recomputed hash cannot be performed by local HMAC re-verification, so coverage fails |
| H3 | crypto-interactive-oracle (forgery plus timing merged) | First non-coverable step is ambiguous between minting under a key and measuring a timing side channel | STATE 5 derivation fails: statistical timing inference cannot be performed by token minting and acceptance, so coverage and disjointness fail |

## 10. Well-formedness evaluation
Coverage is critical: H1 places every genuine non-coverable step (predict-and-test with recomputation and lookup, offline secret search with local verify plus alg removal and minting, statistical timing extraction) in exactly one variant.
Disjointness is critical: H1 variants never share a technique, since a predicted token, a key-minted or stripped token, and a timing-extracted prefix each occupy one variant.
Divergence delta is high: each H1 variant adds a named non-coverable step over the coarse parent, while the H2 fourth variant adds none and is therefore deleted under branch 5a.
Stability is high: all H1 variants survive changes of token stack, hash algorithm, secret value, wordlist, claim wording, tooling, and runtime asset identity.
Parsimony is medium: H1 uses one three-valued feature, H2 uses two features for the same coverage, and H3 uses fewer features but fails coverage.
H1 is the winner with full marks on coverage, disjointness, delta, and stability, plus the best parsimony among covering sets.
H2 loses on parsimony and delta because its combined variant contributes no step of its own.
H3 loses on coverage and disjointness because each merged variant harbours two distinct oracle kinds.
No return to STATE 3 is needed because the winner passes both critical criteria.

## 11. Recommended set
The class-specific discrimination function is: split crypto-weakness by which cryptographic trust property the test breaks, namely token unpredictability, signing-key trust, or comparison-timing independence.
Recommended variant `crypto-predictable-token`: first non-coverable step is proving token predictability through collection plus recomputation plus lookup plus acceptance testing, and its divergence delta over P2 is the deterministic re-derivation and lookup-and-test procedure that statistical collection alone cannot express.
Recommended variant `crypto-signing-key-forgery`: first non-coverable step is breaking signing trust through offline secret search plus algorithm removal plus elevated minting, and its divergence delta over P4 plus P5 is the local HMAC re-verification loop and the no-key removal procedure that generic crack-and-forge language never names.
Recommended variant `crypto-timing-oracle`: first non-coverable step is extracting the token through a statistical timing oracle, and its divergence delta over P1 through P5 is the baseline-plus-prefix measurement sequence that no validity-submission step describes.
Non-discriminators are TechnologyStack in full, concrete Service, System, Endpoint, Parameter, Header, BaseURL, DataItem, HTTP history, token-kind labels, victim identifier values, secret and wordlist values, attack goal and impact, acceptance observation channel, and tester tooling, each for the reasons recorded in section 6.
Aspects (not variants) are hash derivation wording and length thresholds inside predictable-token, claim choice and serialization inside signing forgery, and sample depth and threshold ratios inside timing oracle.
Cross-references owned elsewhere are JWT algorithm confusion beyond none and kid plus jku plus x5u key-resolution mechanics (authentication-jwt), authorization consequences of inflated roles (two-principal-authz), and proxy or gateway session mechanics where they belong to the `proxy-techniques` family.
Open questions: whether remember-me and CSRF token scopes need dedicated acceptance matrices once the class documents per-scope endpoints, since the current skill names them once without a procedure.
Grey points: alg-none sits inside signing forgery by validation-removal affinity, though a strict reading could place it with parser-misuse aspects; short-token brute force stays inside predictable-token until exhaustive search outgrows prediction, at which point the finding hands off to rate-limit analysis; Flask default secrets stay inside signing forgery as weak-secret values, not a framework variant; timing jitter countermeasures stay inside the timing variant as measurement robustness, not a network variant.
FAIL-level uncertainty: none, since every recommended variant traces to a named ontology value and a named failing parent step with positive divergence delta.
