# subdomain-takeover - variant decomposition analysis

## 1. Class and scope

This analysis decomposes the `subdomain-takeover` class from `skills-unspurious/subdomain-takeover/SKILL.md`.
The class covers trusted-subdomain control through dangling DNS and unclaimed provider bindings across resource claims plus alternate-domain bindings plus delegation takeovers.
STATE 1 inventory below confirms the class is well formed because it carries six methodology steps and pinnable ontology values.

## 2. Ontology entity ledger

| Entity type | Value(s) | Source lines | Role |
|---|---|---|---|
| PreconditionEnvironment | Dangling CNAME or A or ALIAS to unclaimed endpoint; orphaned NS delegation to expired nameserver domain; CDN alternate-domain mapping without ownership verification; MX to decommissioned provider; wildcard CNAME to provider | 12, 15, 17, 24, 28, 29, 30, 31, 55, 60, 66, 92 | Discriminator candidate |
| TechnologyStack | GitHub Pages; S3 and Blob and GCS storage; CloudFront and Fastly and Azure CDN and Akamai; Heroku and App Service and Vercel and Netlify; SaaS integrations | 16, 28, 36, 37, 38, 39, 40, 41, 42, 95, 100, 105 | Non-discriminator |
| DefensiveControl | TXT and ownership verification prior to binding; alternate-domain ownership check; CAA issuance restriction | 57, 85, 88, 102, 107, 126, 138 | Non-discriminator |
| VulnerabilityClass | Subdomain takeover | 6, 8 | Non-discriminator |
| AttackGoal | Serve content under trusted subdomain; phishing and malware delivery; cookie and CORS pivot; OAuth redirect abuse; email receipt manipulation | 8, 66, 74, 81 | Non-discriminator |
| AttackerCapability | Operate provider account and create named resource; register expired nameserver domain; host authoritative NS and publish zone records | 50, 51, 52, 53, 58, 62 | Non-discriminator |
| AttackTechnique | Exact-name third-party resource creation; victim name added as alternate domain on attacker distribution; expired-domain registration with authoritative NS hosting; mail receipt claim on decommissioned MX | 50, 55, 60, 66 | Discriminator candidate |
| PayloadPattern | Minimal static unique ownership-proof page content | 79, 122, 131 | Aspect inside variants |
| Artifact | CNAME record graph; provider fingerprint corpus; served proof content; DV certificate with CT entry | 24, 33, 79, 122, 131 | Non-discriminator |
| ObservableSignal | NXDOMAIN versus SERVFAIL versus provider-branded error codes; provider unclaimed texts across Pages plus Fastly plus Heroku plus S3 plus CloudFront plus Azure plus Shopify; TLS SAN mismatch to provider default; CDN edge differentials | 23, 35, 36, 37, 38, 39, 40, 41, 42, 44, 73 | Collapsed into binding type per STATE 3 |

## 3. RDF notion map

Attack surface and reconnaissance hold dangling records plus orphaned delegations plus alternate-domain mappings plus SaaS bindings plus enumeration and DNS and probe pipelines, and binding type varies while pipeline order stays invariant.
Adversarial capabilities hold provider-account resource creation plus expired-domain registration plus authoritative hosting plus certificate issuance, and all four stay invariant as shared preconditions across variants.
Common trust assumptions hold DNS points at owned resources plus providers verify ownership plus delegations stay live plus alternate names stay bound, and each assumption varies by binding type.
Testing methodology holds enumeration plus DNS resolution plus HTTP and TLS probing plus provider fingerprinting plus authorized claim plus control validation, and the resolution plus claim plus validation steps vary as section 7 shows.
Proxy techniques hold none as a named family because edge-differential reading is carried inside the alternate-domain variant and named here only.
Defence bypass techniques hold TXT-prior binding acceptance plus race-window re-claim plus fallback-origin exposure, and all three stay as aspects inside the claim variants.
Techniques anti-patterns hold none named beyond the S5 authorization gate that forbids claiming without scope.
Scripted tests hold none because the skill ships no references suite.
False positives hold unclaimable unknown-domain pages plus owned-resource default pages plus catch-all and soft-404 vhosts, and all three stay invariant as stop conditions.
Chaining holds OAuth redirect abuse plus CSP and script-source trust plus cookie scoping plus cache poisoning, and each chain varies by control proof while exploitation stays owned by consumer families.

