# Measurement - white-jotter-1-20261026T031121-1618c524

## Trial summary and identity

| field | value |
|---|---|
| trial | `white-jotter-1-20261026T031121-1618c524` |
| target | `white-jotter` |
| project | `dda347be-abea-48e4-94e5-4a4039f41858` |
| eval_sha | `81522a71f3f5fbb0dcd9f9bb3c71d59a5e2b9002` |
| stack_fingerprint | `eacbaf79e043443e1ea6bd7db5c1e0b36612505d36799609f22bbb2d68b313e6` |
| terminal | `failed` |
| window | 2026-10-25T21:51:53Z to 2026-10-26T03:11:21Z |
| budget / spend | 7,000,000 / 7,017,453 capped tokens |
| official result | 0 identified, 1 partial, 6 missed |

The trial entered at recon, completed recon, drained analysis, and failed in hunting.
The app's hunting run finished `stopped` at 03:11:21 after crossing the capped-token budget, but the trial's stop confirmation timed out, so the trial record says `failed` and records no overshoot.
The official discovery record is [verdicts.yaml](verdicts.yaml) and [diagnoses.yaml](diagnoses.yaml).

## Official discovery result

The official result is 0 identified, 1 partial (`white-jotter-001`, confidence 0.45), and 6 missed.
Identification rate is 0.0; the partial-or-identified rate is 0.1429.
The partial is not a GT-scoped discovery: the rate-limit pod's control probes authenticated `admin/123`, but the pod's confirmed class was rate-limit-bypass and its spec never tested credential acceptance.
The seven diagnoses fall into three clusters: the progressive risk halt (003, 004, 007), the batched risk-desc queue plus the token budget (005, 006), and modeller fault binding (001, 002).
All seven diagnoses carry a proposed issue because the issue bank was unreachable (`EVAL_GITHUB_TOKEN` unset).

By class, weak/default credentials is 0/1 identified and 1/1 partial; access control, stored XSS, RCE, SQL injection, arbitrary file read and IDOR/mass assignment are each 0/1.
By locus, only `/api/login` has any credit (partial); `/api/`, `/api/admin/content/article`, `/api/admin/user`, `/api/search`, `/api/file/` and `/api/register` are all missed.

## Quality results by the six criteria

### 1. L0/L1 testable-unit specification

All 7 vulnerabilities meet the 0.3 floor; the core mean is 0.714 and the enriched mean is 0.729.
Full core is 2/7: `white-jotter-001` and `white-jotter-007`.
The other five resolve the unit but not the complete unit-L0-system triangle.
`white-jotter-006` sits exactly on the floor at core 0.3333 with no link to the file route.

| metric | value |
|---|---|
| unit present | 7/7 |
| L0 present | 2/7 |
| link present | 6/7 |
| typed present | 1.0 for all 7 |
| L0 recall | 3/11 endpoints |
| edge recall | 10/17 service-to-system edges |
| full core | 2/7 |

The missing L0 endpoints and edges are partly the corpus's known capability gaps: no resolved-path facet for 002, no path-position carrier for 006, and no credential witness for 001.
Those are documented in the bundles' `gaps.md` and are not scored as new regressions.

### 2. Threat model quality

Only `white-jotter-005` has a loop candidate that binds the expected unit and the GT class.
`white-jotter-006` has a strong traversal loop, but it is bound to `Service:library-catalog`, not the corpus's `Service:book-cover-serving`; the official diagnosis treats library-catalog as the owner, while this measurement follows the corpus unit mapping.
The modeller modelled 3 of 27 intake units: `Service:sign-in`, `RESTApi:api`, and `Service:library-catalog`.
The sign-in unit produced 11 threats over 10 classes; RESTApi produced 10; library-catalog produced 5.
The 005 SQL-injection loop is the best artifact in the trial: it names the query-composition interface, cites `lib-06`, `lib-21` and `lib-17`, carries a stable differential and a risk score of 12, and is not duplicated.
The 006 traversal loop is nearly as strong: it names the tier-split normalisation, cites the `..;` escape that served the 11,001-byte bundle and the 31,369-byte source map, and is risk-scored at 6; its unit identity is a sibling and it was never dispatched.
The 002 RESTApi loop is concrete but explicitly closes the path-spelling family after suffix-only probes, so it cannot reach `/api/;/admin/user`.
The 001 unit binds `F-1` (missing attempt throttling) and records the default pair only as a likelihood premise.
The 003, 004 and 007 units were never modelled.
The deterministic `loop_candidate` is false for every row because the script globs `loop-*.yaml` while the artifacts are `threat-*.yaml`; 21 threat files exist, so the defect hides the 005 and 006 loops, and the 006 row also has a sibling-unit mismatch.

