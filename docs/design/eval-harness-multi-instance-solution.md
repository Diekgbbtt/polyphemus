# Eval Harness Multi-Instance Evolution - Solution Draft

*DRAFT. Pre-spec artifact: FR rewrite, extended system description, and the holistic impact map.
Design decisions are recorded progressively during the grill; a new spec is written only after the grill closes.
Status: draft, NOT implementation.*

---

## 1. Problem statement

The eval harness (agent-as-orchestrator-and-oracle over `tools/eval/`) evaluates one polymerhus stack against one target at a time.
It cannot run multiple configurations in parallel, has no typed configuration surface, loses artifacts when a container is recreated on the base stack, has no per-target pre-eval work-item gate, and grades synchronously so the next target waits on the previous trial's judgment.
Its runtime assumptions (one shared stack, one global KB, one shared kali, one global module control plane, one global target front) are the constraints that break first at scale.

## 2. Present functional requirements (as-built, kept)

- **P1 - Toolkit primitives**: `target.sh` (target lifecycle), `hosts.sh` (kali alias), `gt.py` (ground truth), `ph.py` (API client: project/settings/auth/bootstrap/recon/hunting/graph), `scaffold.py` (deterministic L1), `ev.py` (evidence bundle), `cwes.yaml` (type -> CWE), `hunting_ctl.py`.
- **P2 - Target lifecycle**: `targetctl` build/up/down on the remote host + nginx front by `server_name` + readiness poll.
- **P3 - Ground-truth isolation**: `gt.py` output never reaches the pipeline.
- **P4 - Deterministic L1 scaffold** primary, LLM bootstrap fallback (prose KBs).
- **P5 - Auth via the store**: seed `PUT /projects/{id}/auth`; the recon orchestrator's authn gateway validates/mints.
- **P6 - Per-target precomputed KBs** (`tools/eval/kbs/<target>/`).
- **P7 - Judgment protocol**: `identified`/`partial`/`missed` with the three conjuncts; `verdicts.yaml` + `trial.yaml`.
- **P8 - Integrity gates**: recon liveness (job rows), absence-vs-failure, degraded-trail grading.
- **P9 - pass@k**: fresh target instance + fresh project per attempt.
- **P10 - Evidence substrate**: L0/L1 graph, hunt store, pod artifacts, Langfuse.

## 3. New functional requirements (from the operator's overview)

