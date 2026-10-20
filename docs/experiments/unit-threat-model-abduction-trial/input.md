# Trial T1-TBSG - threat modeller on `Service:model-download` (comfyui live target, boundary-abduction variant)

Trial id: `t1-tbsg-service-model-download`.
Target family: comfyui (ComfyUI core v0.3.76 + ComfyUI-Manager V3.37), live deployment.
Artefacts land under: `/Users/diekgbbtt/.claude/worktrees/unit-threat-model/docs/experiments/unit-threat-model-abduction-trial/output/`.

## 0. Mission

You are the **threat modeller** of the polymerhus hunting pipeline (design in flight).
Execute the five-state unit-threat-model workflow (section 4) on the unit in section 2, against the live target in section 1.
The workflow in section 4 is the **boundary-abduction** variant: the trust model is written as boundary records (what the receiving side checks versus what it requires), and the assumptions state runs a structured abduction over four dimensions with a propagation walk.

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

- The target is live at `http://46.224.225.245:47745` (this is the ComfyUI deployment described in section 1).
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
- The baseurl carried in the projection is the synthetic host form `http://comfyui-manager:8288`; the live origin you probe is `http://46.224.225.245:47745` (same deployment, different address).

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
  `/Users/diekgbbtt/.claude/worktrees/unit-threat-model/docs/experiments/unit-threat-model-abduction-trial/output/probes.log`:

  ```
  printf '%s %s %s -> %s | %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "<method>" "<path>" "<status-or-error>" "<one-line observation>" >> /Users/diekgbbtt/.claude/worktrees/unit-threat-model/docs/experiments/unit-threat-model-abduction-trial/output/probes.log
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
printf '%s [%s] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "<STATE>" "<decision node :: branch taken :: rationale>" >> /Users/diekgbbtt/.claude/worktrees/unit-threat-model/docs/experiments/unit-threat-model-abduction-trial/output/notes.md
```

### 3.3 Gate writes (the store write at each state)

Each state ends with a gate: write/extend the model document at
`/Users/diekgbbtt/.claude/worktrees/unit-threat-model/docs/experiments/unit-threat-model-abduction-trial/output/threat-model-Service-model-download.yaml`
and log the gate:

```
printf '%s GATE-WRITE %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "<STATE>" >> /Users/diekgbbtt/.claude/worktrees/unit-threat-model/docs/experiments/unit-threat-model-abduction-trial/output/gates.log
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
- **Evidences**: every claim (agreement, flow, boundary record item, assumption, fault, vulnerability, failure mode) carries an `evidences` list.
  Evidence kinds available in this trial: request records (`GET /path -> 200`), probe log references, note references.
  There is no separate citations block.
- **Rungs**: every claim carries a rung, one of
  - `OBSERVED` - witnessed by a probe or a response you received;
  - `INFERRED` - reasoned from observed facts plus technology/framework defaults;
  - `ASSUMED` - a hypothesis you have not yet probed.
  Rungs direct probing: `ASSUMED` claims are your probe targets; a probe either raises the rung (toward `OBSERVED`) or falsifies and rewrites the claim.
- **Boundary records**: every interface agreement and every EFSM transition carries a boundary record: the crossing `artifact`, `establishes` (the checks actually applied and the assertions they establish), and `requires` (what the receiving side relies on before it can process safely).
  Both sides are claims: each item carries a rung and evidences.
  A boundary where no validation exists is recorded as "no validation present" and is itself a finding.
- **Abduction**: in state 3 the trust assumptions are abduced from the boundary records across the four dimensions (section 4.3).
  Each assumption still names the developer assumption and the programming fault it induces, and is marked `local` or `propagated`.
- **No symbolic machinery**: the records and the propagation walk are authored by you from the sharpening.
  Nothing is enumerated symbolically and no verification algorithm is implied.
- **Assumptions** are each named by induction from or to a programming fault that a developer could have made; the abduction supplies the structured reason why the receiving side's reliance is unsafe.
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
  1. the technical interface agreements between the components involved in the unit, each carrying its boundary record fields: `artifact` (the crossing item: request, message, token, response, file) and `establishes` (the inventory of checks the receiving side actually applies and what each check establishes; use the request-handling stack layers as the checklist; each item with rung and evidences; record a missing check as "no validation present");
  2. the control flows;
  3. the data flows.
- Gate: write the initialised model document (state 1 content) and log `GATE-WRITE UNIT_TECHNICAL_SHARP`.
- Close the phase with an episodic note.

### 4.2 State 2 - TRUST_MODELLED (two sequential branches)

1. Trust-agreement branch: translate every interface agreement into a trust agreement over data attributes, application contexts and principal privileges.
   The receiving side's reliance is written as `requires` (what must hold before the receiving side can process the artifact safely: the required data attributes, the required application context, the required principal privileges; each item with rung and evidences).
   The formal core of this branch is the comparison between `establishes` and `requires`: a gap candidate is any requirement the established assertions do not entail.
   Material: the trust-modelling steps of `modelling-trust-boundaries-notes.md` that do not concern making assumptions; the notes' reconciliation step (compare what each component guarantees with what the next assumes) is read in these terms.
2. Dynamic-state branch: then analyse the unit as an application-states flow and model dynamic state trust (EFSM stages 1-4), looking for TOCTOU, multi-step business-logic bypass and forced state transitions.
   Each transition carries a boundary record: `artifact` (the transition input plus the state read), `establishes` (the guard conditions actually enforced - the "actually verified" side, each item with rung and evidences), and `requires` (the post-state invariant plus the trust-transition agreement that must hold before a less-trusted state can advance into a more-trusted one, plus the state attributes downstream steps rely on - the "merely trusted" side, each item with rung and evidences).
   Material: `/Users/diekgbbtt/.claude/worktrees/unit-threat-model/docs/design/modelling-dynamic-states-trust-notes.md` until stage 4; stages 3 and 4 are read as the guard-versus-invariant split.

- Gate: extend the model with both branches' outcomes and log `GATE-WRITE TRUST_MODELLED`.
- Close the phase with an episodic note.

### 4.3 State 3 - TRUST_ASSUMPTIONS_WRITTEN (the abduction)

- For every boundary record - interface and transition - run the four dimension questions.
  The dimensions are the hypothesis space of the abduction: they classify what the receiving side still lacks after a successful pass.
  - `identity`: does the pass establish that the actor behind the artifact is the principal the receiving side intends to trust, with current authority? (gap shapes: revoked or stale authority, token reuse, identity binding)
  - `spatial`: does the pass establish that the artifact reaches only the intended destination and its effects stay inside the expected scope? (gap shapes: wrong object, wrong tenant, out-of-scope reach, path escape)
  - `temporal`: does the pass establish that the assertion remains valid at use time, not only at check time? (gap shapes: check-use divergence, staleness, non-atomic commit, replay, out-of-order)
  - `interpretation`: does the pass establish that the artifact produces only the behaviour the receiving side intends when it is processed? (gap shapes: parser differentials, overloaded fields, stored content reinterpreted, injection)
- Write one trust-assumption record per credible gap: `statement` (the developer assumption: what the developer relied on), `induced_fault` (the programming fault it induces), `boundary_ref` (the boundary record it bends), `dimension` (one or more), `propagation` (`local`, or `propagated` with `origin_ref`), rung, evidences.
- Propagation walk (bounded): for a gap visible at a boundary, ask whether it originates at an earlier boundary or transition whose requirement was not established and which carried the unverified assertion forward; when it does, mark the current assumption `propagated` with that origin.
  Walk the EFSM the same way: a state reached by one transition can carry an unverified assertion into the next.
  Do not enumerate interleavings, and a suspected composition claim with no single-transition origin and no traceable carried assertion is out of scope - record it in `evidence_gaps` if it looks real.
- Each assumption is still named by induction from or to a technical programming fault a developer could have made; the abduction supplies the structured reason, not a replacement for the fault naming.
  The result is a cohesive, solid set of faults.
- Discipline before the gate: check the closure - every interface agreement and every transition has a boundary record, and every assumption resolves to one.
- Material: the adversarial reasoning steps of the two notes documents.
- Gate: extend the model with assumptions and faults and log `GATE-WRITE TRUST_ASSUMPTIONS_WRITTEN`.
- Close the phase with an episodic note.

### 4.4 State 4 - VULNERABILITIES_WRITTEN

- World 2: runtime state adversarial analysis; abduction of vulnerability classes from the mapped programming faults.
- For each assumption/fault, name the web vulnerability classes (canonical taxonomy, freely) whose exploitation realises the unestablished property in that dimension (for example a spatial gap yields classes whose technique is reach-out beyond the intended scope, such as server-side request forgery or path traversal).
  The dimension constrains the reasoning, not a list: do not consult or invent per-dimension class lists.
- Only then map each class onto the suite (section 3.4); multiple vulnerabilities per fault are allowed.
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

All under `/Users/diekgbbtt/.claude/worktrees/unit-threat-model/docs/experiments/unit-threat-model-abduction-trial/output/`:

1. `threat-model-Service-model-download.yaml` - the model document (skeleton in section 7), written at the gates.
2. `trace.md` - the trajectory: for each state, the gate write, the probes run, the decisions made and the state of the model at that point; blocked probes and their reasons.
3. `notes.md` - the episodic notes (one or more per tool-using phase).
4. `gates.log`, `probes.log` - the command logs (sections 3.1, 3.3).
5. `metrics.yaml` - per state: `probes_run`, `notes_written`, `wallclock_s` (measure with `date +%s` deltas).
   Counts under `model_counts`: `interface_agreements`, `control_flows`, `data_flows`, `trust_agreements`, `efsm_states`, `efsm_transitions`, `efsm_violations`, `assumptions`, `assumptions_local`, `assumptions_propagated`, `dimensions_used` (list), `faults`, `vulnerabilities_kept`, `vulnerabilities_dropped`, `failure_modes_feasible`, `failure_modes_dropped`, `loops`, `evidence_gaps`.

Final message (short): states reached; counts (interface agreements, control flows, data flows, trust agreements, EFSM states/transitions/violations, assumptions with local/propagated split and dimensions used, faults, vulnerabilities, failure modes, loops kept/dropped); the top three loops with their classes and likelihood; drops with reasons; evidence gaps; the artefact paths.

## 7. Model document skeleton

```yaml
unit_id: Service:model-download
kind: Service
state: COMPLETED            # the five uppercase states are the persisted states
environment:
  base_url: http://46.224.225.245:47745
  http_history: none
  previous_models: none
