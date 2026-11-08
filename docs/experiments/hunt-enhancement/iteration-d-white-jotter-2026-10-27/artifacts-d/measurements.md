# Measurement: white-jotter trial `white-jotter-1-20261028T083326-1618c524`

## Summary

| Attribute | Value |
|-----------|-------|
| Trial | `white-jotter-1-20261028T083326-1618c524` |
| Target | `white-jotter` (WebExploitBench) |
| Project | `fe446230-1f19-41c7-bf2e-b7b4b9c6f0f5` |
| Instance | `eval-server-1`, seeded hunting-only trial |
| Code identity | `eval_sha` `5cadea78d4a4b8a88bf5284f29db14f29f1690ac`, `worktree_dirty` true, `stack_fingerprint` `84d14309...b6e0` |
| Terminal | `stopped` (trial record) |
| Trial window (record) | 2026-10-27T21:53:51Z to 2026-10-28T08:33:26Z |
| Run window (actual) | 2026-10-27T21:53:51Z to 2026-10-28T14:45:24Z |
| Budget | 7,000,000 capped tokens |
| Spend (record) | 4,940,868 capped |
| Spend (actual, ledger) | 7,003,931 capped (overshoot 3,931) |
| Ground truth | 7 vulnerabilities |
| Official result | 2 identified, 2 partial, 3 missed (identification 28.57%) |

This is a single-case measurement.
The official `verdicts.yaml` and `diagnoses.yaml` remain the discovery record; this document measures execution quality beside them.
The deterministic base is `metrics.yaml`; every place it disagrees with the artifacts is named in this report.

## Hypothesis recap

The plan's hypothesis is that the rewritten unit-threat-model pipeline completes every phase and produces a linked L0/L1 surface, sharp per-unit threat models, sound hunter specs, and real pod executions, with at least one walkable direction per ground-truth vulnerability.
This trial tests that hypothesis on white-jotter under the 7M capped-token budget.
The measured code is `5cadea78`, not the `5df29930` the plan names, so this is an iteration-d trial, not the plan's frozen baseline.

## Results

### Primary metric: ground-truth identification

| Metric | Value | Sample |
|--------|-------|--------|
| Identified | 2 of 7 (28.57%) | white-jotter-002, white-jotter-005 |
| Identified or partial | 4 of 7 (57.14%) | plus white-jotter-001, white-jotter-007 |
| Missed | 3 of 7 | white-jotter-003, white-jotter-004, white-jotter-006 |
| Mean confidence of positives | 0.75 | 0.93, 0.97 identified; 0.50, 0.60 partial |

The two identified vulnerabilities are strong: the path-confusion access-control bypass (002, confidence 0.93) and the UNION SQL injection (005, confidence 0.97).
The two partials are near-misses caused downstream of the model: 001's default credential was observed inside a pod but never re-scoped as a finding, and 007's mass-assignment was fully confirmed in the pod's experiment log but exported as unsuccessful.
The three misses split into one hunter coverage miss (003, a sharp threat never dispatched) and two modeller binding misses (004 JNDI, 006 traversal).

### Secondary metrics

| Metric | Value | Note |
|--------|-------|------|
| L0/L1 core floor (`core_score >= 0.3`) | 7 of 7 (100%) | floor met, but 006 sits exactly on 0.3333 |
| L0/L1 full core (unit + L0 + link) | 2 of 7 (28.57%) | 001 and 007 only |
| L0 endpoint recall (expected GT loci) | 3 of 11 (27.3%) | /api/authentication, /api/login, /api/register |
| L1 unit recall | 7 of 7 (100%) | all expected units resolve, aliases honoured |
| Typed-backbone recall | 7 of 7 (100%) | every required field present with the expected value |
| Service-to-system edge recall | 10 of 17 (58.8%) | 002/004/006 have zero edges |
| Threat candidate recall | 4 of 7 (57.14%) | 001-004; 005/006/007 false |
| Spec candidate recall | 1 of 7 (14.29%) | only 001 is unit+class bound |
| Class-level spec recall | 5 of 7 (71.4%) | 001, 002, 004, 005, 007; 004's matches are keyword artifacts, not RCE specs |
| Pod recall (a pod ran the GT locus) | 4 of 7 | 001, 002, 005, 007; 007's export is unsuccessful and 001's pod confirmed a different class |
| Confirmed non-GT symptoms | 13 | see the scope-tightness table |

