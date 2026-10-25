---
artifact: experiment-results
version: "1.0"
created: 2026-10-25
status: baseline-measured
---

# Experiment Results: Threat-modeller impact quality baseline

## Summary

| Attribute | Value |
|---|---|
| **Experiment ID** | `modeller-impact-quality-2026-10-25` |
| **Experiment name** | Threat-modeller impact quality baseline |
| **Status** | Completed baseline measurement; no treatment arm yet |
| **Population** | One hunting run on `eval-server-1` |
| **Project** | `0c8cb6e6-7e91-4a01-880e-408896c0ce4a` |
| **Run** | `a5f487fb-8329-431c-b95d-207799a038f9` |
| **Artifact root** | `/opt/polymerhus-dev/eval/instances/data/eval-server-1/0c8cb6e6-7e91-4a01-880e-408896c0ce4a/hunting/threat_modeller` |
| **Models** | 17 unit models: 13 produced, 1 consumed, 3 abandoned |
| **Loops** | 113 |
| **Primary metric** | Share of loops in low-yield impact families |
| **Design** | Full census, not an A/B test |

This document records the baseline defect that the impact-first elicitation workstream must fix.
It is a census of one completed run, so counts are exact for that run and no inferential test applies.
The unit of analysis is the loop, because the loop is the dispatch grain and the artifact the modeller publishes.

## Measurement question

The operator reported that the modeller's interface agreements, control flows, and data flows are solid, but that quality degrades from the trust assumptions and faults downstream.
The reported symptoms are:

- low-yield and low-impact vulnerabilities dominate the model;
- the trust assumptions do not name the attacker-controlled artifacts and the security-sensitive variables that carry the highest impact potential;
- the failure mode is scoped to a service contract and blocks impact scoring;
- technique families such as `defence-bypass` and `proxy-techniques` are used as vulnerability classes.

This measurement tests those symptoms on the persisted artifacts.
It does not test a prompt change, because no change has landed.

## Method

### Population

The survey reads every unit model under `threat_modeller/produced`, `threat_modeller/consumed`, and `threat_modeller/abandoned`.
It reads the loop records from the model document, not from the separate `loop-N.yaml` files, so the ranked order and the model's own classes are preserved.
It resolves each loop's fault, assumption, trust agreement, vulnerability, and failure mode by id.

The run emitted 17 models and 113 loops.
Of those, 10 loops were dispatched to the hunter (`hunter/test-specs/Service-sign-in__loop-1..10`).
The other 103 loops were never dispatched before the 7,000,932 capped-token budget stopped the run.

### Impact tier rubric

The tier is the impact if the loop's stated mechanism holds.
It is not the likelihood and not the model's own `likelihood` value.

- **severe**: a plausible path to code execution, cross-user or cross-tenant data access or action, privilege escalation, authentication or session compromise, XSS, SSRF, arbitrary file read or write, or a business-logic effect that changes another principal's state.
- **conditional**: a security weakness whose end effect needs a precondition or a second primitive that the model itself does not establish.
- **low**: the model's own end effect is metadata disclosure, enumeration, throttling, diagnosis or observability, contract or UI consistency, or availability of a non-critical function.

The rubric follows the operator's target families.
It counts XSS, SSRF, access control, mass assignment, business logic, race conditions, session compromise, and code execution as severe.
It counts information disclosure, rate limiting, enumeration, and contract divergence as low.
A weak disclosure that leaks a live credential is severe, not low, because the end effect is account takeover.
A session weakness that needs a second session first is low, because the end effect is confined.

### Boundary-shape tags

Each loop receives one primary boundary shape.
The tag records what crosses the trust boundary.

- `artifact->decision`: an attacker-influenced artifact crosses into a security decision. This is the sharp shape.
- `principal->authority`: a principal or a permission crosses into an authority decision.
- `state->decision`: a state transition or a stored state crosses into a decision.
- `contract->consumer`: a response or contract crosses into a consumer's reading.
- `observation->inference`: an observation crosses into a caller's or operator's inference.
- `component->component`: two components disagree, with no attacker artifact.
- `server->client`: server metadata or content crosses into the client.
- `client->server`: client-supplied data crosses into the server.

