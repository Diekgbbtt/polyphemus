# ADR: eval-environment version pinning - the `eval` branch, the advance daemon, and the stack fingerprint

*Status: RATIFIED through round 5 (2026-09-28); grill complete. Match check: no existing ADR covers the eval environment's version lifecycle; this is a new record. Extends the branch-topology contract in `docs/agents/issue-tracker.md` with an eval-specific rule.*

## Context

The continuous delivery pipeline must never change the version of the system under evaluation while an effective project execution is running.
Delivery already happens out-of-band (fast-forward `dev`, push). What was missing is the separation between who delivers to the server, who advances the evaluated version, and who runs the eval cycle, plus a reliable way to know what a version jump must align.

## Decision

### 1. Three planes, three owners

| Plane | Owner | Owns |
| --- | --- | --- |
| Delivery | GitHub Actions CD controller | `origin/dev` -> the eval server's `dev` worktree. Fetching/forwarding `dev` is explicitly NOT the daemon's job. |
| Advancement | server sync daemon (systemd unit + heartbeat file) | `dev` -> `eval` worktrees: ancestry check, stash/pop, fast-forward, gate, manifest/fingerprint, alignment dispatch. Never fetches, never resets or rewinds. |
| Execution | eval orchestrator + surfer loop | Trials, lifecycle, state assertion, configuration-layer repairs (D28), assessment and diagnosis. Its app-state API is the idle proxy. |

### 2. Branches and layout

`dev` is the trunk where delivery lands; `eval` is a read-only mirror, never committed to. Each instance runs from its own `git worktree` off `eval` (shared objects, per-instance working directory + `.env` + `data/`). The worktree and its `data/` evidence root are created if absent and are NEVER removed by the eval lifecycle (section 7b).

### 3. Idle window

Advances are environment-wide and happen only when **all instances are idle**. Idle means no effective project execution; the window may remain open during assessment and diagnosis, because eval-specific artifacts are gitignored and unaffected by a code version jump. The gate filters any jump that deterministically touches eval-specific non-gitignored artifacts, or the underlying component-stack configuration (database schema, data layout, platform dependencies).

### 4. Stack fingerprint and alignment

Every advance computes a **stack manifest**: one SHA per alignment-relevant artifact, plus the digests of the images actually running (postgres, neo4j, lightrag, kali, litellm, agent), and a single compressed **stack fingerprint** over the manifest. The orchestrator workflow step checks the recent `eval` SHAs, diffs the manifest, and performs or dispatches the **alignment action** per impacted component:

| Artifact changed | Impacted component | Alignment action |
| --- | --- | --- |
| `src/**`, `skills/**`, `lightrag/**` | agent code/knowledge | none (bind mount + `uvicorn --reload`) |
| `kali/**` (`entrypoint.sh`, `postrun.sh`, `mcp_server.py`, `http_history/**`) | exec plane | `docker restart kali` |
| `gateway/**` | litellm | `docker restart litellm` (never hot-reloads) |
| `docker-compose*.yml` | topology/env | recreate the affected services |
| `.env.example` | config schema | config-layer alignment (allowed repair, D28), plus the eval overlay (section 8) |
| `db/**`, data-root layout code | database schema / data layout | alignment only if a migration is declared and can be run; otherwise operator decision |
| `requirements*.txt`, `pyproject.toml`, dependency locks | python platform | rebuild + recreate if possible; otherwise operator decision |
| `Dockerfile*`, `kali/Dockerfile`, `Dockerfile.kali` | image definitions | rebuild + recreate if possible; otherwise operator decision |

A rebuild of the agent image should be very rare under the dev overlay. The alignment handoff is: the daemon performs the mechanical advance and emits the manifest diff; the **orchestrator asserts any SHA difference and decides the alignment action itself** - the map above is guidance, not a hardcoded rule. There is no hardcoded fail-closed branch: when the orchestrator judges the jump not alignable without a decision that only the operator can make, it escalates to the operator and holds.

### 5. Records

Each advance records the last-known-good `eval` SHA before moving (D38), and each trial records the `eval` SHA and the stack fingerprint it ran on, so verdicts and diagnoses are attributable to a version, not only to a branch.

### 6. Rollback

Only an operator may rewind. The daemon records the last-known-good SHA and never rewinds on its own.

### 7. Self-repair bound

Repairs are configuration-layer only (`.env`, eval artifacts). Code repairs are not in scope; when no local misconfiguration interpretation exists and a new configuration decision is required, the orchestrator fails closed.

### 7b. Worktree lifecycle - never removed by the eval loop

An instance worktree (`<instances_root>/<instance_id>`) holds the instance's `.env` and its **data root** (`data/`: hunt store, project/pod memory, L0+L1 graph, auth, skills) - the live per-trial evidence. Its lifetime must therefore outlive the stack lifecycle:

- `up` CREATES the worktree idempotently when absent and brings up the stack from it; a re-run with the worktree present reuses it (the `.env` preflight and `docker compose up -d` are idempotent).
- `down`, a recon/analysis/hunting stop or drain, and an eval termination NEVER remove the worktree or its data root. `down` stops the project's containers and volumes and stops there.
- Removing a worktree is an operator-only action (`orchestrator worktree-remove`), deliberately outside the loop, used to re-provision an instance from scratch.

Rationale: the data root inside the worktree is the live evidence; a teardown that removed the worktree destroyed it (hunting artifacts, memories, graph, auth, skills), and the durable artifact store only preserves what was explicitly materialized. The never-remove rule makes evidence loss structurally impossible.

### 8. Eval compose overlay

The `.env` is locally sourced and can drift from the compose interpolation schema (`${VAR:-...}` plus `env_file: .env, required: false`). A new `docker-compose.eval.yml` overlay requires the per-instance `.env` (`required: true`) and fails loud on missing required interpolation (`${VAR:?...}`); it is paired with a preflight that always fills missing keys from `.env.example` into the instance `.env` without clobbering operator values, and the manifest carries a keyset drift check.

## Consequences

### The good

- Version changes during effective execution are structurally impossible; the idle window is short because source is live via the dev overlay.
- The delivery/advancement/execution split removes fetch races entirely: the daemon never talks to origin.
- The stack fingerprint turns "did the stack change" into one recorded value and "what must restart" into a deterministic diff.
- The eval overlay turns env drift from a silent default into a loud startup failure.

### Still open

1. **Daemon health surface.** systemd + heartbeat file are ruled; the alerting threshold ("`dev` ahead while idle for > N minutes") and the notification channel are not specified.
2. **Manifest completeness.** The alignment map is the current best enumeration; the manifest path set must be one reviewed constant, extended when components appear (R16).
3. **Env rename reporting.** The preflight fills missing keys and reports the drift; a renamed key leaves the old one lingering, which is reported but not auto-removed.
4. **Delivery interaction with the PR contract.** `dev` can be ahead of `main` with no PR yet; a verdict may then belong to a commit that never shipped. Acceptable for eval, recorded here.

### Deferred

- Additional failure modes local to the analysis layer, recorded once the eval corpus is large enough to cite them.
