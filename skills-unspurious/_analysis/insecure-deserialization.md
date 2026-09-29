# insecure-deserialization - variant decomposition analysis

## 1. Class and scope
This class covers attacker-controlled byte streams and structured blobs reaching language-native unmarshal functions, enabling remote code execution, authentication bypass, and logic manipulation through gadget chains, magic methods, and polymorphic type binding.
It is derived from `skills-unspurious/insecure-deserialization/SKILL.md` (153 lines), with `skills/insecure-deserialization/SKILL.md` consulted only for extra methodology detail, never as authority.
No outlier state occurred in STATE 1 because the class carries six methodology steps P1 to P6 (lines 120-126) and a populated per-runtime weakness inventory across Java, Python, PHP, .NET, Ruby, and Node.js (lines 44-103).

## 2. Ontology entity ledger
| Entity type | Value(s) | Source line(s) | Role |
|---|---|---|---|
| PreconditionEnvironment | Endpoint accepts serialized blobs via cookies, sessions, params, queues, frames, uploads, cache, or DB columns | 20-24 | Discriminator context (carries trigger-topology values) |
| PreconditionEnvironment | Blob reaches the sink with no integrity check versus under a weak or removable signature | 98-99, 107-110 | Discriminator candidate F1 (blob trust basis) |
| PreconditionEnvironment | Blob is stored and rehydrated by a later job versus a phar path is consumed by a file operation | 84-85, 112-113 | Discriminator candidate F2 (trigger topology) |
| TechnologyStack | Java, Python, PHP, .NET, Ruby, and Node.js runtimes with their libraries and unmarshal entry points | 12-18, 36-40 | Non-discriminator (stability rule: procedure survives stack change) |
| DefensiveControl | Verified HMAC or encryption applied before deserialization | 129 | Falsification oracle, not a discriminator |
| DefensiveControl | Primitive-only whitelist without polymorphic types, safe loaders, JSON parsed to dict | 130-131 | Falsification oracle, not a discriminator |
| DefensiveControl | Isolated sandbox without network or exec primitives | 132 | Falsification oracle, not a discriminator |
| VulnerabilityClass | Insecure deserialization and object injection as the umbrella weakness | 8, 80-82 | Non-discriminator (shared class definition) |
| VulnerabilityClass | Named sub-forms: POP chains, Phar deserialization, ViewState forgery, unsafe YAML typing | 55-59, 72-85, 92-99 | Discriminator labels bound to F1 and F2, not separate classes |
| AttackGoal | Remote code execution, authentication bypass, and logic manipulation | 8 | Non-discriminator (impact never bends a step) |
| AttackerCapability | Ability to submit blobs, plant stored values, and operate a callback listener | 20-24, 112-113, 122-124 | Non-discriminator (runtime position; submission underlies every variant) |
| AttackTechnique | Gadget-chain assembly with OAST-gated proof (fingerprint, no-exec oracle, bounded PoC) | 46-53, 122-126, 144-149 | Discriminator candidate (V1 procedure) |
| AttackTechnique | Type-name injection with property-set construction via discriminator fields | 55-59, 92-96 | Secondary divergence inside V1, not its own variant |
| AttackTechnique | Weak-secret recovery plus signature strip plus re-signing of state blobs | 98-99, 107-110 | Discriminator candidate (V2 procedure) |
| AttackTechnique | Plant-store-trigger with delayed oracle plus phar-path reference for implicit trigger | 84-85, 112-113 | Discriminator candidate (V3 procedure) |
| AttackTechnique | Encoding layers and parameter or location switching to dodge inspection | 115-116, 137-141 | Aspect inside nearest variant; owned by future defence-bypass family |
| PayloadPattern | Chain payloads, POP payloads, reduce blobs, type-name JSON, YAML tags, ViewState blobs | 46-103 | Non-discriminating by exclusion (gadget specifics never define variants) |
| Artifact | Captured blobs, session cookies, fingerprints, recovered secrets, minted tokens | 20-34, 122-126 | Non-discriminator (runtime inputs produced or consumed by procedure) |
| ObservableSignal | Magic bytes and prefixes, stack traces, framework indicators, callbacks, forged-token acceptance | 29-40, 122-124 | Non-discriminator (acceptance channels shared by all variants) |

