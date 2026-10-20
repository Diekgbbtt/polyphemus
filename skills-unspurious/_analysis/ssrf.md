# ssrf - variant decomposition analysis

## 1. Class and scope

This analysis decomposes the `ssrf` class from `skills-unspurious/ssrf/SKILL.md`.
The class covers server-side fetches that an attacker steers toward internal networks plus cloud metadata plus translated protocols plus header-gated targets.
STATE 1 inventory below confirms the class is well formed because it carries eight methodology steps and pinnable ontology values.

## 2. Ontology entity ledger

STATE 1 pins every methodology entity value from the skill text before any verdict is drawn.

| Entity type | Value(s) | Source lines | Role |
|---|---|---|---|
| PreconditionEnvironment | User-influenced server fetch sink present; direct response channel versus no-response egress; internal address space with metadata reachable; non-HTTP scheme handler support; redirect-following fetcher with pre-redirect allowlist | 12, 18, 59, 87, 102, 105 | Discriminator candidate |
| TechnologyStack | Fetcher libraries and clients; protocol translators for PDF and image and document paths; cloud and Kubernetes platforms; internal Redis and FastCGI and Docker and search stores | 16, 27, 40, 99, 123 | Non-discriminator |
| DefensiveControl | Scheme and host allowlist; encoding blocklist; DNS pinning; redirect-following restriction; header and method restriction with metadata token and flavor requirements | 59, 69, 79, 83, 114 | Non-discriminator |
| VulnerabilityClass | Server-side request forgery | 6, 8 | Non-discriminator |
| AttackGoal | Cloud credential disclosure; internal service discovery; lateral movement into orchestration; command execution through protocol abuse | 8, 96, 97, 98 | Non-discriminator |
| AttackerCapability | Supply URL and host and path input; operate callback infrastructure for confirmation; induce server-side fetch through direct and indirect sources | 18, 21, 89, 105 | Non-discriminator |
| AttackTechnique | No-response egress inference; scheme-translated smuggling; header-gated and method-gated cloud read; parser-differential evasion; redirect-chain abuse; internal address probing | 39, 47, 53, 59, 64, 87 | Discriminator candidate |
| PayloadPattern | Address encoding families in decimal and hex and octal and IPv6-mapped forms; URL confusion with userinfo and fragment and scheme-less and trailing-dot forms; wrapper schemes for file and gopher and dict; redirect chains with protocol switches | 47, 53, 59, 69, 79, 83 | Aspect inside variants |
| Artifact | Callback hit with per-payload token; response length and ETag and TLS difference; cloud credential and token object; port map from timeout search | 89, 93, 98, 126 | Non-discriminator |
| ObservableSignal | Direct response body versus callback hit versus timing and size and TLS and ETag difference | 89, 93, 126, 129 | Discriminator candidate collapsed in STATE 3 |

## 3. RDF notion map

Attack surface and reconnaissance hold outbound fetchers plus indirect preview and job sources plus protocol translators plus resolver and crawler sinks, and sink locus stays invariant while handler support varies.
Adversarial capabilities hold URL input supply plus callback operation plus server-fetch inducement, and all three stay invariant across variants.
Common trust assumptions hold allowlist correctness after canonical parse plus first-hop constrains later hops plus scheme restriction holds plus response visibility reflects reachability, and each assumption varies by fetcher and handler.
Testing methodology holds surface inventory plus oracle plus addressing plus protocol plus parser plus redirect plus header control plus high-value targeting, and oracle plus protocol plus header steps vary as section 7 shows.
Proxy techniques hold gateway and sidecar hops that forward attacker URLs into interior services, and this forwarding step is named here without its own variant.
Defence bypass techniques hold address encoding plus DNS rebinding plus parser differentials plus redirect chains, and all four families stay invariant as aspects inside variants.
Techniques anti-patterns hold client-only fetch confusion plus canned simulator responses plus tester-machine callback misattribution plus uniform-error misreading, and all four stay invariant as stop conditions.
Scripted tests hold none because the unspurious skill ships no references suite.
False positives hold client-side fetch only plus strict allowlist with DNS pinning plus simulator without egress plus uniform errors plus tester-source callbacks, and all five stay invariant as stop conditions.
Chaining holds metadata credential to cloud API use plus Redis and FastCGI and Docker to shell plus kubelet and API to lateral movement, and each chain varies by request capability.

