# xxe - variant decomposition analysis

## 1. Class and scope

This analysis decomposes the `xxe` class from `skills-unspurious/xxe/SKILL.md`.
The class covers parser-level external entity resolution plus transclusion plus OOB exfiltration plus expansion effects across every XML consumer.
STATE 1 inventory below confirms the class is well formed because it carries five methodology steps and pinnable ontology values.

## 2. Ontology entity ledger

STATE 1 pins every methodology entity value from the skill text before any verdict is drawn.

| Entity type | Value(s) | Source lines | Role |
|---|---|---|---|
| PreconditionEnvironment | XML consumer present; DOCTYPE accepted; external general-entity resolution enabled; external parameter-entity and DTD fetch enabled; network egress allowed versus blocked; XInclude processing enabled; XSLT transformer reachable; OOXML or SVG implicit parse path; background processor with distinct parser options; SAML ACS parse before signature check | 17, 18, 19, 22, 24, 29, 62, 111, 121, 143, 156, 162 | Discriminator candidate |
| TechnologyStack | XML parser libraries and stacks; SOAP and SAML and XML-RPC and WebDAV; SVG renderers and OOXML and PDF generators and report pipelines; XSLT engines including Jasper and FOP; wrapper schemes including jar and netdoc and php filter and expect and gopher | 18, 19, 26, 30, 130, 136, 137 | Non-discriminator |
| DefensiveControl | Forbid DOCTYPE; disable external entity resolution; disable network access for processors and transformers; disable XInclude and XSLT document loading; WAF DOCTYPE blocking; sandbox literal emission | 119, 150, 186, 190 | Non-discriminator |
| VulnerabilityClass | XML external entity injection | 6, 8 | Non-discriminator |
| AttackGoal | Local file disclosure; internal SSRF and metadata read; denial of service through expansion; code execution through XSLT or language wrappers | 8, 12, 13, 14, 15 | Non-discriminator alone, DoS value collapsed per STATE 3 |
| AttackerCapability | Submit XML to endpoints; upload SVG and Office documents; operate attacker-controlled callback host; reach transform endpoints | 18, 31, 48, 130, 162 | Non-discriminator |
| AttackTechnique | General-entity in-band resolution; parameter-entity OOB chain; XInclude href transclusion; XSLT document transclusion; error-message coercion; timing inference; encoding and DOCTYPE evasion | 38, 42, 46, 50, 80, 106, 111, 121, 148, 152 | Discriminator candidate |
| PayloadPattern | General-entity DOCTYPE pattern; parameter-entity external DTD pattern with two-stage exfil chain; XInclude element pattern; XSLT stylesheet pattern; encoding and case and subset shape families | 58, 68, 80, 111, 123, 148, 152 | Aspect inside variants |
| Artifact | Attacker-hosted external DTD; OAST callback hit; disclosed file content; error fragment; transformed output | 38, 48, 86, 164 | Non-discriminator |
| ObservableSignal | Inline disclosure versus error leak versus OAST callback versus length and ETag difference versus latency difference | 36, 41, 46, 51, 164 | Discriminator candidate collapsed in STATE 3 |

## 3. RDF notion map

Attack surface and reconnaissance hold REST plus SOAP plus SAML plus XML-RPC plus uploads plus pipelines plus converters plus background jobs, and consumer locus stays invariant while parser capability varies.
Adversarial capabilities hold XML submission plus file upload plus callback operation plus transformer reach, and all four stay invariant across variants.
Common trust assumptions hold that DOCTYPE rejection is uniform plus entity resolution is off everywhere plus network is closed for processors plus transclusion is off, and each assumption varies by consumer and background path.
Testing methodology holds consumer inventory plus capability probes plus oracle establishment plus targeted escalation plus cross-channel parity, and oracle plus escalation steps vary as section 7 shows.
Proxy techniques hold gateway and pipeline hops that forward attacker XML into interior parsers, and this forwarding step is named here without its own variant.
Defence bypass techniques hold encoding variants plus DOCTYPE shape variants plus network-versus-file pivots, and all three families stay invariant as aspects inside variants.
Techniques anti-patterns hold literal entity echo without IO plus client-side-only parse plus mock success without access, and all three stay invariant as stop conditions.
Scripted tests hold none because the unspurious skill ships no references suite.
False positives hold DOCTYPE accepted without resolution plus sandbox literal emission plus mock success plus client-side-only processing, and all four stay invariant as stop conditions.
Chaining holds XML file read into path traversal plus SSRF into metadata use plus wrapper into deserialization, and each chain varies by downstream sink.

