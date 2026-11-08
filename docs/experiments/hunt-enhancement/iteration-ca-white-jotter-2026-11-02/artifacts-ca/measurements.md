# Trial measurement - white-jotter-1-20261103T143924-1618c524

## Summary

The trial is a hunting-only seeded arm (iteration C.a) on the white-jotter target, and it discovered 3 of 7 ground-truth vulnerabilities, with 2 partial and 2 missed (identification 42.86%, partial-or-identified 71.43%).
The hunting phase ran end to end: 14 valid unit threat models (3 produced + 11 consumed), 14 threat files, 40 test specs, 37 pod directories and 15 symptom-confirmed pod exports.
The result is a large improvement over the 2026-10-22 white-jotter 7M run (1 identified, 2 partial, 4 missed), but the trial is heavily confounded by a target-substitution failure: the synthetic host t-1618c524.target served co-tenant applications (SIYUCMS, PrestaShop) for most of the hunt while the white-jotter container stayed up on port 46271.
The 7M token budget, not the plan's 14,400 s phase deadline, was the terminator, with 4 of 14 threats never dispatched.

## Identity and configuration

- Trial record: [trial.yaml](trial.yaml); terminal `stopped`; phase `hunting` only (`seeded: true`).
- Project: `cbd28a7d-30cb-498b-8e7a-eaa9bc8f37c8` (L0/L1, auth context and authn skill copied from the iteration C project; hunting and usage excluded).
- `eval_sha` `f020dafd12f3f8f525fad2496c64141b6e4f8fc8`, `stack_fingerprint` `3d396661b0ad9bb7f96101d102feaeba216b9189cef5c57ece87b9f69b56ede5`, `worktree_dirty: true`.
- The plan's frozen canary code is `5df29930`; this arm runs `f020dafd` with a dirty worktree, so it is a separate arm, not the canary baseline.
- Target: `webexploitbench/white-jotter`, target run `iterca-white-jotter`, setup `eval/setups/white-jotter-iteration-ca.yaml`.
- Runtime: 2026-11-02T18:27:04Z to 2026-11-03T14:39:24Z (20 h 12 m), token budget 7,000,000 capped tokens, spent 7,003,040 (overshoot 3,040).
- Setup pins: `pipeline_sync: batched`, `pod_batch_size: 2`, `promotion_risk_threshold: 2.5`, `risk_threshold: 156.25`, `HUNT_POD_SESSION_TIMEOUT_S=5400`, `SKILL_EVOLUTION_ENABLED=0`.
- No recon or analysis phase ran in this trial; the L0/L1 graph is inherited from iteration C, so Criterion 1 measures the copied surface, not this run's recon.

## Official discovery result

The official records are [verdicts.yaml](verdicts.yaml) and [diagnoses.yaml](diagnoses.yaml).
Total 7: identified 3 (`white-jotter-002`, `-003`, `-005`), partial 2 (`-001`, `-007`), missed 2 (`-004`, `-006`); identification rate 0.4286.
The four non-identified vulnerabilities carry one diagnosis each: `-001` modeller unit/fault binding (default credential displaced to the reset flow), `-004` KB coverage gap for a logging-sink JNDI lookup, `-006` skill/design drift on the media route, `-007` pod trajectory divergence plus the watchdog terminal.

## Impact assessment