### Class integrity

The suite has 41 class parents and 124 variant leaves under `skills/web-vulnerability-testing`.
A name is a class parent when it is a level-1 directory with a `SKILL.md`.
A name is a leaf when it is a second-level directory with a `SKILL.md`.
`defence-bypass` and `proxy-techniques` are class parents in the tree, but they are technique families semantically.
A name outside the tree is a fabricated class.

### Token accounting

The project `usage.yaml` records 8 agents and 7,000,932 capped tokens.
The modeller records 429 calls, 99,254,895 total tokens, and 2,179,055 capped tokens.
Capped tokens are uncached input plus generated output.
The per-loop figures are output-efficiency ratios, not per-loop billing, because the modeller bills per model and per call.

## Primary result

The low-yield share is 70 of 113 loops, or 61.9%.
The severe share is 25 of 113, or 22.1%.
The conditional share is 18 of 113, or 15.9%.
Low and conditional together are 88 of 113, or 77.9%.

| Tier | Loops | Share |
|---|---:|---:|
| severe | 25 | 22.1% |
| conditional | 18 | 15.9% |
| low | 70 | 61.9% |
| **total** | **113** | **100%** |

The primary metric fails the operator's stated target.
The operator wants the mass shifted toward severe families.
The measured mass is two thirds low-yield.

## Secondary results

### Impact families

| Family | Loops | Share | Severe | Conditional | Low |
|---|---:|---:|---:|---:|---:|
| contract-integrity | 41 | 36.3% | 0 | 0 | 41 |
| information-disclosure | 16 | 14.2% | 0 | 2 | 14 |
| authentication-session | 14 | 12.4% | 10 | 2 | 2 |
| access-control | 13 | 11.5% | 7 | 6 | 0 |
| enumeration | 9 | 8.0% | 0 | 0 | 9 |
| XSS | 6 | 5.3% | 6 | 0 | 0 |
| CSRF and clickjacking | 3 | 2.7% | 1 | 1 | 1 |
| RCE, deserialization, upload | 3 | 2.7% | 1 | 2 | 0 |
| business logic | 2 | 1.8% | 0 | 2 | 0 |
| supply chain | 2 | 1.8% | 0 | 1 | 1 |
| injection | 2 | 1.8% | 0 | 1 | 1 |
| rate limit | 1 | 0.9% | 0 | 0 | 1 |
| SSRF | 1 | 0.9% | 0 | 1 | 0 |

Contract integrity alone is 36.3% of the corpus and contributes zero severe loops.
Information disclosure and enumeration together are 25 loops, or 22.1%, and contribute zero severe loops.
The severe mass is concentrated in authentication-session, access-control, and XSS: 23 of the 25 severe loops.

### Boundary shape

| Shape | Loops | Share |
|---|---:|---:|
| artifact->decision | 32 | 28.3% |
| contract->consumer | 24 | 21.2% |
| observation->inference | 20 | 17.7% |
| state->decision | 11 | 9.7% |
| component->component | 9 | 8.0% |
| server->client | 8 | 7.1% |
| principal->authority | 7 | 6.2% |
| client->server | 2 | 1.8% |

Only 28.3% of loops carry the sharp shape.
The remaining 71.7% model a contract, an observation, a state, or a component disagreement.
This is the structural signature of the reported defect: the trust model is a software-contract conformance model, not an attacker-capability model.

### Likelihood and impact

| Likelihood | All loops | Severe | Low |
|---|---:|---:|---:|
| critical | 1 | 1 | 0 |
| high | 14 | 7 | 6 |
| medium | 29 | 11 | 12 |
| low | 67 | 6 | 50 |
| none | 2 | 0 | 2 |

Six severe loops are ranked `low`, and eleven are ranked `medium`.
Eighteen of the 25 severe loops sit below `high`.
The ranking is impact-blind by construction, so these loops are demoted behind higher-likelihood low-yield directions.

