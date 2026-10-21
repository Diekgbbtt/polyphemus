# Unit threat model evaluation - 2026-10-20

## Status

Plan written before the first trial.
Deployment and preflight are in progress.
The eight-target run has not started.

## Objective

Stress-test the rewritten polymerhus pipeline end to end against real WebExploitBench targets.
Cover recon, analysis, threat modelling, hunting, and the test-executor pod with zero mocks.
Measure discovery, execution quality, workflow adherence, artifact contracts, and token tax.
Detect regressions introduced by the recent unit threat model and skills work.

## Hypothesis

The rewritten pipeline completes every phase on every pre-pulled target without a functional regression.
It produces a linked L0/L1 surface, sharp per-unit threat models, sound hunter specs, and real pod executions.
At least one loop direction exists for every ground-truth vulnerability.
The measured quality is at least the pre-rewrite baseline on the shared targets, with no new class of contract or workflow defect.

## Scope

Targets: the eight pre-pulled, data-ready WebExploitBench targets.
- comfyui (6 ground-truth vulnerabilities)
- jetlinks (5)
- prestashop (4)
- siyucms (6)
- white-jotter (7 plus one extra bundle)
- dataease (14)
- geoserver (4)
- phpbb (4)

One trial per target.
A trial is one target execution, not a batch.
The run is serial.

Out of scope:
- Exploitation beyond symptom confirmation.
- The exploitation submodule.
- Changes to the pipeline code during the measured run.
- Synthetic or mocked targets, tools, models, stores, or observability.

## Version identity

The measured code is `dev` at `5df29930`.
The instance worktree is reset to the same commit.
The agent mounts the instance worktree source at `/srv/src`.
The agent container was recreated after the worktree and `.env` update.
The LightRAG container was recreated with the new model binding.
The kali container was recreated; its `/opt/kali` is a live mount and reports Steel `0.5.0-preview.6`.
The app health is `ok` for postgres, neo4j, and kali MCP.
The new app surfaces are present, including `/projects/{id}/threads` and the data-dependency endpoints.

The trial record must stamp:
- `eval_sha` = the dev commit the instance mounts.
- `stack_fingerprint` = a deterministic hash of the dev SHA, the running agent and LightRAG image identities, and the SHA-256 of the instance `.env` file.
The `.env` hash covers the effective role, model, thinking, budget, and compaction configuration without printing any secret.

## Runtime configuration

All agent roles use `opencode-go:deepseek-v4.1-flash`.
The threat modeller and hunter declare `xhigh`, which negotiates to the provider's `max`.
The pod runner and pod triager declare `high`.
The compaction threshold is `0.4`.
The recon job subset is the documented five-job single-host contract:
`httpx`, `httpx_reprofile`, `katana`, `jsluice`, and `arjun`.
The trial setup carries it as `recon_jobs`; the automated trial sends it as the
launch `jobs` list.
The full platform plan is not used because it adds `steel_crawl`, `ffuf`,
`whois`, `subdomain_takeover`, and `naabu`, which the single-host eval contract
excludes and whose remote Steel runtime cannot reach the synthetic host.

The token budget is `7,000,000` capped tokens per trial.
Capped tokens are generated output plus uncached input, excluding cache reads.
The native trial process polls `GET /projects/{id}/usage` and stops the whole project execution at the bound.
The wall-clock phase deadline is `14400` seconds, so the token bound is the intended terminator on a normal run.

LightRAG:
- Main, extract, keyword, and query models are `RCP-AIaaS/deepseek-ai/DeepSeek-V4.1-Flash`.
- The binding host is SwissAI.
- The embedding model remains `nvidia/nemotron-3-embed-1b` at dimension `2048`, because the existing KB store is indexed at that shape.
- A model change without a reindex would invalidate retrieval.

The eight data dependencies live at `/root/eval-dd/data/<target>/`.
Each target has `operator_kb.md`, `l1-surface.yaml`, `auth/overview.yaml`, and `auth/credentials.yaml`.
Seven have `skills/authn/SKILL.md`.
ComfyUI has no authn skill and no authentication surface, so its omission is not a blocker.
The preflight must re-check presence and the AuthContext validators before every target.

## Evidence and integrity

The ground-truth corpus is at `/root/utm-groundtruth` on the eval server.
It is outside the pipeline data root, the project inputs, the operator KB, and the L0/L1 seed.
It never enters any agent prompt.
The official WebExploitBench ground truth remains at `/root/WebExploitBench`.

