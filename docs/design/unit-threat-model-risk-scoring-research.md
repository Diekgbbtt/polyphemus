# Unit threat model - risk scoring research

*Status: research note, 2026-10-16. Operator-assigned investigation of five candidate likelihood-scoring schemes for the unit threat model loops. Primary sources only; access limits are listed in section 7. Nothing here is built, and this note is the only file written.*

## 1. Context

- A loop records one research direction as `fault -> web vulnerability class -> failure mode assessment -> likelihood` [first-party: `docs/design/unit-threat-model-workflow.md`, section 2.1].
- The modeller writes the loops at the COMPLETED gate, and loop ids are assigned in ranked order (`loop-1` = highest likelihood) [workflow doc, sections 2.1 and 3.5].
- The operator excludes impact, and the likelihood-only ranking stands [workbench R3-1].
- Hunters are dispatched per loop, and low-ranked loops stay dispatchable [workbench R2-2 and R2-14].
- The unit's risk profile is summed into a progressive risk budget, and the accumulator is run state, checked at each model completion [workbench R2-5].
- The comparison is inclusive, the crossing unit is completed and dispatched, and the next unit is never modelled [workbench R2-5].
- The scheme must satisfy four requirements: LLM-writable in YAML at minimal context cost, auditable, every direction retained at score 0 when infeasible or falsified, and deterministic aggregation as a per-unit sum against a constant threshold.
- The scheme must also satisfy five operator evaluation factors: low technical complexity, low overhead, modularity, low agent-context impact, and score accuracy.
- The workflow contract already fixes the shape: "Likelihood is qualitative (`high` / `medium` / `low`) with a one-line rationale" [workflow doc, section 2.1].
- The open first-party items are R3-2 (scale values, composition, threshold calibration) and R3-4 (LLM score variance, inflation, calibration) [workbench, Round 3].
- Existing loop vocabulary already includes the evidence rung (OBSERVED / INFERRED / ASSUMED), per-record evidences, a rationale, and a suite class [workbench R2-1 and R2-2].

## 2. Candidates

### 2.1 Three-level ordinal weights (low / medium / high -> 1 / 2 / 3), constant threshold

Mechanics:

- The modeller writes one class per loop, and the harness maps the class to a small integer through a fixed table.
- The unit score is the integer sum, and the run accumulator compares it against a constant; the operator's example constant is 12.

Primary-source facts:

- OWASP's risk rating methodology rates likelihood factors on a 0-9 scale, takes the average, and bands the result low (<3), medium (3 to <6), high (6-9) [OWASP Risk Rating Methodology, "Step 2" and "Step 4"].
- OWASP states that identifying whether the likelihood is low, medium, or high is generally sufficient, and that over-precision is not necessary [OWASP RRM, "Step 2"].
- OWASP combines likelihood with impact into a severity matrix; the operator's cut keeps the likelihood half only [OWASP RRM, "Step 4"].

Properties:

- Aggregation is pure integer arithmetic and therefore deterministic once the classes are fixed; the only tuning knob is the threshold constant.
- Audit is cheap: the class, the one-line rationale, the rung, and the evidences are enough to reconstruct the score.
- The zero state must be added explicitly, because three likelihood levels have no natural 0; a `none` class with weight 0 carries infeasible or falsified directions, so no direction is lost and none consumes budget.
- Quantisation loses detail, and one level step moves the unit sum by one point; ties inside a level are resolved by the modeller's ordered loop list, which the T2 trial already exercised (9 loops ranked, 1 high, 5 medium, 3 low) [first-party: `unit-threat-model-prototype/trials/t2-system-catalog-manager-shell/output/trace.md`].

### 2.2 Five-level ordinal extension

The machinery is identical to candidate 1; the enum widens and the threshold rescales.

Primary-source facts:

- NIST SP 800-30 Rev 1, Appendix G, Table G-2 defines a five-value qualitative likelihood scale: Very High (96-100), High (80-95), Moderate (21-79), Low (5-20), Very Low (0-4), with numeric equivalents 10 / 8 / 5 / 2 / 0 [NIST SP 800-30 Rev 1, Table G-2].
- CVSS also uses a five-band qualitative scale (None, Low, Medium, High, Critical), but it rates severity rather than likelihood [CVSS v4.0 specification, Table 22].