## 4. Runtime parametrisation

The concrete Service under test arrives at runtime from the L1 graph and only scopes which business function owns the XML consumer.
The concrete System arrives at runtime and only records which parser or transformer mechanism serves the consumer.
The concrete Endpoint arrives at runtime and only locates the injectable XML surface.
The concrete Parameter arrives at runtime and only names the carrier that holds the XML body or upload.
The concrete DataItem arrives at runtime and only types the destination value flowing into the parser.
The concrete BaseURL arrives at runtime and only anchors relative DTD and stylesheet resolution.
The concrete Header arrives at runtime and only carries content type plus processing-instruction evidence.
The HTTP history arrives at runtime and only supplies the observed request plus response plus callback sequence for reconstruction.

## 5. Agent-with-skill walkthrough

An agent hunts REST endpoints plus SOAP actions plus SAML ACS plus upload converters plus report pipelines after the L1 graph has assigned those consumers to services.
STATE 1 lists the parent methodology steps S1 to S5 exactly as the skill writes them.
S1 inventories consumers across endpoints plus uploads plus background jobs plus converters plus third-party SDKs, and it completes when every XML parsing sink is listed with its carrier.
S2 probes capabilities across DOCTYPE acceptance plus external entity resolution plus network access plus XInclude and XSLT support, and it completes when each capability answer is recorded per consumer.
S3 establishes oracle across error shape plus length and ETag diffs plus OAST callbacks, and it completes when the observable channel for that consumer is fixed and correlated.
S4 escalates with targeted file and SSRF payloads, and it completes when a controlled file path or internal URL shows reproducible access evidence.
S5 validates parity across REST plus SOAP plus SAML plus uploads plus background jobs, and it completes when every channel shows the same parser options or a recorded divergence.
STATE 1 Branch 1a does not trigger because five methodology steps exist.

## 6. Feature-verdict table

STATE 2 runs the two-half test for every candidate feature below.

| Feature | Accurate | Exhaustive | Verdict | Evidence |
|---|---|---|---|---|
| PreconditionEnvironment external DTD fetch enabled versus disabled | No | No | Discriminator | S4 file and SSRF fetch performs a different kind than two-stage DTD-chain exfil |
| AttackTechnique parameter-entity OOB chain | No | No | Discriminator | S4 single-payload fetch misses attacker-DTD hosting plus two-stage sequencing |
| AttackTechnique XInclude href transclusion | No | No | Discriminator | S4 DOCTYPE entity injection misses namespace-aware include-element craft with no DOCTYPE |
| AttackTechnique XSLT document transclusion | No | No | Discriminator carried with XInclude per STATE 3 | S4 misses stylesheet submission to a transformer with document fetch semantics |
| AttackTechnique nested-entity expansion | No | No | Discriminator | S4 fetch-oriented injection misses amplification definition with no external target |
| ObservableSignal inline versus error versus OAST versus diff versus latency | Covaries | No | Discriminator collapsed | Each signal value implies exactly one oracle plus escalation pairing per STATE 3 |
| AttackGoal file versus SSRF choice | Yes | Yes | Aspect | S4 targeted payloads cover file and SSRF selection without changing step kind |
| AttackGoal denial of service | Covaries | No | Discriminator collapsed | DoS value implies exactly the nested-expansion procedure per STATE 3 |
| PayloadPattern encoding and DOCTYPE shape families | Yes | Yes | Aspect | S2 plus S4 enumerate shapes without changing step kind |
| PayloadPattern wrapper scheme choice | Yes | Yes | Aspect | Scheme selection rides inside file and SSRF craft without bending a step |
| TechnologyStack parser library and platform and version | Yes | Yes | Non-discriminator | Library and platform change payloads without changing step kind |
| DefensiveControl kind alone | Yes | Yes | Non-discriminator | Control kind rides on parser capability rather than standing alone |
| VulnerabilityClass XXE itself | Yes | Yes | Non-discriminator | Single class under analysis cannot split itself |
| AttackerCapability submission and upload and callback operation | Yes | Yes | Non-discriminator | Shared preconditions hold across all variants |
| Artifact DTD and callback hit and disclosed content | Yes | Yes | Non-discriminator | Evidence objects are produced by every variant alike |
| PreconditionEnvironment container embedding SOAP versus SAML versus SVG versus OOXML | Yes | Yes | Aspect | S1 plus S5 cover placement and parity without changing step kind |