## 4. Runtime parametrisation

The concrete Service arrives at runtime from the L1 graph and only scopes which business function owns the subdomain.
The concrete System arrives at runtime and only records which hosting or edge mechanism serves the binding.
The concrete Endpoint arrives at runtime and only locates the probe target for HTTP and TLS evidence.
The concrete Parameter arrives at runtime and only names carriers used in downstream impact chains.
The concrete DataItem arrives at runtime and only types values flowing through post-takeover impact chains.
The concrete BaseURL arrives at runtime and only anchors the subdomain under test for probe and proof requests.
The concrete Header arrives at runtime and only carries Server plus status plus certificate evidence from probing.
The HTTP history arrives at runtime and only supplies observed resolver plus status plus body sequences for fingerprinting.

## 5. Agent-with-skill walkthrough

An agent hunts decommissioned assets after subdomain inventory and DNS resolution have produced externally pointing records.
STATE 1 lists the parent methodology steps S1 to S6 exactly as the skill writes them.
S1 enumerates subdomains across CT logs plus passive DNS plus asset lists plus IaC outputs, and it completes when every candidate subdomain is listed with its source.
S2 resolves all RR types across A plus AAAA plus CNAME plus NS plus MX plus TXT while keeping CNAME chains, and it completes when every record chain is recorded with its terminal endpoint.
S3 probes HTTP plus TLS for status plus body plus error text plus Server headers plus certificate SANs, and it completes when each candidate has a captured response triple.
S4 fingerprints providers by mapping unclaimed and missing-resource signatures, and it completes when each response maps to a known signature or to unknown.
S5 attempts claim with authorization by creating the missing resource with the exact required name, and it completes when creation succeeds or is refused by a verification check.
S6 validates control by serving a minimal unique payload over HTTPS, and it completes when the target subdomain returns the unique proof content.
STATE 1 Branch 1a does not trigger because six methodology steps exist.

## 6. Feature-verdict table

STATE 2 runs the two-half test for every candidate feature below.

| Feature | Accurate | Exhaustive | Verdict | Evidence |
|---|---|---|---|---|
| Claim mechanism: dangling record versus alternate domain versus delegation | No, claim action kind differs | No | Discriminator | S2 plus S5 plus S6 miss expiry checks plus alt-name addition plus subzone control |
| TechnologyStack provider identity: Pages versus storage versus CDN versus app hosting | Yes, same claim kind | Yes | Non-discriminator | S4 plus S5 cover all providers through signature values plus exact-name action |
| DefensiveControl TXT and ownership enforcement alone | Yes, refusal kind holds | Yes as stop condition | Non-discriminator | S5 plus false positives cover claimable versus unclaimable without new step kind |
| VulnerabilityClass subdomain takeover itself | Yes | Yes | Non-discriminator | Single class under analysis cannot split itself |
| AttackGoal phishing versus pivot versus OAuth versus email impact | Yes as impact labels | Yes | Non-discriminator | Impact follows proven control and never bends a step by itself |
| AttackerCapability account operation plus domain registration plus NS hosting | Yes | Yes | Non-discriminator | Shared preconditions hold across all three mechanism variants |
| PayloadPattern minimal proof page wording | Yes | Yes | Aspect | S6 covers all proof wordings with the same serve-and-confirm action |
| Artifact CNAME graph plus fingerprint corpus plus certificate evidence | Yes | Yes | Non-discriminator | Evidence objects are produced by every variant alike |
| ObservableSignal fingerprint family: unclaimed text versus edge differential versus delegation liveness | Partly | No | Collapsed discriminator | Signal covaries exactly with claim mechanism per STATE 3 Branch 3a |
| MX mail binding alone | Yes in claim kind only | No procedure to test | Non-discriminator plus outlier | Skill names only receipt possibility with no fingerprint or claim or validation detail |
| Wildcard CNAME scope | Yes | Yes | Aspect | Wildcard only widens enumeration inside the matching mechanism variant |