The clearest case is `Service:sign-in`.
Its ranked order is rate-limit, account enumeration, cleartext session hijacking, session fixation, CSRF forced sign-out, published default administrator credential, session id in URL, and pre-authentication deserialization.
The top two are low-yield recon and rate-limit directions.
The RCE-capable deserialization surface is rank 8.

### Class integrity

| Class status | Loops | Share |
|---|---:|---:|
| class parent | 39 | 34.5% |
| class leaf | 22 | 19.5% |
| empty and suite gap | 45 | 39.8% |
| technique family used as class | 5 | 4.4% |
| name not in the suite | 2 | 1.8% |

The five technique-family uses are four `defence-bypass` and one `proxy-techniques`.
The two fabricated names are `unrestricted-file-upload` for `insecure-file-uploads` and `ssrf-blind-callback-confirmation` for `ssrf`.
Seven of the 68 loops with a non-empty class, or 10.3%, use a technique family or a non-suite name.

The suite gap is concentrated in the low tier: 41 of the 70 low loops have no class.
Only 2 of the 25 severe loops have no class.
Those two are both XSS: `Per-View Encoding Policy Divergence` and `Client-Computed Representation Accepted as Authoritative`.
The modeller found the stored-markup sink but classified it as a contract issue, so the hunter would not receive the XSS class.

### Token economics

| Metric | Value |
|---|---:|
| Run capped budget | 7,000,932 |
| Modeller capped spend | 2,179,055 |
| Modeller share of cap | 31.1% |
| Modeller calls | 429 |
| Modeller total tokens | 99,254,895 |
| Capped per emitted loop | 19,284 |
| Total tokens per emitted loop | 878,362 |
| Capped per severe loop | 87,162 |
| Loops dispatched | 10 of 113 |
| Dispatch coverage | 8.8% |
| Hunter capped spend | 1,254,212 |
| Hunter capped per dispatched spec set | 125,421 |

The modeller consumed 31.1% of the cap and produced 113 loops, of which 10 reached the hunter.
The pro-rata low-yield share of modeller capped spend is 1,348,835, or 61.9%.
The pro-rata severe share is 481,571, or 22.1%.
The pro-rata figure assumes a uniform cost per loop; the true cost is per model and per call, so treat it as an order-of-magnitude estimate.

The token conclusion is not that the modeller is too expensive in absolute terms.
The conclusion is that the run buys 113 directions and can afford to hunt 10.
At that ratio, the quality of each direction dominates the economics, and 70 low-yield directions crowd out the severe ones.

## Segment analysis

### By artifact bucket

| Bucket | Loops | Severe | Conditional | Low | Low share |
|---|---:|---:|---:|---:|---:|
| produced | 86 | 17 | 16 | 53 | 61.6% |
| consumed | 10 | 5 | 0 | 5 | 50.0% |
| abandoned | 17 | 3 | 2 | 12 | 70.6% |

The consumed model is `Service:sign-in`, the only model the run dispatched.
Its 50% severe share is higher than the produced average, but its ranking still places low-yield directions first.

### By unit kind

| Kind | Loops | Severe | Severe share | Low | Low share |
|---|---:|---:|---:|---:|---:|
| service | 42 | 8 | 19.0% | 28 | 66.7% |
| system | 71 | 17 | 23.9% | 42 | 59.2% |

The system units carry slightly more severe mass, driven by `AuthorizationSystem`, `AuthenticationMechanism`, and the cross-origin policy.
The service units carry more low-yield contract integrity.

### By unit