## 4. Runtime parametrisation

The concrete Service under test arrives at runtime from the L1 graph and only scopes which business function owns the fetch sink.
The concrete System arrives at runtime and only records which fetcher mechanism serves the sink.
The concrete Endpoint arrives at runtime and only locates the injectable fetch surface.
The concrete Parameter arrives at runtime and only names the carrier that holds the URL or host or path.
The concrete DataItem arrives at runtime and only types the destination value flowing into the fetcher.
The concrete BaseURL arrives at runtime and only anchors scheme-less and relative resolution.
The concrete Header arrives at runtime and only carries location plus forwarding plus metadata-gating evidence.
The HTTP history arrives at runtime and only supplies the observed request and redirect sequence for reconstruction.

## 5. Agent-with-skill walkthrough

An agent hunts previewers plus importers plus webhook testers plus renderers plus resolvers after the L1 graph has assigned those endpoints to services.
STATE 1 lists the parent methodology steps S1 to S8 exactly as the skill writes them.
S1 inventories surfaces across web plus mobile plus API plus background jobs, and it completes when every user-influenced URL and host and path sink is listed with its carrier.
S2 establishes oracle with quiet callback infrastructure first, and it completes when a per-payload token is minted and the listener outcome is recorded.
S3 pivots to internal addressing across loopback plus RFC1918 plus link-local plus IPv6 plus hostnames, and it completes when each address family has been sent and the response class recorded.
S4 tests protocol variations across gopher plus file plus dict where supported, and it completes when each supported handler has been exercised or its absence recorded.
S5 tests parser differentials across frameworks plus CDNs plus language libraries, and it completes when enforcing-side parse and fetching-side outcome are both recorded.
S6 tests redirect behavior across single-hop plus multi-hop plus protocol switches, and it completes when every hop target and switch outcome is recorded.
S7 tests header and method control, and it completes when the influence over request headers and method is recorded as present or absent.
S8 targets high-value assets across metadata plus kubelet plus Redis plus FastCGI plus Docker plus Vault plus admin panels, and it completes when each reachable target shows a minimal read or a recorded negative.
STATE 1 Branch 1a does not trigger because eight methodology steps exist.

## 6. Feature-verdict table

STATE 2 runs the two-half test for every candidate feature below.

| Feature | Accurate | Exhaustive | Verdict | Evidence |
|---|---|---|---|---|
| PreconditionEnvironment egress visibility direct versus no-response | No | No | Discriminator | S2 callback watch performs a different kind than timing and size and TLS inference |
| AttackTechnique scheme translation HTTP only versus gopher and file and dict | No | No | Discriminator | S4 generic handler test misses raw-protocol grammar crafting |
| AttackTechnique header and method influence absent versus controlled | Yes | No | Discriminator | S7 single-fetch question misses token-then-read gated sequence |
| AttackTechnique parser-differential evasion | Yes | Yes | Aspect | S5 submit-and-compare covers all framework and library pairs |
| AttackTechnique redirect-chain abuse alone | Yes | Yes | Aspect | S6 single-hop and multi-hop and switch testing covers chain depth |
| AttackTechnique internal address probing across ranges | Yes | Yes | Aspect | S3 loopback plus RFC1918 plus link-local plus IPv6 covers range choice |
| PayloadPattern address encoding and URL confusion families | Yes | Yes | Aspect | S3 plus S5 enumerate forms without changing step kind |
| TechnologyStack fetcher library and platform and version | Yes | Yes | Non-discriminator | Library and platform change payloads without changing step kind |
| DefensiveControl allowlist and pinning and method restriction alone | Yes | Yes | Non-discriminator | Control kind rides on sink capability rather than standing alone |
| VulnerabilityClass SSRF itself | Yes | Yes | Non-discriminator | Single class under analysis cannot split itself |
| AttackGoal credential versus discovery versus execution | Yes | Yes | Non-discriminator | Impact follows request capability and never bends a step by itself |
| AttackerCapability input supply and callback operation | Yes | Yes | Non-discriminator | Shared preconditions hold across all variants |
| Artifact callback hit and diff and token and port map | Yes | Yes | Non-discriminator | Evidence objects are produced by every variant alike |
| ObservableSignal callback versus timing and size and TLS diff | Covaries | No | Discriminator collapsed | Signal value implies exactly one egress visibility value per STATE 3 |

