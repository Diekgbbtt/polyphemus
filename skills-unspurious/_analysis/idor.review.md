# idor - reviewer verdict

## 1. Verdict

Verdict is PASS.
The analysis satisfies all nine acceptance criteria and the five-variant set survives adversarial scrutiny.
Trust modes are correctly kept non-discriminating and the five variants carry disjoint non-coverable steps.

## 2. Criterion-by-criterion audit

| Criterion | Result | Evidence |
|---|---|---|
| C1: all 12 sections present and non-empty | PASS | `idor.md:1` holds the class header and `idor.md:3,8,22,34,40,53,69,85,91,105,123` hold sections 1 through 11 with substantive prose in each. |
| C2: all 10 methodology entity types addressed | PASS | `idor.md:9-20` ledger rows cover PreconditionEnvironment, TechnologyStack, DefensiveControl, VulnerabilityClass, AttackGoal, AttackerCapability, AttackTechnique, PayloadPattern, Artifact, and ObservableSignal with `none` avoided because every type has a stated value or explicit role. |
| C3: deductive discriminator derivation | PASS | `idor.md:64-67` derive D1 through D4 each from a named entity value plus a named parent step and SKILL.md source lines, not from a universal menu. |
| C4: two-half test for every recommended variant | PASS | `idor.md:98-102` plus `idor.md:125-129` name a parent step per variant and state what that step omits, and `idor.md:70-80` falsify each value against S3 or S4. |
| C5: positive delta plus disjointness plus stability | PASS | `idor.md:111-114` score coverage, disjointness, delta, and stability as pass with per-variant deltas stated at `idor.md:125-129`. |
| C6: non-discriminators stated explicitly with reason | PASS | `idor.md:56-63` record seven non-discriminator groups with reasons and `idor.md:130` restates the full non-discriminator list in the recommendation. |
| C7: falsifiable hypotheses plus weighted evaluation | PASS | `idor.md:86-89` state H1 through H4 each with an explicit falsification condition and `idor.md:106-116` apply weights in coverage, disjointness, delta, stability, and parsimony order. |
| C8: no workflow state skipped and outliers reported | PASS | `idor.md:118-121` account for STATE 1 through STATE 3 branches including the no-outlier report, and sections 8 through 11 complete STATE 4 through STATE 7. |
| C9: no em dashes and one sentence per prose line | PASS | No em dash character appears in `idor.md:1-136` on inspection, and each prose line terminates as one full sentence with semicolon-joined clauses used instead of extra sentence breaks. |

## 3. Detailed findings per criterion

C1 passes because the header at `idor.md:1` matches the required title pattern.
C1 passes because section 1 at `idor.md:3-6` defines scope and authority in one paragraph.
C1 passes because section 11 at `idor.md:123-136` contains the discrimination function, five variant deltas, non-discriminators, open questions, and grey points.
C2 passes because TechnologyStack at `idor.md:12` is marked non-discriminator with an excluded-axis reason.
C2 passes because PayloadPattern at `idor.md:18` is marked aspect rather than hidden or omitted.
C2 passes because Artifact at `idor.md:19` and ObservableSignal at `idor.md:20` are marked non-discriminator with runtime and detection reasons.
C3 passes because D1 at `idor.md:64` traces cardinality to S3 and S4 with SKILL.md lines 62 through 71.
C3 passes because D2 at `idor.md:65` traces redemption timing to live-swap S4 with SKILL.md lines 73 through 82.
C3 passes because D3 at `idor.md:66` traces identity carrier to token-swap S4 with SKILL.md lines 100 through 110.
C3 passes because D4 at `idor.md:67` traces resource depth to reference-swap S4 with SKILL.md lines 30 through 32 and 84 through 98.
C4 passes because the direct variant at `idor.md:98` claims control-paired swapping with verb derivation and differential confirmation over S4.
C4 passes because the collection variant at `idor.md:99` claims cursor filter-skip and position reasoning over S3.
C4 passes because the deferred variant at `idor.md:100` claims two-phase binding with scope and expiry over S4.
C4 passes because the carrier variant at `idor.md:101` claims precedence and audience binding over S4.
C4 passes because the expansion variant at `idor.md:102` claims sub-resource binding beyond the swapped reference over S4.
C5 passes because each delta at `idor.md:125-129` adds a procedural verdict that parent S3 or S4 never names.
C5 passes because stability is credible since cardinality, timing, carrier, and depth survive stack and payload swaps.
C6 passes because trust direction at `idor.md:56` is rejected as non-discriminator with S4 lines 173 through 174 cited.
C6 passes because identifier form at `idor.md:57` is rejected per the SPEC section 8 encoding pitfall.
C6 passes because duplicate-key pollution at `idor.md:63` is kept as aspect with SKILL.md lines 46 and 130 through 138 cited.
C7 passes because H4 at `idor.md:89` is a genuine falsifiable trust-mode split that section 10 discards for zero delta.
C7 passes because H3 at `idor.md:88` predicts exactly five variants and is falsifiable by shared uncovered values or missing deltas.
C8 passes because STATE 2 at `idor.md:119` records both halves for every ledger value.
C8 passes because STATE 3 branch 3a at `idor.md:120` and branch 3b at `idor.md:121` are addressed explicitly.
C9 passes because the file contains only hyphens and no em dash glyph.
C9 passes because long lines such as `idor.md:23` and `idor.md:130` use semicolons and commas within one terminating period.

## 4. Trust-mode scrutiny