Evidence about finer scales for LLM raters:

- The COLING 2025 consistency study compares five LLM evaluators across four scoring scales (5-point interval, 10-point interval, 5-point Likert, and binary) and finds that different scoring scales produce divergent evaluations [Lee et al., "Evaluating the Consistency of LLM Evaluators"].
- The same study finds that non-numerical scales align worst with interval scales, that even a 5-point versus a 10-point interval pairing shows weaker alignment than expected, and that consistency is not implied by model capability [Lee et al.].
- A 2026 clinical ordinal-scoring audit finds a central-tendency effect in all three tested LLM families: predictions compress toward the middle of the scale, with over-prediction at the low end and under-prediction at the high end, and the effect survives few-shot exemplars and terminology ablations [Zhang et al., arXiv:2605.16386].
- Transfer caveat: both studies evaluate text-quality or clinical scales, not vulnerability likelihood; the transfer to this domain is an assumption to test, not a fact.

### 2.3 LLM numeric score (for example 0-100 per loop) with deterministic aggregation

Mechanics:

- The modeller writes an integer per loop, and the harness sums integers and compares the sum against a threshold.
- The zero case is natural for a falsified direction, but 0 would then mean "retained but dead" rather than "nearly impossible"; the schema must separate the two readings.

Primary-source facts about reliability:

- LLM evaluators are not necessarily consistent across scales, and consistency is an independent property from accuracy [Lee et al.].
- LLM judges carry documented position, verbosity, and self-enhancement biases plus limited reasoning ability; the MT-Bench study proposes mitigations rather than claiming the biases are absent [Zheng et al., arXiv:2306.05685].
- LLM raters show central-tendency compression on ordinal scales, with the largest errors at the clinically critical extremes [Zhang et al., arXiv:2605.16386].
- Verbalised confidence is encouraging on some tasks, but calibration degrades on new tasks: "models perform well at predicting P(IK) and partially generalize across tasks, though they struggle with calibration of P(IK) on new tasks" [Kadavath et al., arXiv:2207.05221].
- On CVSS prediction from CVE descriptions across 31,000+ entries, LLMs beat a baseline on some metrics, improve modestly on others, and share systematic misclassification patterns; ensemble meta-classifiers improve only marginally [Jafarikhah et al., arXiv:2512.06781].
- AutoCVSS reports that LLMs can complement supervised baselines in data-scarce settings and are the only viable approach with no annotated data; it does not claim superiority where annotated data exists [Sanvito et al., EMNLP 2025 Industry Track].

Audit and aggregation properties:

- A 0-100 score has no natural anchors, so drift across modeller versions is hard to detect and hard to defend in review.
- The per-unit sum then depends strongly on the number of kept loops, so a wide numeric scale makes breadth dominate the budget unless the composition normalises.
- No head-to-head primary study of ordinal versus scalar risk scores for LLM vulnerability likelihood was found in this pass; every accuracy claim here therefore rests on adjacent-domain evidence and is flagged as such.

### 2.4 CVSS v4.0-based scheme (likelihood-only reading)

What the standard defines:

- The Base metric group "is composed of two sets of metrics: the Exploitability metrics and the Impact metrics" [CVSS v4.0 specification, "Base Metrics"].
- The Exploitability metrics are Attack Vector (AV), Attack Complexity (AC), Attack Requirements (AT), Privileges Required (PR), and User Interaction (UI) [spec, "Exploitability Metrics"].
- The Impact metrics are Vulnerable System Confidentiality / Integrity / Availability (VC / VI / VA) and Subsequent System Confidentiality / Integrity / Availability (SC / SI / SA) [spec, "Impact Metrics"].
- The exact value sets are fixed [spec, Table 23]: AV [N, A, L, P]; AC [L, H]; AT [N, P]; PR [N, L, H]; UI [N, P, A]; VC / VI / VA [H, L, N]; SC / SI / SA [H, L, N].
- The operator's metric list omits User Interaction, which v4.0 places in the Exploitability group.

How the Base score is composed:

- The v4.0 score is not an algebraic sum of metric weights; the spec groups vectors into equivalence classes called MacroVectors, assigns each class a lookup score, and interpolates within each class [spec, "CVSS v4.0 Scoring using MacroVectors and Interpolation"].
- The macrovector axes (EQs) are EQ1 = AV / PR / UI, EQ2 = AC / AT, EQ3 = VC / VI / VA, EQ4 = SC / SI / SA, EQ5 = E, and EQ6 = VC / VI / VA plus CR / IR / AR [spec, Tables 24 to 30].
- The lookup table holds 270 entries in both reference implementations, verified directly in the FIRST calculator `cvss_lookup.js` and the Red Hat `constants4.py`.
- FIRST's FAQ states that the v4.0 method "is unique in relation to the algebraic formula of weighting metrics in CVSS v3.0 and v3.1", that there are roughly fifteen million valid vectors, and that scores come from expert ranking [CVSS v4.0 FAQ].

Consequences for a likelihood-only reading:

- No official exploitability-only output exists in v4.0; Exploitability is a metric group, not a score.
- The Base score always includes the impact metrics through EQ3 and EQ4; a live run of the Red Hat library on an all-None impact vector returns 0.0 with severity "None", so fixed "no impact" values cannot expose the exploitability component either.
- A lookup table over exploitability combinations is feasible only as a bespoke artefact; the exploitability subspace is 4 x 2 x 2 x 3 x 3 = 144 combinations, so a first-party table is small, reviewable, and deterministic, but the standard provides no such table.
- CVSS v3.1 is the last version with an official Exploitability sub-score equation: `Exploitability = 8.22 x AttackVector x AttackComplexity x PrivilegesRequired x UserInteraction`, with metric weights in Table 16 [CVSS v3.1 specification, sections 7.1 and 7.4].
- Even the v3.1 equation does not cover AT, which did not exist in v3.1; reusing the equation with v4.0 values would require invented weights for AT and for UI's third value.

Reference implementations and cost:

- FIRST publishes the calculator reference implementation in JavaScript (BSD-2-Clause licence) [FIRST cvss-v4-calculator repository, LICENSE].
- Red Hat publishes the `cvss` Python library, which the FIRST FAQ lists as the origin of the official calculator; PyPI shows version 3.6 with the LGPLv3+ package licence, while `cvss4.py` carries a file-level BSD-2-Clause notice [PyPI `cvss`; Red Hat repository].
- Neither v4.0 implementation exposes an exploitability-only output; verified by source inspection and by running the library, where the public members are `base_score`, `metrics`, `missing_metrics`, `original_metrics`, `severity`, and `vector`.
- The computation itself is small (a lookup table plus interpolation), but the pipeline costs agent context: 11 mandatory base metrics per loop plus a scoring rubric, and it answers a severity question rather than the likelihood question.
- Validation is the real cost: FIRST states that the SIG cannot check calculators, that it makes no guarantees about the listed community libraries, and that validation is a project (roughly 15 million valid vectors; reference sets of about 50,000 records) [CVSS v4.0 FAQ, "How can I implement a CVSS calculator for my own organization?"].

Licensing:

- FIRST states: "While FIRST owns all rights and interest in CVSS, it licenses it to the public freely for use, subject to the conditions below" [spec, preamble; repeated in the FAQ].
- FIRST requires proper attribution from users of CVSS, and it requires anyone publishing CVSS data to provide both the score and the vector string [spec, preamble].
- The practical consequences for this design are light but real: embedding a calculator is legally cheap, a derived likelihood number must not be presented as a CVSS score, and CVSS-derived terminology needs attribution.

### 2.5 Hybrid: CVSS-style qualitative fibre mapped deterministically to a small ordinal class

Mechanics:

- The modeller writes the five exploitability descriptors per loop (AV, AC, AT, PR, UI), and the harness maps each descriptor combination to a small likelihood class through a fixed bespoke table; the class then aggregates as in candidate 1.
- The full mapping space is 144 combinations, so the table is small enough to review by hand.

Facts:

- The descriptors and their values are precisely defined, including the UI distinction between Passive and Active, with worked guidance for reflected XSS, stored XSS, and CSRF [CVSS v4.0 specification, Table 5; CVSS v4.0 FAQ].
- The descriptors describe a concrete vulnerability assessed under perfect attacker knowledge; the Base metric assessment guidance assumes that the analyst knows the exploitation conditions [spec, "Exploitability Metrics"].
- The v4.0 EQ structure shows that AV, PR, and UI interact non-linearly (EQ1 merges them into one level) and that AC and AT merge into one level (EQ2) [spec, Tables 24 and 25]; a bespoke mapper should respect that grouping or it will disagree with the standard's own ordering.
- No published mapping from the exploitability descriptors to a likelihood class exists; the mapper is first-party content and inherits no validation.