technical_sharpening:
  interface_agreements: [{id, statement, artifact, establishes: [{item, layer, rung, evidences: []}], rung, evidences: []}]
  control_flows: [{id, statement, rung, evidences: []}]
  data_flows: [{id, statement, rung, evidences: []}]
trust_model:
  trust_agreements: [{id, statement, requires: [{item, kind: attribute|context|privilege, rung, evidences: []}], rung, evidences: []}]
  dynamic_state_trust:
    states: [{id, name, definition, rung, evidences: []}]
    transitions: [{id, state_from, state_to, trigger, artifact, establishes: [{item, rung, evidences: []}], requires: [{item, kind: invariant|trust_transition|state_attribute, rung, evidences: []}], side_effects, rung, evidences: []}]
    violations: []
assumptions: [{id, statement, induced_fault, boundary_ref, dimension: [identity|spatial|temporal|interpretation], propagation: {kind: local|propagated, origin_ref}, rung, evidences: []}]
faults: [{id, name, rung, evidences: []}]
vulnerabilities: [{id, fault_ref, class, suite_class, rung, evidences: []}]
failure_modes: [{id, vulnerability_ref, runtime_failure_mode, feasible: true, drop_reason: null, rung, evidences: []}]
loops: [{loop_id, fault_ref, vulnerability_ref, failure_mode_refs: [], likelihood: high|medium|low, likelihood_rationale, rung}]
evidence_gaps: []
```
