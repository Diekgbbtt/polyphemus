# Recon

Layer-0 descriptive attack-surface discovery.
This context observes a target from the outside and records what tools witnessed as a graph of typed L0 nodes; it never judges what any of it means (that is [Analysis](../analysis/CONTEXT.md)).
It also owns the pipeline that orchestrates discovery - Run, Job, Phase, Pod - which by operator ruling are elements of the recon pipeline and live here, not in a separate context.

Vocabulary derived from `docs/design/domain-model.md` (esp. §2.1-2.2, §5, §7); see also `docs/design/recon-pipeline-design.md`.

## The surface and its atoms

**Attack surface**:
The total set of loci at which a tester can present input to the target and observe a consequence.
Its irreducible atom is a locus where externally-controllable input crosses into the system - an Endpoint together with the Parameter or Header that carries the input - not "the application" and not a lone Endpoint.

**Layer 0 (L0)**:
The observed store: a claim here is descriptive, and its truth condition is "a tool witnessed this feature of the surface at a moment in time".
_Avoid_: L1, the judged store (that is Analysis).

**L0 node**:
A typed node in the observed store, drawn from a small fixed label set: `Domain, Subdomain, IP, Port, Service, DNSRecord, BaseURL, Endpoint, Parameter, Header, Certificate, Technology, Secret, Traceroute, ExternalDomain`.
Each exists only because a tool witnessed it.
_Avoid_: asset (loose synonym; prefer the specific label).

**Endpoint**:
A reachability fact - a path that responded.
Input-carrying capability is not on the Endpoint itself but on the Parameter and Header nodes that hang off it.

