# Hunting agent spec: threat modeller

## Amendment 2026-10-25: impact-first elicitation

The threat-model impact-elicitation workstream supersedes the likelihood-only risk score and the failure-mode artifact in this document.
The decisions are in `docs/design/threat-model-impact-elicitation-adr.md`; the component map is `docs/design/threat-model-impact-elicitation-impact-map.md`.
Where this document and the amendment disagree, the amendment wins.

- A threat carries `VC`, `VI`, and `VA` plus a literal end impact. The store computes `impact = 1 - (1-VC)(1-VI)(1-VA)`, the ordinal weight, and `threat risk = likelihood_weight * impact_weight`.
- The ranking and the dispatch buckets use the combined risk. The run record carries `impact_weights` and `impact_breakdown`.
- The `failure_modes` artifact, `Threat.failure_mode_refs`, and the pod `failure-mode` variant basis are removed. The modeller no longer judges technical feasibility; the hunter and the pod own the effective attempt.
- The trust procedure uses the four axes `identity`, `spatial`, `temporal`, and `controls_semantics`.
- The well-formedness phase runs between `VULNERABILITIES_WRITTEN` and `COMPLETED`. Its exit is one `wellformedness` note plus the `COMPLETED` write; a lower-gate write is the re-entry signal.
- Every vulnerability binds a suite class parent or leaf. Technique families are not classes. `suite_gap` is removed. Class findings are non-blocking.