| Unit | Loops | Severe | Conditional | Low | Low share |
|---|---:|---:|---:|---:|---:|
| IdentificationSystem | 6 | 0 | 0 | 6 | 100.0% |
| Service:library-catalog | 7 | 0 | 1 | 6 | 85.7% |
| WebPresentation:library-catalog::catalogue-pages | 6 | 0 | 1 | 5 | 83.3% |
| Service:article-management | 6 | 1 | 0 | 5 | 83.3% |
| Service:jotter-reading | 6 | 1 | 0 | 5 | 83.3% |
| WebPresentation:register::registration-page | 7 | 1 | 1 | 5 | 71.4% |
| Service:navigation-menu | 6 | 0 | 2 | 4 | 66.7% |
| WebPresentation:sign-in::credential-pages | 6 | 1 | 1 | 4 | 66.7% |
| ReverseProxy | 5 | 1 | 1 | 3 | 60.0% |
| RESTApi:api | 7 | 0 | 3 | 4 | 57.1% |
| WebPresentation:article-management::console-pages | 7 | 2 | 1 | 4 | 57.1% |
| Service:sign-in | 10 | 5 | 0 | 5 | 50.0% |
| WebPresentation:jotter-reading::reading-pages | 6 | 2 | 1 | 3 | 50.0% |
| AuthenticationMechanism | 7 | 3 | 1 | 3 | 42.9% |
| Service:register | 7 | 1 | 3 | 3 | 42.9% |
| AuthorizationSystem | 8 | 4 | 1 | 3 | 37.5% |
| IntegrationSystem:cross-origin-policy | 6 | 3 | 1 | 2 | 33.3% |

The read-only presentation and catalogue units produce the highest low-yield shares.
`IdentificationSystem` is 100% low.
`Service:library-catalog` is 85.7% low.
`RESTApi:api`, the API surface, produces no severe loop at all: three conditional and four low.
The units with a clear authority or data boundary produce the severe mass: `AuthorizationSystem` at 37.5% low, `IntegrationSystem:cross-origin-policy` at 33.3% low, and `AuthenticationMechanism` at 42.9% low.

This is the linear degradation the operator described.
The sharpening and the interface agreements are strong on every unit.
The assumptions and faults on units without an obvious attacker-controlled artifact drift into contract integrity, and the downstream loops inherit that drift.

## Shape of the low-yield families

### Contract integrity: 41 loops, zero severe

This is the largest family and the clearest defect.
Representative trust boundaries are:

- `denial state -> caller's inference`;
- `response message -> the store's state`;
- `save -> publication`;
- `absence -> the caller's decision`;
- `collection -> its own completeness`;
- `page identity -> the client`;
- `route -> its ordering`;
- `failure cause -> diagnosis`.

Representative faults are `refusal and empty success collapsed into one response`, `response composed from request acceptance`, `publication fused with saving`, `page inventory held only by the client build`, and `single undifferentiated failure envelope`.
The assumption type is consistent: the response is treated as a faithful description of the system's state, and a divergence between two descriptions is treated as the vulnerability.
The attacker is absent from the chain.
The harm is to a consumer's reasoning, to an operator's diagnosis, or to a client's state.

The evidence is usually a direct probe of the divergence, so the confidence is `OBSERVED`.
The complexity is `low` because no precondition is needed to observe the divergence.
The likelihood therefore lands at `medium` even when the end impact is explicitly zero.
The `Service:navigation-menu` V-2 loop is the canonical case.

### Information disclosure: 16 loops, 14 low

The boundaries are `edge -> client fingerprint`, `stored data -> response`, `server metadata -> caller`, `third-party fetch -> referrer`, and `content type -> browser`.
The faults are a version token, a republished stored URL, a framework error page, and a missing content-type assertion.
The assumption type is that disclosure of non-secret metadata is an end impact.
Two loops are conditional because the disclosure can reach a live credential: the refusal-redirect session id and the per-principal cache.
The other fourteen are low.

### Enumeration: 9 loops, all low

The boundaries are `login outcome -> knowledge of the identity space`, `gate verdict -> caller and observer`, `refusal producer -> caller inference`, and `menu grants -> permission grants`.
The faults are distinct failure text, an empty-200 denial, per-layer refusal shapes, and a route-existence differential.
The assumption type is that reconnaissance is the impact.
The model itself calls the effect `the reconnaissance step a credential attack consumes`, but it does not model the credential attack as the end impact.
The loop is therefore recorded as the vulnerability rather than as an enabler.

