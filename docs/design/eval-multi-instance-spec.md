# Spec: Multi-Instance Eval Harness

*Status: draft for implementation.
Synthesized from the round-1 to round-5 grill, recorded in `docs/design/eval-multi-instance-decisions.md` (D1-D47, R1-R17), `docs/design/eval-environment-version-pinning-adr.md` (RATIFIED), and the FR rewrite in `docs/design/eval-harness-multi-instance-solution.md` (N1-N19).
The keyed dataset and target model of spec #301 is recorded in `docs/design/eval-dataset-domain-model-impact-map.md` (D47).
Glossary: `eval/CONTEXT.md` (moves with the restructure from `tools/eval/CONTEXT.md`).*

## Problem Statement

The operator cannot currently run reproducible, attributable, multi-target evaluations of polymerhus's vulnerability-discovery capability.

The existing eval path is a single shared polymerhus stack with a fresh project id per trial.
Global surfaces (one LightRAG workspace, one kali exec plane, one ingest registry, a process-global module control plane, an unscoped `GET /runs`) mean results are not isolated, and two trials cannot run in parallel.
Target lifecycle, auth bootstrap, hunting caps, and teardown are hand-driven through ad-hoc scripts under `tools/eval/`, several of which read pre-#234 paths and silently report empty evidence.
An eval produces a score but no learning: a verdict does not carry the artifacts backing it, and an undiscovered vulnerability is not root-caused, so the same defects recur across trials.
The continuous delivery pipeline can change the evaluated version mid-eval, invalidating a comparison without leaving a trace.
There is no durable, self-contained record of a trial that an assessor, a diagnoser, or the operator can read after the fact.

## Solution

A multi-instance eval harness rooted at `eval/` (brought up one layer from `tools/eval/`) that:

- runs an `EvalSetup` over one or more `PolyphemusInstance`s, each a full polymerhus stack, each running from its own git worktree off the read-only `eval` branch;
- gives every `Trial` a fresh target instance and a fresh project, routed by a unique synthetic Host, able to enter at recon, analysis, or hunting behind persisted-state predicates;
- chains the setup outcome directly into execution: the orchestrator fixes configuration-layer failures or starts the eval;
- enforces a per-`Target`-declared hunting cap, counted trial-scoped from the consumed directory against a persisted baseline, and supports pre-mined hunting artifacts mounted before a run;
- produces evidence-chained `verdicts.yaml` through an asynchronous assessment subagent, with an eval-close verification phase, then a diagnoser subagent writes `diagnoses.yaml` for every `missed` and `partial` vuln, root-causing into code **and** the persisted data layer;
- pins the evaluated version: GitHub Actions delivers to `dev`, a systemd sync daemon advances the `eval` branch only when all instances are idle, emitting a stack manifest and fingerprint, and the orchestrator decides and executes the alignment action, escalating to the operator when a jump is not alignable without a decision;
- keeps a durable artifact store through a one-way continuous sync, one self-contained directory per trial.

## User Stories