## 3. RDF notion map
Vuln-specific attack surface and reconnaissance: formats per runtime plus input locations plus magic-byte and white-box indicators (lines 12-40) is invariant as inventory, while which marker confirms the sink varies per variant.
Adversarial capabilities: blob submission plus stored-value planting plus callback-listener operation (lines 20-24, 112-113, 122-124) vary only as runtime position, never as procedure kind.
Common trust assumptions: every consumed blob is sender-faithful, every signature binds its blob to a strong secret, and every stored blob reaches rehydration unmodified is the invariant that each variant falsifies at a different binding.
Testing methodology: the six parent steps P1 to P6 (section 5) plus the per-runtime flows are invariant as labels, but a coarse reading that treats every sink as submit-and-observe plus pick-a-payload lumps genuinely different procedures and therefore fails the step test.
Proxy techniques: none are described in this class, so nothing is pinned here.
Defence bypass techniques: weak-secret forging, signature stripping, compression wrappers, and parameter or location switching (lines 107-116, 137-141) are per-variant oracles, with encoding layers named for the future defence-bypass family.
Techniques anti-patterns: none are named in this class, so nothing is pinned here.
Scripted tests (`references/`): none exist in the spurious skill (no `references/` directory), which is recorded as a gap rather than a discriminator.
False positives: verified HMAC, primitive whitelists, no-unmarshal parsing, sandboxing, and dead code paths (lines 129-133) are invariant rejection signals shared by all variants.
Chaining: RCE, forged sessions, and role manipulation (line 8) are invariant exit edges, with JdbcRowSetImpl-style LDAP pointers handing off to JNDI and SSRF consumers and deferred triggers handing off to batch and admin flows.

## 4. Runtime parametrisation
The concrete Service under test, the System mechanism it lies on, and the Endpoint, Parameter, Header, BaseURL, and DataItem loci where blobs are submitted, stored, or rehydrated are supplied at runtime from the attack-surface graph.
The knowledge base supplies runtime and library versions, gadget-chain inventories, HMAC-secret candidates, ViewState machine-key facts, and file-operation sink facts as runtime data.
The HTTP history supplies captured blobs, cookies, prior acceptance or rejection observations, stack traces, and immediate or delayed callback evidence.
Language choice, gadget-chain names, POP chain names, type-name strings, YAML tag spellings, secret values, claim values, and delay durations parametrise a variant and never define one.
Technology stack differences, payload wording differences, library-version differences, and concrete asset identities change tooling and encoding, never which variant procedure the agent runs.

## 5. Agent-with-skill walkthrough
The hunting circumstance is an application that consumes opaque blobs, session tokens, or structured type-tagged input at loci the agent can reach, with the unmarshal behaviour hidden behind binary formats, framework code, signatures, or deferred processing.
The agent locates decode and unmarshal sinks on user-influenced data first (P1), and the step is complete when each sink has a code or frame reference tied to an injection locus.
The agent confirms the format through markers, traces, or fingerprints next (P2), and the step is complete when the responsible deserializer and blob format are recorded.
The agent proves the sink live with a no-exec callback or delay oracle next (P3), and the step is complete when the callback or delay confirms attacker input reaches deserialization.
The agent selects or constructs the object payload matched to the fingerprinted version next (P4), and the step is complete when a chain, type name, or self-executing blob is chosen with a version rationale.
The agent demonstrates bounded execution or critical logic bypass next (P5), and the step is complete when the impact is observed with the least destructive command.
The agent prioritises server-side session stores early throughout (P6), and the step is complete when each named session locus is tested or ruled out.
STATE 2 finding preview: generic pick-a-payload language cannot describe secret recovery with re-signing, and generic submit-and-observe language cannot describe plant-then-trigger with delayed correlation.