### Rate limit: 1 loop, low

The boundary is `credential verifier -> attempt accounting`.
The fault is a missing attempt counter.
The loop is observed at high likelihood because repetition is admitted at request throughput.
The end impact is the brute-force attack that the loop enables, but the model records the missing counter, not the account takeover.
This is the operator's low-yield family in its purest form: a real weakness, but a prerequisite for the severe effect.

### Technique families as classes: 5 loops

`defence-bypass` is used for a path-filter bypass, an origin-verdict coverage gap, an authorization-map guard, and an identity normalization mismatch.
`proxy-techniques` is used for an unpinned third-party stylesheet.
The class name describes how the defence is bypassed, not what the vulnerability is.
The underlying classes are broken function-level authorization, path traversal, cache deception, and parser differential.
The hunter binds the class skill, so a technique family gives the hunter a technique procedure instead of the class procedure.

Two further loops use names that do not exist in the suite.
`unrestricted-file-upload` should be `insecure-file-uploads`.
`ssrf-blind-callback-confirmation` should be `ssrf`, and the loop is not even server-side SSRF: it is a stored URL that drives a reader's browser fetch.
The store validator checks that the loop copies the vulnerability's class, but it does not check that the name exists in the suite, so both errors persist.

## Evidence of the defect

### The V-2 example

`Service-navigation-menu` V-2 is `Denied Equivalent to Empty Success`.
Its characterisation says:

> The consequence is not a leak but an inability to reason.

The failure mode says the console renders an empty navigation for a denial exactly as it would for an account that was never granted anything.
The loop is ranked `medium` and carries `OBSERVED` confidence.
The end impact is explicitly zero for an attacker.
This is not an isolated miss: it is the archetype of the 41-loop contract-integrity family.

### Explicit no-impact language

Eight loops state in their own characterisation or rationale that the effect is not an attacker effect.
The phrases are:

- `the consequence is an inability to verify rather than an exposure` (`IdentificationSystem` loop-5);
- `No attacker effect is reachable ... the failure is operator-side blindness` (`IdentificationSystem` loop-6);
- `the effect is cost and payload, not access` (`WebPresentation:jotter-reading::reading-pages` loop-5);
- `confined: the server refuses the value, so the retained credential grants nothing` (`AuthenticationMechanism` loop-6);
- `The consequence is not access but diagnosis` (`RESTApi:api` loop-7);
- `no attacker effect is reachable through it` (`Service:article-management` loop-6);
- `the effect is confined to what a caller can conclude about the category space` (`Service:library-catalog` loop-7);
- `not a leak but an inability to reason` (`Service:navigation-menu` loop-2).

These are not inference errors by the reviewer.
The modeller records the absence of impact and still emits the loop at `medium` or `low` likelihood.

### Misclassified severe loops

Two severe loops have no suite class because the modeller framed them as contract issues:

- `WebPresentation:jotter-reading::reading-pages` loop-4, `Per-View Encoding Policy Divergence`, is the same stored-XSS sink as loop-1, but it is recorded without the XSS class.
- `WebPresentation:article-management::console-pages` loop-1, `Client-Computed Representation Accepted as Authoritative`, stores the browser-rendered HTML that every reader executes, but it is recorded without the XSS class.

The defect is therefore both omission and misclassification.
The modeller can find the severe mechanism and then file it under a contract label, which removes it from the class-bound hunter path.

### Ranking evidence

`Service:sign-in` is the only model that reached the hunter.
Its ranked order puts rate-limit and enumeration first, and deserialization eighth.
The hunter received the two low-yield directions first.
This is the impact-blind ranking in production, not a hypothetical.

## Learnings

1. **The trust model is a contract-conformance model.**
   Only 28.3% of loops carry an attacker-artifact-to-security-decision boundary.
   71.7% model a contract, an observation, a state, or a component disagreement.
   The trust agreements are precise about what each component promises, but they do not consistently name the attacker-controlled field and the security-sensitive variable it reaches.