The pipeline evidence is under the instance data root `/opt/polymerhus-dev/eval/instances/data/eval-server-1/<project_id>/`.
The official trial records are under `eval/runs-utm-20261020/<target_id>/<trial_id>/`.
The artifact store is `/srv/eval-artifacts/<target_id>/<target_run_id>/<trial_id>/`.

## Measurement framework

The official `verdicts.yaml` and `diagnoses.yaml` remain the discovery record.
The new measurement records sit beside them.
The deterministic metrics are written to `metrics.yaml`.
The quality judgement is written to `measurements.yaml` and `measurements.md`.
The aggregate report is `EXPERIMENT-RESULTS.md`.
The progressive failure and error register is `FAILURES.md`.

### Criterion 1 - L0/L1 testable-unit specification

Ground truth for each vulnerability is `unit-spec.yaml` in its corpus bundle.
It names the unit, the applicable fault class, the required L0 endpoints, the service-to-system edges, and the typed backbone fields.

For each vulnerability:
- `unit_present`: the expected Service or System identity exists in the L1 graph.
- `l0_present`: at least one expected L0 endpoint exists on the target BaseURL.
- `link_present`: an `AGGREGATES` or equivalent L0-to-L1 link anchors the unit to the endpoint set.
- `typed_present`: the fraction of required typed backbone fields that exist with the expected values.
- `systems_present`: the fraction of required service-to-system edges that exist.

`core_score = mean(unit_present, l0_present, link_present)`.
`enriched_score = mean(unit_present, l0_present, link_present, typed_present, systems_present)`.
The loose floor is `core_score >= 0.3`, per the operator frame.
Report the full distribution, the fraction at the floor, and the full-core fraction.
Report `l0_recall`, `l1_unit_recall`, and `edge_recall` against the expected sets.
Never inflate the score from a name alone; an identity must resolve to a graph node and a real edge.

### Criterion 2 - Threat model quality

For each vulnerability:
- `loop_candidate`: at least one loop binds the expected unit and a fault/class compatible with the ground truth.
- `loop_sharpness`: 0 to 3 rubric.
  - 0: no loop, or a generic class-level statement.
  - 1: unit, fault, and class present; the trust assumption is vague.
  - 2: the trust assumption names the interface or state transition; the failure-mode slice is explicit; evidence is cited.
  - 3: the direction is concretely probeable, falsifiable, evidence-grounded, risk-scored, and non-duplicative.
- `direction_diversity`: distinct research directions per unit, plus the distinct fault/class and failure-mode count.
- `failure_mode_coverage`: the fraction of expected failure modes and classes in the corpus bundle that appear in the model.
- `evidence_density`: evidence references per loop.
- `duplicate_rate`: loops with the same unit and direction fingerprint.

`loop_candidate_recall` = vulnerabilities with at least one candidate loop / all vulnerabilities.
The key test is direction reachability: can a hunter walk one loop to the vulnerability, without the ground-truth answer being visible.

### Criterion 3 - Hunter soundness

For each vulnerability and loop:
- `spec_candidate`: a spec exists for the expected unit and fault/class.
- `spec_completeness`: all reduced-D4 fields are present; no retired field is present.
- `procedure_grounding`: the typed seven-field skill procedure is populated from the relevant class skill.
- `symptom_discrimination`: the verification symptoms name a manifestation and a negative control or differential; a generic status or non-empty body alone is not enough.
- `grounding_depth`: the spec cites the L1 unit, L0 assets, the KB, and the relevant skill.
- `verify_claims`: only technically infeasible tests are dropped; the ratified set is implementable; the drops carry evidence.
- `spec_sharpness`: 0 to 3 rubric, analogous to loop sharpness.

Report per-spec and per-vulnerability recall.
Report the ratified and dropped counts and the verify-claims drop reasons.

### Criterion 4 - Pod quality

For each pod run:
- `runner_grounding`: the runner used the spec, the relevant skill procedure, and the target surface.
- `chain_depth`: executed branches, tool calls, and variants.
- `observation_quality`: signals were recorded, interpreted, and used to steer.
- `triager_quality`: the verdict, terminal reason, and clean flag match the evidence.
- `variant_quality`: the minted variant names a valid basis and is not a duplicate.
- `symptom_confirmation`: a successful pod carries `symptom-confirmed` and a confirming observation.
- `non_gt_confirmation`: a confirmed symptom outside the ground-truth set; report it separately as benchmark-scope tightness, not as a false positive by default.

