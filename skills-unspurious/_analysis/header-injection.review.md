# header-injection - reviewer reaudit after rework

## 1. Verdict

Verdict is PASS with no FAIL-level rework required.
The reworked analysis at skills-unspurious/_analysis/header-injection.md satisfies all 9 acceptance criteria in SPEC section 6.
All 10 corrections demanded by the earlier review are verified as applied with file and line evidence in section 3.
The recommended H4 six-variant set survives fresh adversarial attacks on coverage and disjointness and delta and stability and parsimony.
Remaining items in section 6 are non-blocking notes that do not change the verdict.

## 2. Criterion audit

The table gives one row per SPEC section 6 criterion with exact evidence.

| # | Criterion (SPEC section 6) | Result | Evidence |
|---|---|---|---|
| 1 | Every one of the 12 sections is present and non-empty | PASS | Title at header-injection.md:1 plus sections at header-injection.md:3, 9, 57, 77, 83, 94, 114, 132, 142, 161, 180 |
| 2 | All 10 methodology entity types are addressed with none where applicable | PASS | Ledger covers all 10 types at header-injection.md:10-55 with PreconditionEnvironment plus TechnologyStack plus DefensiveControl plus VulnerabilityClass plus AttackGoal plus AttackerCapability plus AttackTechnique plus PayloadPattern plus Artifact plus ObservableSignal |
| 3 | Discriminator derivation is deductive from entity value plus step | PASS | Each discriminator row names an entity pair plus a parent step at header-injection.md:105-110 with falsification at header-injection.md:115-127 |
| 4 | Every variant satisfies the two-half test with a named parent step | PASS | Each recommended variant names its parent step plus uncovered reality at header-injection.md:182-187 under the section-2 either-fails rule at SPEC lines 25-26 |
| 5 | Every variant has positive delta plus disjointness plus stability | PASS | Six deltas stated at header-injection.md:182-187 with disjointness predicates at header-injection.md:167 and stability claim at header-injection.md:169 |
| 6 | Non-discriminators stated explicitly with reason | PASS | Non-discriminators listed with reasons at header-injection.md:97-104 and header-injection.md:111-112 and summarised at header-injection.md:188 |
| 7 | Hypotheses are falsifiable and evaluation uses weighted criteria | PASS | H1 plus H4 plus H2 plus H3 each carry a falsifier at header-injection.md:133-140 with ordered weights applied at header-injection.md:162-174 |
| 8 | No workflow state skipped and outliers reported not hidden | PASS | STATE 1 through STATE 7 artefacts span header-injection.md:83-178 with branch 6a return claimed at header-injection.md:174 and no malformed-class outlier existing |
| 9 | No em dashes and one full sentence per line for prose | PASS | Em-dash scan reports zero hits and the sentence scan reports no multi-sentence prose line in the reworked analysis |

Note on AC4 wording is retained from the earlier review because SPEC line 134 says neither accurate nor exhaustive while SPEC lines 25-26 say either failure yields a variant.
The reaudit applies the section-2 either-fails semantics because the literal neither-nor reading would disqualify every Accurate-Yes row including header-injection.md:105-109.
The V7 Accurate label correction at header-injection.md:110 now reads No plus No with a same-kind justification tied to SKILL line 153.

## 3. Correction verification against the earlier review

This section checks each of the 10 demanded corrections in order.
Each item below is one sentence and cites the applied evidence.