1. As an operator, I want to declare an `EvalSetup` (the benchmark datasets by key, instances, targets, caps, pre-mined artifacts, artifact store) in one place, so that an evaluation is reproducible.
2. As an operator, I want each instance configured by an `InstanceConfiguration` that references a manually managed `.env`, so that ports, LLM roles, and provider keys are explicit and diffable.
3. As an operator, I want the harness to start, stop, and destroy instance stacks, so that I do not drive docker by hand.
4. As an operator, I want a preflight that fills missing `.env` keys from `.env.example` without clobbering my values, so that compose interpolation never drifts silently.
5. As an operator, I want an eval compose overlay that fails loud on missing required environment, so that a stale `.env` is caught before a run starts.
6. As an operator, I want the eval toolkit brought up to `eval/` with helper scripts placed cohesively and obsolete ones removed, so that the harness is navigable and maintainable.
7. As an operator, I want per-target parameters (ports, LLM role models, provider API keys) expressible per instance, so that comparative arms can differ.
8. As an eval orchestrator, I want a strategy-typed target lifecycle (`targetctl`, `compose`, `image`) selected from each target's `TargetConfiguration` behind one interface, so that WebExploitBench and pullable-container targets follow the same contract.
9. As an eval orchestrator, I want a unique synthetic Host per `TargetRun`, registered in the target front and aliased in the instance kali, so that two instances can address the same target unambiguously.
10. As an operator, I want target bring-up, readiness verification, and teardown cycles proven repeatable, so that runs can be trusted.
11. As an operator, I want pre-eval work items (auth bootstrap, L1 surface, hunting artifacts) recorded at the `EvalSetup` level and gated, so that no trial starts unprepared.
12. As an eval orchestrator, I want `Trial`s to enter at recon, analysis, or hunting with persisted-state predicates, so that partial re-runs are possible.
13. As an eval orchestrator, I want the recon-entry predicate to include the project-specific `authn` skill and the seeded `AuthContext` (overview and credentials), so that authenticated targets are exercised.
14. As an eval orchestrator, I want to chain the setup outcome into execution, fixing configuration-layer failures or starting the eval, so that setup and run are one coherent procedure.
15. As an operator, I want a hunting cap declared per `Target` and counted per `Trial` from the consumed hunt-config directory against a persisted baseline, so that a prior run's configs never satisfy a new trial's budget while a resumed trial keeps counting.
16. As an operator, I want pre-mined hunting artifacts mounted before a run and consumed lazily by the pipeline, so that prior work can seed a trial.
17. As a surfer loop, I want to assert instance state in the background and prompt the orchestrator on cap-reached or failed state, so that stuck or credit-exhausted runs are handled.
18. As the eval orchestrator, I want to decide between terminate, destroy, and fix-and-restart on a failed instance, bounded to configuration and data-layer repairs, so that recovery is deliberate.
19. As an assessor, I want every `identified` or `partial` verdict to carry an evidence chain (hunt config, `TestImplementationSpec`, experiment logs, `PodExport`) with data-root-relative paths, so that the verdict is auditable.
20. As an assessor, I want the evidence chain to also reference observability reasoning (state assertions, decision nodes, taken branches with rationale, mapped to workflow phases), so that "researched in that direction" is evidenced.
21. As an operator, I want the assessment subagent to receive the trial record, ground truth, data root, and destination, and to write `verdicts.yaml` only, so that scoring is isolated from the run.
22. As an eval orchestrator, I want an eval-close verification phase that checks `verdicts.yaml` presence, re-dispatches twice, and then micro-diagnoses, so that assessment failures surface.
23. As an operator, I want verdicts to carry the `eval` SHA and the stack fingerprint, so that results are attributable to a system version.
24. As a diagnoser, I want to run a dedicated adapted procedure built on the scientific debugging loop, so that root-causing is systematic rather than anecdotal.
25. As an operator, I want `diagnoses.yaml`, paired with `verdicts.yaml`, with one entry per `missed` and `partial` vuln, so that the eval closes the loop.
26. As an operator, I want each diagnosis to carry a failure mode, a typed root cause with an extended description and combinations, a diagnosis overview, and evidence references, so that findings aggregate across trials.
27. As an operator, I want root causes typed across code (`implementation_defect`, `design_defect`, `missing_component`) and the persisted data layer (`kb_coverage_gap`, `skill_defect`), so that data-layer defects are first-class.
28. As a diagnoser, I want to ground on the design docs and counter-check the relevant code area, reasoning mostly over observability, so that every diagnosis cites facts.
29. As a diagnoser, I want to search the issue bank for the closest matching issue and either reference it or write a proposed issue, so that findings connect to the backlog without violating work authority.
30. As an operator, I want a confirmed failure-mode taxonomy with analysis-layer modes recorded as a future extension, so that classifications stay honest.
31. As an operator, I want the diagnosis to interact with the environment (observability, artifacts, code, docs) without modifying the trial, so that evidence stays pristine.
32. As an evaluator, I want one full stack per instance, so that data-plane collisions cannot contaminate results.
33. As an evaluator, I want one instance per worktree off the `eval` branch, so that instances share objects while keeping filesystem and data isolation.
34. As an operator, I want the CD controller (GitHub Actions) to own `origin/dev` into the server's `dev` worktree, and the sync daemon to own `dev` into `eval`, so that responsibilities do not overlap.
35. As an operator, I want the sync daemon to fast-forward `eval` only when all instances are idle, reading idle state from the app-state proxy with a postgres fallback, so that CD never changes the evaluated version during an effective execution.
36. As an operator, I want leaked workbench edits stashed and popped across an advance, so that a dirty tree neither blocks the advance nor loses work.
37. As an operator, I want every advance to emit a stack manifest (per-artifact SHAs plus running image digests) and a compressed stack fingerprint, so that "what changed" is one value and "what must restart" is a diff.
38. As an eval orchestrator, I want to assert SHA differences and decide the alignment action myself, with the impact map as guidance and no hardcoded fail-closed set, so that alignment adapts to reality.
39. As an operator, I want a jump the orchestrator cannot align without an operator decision to be escalated and held, so that nothing is advanced or rebuilt silently.
40. As an operator, I want the last-known-good `eval` SHA recorded before each advance and a rewind available only to me, so that rollback is deliberate.
41. As an operator, I want a one-way continuous sync of each instance data root into the artifact store, so that the store is a durable sink and never an authority.
42. As an operator, I want an artifact-store layout that is self-contained per trial (verdicts, diagnoses, copied evidence chain, run manifest), so that a trial can be read after the fact without the live stack.
43. As an operator, I want Langfuse traces correlated per trial and run, so that the assessor and diagnoser can reason over real executions.
44. As an operator, I want the eval system's glossary next to it, so that the harness vocabulary is discoverable.