## 6. Feature-verdict table
| Candidate feature | Accurate? | Exhaustive? | Verdict | Evidence |
|---|---|---|---|---|
| Blob trust basis F1 (unsigned graph versus signature-gated state) | No | No | Discriminator | Key recovery plus strip plus re-sign is cryptanalysis and minting, while chain matching assumes no key layer exists at all |
| Trigger topology F2 (direct versus stored-deferred versus wrapper-implicit) | No | No | Discriminator | Plant-trigger-correlate and file-op inducement are locus-splitting actions, while submit-and-observe assumes injection equals deserialization |
| Type-binding mechanism (native graph versus attacker-named type) | No (for type-tagged values) | No | Aspect | Active type-resolution probing differs from passive marker reading, yet it shares the oracle-gated proof loop, so it stays a secondary divergence inside V1 |
| Chain versus self-executing formats (inventory match versus reduce or tag directness) | No (for self-executing values) | No | Aspect | No-selection execution differs from inventory matching, yet both prove through the same gated loop, so this stays inside V1 |
| Technology stack (Java versus PHP versus Python versus .NET versus Ruby versus Node) | Yes | Yes | Non-discriminator | The same procedure replays across stacks with only generators and entry points changed, so the stack parametrises rather than bends any step |
| Gadget and POP inventory plus payload wording | Yes | Yes | Non-discriminator | PayloadPattern specifics change the bytes, never the procedure kind, per the exclusion rule |
| Encoding and compression layers | Yes | Yes | Aspect | Layering changes inside the identical submission procedure and belongs to the future defence-bypass family |
| Parameter and location switching | Yes | Yes | Aspect | Locus choice changes inside the identical procedure, never the procedure kind |
| Attack goal and impact (RCE, bypass, manipulation) | Yes (no step changes kind) | N/A | Non-discriminator | Impact never changes which action the agent performs, so Question A fails immediately |
| Observation channel (status, trace, callback, acceptance) | Yes | Yes | Non-discriminator | Acceptance reading is shared machinery, while delay is trigger topology rather than a channel difference |
| Version, secret, and claim values | Yes | Yes | Non-discriminator | Concrete values are runtime KB facts per the version-and-secret exclusion, never a procedure difference |

## 7. Step-coverage falsification
For self-executing values (pickle reduce, unsafe YAML tags), parent step P4 (match classpath or runtime version to available chains) is neither accurate nor exhaustive because no inventory matching occurs and the no-match case is unnamed, which gives V1 its span-level delta.
For attacker-named-type values (Jackson default typing, Json.NET TypeNameHandling), parent step P2 (confirm format via markers, traces, or fingerprint) is neither accurate nor exhaustive because active discriminator-field probing is a different kind of action from passive marker reading and no type-resolution probe is named.
For weak-signed values (guessable HMAC secret, weak ViewState keys), parent step P4 is neither accurate nor exhaustive because offline secret recovery with local re-verification is cryptanalysis rather than chain matching and no recovery loop is named.
For signature-strip values (unsigned fallback accepted, MAC disabled), parent steps P4 plus P5 are neither accurate nor exhaustive because validation-layer removal uses no secret at all and no keyless acceptance path is named.
For stored-deferred values (profile blob rehydrated by export, cache warm, or batch job), parent step P1 (locate unmarshal calls on user-influenced data) is neither accurate nor exhaustive because the plant locus and the trigger locus are distinct sinks and neither is named, and parent step P3 is neither accurate nor exhaustive because delayed plant-trigger correlation is a different kind of oracle from prompt submit-and-observe.
For wrapper-implicit values (phar path consumed by a file operation), parent step P1 is neither accurate nor exhaustive because the sink is a file operation rather than an unmarshal call and no implicit-deserialization sink is named.
Branch 3a check: trust basis and trigger topology do not co-vary, since signed-direct ViewState, unsigned-deferred profile blobs, and unsigned-implicit phar paths all occur independently.
Branch 3b check: chain-version granularity, secret-strength gradations, and trigger-delay durations are continuous or overlapping values, so they are recorded as aspects inside the nearest variant, never as variant axes.