The unit-bound candidate recall (4/7) understates delivery: the GT was actually reached for 002, 005 and 007 through class-level specs bound to sibling units, so the candidate gate is stricter than the path the pipeline really uses.
The L0 recall is the weakest surface metric: four of the seven GT loci never entered the graph.

### Guardrail metrics

| Guardrail | Result |
|-----------|--------|
| Token budget respected | NO - the ledger reached 7,003,931 (overshoot 3,931) after the trial recorded 4,940,868 |
| Trial terminal recorded | yes, `stopped` |
| Run terminal recorded | yes, hunting run `stopped` at 14:45:24 |
| Artifact store completeness | 27 threat files, 60 specs, 47 PodExports in 52 pod directories |
| Provider failures | 3 provider 401s, 3 model-name 400 generations (9 ERROR observations), 1 runner idle timeout |
| Pod watchdog | 17 of 47 exports (36%) |

## Quality results by criterion

### Criterion 1 - L0/L1 testable-unit specification

The L1 layer is the strongest part of the run: all 7 expected units resolve and all 7 typed backbones are complete.
The L0 layer is weak: only 3 of 11 expected endpoints exist, and the missing ones are exactly the handlers the pods later proved reachable (`/api/admin/user`, `/api/admin/content/article`, `/api/search`, `/api/file/cover.png`).
The edge layer is partial: 10 of 17 service-to-system edges resolve, with 002 and 004 failing both inbound `AUTHORIZED_BY` edges because the target kind is empty.
Full core is 2 of 7; the 0.3333 on 006 is the loose floor, not a good unit, because it has no link and no linked endpoint.
Per-vuln detail is in `measurements.yaml` under `per_vuln[].l0_l1`.

### Criterion 2 - Threat model quality

Twenty-seven threat files were produced across 27 completed unit models, all valid (parseable, no missing/unclosed/referential/class findings).
The directions are unusually sharp: the SQLi threat names the boolean oracle and the login-binding negative control, the mass-assignment threat names the roles member and the sysadmin roster result, and the stored-XSS threat names both the write interface and the `innerHTML` sink.
Sharpness scores: 3 for 002, 003, 005 and 007; 2 for 001; 0 for 004 and 006.
The binding is where the model fails: three GT faults are unbound (the shipped default credential on 001, the JNDI/logging-sink chain on 004, the double-decoded traversal on 006).
The 001 candidate flag is a class-matcher artifact: the sign-in unit carries enumeration, session-management, deserialization and sign-out directions, none of which is the default-credential fault.

### Criterion 3 - Hunter soundness

The 12 dispatched threats produced 60 specs (52 ratified, 8 dropped with reasoned probe evidence), and the specs are well formed on the reduced D4 (5/5 fields, 0 retired fields).
The typed procedure is fully populated in the artifacts (9 fields per spec) - the deterministic `procedure_fields 0/7` is a script defect, not a hunter gap, because `measure_utm.py` reads `provenance.skill_procedure` while the hunter writes `skill_concretised_procedure`.
Symptom discrimination is good: the specs carry negative controls (canonical zero-length 200, no-roles control, bare-literal control) rather than status-only assertions.
Coverage is the failure: 15 of 27 threats were never dispatched, including the sharp stored-XSS threat and the traversal precursor, and 003 never got a spec.
The hunter phase notes also show three gate skips and one fully duplicated phase cycle (Service-register).

### Criterion 4 - Pod quality