`pod_recall` = vulnerabilities with a confirmed pod / all vulnerabilities.
`pod_precision` = confirmed pods that match a ground-truth vulnerability / all confirmed pods.
`benchmark_scope_tightness` = confirmed non-ground-truth symptoms / all confirmed symptoms.
Every confirmed non-GT symptom needs a manual quality note.

### Criterion 5 - Workflow adherence

Check the expected sequence for every agent.
- Threat modeller: `UNIT_TECHNICAL_SHARP -> TRUST_MODELLED -> TRUST_ASSUMPTIONS_WRITTEN -> VULNERABILITIES_WRITTEN -> COMPLETED`.
- Hunter: `GROUNDING -> SLICE -> COLLECT -> DISCRIMINATE -> GENERATE -> WELL-FORMEDNESS -> VERIFY-CLAIMS -> COMPLETE`.
- Pod: runner and triager turns follow the pod graph; no fabricated domain verdict on an infrastructure failure.

Detect and count:
- skipped, reordered, or repeated gates and phases;
- degraded turns and provider-caused interruptions;
- steering or divergence from the phase contract;
- tool calls that violate their schema or the bound surface;
- missing or duplicated system-prompt sections;
- old vocabulary in a live prompt;
- structured-output failures;
- loop-to-spec-to-pod identity or path breaks;
- malformed hunting artifacts or notes;
- malformed skill-usage lesson records;
- missing phase-summary notes;
- missing skill or auth-context loads.

`workflow_adherence_score` is 1.0 minus the weighted defect rate.
The raw counts remain in the record; never hide them behind the score.

### Criterion 6 - Token tax

Read the trial's `token_spectrum` and `usage` snapshots.
Cross-check the live `GET /projects/{id}/usage` surface.
Report per agent:
- visible, reasoning, cached input, uncached input, generated, total, capped, calls.

Report per type:
- output share, reasoning share, cached share, uncached share;
- capped tokens per vulnerability;
- capped tokens per phase where the trace permits;
- cache-detail omitted counts.

The budget axis is capped tokens.
Never substitute the raw total, which includes cache reads.

### Criterion 7 - Discovery and diagnosis

Use the official verdicts:
- identified, partial, missed, confidence, matched unit/class/fault/symptom, evidence-chain completeness.
- identification rate per target, per class, and per locus.
- the diagnoses for every partial and missed vulnerability, clustered by root cause.

Report confirmed non-GT symptoms as a separate scope-tightness axis.
Report absence-versus-failure integrity rows: target reachability, run liveness, phase terminal, and job counts.

## Probes

P0 - environment and identity:
- remote `git -C /opt/polymerhus-dev` SHA;
- instance worktree SHA and clean/dirty state;
- agent, LightRAG, and kali image IDs and source mounts;
- app health, `/app-state`, and the new endpoint set;
- `.env` role/model/threshold values, redacted;
- LightRAG health and the effective model binding;
- Langfuse authentication and a bounded recent-observation read;
- target image store and readiness tools;
- data-dependency presence and AuthContext validation.

P1 - launch:
- trial record, project id, phase records, run ids;
- app-state in-flight state and liveness heartbeat;
- no orphan run from an earlier trial.

P2 - recon:
- per-job status and stats;
- L0 node and edge counts;
- failed jobs and retries;
- target 5xx/502 and front availability;
- analysis drain predicate and `analysis_drained`.

P3 - analysis:
- L1 Service/System/DataItem counts;
- `AGGREGATES`, `SURFACES_AT`, and other L0-to-L1 edges;
- per-vulnerability unit and endpoint recall;
- proposal/turn errors and schema failures.

P4 - hunting:
- threat-model produced/consumed/abandoned trees;
- model and loop counts;
- gate state order and validation;
- hunter test-spec trees and statuses;
- pod variant and experiment-log trees;
- notes and lesson records;
- mapper and mover markers.

P5 - observability:
- Langfuse v2 observations, cursor-paginated, bounded by trial time and session id;
- ERROR and WARNING observations, tool spans, and generation usage;
- the composed system prompt on the first turn of each role;
- tool-call inputs and outputs, rejection reasons, and structured-output failures;
- trace and session ids tied to the trial runs.

P6 - usage:
- `GET /projects/{id}/usage` at every phase poll and at the terminal;
- trial `spent_tokens`, `spend_overshoot`, `spend_baseline`, `usage`, and `token_spectrum`;
- per-agent and per-type tax;
- cache-detail omission.