Trust direction was correctly kept non-discriminating.
`idor.md:56` answers Accurate as No because horizontal, vertical, and cross-tenant access use the same kind of swap-and-compare action.
`idor.md:81` confirms no falsification holds because S4 at SKILL.md lines 173 through 174 already enumerates swapping IDs, tokens, and tenants.
H4 at `idor.md:89` hypothesised a horizontal, vertical, and cross-tenant split and was discarded at `idor.md:103` and `idor.md:110` for zero procedural delta.
This matches SPEC section 8 which warns against imposing trust assumption as a universal axis.
SKILL.md lines 12 through 16 list the three directions as scope labels rather than distinct procedures.
No variant is named by direction and no direction adds a non-coverable step.
Therefore the analysis does not over-split one procedure under three names.

## 5. Adversarial well-formedness argument

Coverage was attacked by asking whether WebSocket, gRPC, cache, race, and webhook techniques from SKILL.md lines 112 through 150 lack a variant.
The attack fails because transport framings are owned aspects under S5 and S6 per `idor.md:83`, GraphQL specifics delegate to the `graphql` skill per SPEC section 7, and race, proxy, and bypass detail delegate to their owning families per `idor.md:27-28` and `idor.md:135`.
Coverage was attacked by asking whether secondary harvest belongs to direct swap rather than collection scope.
The attack fails because `idor.md:99` explicitly carries list-seeded secondary harvest inside the collection variant with cursor distrust as the binding rule.
Coverage holds because every falsified value at `idor.md:70-80` maps to exactly one of the five H3 variants at `idor.md:98-102`.
Disjointness was attacked by alleging that bulk batch arrays at SKILL.md lines 62 through 65 and GraphQL batching at SKILL.md lines 84 through 98 collide on the word batch.
The attack fails because the analysis partitions single-request aliased node retrieval to expansion per `idor.md:80` and `idor.md:134`, while mid-array validation gaps stay in collection per `idor.md:71`.
Disjointness was attacked by alleging that tenant selectors could fall in both direct and carrier variants.
The attack fails because the grey point at `idor.md:132` assigns routing-only selectors to direct and selector-as-identity cases to carrier.
Disjointness was attacked by alleging that signed URLs could fall in both deferred and carrier variants.
The attack fails because `idor.md:133` assigns key and signature scope-and-expiry redemption to deferred while carrier covers header precedence and token audience.
Disjointness holds under the grey-point assignments at `idor.md:132-136` and no attempt admits two verdicts without a stated tie-break.
Delta was attacked hardest on the direct variant because verb derivation lives in S0b and control pairing lives in S0c.
The attack fails under the per-step test because the tested step is S4 alone, which never names verb derivation, control pairing, or differential confirmation, so the combined controlled procedure is a genuine delta over S4.
Delta holds for the other four variants because pagination filter-skip, two-phase redemption, precedence and audience checks, and projection plus resolver-hop verdicts are absent from S3 and S4 text.
Stability was attacked by asking whether carrier header names or GraphQL syntax tie variants to a stack.
The attack fails because precedence probing, audience binding, and per-hop verdicts survive renaming of headers, tokens, stacks, and payloads.
Parsimony was attacked by asking whether four features and five variants over-split the class.
The attack fails because H1 and H2 leave deferred, carrier, and expansion values uncovered per `idor.md:107` and `idor.md:109`, so no smaller set covers.
The H3 set is therefore the minimal covering set and the winner declaration at `idor.md:116-117` is sound.

## 6. Workflow audit STATE 1 through STATE 7

STATE 1 completed with S0a through S0d plus S1 through S6 at `idor.md:42-51` and a full entity inventory at `idor.md:9-20`.
No malformed-class outlier existed and none was hidden per `idor.md:118`.
STATE 2 completed with both halves tested for every candidate at `idor.md:56-67`.
STATE 3 completed with co-varying framings and direction labels collapsed per `idor.md:120` and continuous values kept as aspects per `idor.md:121`.
STATE 4 completed with two single-feature hypotheses H1 and H2, one combined hypothesis H3, and one rejected trust-mode hypothesis H4 at `idor.md:86-89`.
STATE 5 completed with variant sets per hypothesis at `idor.md:92-103` including secondary divergences carried inside each variant.
Branch 5a was respected because no combined variant beyond the five was emitted without its own non-coverable step.
STATE 6 completed with weighted scoring at `idor.md:106-117` and explicit losing reasons for H1, H2, and H4.
Branch 6a was respected because H1 and H2 coverage failures were named and no return to STATE 3 was needed for the passing winner.
STATE 7 completed with the one-sentence discrimination function at `idor.md:124`, five deltas at `idor.md:125-129`, non-discriminators at `idor.md:130`, and open questions plus grey points at `idor.md:131-136`.
No algorithm failure occurred and no state was skipped.

## 7. SKILL.md fidelity check

The class body at `skills-unspurious/idor/SKILL.md:159-176` supports the S0 through S6 walkthrough at `idor.md:42-51`.
The scope labels at SKILL.md lines 12 through 16 support the non-discriminator verdict on trust direction at `idor.md:56`.
The bulk, secondary, job, storage, GraphQL, microservice, and tenant passages at SKILL.md lines 62 through 110 support D1 through D3 citations.
The expansion knobs at SKILL.md lines 30 through 32 plus the GraphQL section at lines 84 through 98 support D4.
The bypass passages at SKILL.md lines 128 through 150 support the aspect treatment at `idor.md:63` and the delegation statements at `idor.md:27-28`.
No citation was found to misquote its SKILL.md source range.

## 8. Required corrections

No corrections are required.
No FAIL-level open question exists and the grey points at `idor.md:132-136` are documented tie-breaks rather than hidden gaps.
A future SKILL.md split should preserve the tenant-selector tie-break, the storage-inside-deferred boundary, and the GraphQL-batching-inside-expansion boundary.
A future defence-bypass and proxy family cutover should keep the delegation pointers at `idor.md:27-28` intact.
