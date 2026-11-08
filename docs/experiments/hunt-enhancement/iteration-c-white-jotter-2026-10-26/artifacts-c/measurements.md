# Measurement - white-jotter-1 - 2026-10-27

## Trial summary and identity

| field | value |
|---|---|
| trial id | white-jotter-1-20261027T074905-1618c524 |
| target | webexploitbench/white-jotter (target_id white-jotter-1) |
| project | 8e2e5dc7-a880-4451-aaa5-267cedd48264 |
| instance | eval-server-1, target_run_id iterc-white-jotter |
| terminal | stopped |
| window | 2026-10-26T20:03:33Z to 2026-10-27T07:49:05Z (11h45m32s) |
| eval_sha | 13ce0edb1a44a1ce99f60841812cdb56a824262d, worktree_dirty true |
| stack_fingerprint | 112e9c3b05bc155d8a087d4131764d6ffc532af8c8a47bc645ddb053babd2407 |
| budget | 7000000 capped, spent 6919138, overshoot null, baseline 0 |

The trial ran clean through recon, analysis and hunting setup, and the hunting run was ended by the configured cumulative risk halt at 185 against a 180 threshold.
The terminal is `stopped`, not a budget stop: 80,862 capped tokens remained and the trial's own stop did not fire.
The official records are `verdicts.yaml` and `diagnoses.yaml` in this directory; the deterministic base is `metrics.yaml`.

## Official discovery result

| vuln | type | verdict | confidence |
|---|---|---|---|
| white-jotter-001 | Weak or Default Credentials | partial | 0.45 |
| white-jotter-002 | Access Control Bypass / Unauthorized Read or Write | identified | 0.95 |
| white-jotter-003 | Stored XSS | missed | 0.95 |
| white-jotter-004 | Remote Code Execution | missed | 0.95 |
| white-jotter-005 | SQL Injection | identified | 0.97 |
| white-jotter-006 | Arbitrary File Read | missed | 0.95 |
| white-jotter-007 | IDOR / Unauthorized Write or Overwrite | identified | 0.90 |

Identification rate is 3 of 7 (0.4286) and partial-or-identified is 4 of 7 (0.5714).
The three misses are not one failure: GT-003 was never dispatched, GT-006 was closed by the modeller as route-absent, and GT-004 is a known corpus KB gap (G004-05).

## Quality by the six criteria

### 1. L0/L1 testable unit

| vuln | core | enriched | unit | l0 | link | full core |
|---|---|---|---|---|---|---|
| 001 | 1.000 | 1.000 | yes | yes | yes | yes |
| 002 | 0.667 | 0.600 | yes | no | yes | no |
| 003 | 0.667 | 0.733 | yes | no | yes | no |
| 004 | 0.667 | 0.600 | yes | no | yes | no |
| 005 | 0.667 | 0.800 | yes | no | yes | no |
| 006 | 0.333 | 0.400 | yes | no | no | no |
| 007 | 1.000 | 1.000 | yes | yes | yes | yes |

Every unit resolves and 7 of 7 meet the loose 0.3 floor, but only 2 of 7 are full core.
Expected-endpoint recall is 3 of 11: only /api/login, /api/authentication and /api/register exist as L0 endpoints.
The 39 L0 endpoints are all anonymous recon GETs; the authenticated admin routes (/api/admin/user, /api/admin/content/article) and the injected read routes (/api/search, /api/file) never entered the graph.
Service-to-system edge recall is 10 of 17, with the AUTHORIZED_BY rows on the AuthorizationSystem the recurring failure.
GT-006 is at the loose floor only: it has no AGGREGATES link and no endpoint.
Evidence: `metrics.yaml` per-vuln `graph` blocks and the live graph at `GET /projects/8e2e5dc7-a880-4451-aaa5-267cedd48264/graph`.

### 2. Threat model quality