P7 - official assessment and diagnosis:
- `orchestrator monitor` tick to convergence after each trial;
- `verdicts.yaml` presence, schema, identity, and evidence-chain resolution;
- `diagnoses.yaml` pairing and root-cause schema;
- `close-verify` and `store materialize`.

P8 - measurement:
- deterministic `metrics.yaml`;
- measurement subagent `measurements.yaml` and `measurements.md`;
- update `FAILURES.md` and the aggregate experiment report.

## Execution protocol

1. Freeze the code SHA.
2. Run the preflight on the instance and the canary target.
3. Run the comfyui canary trial from a fresh project.
4. Tick the monitor to assessment and diagnosis.
5. Run the measurement and update the failure report.
6. If the canary is clean, continue with the remaining seven targets serially.
7. After each trial: monitor, assess, diagnose, measure, and update the failure report before the next target.
8. At the end: close-verify, materialize the store, cluster the failures, and write the aggregate experiment results.

Monitoring cadence:
- every 30 to 60 seconds during recon;
- every 60 seconds during analysis drain;
- every 60 to 120 seconds during hunting;
- on every phase terminal and every artifact batch.

Each poll reads the state and classifies it.
A blind poll does not count.
A failed job is a note-and-continue unless it removes a required dependency.
A target 5xx is an upstream-availability signal, not route absence.

Remediation:
- configuration and data-dependency fixes only;
- no code edits during the eight-trial measured run;
- any code defect is recorded, diagnosed, and reported to the operator before a fix;
- a fix would create a new SHA and a separate re-run, never a silent mid-run version change.

Abort gates:
- app health not `ok`;
- instance worktree not at the frozen SHA;
- provider unavailable or quota exhausted without an approved fallback;
- LightRAG query failure that prevents methodology retrieval;
- a missing required data dependency;
- a target that cannot be reached from kali;
- a canary functional failure;
- a run with no lifecycle heartbeat or an orphan from an earlier trial;
- the token budget or phase deadline exceeded without a recorded terminal.

## Reports

`FAILURES.md`:
- append-only, timestamped;
- one entry per observed failure or error;
- trial, target, phase, agent, signal, evidence path, severity, first seen, recurrence, provisional domain, status;
- no root-cause claim without evidence;
- at the end, regroup by failure domain and common root cause.

`metrics.yaml`:
- deterministic fields described above;
- source paths and hashes for the evidence;
- no LLM judgement.

`measurements.yaml`:
- per-vulnerability rows with the 0 to 3 rubrics and evidence;
- per-agent workflow and token rows;
- the benchmark-scope-tightness rows;
- the confidence and the unresolved questions.

`measurements.md`:
- the narrative per trial, following the experiment-results structure;
- summary, evidence, learnings, recommendation, next steps.

`EXPERIMENT-RESULTS.md`:
- the final aggregate, using the measure-experiment-results template;
- identification rate, per-class and per-locus breakdown, pass@1 for the single attempt, quality axes, token tax, failure clusters, learnings, recommendation.

## Acceptance

The evaluation is complete when:
- all eight targets have one terminal trial record;
- every trial has an official verdicts file and the required diagnoses;
- every trial has `metrics.yaml` and `measurements.yaml`/`measurements.md`;
- the artifact store has the self-contained trial trees;
- `FAILURES.md` is clustered by root cause;
- `EXPERIMENT-RESULTS.md` is written with a clear recommendation;
- every unresolved functional failure or contract defect is named with evidence.

## Current preflight state

Completed:
- dev force-pushed at `9e9e8522`; deploy-eval succeeded for the 300-asset cap;
- the endpoint micro-family fix and the typed store contracts are local, tested, and not yet deployed;
- instance worktree reset to `9e9e8522`;
- `.env` overwritten and preflight-clean;
- the five-job recon subset is wired through the setup and the trial;
- agent, LightRAG, and kali recreated;
- app health `ok`;
- new thread and skills endpoints present;
- LightRAG effective model is `RCP-AIaaS/deepseek-ai/DeepSeek-V4.1-Flash`;
- ground-truth corpus staged at `/root/utm-groundtruth`;
- deterministic measurement script `eval/measure_utm.py`;
- measurement subagent prompt and role;
- per-trial measurement wrapper `eval/measure_trial.sh`.