### 3. Hunter soundness

No GT-class spec candidate exists for any of the 7 vulnerabilities.
The hunter produced 104 specs: 93 ratified and 11 dropped.
Most ratified specs carry the reduced D4 fields and a rich typed procedure.
Two contract failures dominate:
12 of 104 ratified specs lack `verification_symptoms` and `assumptions`, and the same 12 lack `skill_concretised_procedure`.
The affected set is all five `Service-sign-in__threat-8` specs, two `RESTApi-api__threat-4` specs, and five `RESTApi-api__threat-10` specs.
The drops are well reasoned where they exist: the produced specs correctly falsify the native-stream, padding-oracle and stripped-rememberMe envelopes, the read-folds-more family, and the role-halt minting premise.
Only 10 of 21 hunts carry an explicit verify-claims note.
The procedure is populated in 89 of 104 specs (4 to 9 fields); the deterministic script reports 0 because it reads `provenance.skill_procedure` instead of the top-level `skill_concretised_procedure`.
The bfla-alternate-path specs are the closest to the 002 GT: they have a 302/empty-body negative control and a 200/data candidate, but their payload vector is a trailing separator and their interpretation pitfall calls the in-path matrix form a dead end.

### 4. Pod quality

86 pod directories ran, 66 produced a PodExport, and 4 are successful/symptom-confirmed.
All 4 successes are outside the GT set; none confirms one of the 7 vulnerabilities.
58 of 66 exports are degraded `budget-timeout` envelopes written by the 2700 s watchdog; they carry top-level terminal fields and zero raw observations.
20 of 86 pod directories have no export at all.
No pod minted a second variant; every directory contains only `v0`.
The best runner work is the session-management login-boundary pod: it established a garbage-id control, an unused-mint control, a cookie-less replay and a `/api/authentication;jsessionid=` replay, and confirmed a real pre-auth session fixation.
The rate-limit pod is also clean: 30 sequential failures, an unknown-user control, a known-good seed, a latency trend and a header census.
The near miss is `broken-function-level-authorization__admin-content__wildcard-prefix__data-or-privileged-effect`: observation 6 reached `/api/;/admin/content/books` with HTTP 200 and a 41-byte code-400 envelope, then moved to `/actuator`; its export is budget-timeout.
The one pod that reached the right spelling lost its terminal to the watchdog, and the GT-002 roster read was never attempted.

### 5. Workflow adherence

The modeller sub-score is 0.50; the hunter sub-score is 0.55; the pod sub-score is 0.30.
The overall adherence score is 0.41, computed as 1.0 minus 0.10 per high defect, 0.05 per medium and 0.02 per low: 3 high, 5 medium and 2 low.
The three high workflow defects are the modeller coverage halt, the hunter contract breach and the pod lifecycle loss.
The five medium defects are the phase-note gaps, the missing skill-usage lessons, the sparse episodic memory, the absent variant expansion and the split PodExport schema.
The two low defects are the six repeated lower-gate writes and the four recovered tool-contract rejections.
The raw defect inventory is larger and is listed per axis in `measurements.yaml#workflow`; the score weights the distinct workflow-level defects, not every repeated instance.
The modeller states are `UNIT_TECHNICAL_SHARP -> TRUST_MODELLED -> TRUST_ASSUMPTIONS_WRITTEN -> VULNERABILITIES_WRITTEN -> COMPLETED`; the persisted `postgres:hunting_runs/12d15890-47b2-43c2-bbe3-14c9626a2fdb.stats.trajectory` shows five forward gates per unit with no skipped states, plus six lower-gate rewrites (three on sign-in, three on RESTApi).
The hunter pass order is clean where notes exist: 20/21 grounding, 21/21 slice, 21/21 collect, 21/21 discriminate, 21/21 well-formedness, and 21/21 `terminal.yaml`.
`RESTApi-api__threat-8` has no grounding note, and GENERATE and COMPLETE have no phase notes because their signals are the spec and terminal writes.
The pod runner and triager order is respected; the 58 watchdog envelopes are infrastructure terminals, not fabricated domain verdicts.
The four tool-contract rejections are all recovered: three `hunts_store` `extra_forbidden` errors and one `notes` `cmd=append` literal error.
The composed prompts are present and have no exact retired vocabulary; `hypothesis`/`hypothesised` are live terms (tracked prompt sources under `src/polymerhus/attack/hunting/prompts/`).