The deterministic script reports zero loops because it globs `loop-*.yaml`, while this pipeline writes `threat-N.yaml` under the unit model directory.
There are 28 threat files across 14 threat-bearing units, so the deterministic loop recall is a measurement artifact, not a discovery result.
Judged on the artifacts, a compatible direction exists for 4 of 7 GT vulnerabilities:

| vuln | compatible threat | sharpness | why |
|---|---|---|---|
| 001 | no | 0 | Service:sign-in binds four adjacent faults and explicitly defers default-credential state |
| 002 | ReverseProxy threat-1 | 3 | names the literal-URI classifier vs dispatcher, the semicolon carrier, controls and risk 9 |
| 003 | Service:article-management threat-1 | 3 | names the write channel, raw-body bind, anonymous read and surviving-payload sweep |
| 004 | no | 0 | no logging-sink or lookup direction in any model |
| 005 | RESTApi:api threat-2 | 3 | names the LIKE concatenation and the true/false pair with a control |
| 006 | no | 0 | V-2 traversal-read is an ASSUMED placeholder and the unit produced zero threats |
| 007 | Service:register threat-2 | 3 | names the nested role member, the self-minted session and the privilege lift |

Direction diversity is high where the class was bound: ReverseProxy has six threats, Service:sign-in four, RESTApi:api three, Service:register two.
Evidence: `threat_modeller/consumed/` and `threat_modeller/produced/`, plus the model notes in `threat_modeller/notes.yaml`.

### 3. Hunter soundness

There are 69 specs: 55 ratified, 13 hypothesised and 1 dropped, across 16 dispatches.
All 69 carry the five reduced-D4 fields, 68 carry the seven-field `skill_concretised_procedure` (48 at 7 of 7, 14 at 6 of 7, 6 at 5 of 7), and no retired field appears.
Verification symptoms are specific: no spec is flagged generic, and 51 of 69 use explicit control or differential wording in the sampled text.
The single drop has a real falsification trail (`RESTApi-api__threat-3/produced/differential-oracle-disclosure__identifier-prefix...`), not a convenience drop.
Judged sharpness: 3 for GT-002, GT-005 and GT-007; 0 for GT-001, GT-003, GT-004 and GT-006 because no spec targets their unit or class.
The deterministic `spec_candidate` is 0 for all seven, but 4 of the 7 have an exact-content spec under a differently named unit.
The cause is unit naming (RESTApi:api vs Service:book-search, ReverseProxy vs AuthorizationSystem) and a class matcher that does not map mass assignment to the GT IDOR type.

### 4. Pod quality

There are 55 pod sessions and 12 symptom-confirmed exports.
The 12 confirmations are strong: each carries a live control, a discriminating observation and a triager note that reasons about alternative explanations.
The pod runner and triager are excellent when the session concludes: the SQL pair was repeated twice and normalised against `/api/books`; the path-confusion pods tested a non-existent mapping as a catch-all control; the mass-assignment pod registered a control account without roles.
The failure is termination, not judgement: 41 of 55 exports are `pod-watchdog-timeout` at 3600 s and 38 of 55 carry no interpretation at all.
One triager crash turns a confirmed permission-catalogue symptom into `unsuccessful` / `no-symptom-evidence`.
Two successful pods are `clean=false` because a KB query degraded, not because the symptom was doubtful.
Variant quality is adequate: every pod minted one valid v0 from its spec and two pods reached a second variant; no duplicate variant was found.
Evidence: `test-executor-pod/*/*.yaml` and `test-executor-pod/notes.yaml`.

### 5. Workflow adherence

The modeller ran its live seven-state sequence (technical_sharpening, prior_art, trust_modelled, assumptions, vulnerabilities, wellformedness, impact_assessed, completed) and every one of the 23 unit models closed `COMPLETED` with `validation.valid=true`.
The gate is working, but it fires often: five units had a first COMPLETED write rejected and corrected, and four of those are the same `interface_agreement_refs` IA-only mistake (a DF or CF reference in an IA field).
One prior_art query was also rejected for a bare path and corrected.
The hunter ran grounding, slice, collect, discriminate, well_formattedness and generate for the units it reached; the three actuator dispatches stopped after discriminate.
The pod ran runner then triager; no fabricated domain verdict on an infrastructure failure was observed.