Canary history:
- attempt 1 used the platform default recon plan and stalled on `steel_crawl` against the remote Steel runtime;
- the recon was stopped, the client was terminated, and no trial record was written;
- attempt 2 used the five-job recon subset and completed recon;
- attempt 2 then stalled in analysis: `mechanism_typist` reached 649,011 tokens against a 400,000 budget at the global `0.4`, the compaction log kept `over_budget=True` with no reduction, and the analysis never drained;
- attempt 2 produced no hunting run and no trial record;
- the analysis worker was cleared by an agent restart;
- the analysis roles now compact at `0.2`; the hunting roles remain at `0.4`;
- attempt 4 reached recon complete, analysis drained, hunting complete, and pod execution;
- attempt 4's trial record is `failed` on a provider 429 at 00:27:30; the T11 operator resume returned 202 and the hunting run completed at 01:05:04;
- attempt 4's official assessor marked all 6 comfyui vulnerabilities `missed`; `diagnoses.yaml` names F-017 (a consumed pod spec was lost on the provider pause) as the leading cause;
- attempt 4 spent 4,420,861 capped tokens of 7,000,000.

Pending:
- measure canary attempt 4 with `eval/measure_trial.sh`;
- deploy and retest the F-013 endpoint micro-family fix and the F-015 typed contracts;
- apply the F-016 gateway request-limit fix and decide the durable budget binding;
- the remaining seven trials.

Pre-run corrections:
- attempt 1: added the five-job recon subset, because the platform default includes `steel_crawl` and `ffuf`, and the remote Steel runtime cannot reach the synthetic host;
- attempt 2: added the role-specific analysis compaction override, because the global `0.4` did not drain the 1,128-asset mechanism-typist chunk;
- attempt 3: proved the `0.2` override alone is insufficient; the family still entered as one 592K recent block;
- attempt 3: added the hard `CHUNK_MAX_ASSETS=300` chunk cap, which splits only an oversized family into ordered sub-chunks;
- attempt 4: measured with the five-job subset, the 0.2 analysis thresholds, the 0.4 hunting thresholds, and the 300-asset split;
- post-attempt 4: replaced the split workaround with the endpoint micro-family packing fix (F-013) and typed the store contracts (F-015);
- post-attempt 4: decoupled the gateway RPM limit from the disabled USD guard (F-016);
- the failed attempts are smoke failures, not measured trials;
- attempt 4 is a measurement case, not a clean baseline.

## Canary 4 measurement caveats

The measurement must report the following structural limitations separately from model quality:

- The recon used the documented five-job subset (`httpx`, `httpx_reprofile`, `katana`, `jsluice`, `arjun`), not the platform's full plan. The full plan cannot reach the synthetic host through the remote Steel runtime.
- The analysis used the 300-asset hard-cap split, not the endpoint micro-family packing fix. The canary's mechanism-typist chunks were 200K-235K and close to the 200K analysis budget; the micro-family fix is post-canary.
- The analysis roles used 0.2 compaction; the hunting roles used 0.4.
- The gateway had no request limiter: `LLM_GATEWAY_BUDGET_ENABLED=false` and no `LLM_GATEWAY_KEY_RPM_LIMIT`. The provider returned repeated 429s.
- The trial record is `failed` on the provider failure while the hunting run was resumed by the T11 operator verb and completed. The assessor and diagnoser were dispatched manually on a failed record; the normal monitor would defer a failed trial.
- The 7M cap is trial-client-scoped. The trial froze at 3,892,171 spent; the app continued after the client failure to 4,420,861. The cap was not reached, but the execution was not budget-supervised after the failure.
- F-015 dropped one four-spec `hunts_store` batch during the hunter phase. The typed-contract fix is post-canary.
- F-017 lost one admitted pod spec when the run paused; the spec had no PodExport. The 0/6 discovery result is therefore not a clean model-quality baseline.
- The measurement must distinguish discovery quality (0/6), execution quality (the phases did run), and structural defects (F-013, F-015, F-016, F-017).

## Canary 4 measurement checklist

Run:

```
bash eval/measure_trial.sh comfyui \
  /opt/polymerhus-dev/eval/runs-utm-20261020/comfyui-1/comfyui-1-20261021T002730-1fc05262 \
  /opt/polymerhus-dev/eval/instances/data/eval-server-1
```

Then verify:
- `metrics.yaml` exists and its counts match the trial artifacts;
- `measurements.yaml` and `measurements.md` exist;
- every quality claim cites an artifact or a Langfuse observation;
- the report separates structural limitations from model quality;
- the report names the 0/6 verdict result and the F-017 cause.