## 7. Step-coverage falsification

STATE 3 records the failing parent step and the uncovered reality for each discriminating value.
Blind parameter-entity OOB fails S4 because the parent targeted file and SSRF description cannot describe attacker-hosted DTD delivery plus external subset inclusion plus file read plus redefinition plus DNS-path exfil sequencing.
S3 OAST callback watching covers the listener half of blind confirmation, so S3 is carried as secondary oracle correlation inside the blind variant.
XInclude transclusion fails S4 because the parent DOCTYPE entity description cannot describe include-element injection with href fetch semantics and no DOCTYPE at all.
XSLT transclusion fails S4 in the same step because the parent description cannot describe full stylesheet submission with document fetch against transform endpoints and reporting engines.
STATE 3 Branch 3a carries XSLT inside the transclusion variant because stylesheet submission adds transclusion craft but no separate non-coverable step beyond consumer inventory already in S1.
Entity-expansion denial of service fails S3 because the parent error plus length plus OAST oracle description cannot describe CPU plus memory plus timeout exhaustion observation.
Expansion also fails S4 because the parent file and SSRF description cannot describe nested entity amplification with no external fetch target.
Direct general-entity disclosure stretches nothing because S3 plus S4 describe inline plus error plus diff confirmation with single-payload file and SSRF semantics.
Container placement across SOAP plus SAML plus SVG plus OOXML fails nothing because S1 plus S5 describe consumer inventory plus parity validation with repackaging as one procedure.
Encoding and DOCTYPE shape families fail nothing because S2 plus S4 cover declarations plus case plus PUBLIC versus SYSTEM plus subset choice with the same probe-and-send actions.
Outlier: SAML assertion parse-before-signature ordering belongs to the authentication and SAML family and is named here without a variant.
Outlier: Gateway and pipeline interior forwarding belongs to proxy-technique handling and is named here without a variant.
Outlier: WAF DOCTYPE evasion craft belongs to the `defence-bypass` family and is named here without a variant.
Outlier: Downstream path traversal and deserialization use of disclosed content belongs to those skills and is named here without a variant.

## 8. Hypotheses

STATE 4 states two single-feature hypotheses plus one combined hypothesis.
H1 predicts that resolution mechanism alone splits the class into in-band entity disclosure plus transclusion without entity resolution.
H1 is falsified if blind OOB exfiltration or expansion exhaustion needs a non-coverable step beyond resolution craft, which section 7 confirms for S4 DTD chains and S3 exhaustion.
H2 predicts that observability alone splits the class into direct disclosure plus blind OOB exfiltration.
H2 is falsified if transclusion or expansion needs a non-coverable step beyond oracle handling, which section 7 confirms for S4 include and document craft and S3 exhaustion.
H3 predicts that mechanism crossed with observability plus expansion effect yields blind parameter-entity OOB exfiltration plus transclusion without entity resolution plus entity-expansion denial of service, with direct general-entity disclosure as the parent baseline.
H3 is falsified if any product cell lacks its own non-coverable step or if two cells share all steps, which section 9 tests.
STATE 3 Branch 3a collapses ObservableSignal into technique and pairing because each signal value implies exactly one oracle plus escalation combination.
STATE 3 Branch 3a collapses AttackGoal denial of service into expansion technique because the goal value implies exactly the nested-expansion procedure.
STATE 3 Branch 3b keeps encoding plus DOCTYPE shapes plus wrapper choice plus container placement as aspects because their values have no clean procedural partition.

## 9. Variant sets per hypothesis

STATE 5 derives one variant set per surviving hypothesis, and each variant is named by its first non-coverable parent step.