1. Line-break versus delimiter-free exclusion is applied at header-injection.md:19 and header-injection.md:20 and header-injection.md:34 and header-injection.md:40 and header-injection.md:42 with the SKILL line 60 CRLF Set-Cookie example assigned to splitting.
2. Merged spoof is adopted at header-injection.md:106 and header-injection.md:118 and header-injection.md:135 and header-injection.md:153 with X-Forwarded-Host link building owned once and rewrite headers excluded.
3. Rewrite-header sole ownership is moved entirely into routing at header-injection.md:18 and header-injection.md:36 and header-injection.md:38 and header-injection.md:119 and header-injection.md:123 with the V3 delta cleaned of rewrite outcomes.
4. Splitting versus cache oracles are distinguished by non-overlapping predicates at header-injection.md:51 and header-injection.md:52 and header-injection.md:116 and header-injection.md:121 and header-injection.md:167 with a rejected cache-merge rationale at header-injection.md:173.
5. Merged spoof delta is strengthened as a unified comparison procedure at header-injection.md:135 and header-injection.md:153 and header-injection.md:168 which neither P3 nor P4 describes alone.
6. V7 Accurate label is corrected to No at header-injection.md:110 with delimiter-free replacement named as a different action kind from the SKILL line 153 CRLF probe.
7. Email-header contradiction is resolved as explicitly out of scope at header-injection.md:7 and header-injection.md:13 and header-injection.md:98 and header-injection.md:188 with ownership pointed to the related SMTP class.
8. Single-feature collapse is justified against co-variance at header-injection.md:176 and header-injection.md:177 with non-co-variance stated through framing-parser trust holding without URL-builder trust.
9. Leaner hypotheses are scored in STATE 6 at header-injection.md:163-173 with H4 as winner and H1 plus H2 plus H3 plus merged cache-served response given explicit losing reasons.
10. STATE 6 branch 6a is rerun honestly at header-injection.md:174 with the H1 straddle named and the return to STATE 3 and the four exclusions documented before H4 is rescored.

## 4. Adversarial well-formedness argument

This section re-attacks the recommended H4 six-variant set and judges survival.

### 4a. Coverage

The attack asserts that SMTP email headers leave a ledger source without an owning variant.
The attack fails because the analysis scopes SMTP out at header-injection.md:7 and marks the ledger value out of scope at header-injection.md:13 while the SKILL body at SKILL lines 16 and 177 confirms the related-class reading.
The attack asserts that proto-host cache links and X-Accel-Redirect file access and javascript-scheme redirects lack owners.
The attack fails because proto-host poisoning is swept under the cache sub-shape oracle at header-injection.md:121 while X-Accel-Redirect and javascript schemes ride inside value-confusion sinks at header-injection.md:44-46 with grey-point guards at header-injection.md:190-191.
Coverage therefore PASSES for the declared HTTP scope with no genuine non-coverable step left homeless.

### 4b. Disjointness

The attack replays the four earlier overlaps against the new exclusion predicates.
The CRLF Set-Cookie overlap fails because splitting owns only line-break payloads with a stored-header-field oracle at header-injection.md:34 while value-confusion owns only delimiter-free replacement at header-injection.md:40.
The X-Forwarded-Host straddle fails because the merged spoof variant owns all Host-family link and decision proof once at header-injection.md:153 with no second spoof partition left to collide.
The rewrite-header overlap fails because routing solely owns X-Original-URL plus X-Rewrite-URL at header-injection.md:38 while spoof explicitly excludes them at header-injection.md:36 and P4 is barred from owning them at header-injection.md:119.
The cache-served second-response overlap fails because splitting requires a stored header field served downstream at header-injection.md:51 while cache requires attacker-influenced body on clean replay with no new header field at header-injection.md:52.
Disjointness therefore PASSES on the four demanded predicates with the residual proto-host chaining note kept as non-blocking in section 6.

### 4c. Divergence delta

The attack asserts that the merged spoof precedence plus per-alias mapping is still value enumeration inside P3 at SKILL line 154 and P4 at SKILL line 155.
The attack fails because P3 plus P4 each describe single-value submission or single spray while H4 at header-injection.md:118 and header-injection.md:153 adds controlled swapped-value precedence comparison plus bracketing and dot and port edges plus emailed-link capture plus per-alias allowlist versus scheme mapping with negative controls.
The attack asserts that cache sub-shape sweep and smuggling downgrade shapes are enumerations inside P5 and P7.
The attack fails because P5 never names the five-shape sweep with Vary plus Cache-Control plus deception handling at header-injection.md:121 and P7 never names downgrade plus lowercase plus CONTINUATION-split replay with leftover-bytes proof at header-injection.md:125.
The attack asserts that value-confusion merely renames cookie and MIME and redirect sinks.
The attack fails because P2 describes only line-break splitting at SKILL line 153 while value-confusion at header-injection.md:127 performs delimiter-free replace-then-observe-client with no line break.
Divergence delta therefore PASSES for all six variants with the modelling note in section 6 kept as non-blocking.