### 6. Token tax

The trial spent 7,017,453 capped tokens, which is 17,453 over the 7,000,000 budget (0.25%).
Capped tokens are 7.25% of the 96.8M total; cached input is 94.6% of context, so the capped axis is the meaningful cost.
Hunting agents take 6,524,418 capped tokens (93.0%): pod runner 3,475,010, hunter 2,177,105, threat modeller 582,875, pod triager 289,428.
The analysis-side agents take 451,546 (6.4%) and job_orchestrator 41,489 (0.6%).
Capped tokens per ground-truth vulnerability are 1,002,493.
Reasoning is 54.6% of generated output; cache detail is omitted 0 times in every agent.
The live usage endpoint reads 7,022,363 capped and 2,460 calls versus the trial snapshot's 7,017,453 and 2,459; the +4,910 capped and +1 call after the terminal snapshot are a measurement drift, not a quality failure.

## Workflow and contract findings

The dominant workflow finding is coverage, not tool misuse: 3 of 27 intake units were modelled and the crossing unit was never dispatched.
The second is the pod watchdog: 58 of 66 exports are degraded envelopes, so most pod conclusions are lost.
The third is the hunter contract: 12 ratified specs are missing two required body fields and the procedure.
The fourth is the execution-record failure: the budget stop fired but its confirmation timed out, so the trial is `failed` with `spend_overshoot: null` even though the hunting run finished `stopped`.
The modeller wrote 6 episodic notes for 3 units, not one per gate; RESTApi has no trust-mapping note and library-catalog has only wellformedness.
The pod layer wrote 2 episodic notes for 86 pods.
No skill-usage lesson shard exists under the project's `lessons/` directory.
The hunting phase has `run_id: null` in `trial.yaml` although run `12d15890` produced 86 pod directories, so the trial-to-run identity chain breaks on the failure path.
The Langfuse 30/min limit forced backoff; the ERROR set contains 309 observations, of which 4 are TOOL-level rejections and the rest are nested CHAIN/AGENT spans with Python object reprs as status messages.

## Benchmark-scope tightness

Four successful pods confirm symptoms outside the ground-truth set.
All four are judged novel, but two of them use the GT default credential as their payload, so they are sibling faults on the same credential rather than independent discoveries.

| spec_id | judgement | note |
|---|---|---|
| `rate-limit-bypass__burst-classification__sequential__canonical` | novel | Missing throttle with 30 failures, no rate-limit header and a flat latency trend; the seed also re-proved `admin/123`. |
| `information-disclosure__session-id__response-cookie` | novel | JSESSIONID has HttpOnly but no Secure/SameSite over plain HTTP; low severity. |
| `defence-bypass-parser-confusion__encoding-declaration__body-bytes__representation-split` | novel | BOM-marked UTF-16LE body authenticates as admin; the payload is the GT pair. |
| `session-management__login-boundary__preauth-anonymous` | novel | Anonymous JSESSIONID is retained across login and gains admin authority; genuine session fixation. |

The deterministic `confirmed_non_gt` is 1, not 4, because its mapping only counts a confirmed pod whose spec id is absent from every candidate spec row; three of the four successes were pulled into `white-jotter-001` by keyword class matching.

## Failures and error findings

The full list is in `measurements.yaml#failures`.
The highest-severity findings are:
- The token-budget stop POST timed out, so the trial terminal is `failed` and `spend_overshoot` is null although the run stopped.
- 58 of 66 PodExports are degraded watchdog envelopes and 20 pod directories have no export.
- 12 ratified specs lack two required fields and the skill procedure.
- The progressive halt modelled 3 of 27 units and never dispatched the crossing library-catalog unit.
- The GT default credential is recorded as a premise, not a fault, and the operator auth store uses the same `admin/123` pair.
- L0 recall is 3/11 and edge recall is 10/17.
Three deterministic-measurement defects are recorded separately: the loop glob, the procedure field path, and the keyword-inflated `spec_candidate`/`confirmed_non_gt`.

## What we learned

