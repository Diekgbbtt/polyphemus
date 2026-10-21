# open-redirect - variant decomposition analysis

## 1. Class and scope

This analysis decomposes the `open-redirect` class from `skills-unspurious/open-redirect/SKILL.md`.
The class covers redirect targets that an attacker can steer to an external or unintended destination across server 3xx, client navigation, OAuth relay, and fetcher chains.
STATE 1 inventory below confirms the class is well formed because it carries five methodology steps and pinnable ontology values.

## 2. Ontology entity ledger

| Entity type | Value(s) | Source lines | Role |
|---|---|---|---|
| PreconditionEnvironment | User-controllable redirect destination; OAuth redirect flow present; client navigation sink reachable; server fetcher follows redirects | 19, 29, 39, 84, 96, 100 | Discriminator candidate |
| TechnologyStack | HTTP 3xx Location; browser navigation and SPA router; OAuth OIDC SAML; reverse proxy and gateway and CDN; server-side fetcher | 12, 17, 20, 81, 91, 96 | Non-discriminator |
| DefensiveControl | Exact origin allowlist after canonical parse; relative same-origin constraint; exact pre-registered redirect URI verifier; user confirmation prompt | 69, 108, 109, 111 | Non-discriminator |
| VulnerabilityClass | Open redirect | 6, 8 | Non-discriminator |
| AttackGoal | Phishing navigation; OAuth code and token interception; allowlist bypass with internal egress | 8, 96, 104 | Non-discriminator |
| AttackerCapability | Supply redirect target input; operate callback endpoint; induce victim navigation for phishing | 29, 96, 104 | Non-discriminator |
| AttackTechnique | Parser-differential allowlist evasion; OAuth registration relay abuse; client sink injection; multi-hop relay abuse; redirector to fetcher pivot | 35, 56, 75, 86, 96 | Discriminator candidate |
| PayloadPattern | Userinfo and slash and whitespace and fragment and unicode families; double encoding and scheme smuggling; numeric IP forms; nested redirector URL | 35, 49, 53, 56, 111 | Aspect inside variants |
| Artifact | Attacker callback URL; intercepted code or token; redirect chain trace; fetcher egress response | 96, 104, 111, 119 | Non-discriminator |
| ObservableSignal | Browser address bar reaches external domain; Location header points externally; code arrives at attacker endpoint; fetcher egress reaches internal target | 45, 96, 104, 111 | Discriminator candidate collapsed in STATE 3 |

## 3. RDF notion map

Attack surface and reconnaissance hold server 3xx sinks plus client sinks plus OAuth parameters plus redirector chains plus parser-differential injection points.
Adversarial capabilities hold input supply plus callback operation plus victim inducement, and all three stay invariant across variants.
Common trust assumptions hold allowlist correctness plus first-hop constrains later hops plus registration constrains relay plus fetcher stays safe, and each assumption varies by sink and consumer.
Testing methodology holds inventory plus matrix plus comparator plus multi-hop plus impact proof, and the comparator and relay and egress steps vary as section 7 shows.
Proxy techniques hold reverse proxy header construction plus gateway absolute URL building, and this step is owned by the header-injection family and is only named here.
Defence bypass techniques hold userinfo and slash and whitespace and fragment and unicode and encoding bypasses, and the families stay invariant as matrix aspects.
Techniques anti-patterns hold substring checks plus wildcard overreach plus missing scheme pinning plus case drift, and all four stay invariant across variants.
Scripted tests hold none because the skill ships no references suite.
False positives hold relative-only paths plus exact registered URIs plus single canonical parser plus explicit user prompt, and all four stay invariant as stop conditions.
Chaining holds OAuth code relay plus redirector to fetcher pivot plus multi-hop escape, and each chain varies by sink and consumer.

## 4. Runtime parametrisation

The concrete Service under test arrives at runtime from the L1 graph and only scopes which business function owns the sink.
The concrete System arrives at runtime and only records which mechanism serves the sink.
The concrete Endpoint arrives at runtime and only locates the redirector surface.
The concrete Parameter arrives at runtime and only names the injectable destination carrier.
The concrete DataItem arrives at runtime and only types the destination value flowing into the sink.
The concrete BaseURL arrives at runtime and only anchors relative resolution and allowlist comparison.
The concrete Header arrives at runtime and only carries Location plus Host plus forwarding evidence.
The HTTP history arrives at runtime and only supplies the observed hop sequence for chain reconstruction.

## 5. Agent-with-skill walkthrough