### 4d. Stability

The attack swaps CDN vendor plus HTTP version plus framework plus payload literal plus runtime asset and asks whether any consumer oracle collapses.
The attack fails because each oracle at header-injection.md:182-187 is defined by trusting-consumer behaviour rather than stack identity and each variant enumerates encodings and sinks as parameters.
The attack asserts that IIS plus ASP.NET ownership makes routing stack-bound.
The attack fails because the discriminator is pre-authorization routing trust at header-injection.md:18 while IIS plus ASP.NET at header-injection.md:123 names only where the behaviour was observed rather than what defines the step.
H3 is correctly discarded for technology-axis instability at header-injection.md:140 and header-injection.md:172.
Stability therefore PASSES and survives the attack.

### 4e. Parsimony

The attack asserts that six variants from one consumer feature remain over-split and that a leaner framing or cache-served merge was skipped.
The attack fails because H4 already merges the two spoof partitions into one variant at header-injection.md:135 and beats seven-variant H1 on parsimony at header-injection.md:170.
The attack asserts that the merged cache-served response hypothesis was dismissed without testing.
The attack fails because the analysis considers and rejects that merge at header-injection.md:173 on payload-precondition grounds since splitting requires line breaks while cache forbids that requirement.
H2 is correctly discarded for defeat-cell multiplication without a new step at header-injection.md:171.
H3 is correctly discarded for stack-cell multiplication without a new step at header-injection.md:172.
Parsimony therefore PASSES for H4 as the leanest covering set tested.

## 5. Workflow audit

The table checks each workflow state against the algorithm in SPEC section 3.

| State | Followed | Evidence |
|---|---|---|
| STATE 1 class inventory | Yes | Eight parent steps P1-P8 with completion conditions at header-injection.md:85-92 plus full entity inventory at header-injection.md:10-55 |
| STATE 2 feature test | Yes | Accurate plus exhaustive asked per feature at header-injection.md:95-112 with aspects plus non-discriminators recorded |
| STATE 3 signature | Yes | One consumer feature with seven values plus non-co-variance at header-injection.md:177 plus branch 3b aspects at header-injection.md:178 |
| STATE 4 hypothesise | Yes | Single-feature H1 plus lean H4 plus combined H2 plus H3 with falsifiers at header-injection.md:133-140 |
| STATE 5 derive variant sets | Yes | Per-hypothesis sets with first non-coverable steps at header-injection.md:143-159 with no unjustified product variant |
| STATE 6 well-formedness evaluation | Yes | Ordered weights plus per-set scores plus winner plus losing reasons at header-injection.md:162-174 with branch 6a return at header-injection.md:174 |
| STATE 7 recommendation | Yes | One-sentence signature plus six deltas plus non-discriminators plus open questions plus grey points at header-injection.md:181-191 |

No malformed-class outlier existed so none was hidden.
The earlier evaluative failure is repaired because branch 6a fired on the H1 straddle before H4 was declared winner.

## 6. Remaining corrections

No FAIL-level correction remains and further rework is not required before variant authoring.
The proto-host cache-poisoning chain should gain one exclusion sentence in a later edit stating that spoof owns link-bending proof while cache owns clean-replay serving proof when both fire together.
The HTTP/2 shape double appearance as aspect at header-injection.md:41 and as smuggling delta at header-injection.md:125 should gain one clarifying sentence naming replay as parameter and frame-split reassembly as step.
The consumer-feature grouping should keep its non-co-variance sentence at header-injection.md:177 because consumer is a role over entity pairs rather than a literal methodology entity type.
Final verdict is PASS.