## 7. Step-coverage falsification

STATE 3 records the failing parent step and the uncovered reality for each discriminating value.
Dangling-record claim stretches S5 because the parent phrase of creating the missing resource cannot describe provider binding flows plus TXT-prior acceptance plus race re-claim plus website versus API claimability.
Alternate-domain binding fails S5 because the parent creation wording cannot describe adding the victim subdomain as an alternate name on the attacker distribution plus uploading or issuing a certificate.
Alternate-domain binding stretches S4 because the parent generic signature mapping cannot describe edge differentials of 404 plus 421 versus 403 that reveal partial alternate-name configuration.
Alternate-domain binding stretches S6 because the parent unique-payload over HTTPS wording cannot describe alternate-name plus certificate plus cache-key proof on shared edge infrastructure.
Delegation takeover fails S2 because the parent all-RR resolution plus CNAME-chain wording cannot describe child-zone delegation tracing plus nameserver-domain expiry checks plus authoritative-server liveness checks.
Delegation takeover fails S5 because the parent exact-name creation wording cannot describe expired-domain registration plus authoritative NS hosting plus publishing records for the delegated subzone.
Delegation takeover fails S6 because the parent single-subdomain payload wording cannot describe full control of all hosts below the delegated label.
Provider identity fails nothing because S4 plus S5 cover Pages plus storage plus app hosting plus CDN through the same fingerprint plus exact-name actions with provider-specific values only.
TXT enforcement fails nothing as a splitter because S5 refusal plus false positives already cover unclaimable bindings as stop conditions with the same step kind.
STATE 3 Branch 3a collapses PreconditionEnvironment binding condition with AttackTechnique claim action into one claim-mechanism feature because each binding value implies exactly one claim action.
STATE 3 Branch 3a collapses ObservableSignal fingerprint family into claim mechanism because unclaimed text implies resource claim plus edge differentials imply alternate-domain binding plus delegation liveness implies delegation takeover.
STATE 3 Branch 3b keeps bucket-naming constraints plus website versus API differences plus proof wording as aspects inside the resource-claim variant with no clean procedural partition.
Outlier: MX mail receipt names a possible email consequence with no fingerprint plus no claim flow plus no validation detail and is carried without a variant.
Outlier: OAuth redirect plus CSP plus cookie pivot plus cache poisoning name post-takeover impact owned by consumer families and are named here without variants.

## 8. Hypotheses

STATE 4 states two single-feature hypotheses plus one combined hypothesis.
H1 predicts that claim mechanism alone splits the class into resource claim plus alternate-domain binding plus delegation takeover.
H1 is falsified if any of its three variants lacks its own non-coverable step from section 7 or if two variants share all steps.
H2 predicts that provider identity alone splits the class into storage plus pages plus app-hosting plus CDN variants.
H2 is falsified if provider change leaves S2 plus S4 plus S5 plus S6 step kinds unchanged, which section 7 confirms.
H3 predicts that claim mechanism crossed with provider yields a product set with provider-specific subvariants under each mechanism.
H3 is falsified if no product cell adds a non-coverable step beyond its mechanism parent, which section 9 tests under Branch 5a.
STATE 4 Branch 4a discards H2 because section 7 shows provider change alters only signature values and binding-flow values without bending any step kind.

## 9. Variant sets per hypothesis

STATE 5 derives one variant set per surviving hypothesis, and each variant is named by its first non-coverable parent step.