Pods ran real tests: 47 exports, 72 experiment logs, 17 clean `symptom-confirmed` successes.
The four GT-matching successes (three BFLA pods and the UNION pod) are excellent: the role-grant read proves byte-identical disclosure against a canonical zero-length control, and the UNION pod reads `/etc/passwd` through the rendered column.
The two enumeration pods (non-GT) likewise sweep 19 names against a control.
The pod layer is also the least reliable: 17 exports hit the 3600 s watchdog, 5 pods have no export at all, 3 provider 401s were recorded as `technical-infeasibility`, and 1 confirming pod was exported unsuccessful.
Two confirmed non-GT exports also contradict their own interpretation.
Variant minting is essentially unexercised: 49 of 52 pods have only a v0 root, and the 3 v1 variants are all based on a runner failure/divergence, not a target-state divergence.

### Criterion 5 - Workflow adherence

The modeller completed all 27 units through the seven-state gate ladder, with 211 gate events (181 gate, 30 lower_gate) and 8 skipped gates across 6 units.
The hunter wrote phase summaries for all 12 dispatches but left a required phase note missing in three of them and repeated the whole cycle once.
The pod runner/triager order is present in every export, but the triager is where the workflow breaks: watchdog timeouts, a corrupted model name, and infrastructure failures labelled as domain verdicts.
Weighted adherence (agent-controlled defects, infrastructure reported separately): modeller 0.79, hunter 0.71, pod 0.85, overall 0.78.
No retired vocabulary was found in the live hunting prompts, and no tool-surface violation was observed beyond the `merged_from` spec field.

### Criterion 6 - Token tax

The trial record snapshots 4,940,868 capped tokens and 1,579 calls; the durable ledger and the live usage endpoint both show 7,003,931 capped and 2,303 calls.
The 2,063,063-capped delta is entirely hunter (+531k), pod_runner (+1,295k) and pod_triager (+237k); the modeller total is unchanged.
Per agent (actual): modeller 2,210,283 (31.6%), hunter 1,189,035 (17.0%), pod_runner 3,049,457 (43.5%), pod_triager 555,156 (7.9%).
Per type: generated 2,151,612 (30.7% of capped), uncached input 4,852,319 (69.3%), cached input 159,938,944 (95.8% of the 166,942,875 raw total, never charged).
Capped per GT vulnerability: 1,000,562 (actual) versus 705,838 on the stale snapshot.
Cache-detail omitted is 0 for every agent.

## Narrowing

Distinct artifacts, not metric rows:

| Threat | Bound class | Parent? | Breadth | Specs (per dispatch) | Primary axes | Substantial | Well-formed |
|--------|-------------|---------|---------|----------------------|--------------|-------------|-------------|
| ReverseProxy__threat-1 | broken-function-level-authorization | yes | broad | 7 | surface x7 | yes | no |
| ReverseProxy__threat-2 | broken-function-level-authorization | yes | broad | 4 | surface x4 | yes | no |
| ReverseProxy__threat-3 | information-disclosure | yes | broad | 6 | endpoint-family x6 | yes | no |
| AuthenticationMechanism__threat-1 | session-management | no | narrow | 5 | lifecycle-event x5 | yes | no |
| AuthenticationMechanism__threat-2 | business-logic | yes | broad | 5 | write-surface x2 + selector-key + read-back-channel x2 | yes | no |
| RESTApi-api__threat-1 | mass-assignment-nested-relation-write | no | narrow | 4 | relation-claim x4 | yes | no |
| RESTApi-api__threat-2 | sql-injection | yes | broad | 4 | technique x4 | yes | no |
| Service-register__threat-1 | concurrent-duplication | no | narrow | 9 | payload-vector x8 + state | yes | no |
| Service-sign-in__threat-1 | username-enumeration-oracle | no | narrow | 4 | signal-channel x4 | yes | no |
| Service-sign-in__threat-2 | session-management | no | narrow | 4 | path-shape x2 + subject-state + consumer | yes | no |
| Service-sign-in__threat-3 | insecure-deserialization | yes | broad | 4 | technique x4 | yes | no |
| Service-library-catalog__threat-1 | stored-artifact-disclosure | no | narrow | 4 | discovery-path x4 | yes | no |
| Other 15 threats | various | mixed | mixed | 0 | none | no | no |

