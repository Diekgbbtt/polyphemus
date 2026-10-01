# Eval Multi-Instance: Decisions Record

*Living record of design decisions taken during the grill. Each decision is dated and numbered; risks are recorded as they surface and are carried into the future spec's risk section.*
*Status: rounds 1-3 recorded. Round 3 (config delta, lifecycle ownership, assessment contract, artifact store) still open.*

## Decisions

### D1 - Isolation unit: a full compose stack per `PolyphemusInstance`
*2026-09-25.* One `PolyphemusInstance` owns its own agent + kali + postgres + neo4j + lightrag. The verified collisions live in the shared data plane (neo4j `:Observation` not project-partitioned, one global LightRAG workspace, a project-less ingestion registry, a process-global module control plane, a single litellm writer), so duplicating only the exec plane would leave them unaddressed.

### D2 - Routing discriminator: a unique synthetic Host per `TargetRun`
*2026-09-25.* Each target run gets a unique synthetic Host (e.g. `t-<short>.target`), written into the workshop nginx `server_name` and aliased into that instance's kali `/etc/hosts`. Distinct published ports were rejected (they break the platform's bare-domain scope gate).

### D3 - Canonical terms
*2026-09-25.* `PolyphemusInstance` (one polymerhus deployment, identified by uuid and defined by its `.env`), `Trial` (fresh target instance + fresh project per attempt), `Target` (the evaluated application; WebExploitBench calls it a `challenge`). Glossary: `tools/eval/CONTEXT.md`. `System` stays reserved for the L1 node.

### D4 - Config topology
*2026-09-25.* One `EvalSetup` per evaluation. Each instance has an `InstanceConfiguration` that references a manually managed `.env` file.

### D5 - Symbolic/agent boundary
*2026-09-25.* Configuration, lifecycle, phase gating, state predicates, artifact migration, and verification live in the symbolic (code) layer. The orchestration agent keeps supervision: monitoring, the documented minimal remediations, small state-validation checks at phase transitions, and the bounded micro-diagnosis/self-repair of D15.

### D6 - Asynchronous assessment; no polling
*2026-09-25.* On execution completion the orchestrator dispatches a background subagent that writes `verdicts.yaml` into the trial directory. The orchestrator does not poll for it; the presence check is the workflow phase of D15.

### D7 - Durability: bind mount + active continuous sync
*2026-09-25.* The instance data root is host-backed by a docker bind mount plus an active continuous sync to a durable artifact store.

### D8 - Hunting cap: per `Target`, counted from the consumed directory
*2026-09-25.* The cap is a per-`Target` integer. It counts files present in the consumed hunt-configs directory; every file moved there counts, including mounted/pre-mined ones.
*2026-09-29 (operator-ratified amendment).* The cap is enforced **trial-scoped**: it counts only the configs consumed during the trial, against a baseline of the consumed names already present at the trial's first hunting poll. The baseline is persisted in the trial record (`cap_baseline`) and carried across a resume, so a config consumed by a previous run - or a mounted/pre-mined file already in `consumed/` - no longer satisfies a new trial's cap. A new trial id snapshots a fresh baseline; a resumed trial keeps its own and its count does not reset.

### D9 - Target agnosticity: strategy-typed lifecycle
*2026-09-25.* A strategy-typed lifecycle (`targetctl` for WebExploitBench, `image`/`compose` for pullable containers) behind one interface, selected by the target descriptor. Accepted provisionally; see **R2**.
*2026-10-01 (amended by D43).* The lifecycle interface gains an image-provisioning seam with a strict precedence (build > pull > present > fail-hard); the strategy still selects by the target descriptor, but how the image is obtained is decided by the target's build recipe and the dataset registry, not by the strategy alone.

### D10 - No machine resource limits; one instance at a time
*2026-09-28.* Co-located instances are **not** cgroup-capped. Normally only one instance runs, and the operator accepts the contention in the exceptional case. Host-published port offsets remain necessary (R3) so host-side tooling addresses the right instance.

### D11 - Per-instance layout: one directory per instance
*2026-09-28.* Each instance lives in its own directory (its own checkout + `.env` + `data/`), so relative compose bind mounts are naturally per-instance. Superseded in shape by D23/ADR (single `eval` checkout + per-instance worktrees) - kept as the intent: filesystem isolation per instance.

### D12 - Continuous sync: `lsyncd`, one-way, no phase flush
*2026-09-28.* A one-way `lsyncd` (inotify -> rsync) streams each instance's data root into the artifact store. No phase-completion flush. The artifact store is a sink, never an authority.