- **N1 - Typed eval configuration**: one fine-grained, schema-versioned config aggregating all entities (instances, targets, phases, artifacts), so an eval setup is declared, not improvised.
- **N2 - Multi-instance parallelism**: N system instances evaluated concurrently; each instance executes its targets in a serial pipeline.
- **N3 - Instance identity**: an instance is identified by a uuid and defined by its `.env` (the crucial parameter); all other instance attributes derive from it.
- **N4 - Target descriptor**: per target, a linked configuration: externally bootstrapped auth context (external agent on the operator host, running the parameterised prompt from the `meta/authn-skill-writing` references; the sign-in/sign-up procedure captured as a project skill), and a bootstrapped L1 surface.
- **N5 - Operator pre-mined hunting artifacts**: optional, at a mounted filesystem location, present before the project run starts.
- **N6 - Phase-gated entry**: each target run starts at a declared phase (recon | analysis | hunting) and each phase entry is wrapped in a persisted-state dependency check.
- **N7 - Hunt-config consumption cap**: a per-target bound on consumed hunt configs (the current hunting is unbounded).
- **N8 - Concern movement to the symbolic layer**: configuration parsing, lifecycle, phase gating, and state checks move into the symbolic (code) layer; the orchestration agent keeps only supervision/monitoring plus small state-validation checks at crucial transitions; final assessment stays with the established scoring framework.
- **N9 - Target-system agnosticity**: target configs are self-contained; the orchestration adapts to the dataset; a containerised, pullable target is pull-and-play on the remote host.
- **N10 - Asynchronous assessment**: final assessment runs out of band (a background subagent), so the next target starts as soon as the previous target's execution finishes.
- **N11 - Artifact durability**: periodic migration of produced artifacts from `data/` to the host filesystem.
- **N12 - Eval-wide pre-eval work items**: auth context bootstrap, L1 bootstrap, and (optionally) hunting artifacts are recorded as work items at the `EvalSetup` level (they are target-agnostic) and must be completed before any official eval starts. (Amended 2026-09-28: not per-target attributes.)
- **N13 - Verdict evidence chain**: every verdict at `identified` or `partial` (i.e. anything above the bare minimum, signalling the solution space was researched in that direction) carries a reference to the filesystem location of the supporting hunting artifact chain: the parent hunt config, the child `TestImplementationSpec`, the child experiment logs, and the yielded `PodExport`. Extended 2026-09-28: the chain may also reference observability-platform reasoning - reasoning logs citing state assertions, decision nodes, and taken branches with rationale - mapped to the agent workflow phases.
- **N14 - Eval-cycle closure (diagnosis)**: for every NOT-successfully-discovered vulnerability (`missed` and `partial`), a **diagnoser** subagent root-causes the qualitative defect. It runs a dedicated adapted procedure authored under the eval harness (built on `debug-hypothesis`'s loop plus `diagnosing-bugs`' discipline); it interacts with the observability platform (mostly reasoning), the produced hunting artifacts, and the design-spec docs (primarily the agent-stack docs), and counter-checks any failure-relevant decision in the corresponding code area; it is exposed to the issues bank, records the closest matching issue, and may propose (never file) a new one. The defect may lie in code or in the **persisted data layer**: KB coverage gaps, skill procedural drift, or a missing procedure for a vulnerability variant (payload, vector, trust-assumption variant, or a winning bypass/proxy technique). It writes `diagnoses.yaml`, paired with `verdicts.yaml`, one entry per un-discovered vuln: `{vuln, failure_mode, root_cause: {type, extended_description, combination_of?}, diagnosis_overview, evidences[], closest_issue, proposed_issue?}`.
- **N15 - Evaluation-version pinning**: the eval environment runs a dedicated `eval` branch; each instance runs from its own worktree off it. Three planes with distinct owners: delivery (the GitHub Actions CD controller owns `origin/dev` -> the server's `dev` worktree), advancement (a systemd-unit sync daemon with a heartbeat owns `dev` -> `eval`, never fetches, never resets), execution (the orchestrator owns trials and the idle state). Advances are environment-wide, only when all instances are idle, with the window shortened to effective project execution; leaked workbench edits are stashed and popped. Trial records carry the `eval` SHA and the stack fingerprint. See `docs/design/eval-environment-version-pinning-adr.md`.
- **N18 - Stack alignment at version advance**: every advance computes a stack manifest (one SHA per alignment-relevant artifact plus the digests of running images) and a single compressed stack fingerprint. The orchestrator workflow step checks the recent `eval` SHAs, diffs the manifest, and performs or dispatches the alignment action per the impact map (none for source/skills/lightrag; restart kali; restart litellm; recreate affected services; config-layer alignment for env schema), failing closed on database-schema, data-layout, platform-dependency, and image-definition changes. The daemon performs the mechanical advance and enforces the fail-closed gate; the orchestrator decides and executes everything else.
- **N19 - Eval compose overlay and env-schema preflight**: a `docker-compose.eval.yml` overlay requires the per-instance `.env` (`required: true`) and fails loud on missing required interpolation; a preflight always fills missing keys from `.env.example` into the instance `.env` without clobbering operator values, and the keyset drift is reported in the manifest. Rollback records the last-known-good `eval` SHA, and only an operator may rewind.
- **N16 - Eval-close verification phase**: the orchestrator workflow verifies the presence of every trial's `verdicts.yaml`; missing artifacts are re-dispatched to the assessment subagent, and after two failures the orchestrator micro-diagnoses the cause and repairs **configuration only** (`.env`, eval artifacts). Codebase self-repair is out of scope; when no local misconfiguration interpretation exists and a new configuration decision is required, it fails closed.
- **N17 - State assertion and recovery loop**: a background surfer loop monitors the instances and prompts the orchestrator when the hunt-configs cap is reached or an instance is in a failed state (e.g. LLM credits exhausted). The orchestrator asserts the state and decides: fully terminate, destroy, or fix (configuration/data layer only) and restart.

## 4. Superseded (must not be perpetuated)

- **S1** `eval-harness-design.md` §5 setup-pipeline web API: superseded by a typed config + the target lifecycle strategy (N1/N9).
- **S2** `eval-harness-light-draft.md` §2 "no orchestration engine, no oracle code, no judge service": superseded by N8/N10 (symbolic layer + async judge).
- **S3** "one shared polymerhus stack, fresh `project_id` per trial" (`eval-harness-design.md` §1): superseded by N2/N3 (instance per configuration).
- **S4** one nginx front per workshop domain discriminating on `Host`: superseded by per-instance routing (round-1 decision).
- **S5** synchronous agent-as-oracle: superseded by N10.
- **S6** `eval-targets.yaml` as THE config surface: superseded by N1; it remains a legal target-config source, not the orchestration surface.

## 5. Extended system description

```
EvalSetup
  schema_version
  instances: [Instance]
  artifact_store: <host path for durability migration>

Instance                         # the isolation unit (round-1 decision)
  instance_id: uuid              # identity
  env_file: <path>               # THE crucial parameter
  systems: <compose project / host>
  targets: [TargetRun]           # serial pipeline

TargetRun
  target_id
  target_config: TargetConfig
  start_phase: recon|analysis|hunting
  hunt_config_budget: int | null
  preloaded_hunting_artifacts:
    configs: <host path> | null            # hunt configs -> hunt_configs/produced/
    test_specs: [{path: <host path>, fault_key: <fault key>}]  # -> test-specs/<fault_key>/produced/

TargetConfig
  lifecycle: TargetLifecycle     # strategy: targetctl | image | compose
  target_seed
  operator_kb: <path>
  auth: AuthContext              # externally bootstrapped
  l1_surface: BootstrapSpec      # bootstrapped L1 surface

AuthContext
  overview: <overview record>
  accounts: <account records>
  procedure_skill: <project skill path>   # sign-in/up captured as a skill
  source: external-agent         # meta/authn-skill-writing bootstrap-workflow.md

PhaseEntry (recon | analysis | hunting)
  dependency_predicate: <persisted-state check>
  on_missing: block | degrade
```

## 6. Holistic impact map (what does not hold anymore)

Verified against the code; each item is a place the current architecture breaks under N2.

**6.1 Stack state collisions (why "one shared stack" is superseded).**
- **Module control plane is global**: `POST /projects/{id}/modules/{module}/{pause|resume|drain}` ignores `project_id` and mutates the process-wide `RuntimeManager` - one project can drain recon/analysis/hunting for all.
- **Run control is unscoped by `run_id`**: recon/analysis/hunting stop+status and session verbs never compare the path project to the run's owner.
- **Neo4j `:Observation` is not project-partitioned** (constraint on `id` only; MERGE then `SET project_id`): two projects producing the same observation tuple share one node and last-writer-wins.
- **LightRAG is one global workspace** (single `rag_storage`, no workspace parameter); ingestion registry has no project discriminator (`source_key` global; duplicate submissions inherit the first's document id).
- **Kali is one shared exec surface**: project-aware capture store, but global `/etc/hosts` (snapshotted into leases at creation), global namespace pool (8) that `MAX_PODS=20` already exhausts, global Steel session catalogue + single API key, shared `/work` workdirs, and a single unauthenticated MCP port. Hunting pods all share the session id `hunt-pod`.
- **Agent-side scoping defaults to `config.PROJECT_ID`** (`default`) for auth/skills in several call sites; the recon orchestrator is the one exception that threads the run project.
- **Shared gates serialize**: analysis pass gate width 1; hunting dispatch gate width 20; one worker pool; one litellm gateway with per-container single-writer semantics.
- **`GET /runs` is unscoped** and leaks all projects' runs.

**6.2 Target front and routing.**
- One nginx conf file per workshop host (`/etc/nginx/conf.d/eval-target.conf`) and `target.sh` rewrites it wholesale: two concurrent attempts overwrite each other's front.
- Routing discriminates on the HTTP `Host` header (`server_name`); identical targets across instances yield the same Host.

**6.3 Artifact substrate.**
- Per-project data root `<repo>/data/<project_id>/{skills,auth,hunting/...}`; the only global artifact is `data/hunting/fault-kb.yaml`.
- The dev overlay already bind-mounts `./data`; the base compose does not (container-layer loss on recreate).
- The data-root bind is relative to the compose invocation directory: runs from a worktree write into the main checkout's `data/`.
- **`tools/eval/ev.py` and `hunting_ctl.py` are stale against the #234 root** (they read `src/polymerhus/attack/hunting/data/...`); post-#234 these are empty, so the collector records `present:false` and the cap count always reads 0.

**6.4 Hunting control.**
- No cap on config production or consumption exists anywhere; the only bounds are concurrency gates and per-agent step budgets.
- There is no import/seed API for hunting artifacts; the only seam is the implicit file-drop into `data/<pid>/hunting/orchestration/hunt_configs/produced/*.yaml` (ratified) and `<pid>/hunting/hunter/test-specs/<fault_key>/produced/*.yaml`, read lazily.

**6.5 Auth bootstrap.**
- The parameterised external-agent prompt exists (`skills/meta/authn-skill-writing/references/bootstrap-workflow.md`), and the store seed face is `PUT /projects/{id}/auth`; there is no catalogue `skills/authn/` - it is authored per project at `<data_root>/<project_id>/skills/authn/SKILL.md`.

## 7. Grey areas (the grill queue)

- G1 Isolation unit: full compose stack per instance, or shared data services + duplicated exec/agent?
- G2 Routing discriminator: Host alias, distinct port, or per-instance network?
- G3 Identical targets across instances: how to keep routing robust without complex wiring?
- G4 Instance `.env`: which variables must differ, and how is the file produced (template + per-instance overrides)?
- G5 Config format and ownership: one file per eval setup vs per-instance; who validates it.
- G6 Phase dependency predicates: exact persisted-state checks per phase.
- G7 Hunt-config cap: enforcement point (symbolic layer vs runtime) and semantics (stop vs refuse).
- G8 Pre-mined artifacts: format, mount path, and whether the cap equals the preloaded set.
- G9 Async assessment contract: subagent dispatch, result landing, and how the orchestrator knows it completed.
- G10 Durability migration: mechanism (mount + snapshot vs periodic copy), cadence, and the artifact-store layout.
- G11 Target agnosticity: the generic pull-and-play contract beyond `targetctl`.
- G12 Per-target pre-eval work-item gate: where recorded and enforced.
- G13 Which services, if any, may be shared across instances (postgres/neo4j/lightrag/agent/kali).
- **G14 Verdict evidence chain (N13)** - RESOLVED 2026-09-28: `evidence_chain: {hunt_config, spec_dir, experiment_logs[], pod_export}`, data-root-relative, required for `identified`/`partial`; extended with phase-mapped observability reasoning references (D17). Residual: the exact mapping from reasoning spans to phases.
- **G15 Diagnosis contract (N14)** - RESOLVED 2026-09-28: dedicated adapted procedure (D18); typed `diagnoses.yaml` (D19); failure-mode taxonomy (D21, pending confirmation of the arrow mapping); issue-bank reference-or-propose, never file (D22); root-cause space extended to the persisted data layer (D24).
- **G16 Version pinning (N15)** - RESOLVED 2026-09-28 into D25-D29/D32: stash-and-pop, the app-state proxy, the deploy unit with the agent diff turn, the `eval` branch shape (a) and the worktree layout (a). Remaining open items live in `docs/design/eval-environment-version-pinning-adr.md`: rollback, daemon health/heartbeat, proxy sufficiency for assessment/teardown windows, daemon supervision, per-SHA image tags.
- **G17 Self-repair versus version freeze (R11)** - RESOLVED 2026-09-28: D28, configuration-layer repairs only, fail closed otherwise.
- **G18 Layout reconciliation (R15)** - RESOLVED 2026-09-28: D29, one instance per worktree off the `eval` branch.

## 8. Per-target pre-eval work items (recorded, per operator remark)

Before an official eval run, each target carries:
1. **Auth context**: external operator-host agent runs `bootstrap-workflow.md`, seeds `PUT /projects/{id}/auth`, and writes the `authn` skill bundle.
2. **L1 surface**: a deterministic scaffold from the target KB (or the LLM bootstrap for prose KBs).
3. **Hunting artifacts** (optional): pre-mined configs/specs mounted before the run.

These are the N12 work items; the preflight gate refuses a target until its required items are present.