## 7. Step-coverage falsification

STATE 3 records the failing parent step and the uncovered reality for each discriminating value.
No-response egress fails S2 because the parent quiet-callback description cannot describe per-token correlation plus timing and size and TLS and ETag differencing plus timeout binary search port mapping.
Scheme-translated smuggling fails S4 because the parent handler-variation description cannot describe raw text-protocol grammar crafting for Redis cron plus SMTP plus FastCGI record building.
Scheme-translated file read fails S4 because the parent variation description cannot describe wrapper-enabled local file semantics distinct from network fetch semantics.
Header-gated cloud read fails S7 because the parent influence question cannot describe a PUT token fetch followed by an authenticated metadata GET.
Method-gated cloud read fails S7 plus S8 because the parent generic high-value targeting cannot describe IMDSv2 and flavor-gated flows that require a specific method and header pair.
Direct HTTP addressing stretches nothing because S3 plus S8 describe loopback and RFC1918 and link-local and IPv6 selection with plain GET semantics.
Parser families fail nothing because S5 covers every canonicalization pair with the same submit-and-compare actions.
Redirect depth alone fails nothing because S6 already covers single-hop and multi-hop and switch chains as one procedure.
Outlier: GraphQL resolver fetching by URL belongs to the graphql family and is named here without a variant.
Outlier: Gateway and sidecar interior forwarding belongs to proxy-technique handling and is named here without a variant.

## 8. Hypotheses

STATE 4 states two single-feature hypotheses plus one combined hypothesis.
H1 predicts that egress visibility alone splits the class into direct-response mapping plus no-response inference.
H1 is falsified if scheme translation or header gating needs a non-coverable step beyond oracle handling, which section 7 confirms for S4 and S7.
H2 predicts that request expressive power alone splits the class into plain HTTP addressing plus scheme-translated command plus header-gated cloud read.
H2 is falsified if no-response inference needs a non-coverable oracle step beyond request construction, which section 7 confirms for S2.
H3 predicts that visibility crossed with expressive power yields no-response inference plus direct scheme-translated command plus direct header-gated cloud read, with plain direct HTTP as the parent baseline.
H3 is falsified if any product cell lacks its own non-coverable step or if two cells share all steps, which section 9 tests.
STATE 3 Branch 3a collapses ObservableSignal into egress visibility because each signal value implies exactly one visibility value.
STATE 3 Branch 3b keeps parser families plus redirect depth plus address ranges as aspects because their values have no clean procedural partition.

## 9. Variant sets per hypothesis

STATE 5 derives one variant set per surviving hypothesis, and each variant is named by its first non-coverable parent step.