### D13 - Recon entry: the project-specific `authn` skill and the auth store are predicates
*2026-09-28.* The recon-entry predicate additionally requires the project-specific `authn` procedure skill and the `AuthContext` store seeded with **overview and credentials** (via `PUT /projects/{id}/auth`), when the target declares an auth surface. Amends Q13.

### D14 - Pre-eval dependencies are eval-wide, not per-target attributes
*2026-09-28.* Operator pre-eval data dependencies are target-agnostic; they are not specified as per-target attributes. Amends N12: work items live at the `EvalSetup` level, and the symbolic layer gates the whole eval on them.

### D15 - Eval-close verification phase
*2026-09-28.* The orchestrator workflow includes a phase that verifies the presence of every trial's `verdicts.yaml`. Missing verdicts are re-dispatched to the assessment subagent; after two failures the orchestrator runs a quick diagnosis and, if the cause is a technical defect, repairs it itself.

### D16 - Cap enforcement is symbolic and timer-side
*2026-09-28.* The symbolic layer counts files in the consumed directory and stops the hunting run via the existing stop verb at the cap, recording the overshoot margin (R7). No runtime knob is added.
*2026-09-29.* The count is the trial-scoped count (the present consumed names minus the trial's persisted baseline, D8); `stop_count`, `final_count`, and `overshoot` in the trial record are all trial-scoped. A resumed trial threads the record's baseline into the new trial, so its count continues rather than resetting.

### D17 - Evidence chain includes observability reasoning references
*2026-09-28.* Extends N13: beyond the artifact FS chain, each qualifying verdict may reference observability-platform reasoning details - reasoning logs citing state assertions, decision nodes, taken branches with rationale - mapped to the agent workflow phases.
*Status 2026-09-28 (adversarial review, I4):* the reasoning seam is **designed-not-built** (CODING_STANDARD section 12).
The evidence resolver accepts an injected read-only `ReasoningSource` and maps observations to phases, but no production source is wired, so reasoning references are optional and currently **unproduced**; no Langfuse capture is advertised. A trace id can still be supplied via `--trace-id`/`EVAL_TRACE_ID`; it is stamped into the trial record and substituted into the dispatches, and a real source can be wired later without a schema change.

### D18 - Diagnoser methodology
*2026-09-28.* A dedicated adapted procedure, authored under the eval harness and built on `debug-hypothesis`'s loop plus `diagnosing-bugs`' discipline, run by the diagnoser subagent. Neither installed skill alone fits; `/measuring-experiment` as named does not exist.

### D19 - `diagnoses.yaml` typed surface
*2026-09-28.* Renamed to `diagnoses.yaml`, paired with `verdicts.yaml`. Per un-`identified` vuln: `{vuln, failure_mode, root_cause: {type, extended_description, combination_of?: []}, diagnosis_overview, evidences: [], closest_issue: {repo, number, title, rationale} | null, proposed_issue?: {title, body, labels}}`.
*Amended 2026-09-28 (batch-3 review):* each entry also carries `eval_sha` and `stack_fingerprint`, validated against the trial record, so every produced record is version-attributable (#276 AC2).

### D20 - Diagnosis covers `missed` and `partial`
*2026-09-28.* "Successfully discovered" means `identified` only, so both `missed` and `partial` receive a diagnosis entry.

### D21 - Failure-mode taxonomy (pending confirmation)
*2026-09-28.* `pod_notsufficient_space_coverage` (absorbs the pod-side of `pod_inconclusive`/`never_explored`), `hunter_notsufficient_tests_exploration` (the hunter never generated the tests), `pod_diverged_trajectory` (started right, left the trajectory), plus the retained `surface_gap`, `spec_underspecified`, `cap_hit`. The arrow mapping from the operator's answer is interpreted here and flagged for confirmation. CONFIRMED in D33, which also adds `orchestrator_failed_unit-fault_binding` and records analysis-layer failure modes as a future extension.

### D22 - Issue bank: reference or propose, never file
*2026-09-28.* The diagnoser searches the origin issue bank, records `closest_issue` when one exists, and otherwise writes a `proposed_issue` block. It never files (work authority: `loop-constraints.md`).

### D23 - Evaluated-version pinning: the `eval` branch
*2026-09-28.* The eval environment runs a dedicated `eval` branch: the `dev` trunk and an `eval` branch in two worktrees, with a background daemon fast-forwarding `eval` to the diverging `dev` commit only when no eval is executing. Delivery happens on `dev`, out-of-band. Authoritative analysis and open issues: `docs/design/eval-environment-version-pinning-adr.md`.

### D24 - The root-cause space extends to the persisted data layer
*2026-09-28.* Extends N14: a defect may live in generated data, not only in code. Root causes include **KB coverage gaps** (the generated knowledge base does not exhaust the space), **skill procedural drift** (the agent could not keep the specified trajectory), and **missing procedures** for a specific vulnerability variant - payload, vector, trust-assumption variant, or a winning bypass/proxy technique. `root_cause.type` gains `kb_coverage_gap` and `skill_defect` beside `implementation_defect`, `design_defect`, `missing_component`.

### D25 - Dirty-tree handling: stash before fast-forward, pop after
*2026-09-28.* Git-tracked artifacts on the eval branch are never supposed to change (changes belong under the `eval/` directory). If edits nonetheless leak into the tracked base, the sync daemon stashes the workbench changes, fast-forwards, and pops them back. A pop conflict alerts; nothing is auto-resolved.

### D26 - Execution-state proxy: the app module API state
*2026-09-28.* Instead of a dedicated flag, the daemon reads the app module's API surface - an endpoint exposing the running project / run state - as the sufficiently accurate proxy for "an eval is executing". It is expected to be always reliably available; the fallback is a direct postgres query.

### D27 - Deploy unit: fast-forward is live; targeted restarts via an agent diff turn
*2026-09-28.* Verified in `docker-compose.dev.yml`: the agent mounts `./src:/srv/src` and runs `uvicorn --reload`, so a fast-forward takes effect without a rebuild; env/compose changes need a container recreate; `kali`/`gateway` reload via `docker restart`; a rebuild is needed only when `requirements*.txt`/`Dockerfile` change. A workflow agent turn inspects the diff for technology-stack changes requiring restarts, with the `.sql` script and data-layer layout as the narrow risk locus.

### D28 - Self-repair is configuration-layer only; fail closed otherwise
*2026-09-28.* Repairs of codebase components are explicitly NOT functional requirements. The orchestrator may repair configuration only (`.env`, eval artifacts). When no local misconfiguration interpretation exists and a new configuration decision is required, it fails closed.

### D29 - One instance per worktree on the eval branch
*2026-09-28.* Confirms the D11/D23 reconciliation: a single canonical `eval` checkout, with each instance running from its own `git worktree` off the `eval` branch (shared objects, per-instance working dir + `.env` + `data/`).

### D30 - The per-instance parameter diff includes LLM roles and provider API keys
*2026-09-28.* The diff must capture every eval parameter, so `LLM_<ROLE>` selections and all providers' API keys are per-instance diffable parameters, not assumed-shared constants.

### D31 - Lifecycle: cap and failed-state triggers, arbitrated by the surfer loop
*2026-09-28.* A stop is triggered when the hunt-configs cap is reached, or when either instance is in a failed state (e.g. LLM API credits fully consumed). The background surfer loop prompts the orchestrator, which asserts the state and decides whether the execution is fully terminated, destroyed, or fixed (configuration or data layer only) and restarted.

### D32 - Trial SHA stamping
*2026-09-28.* Every trial record and `verdicts.yaml` row carries the `eval` SHA the trial ran on.

### D33 - Failure-mode taxonomy confirmed; analysis-layer modes deferred
*2026-09-28.* Confirmed: `pod_notsufficient_space_coverage`, `hunter_notsufficient_tests_exploration`, `pod_diverged_trajectory`, `surface_gap`, `spec_underspecified`, `cap_hit`, plus the new `orchestrator_failed_unit-fault_binding` (the orchestrator failed to bind the unit/fault). More failure modes likely exist in the analysis layer but cannot be cited without sufficient eval experience; recorded as a **future extension** once data exists.

### D34 - Separation of concerns: delivery, advancement, execution
*2026-09-28.* Three planes with distinct owners. **Delivery** (GitHub Actions CD controller) owns `origin/dev` -> the eval server's `dev` worktree; fetching/forwarding `dev` is explicitly NOT the daemon's job. **Advancement** (the server sync daemon, a systemd unit with a heartbeat file) owns `dev` -> `eval` worktrees: ancestry check, stash/pop, fast-forward, gate, fingerprint, alignment dispatch; it never fetches and never resets or rewinds. **Execution** (eval orchestrator + surfer loop) owns trials, lifecycle, state assertion, config-layer repairs, assessment and diagnosis; its app-state API is the idle proxy.

### D35 - Idle window shortened to effective project execution; the gate filters stack-config jumps
*2026-09-28.* The window may stay open during assessment and diagnosis, since eval-specific artifacts are gitignored and unaffected by a code version jump. The gate filters any jump that deterministically touches eval-specific non-gitignored artifacts or the underlying component-stack configuration (database schema, data layout, platform dependencies).

### D36 - Environment-wide advances, only when all instances idle
*2026-09-28.* An advance moves all instance worktrees together, and only when every instance is idle; there is no per-instance skew.

### D37 - Stack manifest, fingerprint, and alignment map
*2026-09-28.* Each advance computes a stack manifest (one SHA per alignment-relevant artifact plus the digests of running images) and a single compressed stack fingerprint. The orchestrator workflow step checks the recent `eval` SHAs, diffs the manifest, and performs or dispatches the alignment action per impacted component: none for `src/**`/`skills/**`/`lightrag/**`; `docker restart kali` for `kali/**`; `docker restart litellm` for `gateway/**`; recreate affected services for `docker-compose*.yml`; config-layer alignment for `.env.example`; **fail closed** for `db/**`/data-layout, `requirements*`/`pyproject`/locks, and `Dockerfile*`/`kali/Dockerfile` unless an explicit migration or rebuild decision is taken. Fail-closed is the default under uncertainty. Trials record the SHA and the fingerprint.

### D38 - Rollback: last-known-good recorded, operator-only rewind
*2026-09-28.* Before each advance the daemon records the last-known-good `eval` SHA. Only an operator may rewind; the daemon never rewinds on its own.

### D39 - Stack manifest includes running image digests
*2026-09-28.* The manifest captured per advance and per trial contains one SHA per alignment-relevant artifact plus the digests of the images actually running (postgres, neo4j, lightrag, kali, litellm, agent).

### D40 - Kali alignment classification, verified
*2026-09-28.* Checked in the codebase: the start-time bootstrap is `kali/entrypoint.sh` + `kali/postrun.sh`, both bind-mounted (`docker restart kali`); the baked utility installation is `Dockerfile.kali` at the repo root (image definition, fail-closed). Nothing installs utilities outside these two.

### D42 - The orchestrator asserts SHA differences and decides alignment
*2026-09-28.* The daemon's job is mechanical: compare HEADs, fast-forward inside the idle window, emit the manifest/fingerprint diff. The **eval orchestrator asserts any SHA difference and decides the alignment action itself** - the impact map is guidance, never a hardcoded decision set. There is no hardcoded fail-closed branch: a jump the orchestrator judges not alignable without an operator decision is escalated and held.

### D43 - Restructure: the eval system moves to `eval/` at the repo root
*2026-09-28.* `tools/eval/` moves up one layer to `eval/`, with all helper scripts cohesively placed: kept for source (`ph.py` the API client, `scaffold.py` the L1 scaffold, `gt.py`+`cwes.yaml` the ground truth, `target.sh`/`hosts.sh` as the target and routing strategies), rewritten against the #234 data root (`ev.py`, `hunting_ctl.py`), folded into the new operator guide (`PLAYBOOK.md`, `OPERATOR.md`, `kb-authoring.md`), and obsolete run artifacts dropped. The sealed vulnerability research corpus stays out of the harness (eval-integrity boundary).

### D41 - Eval compose overlay and env-schema preflight
*2026-09-28.* The locally sourced `.env` is a drift risk against the compose interpolation schema (`${VAR:-...}` plus `env_file: .env, required: false`). Solution: a new `docker-compose.eval.yml` overlay that requires the per-instance `.env` (`required: true`) and fails loud on missing required interpolation (`${VAR:?...}`), paired with a preflight that always fills missing keys from `.env.example` into the instance `.env` without clobbering operator values, plus a keyset drift check in the manifest. New risk R17.

## Risks

### R1 - Vertical scaling contention on the single host
Resource limits are deliberately omitted (D10) and a single instance is the normal case. The residual risk is the rare two-instance overlap on 8 vCPU / 15 GiB plus the global caps (`KALI_HTTP_NAMESPACE_POOL=8`, `ANALYSIS_PASS_GATE_WIDTH=1`, `MAX_PODS=20`).

### R2 - Target agnosticity is asserted, not proven
D9 still assumes a containerised, pullable, HTTP target with WebExploitBench-like lifecycle mechanics. **To be carried explicitly as a risk in the future spec** (operator instruction).

### R3 - Port collisions across co-located instances
Every published port collides once two instances run on one host. Needs a per-instance port-offset scheme expressed in the `.env`.

### R4 - Continuous sync failure modes
One-way sync (D12) removes conflict classes; residual risks are lag, backlog growth, and the artifact store silently diverging from the live tree. Needs a health surface.

### R5 - Silent assessment failure without polling
D15's presence phase (check, re-dispatch twice, then self-repair) is the mitigation; a dead subagent is caught at eval-close rather than immediately.

### R6 - Unscoped API endpoints within an instance
Module pause/resume/drain, run stop/status, session verbs, `GET /runs`, LightRAG and ingestion are unscoped. Per-instance stacks mitigate cross-instance leakage; the endpoints stay unsafe for multiple projects in one instance.

### R7 - Cap enforcement race
The symbolic layer stopping hunting at the cap races the runtime moving files into `consumed/`; the effective cap can overshoot by the in-flight margin, recorded.

### R8 - Stale eval tooling paths
`tools/eval/ev.py` and `tools/eval/hunting_ctl.py` still read pre-#234 hunt paths, so the evidence bundle reports `present:false` and cap counts read 0. Must be fixed before the cap (D8/D16) is meaningful.

### R9 - Sync daemon races the eval start
"Fast-forward when no eval is executing" is a check-then-act against a state variable; without an atomic lock (and stale-lock recovery) the daemon can advance the tree between the eval's precondition check and its first use.

### R10 - Version jumps carry data and schema migrations
A fast-forward can change `init.sql`, the data root layout (#234), or serialised artifact shapes. An idle window does not migrate persisted state; an un-migrated jump can corrupt a live instance.

### R11 - Self-repair (D15) against the version freeze (D23)
If the orchestrator "addresses the problem by itself" by editing code, it changes the evaluated version mid-eval, precisely what D23 exists to prevent. Self-repair must be bounded to process-level actions or go through the dev pipeline and wait for a sync.

### R12 - Git fast-forward is not a deployment
The agent image does not mount `src/`, so a fast-forward alone changes nothing until the image is rebuilt and containers recreated; `latest` tags and shared build caches are unaccounted variables.

### R13 - Fast-forward preconditions
`eval` must never carry its own commits, both worktrees must stay clean, and `origin/dev` must be an ancestor. Any violation yields a non-fast-forward that must alert, never reset.

### R14 - Silent drift
A daemon that fails to fetch or advance, or a stale execution-state variable that freezes sync forever, is invisible without an alerting surface and a staleness TTL.

### R15 - D11 vs D23 layout conflict
Per-instance clones (D11) multiplied by the `eval` branch (D23) means N checkouts to fast-forward and possible version skew between instances; the layout needs one canonical checkout with per-instance worktrees (round-3 question).

## Round-3 resolutions

| Risk | Resolution |
| --- | --- |
| R9 sync race | D26: the app-state proxy replaces the dedicated variable; the residual race is the lag between state and first use, plus the stash/pop window (D25). |
| R10 migrations | D27: an agent diff turn decides restart/migration needs; `.sql` and the data-layer layout are the recorded risk locus; an idle window still does not migrate by itself. |
| R11 self-repair vs freeze | D28: configuration-layer repairs only; fail closed when a new configuration decision is required. |
| R12 ff is not a deployment | Corrected and resolved for dev: D27 (src is bind-mounted with `--reload`); a rebuild is needed only on dependency/Dockerfile change. |
| R13 ff preconditions | D25: stash/pop handles dirty trees; the ancestry check stays and a non-fast-forward alerts, never resets. |
| R14 silent drift | Amended: the app-state proxy makes execution state observable; daemon health, heartbeat, and alerting remain open (ADR open items). |
| R15 layout conflict | Resolved: D29, one instance per worktree on the `eval` branch. |

## Round-4 resolutions and one open item

- R9/R13 fetch races: removed entirely by D34 - the daemon never talks to origin; the CD controller owns the `dev` worktree.
- R10 migrations: D35/D37 - the gate fails closed on schema and data-layout jumps; the orchestrator's alignment step performs the mapped restarts.
- R12 deployment: D37's alignment map makes the minimal restart set explicit, and platform/image-definition changes fail closed.
- R14 silent drift: D34's heartbeat file plus the manifest diff give the health surface; the alert threshold stays open.
- **Open: rollback policy** (Q33 not answered) - last-known-good recording plus operator-only rewind is the proposed shape.
- New **R16 - manifest completeness**: a missed alignment artifact means a silently stale component; the manifest path set must be one reviewed constant, extended when components appear.

## Round-5 resolutions (grill closed)

- Q38 rollback -> D38: last-known-good recorded; operator-only rewind.
- Q39 manifest shape -> D39: compressed fingerprint + per-artifact manifest + running image digests.
- Q40 map completeness -> D40 (kali classification verified in the codebase) and D41 (env-schema drift; eval compose overlay).
- Q41 alignment handoff -> confirmed: daemon does the mechanical advance and enforces the fail-closed gate; the orchestrator decides and executes everything else.
- New **R17 - env-schema drift**: a locally sourced `.env` can fall behind the compose interpolation schema; mitigated by D41 (overlay + preflight + keyset check); renames are reported, not auto-removed.
- Grill closed 2026-09-28. Carried into the spec: R2 (target agnosticity), R16, R17, the ADR's still-open items (alert threshold, manifest review discipline, env-rename reporting, PR-contract note), and D33's analysis-layer failure-mode extension.

## Round-6 decisions (multi-target chain and image provisioning, 2026-10-01)

### D42 - The orchestrator is the control plane; the chain advances through `next_target`
*2026-10-01.* The eval orchestrator agent governs the run end to end through exactly two tools. `next_target` advances the target chain one target at a time: it tears the active target down, reclaims its image, provisions the next target's image, brings it up, and verifies its health. `eval_monitor` remains the post-execution workflow tick (D6/D15). The symbolic layer still runs the phases and owns state; the agent never runs a phase and never polls the API (D5). One instance runs its targets serially; the chain position is persisted (`ChainState`) so a later tick resumes at the right target. A failed `next_target` surfaces its full trace (step log, command error, traceback) and the run moves on to the next target, so one unprovisionable target never aborts the chain.

### D43 - Target image provisioning precedence: build > pull > present > fail-hard
*2026-10-01.* Amends D9. Before a target starts, its image is provisioned by a strict precedence:
1. **build** - a Dockerfile declared on the target config (`dockerfile`, with `dockerfile_context` for the build context) builds the app image, overwriting any pull; the Dockerfile's `FROM` supplies its base.
2. **pull** - otherwise a configured dataset registry (`TargetDataset.registry`) pulls each image (qualified by the registry, verified present).
3. **present** - otherwise the image must already be present locally; a missing image is a hard failure for that target, and the chain moves on (D42).
Build and pull are confirmed with `docker image inspect`; present is confirmed by tag only, so it is the weakest tier.
**Critical reliability evaluation.** (a) *Build context*: a bare Dockerfile path is insufficient - a Dockerfile that `COPY`s sibling files needs the real context, so `dockerfile_context` is a first-class field; defaulting to the Dockerfile's parent is a documented footgun. (b) *Tag vs content identity*: build and pull can both yield an image under the same tag with different content (base digest, source revision), so the provisioning path and the resolved image id are recorded on the step; comparability across paths is not assumed. (c) *Pull drift*: a tag can be repointed, so a tag-pull is not drift-free; digest pinning is the intended hardening (carried as an open item). (d) *Present is unverified*: it confirms a tag exists, not that it is the expected image - acceptable only as an explicit operator opt-in, recorded as the weakest tier. (e) *Multi-image targets*: one `dockerfile` builds one image, so a target needing several built images (e.g. jetlinks' app + attacker-stage) can express only the primary build; the rest fall to pull/present. A per-image build map is the future extension. (f) *Security*: building an untrusted Dockerfile runs its build steps as root; acceptable on the isolated eval host, noted here.

### D44 - `TargetDataset` owns the shared location addressing
*2026-10-01.* The registry host + URL path, the remote repo, and the ground-truth root are one fact per dataset, not per target. A `TargetDataset` (`name`, `repo`, `registry`, `ground_truth`) parents the targets and their ground truth; `EvalSetup` references it, and `TargetRun` carries each target's image identifier **as-is**. The pull reference is `dataset.registry` joined to the identifier; an empty registry means the dataset publishes no images, so targets are built (D43). This keeps a shared fact in one place and out of the external `challenge.json`, which is WebExploitBench's artifact, not polymerhus's domain.

### Rejected: the environment-affordance check
*2026-10-01.* An environment-affordance gate (disk/docker/registry probing that chose prebuild-all vs on-demand before any pull) was implemented and then removed. It existed only in uncommitted code, so no prior decision is amended; the durable decisions are D42/D43. The operator's ruling: the chain defaults to reclaim-then-provision per target, and the image precedence (D43) is the gate - not a separate affordance probe.
