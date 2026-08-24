# Eval Harness Design: polymerhus Vulnerability-Discovery Evaluation against WebExploitBench

*Design document. Companion to `docs/design/eval-harness-agentcyberrange.md` (the AgentCyberRange architecture study).
Scope: the orchestration system, the discovery oracle, the target setup pipeline, and the judge agent for evaluating polymerhus's vulnerability-DISCOVERY capability only (no exploitation, no post-exploitation).
The pipeline runs unchanged against a WebExploitBench target; the harness decides, from persisted evidence, whether the pipeline identified each ground-truth vulnerability.*

*Status: design (contract), NOT implementation.*

---

## 1. Purpose and scope

The harness evaluates whether the polymerhus multi-agent pipeline (recon -> analysis -> hunting) discovers the vulnerabilities a WebExploitBench target is seeded with.

Confirmed decisions (operator, 2026-08-24):

- Scoring semantics: the discovery-identification predicate, with the pod's symptom-confirmed verdict as the assertion. Exploitation is sufficiently asserted as executing a test and getting the sought-after symptom back.
- Stages per trial: recon + analysis + hunting.
- Stack isolation: one shared polymerhus stack, fresh `project_id` per trial.
- Harness placement: in-repo, following the existing eval conventions (`analysis/evaluation.py`'s `run_matrix`/`compare`, `tools/eval_bootstrapper.sh`, `tests/e2e/fixtures/eval-targets.yaml`).
- Target on-boarding: a setup pipeline exposed as a web API (machine identifier in, configured target + polymerhus interfacing points out), because the machine cannot hold every target image at once.

## 2. The evidence substrate

The oracle reads persisted artifacts only. Nothing in the harness re-touches the target after scoring; the pipeline's own persisted output is the evidence.

### 2.1 The test-executor pod artifacts (the strongest signal)

The pod lives on branch `feat/hunting-84-test-executor-pod` (worktree `.claude/worktrees/hunting-84-test-executor-pod`), NOT on `main`. Its typed contract (`pod/types.py`):

- **TestImplementationSpec** (D4): `target_identity`, `verification_symptoms`, `testing_pattern`, `assumptions`, `payload_vector_space` (typed base), `rationale`, `interpretation_guidance` (NL core), `parent_spec_ref`, `provenance` (variant lineage).
- **PodExport** (D5 + D6): `verdict` (`successful`|`unsuccessful`), `terminal_reason` (six-value Q3 vocabulary: `symptom-confirmed`, `space-exhausted`, `technical-infeasibility`, `specific-defence-prevention`, `no-symptom-evidence`, `budget-timeout`), `iterations`, `clean`, `init_validation`, `variant_specs`, `raw_observations`, `interpretations`, `error`. `to_envelope()` renders `{verdict, evidence}`.
- **Persistence** (`pod/pod_memory.py`): per-project tree under the hunting data seam:
  - `data/<project_id>/test-executor-pod/<spec_id>/variants/<vN>.yaml` - the minted TestImplementationSpec variants. `spec_id = <fault>_<strategy>`, the #164 hunter's `SpecItem.spec_id`.
  - `data/<project_id>/test-executor-pod/<spec_id>/experiment-log/<order>.yaml` - the per-variant D6 slice: `raw_observations`, `interpretations`, the full `executed` dedup ledger, and the `experiment_summary` TERMINAL record.
  - `data/<project_id>/test-executor-pod/notes.yaml` - per-project notes keyed `<spec_id>:<order>:<note_name>`.
- **Hypothesis verdict derivation** (`hunting_agent.py::derive_verdict`): a PURE trail-driven function `(terminal_reason, clean, init_validation) -> {successful, unsuccessful, insufficient-evidence, underspecified-spec}`. `symptom-confirmed -> successful`; `space-exhausted/technical-infeasibility/specific-defence-prevention -> unsuccessful`; `no-symptom-evidence/budget-timeout -> unsuccessful when clean, else insufficient-evidence`; INIT rejection -> `underspecified-spec`.

### 2.2 The hunt store and the control plane (main)

- `src/polymerhus/attack/hunting/data/hunts/<run_id>/{run,config,hunt,dispatch,result,unresolved,back_edge}.md` - the append-only orchestration trail.
- `data/hunts/projects/<project_id>/{configs.yaml,notes.yaml}` - the per-project memory (accumulated research directions).
- `hunting_runs` status table; API seams `POST /projects/{id}/hunting`, `POST .../hunting/{hunting_run_id}/stop`, `GET .../hunting/{hunting_run_id}` (`project_management/api.py:270+`).
- **Wiring caveat**: `start_hunting` does NOT yet inject `dispatch_fn` (scoped by #110 "Dispatch placement"), so a production hunting run today yields orchestration-pass records (candidates, configs, notes) but no dispatched pod runs. The oracle must therefore grade on the full evidence set, using the PodExport path when present and the degraded trail otherwise.

### 2.3 The L0/L1 graph

- `GET /projects/{id}/graph` (`api.py:85-90`) - L0 + L1 nodes and links. L1 `Service` keyed `business_function_slug`, `System` keyed `kind:discriminator`, `DataItem` keyed `item_key`; cross-layer `AGGREGATES`/`SURFACES_AT`/`EVIDENCED_BY` edges anchor L1 to L0.
- The `CONSUMES` trust-assumption edge is the persisted seed instance of the fault-hypothesis primitive.

### 2.4 Observability

- Langfuse traces: one trace per pod run, spans per loop iteration; plus the recon/analysis/hunting traces. The judge agent reads these for the LLM half of the oracle.

### 2.5 Ground truth (WebExploitBench)

- Per vuln: `vulnerability/<vuln_id>/metadata.json` - `Location` (URL) + `Vulnerability Type`. Plus `challenge.json` scoring signals (`verifier` and/or `LLM_judge`), the `report/`, `verify/`, `exploits/` blobs for the judge's reference.
- Mapping bridges: `Vulnerability Type` string -> CWE fault id via the fault-KB materialisation facet; `Location` URL -> L0 endpoint -> L1 unit via `AGGREGATES`.

## 3. The discovery oracle

The oracle is the heart of the harness. It answers, per ground-truth vuln: did the pipeline identify it?

### 3.1 The identification predicate (operator-ratified framing)

The most accurate proxy for successful discovery is the **verdict + evidence in the PodExport artifact** plus the **elements of the experiment log**, driven by the **TestImplementationSpec variant details**.
The discovery predicate is: the eval orchestrator heuristically reconciles that combined data to the correct vulnerability.
Executing a test and getting the sought-after symptom back is the sufficient assertion.

Formally, a ground-truth vuln `V = (Location L, Type T)` is **identified** if there exists a pod run `R` such that:

1. **Verdict**: `R.verdict == "successful"` and `R.terminal_reason == "symptom-confirmed"` (the binary successful pod outcome is the base gate; the six-value terminal reason plus `clean` feed the hypothesis verdict via `derive_verdict`).
2. **Fault-class match**: `R`'s spec `spec_id` fault half, or its `target_identity`/`rationale`, maps to `T` through the CWE fault-KB (e.g. `CWE-89` for SQL Injection, `CWE-918` for SSRF, `CWE-22` for Arbitrary File Read, `CWE-79` for XSS, `CWE-1392`/`CWE-521` for weak credentials).
3. **Locus match**: `R`'s spec `target_identity` and the probe URLs in its `raw_observations` resolve to `L` (the L1 unit covering `L` via `AGGREGATES`, or the L0 endpoint set of the spec's target identity).
4. **Symptom confirmation**: the confirmed symptom in `R`'s experiment log (the `interpretations` classified `symptom-confirmed`, the matching `raw_observation`, the `experiment_summary` terminal record) corresponds to `T`'s observable symptom as described in the ground-truth `report.md`/`verify.py`.

A pod run that confirms a symptom at the wrong locus or for the wrong fault class is a **false positive**, not an identification; the predicate is strict on all four conjuncts.

### 3.2 Two-tier scoring

- **Deterministic tier** (the first cut, fully offline): the four conjuncts above, resolved by code. Fault class via the fault-KB mapping table; locus via URL/endpoint/unit resolution; symptom via the terminal-reason + interpretation-classification + the `clean` flag. Deterministic and repeatable.
- **Semantic tier** (optional, then the judge agent): for ambiguous cases (matching free-text symptoms to ground-truth reports), grade the combined evidence against the official vuln blobs and return `match`/`partial`/`no_match` + `matched_vuln_id` + `confidence`, mirroring the AgentPentestBench `LLM_judge` mechanics.

### 3.3 Inputs and output

Inputs per trial: the project id, the hunt run id, the pod artifact root, the WebExploitBench challenge ground truth for the target.

Output per vuln: `{vuln_id, ground_truth_type, ground_truth_location, pod_verdict, pod_terminal_reason, hypothesis_verdict, matched_unit, matched_fault_class, symptom_evidence_ref, judge_status, identified}`.

The trial score: `identified / declared_vulns`, plus per-vuln-class and per-locus breakdowns, plus the integrity columns (target reachability, run liveness, absence-vs-failure gate) so "pipeline found nothing" stays distinguishable from "pipeline failed".

## 4. The orchestration harness

A thin in-repo driver. For each `(target, pass@k attempt)` cell:

1. **Target launch**: request the setup pipeline (section 5) with `{machine_id, challenge_id}`; poll until `ready`; obtain the published target URL.
2. **Fresh project**: `POST /projects` `{name: "<trial-id>"}` -> `project_id`.
3. **Settings**: `PUT /projects/{id}/settings` `{"recon": {...}}` - `target_seed` = the published target URL, neutral `operator_kb` (never leaks the vuln list), feature toggles. Mirrors the `eval-targets.yaml` mechanical application pattern.
4. **Bootstrap**: `POST /projects/{id}/bootstrap`.
5. **Pipeline**: `POST /projects/{id}/recon` `{"jobs": [...], "with_analysis": true}` -> `run_id`; poll `GET .../recon/{run_id}` to terminal.
6. **Hunting**: `POST /projects/{id}/hunting` `{candidates: [...]}` -> `hunting_run_id`; poll `GET .../hunting/{hunting_run_id}` to terminal.
7. **Evidence collection**: read the L1 graph (`GET /projects/{id}/graph`), the hunt store trail, the pod artifact tree (when pod dispatch is wired), and the Langfuse trace ids.
8. **Oracle**: run the deterministic tier; dispatch the judge agent (section 6) for the semantic tier; write the per-vuln verdict rows.
9. **Teardown**: `DELETE` the target via the setup pipeline; record the trial record (per-vuln breakdown + pipeline run ids + timing). Repeat for pass@k with a fresh project and a fresh target instance.

Reuse from CAGE where it is genuinely free: serve-mode target bring-up and the WebExploitBench evaluator infrastructure. The harness itself is the orchestrator; CAGE's agent container, in-container proxy, and agent adapters are dropped (see `eval-harness-agentcyberrange.md` C.7).

Parallelism: one shared polymerhus stack, `project_id` partitions all graph state; the recon executor concurrency caps must accommodate the trial fan-out.

## 5. The setup pipeline (web API)

Rationale: the machine has limited space for target images, and target on-boarding must be on demand and repeatable.
The setup pipeline is a small FastAPI service (or a polymerhus-adjacent module) exposing:

- `POST /targets` `{machine_id, challenge_id}` -> `{target_id, status}`. It pulls the WebExploitBench target image (from GitHub or Hugging Face), builds the container, and configures every polymerhus interfacing point: publishes the target port on the host, seeds the reachable URL, writes the `extra_hosts` alias for the target domain, and registers the readiness probe.
- `GET /targets/{target_id}` -> status, published URL, container health. `ready` only when the target genuinely answers.
- `DELETE /targets/{target_id}` -> teardown (stop container, free the port, drop the alias).
- `GET /targets` -> the on-machine inventory (which target images are already pulled).

`machine_id` lets one pipeline instance serve several machines; each machine's docker daemon is the target host.
The pipeline is the single seam between "a target exists on disk" and "polymerhus can reach and probe it".

## 6. The judge agent

The LLM half of the oracle is a separate agent, brought up through a harness like opencode, NOT a code module.

- **Bring-up**: launched per trial (or per batch) through an opencode-style harness.
- **Instruction**: pointed at the observability system (Langfuse) and at the artifact directories that hold all evidence for evaluating successful discovery: the hunt store tree, the pod artifact tree, the per-project memory, and the eval trial records.
- **Behaviour**: polls the artifact directories periodically for new items. For each completed trial, reads the evidence (PodExport verdict + experiment log + spec variants + L1 graph + Langfuse trace), reconciles it against the WebExploitBench ground truth, and emits the semantic verdict rows (`match`/`partial`/`no_match`, `matched_vuln_id`, `confidence`, with the evidence trail it used).
- **Contract**: the judge's output is a well-formed JSON record per vuln, written to the trial record; the harness merges it with the deterministic tier.

## 7. Metrics and reporting

- **Identification rate**: `identified / declared_vulns` per target (the primary axis).
- **Pass@1 / Pass@3 (Avg) / Pass@3 (Max)**: fresh target + fresh project per attempt, as the paper reports.
- **Per-vuln-class breakdown**: which fault classes the pipeline consistently identifies.
- **Per-locus breakdown**: which units/endpoints the confirmed symptoms land on.
- **Integrity columns** (never scored, always shown): target reachability, run liveness (absence-vs-failure gate on the recon run status + job counts), identity stability note (fresh project per trial, within-trial matching only).

## 8. Gaps and risks

1. **Pod dispatch not wired**: the PodExport path (the strongest signal) requires the hunting agent's `dispatch_fn` to be injected into `start_hunting` (scoped by #110). Until then the oracle grades on the degraded trail (hunt store candidates/configs/notes + L1 graph + Langfuse). The oracle is designed for both; the readiness gap is a polymerhus-side dependency, not a harness defect.
2. **Pod on a branch**: `pod/types.py` and the pod memory store live on `feat/hunting-84-test-executor-pod`, not `main`. The harness's oracle contracts against those shapes; the branch must land before the PodExport path is exercised.
3. **Unit identity instability**: Service slugs are only within-project stable (AMV-12/13, ~41% overlap across runs). Fresh project per trial and within-trial matching is the mitigation.
4. **Oracle false positives**: a symptom-confirmed pod on the wrong locus or wrong fault class must NOT count. The predicate is strict on fault-class AND locus AND symptom conjuncts; the judge agent is the arbiter for ambiguous cases.
5. **Target reachability**: the kali container must resolve and reach the published target (host ports + `extra_hosts` aliasing, the established pattern in `docker-compose.yml:66-70`).
6. **Run-to-run variance**: the paper reports high variance; pass@k with fresh instances is mandatory, never a single pass.
7. **Absence is unmodelled**: polymerhus does not distinguish "ran and found nothing" from "failed". The harness enforces its own liveness/sanity gate on the recon run status + job counts.
8. **Secrets**: `eval-targets.yaml` holds real credentials. The harness never prints, logs, or commits secret material.
9. **Judge cost / availability**: the semantic tier needs a judge model or judge agent available; the deterministic tier is the offline default.

## 9. Open questions for implementation

1. Setup pipeline placement: a standalone service, or a polymerhus-adjacent module? (Standalone recommended; it is target-lifecycle, not pipeline.)
2. Which WebExploitBench challenges seed the first run: the 5 bundled targets, comfyui first, then the rest on demand via the setup pipeline.
3. Judge agent cadence: per-trial synchronous, or a batch poll loop over completed trials?
4. Whether to add the deterministic oracle as a polymerhus `evaluation.py`-style module first, with the judge agent as a later refinement.

## 10. References

- `docs/design/eval-harness-agentcyberrange.md` - the AgentCyberRange architecture study (58-component inventory, adaptation analysis).
- `docs/design/hunting-67-test-executor-pod-spec.md` - the pod contract (D4/D5/D6, four-way termination, variants + experiment log).
- `src/polymerhus/attack/hunting/pod/types.py`, `pod/pod_memory.py`, `pod/context.py`, `pod/verification.py` (branch `feat/hunting-84-test-executor-pod`).
- `src/polymerhus/attack/hunting/hunting_agent.py` (`derive_verdict`), `hunt_store.py`, `runtime.py`.
- `src/polymerhus/project_management/api.py` (project/settings/bootstrap/recon/hunting seams).
- `src/polymerhus/analysis/evaluation.py` (`run_matrix`/`compare` - the in-repo eval convention).
- `tests/e2e/fixtures/eval-targets.yaml` (target settings/launch/ground-truth pattern).