| Hypothesis | Variant | First non-coverable parent step | Secondary divergences carried inside |
|---|---|---|---|
| H1 mechanism only | dangling-record-resource-claim | S5 attempt claim | Provider binding flows; TXT-prior gaps; race windows; website versus API handling; unclaimed-text proof |
| H1 mechanism only | cdn-alternate-domain-binding | S5 attempt claim | Edge-differential fingerprinting; certificate issuance; cache-key proof |
| H1 mechanism only | ns-delegation-takeover | S2 resolve DNS | Expiry plus liveness checks; expired-domain registration; authoritative hosting; subzone-wide proof |
| H2 provider only | storage-takeover; pages-takeover; apphost-takeover; cdn-takeover | None | Signature values only with no bent step kind |
| H3 product | mechanism crossed with provider cells | None beyond mechanism parent | Provider values only with no added non-coverable step |

Branch 5a emits no product variant because no mechanism crossed with provider cell adds a step that its mechanism parent does not already cover.
Branch 5a emits no mail variant because the MX surface contributes no fingerprint plus no claim flow plus no validation step of its own.

## 10. Well-formedness evaluation

STATE 6 scores each set with weights Coverage critical plus Disjointness critical plus Divergence delta high plus Stability high plus Parsimony medium.
H1 covers resource claim plus alternate-domain binding plus delegation takeover with exactly one home per non-coverable step, so Coverage passes and Disjointness passes and Delta passes and Stability passes and Parsimony passes.
H2 covers provider cells yet leaves delegation tracing plus alt-name addition homeless, so Coverage fails and Disjointness passes and Delta fails and Stability fails and Parsimony fails.
H3 covers the same ground as H1 with provider-multiplied cells that add no new step, so Coverage passes and Disjointness passes and Delta fails and Stability fails and Parsimony fails.
H2 loses because provider identity changes only TechnologyStack values without bending S2 plus S4 plus S5 plus S6.
H3 loses because provider multiplication duplicates one procedure under many names against the stability rule.
H1 wins because every genuine divergence from section 7 owns exactly one variant and survives provider plus payload plus version plus runtime-asset changes.
Branch 6a does not trigger because the winner passes Coverage and Disjointness.
Branch 6b carries H1 forward to recommendation.

## 11. Recommended set

STATE 7 states the class-specific discrimination function in one sentence.
Subdomain takeover discriminates by claim mechanism, namely dangling-record resource claim versus CDN alternate-domain binding versus NS delegation takeover.
Variant `dangling-record-resource-claim` grounds in S5 attempt-claim failure and adds exact-name creation with binding-flow plus verification-gap plus race-window plus website-versus-API handling and unclaimed-text proof.
Variant `cdn-alternate-domain-binding` grounds in S5 attempt-claim failure and adds attacker-distribution alternate-name addition with certificate handling plus edge-differential fingerprinting and cache-aware proof.
Variant `ns-delegation-takeover` grounds in S2 resolve-DNS failure and adds delegation tracing plus expiry and liveness checks with expired-domain registration plus authoritative hosting and subzone-wide proof.
Non-discriminators are TechnologyStack provider identity plus DefensiveControl TXT enforcement alone plus VulnerabilityClass itself plus AttackGoal impact alone plus AttackerCapability account ability plus PayloadPattern proof wording plus Artifact graph and certificate evidence plus runtime Service plus System plus Endpoint plus Parameter plus DataItem plus BaseURL plus Header plus HTTP history.
Grey point: MX mail takeover stays an outlier because the skill gives no fingerprint or claim or validation procedure for email receipt.
Grey point: wildcard CNAME scope is carried as an aspect of the matching mechanism variant although unbounded labels complicate enumeration proof.
Grey point: CDN products that recently added ownership checks move findings from claimable to false positive without changing the variant procedure.
Open question: whether decommissioned SaaS integrations with provider-managed DNS need their own binding-flow aspect inside the resource-claim variant.
FAIL-level uncertainty: none, because every recommended variant traces to a named step failure with a positive delta and disjoint evidence.