## 8. Hypotheses
H1 (single-feature): if the discrimination feature is blob trust basis alone (unsigned graph versus signature-gated state), then the class yields exactly two variants (direct execution, signature forgery), and H1 is falsified if any genuine non-coverable step fits neither variant.
H2 (combined-feature): if trust basis is crossed with trigger topology (direct versus stored-deferred versus wrapper-implicit), then the grid yields three variants with the signed-deferred cell collapsing by branch 5a into sequential composition, and H2 is falsified if any cell adds its own non-coverable step beyond the three or if any genuine step is left homeless.
H3 (minimal two-way): if the only real split is direct versus indirect triggering with forgery merged into direct execution, then two variants suffice, and H3 is falsified if forgery and gadget execution each demand a distinct non-coverable step that one merged step cannot perform.
Branch 4a note: H1 is discarded because the deferred-trigger step test failures (P1, P3) have no home in either of its two variants, so H1 fails coverage.
Branch 4a note: H3 is discarded because key recovery with re-signing cannot be performed by chain assembly and matching, so the merged direct variant harbours two oracle kinds and fails coverage and disjointness.

## 9. Variant sets per hypothesis
| Hypothesis | Variant | First non-coverable step (methodology order) | Secondary divergences carried inside |
|---|---|---|---|
| H1 | deserialization-direct-execution | P4 span (chain assembly across matched and self-executing formats behind an oracle gate) | Type-named construction and format confirmation probing are aspects inside the proof loop |
| H1 | deserialization-signed-forgery | P4 (signature-layer breaking instead of chain matching) | Secret recovery tooling, claim choice, and strip-versus-resign are aspects |
| H1 | (deferred trigger homeless) | No home: P1 and P3 failures fit neither variant | STATE 6 coverage fails, so H1 loses |
| H2 | deserialization-gadget-chain | P4 span (inventory-matched chain or self-executing payload behind a no-exec oracle gate) | Native versus type-named versus self-executing construction, chain inventory choice, and session-locus priority are aspects, and stack differences are runtime |
| H2 | deserialization-signed-forgery | P4 (recover weak secret or strip signature, then mint or forge state) | Offline search tooling, Flask versus JWT versus ViewState serialization, and claim choice are aspects, and secret values are runtime KB facts |
| H2 | deserialization-deferred-trigger | P1 (plant at an injection locus and induce deserialization at a distinct trigger locus) | Stored-profile versus cache versus batch timing, delay durations, and phar-versus-storage trigger shape are aspects |
| H2 | signed-plus-deferred cell | No step of its own: forge-then-wait is sequential composition of V2 plus V3 timing | STATE 5 branch 5a test: collapses, since assignment follows the first non-coverable step in methodology order |
| H3 | deserialization-direct (forgery merged into gadget) | First non-coverable step is ambiguous between chain assembly and key recovery | STATE 5 derivation fails: local HMAC re-verification and minting cannot be performed by chain matching, so coverage fails |
| H3 | deserialization-indirect | P1 (indirect trigger pair) | Same P1 step as H2 V3, but the surviving direct variant is already incoherent, so the set fails as a whole |

