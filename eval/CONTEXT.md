# Eval Harness

The multi-instance evaluation system that drives polymerhus against a target dataset (WebExploitBench first) and scores discovery.
This glossary is for the eval harness itself; polymerhus's own vocabulary lives in the context map at the repo root.

## Language

**PolyphemusInstance**:
One polymerhus deployment (agent + kali + postgres + neo4j + lightrag) dedicated to an eval instance; identified by a uuid, defined by its `.env` file, and running from its own git worktree detached at the `eval` branch commit.
Detached so any number of instances share the one read-only `eval` branch (git refuses the same branch in two worktrees).
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

**BenchmarkDataset**:
The keyed, first-class benchmark dataset the targets and their ground truth come from, declared once in `eval/datasets/<id>.yaml`: its `id`, remote `repo` (the challenge definitions and per-vuln ground truth), image `registry` (a host/domain plus a URL path prefix; empty means the targets are built, not pulled), `platform_root` (where the per-target platform bank lives), and the `targets[]` list.
It supersedes the old embedded `TargetDataset` value object (`orchestrator/setup.py`); the dataset is addressed by its `id`, and each target by the composite **Target key**.
Its `platform_root` may be an external checkout (used in place so the dataset's own scaffold, such as `scripts/targetctl`, keeps working) or a repo-local bank (resolved relative to `eval/`).
`orchestrator/dataset.py` owns parsing and path resolution.
_Avoid_: benchmark, corpus, repo, TargetDataset

**Target key**:
The one identifier indexing a target across every domain of the eval data: `<dataset>/<target>`.
It indexes the target's bring-up configuration (`eval/targets/<dataset>/<target>.yaml`), its **Platform bank** entry (`<platform_root>/<target>/`), and its project data dependencies (`eval/data/<dataset>/<target>/`), so keying is consistent across configuration, platform, and data.
Both segments are path-safe identifiers; `orchestrator/dataset.py` owns the split and validation.
_Avoid_: target id, target name (the `target_id` is the per-trial identity, not this key)

**TargetConfiguration**:
The bring-up configuration of one target, declared once in `eval/targets/<dataset>/<target>.yaml`: the `compose` file (relative to the target's **Platform bank** entry), the target's image set, the registry pull references, the optional named readiness checker, the `reclaimable` opt-in, and the `runner` (`targetctl`, `compose`, or `image`).
The image set may be omitted and derived from the compose by the dataset helper; `orchestrator/target_config.py` owns parsing and validation.
_Avoid_: target definition, target descriptor

**Platform bank**:
The per-target bring-up scaffolding at the dataset's `platform_root`: the target's compose file and Dockerfiles (plus the dataset's own scaffold, e.g. `scripts/targetctl`).
For `webexploitbench` it is the external WebExploitBench checkout; for the repo-local `mock` dataset it is `eval/platform/mock/`.
_Avoid_: images, docker dir

**Canonical image tag**:
The symbolic image key `ph/<dataset>/<target>[:<service>]`, derived from the target's compose by the dataset helper (the services declaring both `build:` and `image:`), or declared explicitly on the target config.
Provisioning binds every produced image to its canonical tag, and that tag is the one key the store check and reclaim speak; `orchestrator/datasets/base.py` owns the derivation.
_Avoid_: local tag, built image

**Readiness checker**:
The bounded, non-blocking verification that a target is ready after `up`: a `docker compose ps -a --format json` poll of the stack's own health by default, an HTTP port probe for a compose-less target, or a named checker defined per dataset and selected on the target config.
The compose poll is exhaustive: `-a` lists every service (including one-shot inits and not-yet-started services), and a service is ready only when it is `healthy`, or `running` with no healthcheck, or `exited` with code 0.
An HTTP 5xx (500 included) is never a readiness signal.
It never blocks `up`; the chain then verifies readiness under a bounded window, so a slow or broken healthcheck cannot hang the chain.
`orchestrator/readiness.py` owns the plans, and `orchestrator/datasets/base.py` resolves the target's plan.
_Avoid_: healthcheck, wait loop

**Reclaimable**:
A per-target opt-in (default false) to remove the target's own **Canonical image tags** at teardown and after a failed `up`.
A store hit is never reclaimed by provisioning; only the target's own canonical tags are, so a target that does not opt in leaves its images in the store for the next run.
_Avoid_: cleanup, garbage collection

**TargetRun**:
The evaluation of one `<dataset>/<target>` on one instance: its composite target key, its trial identity `target_id` (defaulting to the target segment), its per-trial `TargetConfig`, the phase it starts at, its hunting cap, any pre-mined artifacts, its optional `target_run_id` identity, and its optional `existing_project_id`.
The bring-up configuration and the dataset are resolved from the key at run time, not carried here.
That identity names the artifact store's middle level and is resolved CLI override > setup `target_run_id` > instance id; when set it must be path-safe and unique within the setup.
`existing_project_id` names a pre-recon'd project whose L0/L1 were transferred onto the instance (#277): the trial then enters at hunting, skips creation/settings/scaffold, and asserts the project and its L1; it must be path-safe and unique within the setup, and it forces `start_phase: hunting`.
_Avoid_: job, task

**TargetConfig**:
The per-trial data configuration of a Target: seed, operator KB, auth context, and bootstrapped L1 surface.
The bring-up configuration is not here: it lives in the target's `eval/targets/<dataset>/<target>.yaml` (**TargetConfiguration**).
The seed is the bare Synthetic Host; when a setup leaves it unset the harness derives it from the target-run identity, so routing and scope cannot disagree.
_Avoid_: target definition

**Target image provisioning**:
How the chain obtains one target's image before it starts, by a strict store -> pull -> build precedence: an image already present under its **Canonical image tag** is a store hit and is left alone (never pulled, rebuilt, or reclaimed by provisioning); otherwise a declared pull reference is fetched and bound to the canonical tag; otherwise the target's own compose/Dockerfile builds it and the produced image is bound to the canonical tag - build is the last fallback, not the first.
A target with no store hit, no pull reference, and no built image fails that target hard, and the run moves on to the next target.
Each provisioning is recorded on the step (`store`/`pull`/`build`, where the store tier records as `present`) with the qualified reference actually pulled.
Reclaim happens only when the target is **Reclaimable**; `orchestrator/docker.py` owns the algorithm.
_Avoid_: prebuild, pre-pull, on-demand

**AuthContext**:
The externally bootstrapped authentication state seeded into the store (overview + accounts), plus the project `authn` skill capturing the sign-in/sign-up procedure.
_Avoid_: auth, credentials, session

**Trial**:
One attempt: a fresh target instance and a polymerhus project, from phase entry to terminal.
The project is normally created fresh; a seeded trial (#277) instead reuses the `existing_project_id` as-is (no creation, settings, or scaffold), records `seeded: true`, and enters at hunting.
_Avoid_: attempt, run

**Phase**:
One of the three discovery stages a trial can start at: recon, analysis, or hunting; each phase entry has a persisted-state dependency check.
_Avoid_: stage, step

**Target lifecycle strategy**:
How a target is brought up on the eval host: `targetctl` (WebExploitBench), `compose`, or `image`, selected by the `runner` field of the target's **TargetConfiguration**.
All three run locally on the eval server (D45); none reaches a remote host.
_Avoid_: target kind, deployment

**Synthetic Host**:
The unique per-`TargetRun` hostname (`t-<short>.target`) written into the target front's `server_name` and aliased in that instance's kali `/etc/hosts`; the routing discriminator.
The alias target is the Docker host gateway resolved to a numeric address for every lifecycle (kali is not on the host network, and `/etc/hosts` has no resolver in its address column).
A port-bearing seed was rejected because it breaks the platform's bare-domain scope gate.
_Avoid_: alias, virtual host, domain

**Target front**:
What serves every target on `http://<synthetic-host>/` - the bare domain on the standard web port the platform scope gate requires.
It is the shared host-level `ph-eval-front` nginx container bound to host port 80, carrying one conf per synthetic Host that proxies to the target's published port over the Docker host gateway.
`targetctl`, `image`, and `compose` all use it (D45): no host nginx and no ssh.
The container is created before the first target and removed after the last.
_Avoid_: proxy, reverse proxy, gateway

**Work item**:
An eval-wide pre-eval data dependency (auth bootstrap, L1 surface, hunting artifacts) recorded at the `EvalSetup` level and gated before any target starts (D14).
_Avoid_: prerequisite, checklist

**Hunting cap**:
The per-`Target`-declared bound on hunting, enforced per `Trial`: it counts the hunt configs consumed during the trial, i.e. the files present in the consumed hunt-configs directory whose name is not in the trial's baseline.
The baseline is the set of consumed names already present at the trial's first hunting poll; it is persisted in the trial record (`cap_baseline`) and carried across a resume, so a config consumed by a prior run (or a mounted/pre-mined file already in `consumed/`) never satisfies a new trial's cap, while a stopped trial resumed keeps counting without resetting.
_Avoid_: budget, limit

**Pre-mined hunting artifacts**:
Operator-supplied hunt configs and hunter test specs placed before the project run starts, consumed by the pipeline's normal lazy read.
Hunt configs land in `<data_root>/<project_id>/hunting/orchestration/hunt_configs/produced/`; each test spec carries its `fault_key` and lands in `<data_root>/<project_id>/hunting/hunter/test-specs/<fault_key>/produced/`.
_Avoid_: seeds, preload

**Artifact store**:
The durable host-side location that the instance data root is continuously synced into (D7/D12).
It has two layers: a secondary raw mirror at `<store>/<instance_id>/live/`, streamed one way by `lsyncd` and never an authority, and the authoritative self-contained per-trial tree at `<store>/<target_id>/<target_run_id>/<trial_id>/` holding `verdicts.yaml`, `diagnoses.yaml`, the copied evidence chain, and the run manifest.
The `<target_run_id>` level is the TargetRun identity, not necessarily the instance id.
The store is a sink: nothing ever writes from the store back into the instance data root.
_Avoid_: backup, archive

**Assessment**:
The out-of-band scoring of a completed trial by a background agent, producing `verdicts.yaml`.
_Avoid_: judging, scoring run

**Close verification**:
The eval-close phase that checks every trial's `verdicts.yaml` presence and schema and, once present, the `diagnoses.yaml` pairing (exactly one entry per `missed`/`partial` verdict); it re-dispatches a missing/invalid/unpaired trial at most twice, then micro-diagnoses a bounded configuration-layer repair or a named escalation (D15/D28).
_Avoid_: final check, audit

**Tick control plane**:
The eval orchestrator's post-execution workflow driver (#289): one tick verifies every trial's execution state and advances a single node, from a successful execution to the background assessment and then to the diagnosis.
It is one CLI tick (`orchestrator monitor`) wrapped as the `eval_monitor` custom tool, and it is the only automated path that dispatches the assessment and diagnoser subagents (the manual `assess`/`diagnose` verbs remain); a failed, blocked, or timed-out execution is deferred to the surfer loop.
_Avoid_: monitor loop, watcher, scheduler

**Workflow node**:
One step of the post-execution workflow (`execution`, `assessment`, `diagnosis`), driven by the tick control plane.
Each node has its own prompt under `eval/prompts/` (`orchestrator.md` for the graph, `assessor-workflow.md` and `diagnoser-workflow.md` for the two dispatched nodes), distinct from the subagent role prompt it dispatches.
_Avoid_: stage, step, phase

**Assessment attempt**:
One dispatch or verification step of the assessment subagent, recorded on the trial record with its outcome and, on escalation, a named failure.
_Avoid_: retry, poll

**Eval branch** (`eval`):
The read-only branch the eval environment runs; fast-forwarded from `dev` by the sync daemon only when no eval is executing.
_Avoid_: eval mirror, deploy branch

**Execution-state variable**:
The symbolic runner's authoritative flag that an eval is executing; it gates the sync daemon and must be lock-backed and staleness-recoverable.
_Avoid_: eval lock flag, busy flag

**Evidence chain**:
The per-verdict set of hunting artifacts (hunt config, `TestImplementationSpec`, experiment logs, `PodExport`) plus phase-mapped observability reasoning references that support a positive verdict.
The reasoning references are optional and currently unproduced (designed-not-built, CODING_STANDARD section 12): the resolver's `ReasoningSource` seam is injected but no production source is wired, so a verdict's file chain alone satisfies N13. A trace id may still be supplied via `--trace-id`/`EVAL_TRACE_ID` and is carried in the trial record.
_Avoid_: proof, references

**Diagnosis**:
The per-un-found-vuln root-cause record in `diagnoses.yaml` (paired with `verdicts.yaml`) produced by the diagnoser subagent.
Each record carries exactly one issue reference: a `closest_issue` from the origin bank or, when none matches (or the bank is unavailable), a `proposed_issue` for the operator to file; never both, never neither.
Like a verdict, each record also carries the trial record's `eval_sha` and `stack_fingerprint` (present, non-empty, and checked on write); an invented or mismatched identity is refused.
_Avoid_: post-mortem, failure report

**Failure mode**:
The classification of why a vulnerability was not identified (e.g. `pod_notsufficient_space_coverage`, `hunter_notsufficient_tests_exploration`, `pod_diverged_trajectory`, `surface_gap`, `spec_underspecified`, `cap_hit`, `orchestrator_failed_unit-fault_binding`). Analysis-layer modes are a recorded future extension.
_Avoid_: error, reason

**Surfer loop**:
The background loop that monitors instance state and prompts the orchestrator to assert it and decide: terminate, destroy, or fix (configuration/data layer only) and restart; a jump or repair it cannot bound is escalated into a hold.
Each acted-on trigger is recorded by its deterministic identity in the eval state, so the loop acts once per distinct trigger and skips one it already handled.
_Avoid_: monitor, watchdog

**Version advance**:
The environment-wide move of all instance worktrees from the current `eval` SHA to `dev`'s commit, performed only when all instances are idle.
Each detached HEAD is fast-forwarded; a move that reaches only some worktrees is reported as a partial advance, never as a clean one.
_Avoid_: sync, pull

**Delivery plane**:
The GitHub Actions CD controller's responsibility: fast-forwarding the eval server's canonical `dev` checkout from `origin/dev` on every push to `dev`; it never touches `eval` or instance worktrees, and it never fetches on the daemon's behalf.
_Avoid_: deployment, CD, release

**Idle proxy**:
The read of the app module's running-state surface (`GET /app-state`, with the documented direct-postgres fallback) that tells the sync daemon whether every instance is idle; unknown state is never treated as idle.
_Avoid_: eval lock, busy flag, execution-state variable

**Heartbeat**:
The file the sync daemon atomically rewrites every poll carrying the observed `dev` and `eval` SHAs, the idle verdict, the advance state, each worktree's observed HEAD, the last error, and the timestamp of the last advance.
_Avoid_: status file, health check

**Last-known-good SHA**:
The `eval` SHA the sync daemon records before each advance; the only SHAs an operator rewind may target.
_Avoid_: checkpoint, backup ref

**Rewind**:
The operator-only rollback of every eval worktree to a recorded last-known-good SHA, behind an explicit confirmation flag; the daemon's polling loop can never perform one.
_Avoid_: rollback, revert, reset

**Stack fingerprint**:
A single compressed hash over the stack manifest (alignment-relevant artifact SHAs plus running image digests) that tells whether a version advance needs an alignment action.
_Avoid_: build hash, checksum

**Alignment action**:
The restart, recreate, or config-layer adjustment a version advance requires for an impacted component, decided by the eval orchestrator (not hardcoded); a jump the orchestrator cannot align without an operator decision is escalated and held.
_Avoid_: deploy, rollout

**Hold**:
The atomic marker an escalation writes in the eval state: until an operator resolves it, `up`/`trial` refuse to start and name the hold and its rationale; resolving records the operator's decision and clears the block, without reverting the advance.
Both an alignment escalation and a surfer escalation write one, through the same mechanism.
_Avoid_: lock, freeze, pause

**Eval compose overlay**:
`docker-compose.eval.yml`: it requires the per-instance `.env`, fails loud on missing required interpolation, and pairs with the preflight that fills missing keys without clobbering operator values.
_Avoid_: prod compose, eval env

**Root cause type**:
The typed locus of a diagnosis: `implementation_defect`, `design_defect`, `missing_component`, `kb_coverage_gap`, or `skill_defect` (combinable).
_Avoid_: cause, blame