Coverage, not class knowledge, is the binding constraint on this target: the SQL injection and traversal reads were modelled OBSERVED and never hunted, and three GT units were never modelled.
The default administrator credential is the cheapest finding and the pipeline authenticated it repeatedly as its own bootstrap material without ever reporting it.
The semicolon bypass was one probe away: the wildcard pod executed the admin handler through `/api/;/admin/content/books` and then moved on.
A sharp loop is not enough if the queue cannot reach it: 93% of the budget went to the two highest-risk units and the third unit starved.
The pod watchdog is a discovery-quality problem, not just an infrastructure problem: it destroyed the one pod on the correct semicolon spelling.
The hunter contract is mostly strong, but the threat-8 and header-confusion specs show that a missing two-field body can still be ratified and dispatched.

## What surprised us

The pipeline spent 7,017,453 capped tokens to identify zero of seven ground-truth vulnerabilities, while its own control probes authenticated the GT default pair at least five times.
The one GT-adjacent pod that reached the correct semicolon prefix was not the bfla-alternate-path pod but the wildcard-prefix pod, and its evidence was lost to a timeout.
Four pods confirmed real non-GT findings, including a session fixation and a parser differential, while the GT set stayed at one partial.
The analysis-side agents were only 6.4% of the capped spend; the cost is almost entirely hunting and pod execution.
The stop path can fail its confirmation and still let the run stop, which makes the trial record less trustworthy than the app's run row.

## What remains unknown

The Langfuse skill path named by the measurement contract does not exist in this checkout, so the v2 endpoint was used directly; the measurement procedure itself may be stale.
It is unknown whether a per-unit budget reservation would have admitted the library-catalog batch, and whether 005/006 would then have produced specs and pods.
It is unknown whether the 58 top-level watchdog PodExports are an intended degraded contract or a schema regression.
It is unknown whether the 4,910 capped-token drift after the terminal is a late triager turn or a read race.
It is unknown whether the 12 contract-broken specs are a regression from `81522a71` or a pre-existing hunter defect; they are not in the corpus's known gaps.
It is unknown whether the issue bank would have matched any of the 7 proposed diagnoses, because `EVAL_GITHUB_TOKEN` is unset.
It is unknown which SHA is authoritative for the aggregate: the plan says `5df29930`, the trial stamps `81522a71`.

## Recommendation for the next trial

1. Add a per-unit budget reservation or a coverage floor to the batched queue, and dispatch the crossing unit before the next unit's batch.
2. Make a recorded default/weak credential a mandatory sign-in-unit fault, and require a `default-credential-replay` spec whenever the operator bootstrap authenticates with a shipped pair.
3. Fix the pod lifecycle before the next target: preserve the pod's own terminal on watchdog expiry, or extend the window on progress, and emit an export for every pod directory.
4. Enforce the hunter's reduced-D4 contract at ratification: reject a spec missing `verification_symptoms`, `assumptions` or the skill procedure.
5. Retry the budget-stop POST on transport timeout and record the stop as `stopped` with the overshoot, not `failed` with null.
6. Do not change the pipeline code during the measured run; record the 12-spec contract breach and the 58-export lifecycle defect as operator findings before any fix.

## Evidence appendix

- Official record: [verdicts.yaml](verdicts.yaml), [diagnoses.yaml](diagnoses.yaml).
- Deterministic base: [metrics.yaml](metrics.yaml).
- Trial record: [trial.yaml](trial.yaml).
- Threat models: `dda347be-abea-48e4-94e5-4a4039f41858/hunting/threat_modeller/{produced,consumed}/`.
- Hunter specs and notes: `dda347be-abea-48e4-94e5-4a4039f41858/hunting/hunter/`.
- Pods: `dda347be-abea-48e4-94e5-4a4039f41858/hunting/test-executor-pod/`.
- Auth store: `dda347be-abea-48e4-94e5-4a4039f41858/auth/credentials.yaml`.
- Usage: `GET http://localhost:8080/projects/dda347be-abea-48e4-94e5-4a4039f41858/usage`.
- Langfuse: v2 observations, 2026-10-25T21:51:53Z to 2026-10-26T03:11:21Z; generation `42c69d83ef95bf54` (threat modeller), the hunter system prompt, and the TOOL errors `9660d2a9239bac76`, `83cebac2b77bf3da`, `76704e268422920c`, `3114aa54fa7af6b6`.
- Private corpus: `/root/utm-groundtruth/white-jotter/white-jotter-00{1..7}/unit-spec.yaml`, `symptoms.md`, `skills.md`, `gaps.md`.
- Official ground truth: `/root/WebExploitBench/white-jotter/`.