2. **The low-yield mass is structural, not incidental.**
   Contract integrity is 36.3% of the corpus and contributes zero severe loops.
   Information disclosure and enumeration add another 22.1% and also contribute zero.
   The severe mass is concentrated in three families: authentication-session, access-control, and XSS.

3. **Observed divergence is mistaken for impact.**
   A contract mismatch is directly observable, so it earns `OBSERVED` confidence and `low` complexity.
   The likelihood model then ranks it above a severe loop whose exploit path needs a precondition.
   The likelihood score is doing what it was designed to do; the missing impact axis is what lets the divergence win.

4. **The class vocabulary is technique-first.**
   Five loops use a technique family as the class, and two use a name outside the suite.
   The modeller follows the suite tree, but the tree contains technique families at the same level as vulnerability classes, and the prompt does not forbid their use as classes.

5. **The impact-blind ranking demotes severe work.**
   Six severe loops are `low`, eleven are `medium`, and eighteen of twenty-five sit below `high`.
   The `Service:sign-in` order is the concrete case: rate-limit and enumeration before session fixation and deserialization.

6. **The token economics invert the quality signal.**
   The modeller spends 31.1% of the capped budget and produces 113 loops.
   Ten loops reach the hunter.
   At 19,284 capped tokens per emitted loop and 87,162 per severe loop, the run cannot afford to be wrong about which directions matter.

7. **The severe mechanisms are present but mislabeled.**
   The stored-XSS sink appears in three units.
   The path-shape authorization bypass appears in two units.
   The mass-assignment privilege escalation appears in `Service:register`.
   The modeller can find them; it does not consistently classify them, rank them, or score their impact.

### Surprising findings

- The consumed model has the highest severe share (50%), so the defect is not that the modeller cannot find severe issues in the unit it hunts.
  The defect is the tail it produces around them and the order it assigns.
- `RESTApi:api` produces no severe loop despite being the API surface.
  Its seven loops are four contract issues and three conditional cross-origin or parameter issues.
- The suite gap is almost entirely a low-tier phenomenon: 41 of 45 gaps are low loops.
  The modeller correctly recognizes that contract issues have no suite class, but it does not treat that recognition as a signal that the loop is not a vulnerability.

### What we still do not know

- Whether the low-yield mass is caused primarily by the prompt's Branch A wording, by the absence of an impact field, or by the unit mix.
  The experiment is a census, not an ablation.
- Whether a prompt-only framework change is enough, or whether the typed model must carry the artifact, the security decision, and the impact to make the reasoning enforceable.
- Whether the severe share can rise without increasing the modeller's token spend beyond its current 31.1% share of the cap.
- Whether the same distribution holds on a different target or a different unit mix.

## Recommendation

### Decision: Iterate

The baseline confirms the operator's defect at the artifact level.
The defect is not a single prompt wording issue.
It is a missing impact axis, an under-specified trust-boundary procedure, a technique-first class vocabulary, and a retrospective check that is optional.

The workstream should implement the following changes and re-measure on the same unit set:

1. **Impact-first trust modelling.**
   Give Branch A the same prompt weight as Branch B, add the canonical trust-boundary characterization framework, and require each trust agreement to name the artifact, the controlling principal, the security decision, and the worst-case end impact.

2. **Field-level assumption brainstorming.**
   Require the artifact and field inventory, the component and data state model, and the data-plane and control-plane wiring before the assumptions are written.

3. **End-impact scoring.**
   Add the CVSS 4.0 impact metrics and a qualitative severity to the vulnerability and the loop, and make the risk score and the loop ranking use the impact axis.

4. **Defence-in-depth complexity.**
   Require the modeller to name the assumed security layers between the exploit and the impact, and to ratify the loop as feasible even when a preliminary capability is required.

5. **Mandatory retrospective coverage.**
   Once the vulnerabilities are defined, load the relevant class skills and countercheck the model against their Attack Surface, Reconnaissance, Trust Assumptions, and Key Vulnerabilities sections.
   Record what each skill added, or that it added nothing.

