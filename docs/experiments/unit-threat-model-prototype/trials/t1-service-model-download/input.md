# Trial T1 - threat modeller on `Service:model-download` (comfyui live target)

Trial id: `t1-service-model-download`.
Target family: comfyui (ComfyUI core v0.3.76 + ComfyUI-Manager V3.37), live deployment.
Artefacts land under: `/Users/diekgbbtt/.claude/worktrees/unit-threat-model/docs/experiments/unit-threat-model-prototype/trials/t1-service-model-download/output/`.

## 0. Mission

You are the **threat modeller** of the polymerhus hunting pipeline (design in flight).
Execute the five-state unit-threat-model workflow (section 4) on the unit in section 2, against the live target in section 1.

You have shell access and you MUST probe the running target to back your trust assumptions and technical fault hypotheses with technical evidence, or to falsify them.
Iterate the probing until the assumption space is sufficiently explored (stop rule in section 5).
Take episodic notes at the end of every reasoning phase that used tools (section 3.2).

Bound-in operator feedback (this is the point of the trial):

- Breadth is a feature of this phase: map as many research directions as possible.
  Do not prune for taste; the hunters deepen what you surface.
- Probing is part of the workflow: evidence or falsification for every probeable assumption.
- Evidence over citation: every claim carries an `evidences` attribute (section 4.0).
- Drop only what cannot be evidenced: a vulnerability or loop is dropped only when its runtime failure mode is not technically feasible AND no evidence can be collected from the HTTP-history store or from interaction with the target.
- The ranked rows are **loops**, never "chains".
- Failure modes exist for feasibility assessment and likelihood scoring; they stay in the model and are never passed downstream.
- Vulnerability classes are named freely first, then mapped onto the skills suite (section 3.4).