Costs and benefits:

- Benefit: decomposed judgements are checkable per descriptor, so audit is stronger, and the descriptors give each rationale a shared vocabulary.
- Cost: five decisions per loop plus a descriptor rubric in the agent context; guessed descriptors produce pseudo-precision; and the vocabulary carries the CVSS attribution hygiene from section 2.4.

## 3. Comparison against the five factors

| Factor | C1: 3-level ordinal | C2: 5-level ordinal | C3: LLM numeric | C4: CVSS v4.0 pipeline | C5: hybrid fibre |
|---|---|---|---|---|---|
| Technical complexity | Lowest: one enum, one weight table, integer sum. | Low: the same code with a wider enum. | Low runtime, high semantic ambiguity. | High: spec port or embed, macrovectors plus interpolation; or a v3.1 equation extended with invented AT weights. | Medium: a bespoke 144-row mapper plus a descriptor rubric. |
| Overhead | Minimal: one token per loop, trivial sum. | Minimal: the same shape. | Minimal runtime, high review cost because values are unanchored. | Small runtime, high prompt and validation cost. | Medium: five descriptor values per loop, low runtime. |
| Modularity | High: weights and threshold live in config, and enum widening is additive. | High: a strict superset of C1. | Medium: no anchors, and threshold semantics need a normalisation decision. | Low: coupled to CVSS vocabulary and its release cycle, and it computes severity, not likelihood. | Medium: the mapper is separable, but the rubric couples to CVSS wording. |
| Agent-context impact | Lowest. | Low: a fixed rubric block that is cacheable. | Low token count, but ambiguity invites rationalisation. | Highest: 11 mandatory metrics plus rubric per loop. | Medium: five descriptors plus rubric. |
| Score accuracy | Good with anchors; coarse at one point per level, and ties are resolved by the ordered loop list. | Potentially finer, with no direct evidence in this domain; LLM scale-sensitivity warns against assuming that finer is better. | No evidence of reliable calibrated numeric scores, and biases and central tendency are documented in adjacent domains. | Measures the wrong construct for this requirement; no official exploitability-only output, so accuracy claims would concern severity rather than likelihood. | Best on paper through decomposed judgement, but unvalidated, with pseudo-precision risk. |

## 4. Recommendation

Recommendation: adopt candidate 1's mechanics now, with a single anchored ordinal class per loop (`low` / `medium` / `high` mapped to 1 / 2 / 3, plus `none` mapped to 0 for retained-but-dead directions), and keep candidate 2 as a documented, cheap upgrade path once a calibration trial shows that the modeller discriminates five levels reliably.

Rationale:

- Candidate 1 meets every stated requirement with the least machinery: LLM-writable in YAML at minimal context cost, auditable through class plus rationale plus rung, deterministic integer sums against a constant, and a built-in zero state for direction retention.
- The three-band choice follows OWASP's own sufficiency guidance, and it matches the already-decided workflow contract plus both completed trials, so the recorded models stay comparable [OWASP RRM; workflow doc].
- Primary evidence on LLM raters points away from finer scales and away from unanchored numeric scores: scale choice changes results, non-numerical scales diverge from interval scales, and central-tendency compression distorts endpoint scores [Lee et al.; Zhang et al.; Zheng et al.].
- Candidate 2 is structurally nearly free and NIST SP 800-30 gives it a standards precedent, but no evidence yet shows that the modeller can use five levels rather than merely write them; widening the enum before a calibration trial adds audit cost without proven accuracy.
- Candidate 3 is rejected: adjacent-domain evidence shows that unanchored numeric scoring is unstable and biased, the sum becomes breadth-sensitive, and the audit trail gets weaker rather than stronger.
- Candidate 4 is rejected for this requirement: CVSS v4.0 defines no official likelihood-only output, its composition is expert-ranked severity that always includes impact, the operator's metric list omits UI, and the embedding plus validation cost is disproportionate to the benefit.
- Candidate 5 is deferred rather than rejected: it is the natural next layer if calibration shows that holistic classes drift, and its mapper is small; adopting it now would front-load CVSS vocabulary, attribution hygiene, and pseudo-precision risk before any measured need.
- The weight table and the threshold constant belong in harness configuration, never in the prompt, so calibration changes do not rewrite agent context.