6. **In-context examples.**
   Add compact worked examples that show the full chain from a field-level trust assumption to a severe end impact, including the service-contract failure mode at runtime.
   Include one low-yield counterexample that is explicitly demoted.

7. **Class guard.**
   Forbid technique families and fabricated names as `web_vulnerability_class`.
   State the rule verbatim in the prompt and add a non-blocking validation finding for a name outside the suite.

### Proposed re-measurement targets

These targets are proposals for operator approval, not measured results.

| Metric | Baseline | Proposed target |
|---|---:|---:|
| Low-yield share | 61.9% | at most 35% |
| Severe share | 22.1% | at least 40% |
| Sharp boundary share | 28.3% | at least 60% |
| Technique-family or non-suite class | 7 | 0 |
| Suite gap | 39.8% | at most 20% |
| Severe loops below `high` likelihood | 18 | at most 8 |
| Capped tokens per severe loop | 87,162 | at most 60,000 |
| Severe loops lost | 0 | 0 |

The re-measurement should use the same 17 units, the same target instance, and a fresh state.
It should model only, without hunting, so the comparison isolates elicitation quality from dispatch and pod behaviour.
A second phase can then hunt the improved loops and compare confirmed symptoms per capped token.

## Next steps

| Action | Owner | Due |
|---|---|---|
| Resolve the design questions on impact scoring, failure modes, trust schema, retrospective state, and examples | Operator and implementer | Before ticket filing |
| Grill the work items and file the tickets | Implementer | After the answers |
| Implement the schema and scoring changes under TDD | Implementer | Ticket order |
| Implement the prompt changes with adversarial review per prompt | Implementer and reviewer | Ticket order |
| Re-model the 17 units on a fresh instance | Operator | After the branch lands |
| Compare against this baseline and decide ship or iterate | Operator | After the re-model |

## Appendix

### Artifacts

- `survey_modeller_loops.py`: the read-only survey script.
- `loop-classification.csv`: the per-loop tier, family, boundary shape, and note.
- `loops.jsonl`: the per-loop structural record, emitted by the script.
- `loops.csv`: the same record as CSV.
- `aggregates.json`: the aggregate counts.

### Reproduce

```bash
python docs/experiments/modeller-impact-quality/survey_modeller_loops.py \
  --hunting-dir /opt/polymerhus-dev/eval/instances/data/eval-server-1/0c8cb6e6-7e91-4a01-880e-408896c0ce4a/hunting \
  --suite-dir skills/web-vulnerability-testing \
  --classification docs/experiments/modeller-impact-quality/loop-classification.csv \
  --out /tmp/modeller-impact-quality
```

### Caveats

- The impact tier is a manual judgement by one reviewer.
  The rubric is documented, and a second reviewer should re-tier a sample before the re-measurement.
- The tier scores the impact if the stated mechanism holds, not the probability that it holds.
  The likelihood is a separate axis and is recorded as the model wrote it.
- The pro-rata token attribution assumes a uniform cost per loop.
  The modeller bills per model and per call, so the per-loop figures are ratios, not invoices.
- The run is one target with a deliberately vulnerable application.
  The distribution may not generalize to a different target or a different unit mix.
- The 10 dispatched loops belong to one unit.
  The dispatch coverage of 8.8% is a run-level fact, not a per-unit dispatch rate.
- The `class parent` and `class leaf` status is read from the suite tree at measurement time.
  A suite rename would change the counts without changing the model.

### Known issues

- The store validator does not check that `web_vulnerability_class` exists in the suite.
  The two fabricated names and the five technique-family uses persist because of that gap.
- The model has no impact field, so the risk profile cannot express impact.
  The likelihood-only design is documented in `docs/design/hunting-67-threat-modeller-spec.md` section 7.4 and `docs/design/unit-threat-model-workbench.md` Q33.
- The modeller's `failure_modes` are service-contract scoped.
  The V-2 failure mode and the contract-integrity family show the scope limit directly.