Defects and their counts:

| axis | defect | count |
|---|---|---|
| modeller notes | threat-bearing units with no vulnerabilities note | 7 |
| modeller notes | units with no assumptions note | 8 |
| modeller notes | repeated wellformedness gate (ReverseProxy) | 1 |
| hunter | dispatches with no terminal.yaml | 3 |
| hunter | produced threats never dispatched | 12 |
| hunter | threat-bearing units reached | 5 of 14 |
| pod | exports ended by the watchdog with no interpretation | 41 / 38 |
| pod notes | pod note records for 55 pods | 2 |
| structured output | triager crashes (`model_dump`) | 1 |
| structured output | late model/LangGraph ERROR chains | 9 |
| tool execution | raw pod observations with a tool failure | 36 of 936 |
| coupling | specs whose provenance.threat_id is a bare id | 69 of 69 |

Weighted adherence is 0.78: modeller 0.88, hunter 0.75, pod 0.72.
The score does not hide the pod timeout rate or the hunter coverage loss; both are reported above and in `failures`.

### 6. Token tax

| agent | generated | uncached in | cached in | capped | calls |
|---|---|---|---|---|---|
| pod_runner | 602,955 | 1,699,168 | 21,998,976 | 2,302,123 | 1,095 |
| hunting_threat_modeller | 669,492 | 1,275,943 | 161,740,160 | 1,945,435 | 700 |
| hunting_hunter | 483,194 | 1,263,117 | 24,074,880 | 1,746,311 | 418 |
| pod_triager | 35,138 | 337,050 | 215,424 | 372,188 | 44 |
| mechanism_typist | 100,784 | 261,323 | 2,496,384 | 362,107 | 56 |
| triager | 10,447 | 78,374 | 26,112 | 88,821 | 11 |
| assigner | 16,337 | 41,507 | 129,152 | 57,844 | 13 |
| job_orchestrator | 14,646 | 29,663 | 263,424 | 44,309 | 17 |
| **total** | **1,932,993** | **4,986,145** | **210,944,512** | **6,919,138** | **2,354** |

Capped tokens are 98.8 percent of the 7,000,000 bound, but the run ended on the risk halt, not the budget.
Output is 27.9 percent of capped (reasoning 13.2, visible 14.7) and uncached input is 72.1 percent.
Cached reads are 96.8 percent of the 217,863,650 raw total and are correctly outside the budget axis.
The cost is 988,448 capped tokens per GT vulnerability and 2,306,379 per identified vulnerability.
`GET /projects/8e2e5dc7-a880-4451-aaa5-267cedd48264/usage` matches `trial.yaml` on every field, and `cache_detail_omitted` is 0 for all agents.
A per-phase split is not recoverable from the ledger.

## Workflow and contract findings

The live modeller prompt and the persisted notes agree on seven states, but `PLAN.md` still lists five; the plan is stale, not the pipeline.
The visible composed prompts use current vocabulary; no `fault hypothesis`, `hunt config`, `hunting cap`, `testing_pattern` or `payload_vector_space` term appears in any sampled generation input.
The modeller system prompt is large and the Langfuse payload is truncated at 261,305 characters, so a full section-by-section prompt audit is not possible from the trace.
Coupling from threat to spec to pod holds by directory and spec stem: all 55 pod `spec_dir` values resolve to a spec file, and 69 of 69 specs have `target_identity.unit_id == provenance.unit_id`.
The only coupling blemish is that `provenance.threat_id` stores `threat-1` rather than `ReverseProxy__threat-1`; the composite is only in the path.

## Benchmark-scope tightness

`metrics.yaml` reports 12 confirmed pods outside the GT set.
All 12 are real confirmed symptoms; the deterministic set is degenerate because no spec is a `candidate` (unit names differ), so it cannot separate duplicates from novel findings.
Manual judgement:

| spec | judgement | note |
|---|---|---|
| bfla roster empty-segment-inside-namespace | duplicate | GT-002, the cited pod |
| bfla roster empty-segment-before-prefix | duplicate | GT-002, second spelling |
| bfla roster-read get | duplicate | GT-002, matrix-parameter spelling |
| bfla account-mutation put | duplicate | GT-002, write half (targeted persisted change) |
| bfla role-catalogue empty-segment | duplicate | GT-002, role/permission data |
| mass-assignment sysadmin | duplicate | GT-007, the actual confirming pod |
| sql-injection boolean-differential | duplicate | GT-005, the cited pod |
| session-management login-body | duplicate | GT-001, default pair accepted but triaged as F-5 |
| information-disclosure httptrace | novel | anonymous 100-trace dump, 27 JSESSIONIDs, no challenge |
| session-management cookie-request-header | novel | replayed harvested JSESSIONID reaches admin JSON |
| rate-limit-bypass principal-spread | novel | 40 attempts, one principal, 1.13 s, no accounting |
| session-management url-path-parameter | novel | session id disclosed in a redirect Location |

So 8 are duplicates and 4 are real non-GT findings, one of which (httptrace plus cookie replay) is a credible high-value chain.
The benchmark is not tight against the actuator/telemetry surface; that is scope tightness, not a false positive.

## Failure and error findings

1. **Evaluation integrity, high.** The instance worktree is dirty at `13ce0ed`; `src/polymerhus/app/llm/providers.py` is modified to run analysis at `max` and design roles at `max`, and the plan names `5df29930` as the measured code. The stamped SHA does not describe the running code.
2. **Harness terminal, high.** The risk halt ended hunting and the trial records `stopped` with empty notes; the orchestrator treats `stopped` as success while 12 dispatchable threats remain.
3. **Pod lifecycle, high.** 41 of 55 pods hit the 3600 s watchdog and 38 never reached the triager.
4. **Hunter coverage, high.** Five of 14 threat-bearing units were reached; GT-003 and GT-006 were never dispatched.
5. **Modeller binding, medium.** GT-001 deferred the default-credential class; GT-006 closed a mapped traversal route as absent on an empty 404.
6. **Triager, medium.** One `model_dump` crash discarded a confirmed permission-catalogue symptom.
7. **Knowledge retrieval, medium.** Eight hunter notes record a degraded KB with no model answer; two generation calls failed with ReadTimeout.
8. **Measurement, high.** `metrics.yaml` misses 28 threats, 68 procedures, the GT-007 pod and four exact spec matches because of naming and path assumptions in `eval/measure_utm.py`.
9. **Trial deadline, medium.** No `budget_s` in the iteration C setup, so the 14,400 s plan deadline never applied and the trial ran 11h45m.
10. **Tool execution, low.** 36 of 936 probes failed on UTF-8 decoding, missing `jq`/`xxd`, or quoting.
11. **Observability, low.** `trace_id` is null, the trace-list API is gone, and prompt payloads are truncated.
12. **Notes schema, low.** Two pod notes for 55 pods and several missing modeller phase notes.

## What we learned

The rewriting is functionally alive: every unit resolved, every spec used the new reduced D4 and the seven-field procedure, every assertion traced to a live probe, and the identified verdicts are backed by clean confirming evidence.
The binding constraint is throughput and termination, not model capability: pods do not conclude, the unit barrier serialises two-hour waves, and the risk halt arrives before the inbox drains.
A modelled vulnerability is not a hunted vulnerability: GT-003 had a sharp, risk-9, write-proven threat and still produced no spec.
The graph is an anonymous-view graph: authenticated and injected routes are systematically absent from L0, which caps L0/L1 scores at 0.667 for five of seven vulns regardless of model quality.
The measurement script lags the pipeline vocabulary and now under-reports recall on every axis.

## What surprised us