## Implementation Decisions

### Vocabulary

The eval glossary (`eval/CONTEXT.md`) is the canonical vocabulary: `PolyphemusInstance`, `EvalSetup`, `InstanceConfiguration`, `Target`, `BenchmarkDataset`, `Target key`, `TargetConfiguration`, `Platform bank`, `Canonical image tag`, `Readiness checker`, `Reclaimable`, `TargetRun`, `TargetConfig`, `Target image provisioning`, `AuthContext`, `Trial`, `Phase`, `Target lifecycle strategy`, `Hunting cap`, `Pre-mined hunting artifacts`, `Artifact store`, `Assessment`, `Evidence chain`, `Diagnosis`, `Failure mode`, `Root cause type`, `Eval branch`, `Version advance`, `Stack fingerprint`, `Alignment action`, `Eval compose overlay`, `Surfer loop`.

### Benchmark dataset and target configuration (spec #301)

The benchmark dataset is a first-class, keyed artifact, declared once in `eval/datasets/<id>.yaml` (id, remote repo, image registry, platform root, targets).
It supersedes the embedded `TargetDataset` value object; the dataset is addressed by its `id` and each target by the composite `Target key` `<dataset>/<target>`.
That one key indexes the target's bring-up configuration (`eval/targets/<dataset>/<target>.yaml`), its platform bank entry (`<platform_root>/<target>/`), and its project data dependencies (`eval/data/<dataset>/<target>/`).
`EvalSetup.datasets` lists the datasets in play by key; `TargetRun` carries `target_key`, `target_id`, and the per-trial data (`TargetConfig`: seed, KB, auth, L1).

The target's bring-up configuration is `TargetConfiguration` (`orchestrator/target_config.py`): compose, image set, registry pull references, readiness checker, `reclaimable`, and runner.
The per-dataset helper (`orchestrator/datasets/base.py`) derives the target's images from the compose and binds each to its `Canonical image tag` `ph/<dataset>/<target>[:<service>]`.