Totals: 27 threats, 18 broad, 9 narrow, 12 substantial, 0 well-formed.
The metric's row counts (118 threats, 79 broad, 39 narrow, 78 substantial) are the same 27 artifacts re-listed under every class-matching vuln, and its per-threat spec counts are unit-agnostic because `threat_downstream` joins on the bare `threat-N` id.
Every substantial set repeats its primary axis, so no set is well-formed under the plan's rule, even though several sets do vary a secondary axis (delivery-method, actor, target-data).
The GT-relevant directions are all "substantial but overlapping": 002 (7 specs, all surface), 005 (4, all technique), 007 (4, all relation-claim), 001 (4, all signal-channel).
No GT-relevant direction is both substantial and well-formed, which is exactly the narrowing signal this experiment measures.

## Workflow and contract findings

- Modeller: 8 skipped gates (PRIOR_ART x5, TRUST_MODELLED x3) and 30 lower_gate re-entries; all 27 models COMPLETED and valid.
- Hunter: 15 undischarged threats, 4 missing phase notes, 1 duplicated cycle, 2 provenance-less specs, and inconsistent `provenance.threat_id` spelling (6 dispatch ids, 6 bare ids).
- Pod: 17 watchdog timeouts, 5 missing exports, 3 provider-401 mislabels, 1 runner idle timeout, 3 interpretation/verdict contradictions, 1 confirming pod exported unsuccessful, and 3 specs carrying the retired `merged_from` field.
- Measurement: the trial snapshot is 6h12m and 2.06M capped tokens behind the run; `measure_utm.py` mis-reads the procedure key and joins specs by bare threat id; the per-vuln threat list triple-counts the 27 threats.
- Coupling: the threat-to-spec-to-pod path is otherwise intact; every pod directory matches its spec id and every verdict evidence chain resolves.
- Memory: no lesson or episodic-memory artifact exists under the project data root, so that axis is unknown rather than clean.

## Benchmark-scope tightness

13 confirmed non-GT symptoms, all judged novel: 3 actuator disclosures (configprops, heapdump, index/health), 4 stored-artifact/source-map disclosures, 4 session-management findings, and 2 account-enumeration findings.
None is a false positive on the evidence read; the strongest are the unauthenticated 87.9 MB heap dump and the source-map disclosure.
Two further pods (concurrent-duplication unused-name and whitespace-variant) carry `symptom-confirmed` interpretations but `unsuccessful` exports; they are excluded from the count and reported as a triager defect.
The GT-relevant successes (3 BFLA + 1 SQLi) are not scope-tightness rows.

## Failure and error findings

| Domain | Severity | Signal |
|--------|----------|--------|
| measurement_integrity | high | Trial snapshot 4,940,868 capped / 08:33:26 vs ledger 7,003,931 capped / run 14:45:24 |
| budget_enforcement | high | Project reached 7,003,931 capped (overshoot 3,931) after the trial terminated |
| pod_triager | high | 5 pods with no export, triager 400 "Invalid model name" at 14:41-14:43 |
| pod_reliability | high | 17 of 47 exports are 3600 s watchdog timeouts |
| pod_triager | high | 3 provider 401s recorded as technical-infeasibility |
| pod_triager | high | Confirming mass-assignment pod exported unsuccessful, downgrading GT-007 |
| pod_triager | medium | 3 concurrent-duplication verdicts contradict their own interpretation |
| hunter_coverage | high | 15 of 27 threats never dispatched |
| modeller_binding | high | GT-001, GT-004, GT-006 faults unbound or under-mined |
| measurement_script | medium | procedure key mismatch (0/7 for all 60 specs) |
| measurement_script | medium | unit-agnostic downstream spec join and 118-row duplication |
| artifact_coupling | medium | inconsistent provenance threat-id spelling |
| graph_l0 | medium | L0 endpoint recall 3 of 11 |
| workflow_modeller | medium | 8 skipped gates, 30 lower_gate re-entries |
| artifact_schema | low | 2 provenance-less specs, 3 retired-field pod specs, non-uniform interpretation labels |
| observability | low | Langfuse v2 carries no usage/input, legacy API 410; 42 ERROR observations retrievable by window |