The default administrator credential was submitted by a pod, returned code 200 with result "admin", and was still not harvested because the spec was scoped to cleartext carriage.
A pod whose logs already contained the account roster was force-finalised as a watchdog timeout, while its sibling spec confirmed the same fault.
Four genuinely new findings (httptrace, cookie replay, login accounting, jsessionid URL) came out of pods that metrics classifies as non-GT because of a unit-name mismatch.

## What remains unknown

Whether the risk-halt terminal should be treated as a successful execution for assessment.
Which of the three SHAs (5df29930, 13ce0ed, 9e9e852) is the honest identity for the aggregate report.
Whether the seeded L1 names or the corpus slugs are the canonical unit identity.
Why the watchdog is the normal pod terminator rather than a last resort.
Where skill-usage lessons and episodic memory are persisted for this arm.

## Recommendation for the next trial

1. Freeze the instance worktree: commit or revert `providers.py` before launch and refuse a trial when `worktree_dirty` is true or `eval_sha` disagrees with the plan.
2. Make the pod conclude: treat a watchdog finalisation as a failed pod, require the triager to write an interpretation, and measure the watchdog share as a release gate.
3. Widen or budget the batched unit barrier so a high-risk modelled threat is dispatched before the cumulative risk halt; treat a `stopped` run with dispatchable produced threats as unsuccessful and resume it.
4. Harvest known-good credentials: when a spec authenticates with a stored default pair, add "default pair accepted" as a verification symptom and promote it to a finding.
5. Require an in-root control and a repeated-decoded shape before a traversal fault may close as route-absent.
6. Repair `eval/measure_utm.py` for `threat-*.yaml`, `skill_concretised_procedure`, mass-assignment-to-IDOR matching, and the seeded unit names before any aggregate recall number is published.
7. Add the authenticated and injected routes to L0 (post-auth crawl or a bootstrap L1 endpoint seed); the current L0 graph cannot support four of the seven units.
8. Configure `budget_s` on the trial so the wall-clock deadline is real.

## Evidence appendix

| artifact | what it settles |
|---|---|
| `trial.yaml` | identity, terminal, phase runs, spend, token spectrum, dirty worktree |
| `metrics.yaml` | deterministic graph, spec, pod and token substrate |
| `verdicts.yaml` | official discovery and evidence chains |
| `diagnoses.yaml` | four root causes with typed loci |
| `.../hunting/threat_modeller/{produced,consumed}/*/threat-*.yaml` | 28 threat directions |
| `.../hunting/threat_modeller/notes.yaml` | 133 modeller notes, seven-state evidence, deferred default-credential gap |
| `.../hunting/hunter/test-specs/*/{produced,consumed}/*.yaml` | 69 specs, statuses, procedures, symptoms |
| `.../hunting/hunter/notes.yaml` | 139 hunter notes, phase summaries, KB degradation |
| `.../hunting/test-executor-pod/*/*.yaml` | 55 PodExports, 12 confirmations, 41 watchdogs |
| `.../hunting/test-executor-pod/notes.yaml` | 2 pod/triager notes, including the triager crash contradiction |
| `GET /projects/8e2e5dc7-a880-4451-aaa5-267cedd48264/graph` | 39 L0 endpoints, 12 L1 services, 15 systems |
| `GET /projects/8e2e5dc7-a880-4451-aaa5-267cedd48264/hunting/65ec294b-e5cf-49c6-9f7c-4664a73aa557` | status stopped, risk halt true, 185/180 |
| `GET /projects/8e2e5dc7-a880-4451-aaa5-267cedd48264/usage` | live token surface, exact match |
| Langfuse v2 observations (bounded windows) | 11 ERROR observations, 2 read timeouts, prompt heads, model and usage |
| `eval/instances/eval-server-1` git status/diff | uncommitted `providers.py` thinking-level change |
| `docs/experiments/unit-threat-model-eval-2026-10-20/PLAN.md` | five-state gate list, 14400 s deadline, 5df29930 identity |