Calibration note:

- The threshold is a tuning constant, not a derived quantity, so the operator's example value of 12 is only a starting point.
- A recorded-data sanity check exists: the T2 trial ranked 9 loops (1 high, 5 medium, 3 low), which sums to 16 under 3 / 2 / 1 weights, so a constant of 12 would be crossed by that single unit's completion.
- The right value should come from replaying recorded models and choosing the halt behaviour the operator wants; R3-2 remains open on this point [workbench R3-2].

## 5. Implementation sketch

What the modeller writes per loop (at the COMPLETED gate write, with existing fields omitted):

- `likelihood: high | medium | low | none`
- `likelihood_rationale: <one line>`
- The existing `rung`, `evidences`, and references stay as they are.
- For `none`, the rationale names the infeasibility or the falsification, and the loop is retained in place; nothing is dropped from the document.

What the harness computes (symbolic, outside the agent):

- `weight = LIKELIHOOD_WEIGHTS[loop.likelihood]`, with the map `{none: 0, low: 1, medium: 2, high: 3}` in configuration.
- `unit_total = sum(weights)` over every loop of the model, plus a per-level breakdown for the run record.
- `run_total += unit_total`, followed by the comparison `run_total >= THRESHOLD`.

Threshold mechanics:

- One constant per run, recorded in the run with its calibration basis.
- The comparison is inclusive; the crossing unit completes and is dispatched; the next unit is never modelled and is recorded as blocked [workbench R2-5].
- Zero-weight loops do not change the sum, but they stay counted in the audit breakdown as `none`.

Score-0 retention:

- A `none` loop stays in the YAML with its rationale, rung, and evidences.
- It contributes 0 to the unit total, and the surfer does not dispatch a hunter to it, because no feasible failure mode exists.
- It remains available for audit and for a later run, so the document always carries the full set of research directions.
- This mechanism satisfies the retention requirement: the document never loses a direction, and only the budget arithmetic ignores dead directions.

Optional extension hooks:

- Five levels: widen the enum, retune the weight table, and keep the arithmetic; the mapping from recorded 3-level models to 5 levels must be defined when the change happens.
- Rung-conditional weighting (for example, discounting ASSUMED claims): deliberately not adopted now, because it would mix evidence maturity into the score and complicate audit; it is listed as an open question.
- Cross-unit dispatch sequencing is unaffected, because both the class and the ordered loop list remain available [workbench R2-14].

Worked example:

- Loops: 1 high, 5 medium, 3 low, 2 none. Weights: 3 + 10 + 3 + 0 = 16.
- The run accumulator adds 16, applies the inclusive threshold test, and records the per-level breakdown.

## 6. Open questions

- Threshold calibration: who runs it, on which recorded models, and who ratifies the constant; R3-2 remains open [workbench R3-2].
- Breadth coupling: the sum counts loops, so a unit with many low loops can consume the budget like a unit with a few high loops. The options are to accept it, to count only non-zero loops, or to add per-level caps. Breadth is an operator feature, so the budget should not penalise it by accident.
- Discrimination test: does the modeller use five levels reliably enough to justify candidate 2? A repeat-run agreement experiment on recorded units would answer this.
- Rung interaction: should an ASSUMED high loop count the same as an OBSERVED high loop? Deferred, and any conditioning must stay deterministic.
- `none` visibility: should dead directions remain visible to hunters as context, or be inert in the store?
- Transition mapping: recorded models use high / medium / low, so any enum change needs an explicit mapping rule.
- Cross-run semantics: completed models are excluded from intake, so confirm that the accumulator resets per run and that the cross-unit budget reads the same per-unit sums [workbench R2-5 and R2-9].
- Evidence caveat: no head-to-head primary study of ordinal versus scalar risk scoring by LLMs for vulnerability likelihood was found; the accuracy arguments here rest on adjacent-domain evidence and are flagged as such.
- CVSS hygiene: if candidate 5 is ever adopted, the mapper must be presented as first-party scoring, not as a CVSS score, and CVSS-derived wording needs attribution.

