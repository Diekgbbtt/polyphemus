# Eval Harness

The multi-instance evaluation system that drives polymerhus against a target dataset (WebExploitBench first) and scores discovery.
This glossary is for the eval harness itself; polymerhus's own vocabulary lives in the context map at the repo root.

## Language

**PolyphemusInstance**:
One polymerhus deployment (agent + kali + postgres + neo4j + lightrag) dedicated to an eval instance; identified by a uuid and defined by its `.env` file.
_Avoid_: system instance, stack, system

**EvalSetup**:
The root configuration of one evaluation: the set of instances and the targets each runs, plus the durable artifact store location.
_Avoid_: eval config, run config

**InstanceConfiguration**:
The per-instance configuration, which references a manually managed `.env` file and declares the instance's serial target pipeline.
_Avoid_: instance config, env

**Target**:
The evaluated application a trial runs against; WebExploitBench's unit is called a `challenge`.
_Avoid_: challenge, app

**TargetRun**:
The evaluation of one Target on one instance: its linked target configuration, the phase it starts at, its hunting cap, and any pre-mined artifacts.
_Avoid_: job, task

**TargetConfig**:
The linked configuration of a Target: lifecycle strategy, seed, operator KB, auth context, and bootstrapped L1 surface.
_Avoid_: target definition

**AuthContext**:
The externally bootstrapped authentication state seeded into the store (overview + accounts), plus the project `authn` skill capturing the sign-in/sign-up procedure.
_Avoid_: auth, credentials, session

**Trial**:
One attempt: a fresh target instance and a fresh polymerhus project, from phase entry to terminal.
_Avoid_: attempt, run

**Phase**:
One of the three discovery stages a trial can start at: recon, analysis, or hunting; each phase entry has a persisted-state dependency check.
_Avoid_: stage, step

**Target lifecycle strategy**:
How a target is brought up on the remote host: `targetctl` (WebExploitBench), `image`, or `compose`.
_Avoid_: target kind, deployment

**Hunting cap**:
The per-Target bound on hunting, counted as the number of files in the consumed hunt-configs directory (including mounted/pre-mined files).
_Avoid_: budget, limit

**Pre-mined hunting artifacts**:
Operator-supplied hunt configs/specs placed at a mounted location before the project run starts, consumed by the pipeline's normal lazy read.
_Avoid_: seeds, preload

**Artifact store**:
The durable host-side location that the instance data root is continuously synced into.
_Avoid_: backup, archive

**Assessment**:
The out-of-band scoring of a completed trial by a background agent, producing `verdicts.yaml`.
_Avoid_: judging, scoring run

**Eval branch** (`eval`):
The read-only branch the eval environment runs; fast-forwarded from `dev` by the sync daemon only when no eval is executing.
_Avoid_: eval mirror, deploy branch

**Execution-state variable**:
The symbolic runner's authoritative flag that an eval is executing; it gates the sync daemon and must be lock-backed and staleness-recoverable.
_Avoid_: eval lock flag, busy flag

**Evidence chain**:
The per-verdict set of hunting artifacts (hunt config, `TestImplementationSpec`, experiment logs, `PodExport`) plus phase-mapped observability reasoning references that support a positive verdict.
_Avoid_: proof, references

**Diagnosis**:
The per-un-found-vuln root-cause record in `diagnoses.yaml` (paired with `verdicts.yaml`) produced by the diagnoser subagent.
_Avoid_: post-mortem, failure report

**Failure mode**:
The classification of why a vulnerability was not identified (e.g. `pod_notsufficient_space_coverage`, `hunter_notsufficient_tests_exploration`, `pod_diverged_trajectory`, `surface_gap`, `spec_underspecified`, `cap_hit`, `orchestrator_failed_unit-fault_binding`). Analysis-layer modes are a recorded future extension.
_Avoid_: error, reason

**Surfer loop**:
The background loop that monitors instance state and prompts the orchestrator to assert it and decide: terminate, destroy, or fix (configuration/data layer only) and restart.
_Avoid_: monitor, watchdog

**Version advance**:
The environment-wide move of all instance worktrees from the current `eval` SHA to `dev`'s commit, performed only when all instances are idle.
_Avoid_: sync, pull

**Stack fingerprint**:
A single compressed hash over the stack manifest (alignment-relevant artifact SHAs plus running image digests) that tells whether a version advance needs an alignment action.
_Avoid_: build hash, checksum

**Alignment action**:
The restart, recreate, or config-layer adjustment a version advance requires for an impacted component, decided by the eval orchestrator (not hardcoded); a jump the orchestrator cannot align without an operator decision is escalated and held.
_Avoid_: deploy, rollout

**Eval compose overlay**:
`docker-compose.eval.yml`: it requires the per-instance `.env`, fails loud on missing required interpolation, and pairs with the preflight that fills missing keys without clobbering operator values.
_Avoid_: prod compose, eval env

**Root cause type**:
The typed locus of a diagnosis: `implementation_defect`, `design_defect`, `missing_component`, `kb_coverage_gap`, or `skill_defect` (combinable).
_Avoid_: cause, blame