## 10. Well-formedness evaluation
Coverage is critical: H2 places every genuine non-coverable step (P4-span proof loop, P4 signature breaking, P1 indirect-trigger pair with delayed oracle) in exactly one variant, while H1 leaves the deferred pair homeless and H3 leaves forgery homeless inside a merged step.
Disjointness is critical: H2 variants never share a technique, since graph-proof execution, signature-layer breaking, and plant-and-trigger each occupy one variant with first-step assignment resolving signed-deferred combos, while H3 harbours two oracle kinds in one variant.
Divergence delta is high: each H2 variant adds a named non-coverable step over the coarse parent (gated proof loop spanning self-executing formats, key-centric forgery loop, locus-splitting trigger pair), while the H2 combined cell adds none and is deleted under branch 5a.
Stability is high: all H2 variants survive changes of language, library version, gadget inventory, secret value, claim wording, and concrete asset identity.
Parsimony is medium: H2 uses two features for three variants, H1 uses one feature but fails coverage, and H3 uses one feature but fails coverage and disjointness.
H2 is the winner with full marks on coverage, disjointness, delta, and stability, plus the best parsimony among covering sets.
H1 loses on coverage because the deferred-trigger pair has no home in a trust-basis-only split.
H3 loses on coverage and disjointness because its merged direct variant fuses chain matching with key recovery.
No return to STATE 3 is needed because the winner passes both critical criteria.

## 11. Recommended set
The class-specific discrimination function is: split insecure-deserialization by the trust basis of the serialized blob crossed with the deserialization trigger topology, namely unsigned graph versus signature-gated state, and direct unmarshal versus deferred rehydration versus implicit file-operation trigger.
Recommended variant `deserialization-gadget-chain`: first non-coverable step is the P4-span proof loop (fingerprint version, gate on a no-exec oracle, assemble an inventory-matched chain or a self-executing payload, prove with a bounded command), and its divergence delta over coarse P2 plus P4 is the oracle-gated assembly spanning matched and selection-free formats that generic confirm-and-pick language never names.
Recommended variant `deserialization-signed-forgery`: first non-coverable step is P4 signature-layer breaking (recover the weak secret with local re-verification or strip the signature, then mint or forge the state blob), and its divergence delta over P4 plus P5 is the key-centric recovery and keyless-removal procedure that chain-matching language cannot express.
Recommended variant `deserialization-deferred-trigger`: first non-coverable step is the P1 indirect-trigger pair (plant the payload at an injection locus and separately induce or await deserialization at a distinct trigger with delayed oracle correlation), and its divergence delta over P1 plus P3 is the locus-splitting plant-and-trigger sequence that submit-and-observe language never names.
Non-discriminators are TechnologyStack in full, concrete Service, System, Endpoint, Parameter, Header, BaseURL, DataItem, HTTP history, gadget and payload wording, version and secret and claim values, attack goal and impact, acceptance observation channels, and tester tooling, each for the reasons recorded in section 6.
Aspects (not variants) are native versus type-named versus self-executing construction inside the gadget chain, serialization and claim choice inside signed forgery, trigger shape and delay durations inside deferred trigger, and encoding layers plus parameter switching inside the nearest variant.
Cross-references owned elsewhere are offline secret-search mechanics (crypto-weakness), authorization consequences of forged sessions and roles (two-principal-authz), JNDI and LDAP egress consequences (ssrf and rce consumers), and encoding-layer bypass mechanics (the future defence-bypass family).
Open questions: whether administered batch-job triggers need a dedicated trigger matrix once the class documents per-scheduler inducement, since the current skill names batch jobs once without a procedure.
Grey points: Phar sits inside deferred trigger by trigger affinity though its payload is gadget content, with first-step assignment resolving any dispute toward V3; type-named construction stays inside the gadget chain under the PayloadPattern exclusion until type probing grows an oracle loop of its own; signed-plus-deferred combos assign by first non-coverable step (forgery first toward V2, trigger pair first toward V3); ViewState key recovery hands the brute-force sub-step to crypto-weakness rather than restating it.
FAIL-level uncertainty: none, since every recommended variant traces to named ontology entity values and named failing parent steps with positive divergence delta.