Target image provisioning follows the precedence store -> pull -> build: a store hit under the canonical tag is left alone (never pulled, rebuilt, or reclaimed), otherwise a declared pull reference is fetched and bound, otherwise the target's own build produces it and the produced image is bound; a missing image is a hard failure for that target.
Reclaim of a target's own canonical tags is opt-in per target (`reclaimable`, default false) and happens at teardown and after a failed up.
Readiness is bounded and non-blocking (`orchestrator/readiness.py`): a plan of one or more probes, every one of which must answer ready.
The plan defaults from the target's composition: the compose's own health when the application-serving services declare a healthcheck, the composite target front + per-application-service port + compose plan when they do not, and a port probe for a compose-less target.
The front probe is the same bare-domain path recon uses, and each application service the challenge publishes in `target_ports` is probed on its own port, so a booting backend is never read ready behind a serving front root (`docs/design/eval-target-readiness-http-checker-adr.md`, #323).
The model, its module seams, and the migration are recorded in `docs/design/eval-dataset-domain-model-impact-map.md` (D47).

### Restructure

`tools/eval/` moves up one layer to `eval/` at the repo root.
The harness gains sub-areas: the symbolic orchestrator, the advancement daemon (decision function, live executor, systemd unit), the compose overlay, target lifecycle strategies, the polymerhus API client, the L1 scaffold, the oracle (ground truth plus CWE mapping), KB materials, and the glossary.
Disposition of the existing scripts: `ph.py` (API client), `scaffold.py` (deterministic L1 scaffold), `gt.py` plus `cwes.yaml` (ground truth) are kept as sources; `ev.py` and `hunting_ctl.py` are rewritten against the #234 data root; `target.sh` and `hosts.sh` become the target and routing strategy implementations; `PLAYBOOK.md`, `OPERATOR.md`, and `kb-authoring.md` fold into one operator guide; the committed historical `runs/` artifacts are removed as obsolete.
The sealed vulnerability research corpus stays outside the harness (eval-integrity boundary).

### Three planes

Delivery (GitHub Actions CD controller) owns `origin/dev` into the server's `dev` worktree.
Advancement (the sync daemon, a systemd unit with a heartbeat file) owns `dev` into the `eval` worktrees and never fetches and never rewinds.
Execution (the orchestrator plus the surfer loop) owns trials, lifecycle, state assertion, configuration-layer repairs, assessment, and diagnosis.

### Idle window

Advances are environment-wide and only when all instances are idle.
Idle means no effective project execution; the window may remain open during assessment and diagnosis because eval-specific artifacts are gitignored.
The gate filters any jump that deterministically touches eval-specific non-gitignored artifacts or the underlying component-stack configuration.

### Stack manifest, fingerprint, and alignment

Every advance computes a stack manifest (one SHA per alignment-relevant artifact, plus the digests of the images actually running) and a compressed stack fingerprint.
The orchestrator asserts any SHA difference and decides the alignment action per impacted component, using the documented impact map as guidance: none for source, skills, and lightrag; restart kali for `kali/**`; restart litellm for `gateway/**`; recreate for compose changes; configuration-layer alignment for the env schema; migration or rebuild plus recreate where declared and possible.
No hardcoded fail-closed set exists; an unalignable jump is escalated to the operator and held.
Each advance records the last-known-good SHA before moving.

### Eval compose overlay and preflight

A `docker-compose.eval.yml` overlay requires the per-instance `.env` (`required: true`) and fails loud on missing required interpolation.
A preflight always fills missing keys from `.env.example` into the instance `.env` without clobbering operator values, and the keyset drift is reported in the manifest.

### Orchestrator and lifecycle

The orchestrator is the symbolic layer: it renders instance stacks, runs the setup, chains the setup outcome into execution (fixing configuration-layer failures or starting the eval), drives phases, gating, caps, close verification, and artifact migration.
The agent's judgement is used for the alignment decision and the bounded micro-diagnosis; the surfer loop asserts state in the background and prompts the orchestrator.
Self-repair is configuration-layer only; a required new configuration decision is escalated to the operator.

### Phases

A `Trial` may enter at recon, analysis, or hunting.
Recon entry: project exists, `settings.target_seed` set, L1 scaffold present, target reachable from kali, and, when the target declares an auth surface, the project `authn` skill and the seeded `AuthContext` (overview and credentials).
Analysis entry: the recon run is terminal with job rows and L0 count above zero.
Hunting entry: analysis drained (or L1 present) and pre-mined artifacts in place when configured.
A single failed recon job is note-and-continue.

### Hunting cap and pre-mined artifacts

The cap is declared per `Target` but enforced per `Trial`: it counts the hunt configs consumed during the trial, against a baseline of the consumed names already present at the trial's first hunting poll. The baseline is persisted in the trial record and carried across a resume, so files consumed by a prior run (or mounted before the trial started) are baseline, not count; a new trial id snapshots a fresh baseline.
Enforcement is symbolic: at the cap the orchestrator stops the hunting run and records the trial-scoped overshoot margin.

### Vesting schemas

Decision-rich shapes (from the designs, not from code):

`verdicts.yaml` per trial:

```yaml
- vuln_id: string
  identified: identified | partial | missed
  confidence: number
  matched: {unit, fault_class, symptom}
  evidence_chain:            # required for identified and partial
    hunt_config: path        # data-root-relative
    spec_dir: path
    experiment_logs: [path]
    pod_export: path
    reasoning:               # optional, phase-mapped
      - {phase, decision_node, rationale, observation_ref}
  eval_sha: string
  stack_fingerprint: string
```

`diagnoses.yaml`, paired, one entry per `missed` and `partial` vuln:

```yaml
- vuln: string               # same identifier as the verdict
  failure_mode: pod_notsufficient_space_coverage
              | hunter_notsufficient_tests_exploration
              | pod_diverged_trajectory
              | surface_gap | spec_underspecified | cap_hit
              | orchestrator_failed_unit-fault_binding
  root_cause:
    type: implementation_defect | design_defect | missing_component
        | kb_coverage_gap | skill_defect
    combination_of: [type]
    extended_description: string
  diagnosis_overview: string
  evidences: [{source, ref, note}]
  closest_issue: {repo, number, title, rationale} | null
  proposed_issue: {title, body, labels} | null
  eval_sha: string             # copied from the trial record, never invented
  stack_fingerprint: string     # copied from the trial record, never invented
```

More failure modes are expected, particularly in the analysis layer; they are recorded as a future extension once the corpus is large enough to cite them.
Like a verdict row, every diagnosis row carries the trial record's `eval_sha` and `stack_fingerprint`; a missing or mismatched identity is refused on write.

### Assessment

On execution completion the orchestrator dispatches a background assessment subagent that writes `verdicts.yaml` into the trial directory and never blocks the next target.
The assessor receives the trial record, the ground truth, the instance data root, and the destination, and writes only that file.
No polling: the eval-close verification phase checks presence, re-dispatches missing trials twice, then micro-diagnoses the cause.

### Diagnosis

For every `missed` and `partial` vuln, a diagnoser subagent writes one `diagnoses.yaml` entry.
It runs a dedicated adapted procedure built on the scientific debugging loop; it reasons over the observability platform, reads the produced hunting artifacts, grounds on the design docs (primarily the agent-stack docs), counter-checks the relevant code area, searches the issue bank for the closest match, and may propose (never file) an issue.
The defect may live in code or in the persisted data layer: KB coverage gaps, skill procedural drift, or a missing procedure for a payload, vector, trust-assumption variant, or bypass/proxy technique.

### App-state seam

The only polymerhus-core change is a read-only app-module API surface exposing running project and run state, used as the idle proxy, with a direct postgres query as the documented fallback.

### Artifact store

One-way continuous sync (lsyncd) streams each instance data root into the artifact store.
The store layout is `<store>/<target>/<target_run>/<trial>/` holding `verdicts.yaml`, `diagnoses.yaml`, the copied evidence chain, and the run manifest.

## Testing Decisions

The discipline is `/to-assertions`: this spec is projected into contract predicates (integration tier) and walkthrough predicates (end-to-end tier), each attributed to a seam, then mechanised as tests in those tiers.
Quality-assurance-oriented assertions are disregarded by operator ruling; the concern is functional-requirement coverage.

Seams, confirmed with the operator:

1. The eval orchestrator entry (`eval/`): drives one `EvalSetup` end to end and is asserted on the artifacts it writes and the decisions it takes.
2. The advance assertion and alignment decision, exercised by the orchestrator over the daemon's manifest diff; the daemon itself stays a thin mechanical executor behind the same seam.
3. The app-state endpoint, asserted in the existing REST API test tier.

Config-level verification replaces live runs only where a live run is impossible: `docker compose -f base -f dev -f eval config` rendering for the overlay, and schema validation for `verdicts.yaml` and `diagnoses.yaml` as integration tests.

Walkthroughs run live: the whole eval harness up with the polymerhus stack(s), the targets running locally on the eval host (D45), LLM providers, Steel, and Langfuse real.
Every walkthrough's bootstrap data that only the operator can supply (the target checkout, the eval server key, amd64 binfmt emulation on an aarch64 host (D46), per-instance `.env` values, seeded credentials) is named and requested by name before it is mechanised; a walkthrough whose bootstrap is unanswered is carried as blocked, never substituted with a double.

Prior art: the live e2e suite (`tests/e2e/`), the eval playbook runs (`eval/runs/` historical, the juice-shop-remote run), and the analysis evaluation harness.

## Out of Scope

- Exploitation and post-exploitation; scoring beyond the discovery-identification predicate.
- Horizontal scaling and machine-level resource limits (vertical scaling only; normally one instance).
- Fixing the unscoped single-stack API endpoints beyond adding the app-state read surface.
- Completing the analysis-layer failure-mode taxonomy (future extension).
- The local Steel runtime (#245) and other unrelated workstreams.
- PR and merge workflow changes; this spec does not alter the `dev`/`main` integration contract.

## Further Notes

- Companion docs: `docs/design/eval-harness-multi-instance-solution.md` (FR rewrite, impact map), `docs/design/eval-multi-instance-decisions.md` (D1-D47, R1-R17), `docs/design/eval-environment-version-pinning-adr.md` (RATIFIED), `docs/design/eval-harness-design.md` (oracle and target pipeline), `docs/design/eval-harness-agentcyberrange.md` (architecture study), `docs/design/eval-dataset-domain-model-impact-map.md` (the keyed dataset and target model, #301).
- Carried risks: R2 target agnosticity is asserted, not proven; R16 manifest completeness; R17 env-schema drift; the ADR's still-open items (alert threshold, manifest review discipline, env-rename reporting, the PR-contract note).
- Next step: `/to-tickets` over this spec, then `/to-assertions` over each ticket.
- The eval environment is not production; the `eval` branch is never merged, and verdicts may belong to a `dev` commit that has not shipped.