| Hypothesis | Variant | First non-coverable parent step | Secondary divergences carried inside |
|---|---|---|---|
| H1 visibility only | direct-response-mapping | S3 addressing | Range selection plus parser forms plus redirect depth plus direct high-value reads |
| H1 visibility only | no-response-egress-inference | S2 oracle | Timeout port mapping plus ETag and TLS differencing plus per-token correlation |
| H2 expressive power only | plain-http-internal-mapping | S3 addressing | Range selection plus direct high-value reads with tight timeouts |
| H2 expressive power only | scheme-translated-command-execution | S4 protocol | Gopher grammar crafting plus file wrapper reads plus dict probing |
| H2 expressive power only | header-gated-cloud-credential-read | S7 header control | Token-then-read sequencing plus flavor-gated GET plus method pairing |
| H3 combined | no-response-egress-inference | S2 oracle | All blind cases including blind-translated and blind-gated as secondary craft |
| H3 combined | scheme-translated-command-execution direct-only | S4 protocol | Gopher and file and dict craft with direct oracle as secondary |
| H3 combined | header-gated-cloud-credential-read direct-only | S7 header control | Token-then-read plus flavor-gated flows with direct oracle as secondary |

Branch 5a emits no blind-translated product because blind craft adds no step beyond S2 inference plus S4 craft carried as secondary.
Branch 5a emits no blind-gated product because blind gating adds no step beyond S2 inference plus S7 sequencing carried as secondary.
Branch 5a scopes translated and gated variants to direct oracle by first-failure order because S2 precedes S4 and S7 in methodology order.

## 10. Well-formedness evaluation

STATE 6 scores each set with weights Coverage critical plus Disjointness critical plus Divergence delta high plus Stability high plus Parsimony medium.
H1 covers direct plus blind yet leaves S4 grammar crafting and S7 token sequencing homeless inside generic oracle handling, so Coverage fails and Disjointness passes and Delta passes and Stability passes and Parsimony passes.
H2 covers plain plus translated plus gated yet leaves S2 timing and TLS inference duplicated as an undocumented aspect inside every variant, so Coverage fails and Disjointness passes and Delta passes and Stability passes and Parsimony fails.
H3 covers S2 inference plus S4 craft plus S7 sequencing with exactly one home per non-coverable step and with blind craft carried by order rule, so Coverage passes and Disjointness passes and Delta passes and Stability passes and Parsimony passes.
H1 loses because protocol smuggling and header-gated sequencing have no home outside oracle visibility.
H2 loses because no-response statistical inference has no home outside request construction.
H3 wins because every genuine divergence from section 7 owns exactly one variant and survives runtime and payload changes.
Branch 6a does not trigger because the winner passes Coverage and Disjointness.
Branch 6b carries H3 forward to recommendation.

## 11. Recommended set

STATE 7 states the class-specific discrimination function in one sentence.
SSRF discriminates by server egress observability crossed with server request expressive power, namely no-response inference versus scheme-translated command versus header-gated cloud read.
Variant `no-response-egress-inference` grounds in S2 oracle failure and adds per-token callback correlation plus timing and size and TLS and ETag differencing plus timeout binary-search port mapping.
Variant `scheme-translated-command-execution` grounds in S4 protocol failure and adds raw-protocol grammar crafting plus wrapper-aware file reads scoped to direct oracle.
Variant `header-gated-cloud-credential-read` grounds in S7 header-control failure and adds token-then-read sequencing plus flavor-gated GET flows scoped to direct oracle.
Plain direct HTTP internal mapping remains the parent baseline and is not emitted as a variant because it adds no non-coverable step.
Parser differentials plus redirect chains plus address encoding families remain aspects inside every variant.
Non-discriminators are TechnologyStack runtime plus DefensiveControl kind alone plus VulnerabilityClass itself plus AttackGoal impact alone plus AttackerCapability preconditions plus PayloadPattern families plus Artifact evidence plus high-value target name alone.
Grey point: blind-translated command attribution is carried inside the inference variant although its payload grammar comes from the translated variant.
Grey point: redirect-to-metadata chains are carried as redirect aspects although an allowlisted redirector can be the entry into any of the three variants.
Grey point: IPv6-mapped and mixed-notation forms stretch S3 wording and are carried as an addressing aspect by rewriting the range list.
Open question: whether file-wrapper reads deserve separation from gopher command craft inside the translated variant when wrapper semantics diverge further.
FAIL-level uncertainty: none, because every recommended variant traces to a named step failure with a positive delta and disjoint evidence.