The deterministic v5 block is `metrics.yaml#impact`.
27 assessment rows: 14 threats, 13 precursors, 27 capability-bearing rows.
14 green rows and 1 red row (`IntegrationSystem:cross-origin-policy::IA-1`, `scope=out`), a green share of 0.9333; threat share 0.5185, precursor share 0.4815.
CIA distribution over the 27 rows: confidentiality none 17 / low 6 / high 4; integrity none 18 / low 4 / high 5; availability none 24 / low 3 / high 0.
Two prior-art records were reused in the primary set (Service:library-catalog cites RESTApi:api's SQLi threat and vulnerability); 6 reused records exist across all files including abandoned copies.
Risk: the metric reports `risk_total` 100.0 with 6 medium + 7 critical.
The artifact disagreement is real: the 14 threat rows sum to 106.9 with 7 medium + 7 critical.
The missing 6.9 is `consumed/Service-register/threat-1.yaml` (concurrent duplication); its parent model is `produced/Service-register/Service-register.yaml`, so the metric cannot stamp a schema and drops it from the total (flagged as a measurement defect).

## Quality by criterion

### Criterion 1 - L0/L1 testable-unit specification

The loose floor (`core_score >= 0.3`) is met by all 7 (1.0), but only 2 of 7 have full core (`white-jotter-001`, `-007`), a full-core rate of 0.2857.
Per-vuln core: `-001` 1.0, `-002` 0.667, `-003` 0.667, `-004` 0.667, `-005` 0.667, `-006` 0.333, `-007` 1.0.
Aggregate recall against the corpus: L1 unit recall 7/7 (1.0), L0 endpoint recall 3/11 (0.273), edge recall 10/17 (0.588), typed backbone 12/12 (1.0).
The L0 gap is the dominant weakness: `/api/logout`, `/api/admin/user`, `/api/admin/content/article`, `/api/search` and `/api/file/cover.png` are absent from the graph.
`white-jotter-006` is the floor artifact at 0.333: unit-only presence with no L0 endpoint, no link and no system edge, so a 0.3 is not a good unit.
The L0 set is inherited from iteration C; the seeded hunting arm cannot repair it.

### Criterion 2 - Threat model quality

The expected unit's own model engages the GT locus for only 2 of 7: `-003` (stored XSS, the exact GT class) and `-001` (an enumeration direction at the GT login locus, but not the GT class).
For `-002`, `-005` and `-007` the GT direction exists on a different L1 unit (`ReverseProxy`, `RESTApi:api`, `RESTApi:api`), so `threat_candidate` is false on the strict unit match even though the direction was found and confirmed.
`-004` has no logging/JNDI direction anywhere, and `-006`'s owning unit closed with zero threats.
Artifact sharpness is high where a direction exists: all 5 GT-relevant threats name the concrete interface, the state transition, probe evidence, CVSS factors, risk and band.
The 001 enumeration threat is sharp but carries the wrong class; the 004 and 006 rows are 0.
Every GT-relevant threat is a leaf or a parent used one-dimensionally (see Narrowing).

### Criterion 3 - Hunter soundness

40 distinct specs: 37 ratified, 3 dropped (all `ReverseProxy__threat-1` path variants).
All 40 carry 5/5 required fields except 3 account-recovery specs missing `assumptions` (4/5); no retired fields are present; no symptom list is generic.
The procedure is fully populated at the spec's top-level `skill_concretised_procedure` for 33/40; 4 are 6/7 and 3 are 5/7.
The deterministic `procedure_fields: 0` is a metric path defect (it reads `provenance.skill_procedure`); the artifact path is the correct one.
KB grounding is effectively absent: 2/40 specs cite the KB, 26/40 cite an HTTP baseline and 40/40 cite recon probes and skills.
The 3 dropped specs carry no drop reason, so the verify-claims evidence requirement is not met.
Spec sets exist for 10 of 14 threats; 8 have 3-6 specs (substantial) and every one of the 10 sets is structurally overlapping.

### Criterion 4 - Pod quality

37 pod directories: 15 successful/symptom-confirmed, 13 `pod-watchdog-timeout`, 2 `node-timeout`, 2 `technical-infeasibility`, 5 `no-symptom-evidence`.
GT-level confirmation is 3/7 (`-002` BFLA menu read, `-003` stored XSS, `-005` SQL injection); `-001` and `-007` have no GT-class confirmation (their pods confirmed enumeration and non-GT classes).
The runner is grounded where it ran (spec + skill procedure + live target), and the confirmed pods carry real differentials (canonical denial beside injected success, role-less control, id list walk).
The failure mode is the terminal path: 35% of pods consume the 5,400 s watchdog, 2 runner nodes idle-time out, and the watchdog is always `unsuccessful/clean=false`.
`white-jotter-007` is the sharpest loss: the raw trail registered `roles:[{"id":1}]`, got a 1,575-byte administrative menu against a 1,000-byte role-2 menu and an empty role-less control, then the upstream changed and the pod exported `unsuccessful/pod-watchdog-timeout`.
Three triager turns died on `'dict' object has no attribute 'model_dump'`, and one `graph_view` read-only query was refused as write-shaped cypher.

### Criterion 5 - Workflow adherence

The modeller, hunter and pod sequences are only partly observable: no gate-transition trace and no hunter phase notes are persisted.
Where observable, order is correct: 14 valid unit models are COMPLETED with canonical sections; 37 ratified specs each have exactly one pod directory; every dropped spec has none; runner -> triager -> terminal is visible in the exports.
The defect counts are large: 38 rejected `notes` writes, 9 rejected `hunts_store` writes, 1 rejected `assess_impact`, 13/13 abandoned models COMPLETED invalid, 3 dropped specs without reasons, 3 account-recovery specs without `assumptions`, 13 watchdog terminals, 3 triager degradations, 1 `graph_view` false refusal and 1 spec-divergence pod.
The weighted adherence score is 0.33 under the weights high 0.08, medium 0.03, low 0.01 (5 high, 7 medium, 6 low defects).
Per-agent scores: modeller 0.83, hunter 0.91, pod 0.62.
No duplicate system-prompt sections and no retired fault-hypothesis vocabulary were found; the "hypothesis" uses are the reasoning sense and the `hypothesised` spec status.
The modeller prompt does not document the `notes` tool's argument schema, which is the root cause of the 38 rejected writes.
The triager prompt has one sentence split across three H1 headings.

### Criterion 6 - Token tax

Source: `trial.yaml#token_spectrum`, cross-checked against `GET /projects/cbd28a7d-30cb-498b-8e7a-eaa9bc8f37c8/usage` and `usage/usage.yaml`; all three agree exactly.

| Agent | visible | reasoning | cached input | uncached input | generated | total | capped | calls |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| hunting_threat_modeller | 420,523 | 353,135 | 117,276,416 | 645,447 | 773,658 | 118,695,521 | 1,419,105 | 522 |
| hunting_hunter | 145,590 | 206,124 | 18,721,920 | 931,062 | 351,714 | 20,004,696 | 1,282,776 | 291 |
| pod_runner | 412,242 | 670,758 | 65,934,208 | 2,268,362 | 1,083,000 | 69,285,570 | 3,351,362 | 1,614 |
| pod_triager | 27,882 | 70,705 | 537,344 | 851,210 | 98,587 | 1,487,141 | 949,797 | 83 |
| **Total** | **1,006,237** | **1,300,722** | **202,469,888** | **4,696,081** | **2,306,959** | **209,472,928** | **7,003,040** | **2,510** |

Capped shares: modeller 20.26%, hunter 18.32%, pod runner 47.86%, pod triager 13.56%.
Cached input is 97.73% of input and 96.67% of the raw total; the budget axis counts only 4.70M uncached input plus 2.31M generated.
Capped tokens per GT vuln 1,000,434; per identified 2,334,347; per GT-confirmed pod 2,334,347; per ratified spec 175,076.
No cache-detail omission was reported (0 for every agent).

## Narrowing

The deterministic narrowing block counts matched rows, not distinct threats: 57 rows over 14 threat files, 31 broad and 26 narrow.
The distinct-threat result is 7 broad and 7 narrow.
Ten threats dispatched specs; eight have three or more specs, and every one of the ten sets has an overlapping primary axis, so 0 of 10 are well-formed.

| Threat | Bound class | Breadth | Specs | Primary axes | Well-formed | GT relevance |
|---|---|---|---:|---|---|---|
| Service:sign-in threat-1 | username-enumeration-oracle | narrow | 4 | state-class x4 | no | `-001` locus, wrong class |
| ReverseProxy threat-2 | broken-function-level-authorization | broad | 6 | guard x6 | no | `-002` exact class, wrong unit |
| Service:article-management threat-1 | xss-stored | narrow | 3 | write-path x3 | no | `-003` exact |
| RESTApi:api threat-1 | sql-injection | broad | 5 | extraction-channel x5 | no | `-005` exact class, wrong unit |
| RESTApi:api threat-2 | mass-assignment | broad | 4 | binding-shape x4 | no | `-007` exact class, wrong unit |
| ReverseProxy threat-1 | broken-function-level-authorization | broad | 5 | payload-vector x5 | no | none |
| Service:register threat-1 | concurrent-duplication | narrow | 3 | technique x3 | no | none |
| Service:user-administration threat-1 | account-recovery | narrow | 3 | reach x3 | no | none |
| ReverseProxy threat-3 | stored-artifact-disclosure | narrow | 4 | artifact-family x4 | no | none |
| Service:article-management threat-2 | idor | broad | 3 | operation, operation, identifier-carrier | no | none |
| IdentificationSystem threat-1 | csrf-navigation-get | narrow | 0 | - | no | none |
| Service:navigation-menu threat-1 | broken-function-level-authorization | broad | 0 | - | no | none |
| Service:register threat-2 | business-logic | broad | 0 | - | no | none |
| Service:sign-in threat-2 | session-management | narrow | 0 | - | no | none |

The four zero-spec threats are the low-risk tail left by the 7M stop; none names a GT class.
The central narrowing observation is that breadth is not the discriminator here: the broad threats stay broad in the class tree, but the spec sets collapse to one primary axis, and the GT directions that were split onto adjacent units did not produce a second spec family.

## Benchmark-scope tightness

15 pod exports are symptom-confirmed, of which 4 match a GT class+fault (`-002` BFLA menu read, `-003` two XSS pods, `-005` SQL injection).
The remaining 11 are non-GT confirmations and are recorded with a manual note each in `measurements.yaml#benchmark_scope_tightness`:
- novel: `account-recovery__semicolon-matrix__anonymous__second-account` (name-keyed reset to 123, not a GT bundle).
- novel: `concurrent-duplication__burst-escalation...` and `concurrent-duplication__parallel-burst...` (duplicate of each other).
- duplicate: `idor__create__absent__no-identifier` (the same anonymous article write as GT `-003`).
- novel: the four `stored-artifact-disclosure` source-map pods (duplicates of each other).
- novel class at the GT 001 locus: the three `username-enumeration-oracle` pods (duplicates of each other; the assessor scored `-001` partial on them).
The deterministic `confirmed_non_gt` is 10, not 11: it counts confirmed pods not linked to a candidate spec, which wrongly treats the BFLA and SQLi GT confirmations as non-GT and the three enumeration confirmations as GT-mapped.
Both counts are reported here; the artifact-level class judgement is 11.

## Failures and error findings

The full list is in `measurements.yaml#failures`; the leading signals are:
- High: the synthetic host was re-pointed to co-tenant deployments for most of the hunt; pod notes call `:80` a shared nginx proxy that time-slices co-tenant deployments, the front conf was last rewritten 2026-11-03T13:55:40Z, and a concurrent Langfuse session `e2e-siyucms-20261103T013954Z` is visible.
- High: 13/37 pods terminaled `pod-watchdog-timeout`, 2 node-timed out, and the watchdog discarded the observed `white-jotter-007` GT symptom.
- High: 3 triager turns failed on `'dict' object has no attribute 'model_dump'`.
- High: 38 `notes` writes were rejected for a missing `cmd` field, and the prompt documents no argument contract.
- High: the `graph_view` read-only guard refused a legitimate `MATCH ... WHERE ...` read as write-shaped cypher.
- Medium: 9 `hunts_store` and 1 `assess_impact` schema rejections; 6 provider transport errors plus 7 opaque `<object object>` model statuses.
- Medium: 13/13 abandoned models are COMPLETED with `validation.valid=false`; the media and telemetry units closed with zero threats and no hunter work.
- Medium: 3 dropped specs without drop reasons, 3 account-recovery specs without `assumptions`, 7 incomplete procedures.
- Medium: the trial ran 20 h 12 m against the plan's 14,400 s deadline, with no record of the multi-hour idle window.
- Medium: the inherited L0 graph has 3/11 expected endpoints.
- Measurement: `procedure_fields`, `risk_total`, `downstream.spec_count`, `confirmed_non_gt`, per-vuln pod aggregation and `class_match` all disagree with the artifacts in bounded ways; each disagreement is reported in `measurements.yaml#impact.notes`, `#narrowing.notes` and `#per_vuln`.

## What we learned

- The hunting pipeline is functional end to end on this target: 14 valid models, 14 threats, 40 specs, 37 pods and 3 GT confirmations from a seeded hunting-only start.
- Unit granularity is now the binding constraint: 3 of the 5 GT directions that exist are filed on an adjacent L1 unit (`ReverseProxy` or `RESTApi:api`), so the strict unit+class candidate rate (2/7) understates direction reachability (5/7).
- The threat model is sharp where it engages: the confirmed threats carry concrete interfaces, probe evidence and CVSS factors, and the GT 003 stored-XSS threat is the strongest artifact of the trial.
- The pod terminal path, not the reasoning, is the largest quality loss: 15 confirmed pods versus 13 watchdogs, and at least one observed GT symptom was lost to the watchdog.
- The 7M budget stopped the tail of a risk-descending queue with 4 threats undispatched; none of the four names a GT class, so the cap did not directly cost a GT identification in this trial.

## What surprised us

- The target substitution was not noticed by the pipeline: pods kept probing a SIYUCMS/PrestaShop upstream for hours, and the only detection was in the agents' own notes.
  A target-identity assertion is the clearest missing guard.
- The notes tool's argument contract failed 38 times without the pipeline surfacing it as a defect; the phase notes were largely lost while the models still reached COMPLETED.
- The 007 GT symptom was observed in a raw trail and exported as unsuccessful; a single terminal-path decision turned an identified vulnerability into partial.
- The four source-map pods confirmed a real new disclosure class that no GT bundle names.

## What remains unknown

- Which process re-pointed the front conf, and whether the concurrent `e2e-siyucms` session shares the same synthetic host.
- Whether a salvaged or renewable watchdog terminal would identify `white-jotter-007`.
- Why 13/37 pods consume the watchdog; the substitution explains some, not all.
- Whether the four undispatched threats would have produced any GT-relevant direction under a larger budget.
- Whether the L0 endpoints were lost in iteration C recon or in the graph copy.
- Whether a stable upstream would have converted the 3 dropped ThinkPHP specs and the account-recovery technical-infeasibility pod into usable evidence.

## Recommendation for the next trial

1. Fix target isolation first: add a target-identity assertion to every probe and serialize or namespace the shared `ph-eval-front` per synthetic host; re-run white-jotter only on a stable upstream.
2. Make the pod terminal salvage an observed symptom (or let the triager reach its terminal before the watchdog) and fix the `dict.model_dump` triager crash; `white-jotter-007` is the proof case.
3. Repair the `notes` tool contract (document `cmd` in the prompt or accept `option`/`body`) and the `hunts_store` extra-field schema, then re-measure phase-note coverage.
4. Fix the `graph_view` read-only guard so a `MATCH ... WHERE` read is not classified as a write.
5. Bind the shipped default credential as a first-class fault on the login acceptor and load weak-credential-discovery at the sign-in unit; add a logging-sink/JNDI class; require a direct request to a mapped route before a unit closes with zero threats (`-001`, `-004`, `-006`).
6. Make the hunter's discriminator set genuinely multi-axis (the current sets are one primary axis in 10 of 10 threats); require a drop reason at verify-claims.
7. Keep the 7M budget for a like-for-like comparison, but record the effective phase deadline and the idle windows so the 20 h wall clock is explainable.

## Evidence appendix

- Trial and official records: `trial.yaml`, `verdicts.yaml`, `diagnoses.yaml`, `metrics.yaml`, `impact_review.yaml` in this directory.
- Threat model: `cbd28a7d-30cb-498b-8e7a-eaa9bc8f37c8/hunting/threat_modeller/{produced,consumed,abandoned}/` and `notes.yaml`.
- Hunter: `.../hunting/hunter/test-specs/<dispatch>/{produced,consumed}/` and `notes.yaml` (40 specs, 37 ratified, 3 dropped).
- Pods: `.../hunting/test-executor-pod/<spec_id>/{experiment-log,variants}/` and `notes.yaml` (37 pods, 15 confirmed).
- Auth and usage: `.../auth/{overview,credentials}.yaml`, `.../usage/usage.yaml`; live usage `http://localhost:8080/projects/cbd28a7d-30cb-498b-8e7a-eaa9bc8f37c8/usage`.
- Graph: `http://localhost:8080/projects/cbd28a7d-30cb-498b-8e7a-eaa9bc8f37c8/graph` (250 nodes, 317 links, 39 endpoints).
- Langfuse: v2 observations over 2026-11-02T18:27:00Z to 2026-11-03T14:40:00Z; 28,000 observations sampled (19:34:48Z to 14:39:16Z, 120 ERROR), plus the 18:27-18:41Z first-turn window; sessions `c84d2ada-e05c-42ba-bb12-8386119796f8:<dispatch>:<role>`; the concurrent session `e2e-siyucms-20261103T013954Z` is visible in the same project.
- Cross-check: the live usage endpoint and `usage/usage.yaml` match `trial.yaml#token_spectrum` exactly on every scalar.