*Status: spec (contract), NOT implementation. Tracker: [#373](https://github.com/Diekgbbtt/polyphemus/issues/373). This document is the build spec for the unit threat model redesign. It supersedes `docs/design/hunting-67-orchestrator-spec.md` in full for the modeller role. It is synthesised from the grilling record (`docs/design/unit-threat-model-workbench.md`), the workflow contract (`docs/design/unit-threat-model-workflow.md`), the tool-binding ADR (`docs/design/unit-threat-model-tools-adr.md`), and the ordering-halt ADR (`docs/design/unit-threat-model-ordering-halt-adr.md`). The artifact contract is `docs/design/hunting-67-threat-model-artifact-spec.md`; the impact map is `docs/design/unit-threat-model-spec-impact-map.md`.*

## 1. Problem statement

The hunting pipeline schedules hunts by fault class.
It orders the fault space globally and spends the run before it reaches the unit-specific, high-yield directions.
The measured defect is navigational, not instrumental.
The White Jotter evaluation never covered stored XSS, RCE, SQLi, or arbitrary file read.
The consumed configs were access-control and hygiene families.
A second cause was upstream: SPA API endpoints were never collected.

The operator's framing is that the fault space is too wide and that units differ.
A product-submission service can vector a payload into a victim context, so stored or reflected XSS is inherently likely there.
An API that interfaces a file-upload primitive makes RCE inherently likely there.
The ordering must be unit-specific and probability-first, not a global fault-class sweep.

The current hunt-orchestrator is a planner over a pre-computed fault substrate.
The DataItem layer and the trust-boundary L1 nodes were retired.
A planner can no longer read the trust model from the substrate.
The pipeline needs an agent that builds the trust model per unit and publishes the research directions that follow from it.

## 2. Solution

### 2.1 The role change

The hunt-orchestrator is rewritten in place into the **threat modeller**.
No new submodule is added and no role is split.
For each discretely testable L1 unit, the modeller publishes one **unit threat model** with a ranked set of **threats**.
A threat is a research direction: fault -> web vulnerability class -> failure-mode assessment -> likelihood.
The model is the persisted artifact and the dispatch grain is the threat.

The phase-2 attack-tree document is inspirational only, never a compatibility contract.
The two paradigms abduct in opposite directions.
The shared shape is `fault -> vulnerability class -> failure mode` plus `fault -> observable symptom`.
A confirmed vulnerability can feed a later hunting phase.
It never updates a threat model, because a model never evolves.

### 2.2 The outcome

The run consumes the L1 inventory in live-edge-count order.
It models each unit until the progressive risk budget halts the intake.
It publishes the model and its threat files.
The surfer dispatches one hunter per threat.
High and medium threats are dispatched first.
Low threats stay dispatchable and are paused until the higher ranks are executed.
No direction is lost: a falsified vector lowers the likelihood, and a fundamental infeasibility is recorded as a backward correction.

## 3. User stories

1. As an operator, I want the pipeline to model each L1 unit into a formal threat model, so that the research directions follow the unit's actual trust agreements instead of a global fault checklist.
2. As an operator, I want the run to spend its budget on the units with the most live edges first, so that the modelled set covers the most connected surface.
3. As an operator, I want the progressive risk budget to stop the intake at a recorded crossing unit, so that the run is bounded without a hidden per-unit cap.
4. As an operator, I want the blocked unit recorded in the run, so that the halt is auditable.
5. As an operator, I want a unit with a completed model excluded from a later run, so that the pipeline never re-models a decided unit.
6. As an operator, I want the model to persist its evidence per claim, so that a reviewer can reconstruct why a direction was kept, lowered, or dropped.
7. As an operator, I want every claim to carry a confidence degree, so that ASSUMED claims are visible as probe targets.
8. As an operator, I want the modeller to probe the live target, so that the trust agreements rest on observed mechanics rather than induction.
9. As an operator, I want mutating probes allowed for evidence with best-effort restoration, so that a probe can establish a state-changing agreement without damaging the target.
10. As an operator, I want probes never destructive or data-exfiltrating, so that the modeller checks mechanics without exploiting.
11. As an operator, I want a drop to require a fundamental infeasibility finding, so that a missing observation never masquerades as a missing mechanism.
12. As an operator, I want a falsified vector to lower the likelihood instead of dropping the threat, so that the hunter keeps the room to find the vectors.
13. As an operator, I want failure modes kept in the model and never fed to the hunter, so that the hunter is not narrowed to one engineered procedure.
14. As an operator, I want the model to cite the web-vulnerability skills suite class, so that the hunter can load the class procedure.
15. As an operator, I want the model's likelihood score to use the CVSS-inspired four-factor reasoning, so that the score is grounded in attack vector, attack requirements, privileges, and complexity.
16. As an operator, I want the five-level likelihood enum and monotonic weights, so that the per-unit sum is deterministic.
17. As an operator, I want the threshold and the weights recorded in the run, so that the halt is reproducible.
18. As an operator, I want the model to record an assumption-to-threat closure finding, so that an unclosed assumption is visible at review.
19. As an operator, I want a degraded unit recorded and skipped, so that an unreachable target never fabricates a model.
20. As an operator, I want the run to resume from the recorded intake position and accumulator, so that a stopped run does not lose its ordering.
21. As the threat modeller, I want the unit projection, the L1 application-surface overview, and the HTTP history as grounding inputs, so that I can sharpen the unit's interfaces, control flows, and data flows.
22. As the threat modeller, I want the two modelling notes embedded in my phase prompts, so that the trust-modelling method is available at the point of use.
23. As the threat modeller, I want one generic store-write surface with a gate state, so that I extend the model at each workflow state without a schema lock.
24. As the threat modeller, I want the next-state hint injected into the gate write's response, so that I know the next state without the system prompt carrying the whole control flow.
25. As the threat modeller, I want HTTP-history search and get tools, so that I can cite recorded request traffic.
26. As the threat modeller, I want the auth store and the project skill, so that my probes and trust analysis use the project's real context.
27. As the threat modeller, I want the web-vulnerability skills suite, so that I can map a freely named class to the suite class that covers it.
28. As the threat modeller, I want the loose completion checker, so that missing necessary attributes are surfaced without blocking the model's publication.
29. As the threat modeller, I want a saturation stop, so that I do not stop on an arbitrary question count while a probeable assumption remains.
30. As the threat modeller, I want the live-authority rule, so that upstream material stays a hypothesis generator and live responses stay the evidence.
31. As a reviewer, I want the gate cadence telemetried, so that batched and interleaved writes remain visible.
32. As a reviewer, I want the model's state to be monotonic, so that a late earlier-gate write cannot regress the persisted state.
33. As a reviewer, I want the run record to carry the order, per-unit sums, crossing unit, and blocked unit, so that the progressive halt is auditable.
34. As a reviewer, I want the removed planner surfaces gone, so that no dead candidate gate, back-edge, or `HuntConfig` path remains.
35. As a runtime operator, I want the modeller's provider failures to pause the run as interrupted, so that a throttle is never recorded as a modelling result.
36. As a runtime operator, I want the role and session names to say "threat modeller", so that logs and traces name the role truthfully.

## 4. Identity and agentic attributes

### 4.1 Role

The threat modeller is the first agent role of the hunting bounded context.
One modeller exists per hunting run.
It models one L1 unit at a time.
It is not a planner over a fault catalogue.
It is a trust modeller and a research-direction publisher.

The runtime role key is renamed from `orchestrator` to `threat-modeller`.
The LLM role ID is renamed from `hunting_orchestrator` to `hunting_threat_modeller`.
The actor/session role is renamed from `hunting_orchestrator` to `hunting_threat_modeller`.
The provider environment variable `LLM_HUNTING_THREAT_MODELLER` replaces `LLM_HUNTING_ORCHESTRATOR`.
The agent-profile and skill-binding entries follow the new role id.
The rename is an expand-contract pass inside this change.
The old names remain as aliases for one change window, then are removed.
New runs use the new session id.
A run interrupted before the rename does NOT resume: T10 (#383) closed the alias window, there is no recorded-id mapping back to the retired names, and no resume path is invented.
The provider environment variable `LLM_HUNTING_ORCHESTRATOR` remained a one-window fallback for `LLM_HUNTING_THREAT_MODELLER`; T10 closed the window and removed it (no alias remains).

### 4.2 Goal

For each admitted L1 unit, build a formal trust model and publish a unit threat model whose threats are ranked by likelihood.
Consume the unit intake in live-edge-count descending order.
Stop modelling when the progressive risk budget crosses its threshold.
Record every outcome and every exclusion in the run.
Never fabricate a model, a threat, or a verdict.

### 4.3 Scope

In scope:

- The modeller agent, its prompt material, its tool binding, and its passive workflow tracking.
- The unit threat model artifact and its store.
- The run-level intake, ordering, risk accumulator, halt, interleave, and resume.
- The removal of the planner surfaces: candidate intake, in-turn gate, `HuntConfig` minting, back-edge needs, materialisation, ratify/note phase turns.

Out of scope:

- Surface recovery, recon, and analysis.
- The hunter workflow redesign and the pod contract, which are separate specs.
- Model evolution, re-modelling, and version pins.
- Alpha-omega, full CVSS base metrics, and TBSG boundary records.

### 4.4 Runtime topology

The existing actor runtime is reused.
The modeller is a persistent mailbox actor on one per-run session thread.
The session id is `hunting:<run_id>:threat-modeller`.
The actor holds the per-run reasoning memory across units.
The per-turn isolation, retries, and no-decision recovery are unchanged.
The consecutive-degradation breaker is kept.
A provider failure is classified through the shared provider-failure path and pauses the run as `interrupted`.

The run bootstrap launches one modeller pass and one run-scoped surfer.
The modeller pass models units.
The surfer dispatches threats and pods.
The two run concurrently.
The modeller never dispatches a hunter directly.

### 4.5 Observability

One Langfuse trace per run.
Session = run id.
One span per state and per gate write, named after the state.
The gate cadence, probe cadence, and accumulator updates are recorded as observation metadata.
Langfuse is optional and fail-open.
Verdicts are read from the store records, never from Langfuse scores.

### 4.6 Context inputs

The modeller's grounding inputs are data:

- The L1 unit projection for the dispatched unit: the service contract or the system technical description, the linked endpoints and services-systems, and the live edge families.
- The L1 application-surface overview: the core features and canonical user journeys.
- The HTTP-history records for the unit's endpoints.
- The notes store and previous threat models, read as prior insights.
The shared notes store is the memory successor; prior insights feed the grounding; a re-model is a new run.
- The project skill and the web-vulnerability skills suite.
- The live target, through `exec` probes.

HTTP-history reads and probes are actions, not input artifacts.
Their records become claim evidence.
The L1 application-surface overview is a cross-workstream dependency; when it is absent, the modeller grounds on the projection and records the gap.

### 4.7 Output

The output is one unit threat model document and, at completion, one threat file per dispatchable threat.
The artifact contract is S2.
The model is consumable once it reaches COMPLETED with its threats written.
The surfer materialises the per-threat hunter payload at dispatch time.
No `HuntConfig` entity is minted.

### 4.8 Honour clauses

- Passive tracking: the harness never gates a tool call on the current state and never rejects a transition.
- Sole writer: the modeller never writes L0/L1.
- Evidence before assertion: every claim carries a confidence degree and evidence entries.
- Live authority: live target responses are the evidence; upstream material is a hypothesis generator only.
- Retention first: a falsified vector lowers the likelihood; only a fundamental infeasibility drops.
- No feed-forward of failure modes: failure modes stay in the model.
- No exploitation: probes are non-destructive where feasible, restored best-effort, and never destructive or exfiltrating.
- Fail-open: a degraded input degrades the unit or the run; it never raises into the turn.
- No fabricated result: an absent write means an absent artifact.

## 5. Tool surface

### 5.1 `hunts_store`

The modeller binds one store-write tool for the threat model.

The tool has `cmd: read | write`.
The name `hunts_store` is shared with the hunter; the modeller binds the threat-model store and the hunter binds the spec store.

A write carries one payload:

- `state`: one of `UNIT_TECHNICAL_SHARP`, `TRUST_MODELLED`, `TRUST_ASSUMPTIONS_WRITTEN`, `VULNERABILITIES_WRITTEN`, `COMPLETED`.
- `sections`: a mapping from section name to content for that state.

The store derives the unit directory and the model file name from the harness-bound unit identity.
The unit identity is bound at tool construction for the current unit pass.
The write payload never carries a file name, a model id, a storage path, or a derived symbol.

The store merges the sections into the existing model document.
The model `state` is monotonic.
A write whose state is lower than the persisted state updates the section content but never regresses the model state.
A write that is unparseable is rejected loudly and fail-safe.
No semantic schema gate exists at the write.
The completion checker runs only on the `COMPLETED` write.

The write response injects the next-state hint.
The hints are module constants, never the system prompt.

A read payload is `{cmd: read, unit_id?, section?}`.
A read with no `unit_id` reads the bound unit.
A read with a `unit_id` reads that unit's model for prior insight.
A read with a `section` returns only that section.
The read is read-only.

### 5.2 `notes`

The modeller binds the shared `notes` tool.
The notes are episodic memories of the execution.
They record decision nodes and the rationales of the taken branches.
They do not replace the model document.
The note key is bound to the current unit: `<unit_name>:<note_name>`.
The existing note kinds are available.
The `phase_summary` kind is reserved for the hunter and is not used by the modeller.
Notes are bounded by the shared conciseness directive.
Each reasoning phase ends with an episodic note through `notes`.
The note records the decision nodes and the rationales of the taken branches.
The note is prose, not a gate.

### 5.3 HTTP history

The modeller binds the read pair `search_http_history` and `get_http_artifact`.
It never binds `replay`.
Search returns candidate summary rows.
Get inspects one artifact and its capture state.
The artifact id and the request record become evidence entries.
The tool contracts are the existing `http-artifact/v1` contracts.

### 5.4 `exec`

The modeller binds the Kali exec tool.
The timeout is the shared `EXEC_TIMEOUT_S`.

The probe budget is unbounded at the role level.
The execution-wide token budget and the risk budget bound the run.
The probe cadence is telemetried.

Probe rules:

- Probes seek technical evidence for or against a claim.
- Mutating probes are allowed for evidence, for example persisting a value or submitting a form.
- Every probe and its side effect is recorded in the claim's `evidences`.
- Restoration is best-effort where the surface offers it.
- Probes are never destructive or data-exfiltrating.
- The modeller checks mechanics; it does not exploit.
- The target-front availability directive applies: a 502, 503, or 504 means the upstream is unavailable, not that the route is absent.
- The probe surface is black-box: HTTP surface only; no internal network probing beyond the target's own interfaces.
- Server-side fetch classes must be probed behind file, reference, import, and URL-shaped inputs (LACK-1).

### 5.5 Auth store and skills

The auth store is bound in READ-ONLY mode.
The modeller reads the login overview and the account records.
It never writes the store and never replays a secret.
The binding goes through the shared `auth_capable_binding` `arm_exempt_surface` path.
That path also carries the project `authn` skill.

The project skill is bound through `load_skill`.
The skill-usage lesson recorder is bound through `record_skill_lesson`.

The web-vulnerability skills suite is bound through `skill_list` and `skill_load`.
The suite class is the stored `web_vulnerability_class` of a vulnerability.
The class name must equal a skills-suite directory name.
`skill_list` requires a case-insensitive regex over skill names.
A missing filter is `skill_filter_required`; an invalid regex is `skill_filter_invalid`; a no-match regex returns an empty `skills` list.
A parent match returns the class parent plus its variant leaves; a leaf match returns the leaf plus its class parent, so an abbreviated leaf (`bfla-*`) still yields `broken-function-level-authorization`.
The listing is capped at 20 entries and reports the omitted count.
If the suite lands with different tool names, an adapter maps the assumed `skill_list` / `skill_load` names to the built tools.
The role is enabled only when the suite contract test passes.
The control plan binds that skill to the hunter prompts.

The modeller's bound surface is:

- `hunts_store`;
- `notes`;
- `search_http_history`;
- `get_http_artifact`;
- `exec`;
- `skill_list`;
- `skill_load`;
- `load_skill`;
- `record_skill_lesson`;
- `auth_store` (read-only).

The prompt's tool section names every tool in that list.
The request tool definitions are the full surface.
The system prompt carries no second description body.

The 5xx rule is the shared target-front rule.
The prompt points at it with the 502, 503, 504, and 404 semantics.
It does not copy the full directive.

### 5.6 Not bound

`graph_view` is not bound.
The modeller is fed the unit projection and the application-surface overview.
The fault-KB aid tool is withdrawn.
Fault hypothesisation is trust-model driven, never copied from an outside repository.
`kb_query` / `query_lightrag` is not bound.
The testing-methodology KB stays with the hunters and the pod.

### 5.7 Context is live

The unit projection, the application-surface overview, the notes, and the previous models are read at grounding time.
They are never a stale pipeline snapshot.
A failed read degrades to an empty set and is recorded.
A failed write raises to the harness, which warns and keeps serving.

## 6. Workflow and reasoning contract

### 6.1 States and gates

The harness tracks five states passively.
Each gate is a `hunts_store` write.
The workflow contract is `docs/design/unit-threat-model-workflow.md`.

| State | Gate write section | Necessary content |
|---|---|---|
| `UNIT_TECHNICAL_SHARP` | `technical_sharpening` | Interface agreements, control flows, data flows; each with confidence and evidence |
| `TRUST_MODELLED` | `trust_model` | Trust agreements plus dynamic-state trust (states, transitions, violations) |
| `TRUST_ASSUMPTIONS_WRITTEN` | `assumptions` | Assumptions, each naming an induced programming fault |
| `VULNERABILITIES_WRITTEN` | `vulnerabilities` | Web vulnerability classes, each mapped to a suite class |
| `COMPLETED` | `failure_modes`, `threats` | Failure modes for the map-back and the ranked threats; the store computes the risk profile; the completion checker runs |

The states are sequential.
The harness accepts a forward jump and records the skipped states in the run record's `trajectory`.
A trajectory entry records the unit, the signal, the from-state, the to-state, the outcome, and the time.
The model's gate writes remain the authority for the content.
A skipped gate leaves a missing section; the completion checker reports it.
The machine never blocks the model from reasoning ahead.

The state values are structural, not a separate lifecycle.
The model's `state` is the latest gate.
The COMPLETED write makes the model consumable.
There is no `confirmed` state and no confirmation step.

### 6.2 The five phases

**Grounding -> UNIT_TECHNICAL_SHARP.**
Ground on the service contract or the system technical description.
Extend onto the linked endpoints and services-systems.
Read the HTTP history for the unit's endpoints.
Interact with the target to reverse-engineer the technical mechanism.
Probe iteratively until the assumption space is sufficiently explored.
Define the technical interface agreements, the control flows, and the data flows.
The gate write initialises the model.
The phase material is the request-handling stack and the trust-boundary steps from the retired notes document, embedded in the prompt.
The phase ends when the modeller can define the agreements formally and every probeable ASSUMED claim is resolved or explicitly carried.
The grounding is an explore/exploit threat in the reasoning, not a harness threat state.
Completion needs nothing beyond context; the modeller re-queries the model if compression evicted it.

**Trust mapping -> TRUST_MODELLED.**
Run two branches sequentially.
Branch A translates the interface agreements into trust agreements over data attributes, application contexts, and principal privileges.
Branch B models dynamic-state trust from the application-states-flow perspective: states, transitions, and trust-transition violations, including TOCTOU, multi-step business-logic bypass, and forced state transitions.
The branches consume the interface agreements and the confidence layers.
The gate write extends the model with both outcomes.
The phase material is the dynamic-state trust workflow, until stage 4.

**Assumptions -> TRUST_ASSUMPTIONS_WRITTEN.**
Continue both perspectives.
Write the assumptions that bend the trust agreements.
Each assumption is induced from or to a technical programming fault that a developer could have made.
The result is a cohesive set of faults, not a list of guesses.
The gate write extends the model with the assumptions and their faults.

**Vulnerability citation -> VULNERABILITIES_WRITTEN.**
Switch to the abduction world.
For each mapped fault, name the web vulnerability classes freely from the canonical taxonomy.
Then map each named class onto the unspurious web-vulnerability suite class that covers it.
The stored `canonical_class` is the freely named taxonomy class.
The stored `web_vulnerability_class` is the skills-suite directory name; the decided field keeps its original semantics.
Where no suite class covers the named class, `web_vulnerability_class` is empty and `suite_gap` is true.
A fault may yield several vulnerabilities.
The gate write extends the model with the vulnerabilities.

**Failure-mode deduction -> COMPLETED.**
Map each vulnerability back to one or more runtime failure modes, grounded in the sharpening.
The failure modes drive the feasibility assessment and the likelihood.
They are never rendered into the hunter payload.
Apply the drop rule.
Rank the surviving threats by likelihood.
Assign threat ids in ranked order.
Write the ranked threats; the store computes the risk profile.
The completion checker runs and records its non-blocking outcome.
The gate write finalises the model and emits the threat files.

### 6.3 Confidence degrees

Every formal claim carries a confidence degree:

- `OBSERVED`: witnessed by a probe or a request record.
- `INFERRED`: reasoned from observed facts plus technology or framework defaults.
- `ASSUMED`: a hypothesis not yet probed.

The degree directs probing.
The ASSUMED claims are the probe targets.
A promotion probe has a pure falsification nature.
When the proofs do not back the falsification claim, the claim is certified robust and promoted from ASSUMED to INFERRED or OBSERVED, depending on the accuracy delta of the proxy signal.

The content profile is repeatable and indexable.
A claim carries a list of evidence entries.
Each entry names the grounding that produced the confidence, for example a request record, an HTTP-history artifact, a probe, a note, a previous model, a framework default, or a document.

The threat carries its own confidence degree.
It grades the threat's load-bearing premise.
It is authored at the COMPLETED write.
It is one factor of the class assignment: the modeller lowers the class when the load-bearing premise is ASSUMED and records the reason.
The harness weights only the class; the confidence is not an independent summand.

The degrees freeze with the model at COMPLETED.

### 6.4 Assumption-to-threat closure and dedup

The adopted closure check requires:

- Every assumption names at least one programming fault.
- Every fault closes to at least one vulnerability.
- Every vulnerability that is not dropped closes to at least one failure mode and at least one threat.
- A dropped vulnerability records the fundamental infeasibility proof and the backward correction of the agreements it was mapped from.
- An unclosed assumption is recorded as a validation finding.

The dedup check is loose.
It reasons over all runtime failure modes a vulnerability could yield.
When the failure modes are not fully overlapping, the row is kept.
It prefers structurally promoting entries over tight cuts.
It accepts the risk of false overlap rather than losing a research direction.

The abduction research's boundary-record vocabulary is not adopted.
The KILL verdict bounds it to the evaluated implementation.
The two orthogonal disciplines are adopted: the drop-decision discipline and the assumption-to-threat closure check.

### 6.5 The drop rule

Retention is the default.
The hypothesis is stated broadly at the trust-agreement level.
Vectors and payloads belong to the hunters.

A probe that falsifies a vector lowers the likelihood.
It never drops the vulnerability.

A drop requires a fundamental technical-infeasibility finding:

- The mechanics the failure mode relies on are absent.
- Or the data is not attacker-influenced, so the trust agreement was misspecified.

A drop is a backward correction.
It corrects the interface and trust agreements it was mapped from.
The finding and the correction are recorded in place.
The failure mode stays in the formal model for debugging.
It is never fed forward.

An unprobed carrier keeps its threat at ASSUMED.
A threat with no feasible failure mode is retained with likelihood `none`.
It contributes zero to the risk sum.
It is not dispatched.

LACK-2 is binding.
A drop never rests on absence of evidence in the sharpening.
The modeller names the infeasibility finding and the discriminating probe shape that would have falsified it.

### 6.6 Completion validation

There is no blocking schema gate at any write.
The gate write checks parseability only, fail-safe and loud on an unparseable write.

`ratify` no longer names a phase or a turn.
It names the completion-time whole-model validation.
The validation runs on the `COMPLETED` write.
It is the loose necessary-attribute checker plus the referential-integrity and closure checks.
It records the outcome in the model's `validation` record.
The outcome is non-blocking.
The write finalises the model.

The necessary-attribute set is fixed in S2 5.7.
The per-phase loose checks ride the gate writes.

### 6.7 Live authority

Live target responses are the evidence.
Upstream source material, notes, and framework defaults are hypothesis generators only.
A divergence between upstream material and a live response is recorded.
The live response wins.

The rule serves the technical-feasibility judgement of the fault's implementation.
It checks whether the fundamental mechanics the failure mode relies on are present.
It is not a vector-level check.

### 6.8 Termination

Termination is saturation-based.
There is no modeller-scoped depth, question-count, or probe cap.

The stop condition is:

- Every probeable ASSUMED claim is resolved.
- A full further pass yields no new assumption branches.

The cost bound is the execution-wide token budget plus the risk budget.
The token cap is a runtime-plane hard stop.
The risk budget halts the intake, not the current unit.
The saturation stop and the risk halt are different boundaries.

## 7. Run lifecycle

### 7.1 Intake and freeze

At run start, the runtime reads the L1 inventory and freezes the unit set.
A unit is excluded when its threat model is already complete in `consumed/`.
A unit is also skipped when its model is in flight in `produced/`, because the model never evolves and a second writer would violate the sole-writer invariant.
A unit is excluded as `stale` when a terminal, non-resumable run's produced model could not be archived to `abandoned/`: it is never modelled into a stale model (implementation-time addition, T3 #376).
Each exclusion is recorded with its reason (`completed`, `in-flight`, or `stale`).

The freeze is a run-level snapshot.
The L1 graph may change during the run; the modeller does not re-read the inventory.

### 7.2 Ordering algorithm

Count the live L1 edges in both directions.
Use only the live edge families.
Exclude retired edge families and retired edges.

The live families are:

- `EXPOSED_VIA`
- `IDENTIFIED_BY`
- `AUTHENTICATED_BY`
- `AUTHORIZED_BY`
- `FRONTED_BY`
- `PROTECTED_BY`
- `ROUTED_BY`
- `SHAPES_DATA_OF`
- `ON_REQUEST_PATH`
- `DEPENDS_ON`

The L0-facing families `AGGREGATES` and `EVIDENCED_BY` are not counted as L1 edges.
They feed the tie-break only.

The sort key is:

1. Live L1 edge count, descending.
2. Aggregated endpoint count, descending.
3. Unit id, ascending lexicographic.

The aggregated endpoint count is:

- For a Service: the count of its `AGGREGATES` out-edges.
- For a System: the sum of the `AGGREGATES` out-degree of the Services connected to it.
Connectivity means reachable by any live L1 edge.
The Services are deduplicated by unit id, so multiple edges between the same pair count once.

The resulting order is recorded in the run as `intake_order`.

### 7.3 The modelling interleave

The modeller pass dequeues the next unit and models it to COMPLETED.
The surfer moves and dispatches completed threats while the modeller models the next unit.
The modeller does not wait for dispatch.
The store's produced threat files are the handoff.
The surfer's dispatch is idempotent and at-least-once.

### 7.4 Progressive risk budget

The threat likelihood weights are `none: 0`, `low: 1`, `medium: 2`, `high: 3`, `critical: 4`.

The harness computes the unit total symbolically:

```
unit_total = sum(weight(threat.likelihood) for threat in model.threats)
```

The modeller writes the threats.
The store computes the `risk_profile` from the threat likelihoods at the COMPLETED write.
The harness-owned total is authoritative.
The modeller does not author the total.

The run accumulator is symbolic run state:

```
run_total = run_total + unit_total
crossed = run_total >= threshold
```

The comparison is inclusive.
The check runs immediately after the COMPLETED write, before the next unit is dequeued.

When `crossed` is true:

- The crossing unit is fully modelled and dispatched.
- The next unit in `intake_order` is never modelled.
- The blocked unit is recorded as `blocked_unit`.
- `halt` is set in the run record.
- The modeller stops dequeuing.

The intake order is also the halt order; the halt set is a function of the order by construction (ordering-halt ADR).
The intake order is never re-sorted.
The sort key stays the sort key.

The token cap can still hard-stop dispatch independently.
The halt stops modelling, not the dispatch of admitted work.
The run drains admitted work and then settles.

The run record carries:

- `intake_order`
- `intake_position`
- `risk_threshold`
- `threshold_basis`
- `risk_weights`
- `risk_total`
- `risk_breakdown`
- `model_sums`
- `crossing_unit`
- `blocked_unit`
- `halt`
- `degraded_units`
- `trajectory`

Each `model_sums` entry carries the unit id, the total, and the per-level breakdown.
`risk_breakdown` is the sum of the per-model breakdowns.
`intake_position` is the index of the next unit to model.
The `trajectory` entries are defined in 6.1.

The per-level breakdown counts every threat, including `none`.

### 7.5 Resume

A stopped run resumes from the persisted run record.
It re-enters at `intake_position`.
It reads `risk_total`, `risk_threshold`, `intake_order`, and the model and threat files on disk.
It never re-models a unit whose model is complete.
It resumes the pending dispatch of produced threat files.
The pause of low threats survives a restart because it is filesystem state.
A resumed pass cannot update a completed model.
The model document commits before the run-record update.
On resume, the run recomputes `risk_total` from `model_sums` and the completed models, so a crash between the two writes cannot leave a stale total.
A halted run resumes dispatch only; it does not model another unit.
An interrupted run that predates the rename does NOT resume: the alias window is closed (T10 #383) and there is no recorded-id mapping back to the retired names.

### 7.6 Dispatch sequencing

The surfer dispatches threats in likelihood order.
`critical`, `high`, and `medium` threat files are dispatchable immediately.
`low` threat files stay in `produced/` until no critical, high, or medium threat file is produced and no critical, high, or medium hunter session is live.
`none` threats have no threat file and are never dispatched.

The sequencing is cross-unit.
The surfer reads the run's produced threat files, not only the current unit's.
A produced threat file from another run is left untouched.
The low-threat pause is a per-tick condition; a later unit's high threat can arrive after an earlier low threat has been dispatched.
This is accepted: the run is streaming and a later high threat cannot preempt work already admitted.

The model document moves with its last threat file.
A unit with zero dispatchable threats has its model document consumed at COMPLETED and records zero dispatches.

### 7.7 Degraded and interrupted outcomes

A unit is **degraded** when the evidence is unusable:

- The target is unreachable and no HTTP history exists.
- The unit projection is absent or unparseable.
- The skill suite is unavailable when the class mapping is required.

If a partial model exists, the store moves its unit directory to `abandoned/`.
The harness records the unit as degraded with the reason.
The run continues to the next unit.
A new run retries the unit because no completed model exists.
A unit whose COMPLETED validation fails is handled the same way: the model is archived to `abandoned/`, the unit is recorded in `degraded_units`, and no threat is dispatched.

The **escalated** run path is retired.
There is no validation bound to exceed.
The only run-level stops are the risk halt, the runtime token cap, and a provider interruption.

A provider failure pauses the run as `interrupted` with the typed cause.
A genuine internal error degrades the unit or fails the pass per the existing fail-open canon.

## 8. Prompt material

The system prompt carries the stable role and method.
The gate cadence is a prompt-level instruction only; the harness stays passive and telemetries the observed cadence.
The per-turn HumanMessage carries the current unit, the current state, the input data, and the gate instruction.
The next-state hints are injected in the store tool responses.

The system prompt must carry:

- The role and the goal.
- The five states and their content requirements.
- The trust-modelling ontology and the two-branch method.
- The confidence-degree definitions and the falsification lifecycle.
- The evidence discipline: every claim carries evidence entries; no probe plans; no citations block.
- The live-authority rule.
- The retention-first drop rule and the fundamental-infeasibility criterion.
- The assumption-to-threat closure check.
- The risk-scoring ontology: attack vector, attack requirements, privileges required, complexity; the five-level enum; the monotonic weights; the likelihood-only rule.
- The probe rules and the target-front availability directive.
- The tool guidance for `hunts_store`, `notes`, HTTP history, `exec`, the auth store, the skills suite, `load_skill`, and `record_skill_lesson`.
- The saturation stop.
- The output contract for each gate.

The per-state material is embedded from the retired notes documents:

- Grounding: the request-handling stack and the trust-boundary steps.
- Trust mapping: the dynamic-state trust steps until stage 4.
- Assumptions: the adversarial steps.
- Vulnerability citation: the suite mapping rule.
- Completion: the map-back, the drop rule, and the scoring.

No failure-mode detail is rendered into the hunter payload.
The threat rationale stays vulnerability-level.

## 9. Implementation decisions

### 9.1 Rewrite in place

The hunt-orchestrator module is rewritten in place.
The new public entry points replace the planner pass.
The runtime role, session, actor, and LLM role are renamed as section 4.1 states.
The old planner types are removed: `CandidateIntake`, `EnvisionedDirection`, `GateInput`, `GateDecision`, `RatifyDecision`, `NoteDecision`, `HuntConfig`, `DispatchResult`.
The old planner surfaces are removed: the candidate gate, the in-turn prune, `HuntConfig` minting, the back-edge need, the materialisation render, and the ratify and note phase turns.
The old selection and materialisation modules (`fault_source`, `fault_kb`, `symptom_kb`, `fault_risk`) have no producer in the new pipeline.
The implementation retires their runtime consumers and records the data-file disposition; the fault-KB artifact is not a runtime dependency of the modeller or the hunter.
The stale `OrchestratorTools.back_edge` field and the stale back-edge residue in the old orchestrator spec are removed.

The new types are owned by S2.
The modeller's run types are `ThreatModelRun`, `UnitOutcome`, and `RiskAccumulator`.

### 9.2 Store and tools

The threat model store is a new store class.
It reuses the established patterns:

- `write_text_atomic` for every whole-file write (same-directory temp file, flush, fsync, replace).
- `retain_bounded_records` for the notes store.
- The derived-symbol discipline: the store owns the file name, the unit directory, the threat id, and the dispatch id.
- The move-aware write discipline: a write for a consumed identity is a no-op success.
- The coded teaching rejection for a missing or malformed derivation input.
- The shared `notes` tool base with a caller-bound handle.

The implementation follows the patterns recorded in `src/polymerhus/attack/hunting/CONTEXT.md`: the atomic store writes (#340), the bounded whole-file notes store (#341), the shared tool-contract base (#293), the phase-transition verbatims, the hunter memory store, the hunt store, and the inbox surfer and mover with the at-least-once marker.
It replicates the similar component and does not import another store's namespace.

The store write tool is a typed `BaseTool` with `extra="forbid"`.
The unit identity is bound at construction.
The write intent is the single `state` + `section` payload.
The tool description states the gate semantics and the next-state hint.

### 9.3 Prompt and hints

The modeller prompt is rewritten around the five states.
The phase hints are constants in the modeller state module.
The store tool response injects the hint.
The hints are:

| Gate written | Hint |
|---|---|
| `UNIT_TECHNICAL_SHARP` | Proceed to trust mapping: translate the interface agreements into trust agreements, then model dynamic-state trust. |
| `TRUST_MODELLED` | Proceed to assumptions: each assumption names an induced programming fault. |
| `TRUST_ASSUMPTIONS_WRITTEN` | Proceed to vulnerability citation: name the classes freely, then map them to the suite. |
| `VULNERABILITIES_WRITTEN` | Proceed to failure-mode deduction and the ranked threats; apply the drop rule. |
| `COMPLETED` | No hint. The model is published. |

The hint text is finalised in the implementation prompt pass.
The table shape and the injection point are fixed here.

### 9.4 Run record

The run record is the existing run row's stats JSON.
The keys in section 7.4 are fixed.
The run bootstrap writes the intake order and the exclusions before the first unit.
The accumulator updates after each COMPLETED write.
The crossing and blocked units are written when the halt fires.

### 9.5 Eval translation

Anything in the eval assessment artifacts and in the assessor and diagnoser prompts that refers to hunt configs is translated:

- `HuntConfig` -> threat payload.
- `specified` -> `ratified`.
- Hunt store -> threat model store.
- `hunt_id` -> threat dispatch id.
- `fault_class` -> web vulnerability class and fault.
- `rationale` / `research_direction` -> threat rationale and trust-model overview.

The eval fixtures, trial records, and challenge-location mapping are updated with the change.
The eval's hypothesis-verdict derivation via `derive_verdict` is disabled or replaced; the verdict-consumption workflow remains out of scope.
Model scoring stays outside the eval system.

### 9.6 Documentation

The change updates:

- The two modelling-notes documents are removed from production as standalone documents; their material is embedded in the modeller prompt. The files remain as historical design notes.
- `docs/design/domain-model.md`: add the unit threat model bounded context and its entities.
- `docs/design/evolution-paradigm.md`: a minimal citation only.
  It states that the phase-1 system now has a threat model feature with a different design model from attack-tree-based models.
  It states that the development of the attack-tree-based models should draw inspiration from the insights emerging from the use of the threat model feature.
- The `CONTEXT.md` glossary: update the stale D4 term and sharpen the threat model, threat payload, and phase-summary terms.
- The supersession notes listed in the impact map.

The G7 check stands: the accumulator is symbolic run state, not an orchestrator graph stage, so G7 needs no amendment.
`#166` and `#298` are closed upstream; their conditionals are moot.

## 10. Testing decisions

### 10.1 What makes a good test

Test external behaviour, not implementation details.
Drive the real store on a temporary project root.
Drive the real passive graph with injected observations.
Use a fake `exec` and a fake HTTP-history store at their contract boundaries.
Assert the persisted files and the run record, not private calls.
Keep every failure path fail-open and observable.

### 10.2 Seams

- The pure ordering function: live-edge count, tie-break, exclusion.
- The pure risk accumulator: weights, inclusive comparison, crossing unit, blocked unit.
- The pure workflow tracker: gate detection, monotonic state, forward jump, trail-only backward signal, hint injection.
- The store: merge, derived symbols, atomic write, move-aware write, threat-file emission, zero-threat consumption, completion checker.
- The tool contracts: `hunts_store`, `notes`, HTTP history, `exec`, skills.
- The prompt contract: the five states, the gates, the evidence discipline, the drop rule, the scoring ontology, the live-authority rule.
- The run lifecycle: intake freeze, exclusion, interleave, halt, resume, degraded unit, provider interruption.
- The eval translation mapping.

### 10.3 Prior art

Reuse the patterns and harnesses of:

- The hunting cache and store tests for the atomic and bounded writes.
- The store-write decision tests for the derived-symbol and coded-rejection discipline.
- The actor tests for the per-run session and the degradation breaker.
- The state-graph tests for the passive detect-and-push invariant.
- The isolated end-to-end hunting harness for the real skill and real store files.

### 10.4 Coverage shape

The suite must cover:

- The acceptance scenarios in the workbench section 6.
  The product-submission and file-upload ranking scenarios are replayed over the prototype units.
  If a replay is not feasible before the build, the outcome is measured in the post-build eval and recorded as a risk.
- Every gate's necessary-content check.
- The drop rule: retained vector, `none` threat, fundamental drop with the backward correction.
- The closure check: closed and unclosed assumptions.
- The ordering ties and the exclusion reasons.
- The halt at the crossing unit and the blocked unit.
- The resume from a stopped run.
- The zero-threat unit and the low-threat pause.
- The degraded unit.
- The role rename: no old role name remains in a live path.

## 11. Out of scope

- Surface recovery, recon, and analysis.
- The hunter pass redesign, the harness FSM, and the pod contract.
- The test-executor pod's internal threat.
- Model evolution and change-driven re-modelling.
- Alpha-omega (`#355`).
- Full CVSS base metrics (`#368`).
- The TBSG boundary-record vocabulary (`#371`).
- Model scoring in the eval system.
- The attack-tree compatibility.

## 12. Further notes

The workbench is the decision authority.
The workflow document is the workflow contract.
The tools ADR and the ordering-halt ADR are the two accepted ADRs.
The risk-scoring research note carries the scoring evidence.
The impact map carries the supersession ledger.

The design phase is closed.
The implementation work items are:

- The threat modeller rewrite and its store.
- The production hunter prompt work phase.
- The hunter harness FSM refactor.
- The test-executor pod contract refactor.
- The documentation and hygiene pass.

The tickets are cut from this spec set through `/to-tickets`.

## 13. Context dedup amendment (2026-10-23)

The shared decision record is `docs/design/hunting-context-dedup-2026-10-23-adr.md`.
The impact map is `docs/design/hunting-context-dedup-impact-map.md`.

The modeller changes are:

- The six state and section families remain the same.
  Their human projection is pinned to `ModelState`, `GATE_SECTIONS`, and `ModelSections` by tests.
- The prompt names the full 10-tool surface.
  `record_skill_lesson` is no longer hidden.
- The auth store is read-only.
  The `arm_exempt_surface` path no longer binds the write contract.
- The 5xx paragraph is a pointer to the shared target-front rule.
- The tool descriptions are shared constants.
  The modeller surface falls from 18,594 to 6,850 chars.
  Of that cut, 7,095 chars are shared description text and 4,649 chars are the auth-mode switch.
- The first human context is pinned through compaction.

The state, gate, and reference table generation remains a follow-up.
The current tests pin the prompt projection to the typed sources so it cannot drift silently.