An agent hunts login and logout plus reset plus SSO plus payment plus email links after the L1 graph has assigned those endpoints to services.
STATE 1 lists the parent methodology steps S1 to S5 exactly as the skill writes them.
S1 inventories surfaces across login and logout plus reset plus SSO plus OAuth plus payment plus email links, and it completes when every redirector candidate is listed with its carrier.
S2 builds a scheme by host by path matrix with encoding and unicode forms, and it completes when each carrier has a variant set ready to send.
S3 compares enforcing-side validation against navigating-side outcome, and it completes when the validator result and the real navigation result are both recorded.
S4 tests multi-hop chains from a trusted domain through a redirector to an external destination, and it completes when every hop is validated or an escape hop is recorded.
S5 proves impact through phishing or code interception or internal egress, and it completes when the captured evidence shows victim navigation or code delivery or fetcher egress.
STATE 1 Branch 1a does not trigger because five methodology steps exist.

## 6. Feature-verdict table

STATE 2 runs the two-half test for every candidate feature below.

| Feature | Accurate | Exhaustive | Verdict | Evidence |
|---|---|---|---|---|
| PreconditionEnvironment sink locus: server 3xx vs client JS vs OAuth registered | No for OAuth relay | No | Discriminator | S2 matrix and S3 comparator miss two-party registration plus relay |
| PreconditionEnvironment consumer: browser victim vs server fetcher | Yes comparator kind holds | No | Discriminator | S4 external-only chain and S5 browser proof miss internal egress |
| AttackTechnique parser-differential evasion | Yes | Yes | Aspect | S2 matrix plus S3 comparator cover all families |
| AttackTechnique multi-hop relay alone | Yes | Yes | Aspect | S4 already names trusted to redirector to external testing |
| PayloadPattern encoding and unicode and IP families | Yes | Yes | Aspect | S2 matrix explicitly enumerates scheme host path encoding unicode forms |
| TechnologyStack runtime parser per language | Yes | Yes | Non-discriminator | Per-runtime suites change payloads without changing step kind |
| DefensiveControl allowlist vs exact registration vs prompt | Yes comparator kind holds | Yes for generic, No for OAuth | Non-discriminator alone | Control difference rides on sink locus rather than standing alone |
| VulnerabilityClass open redirect itself | Yes | Yes | Non-discriminator | Single class under analysis cannot split itself |
| AttackGoal phishing vs interception vs egress | Yes | Yes as impact labels | Non-discriminator | Impact follows sink and consumer and never bends a step by itself |
| AttackerCapability input supply and callback and inducement | Yes | Yes | Non-discriminator | Shared preconditions hold across all variants |
| Artifact callback URL and code and chain trace | Yes | Yes | Non-discriminator | Evidence objects are produced by every variant alike |
| ObservableSignal browser navigation vs code delivery vs fetcher egress | Partly | No | Discriminator collapsed | Signal covaries exactly with sink and consumer per STATE 3 |

## 7. Step-coverage falsification

STATE 3 records the failing parent step and the uncovered reality for each discriminating value.
OAuth registered sink fails S2 because the parent matrix of scheme by host by path cannot describe IdP registration matching plus prefix plus suffix plus path traversal plus post logout looseness.
OAuth relay fails S3 because the parent single-party validator versus browser comparison cannot describe a two-party IdP to redirector to attacker relay.
OAuth relay fails S5 because the parent generic impact proof cannot describe code capture at an attacker endpoint through a trusted redirector.
Fetcher consumer passes S3 in comparator kind yet fails S4 because the parent trusted to redirector to external chain cannot describe an allowlisted redirector to internal metadata pivot.
Fetcher consumer fails S5 because the parent phishing and interception proof cannot describe timing and header confirmation of server-side egress to an internal target.
Client JS sink stretches S3 because the parent server-side validation wording cannot name a client-side guard versus DOM navigation comparison, and the recommended generic variant rewrites that comparator to cover both signals as an internal aspect.
Hop count alone fails nothing because S4 already covers single and multi-hop chains as one procedure.
Parser families fail nothing because S2 plus S3 cover every canonicalization family with the same submit and compare actions.
Outlier: Host and X-Forwarded-Host absolute URL construction belongs to the header-injection family and is named here without a variant.
Outlier: CDN link-checker token leakage is a fetcher-side validation gap and is named here without its own variant.

## 8. Hypotheses

STATE 4 states one single-feature hypothesis plus a second single-feature hypothesis plus one combined hypothesis.
H1 predicts that sink and validation locus alone splits the class into generic parser-differential testing plus OAuth registration relay testing.
H1 is falsified if OAuth relay needs no registration or relay step beyond the generic comparator, which section 7 refutes.
H2 predicts that redirect consumer alone splits the class into browser-navigation testing plus fetcher-follow testing.
H2 is falsified if fetcher egress needs no internal-target chain step beyond browser comparison, which section 7 refutes for S4 and S5.
H3 predicts that sink locus crossed with consumer yields generic browser plus OAuth relay plus redirector to fetcher pivot, with the OAuth fetcher cell empty by construction.
H3 is falsified if any product cell lacks its own non-coverable step or if two cells share all steps, which section 9 tests.
STATE 3 Branch 3a collapses ObservableSignal into sink and consumer because each signal value implies exactly one sink and consumer pair.
STATE 3 Branch 3b keeps payload families and hop count as aspects because their values have no clean procedural partition.