| Hypothesis | Variant | First non-coverable parent step | Secondary divergences carried inside |
|---|---|---|---|
| H1 mechanism only | in-band-entity-disclosure | S4 escalate | File plus SSRF selection with direct oracle as secondary |
| H1 mechanism only | transclusion-without-entity-resolution | S4 escalate | XInclude href craft plus XSLT document craft with transformer inventory as secondary |
| H2 observability only | direct-disclosure | S4 escalate | Inline plus error plus diff confirmation of file and SSRF reads |
| H2 observability only | blind-parameter-entity-oob-exfiltration | S4 escalate | DTD hosting plus two-stage chain plus OAST correlation as secondary |
| H3 combined | blind-parameter-entity-oob-exfiltration | S4 escalate | DTD hosting plus two-stage chain plus DNS-path exfil with OAST correlation as secondary |
| H3 combined | transclusion-without-entity-resolution | S4 escalate | XInclude href plus XSLT document craft where entities are blocked |
| H3 combined | entity-expansion-denial-of-service | S3 oracle | Nested entity amplification plus exhaustion observation with minimal-payload discipline |

Branch 5a emits no separate XSLT variant because stylesheet submission adds no non-coverable step beyond S4 transclusion craft plus S1 consumer inventory carried as secondary.
Branch 5a emits no blind-transclusion product because blind include fetch adds no step beyond S4 transclusion craft plus OAST watching carried as secondary.
Branch 5a scopes transclusion and blind variants to their S4 craft because S2 probe wording already covers capability detection for both.
In-band direct disclosure carries no delta over the parent in every hypothesis and is deleted as the baseline wherever it appears.

## 10. Well-formedness evaluation

STATE 6 scores each set with weights Coverage critical plus Disjointness critical plus Divergence delta high plus Stability high plus Parsimony medium.
H1 covers in-band plus transclusion yet leaves S4 DTD-chain exfiltration and S3 exhaustion observation homeless inside generic escalation, so Coverage fails and Disjointness passes and Delta passes and Stability passes and Parsimony passes.
H2 covers direct plus blind yet leaves S4 include and document craft and S3 exhaustion homeless inside generic oracle handling, so Coverage fails and Disjointness passes and Delta passes and Stability passes and Parsimony fails.
H3 covers S4 DTD-chain craft plus S4 transclusion craft plus S3 exhaustion observation with exactly one home per non-coverable step, so Coverage passes and Disjointness passes and Delta passes and Stability passes and Parsimony passes.
H1 loses because blind OOB sequencing and expansion exhaustion have no home outside resolution mechanism.
H2 loses because transclusion craft and expansion exhaustion have no home outside observability.
H3 wins because every genuine divergence from section 7 owns exactly one variant and survives runtime and payload changes.
Branch 6a does not trigger because the winner passes Coverage and Disjointness.
Branch 6b carries H3 forward to recommendation.

## 11. Recommended set

STATE 7 states the class-specific discrimination function in one sentence.
XXE discriminates by parser resolution path crossed with exfiltration observability plus expansion effect, namely in-band general-entity disclosure as the parent baseline versus blind parameter-entity OOB exfiltration versus transclusion without entity resolution versus entity-expansion denial of service.
Variant `blind-parameter-entity-oob-exfiltration` grounds in S4 escalate failure and adds attacker-DTD hosting plus two-stage chain plus DNS-path exfil plus OAST request correlation.
Variant `transclusion-without-entity-resolution` grounds in S4 escalate failure and adds include href craft plus XSLT document submission that succeed where entity resolution is blocked.
Variant `entity-expansion-denial-of-service` grounds in S3 oracle failure plus S4 escalate failure and adds nested entity amplification plus exhaustion observation with minimal-payload discipline.
Direct general-entity file and SSRF disclosure remains the parent baseline and is not emitted as a variant because it adds no non-coverable step.
Container placement plus encoding shapes plus wrapper choice plus file-versus-SSRF selection remain aspects inside every variant.
Non-discriminators are TechnologyStack runtime plus DefensiveControl kind alone plus VulnerabilityClass itself plus AttackGoal file-versus-SSRF alone plus AttackerCapability preconditions plus PayloadPattern shape families plus Artifact evidence plus container name alone.
Grey point: blind XInclude fetch with OAST confirmation is carried inside the transclusion variant although its oracle comes from the blind variant.
Grey point: error-coerced exfiltration is carried across classic baseline and blind variant although parameter entities can serve both channels.
Grey point: XSLT code execution through expect and wrappers touches the RCE skill boundary and is carried here as document-fetch impact only.
Open question: whether stylesheet-driven code execution deserves separation from document-fetch transclusion when transformer impact diverges further.
FAIL-level uncertainty: none, because every recommended variant traces to a named step failure with a positive delta and disjoint evidence.