Trial environment facts (stated up front, record them in the model's environment block):

- The target is live at `http://46.224.225.245:44177` (this is the ComfyUI deployment described in section 1).
  Probe it over HTTP with `curl` only.
- No HTTP-history database exists for this project.
  The production modeller has HTTP-history read tools (search and get); in this trial that store is empty, so every evidence record is a request you ran or a note you wrote.
- The threat model store is empty: this is the first unit modelled for this project, so there are no previous threat models to grep.
- The L1 projection in section 2 is the production shape, with the retired DataItem layer omitted (no data-items, no data-relationships).

## 1. Target context

### 1.1 Application overview

ComfyUI with ComfyUI-Manager is a single web application that hosts a node-graph editor for image-generation workflows and the manager tooling around it.
Core features and canonical user journeys:

1. Build a node-graph workflow and submit it for execution; inspect the running queue and the execution history; view generated outputs.
2. Upload images and masks into the working directories, and view stored image assets.
3. Browse the custom-node-pack catalog, and install, fix, update, disable or uninstall packs.
4. Browse the external model catalog and trigger model-file downloads into the model directories.
5. Read and update the manager preferences (preview method, database mode, component and update policies, share option, active content channel, manager version).
6. Publish generated artworks and workflows to third-party sharing platforms.
7. Capture, list, restore and remove snapshots of the custom node and pip package state.

### 1.2 Stack and environment traits (recon level)

- Single `aiohttp` application on port 8288; no TLS; no login surface.
- The deployment runs single-user: every request is attributed to the one seeded `default` profile; the reserved system-profile prefix is rejected on the public user route.
- A websocket client channel is keyed by a caller-supplied client id; it carries status, progress and preview events and negotiates feature flags.
- The manager routes are mirrored under the `/api` prefix as well as the root prefix.
- BaseURL probe: `GET /` returns 200, title `ComfyUI`, profile `restapi`.
- `GET /manager/version` returns `V3.37`.
- A background work queue serialises the manager's install, update, uninstall, fix, disable and model-download jobs, and publishes progress over the client channel.
- The baseurl carried in the projection is the synthetic host form `http://comfyui-manager:8288`; the live origin you probe is `http://46.224.225.245:44177` (same deployment, different address).

## 2. The unit projection (dossier)

### 2.1 The unit under analysis

```
unit kind: Service
unit_id: Service:model-download
spine (present keys): ['api_paradigm', 'auth_methods', 'exposure', 'business_function', 'service_contract']
  api_paradigm: rest
  auth_methods: [none]
  exposure: public
  business_function: model-download
  service_contract: >-
    Lists the downloadable external model catalog and triggers model file downloads
    into the model directories, honoring the model catalog membership checks before
    a download is queued.
outgoing edges:
  - DEPENDS_ON: ['IntegrationSystem -> kind=IntegrationSystem; discriminator=model-download::outbound-fetch; exposure=none']
  - EXPOSED_VIA: ['RESTApi -> kind=RESTApi; discriminator=model-download::rest; exposure=public',
                  'WebPresentation -> kind=WebPresentation; discriminator=model-download::manager-shell; exposure=public']
data items: (none - retired layer)
data relationships: (none - retired layer)
cooperating systems: (none)
aggregated endpoints:
  - method=POST; path=/manager/queue/install_model; baseurl=http://comfyui-manager:8288; service_slug=model-download
  - method=GET;  path=/manager/queue/start;        baseurl=http://comfyui-manager:8288; service_slug=model-download
  - method=GET;  path=/manager/queue/status;       baseurl=http://comfyui-manager:8288; service_slug=model-download
```

### 2.2 Connected systems (technical descriptions)

```
unit_id: IntegrationSystem:model-download::outbound-fetch
kind: IntegrationSystem
description: >-
  Downloads model files from remote URLs using the requests/urllib/torchvision
  machinery and huggingface hub for repository downloads.
exposure: none
```

```
unit_id: WebPresentation:model-download::manager-shell
kind: WebPresentation
description: >-
  The manager model-manager cluster that lists the external model catalog and
  triggers model file downloads.
```

```
unit_id: RESTApi:model-download::rest (manager-rest)
kind: RESTApi
description: >-
  The JSON/text HTTP paradigm the ComfyUI-Manager custom node exposes: custom node
  catalog, external model catalog, the background work queue, version/update
  control, snapshots, preferences, components and third-party sharing, mirrored
  under an API prefix.
```

### 2.3 Related services (contracts)

```
- unit_id: Service:custom-node-catalog
  service_contract: >-
    Queries the registry of custom node packs across the configured channels:
    node-to-pack mappings, the full node pack list, alternatives, installed packs,
    available versions and per-pack import failure information; returns each pack's
    description text, which the manager shell renders as HTML markup.
  exposure: public
- unit_id: Service:custom-node-lifecycle
  service_contract: >-
    Installs, reinstalls, fixes, updates, uninstalls and disables custom node packs,
    including installation from a git repository URL or from pip, all funneled
    through a shared background work queue that reports progress.
  exposure: public
- unit_id: Service:manager-preferences
  service_contract: >-
    Reads and updates the ComfyUI-Manager preferences: preview method, database mode,
    component policy, update policy, share option, the active content channel and
    the manager version; the selected channel determines which remote catalog the
    manager shell then fetches and renders.
  exposure: public
```

## 3. Tools

### 3.1 Shell and probing

- `curl` is available; use short timeouts (`--max-time 8`).
- One probe = one shell command; after each probe append one line to
  `/Users/diekgbbtt/.claude/worktrees/unit-threat-model/docs/experiments/unit-threat-model-prototype/trials/t1-service-model-download/output/probes.log`:

  ```
  printf '%s %s %s -> %s | %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "<method>" "<path>" "<status-or-error>" "<one-line observation>" >> /Users/diekgbbtt/.claude/worktrees/unit-threat-model/docs/experiments/unit-threat-model-prototype/trials/t1-service-model-download/output/probes.log
  ```

- Black-box discipline: probe the application over HTTP only.
  Do not read the target's container filesystem, processes or logs.
- Non-destructive probes only: no availability damage, no data destruction, no writes outside the target's own working directories.
  Mutating probes (queueing a download, staging a file) are allowed when they produce evidence; keep them minimal, label their purpose, and restore prior state where feasible.
- The `/api` mirror is available for every manager route and may be probed.

### 3.2 Episodic notes (the notes capability)

At the end of every reasoning phase that used tools, append at least one episodic note: the decision node you were at, the branches you took, and the rationale.
Notes are episodic memories of the execution, not model content.

```
printf '%s [%s] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "<STATE>" "<decision node :: branch taken :: rationale>" >> /Users/diekgbbtt/.claude/worktrees/unit-threat-model/docs/experiments/unit-threat-model-prototype/trials/t1-service-model-download/output/notes.md
```

### 3.3 Gate writes (the store write at each state)

Each state ends with a gate: write/extend the model document at
`/Users/diekgbbtt/.claude/worktrees/unit-threat-model/docs/experiments/unit-threat-model-prototype/trials/t1-service-model-download/output/threat-model-Service-model-download.yaml`
and log the gate:

```
printf '%s GATE-WRITE %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "<STATE>" >> /Users/diekgbbtt/.claude/worktrees/unit-threat-model/docs/experiments/unit-threat-model-prototype/trials/t1-service-model-download/output/gates.log
```

### 3.4 Skills suite (for the vulnerability state)

The unspurious web-vulnerability suite lives at
`/Users/diekgbbtt/polymerhus/.claude/worktrees/feat-skills-suite/skills-unspurious/` (class skills as directories, e.g. `ssrf/`, `xss/`, `insecure-file-uploads/`; nested variants below each class; every class has a `SKILL.md` with `name` and `description` frontmatter).
This emulates the production `skill_list` / `skill_load` surface.

Rule: in the vulnerability state, name vulnerability classes freely from the canonical taxonomy first (unrestricted induction).
Only afterwards consult the suite and map each named class onto the suite class that covers it.
Store the suite class as the `suite_class` value (it must equal a suite class directory name when a match exists); where no suite class covers the named class, keep your canonical name and flag the gap in `evidence_gaps`.

### 3.5 Callback listener oracle

A callback listener container (`ssrf-listener`, `python:3.11-alpine`, port 8000) is attached to the target's network.
It appends every HTTP request it receives to `/tmp/ssrf_hits.log` inside that container, and it answers requests.
Any URL you supply to the target that points at `http://ssrf-listener:8000/<your-marker>` will be recorded if the target fetches it.

Read the hit log with:

```
ssh eval-server-polyphemus 'docker exec web_comfyui-ssrf-listener-1 tail -n 40 /tmp/ssrf_hits.log'
```

Use it only to observe fetches caused by your own probe URLs (put a unique marker in the path).
This is an effect oracle you own; the black-box discipline of section 3.1 still applies to the target.

## 4. The workflow (five states) and the reasoning rules

### 4.0 Reasoning rules (always in force)

- **Two worlds**: states 1-3 build the technical and trust model (sharpening); state 4 abducts vulnerability classes from the mapped programming faults; state 5 deduces runtime failure modes and closes the loops.
- **Evidences**: every claim (agreement, flow, assumption, fault, vulnerability, failure mode) carries an `evidences` list.
  Evidence kinds available in this trial: request records (`GET /path -> 200`), probe log references, note references.
  There is no separate citations block.
- **Rungs**: every claim carries a rung, one of
  - `OBSERVED` - witnessed by a probe or a response you received;
  - `INFERRED` - reasoned from observed facts plus technology/framework defaults;
  - `ASSUMED` - a hypothesis you have not yet probed.
  Rungs direct probing: `ASSUMED` claims are your probe targets; a probe either raises the rung (toward `OBSERVED`) or falsifies and rewrites the claim.
- **Assumptions** are each named by induction from or to a programming fault that a developer could have made.
- **Breadth over pruning**: keep every loop that survives the drop rule below; do not filter by taste.
- **Drop rule**: drop a vulnerability (and its loop) only when its runtime failure mode is not technically feasible AND no evidence can be collected from the HTTP-history store or from target interaction.
  Record each drop in place with its reason; never delete silently.
- **Probe plans are not model content**: probing is an action of this phase.
  Unrun or blocked probes go in the trace only.
  Attack engineering belongs to the hunters.
- **Failure modes** are strictly for technical feasibility assessment and likelihood scoring.
  A vulnerability may have one or more failure modes (1:n).
  They remain in the formal model and are never passed downstream.
- **Loops**: the ranked rows are keyed `loops` (the old name "chain" is retired because it collides with attack kill chains).
  A loop is: fault -> vulnerability class -> failure mode assessment -> likelihood.
  Loop ids are assigned symbolically at the completion write, in ranked order (`loop-1` = highest likelihood).
- **Likelihood** is qualitative (`high` / `medium` / `low`) with a one-line rationale; impact is excluded.
- **Completion** needs no extra input: the reversed technical architecture is in the model; re-read the model if context is lost.

### 4.1 State 1 - UNIT_TECHNICAL_SHARP (grounding)

- Ground on the service contract in section 2.1.
- Extend onto the linked endpoints and services-systems (section 2.2, 2.3), and probe the live target to reverse-engineer the technical mechanism the unit relies on.
- Read the reasoning material: the first two steps of `/Users/diekgbbtt/.claude/worktrees/unit-threat-model/docs/design/modelling-trust-boundaries-notes.md`, particularly the request-handling stack layers.
- Define formally, once the picture is sharp:
  1. the technical interface agreements between the components involved in the unit;
  2. the control flows;
  3. the data flows.
- Gate: write the initialised model document (state 1 content) and log `GATE-WRITE UNIT_TECHNICAL_SHARP`.
- Close the phase with an episodic note.

### 4.2 State 2 - TRUST_MODELLED (two sequential branches)

1. Trust-agreement branch: translate every interface agreement into a trust agreement over data attributes, application contexts and principal privileges.
   Material: the trust-modelling steps of `modelling-trust-boundaries-notes.md` that do not concern making assumptions.
2. Dynamic-state branch: then analyse the unit as an application-states flow and model dynamic state trust (EFSM stages 1-4), looking for TOCTOU, multi-step business-logic bypass and forced state transitions.
   Material: `/Users/diekgbbtt/.claude/worktrees/unit-threat-model/docs/design/modelling-dynamic-states-trust-notes.md` until stage 4.

- Gate: extend the model with both branches' outcomes and log `GATE-WRITE TRUST_MODELLED`.
- Close the phase with an episodic note.

### 4.3 State 3 - TRUST_ASSUMPTIONS_WRITTEN

- Continue both perspectives and write the trust assumptions that bend the trust agreements.
- Each assumption is named by induction from or to a technical programming fault a developer could have made; the result is a cohesive, solid set of faults.
- Material: the adversarial reasoning steps of the two notes documents.
- Gate: extend the model with assumptions and faults and log `GATE-WRITE TRUST_ASSUMPTIONS_WRITTEN`.
- Close the phase with an episodic note.

### 4.4 State 4 - VULNERABILITIES_WRITTEN

- World 2: runtime state adversarial analysis; abduction.
- For each mapped programming fault, name the web vulnerability classes (canonical taxonomy, freely) that could characterise the application if the fault is effectively implemented.
- Only then map each class to the suite (section 3.4); multiple vulnerabilities per fault are allowed.
- Gate: extend the model with the vulnerabilities and log `GATE-WRITE VULNERABILITIES_WRITTEN`.
- Close the phase with an episodic note.

### 4.5 State 5 - COMPLETED

- Deduce: map each vulnerability back to the runtime execution failure mode(s) where the vulnerability is exploited, grounded in the state-1 sharpening.
- Feasibility check per vulnerability: if the runtime failure mode is not technically feasible from this perspective AND no evidence can be collected from the HTTP-history store or from target interaction, drop it (record the reason in place).
- Rank the surviving loops by likelihood (`high` / `medium` / `low`), ids assigned in ranked order.
- Gate: extend the model with the failure modes and the loops and log `GATE-WRITE COMPLETED`.
- Close the phase with an episodic note.

## 5. Stop rule

Probe until:

- every probeable `ASSUMED` claim has been probed (raised, falsified, or blocked-with-reason), and
- one further probing pass over the sharpening yields no new assumption branches (saturation).

Blocked probes are recorded in the trace with the reason.
Keep the total under 60 shell probe commands.

## 6. Outputs (exact paths)

All under `/Users/diekgbbtt/.claude/worktrees/unit-threat-model/docs/experiments/unit-threat-model-prototype/trials/t1-service-model-download/output/`:

1. `threat-model-Service-model-download.yaml` - the model document (skeleton in section 7), written at the gates.
2. `trace.md` - the trajectory: for each state, the gate write, the probes run, the decisions made and the state of the model at that point; blocked probes and their reasons.
3. `notes.md` - the episodic notes (one or more per tool-using phase).
4. `gates.log`, `probes.log` - the command logs (sections 3.1, 3.3).
5. `metrics.yaml` - per state: `probes_run`, `notes_written`, `wallclock_s` (measure with `date +%s` deltas).

Final message (short): states reached; counts (interface agreements, control flows, data flows, trust agreements, EFSM states/transitions/violations, assumptions, faults, vulnerabilities, failure modes, loops kept/dropped); the top three loops with their classes and likelihood; drops with reasons; evidence gaps; the artefact paths.

## 7. Model document skeleton

```yaml
unit_id: Service:model-download
kind: Service
state: COMPLETED            # the five uppercase states are the persisted states
environment:
  base_url: http://46.224.225.245:44177
  http_history: none
  previous_models: none
technical_sharpening:
  interface_agreements: [{id, statement, rung, evidences: []}]
  control_flows: [{id, statement, rung, evidences: []}]
  data_flows: [{id, statement, rung, evidences: []}]
trust_model:
  trust_agreements: [{id, statement, rung, evidences: []}]
  dynamic_state_trust:
    states: []
    transitions: []
    violations: []
assumptions: [{id, statement, induced_fault: <fault-id>, rung, evidences: []}]
faults: [{id, name, rung, evidences: []}]
vulnerabilities: [{id, fault_ref, class: <canonical name>, suite_class: <suite directory name or null>, rung, evidences: []}]
failure_modes: [{id, vulnerability_ref, runtime_failure_mode, feasible: true, drop_reason: null, rung, evidences: []}]
loops: [{loop_id, fault_ref, vulnerability_ref, failure_mode_refs: [], likelihood: high|medium|low, likelihood_rationale, rung}]
evidence_gaps: []
```