## 9. Variant sets per hypothesis

STATE 5 derives one variant set per surviving hypothesis, and each variant is named by its first non-coverable parent step.

| Hypothesis | Variant | First non-coverable parent step | Secondary divergences carried inside |
|---|---|---|---|
| H1 sink only | generic-redirect-parser-bypass | S3 comparator | Server 3xx versus client JS signals; all parser families; single and multi-hop depth |
| H1 sink only | oauth-redirect-uri-relay | S2 matrix | Prefix and suffix and traversal checks; post logout looseness; code capture proof |
| H2 consumer only | browser-navigation-redirect | S3 comparator | Server versus client signals; phishing proof |
| H2 consumer only | fetcher-followed-redirect | S4 chain | Internal target selection; egress timing and header proof |
| H3 combined | generic-redirect-parser-bypass | S3 comparator | Server 3xx versus client JS signals; all parser families; external multi-hop depth |
| H3 combined | oauth-redirect-uri-relay | S2 matrix | Registration matching plus trusted relay plus code delivery; post logout looseness |
| H3 combined | redirector-to-fetcher-pivot | S4 chain | Allowlisted redirector selection plus internal target plus egress confirmation |
| H3 combined | oauth-to-fetcher cell | None | Empty by construction and emits no variant per Branch 5a |

Branch 5a emits the fetcher pivot as a product variant because S4 plus S5 add a non-coverable internal-egress chain that neither single-feature variant covers alone.
Branch 5a emits no OAuth fetcher product because no procedure sends an IdP code flow into server metadata egress.

## 10. Well-formedness evaluation

STATE 6 scores each set with weights Coverage critical plus Disjointness critical plus Divergence delta high plus Stability high plus Parsimony medium.
H1 covers generic plus OAuth yet leaves fetcher egress inside generic browser proof, so Coverage fails and Disjointness passes and Delta passes and Stability passes and Parsimony passes.
H2 covers browser plus fetcher yet leaves OAuth registration and relay inside the generic matrix, so Coverage fails and Disjointness passes and Delta passes and Stability passes and Parsimony passes.
H3 covers generic parser bypass plus OAuth relay plus fetcher pivot with exactly one home per non-coverable step, so Coverage passes and Disjointness passes and Delta passes and Stability passes and Parsimony passes.
H1 loses because internal egress has no home outside browser-navigation proof.
H2 loses because two-party registration and relay have no home outside single-party comparison.
H3 wins because every genuine divergence from section 7 owns exactly one variant and survives runtime and payload changes.
Branch 6a does not trigger because the winner passes Coverage and Disjointness.
Branch 6b carries H3 forward to recommendation.

## 11. Recommended set

STATE 7 states the class-specific discrimination function in one sentence.
Open redirect discriminates by redirect sink and validation locus crossed with redirect consumer, namely generic parser-differential versus OAuth-registered relay versus fetcher-followed pivot.
Variant `generic-redirect-parser-bypass` grounds in S3 comparator failure and adds a canonical enforcing versus navigating parser comparison with address-bar proof across all families.
Variant `oauth-redirect-uri-relay` grounds in S2 matrix failure and adds IdP registration testing plus trusted-redirector relay with code delivery proof.
Variant `redirector-to-fetcher-pivot` grounds in S4 chain failure and adds allowlisted-redirector to internal-target chaining with server-egress confirmation.
Token exchange after code capture stays owned by the OAuth family and is only named here.
Internal metadata exploitation after fetcher egress stays owned by the SSRF family and is only named here.
Non-discriminators are TechnologyStack runtime plus DefensiveControl kind alone plus VulnerabilityClass itself plus AttackGoal impact alone plus AttackerCapability preconditions plus PayloadPattern families plus Artifact evidence plus hop count alone.
Grey point: client-side router guards with no server check stretch S3 wording and are carried as an aspect of the generic variant by rewriting the comparator.
Grey point: `javascript` and `data` scheme acceptance overlaps client script injection handling and the generic variant proves only navigation while script execution stays out of scope.
Grey point: post logout redirect looseness is carried inside the OAuth variant although some deployments expose it as a standalone generic redirector.
Open question: whether fetcher pivots that end at external exfiltration rather than internal metadata deserve a separate impact proof inside the fetcher variant.
FAIL-level uncertainty: none, because every recommended variant traces to a named step failure with a positive delta and disjoint evidence.
