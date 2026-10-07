# Eval Harness

The multi-instance evaluation system that drives polymerhus against a target dataset (WebExploitBench first) and scores discovery.
This glossary is for the eval harness itself; polymerhus's own vocabulary lives in the context map at the repo root.

## Language

**PolyphemusInstance**:
One polymerhus deployment (agent + kali + postgres + neo4j + lightrag) dedicated to an eval instance; identified by a uuid, defined by its `.env` file, and running from its own git worktree detached at the `eval` branch commit.
Detached so any number of instances share the one read-only `eval` branch (git refuses the same branch in two worktrees).
_Avoid_: system instance, stack, system

**Instance worktree**:
The per-instance git worktree, `<instances_root>/<instance_id>`, detached at the `eval` branch commit.
It holds the instance's `.env` and its data root (`data/`) - the live evidence (hunt store, project/pod memory, L0+L1 graph, auth, skills).
`up` CREATES it idempotently when absent and brings up the stack from it; the stack lifecycle NEVER removes it - a `down`, a project stop/drain, or an eval termination preserves the worktree and its data root.
Removal is an operator-only action (`orchestrator worktree-remove`), deliberately outside the loop, that re-provisions an instance from scratch.
_Avoid_: checkout, instance dir, tree

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
The keyed, first-class benchmark dataset the targets and their ground truth come from, declared once in `eval/datasets/<id>.yaml`: its `id`, remote `repo` (the challenge definitions and per-vuln ground truth), image `registry` (a host/domain plus a URL path prefix; empty means the targets are built, not pulled), `platform_root` (where the per-target platform bank lives), the `targets[]` list, and the `exclude_services[]` every target keeps out of its stack.
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
The bring-up configuration of one target, declared once in `eval/targets/<dataset>/<target>.yaml`: the `compose` file (relative to the target's **Platform bank** entry), the target's image set, the registry pull references, the optional named readiness checker, the `reclaimable` opt-in, any target-level `exclude_services`, and the `runner` (`targetctl`, `compose`, or `image`).
The image set may be omitted and derived from the compose by the dataset helper; `orchestrator/target_config.py` owns parsing and validation.
_Avoid_: target definition, target descriptor

**Excluded service**:
A service the stack keeps out (D49), declared on the **BenchmarkDataset** (every target) or on one **TargetConfiguration** (that target), most notably the WebExploitBench `evaluator`.
The `targetctl` strategy renders the exclusions into a generated compose: it cuts each named service block and every `depends_on` edge pointing at it from a `docker compose config` resolution of the target's compose, and `up`/`build`/`ps`/`down` use that copy. The upstream compose is never edited.
An excluded service is not a **Canonical image tag**: it is never built, pulled, reclaimed, or asserted by **Readiness**.
_Avoid_: disabled service, skipped service, removed service

**Platform bank**:
The per-target bring-up scaffolding at the dataset's `platform_root`: the target's compose file and Dockerfiles (plus the dataset's own scaffold, e.g. `scripts/targetctl`).
For `webexploitbench` it is the external WebExploitBench checkout; for the repo-local `mock` dataset it is `eval/platform/mock/`.
_Avoid_: images, docker dir

**Canonical image tag**:
The symbolic image key `ph/<dataset>/<target>[:<service>]`, derived from the target's compose by the dataset helper (the services declaring both `build:` and `image:`), or declared explicitly on the target config.
Provisioning binds every produced image to its canonical tag, and that tag is the one key the store check and reclaim speak; `orchestrator/datasets/base.py` owns the derivation.
_Avoid_: local tag, built image

**Readiness checker**:
The bounded, non-blocking verification that a target is ready after `up`, as a **Readiness plan** of one or more probes that every one of must answer ready: a `docker compose ps -a --format json` poll of the stack's own health, an HTTP probe, or both.
The compose poll is exhaustive: `-a` lists every service (including one-shot inits and not-yet-started services), and a service is ready only when it is `healthy`, or `running` with no healthcheck, or `exited` with code 0.
The plan is selected by default from the target's own composition, with no per-target opt-in: a `targetctl`/`compose` target whose application-serving services declare a healthcheck uses the compose poll alone; one whose application services declare no healthcheck uses the **composite** plan; a compose-less target probes its published port.
The application-serving services are the challenge's own `application_service_keys` (`challenge.json`), or the compose's built services when that metadata is absent.
The composite pairs the compose poll with the **Target front** HTTP probe on the host loopback carrying the synthetic Host, and with one HTTP probe per application service the challenge publishes in `target_ports`.
The front probe asserts the bare-domain routing and the front's own upstream, so the front's `502` (while that port is still binding) is never a ready signal.
Each application-service probe resolves the service's own published host port with `docker compose port` and reads its answer, so a booting backend is never read ready while only a sibling service answers (the #323 multi-service gap), and the support services stay asserted by the compose poll.
An unknown named `checker` fails loud rather than falling back to compose health; a target may still declare one, and the named `http` checker is composite when a compose is resolvable.
An HTTP 5xx (500 included) is never a readiness signal.
It never blocks `up`; the chain then verifies readiness under a bounded window, so a slow or broken healthcheck cannot hang the chain.
`orchestrator/readiness.py` owns the plans, and `orchestrator/datasets/base.py` resolves the target's plan.
_Avoid_: healthcheck, wait loop

**Reclaimable**:
A per-target opt-in (default false) to remove the target's own **Canonical image tags** at teardown and after a failed `up`.
A store hit is never reclaimed by provisioning; only the target's own canonical tags are, so a target that does not opt in leaves its images in the store for the next run.
_Avoid_: cleanup, garbage collection

**TargetRun**:
The evaluation of one `<dataset>/<target>` on one instance: its composite target key, its trial identity `target_id` (defaulting to the target segment), its per-trial `TargetConfig`, the phase it starts at, its token budget, any pre-mined artifacts, its optional `target_run_id` identity, and its optional `existing_project_id`.
The bring-up configuration and the dataset are resolved from the key at run time, not carried here.
That identity names the artifact store's middle level and is resolved CLI override > setup `target_run_id` > instance id; when set it must be path-safe and unique within the setup.
`existing_project_id` names a pre-recon'd project whose L0/L1 were transferred onto the instance (#277): the trial then enters at hunting, skips creation/settings/scaffold, and asserts the project and its L1; it must be path-safe and unique within the setup, and it forces `start_phase: hunting`.
_Avoid_: job, task

**TargetConfig**:
The per-trial data configuration of a Target: seed, operator KB, auth context, and bootstrapped L1 surface.
The bring-up configuration is not here: it lives in the target's `eval/targets/<dataset>/<target>.yaml` (**TargetConfiguration**).
The seed is the bare Synthetic Host; when a setup leaves it unset the harness derives it from the target-run identity, so routing and scope cannot disagree.
The inline `auth` mapping is RETIRED for delivery: the AuthContext, the `authn` skill, and the L1 surface are placed through the **Data-dependency placement endpoint** instead.
_Avoid_: target definition

**Target image provisioning**:
How the chain obtains one target's image before it starts, by a strict store -> pull -> build precedence: an image already present under its **Canonical image tag** is a store hit and is left alone (never pulled, rebuilt, or reclaimed by provisioning); otherwise a declared pull reference is fetched and bound to the canonical tag; otherwise the target's own compose/Dockerfile builds it and the produced image is bound to the canonical tag - build is the last fallback, not the first.
A target with no store hit, no pull reference, and no built image fails that target hard, and the run moves on to the next target.
Each provisioning is recorded on the step (`store`/`pull`/`build`, where the store tier records as `present`) with the qualified reference actually pulled.
Reclaim happens only when the target is **Reclaimable**; `orchestrator/docker.py` owns the algorithm.
_Avoid_: prebuild, pre-pull, on-demand

**AuthContext**:
The externally bootstrapped authentication state seeded into the store (overview + accounts), plus the project `authn` skill capturing the sign-in/sign-up procedure.
It is placed by direct file write through the **Data-dependency placement endpoint**, so the agent container finds `auth/` and `skills/authn/` mounted at startup.
_Avoid_: auth, credentials, session

**Data-dependency placement endpoint**:
One of the four NON-IDEMPOTENT app-API write endpoints that place a target's pre-built eval artifacts by direct file write, plus the graph persistence of the L1 surface: `POST /projects/{id}/data-dependencies/{authn-skill,auth-overview,auth-credentials,l1}`.
Each is `multipart/form-data` with one required `file` part (raw bytes; `authn-skill` carries a single `.tar.gz`/`.zip` bundle, unpacked server-side with traversal rejected); `fileName` is optional and never builds a path.
Every call overwrites and creates the canonical file when absent.
The auth files land through the auth and skill stores, and the L1 `operator_kb.md` persists through the deterministic `analysis/scaffold.py` path into the graph.
_Avoid_: upload, seed, provision

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

**Chain state**:
The per-instance durable position of the serial target chain: `{instance_id, active_target, completed}`, persisted at `<instances-root>/<instance_id>/chain-state.yaml`.
`active_target` is the target the chain most recently advanced to; a resume uses it to tear the deployed target down first.
`completed` lists every target the chain has advanced.
The chain is terminal when `completed` covers every declared target.
At that transition `active_target` is cleared to null, so a re-run never tears down a target that is already done.
A partial chain keeps `active_target`, so a resume continues from the right target.
_Avoid_: chain position, chain pointer

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
When a target's upstream is down or restarting, the front answers `502 Bad Gateway` (the nginx default page); that is EXPECTED front behaviour, not a defect and not route-absence (an absent route answers `404`).
The front conf proxies every path to ONE published port, so when a challenge publishes several application services the front root may be served by a different service than the application backend (jetlinks' `ui` answers `/` while the `jetlinks` JVM boots).
A target restart can be self-inflicted: probing a destructive control route (e.g. ComfyUI-Manager's `/api/manager/reboot`, which `os.execv`s the ComfyUI process) closes the upstream for the restart window, during which every path answers `502`.
The hunting layer treats a front `5xx` as upstream-unavailable and stops probing rather than looping (`attack/hunting/hunting_status.py`, #323, `docs/design/hunting-target-front-availability-adr.md`).
_Avoid_: proxy, reverse proxy, gateway

**Work item**:
An eval-wide pre-eval data dependency (auth bootstrap, L1 surface, hunting artifacts) recorded at the `EvalSetup` level and gated before any target starts (D14).
_Avoid_: prerequisite, checklist

**Hunting cap**:
REMOVED (2026-10-05): a consumed-config count is not a failure signal, and hard-stopping a run mid-coverage caused the jetlinks-1 tier-0 cap-exhaustion (all 10 configs on tier-0 access-control hypotheses; the validation tier was never scheduled). A trial now settles on the run's own quiesce, the **Token budget**, or the **Trial deadline**.
_Avoid_: budget, limit

**Token budget**:
The per-`Target`-declared bound on a `Trial`'s token spend, enforced trial-wide: every phase poll reads the project's cumulative **generated-token** spend from the app usage surface (`generated_tokens` - reasoning + visible output), and when the spend over the trial's baseline reaches the budget the trial stops the active run and terminates `stopped`.
Counting generated tokens only (never input, cached or not) means context the model re-read never consumes the budget for new work.
_Avoid_: cap, limit

**Token spend**:
The generated tokens a `Trial`'s project produced, measured as the delta between the project's cumulative `generated_tokens` on the app usage surface (`GET /projects/{id}/usage`) and the trial's spend baseline.
_Avoid_: cost, usage

**Spend baseline**:
The project's cumulative `generated_tokens` at the trial's first spend poll; persisted in the trial record (`spend_baseline`) and carried across a resume, so a resumed or seeded trial never re-counts a prior run's spend.
_Avoid_: cap baseline, offset

**Trial deadline**:
The per-`Trial` wall-clock bound (`TrialConfig.budget_s`) on any one phase poll. When a poll reaches it the trial stops the active run - recon, analysis, or hunting - exactly as a **Token budget** stop does, then terminates the phase `timeout`. No run is left running for a surfer, because none runs by default.
The stop is the same `api.stop_run(project_id, run_kind, run_id)` call as the budget stop; only the trial terminal differs (`timeout`, not `stopped`), and the phase record's `stop_run_id` already names the run the stop verb expects.
_Avoid_: budget, phase cap

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
An `interrupted` execution (a provider-paused hunt, #331) is likewise deferred, never escalated - it is resumable, and its hunting-phase failure carries the recorded provider cause so the surfer can tell a transient throttle from consumed credits.
The dispatch is non-blocking (#316, D52): the tick launches the configured agent command detached (`BackgroundRunner`) and returns at once, so one tick can advance every other trial while a subagent runs.
The node's output file is the only completion signal; a detached subagent that never writes it is re-dispatched within the bounded count and budget and then escalated with a named failure.
Each launch redirects the subagent's output to a dispatch log beside the node's destination (`<destination>.dispatch.log`); the log is diagnostic, never an input to the tick decision.
_Avoid_: monitor loop, watcher, scheduler

**Dispatch log**:
The per-launch output sink `<destination>.dispatch.log` beside an assessment or diagnosis node's destination file, written by the detached `BackgroundRunner` so a background subagent outlives the tick that launched it.
_Avoid_: stdout, agent log

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
It also requires the **required capability override** on the agent service, and the preflight asserts that override is correct for the eval relay.
_Avoid_: prod compose, eval env

**Required capability override**:
The committed `LLM_CAPABILITY_OVERRIDES` value the eval deployment requires for its relay (`opencode-go/deepseek-v4.1-flash`), because models.dev wrongly claims that relay supports `json_schema` and a forced tool choice (ADR A6).
Its absence sends the compaction summariser and every schema-bound `invoke_role` to the `json_schema` rung, which 400s (the F12 signature: `summary_status=failed`, `reclaimed=0`).
The canonical value is in `.env.example`, single-quoted so one spelling is valid both when the production driver sources the instance `.env` as a shell script (`set -a; . .env; set +a`) and when compose reads it through `env_file` (quote pair stripped).
The preflight REPAIRS a missing value by appending the line verbatim (reported under `added`) and fails only when the value is present but wrong or malformed.
The **Eval compose overlay** requires it on the agent service, and `eval/env_preflight.py` asserts it (`REQUIRED_CAPABILITY_OVERRIDES`).
The app-layer term is **capability override** in `src/polymerhus/app/CONTEXT.md`.
_Avoid_: capability flag, model quirk

**Root cause type**:
The typed locus of a diagnosis: `implementation_defect`, `design_defect`, `missing_component`, `kb_coverage_gap`, or `skill_defect` (combinable).
_Avoid_: cause, blame