## 7. Sources

Primary standards and first-party implementation sources:

- CVSS v4.0 specification document: https://www.first.org/cvss/v4.0/specification-document (metric groups, Tables 22 to 30, macrovector scoring, licensing preamble).
- CVSS v4.0 FAQ: https://www.first.org/cvss/v4.0/faq (calculator validation, community library list, v3.1 versus v4.0 scoring, UI guidance, licensing paragraph).
- CVSS v3.1 specification document: https://www.first.org/cvss/v3.1/specification-document (Exploitability sub-score equation, sections 7.1 and 7.4; Table 16 weights).
- FIRST reference calculator, JavaScript, BSD-2-Clause: https://github.com/FIRSTdotorg/cvss-v4-calculator (270-entry lookup table in `cvss_lookup.js`).
- Red Hat `cvss` Python library: https://github.com/RedHatProductSecurity/cvss and https://pypi.org/project/cvss/ (version 3.6; package LGPLv3+; `cvss4.py` file-level BSD-2-Clause; 270-entry `CVSS_LOOKUP_GLOBAL`; verified run: all-None impact scores 0.0 and no `exploitability` attribute).
- OWASP Risk Rating Methodology: https://owasp.org/www-community/OWASP_Risk_Rating_Methodology (likelihood factors, averaging, low / medium / high bands, risk composition).
- NIST SP 800-30 Rev 1: https://csrc.nist.gov/pubs/sp/800/30/r1/final and the PDF at https://nvlpubs.nist.gov/nistpubs/Legacy/SP/nistspecialpublication800-30r1.pdf (Appendix G, Table G-2: five-value qualitative likelihood scale).
- CWE-79 weakness page, likelihood-of-exploit property: https://cwe.mitre.org/data/definitions/79.html

LLM scoring evidence:

- Lee, Hong, and Thorne, "Evaluating the Consistency of LLM Evaluators", COLING 2025: https://aclanthology.org/2025.coling-main.710/ and https://arxiv.org/abs/2412.00543 (inter-scale consistency across scoring scales).
- Zheng et al., "Judging LLM-as-a-Judge with MT-Bench and Chatbot Arena", NeurIPS 2023: https://arxiv.org/abs/2306.05685 (judge biases).
- Kadavath et al., "Language Models (Mostly) Know What They Know": https://arxiv.org/abs/2207.05221 (verbalised confidence and calibration limits).
- Jafarikhah et al., "From Description to Score: Can LLMs Quantify Vulnerabilities?": https://arxiv.org/abs/2512.06781 (31,000+ CVEs; metric-level prediction performance).
- Sanvito et al., "AutoCVSS: Assessing the Performance of LLMs for Automated Software Vulnerability Scoring", EMNLP 2025 Industry Track: https://aclanthology.org/2025.emnlp-industry.38/ (data-scarce complement, not replacement).
- Zhang et al., "Auditing Multimodal LLM Raters: Central Tendency Bias in Clinical Ordinal Scoring": https://arxiv.org/abs/2605.16386 (endpoint compression on ordinal scales).
- Microsoft, "Measuring Quality with LLM Judges" white paper, non-peer-reviewed first-party source: https://microsoft.github.io/mcscatblog/assets/posts/better-llm-scoring/20260626_LLM1-5Scoring_WhitePaper.pdf

First-party polymerhus context, not external sources:

- `docs/design/unit-threat-model-workflow.md` (loop contract; qualitative likelihood with rationale).
- `docs/design/unit-threat-model-workbench.md` (R2-5 budget mechanics, R3-1 risk criterions, R3-2 open calibration, R3-4 unreliability).
- `docs/experiments/unit-threat-model-prototype/trials/` (recorded loop counts and rankings).

Access notes:

- The FIRST terms-of-use page rendered navigation only, so the licensing paragraph was read from the specification and FAQ pages, which carry it verbatim.
- The SAGE article "On the Consistency of Automatic Scoring with Large Language Models" (https://journals.sagepub.com/doi/10.1177/00131644261418138) returned HTTP 403, and no claim here relies on it.
- `cvss.readthedocs.io` does not exist (HTTP 404), so the library README and source were used instead.
- Web search tooling was unavailable in this environment, so paper discovery used direct fetches of publisher pages and search-result pages.