## What we learned, what surprised us, what remains unknown

What we learned: the model's sharpness is not the bottleneck on this target - the unbound GT faults are.
Three of the seven GT faults are either unbound (001, 004) or filed as a precursor (006), while four of the five GT-relevant directions the model did produce score 3 on the plan's sharpness rubric.
The class-level delivery path matters more than the unit binding: 002, 005 and 007 were all reached by specs bound to a sibling unit, and the unit-bound candidate gate would have scored them as misses.

What surprised us: the trial record and the run disagree by six hours and two million capped tokens, so the recorded spend is not the run's spend.
The pod layer is simultaneously the most productive and the least reliable: it produced 17 clean confirmations and lost 22 pods to watchdog timeouts and missing exports, plus 3 to provider 401s and 1 to a runner idle timeout.
A confirming pod can be exported as unsuccessful, and a confirmed non-GT pod can be exported as unsuccessful too, which makes the pod verdict a weak signal for measurement.

What remains unknown: why the client terminated at 08:33 while the run continued to 14:45, and whether the 7M gateway guard was the real terminator.
Whether the 13 non-GT confirmations reproduce on a clean instance.
Whether the 3600 s watchdog is simply too short for 30-65-probe pods.
Why L0 captured SPA routes but no XHR handlers.
And whether the 118-row per-vuln threat duplication is intended by the deterministic script.

## Recommendation

Measure the pod layer as a separate reliability axis before trusting any per-vuln quality comparison across targets.
Concretely, for the next trial: (1) fix the trial terminal so the record snapshots the run's real end and spend; (2) fix the triager model-name construction and stop labelling provider 401s as domain verdicts; (3) raise or phase the pod watchdog, since 36% of exports die in it; (4) dispatch the promoted-but-undispatched threats, starting with the stored-XSS threat (risk 6); (5) add a logging-sink/JNDI class and a double-decoded traversal shape, since those are the two missing GT faults; and (6) fix the two `measure_utm.py` joins so the narrowing and procedure metrics measure the artifacts rather than a filename accident.
Do not compare this trial's identification rate against the plan's frozen `5df29930` baseline without noting that the pod reliability and the trial-window defect differ from that baseline.

## Evidence appendix

- Trial record: `trial.yaml` in the trial directory.
- Official records: `verdicts.yaml`, `diagnoses.yaml`, `impact_review.yaml` in the trial directory.
- Deterministic metrics: `metrics.yaml` in the trial directory.
- Pipeline artifacts: `/opt/polymerhus-dev/eval/instances/data/eval-server-1/fe446230-1f19-41c7-bf2e-b7b4b9c6f0f5/hunting/{threat_modeller,hunter,test-executor-pod}/`.
- Token ledger: `.../fe446230-1f19-41c7-bf2e-b7b4b9c6f0f5/usage/usage.yaml`; live `GET http://localhost:8080/projects/fe446230-1f19-41c7-bf2e-b7b4b9c6f0f5/usage`.
- Run state: `GET http://localhost:8080/projects/fe446230-1f19-41c7-bf2e-b7b4b9c6f0f5/hunting/aac5ecac-f119-4e26-9f21-fc259153ccf3` (211 trajectory events, 27 model sums, risk_total 150).
- Graph: `GET http://localhost:8080/projects/fe446230-1f19-41c7-bf2e-b7b4b9c6f0f5/graph` (250 nodes, 317 links, 39 Endpoints, 27 L1 units).
- Observability: Langfuse v2 `GET /api/public/v2/observations` filtered by session `aac5ecac-f119-4e26-9f21-fc259153ccf3` and by the trial window; 42 ERROR-level observations; the legacy trace API returns 410 for this organisation.
- Ground truth: `/root/utm-groundtruth/white-jotter/white-jotter-00{1..7}/` and `/root/WebExploitBench/white-jotter/` (judge-only; never copied into a prompt or the data root).
- Known measurement caveats: this trial is seeded hunting-only, so recon and analysis were not measured; the run used the `batched` pipeline sync; the 5-pod export gap is a provider/model-name defect, not a model-quality result.