**profile** (`webapp` / `restapi` / `graphql_api`):
A per-Endpoint classification of the surface an Endpoint exposes, derived from its own httpx-observed content-type (+ host-label / GraphQL-path signals) by `noise_filter.classify_profile`.
Every produced Endpoint is profiled by the `httpx_reprofile` pass (D16 per-endpoint split, workflow #28), not just BaseURL roots - so an API mounted under a `webapp` root is visible.
`BaseURL.profile` is the backward-compatible mirror of its root `/` Endpoint's profile.

**API scope** (kiterunner):
The evidence-derived API-root prefix a fuzzer is scoped to, computed by `api_scope.derive_scan_targets` from a host's `restapi` Endpoint paths (last api-noun cut, versions left as fuzz-space, parent-dir fallback). Not a naming classifier - the gate is the content-type `profile`; the noun set only picks the cut depth.

**Parameter / Header**:
The input-carrying atoms that hang off an Endpoint; they, not the Endpoint, express that a user-controllable input reaches a sink.

**Service (L0)**:
A network service discovered on a Port (the descriptive node label).
_Not to be confused with_: the L1 `Service` (a reconstructed business target), which is an entirely separate concept owned by Analysis.

**Secret**:
An L0 node for credential-like material witnessed on the surface (e.g. read out of a JS bundle).
_Not to be confused with_: a DataItem (Analysis), which is a judged logical data record, not a raw witnessed string.

**Observation**:
An adversarial natural-language insight the triager reads out of tool output - deliberately NOT a restatement of a witnessed primitive (an HTTP status or an SSL cert is a primitive, not an Observation).
Despite the name it is a *low inference*, not a pure observation in the epistemic sense; genuine directly-witnessed facts are the typed L0 nodes themselves.
_Avoid_: finding, primitive, restatement.

## The pipeline

**Project**:
The operator-scoped unit of work: a target, its scope, the free-text `operator_kb` business framing, and settings.
It is the boundary at which identity and idempotency currently hold.
_Avoid_: engagement, target (target is the thing under test, not the record).

**Seed** (`target_seed`):
The single string that names what a Project probes, seed-type-agnostic (D-HS): a domain (`example.com`, `*.example.com`) or a bare IPv4 (`93.184.216.34`).
`resolve_seed` reads it, falling back to the deprecated `target_domain` alias so already-persisted projects still launch.
_Avoid_: target_domain (the legacy, domain-only name).

**Scope mode**:
The shape `parse_scope` gives a seed, driving which jobs run: `wildcard` (a zone, discovery runs), `exact` (one host, discovery suppressed), or `host` (a bare IP - discovery and the passive harvesters suppressed, the IP probed directly).
An IP's engagement root is an `IP` node, never a `Domain`; the whole web-discovery chain then unfolds from httpx's `BaseURL`s exactly as for a domain (D-HS).
_Avoid_: treating a mode as an asset type (it is a routing decision, not an L0 label).

**Run**:
One execution of the pipeline over a Project's phase plan, keyed by `run_id`.
Re-running re-derives the graph rather than duplicating it.
_Avoid_: scan, session.

**Phase**:
An ordered stage of the phase plan whose jobs run before the next stage begins; each phase seeds the next from the assets the prior phase produced.
_Avoid_: stage, round.

**Phase barrier**:
The hard boundary between phases: every Job in a phase (and all its pods) completes before any Job in the next phase starts, bounding peak concurrency to a single job's pods.
_Avoid_: sync point, gate.

**Job**:
A single tool-execution specification (`JobSpec`: a tool, a skill, a command template, what it consumes and produces) run within a phase, fanned out over its input population into pods.
_Avoid_: task, step.

**Pod**:
The per-input-asset execution unit that runs one Job against one input asset, invokes the tool, and emits asset deltas and Observations.
_Avoid_: worker, container (a Pod is the graph-runtime unit, not a k8s pod).

**Asset delta**:
The unit of L0 write a pod emits: a typed node with identity, props, and edges, proposed for the curator to merge.
_Avoid_: patch, diff.

## Actors and authority

**Curator (L0 sole-writer)**:
The single module (`src/polymerhus/recon/domain/curator.py`) authorised to write the L0 store: it enforces identity, stamps provenance, validates every label and edge against a fixed allowlist, and is the boundary between "proposed" and "true in the graph".
_Avoid_: writer, persister.

**Sole-writer**:
The principle that each store has exactly one authority that turns a proposal into a fact; it is what lets provenance-on-write and idempotent identity be guarantees rather than hopes.
The L1 counterpart is the `l1_curator` (Analysis).

**Triager**:
The LLM proposer role that reads raw L0 tool output into adversarial Observations; it holds judgment but no write authority.
STATEFUL as of #94: it runs on a per-concurrent-pod session (`PodSession`, `recon/domain/pod.py::pod_session`), keyed by the pod's `(phase, tool, input-asset)` discriminator so several pods of one run never share context; the triager node binds the session on a ContextVar (`app/llm/session.py::stateful_turn`).
_Avoid_: analyst, classifier.

**Configurator**:
The role that resolves a Job's command for a target; a `deterministic` template by default, or an `agent` mode.
STATEFUL as of feat/async-actor-agents: the pod graph's configurator node consults a per-concurrent-pod `configurator` session (`PodSession`, keyed like the triager) over the orchestration steering signals (`extra["steering"]`), decides the pod's `rate_profile` (throttling moved HERE from the job-level `decide_pod_selection`), and merges it before the command template is filled; fail-open (never a pod failure) and consulted once per pod even across gate retries.
_Status_: registered `session` (`LLM_MODEL_CONFIGURATOR`).
_Avoid_: planner.

**Job orchestrator**:
A resumable `session`-mode role (`role_id=job_orchestrator`) validated at app boot.
Since feat/async-actor-agents it runs as a per-run MAILBOX actor
(`orchestrator_agent.py::ReconOrchestratorActor`): one `run_session_agent` on the
run's `OrchestratorSession` thread, fed each phase's steering signals and replying a
structured `RoutingDecision` per phase, so its checkpointed memory carries the
steering reasoning across the run's phases. `decide_routing` remains as the sync
thin wrapper seam (the injected/rollback path).
_Avoid_: planner.

**Operator**:
The only human, and the source of intent the system is blind to by design: supplies the target, scope, `operator_kb` framing, and settings.
Deliberately kept blind to the target's true identity (it analyses `soupmarket.shop` without being told it is Juice Shop).

## Invariants owned here

**Fail-open**:
One bad delta never aborts a batch and a missing collaborator degrades rather than crashes; the accepted cost is that a dropped item is silently lost with only a log line.
_Avoid_: fail-safe, fail-closed.

**asset_context**:
The context string threaded end-to-end into every pod for the designed-not-built context-memory scaffold; today always the empty string.
_Status_: scaffolded, not built.
