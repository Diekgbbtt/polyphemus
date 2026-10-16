# Analysis

Layer-1 interpretive abstraction.
This context reconstructs, from the observed L0 attack surface, a judged model of what the target *is* - its business targets (Service) and its shared mechanisms (System) - and anchors every judgment back onto the L0 evidence that licenses it.
Nothing here is witnessed; every node is an analyst-role LLM's proposal that the L1 sole-writer turns into a fact.
(The logical-data plane - `DataItem`, `SURFACES_AT`, `CONSUMES`/`PRODUCES` - was REMOVED 2026-10-15; see the RETIRED entries below and `docs/design/drop-data-modeller.md`.)
This context is a physically independent module at `src/polymerhus/analysis/` (extracted from under `recon/` in the 2026-07 `src/` restructure). Its only structural tie to recon is the published L0 vocabulary in `recon.domain.types` - the anti-corruption seam.

Vocabulary derived from `docs/design/domain-model.md` (esp. §2.2-2.6, §4, §6); see also `docs/design/l1-domain-model-catalogue.md`.

## Trunk scope

This context is the L0-chunk-sourced pipeline.
Recon pushes one job-keyed chunk per producing job (`chunking.chunks_for_job`); the supervisor runs a chunk-major schedule of the two proposers (assigner, mechanism-typist), and each proposer reasons over the chunk's admitted slice plus the live L1 inventory.
The service-sourced pipeline (a per-Service reasoning workflow with `graph_view`/HTTP-history tools and episodic memory) is a separate experiment and does not live on this trunk; see `docs/design/l0-l1-pipeline-split-adr.md`.

## The stores and the crossing

**Layer 1 (L1)**:
The judged store: a claim here is interpretive, and its truth condition is "an analyst-role LLM judged this to be the case from evidence".
It is physically co-resident with but logically separate from L0, shares no identity keys with it, and is reachable from L0 only across the cross-layer edges.
_Avoid_: L0, the observed store (that is Recon).

**Proposal**:
The unit an analyst-role LLM emits: an L1 node or edge that deliberately omits provenance and identity, which the write boundary injects and guards.
L1 outputs are proposals, never readings, because no tool ever emits a Service.
_Avoid_: reading, fact (a fact is what the sole-writer has committed).

**Cross-layer edge**:
An edge from an L1 (judged) node down onto an L0 (observed) node, anchoring an inference to the observations that license it; the L0 target is always `MATCH`ed, never `MERGE`d.
The live ones are `AGGREGATES` (assignment) and `EVIDENCED_BY` (reconcile); `SURFACES_AT` is legacy (RETIRED below).

**AGGREGATES**:
The assignment edge from an L1 `Service` to an L0 node, carrying the judgment envelope: "I judge element e belongs to service S, on this evidence".
It is the load-bearing L0/L1 hinge.
_Avoid_: contains, owns, has (membership is N:M and non-possessive).

**SURFACES_AT** - RETIRED 2026-10-15 (`docs/design/drop-data-modeller.md`):
Formerly the cross-layer edge from an L1 `DataItem` to the L0 Parameter / Header / Secret where that logical item appeared on the observed surface.
Nothing writes it anymore; legacy graphs may still carry it (read-only).

**EVIDENCED_BY**:
The cross-layer edge from an L1 `System` to the L0 node that fingerprints it (a `Server:` header, a cookie); carries provenance and timestamps only.

**Application Overview**:
The operator_kb `## Overview` paragraph - the macro description of the deployed solution: its product category, deployment model, and audiences.
It is a SKELETON ATTRIBUTE, not a graph node, so it is carried as `settings.application_overview` and surfaced on the inventory dict (`read_l1_inventory`), never a `:L1*` label.
Each proposer prepends it (`pod.overview_block`) to its human message, so a Service is reasoned inside the application it lives in rather than from its contract alone.

**L1 graph block**:
The current L1 graph posted into the Assigner's volatile human message (`pod.l1_graph_block`): each Service with its `service_contract`, each System as `kind[:disc] :: description {attributes}`, and the typed `Service -[REL]-> System` edges with role/realm/order.
It is built from the per-dispatch `read_l1_inventory` read (`system_details`, `edges`), so it is rebuilt every dispatch and tracks the run as it concretises more linked systems.
It folds in the FR-INVENTORY identity-reuse discipline, so it REPLACES `pod._inventory_block` in the Assigner prompt (`_inventory_block` survives for the Bootstrapper).
The graph is POSTED as a prompt block, never exposed as a `graph_view` tool: a previous graph_view-capable Assigner degraded quality and bloated context (retained decision, operator ruling 2026-10-16).

## The tripartition

**Service (L1)**:
A **target** - a thing an attacker wants to break, individuated by business purpose (the checkout, the sign-in), keyed on `(project_id, business_function_slug)`.
A Service *claims* surface elements by asking "what business function does this serve?".
_Not to be confused with_: the L0 `Service` node (a network service on a port), which is a Recon term.
_Avoid_: feature, module, component.

**System**:
A **mechanism** - a cross-cutting technical capability many targets lie on (a WAF, a CDN, an API paradigm, the auth machinery), keyed on `(project_id, kind, discriminator)`.
A System *overlays* elements that share a mechanism regardless of business function.
_Avoid_: infrastructure, layer.

**Membership direction**:
The single test that decides Service versus System: partition-by-purpose is a Service, overlay-a-shared-mechanism is a System.

**Mechanism-as-System (the mechanism-classification principle)**:
The resolved rule that a mechanism classification (how the UI renders, which API paradigm, which auth method) is a property of the mechanism-System, never of the target-Service that uses it.
(Resolved: the operator corrected this twice; storing `rendering_model` on a Service is a category error, so those handles are System-side, reached by an edge.)

**WebPresentation**:
The System `kind` for the web-presentation channel: the navigable `text/html` PAGES a Service renders (never its API/XHR/JSON responses).
It is PER (service, rendered-page CLUSTER), not a singleton (#53, operator-ratified 2026-08-01): pages are grouped by rendered similarity (title/structure/size) into clusters - a templated product-page set or a single not-found page is ONE cluster, not many - and each (service, cluster) is one node.
Its `discriminator` is `<business_function_slug>::<cluster>`, nesting per-page within the per-service key (superseding the service-only discriminator of the anatomy path, #41); the cluster's member page paths ride a `pages` prop (the location index the downstream agent uses to find where a Service is exposed).
It still carries `rendering_model` (CSR/SSR/...) and `navigation_model` (SPA/MPA/Hybrid) as two ontologically independent props (Phase-B deepening).
(Resolved: replaced the deleted `RENDERED_BY` edge and the `RenderingSystem_*` kinds; a Service reaches it via `EXPOSED_VIA`, exactly as it reaches a REST or GraphQL API. For a CSR+SPA target the served pages are one shell, so it stays ONE node carrying its client-side `pages`/route refs until steel DOM-delta (#51) supplies distinct per-view evidence.)

**kind**:
A System's intrinsic identity attribute, validated against the fixed `SYSTEM_KINDS` constant.
(Resolved: the `SystemKind` catalogue *node* of the older spec no longer exists; kind is an attribute, not a node.)
_Avoid_: type, category, SystemKind (the node).

**DataItem** - RETIRED 2026-10-15 (`docs/design/drop-data-modeller.md`):
Formerly a logical data record (a session token, an order, a `sales_figure`) as a first-class L1 node, the Tier-1 trust locus.
Nothing writes it anymore; legacy graphs may still carry it (read-only).

**Trust boundary** - RETIRED with `DataItem` (same date/ADR):
Formerly where trust changed hands - a `CONSUMES` edge from a service to a data item it did not produce.
Unmodelled now; the impactful faults still live in shared mechanisms, not inside a single target.

**Trust assumption** - RETIRED with `DataItem` (same date/ADR):
Formerly the falsifiable predicate a consuming service held about data it did not produce, carried on a `CONSUMES` edge, and the one persisted seed instance of the phase-3 fault-hypothesis.
Phase 3 will need a new seed; none is persisted now.

## Intra-L1 edges

**EXPOSED_VIA**:
The edge from a Service to the System that presents it (WebPresentation, a REST or GraphQL API).

**CONSUMES / PRODUCES** - RETIRED with `DataItem` (same date/ADR):
Formerly the data-flow edges between a Service and a DataItem.
Nothing writes them anymore; legacy graphs may still carry them (read-only).

**AUTHENTICATED_BY / AUTHORIZED_BY**:
System edges binding a Service to its authentication and authorization mechanisms (kept distinct: who you are versus what you may do).

**DATA_RELATIONSHIP edge** - RETIRED with `DataItem` (same date/ADR):
Formerly the edge between two DataItems whose type was the uppercased kind from a fixed six-value allowlist.
Nothing writes it anymore.

## The reasoning vocabulary

**Judgment envelope**:
The `{status, evidence_refs, provenance, ts}` bundle carried on the `AGGREGATES` assignment edge, even though the MVP only ever writes `status="committed"`.
(The graded `confidence` member was REMOVED 2026-10-15 with its withholding gate; see `docs/design/drop-aggregate-confidence.md`.)

**Provenance**:
Who or what made a claim: `prov_job` / `prov_model` / `prov_prompt_id`, stamped by the sole-writer and structurally forbidden to the proposer.
The concept that lets "an LLM said so" and "a tool measured it" be different kinds of fact in one graph.
(Also stamped by the L0 curator in Recon; defined here as it is core to weighing L1 judgments.)
_Avoid_: metadata, source tag.

**Confidence** - REMOVED 2026-10-15 (`docs/design/drop-aggregate-confidence.md`):
Formerly the strength of a judgment, carried in the envelope and acted on for assignment (`withhold_below_bar` under `ASSIGN_CONFIDENCE_BAR`, swept by `evaluation.bar_sweep`).
Assignment is admit-all now: every structurally-valid aggregate is written, and precision rests on prompt discipline plus the structural gates.
_Status_: no L1 edge carries a graded judgment.

**Evidence**:
The L0 nodes an L1 node's cross-layer edges anchor to; pulling the evidence defeats the judgment.
An inference is only as good as the observations it is anchored to.

**Inference**:
A claim about structure that was never directly visible and had to be reconstructed ("these endpoints constitute the checkout service"); the whole of Layer 1 is inference.
_Not to be confused with_: an Observation (Recon), which is a *low* inference, and a hypothesis, which asserts a fault.

**Escalating epistemic ladder**:
The three rungs observation -> inference -> hypothesis, each weaker, more defeasible, and more adversarially valuable than the one below: an observation is witnessed, an inference reconstructed from observations, a hypothesis a falsifiable fault-claim built on inference.
The bottom two rungs are persisted (L0 observed, L1 inferred); the top rung is reached only in phase 3 and is never written to the graph.
_Status_: designed / provisional framing - a term from the ontology (`domain-model.md` §2.2/§2.6), not settled code vocabulary.

**Staleness**:
The temporal projection of identity: `first_seen` / `last_seen` datetimes say when a fact was last confirmed, letting the stores be re-derived non-destructively rather than migrated.

**Temporal identity**:
Identity carried across time - "this is the same thing" - the companion `last_seen` records when it was last true.

**Idempotent identity (identity ⊥ membership)**:
The keystone principle that a unit is keyed on what it *is* (business function, mechanism kind), never on what it *contains*, and every write is an idempotent MERGE on that key.
(Also enforced by the L0 curator; defined here as the L1 keying rule.)
_Avoid_: dedup key, primary key.

**Stale pool**:
Not a structure but a derived query: the L0 assets with no inbound `AGGREGATES` edge - the ledger of "seen but not yet judged".
Its size is an analysis-coverage signal; an *empty* stale pool is ambiguous and was empirically a negative signal (a stronger model over-assigning noise).

**Convergence**:
The property that re-running the analyser over the same surface reaches a stable graph, guaranteed by idempotent MERGE on identity.

**Defeasibility**:
The ability to withdraw a judgment; only partly modelled.
The MVP is monotonic (append-only via MERGE); reasoning-time retraction is absent and service-splitting is deferred.
_Status_: partially modelled - reasoning-time retraction not built.

**Typed spine**:
The enum-and-edge skeleton of every L1 unit, with natural-language characterisation hung off typed handles; the symbolic layer reasons over the spine, the creative planner consumes the prose.
Retyping it is a one-way door.

## Actors

**Analyser**:
The whole-model proposer role that reconstructs the L1 Service/System/DataItem model.
AMENDED (#48, 2026-07-30): the "run in two passes - an assignment pass and a dedicated data-modelling pass" description is RETIRED with the monolith.
The analyser is now the chunk-fed, per-responsibility proposer decomposition behind the supervisor - `Assigner` (AGGREGATES) and `TechnicalSystem`/mechanism-typist (Systems) - each a standalone A.1 proposer dispatched per chunk (see "Proposer decomposition" below).
_Avoid_: analyst, modeller.

**l1_curator (L1 sole-writer)**:
The single module authorised to write the L1 store: enforces identity, stamps provenance, validates every label and edge type against a fixed allowlist, and never `MERGE`s an L0 node.
The L1 counterpart of the Recon `curator`.

**Bootstrap**:
The pre-analysis step that seeds the operator KB so an analyser run starts from a framed target rather than the bare surface (the bootstrap-first e2e discipline).
The redesigned Bootstrapper (#26) elicits the skeleton in TWO calls - a free-text 5-step reasoning (architect-decompose -> expand -> hypothesis+KB-ground -> critical-withhold -> decide) then a structured shell extraction - taught by 2 divergent-domain few-shot exemplars, and is FAIL-CLOSED: on retry-exhaustion or a write failure it BLOCKS the analysis rather than degrading to an empty skeleton (an empty KB stays a valid linchpins-only proceed).

The Bootstrapper is a pre-analysis PHASE, not a supervised analyser proposer: it runs once, ahead of the analysis, and is triggered over the app API (`POST /projects/{id}/bootstrap`), which ingests the operator's knowledge and returns the skeleton counts - or a 503 carrying the fail-closed block.
Its system message is TWO layers: a stable base prompt in code (identity, pipeline position, the output-field contract - the WHAT) plus the operator-tunable reasoning discipline in `analysis/prompts/bootstrapper.md` (the five stages, service-contract craft, critical withholding - the HOW).
WHICH TURN the discipline rides in is configurable (`BOOTSTRAP_PROMPT_CONFIG`, `_PROMPT_CONFIGS`) and was settled empirically, not by argument: the default `skill_in_prompt` puts it in the USER turn beside the task, which measured best on both breadth mean and breadth floor over 15 live runs (operator-ratified 2026-07-27; see the agent-configuration eval below).
The base layer is always the system message in every arm.

**Service contract**:
A brief functional profile of a business-function Service - what it DOES and what it OWNS - written in the application's own domain nouns and action verbs, and persisted as the `service_contract` prop.
Written by the Bootstrapper for every Service, and by the Bootstrapper alone since #34 D4 retired Assigner minting; it is the PRIMARY evidence the cross-layer Assigner consumes, matching the nouns and actions in an observed endpoint path against it to judge ownership.
It must DISCRIMINATE between business functions (a profile true of every Service is useless to a matcher) and must contain NO path, URL, route or parameter name: the operator KB states none, so a path in a contract is a model's guess that would then be read as evidence.
Its richness is bounded by the KB's own vocabulary - a thin KB gets a thin honest contract.
_Not to be confused with_: `label` (an NL display name) or `salience` (a one-line adversarial summary), both Phase-B concerns the Bootstrapper leaves empty.

**Agent-configuration eval** (`evaluation.py` + `tools/eval_bootstrapper.sh`):
The comparative harness for judging one analysis agent's CONFIGURATION against another - prompt arrangement, exemplar set, reasoning verbatim.
It exists because these agents are non-deterministic (16 and 21 Services from an identical KB on consecutive runs), which makes a single run uninformative and a heuristic pass-bar actively misleading: a bar loose enough to absorb the variance cannot catch a regression, and one tight enough to catch it fires on healthy runs.
A prompt edit once collapsed breadth 25/16/20 -> 13 while every unit test stayed green.
**Breadth is the primary axis and is judged COMPARATIVELY** - arms are ranked against each other over repeated runs, and nothing in the harness encodes a target count or a threshold.
**Granularity is NOT a criterion**: it has no measure this codebase trusts, so it rides along as a qualitative note (how many Services cover one narrated journey) that nothing ranks on.
Breadth is never read alone - the integrity metrics (contract coverage, System count, Service->System edges, role-vocabulary size) travel in the same row, because an arm can buy Service count by losing something else: one live arm matched the best breadth mean while dropping an AuthorizationSystem's entire role vocabulary, and a count-only metric would have called it the winner.
Runs drive the REAL system through the faithful entry path (API -> use-case -> agent -> sole-writer -> Neo4j), never the agent in-process, because the entry path is where an entry-path defect lives.
Every evaluated project is LEFT IN THE GRAPH (start-only wipes) - a teardown wipe deletes the artifact the operator needs to inspect.
GENERAL by construction: `run_matrix` / `compare` take an injected `invoke_fn` + `read_fn`, so another analysis proposer adopts the harness by supplying its own pair and may extend `skeleton_metrics` for the slice of L1 it owns; the Bootstrapper is the first adopter.
The **Assigner is the second** (`evaluate_assigner`), and it shows what agent-agnostic has to mean: its primary axis is assignment VOLUME, which - unlike breadth - must never be read as a score, because this agent's measured failure is over-production. So `compare` takes the primary key and integrity columns as parameters, and the Assigner supplies `ASSIGNMENT_INTEGRITY_KEYS`, in which a LARGER stale pool is a POSITIVE signal.
CAVEAT (2026-07-29): its `out_of_inventory_rate` / `unresolvable_rate` columns read `0.0` because `AssignmentStats` is persisted nowhere and `read_assignment` reads the graph. Read them as **not measured**, never as zero - the real values exist only in per-chunk logs.
The live targets these runs execute against are held in the eval dataset `tests/e2e/fixtures/eval-targets.yaml` (each target's `operator_kb` bootstraps the L1 skeleton the harness then measures).
_Not to be confused with_: the assertion catalogues (fixed contract/walkthrough predicates that pass or fail), or the #19 regression oracle. This ranks configurations; it never passes or fails one.

**Proposer-reasoning pattern**:
The reusable prompt fragments every analyser proposer composes (`proposer_reasoning.py`): a role/goal header, a chain-of-thought scaffold, a few-shot CoT block, and a bounded retry - the "optimal prompt pattern" (system-prompt role design + CoT + few-shot + structured extraction) minus the example-pollution pitfall (no hardcoded domain slugs).

**ServiceShell / SystemShell**:
The Bootstrapper's call-2 elicitation template: a per-Service / per-System shell whose phase-A.1 attributes are PRESENT but EMPTIED (bootstrap fills only slug + exposure + service_contract, or kind + discriminator), mapped down to `L1DeltaBatch` for the sole-writer (the empty A.1 slots are not persisted - absence means not-yet-filled).
A System shell whose `kind` falls outside the controlled vocabulary is dropped at this seam with a warning and a count, rather than silently swallowed downstream by the sole-writer's typo-guard.
The 3 forced linchpins are the identify/authenticate/authorize triad (IdentificationSystem, AuthenticationMechanism, AuthorizationSystem); the AuthorizationSystem alone keeps a shallow KB-sourced role/realm vocabulary, with no edges.

**Service linchpin (gap-3, ratified 2026-07-26)**:
A BROAD umbrella business-function Service the Bootstrapper guarantees on the skeleton so a near-universal, bug-dense surface is never dropped (observed live on the moodique KB, where sign-in/register/password-recovery was absorbed into the AuthenticationMechanism System and lost).
It is always the umbrella, never a leaf: phase-A.2 service decomposition later unpacks it (sign-in -> sign-in-sso / sign-in-credential; account-management -> address / payment / profile management).
The pre-auth trio (sign-in, register, password-recovery) is HARD-forced as `public`, mirroring the system linchpins; every other umbrella (account-management, sign-out, notifications, admin-console, ...) is PROMPT-PRIOR (carried only when the KB grounds it, since a headless / minimal target legitimately lacks it); a linchpin is always a solution-profile business function (sign-out), never a technical System concern (session lifecycle).
The set is a growing single-source constant (a §7 extension point) that feeds BOTH the shells_to_batch forcing AND the prompt text, exactly as SYSTEM_KINDS feeds the writer and the vocabulary prompt.
Guarantee is by FORCING only; the prompt render is retained-not-wired because pushing the umbrellas through the reasoning prompt globally coarsened breadth (a live eval collapsed 25/16/20 Services -> 13).
_Not to be confused with_: the linchpin auth Systems (mechanisms, not targets).

**Curation / reconciliation**:
The curation-time repair authority (`merge` / `delete` / `relabel` / `rehome`) that corrects the L1 graph with a later global pass.
It is repair-after-the-fact, not reasoning-time retraction.
_Avoid_: cleanup, migration.

**Index-card**:
The token-light projection of an L1 unit that reasoning navigates natively, crossing into the heavy L0 detail only at concretisation (traversal-then-fetch).
_Avoid_: summary, snapshot.

**Sweep**:
The pass that derives the stale pool (the L0 assets with no inbound `AGGREGATES` edge).

**Anatomy skills**:
Dedicated procedures (`webpage-profile`, `authorization-pyramid`) that *classify* spine slots that cannot be read off the surface, emitting the triple typed-classification -> spine slot, evidence -> Observation, deeper probe -> backward-recon request.

**Auditor**:
The checker that vets proposals *before* they are written (a noise classifier, an identity-reuse check), moving the maker/checker discipline upstream from repair to prevention.
It is the FIXED stage after every proposer in the control-plane pipeline (never itself dispatched), not one of the routed proposers.
_Status_: the hollow stub exists as of increment 0 (score-and-annotate mode is increment 3, `AMV-16`); the natural home for the orphaned confidence and absence policies.

## Control plane (the redesigned analyser, increment 0)

The redesigned analyser dissolves the two-pass `Analyser` into responsibility-scoped proposer agents behind a central **supervisor**, exchanging typed messages.
Increment 0 (`#22`, realising `#20` increment 0) builds the control plane with HOLLOW agents behind the `analysis.supervisor_enabled` flag; the terms below are its ubiquitous language.

**Supervisor**:
The central node that holds a `schedule` of `AgentDispatch`es and sequences through them one super-step at a time, routing to a proposer with `Command(goto=role)` and reading back the `StepReceipt` outcome.
It is born async-native (async compile + `ainvoke`).
_Avoid_: orchestrator (that is the Recon term), controller.

**AgentDispatch**:
The immutable work order the supervisor sends DOWN to a proposer: `dispatch_id`, `role`, `phase`, `mode`, and exactly one of `chunk` / `sweep_cursor` (or NEITHER, for the slice-less bootstrapper / anti-cluttering roles).
Wraps the existing shapes by composition; carries routing intent, while `Command(goto)` carries the routing itself.

**ProposalEnvelope**:
The single-step baton passed across `proposer -> auditor -> curator`.
Carries SEPARATE optional cargo (`deltas` / `anatomy` / `curation`) - never a `Union`, because the mechanism-typist emits both `deltas` and `anatomy` - plus the `verdicts` trail and a `status`.
_Avoid_: proposal (that is the un-enveloped LLM output), message.

**StepReceipt**:
The outcome a proposer's step yields UP to the supervisor: `status` in `{written, empty, degraded}` + `WriteCounts`.
The supervisor sequences on this outcome, NEVER on the (already written and discarded) batch.

**inflight baton / receipts trail**:
`inflight` is the current `ProposalEnvelope` on the supervisor state (last-write - one logical writer per sequential super-step).
`receipts` is the ONE reducer channel, merging `StepReceipt`s with dedup-by-`dispatch_id` (the state-level mirror of the idempotent `MERGE`).
There is NO accumulated-proposals channel: the live graph is the accumulator.

**SupervisorState**:
The supervisor's LangGraph state - `project_id`, `run_id`, `schedule`, `dispatch`, `inflight`, `steer` (all last-write) plus the `receipts` reducer channel.

**Async-runnable checkpoint (increment 2a)**:
The point at which the async supervisor runs REAL work and produces the same `AnalyserExport` as the legacy pod.
A proposer body may return an `L1DeltaBatch` that rides the envelope; the curator gains a `write_fn` seam and, given a non-empty batch, writes it through the sole-writer (system-stamped provenance) and emits `StepReceipt(status="written")` with real `WriteCounts` (fail-open to `degraded`).
The driver opens an `AsyncPostgresStore` (`setup()`) alongside the `AsyncPostgresSaver`, and attaches the #18 Langfuse callbacks + a correct session id, flushing at run end (observation-delivery guarantee: `docs/design/observability-delivery.md`).
2a wraps the LEGACY two-pass as one transitional `assigner` node (output-identical); the per-responsibility, chunk-fed decomposition is increment 2b.

## Proposer decomposition (increment 2b)

The legacy two-pass analyser monolith dissolves into responsibility-scoped proposers, each consuming a `Chunk` narrowed by its own admission set and writing through the sole-writer. Built as standalone slices (flag OFF) then wired, and fully retired in #48.

All two chunk-fed proposers are **STATEFUL session agents as of #94** (`agent_mode="session"`), and **reset-per-chunk as of the 2026-10-14 context-lifecycle change**: `assigner` / `mechanism_typist` run their structured turn via `app/llm/session.py::stateful_turn` on the ONE per-(RUN, ROLE) `AnalysisSession(run_id, role_id)` thread, which the seam resets to empty at each new chunk (`proposer_turn.session_invoke_fn` resets on a new `proposer_batch(chunk.chunk_id)` scope), so the turns WITHIN one chunk share the agent's memory (the reflection is the extraction's context) while the NEXT chunk starts from the initial system prompt + its fixed human messages instead of resuming the previous trail. The stable thread identity is what the provider prefix cache and the observability/runtime contract key on. The per-batch discriminator is the chunk-boundary signal carried by a `proposer_batch(chunk.chunk_id)` scope the proposer body opens around its invoke chain (`analysis/proposer_turn.py`) - a scoped ContextVar, so the `(messages, *, schema, system_prompt)` invoke contract is unchanged; an unscoped caller keeps its trail, preserving the observability/runtime contract. The shared process-wide pooled checkpointer (`app/llm/checkpoints.py`) is the memory store. The one_shot roles (bootstrapper, anatomy, curation, sweep, anti-cluttering) externalise their reasoning to the graph and stay on `invoke_role`.

**Constant request shape (2026-10-10 cache experiment):** every turn of a proposer role binds the SAME structured tool. The reflection (prose) turn binds the role's `L1DeltaBatch` tool through the seam's `tools=` while keeping `response_format` prose; the extraction turn supplies the same tool through `response_format`. Before this the reflection bound NO tool and the extraction bound one, so `data_modeller`'s strict `P,S,P,S` schedule toggled the tool set every call and the provider prefix cache never matched (`cache_read=0`). `mechanism_typist`'s `P,S,S` shared an `S,S` tool set and cached, which was the asymmetry that named the fix.

Since **#187** both build their turn through ONE seam, `analysis/proposer_turn.py`: the per-run thread, the role's #95 compaction middleware, the run-correlation tag, the project usage scope, and the role's OWN prompt. A proposer can therefore never be built with another proposer's prompt - the role_id selects all of it.

**Prompt delivery (load-bearing):** the role prompt rides the `system_prompt=` binding of `create_agent`, NOT a `SystemMessage` in the turn's messages. The agent factory prepends it ephemerally at each model invocation and never writes it into the checkpoint state, so the trail carries only the volatile task and the request's leading block is byte-identical on every call. Re-adding it as a trail message instead stacks a fresh copy per call at a shifting position, which is what produced the `mechanism_typist` quadratic input growth. This is the client half of the gateway's cache contract (`llm-gateway-100-decisions.md` D8). Reasoning: `docs/design/converged-agent-turn-adr.md`; the reusable rule: `statefulness-pattern-matrix.md` OUTLIER-5. The one-shot legacy leg (`prepend_prompt`) heads a message list with the same prompt at the same position, so the request does not depend on which leg a call site takes.

**Assigner** (built, #8/#34/#30; HTTP-history surface R-A1..R-A3,
`docs/design/assigner-http-history-surface-adr.md`, superseding the
adjacent-surface D-A2/D-A4 for this role):
Sole owner of the `AGGREGATES` hinge: high-precision classification of an observed `Endpoint` onto an EXISTING Service. A.1-only - no minting, no re-assignment, no retraction.
The chunk is the slice recon most recently collected and stays the unit of work AND the scope of judgment; before judging, the assigner MAY read the recorded transactions behind the slice through the HTTP-history pair (`search_http_history` / `get_http_artifact`) - disambiguation, confirmation, AND an adjacently promising endpoint's fuller response (one endpoint often embeds several features, so a minimally promising surface is worth a read - while deep technical understanding stays the mechanism-typist's ownership). The recorded-response read is the whole widening seam, kept central; there is no `graph_view` roam on this turn, and a neighbour the slice does not carry stays a hypothesis, never an aggregate.
The inventory block re-read live at every chunk dispatch is the deductive target: the assigner reasons FROM the observed surface TO those listed identities.
Its first human message POSTS the L1 graph block (`pod.l1_graph_block`): the Services with contracts, the Systems with descriptions/attributes, and the typed Service->System edges, rebuilt every dispatch from the live `read_l1_inventory` read. The graph rides the prompt; there is no `graph_view` tool on this turn (retained decision - a graph_view-capable assigner degraded quality, operator ruling 2026-10-16).

*Contracts.* In: a `Chunk` narrowed by `admit_for_role` to `Endpoint` alone, plus the live L1 inventory with its `service_contract`s (the primary routing evidence). Out: `L1DeltaBatch{aggregates}`, each `AggregatesProposal{service_slug, l0: L0Ref, evidence_refs}`. Writes only through `l1_curator.write_aggregates`.

*Prompt.* TWO layers, the Bootstrapper's split: the role verbatim in code (identity, the aggregates-only contract, the `l0.identity` shape - the WHAT, which must hold with no prompt file) plus `analysis/prompts/assigner.md` (the no-owner null hypothesis, the differential over candidate owners, discriminating evidence - the HOW). The shared analyser skill was never a fit here: it addresses a generalist proposer and instructs the System and data modelling D4/D18 forbid this role (the #30 per-role retirement).
`ASSIGNER_PROMPT_CONFIG` selects; **`skill` is the default** (operator-ratified 2026-07-29), `baseline` a byte-identical rollback. The default was NOT earned on measurement - the comparison was confounded by inventory size (23 vs 11 Services) and supports only "no regression".
The system half is byte-stable so the provider prompt-cache survives a run; inventory and chunk ride the volatile user turn.
Its structured output is the role's DEFAULT, so no call site may drop it by omission: the shared seam treats an absent `schema` as the role's own contract and only a deliberate `None` selects a prose turn.

*Shaping* (deterministic, post-LLM, ORDER load-bearing): `narrow_to_assignment` -> `resolve_l0_refs` -> `drop_out_of_inventory`.
Correctness never depends on the model's formatting: an `l0.label` the model coined is repaired against the chunk's slice.
`resolve_l0_refs` resolves against THIS chunk's admitted slice ONLY (the out-of-scope filter, R-A2): a reference outside the chunk drops as `unresolvable`, even when the settled surface holds it - its own chunk judges it when recon collects it.
`AssignmentStats` counts every gate, so "found nothing" stays distinguishable from "discarded everything".
_Avoid_: analyser (the whole-model term).

**Three "no edge is written" mechanisms** (named apart 2026-07-27, #34; a fourth added #48, 2026-07-30 - one word for all of them hid a decision never taken behind a decision taken and declined; two removed 2026-10-15):
- **Gate** (input side): the element never reaches the agent, so no judgment is formed. The per-role admission set, and the stream-level gate in `chunks_for_job` (`is_noise_endpoint`: never-surface static families, script bundles and `wasm` never stream, images/media only under an `assets/`/`static/` segment; `is_connectivity_asset`: `Domain`/`IP`/`Port`/`Service` never stream - the 2026-10-15 arm-H decision, `docs/design/plans/2026-10-15-streamed-pipeline-corrections.md` T1; families single-sourced from recon's `noise_filter` 2026-10-16). (The httpx-profile delivery gate on the data path was REMOVED by #48, not merely retired as an instance of this mechanism - see "Chunk feeding" below.)
- **Narrow** (output side, structural): the agent may not emit a class of delta at all, whatever the model returned.
- **Withhold** (output side, epistemic) - REMOVED 2026-10-15 with the confidence score (`docs/design/drop-aggregate-confidence.md`): the agent looked, judged, and declined below the bar. Assignment is admit-all now.
- **Ground** (output side, epistemic; #48) - REMOVED 2026-10-15 with the data plane (`docs/design/drop-data-modeller.md`): the DataPlane Analyser's substitute for Withhold is gone with the analyser.

**TechnicalSystem / mechanism-typist**:
The sole owner of mechanism TYPING (agent spec #9) - it defines/extends the cross-cutting `System`s the streamed surface evidences and links them to Services as typed `Service->System` edges, never Service props. BREADTH-ONLY: it emits `L1DeltaBatch{systems, system_edges}`; all System DEEPENING (WebPresentation rendering/navigation, authz inverse-pyramid, backward-recon probes, the `AnatomyResult` triple) is Phase B (epic #39).
It runs a THREE-call chain over one chunk delivered AFTER the Assigner: a hypothesis-driven free-text **reflection** (define which Systems the assets impact, verify soundly against tool-grounded evidence - exhaustion fails the step CLOSED), then structured **systems extraction**, then structured **services linking** (soft pass-through on later-step exhaustion).
Every turn binds the read-only `graph_view`, the HTTP-history pair, and the bounded `exec` tool (D-A2 extended past assigner-only; see `docs/design/typist-tool-workflows.md`); the reflection turn carries them as tools while keeping `response_format` prose, so the request shape never toggles.
The role prompt rides the seam default on all three calls (byte-identical, cache-safe).
_Avoid_: analyser (the whole-model term); anatomy (the Phase-B deepening path).

**System description (discriminative attribute)**:
The System-side counterpart of `service_contract`: a System's brief adversarially-oriented NL `description` prop is its DISCRIMINATIVE attribute - the mechanism-typist reads the currently-defined Systems WITH their descriptions (the additive `read_l1_inventory` `system_descriptions` map) to decide new-vs-extend, and on extend it COMPOUNDS the description (reads the existing one, emits the enriched superset), never emptied. Contrast the Assigner's never-re-emit `service_contract`: there the Bootstrapper is the better whole-architecture author, whereas the mechanism-typist is the SOLE incremental author of System descriptions, so compounding is correct, not clobbering.
_Status_: NL description is the sole carrier at breadth; a richer type-based System specification is Phase B (#40, the L1-System under-typing gap).

**DataPlane Analyser / data-modeller** - REMOVED 2026-10-15 (`docs/design/drop-data-modeller.md`, supersedes #48, `docs/design/dataplane-A1-decisions.md` retained as history):
Formerly the sole owner of the Tier-1 data substrate - lifted logical `DataItem`s from streamed `Parameter`/`Header`/`Secret` surface, bound them with `SURFACES_AT`, and mapped `PRODUCES`/`CONSUMES` flows onto the settled Service model.
The per-chunk schedule is `assigner -> mechanism_typist`; the admission table is `{assigner: Endpoint, mechanism_typist: ADMIT_ALL}`, and the fork-H guarantee holds with two roles (the generalist still catches any unnamed asset type).

**Observed-only fields** - REMOVED with the data plane (same date/ADR):
Formerly the rule that a DataItem's `fields` prop named ONLY surface-observed fields, enforced by intersecting the proposal with the observed vocabulary in the shaping seam.

**Grounded DataItem** - REMOVED with the data plane (same date/ADR):
Formerly the deliverable predicate (at least one `SURFACES_AT` AND at least one `PRODUCES`/`CONSUMES` flow), with the surface half enforced per chunk and the flow half checked graph-level.

**DataItem notes (discriminative attribute)** - REMOVED with the data plane (same date/ADR):
Formerly the DataItem-side counterpart of `service_contract` and of a System's `description`, compounded by the data-modeller as its sole incremental author.

**Withholding gate** - REMOVED 2026-10-15 (`docs/design/drop-aggregate-confidence.md`):
Formerly the Assigner's crux (AMV-14): a below-bar ownership judgment yielded NO `AGGREGATES` entry, so the L0 element stayed in the stale pool.
Assignment is admit-all now; an unplaced Endpoint still ends the run with no owner and stays in the stale pool, but no graded gate puts it there.

**Validation gate** (#34 D9):
An aggregate whose `service_slug` is not a live L1 identity is dropped - an owner that does not exist is a reference to nothing, so a hallucinated owner must not be writable.
The reach is retained as a **backlog description**: ONE short sentence naming the business function that may be missing, with the candidate slug embedded inline.
Carried, not transported (#34 D6): no envelope field carries it upward yet.

**Shared ownership** (#34 D3):
There is no single-owner invariant - several Services may aggregate the same L0 asset.
Each genuine owner is emitted as its own edge.

**Service minting** (RETIRED from the Assigner 2026-07-27, #34 D4):
The Bootstrapper is the sole source of the Service population and of `service_contract`.
An Assigner sees one chunk of surface while the Bootstrapper read the whole architecture, so a chunk-local mint competes with a far better-informed source and is the measured origin of cross-run identity drift (AMV-12).
The Assigner's `existing_slugs` is therefore a VALIDATION set, never a mint discriminator.

**Analysis feed** (`analysis/feed.py`, #34 - the recon/analysis runtime seam):
The ONE runtime edge from recon to analysis, and the reason a recon run no longer waits on an LLM.
Since #74 it carries **payloads, not cursors** (RE-SHAPED 2026-08-03): an `L0Chunk` is the job's EXACTLY-curated L0 slice - the merged `AssetDelta`s and triager `Observation`s a recon job's pods actually merged - so the consumer judges precisely what was pushed, and the feed re-reads no graph. Every pushed chunk is consumed EXACTLY ONCE, in push order: the `QueuedAnalysisFeed` is an unbounded in-memory FIFO (one consumer task per run, one chunk per pass, holding the analysis-module pass gate - a per-module `asyncio.Semaphore`, default width 1, on the shared worker loop (#121), resolving to the legacy process-wide `ANALYSER_PASS_SEMAPHORE` when no runtime is active - the memory bound that made a concurrent consumer admissible at all, the NM-7 ledger having rejected an unbounded one). No coalescing survives, and no cross-pass dedup state: `analyse_chunked`'s `analysed_keys` cumulative filter is GONE, and the cumulative-equals-batch guarantee (L1D-23) is preserved as the UNION over pushes - every pushed asset is judged in exactly the pass that consumes its chunk.
`push` is non-blocking (best-effort: a failing pass degrades that chunk, never the run). Since #75 the feed is held in a PROCESS-LEVEL registry keyed by `run_id` (`get_or_create_feed`), so it OUTLIVES the recon pipeline task - recon (producer) and analysis (consumer) are two independent runtime units. Recon signals end-of-stream with `signal_end` (a TERMINAL marker `L0Chunk`, `terminal=True`, empty payload) on BOTH its complete and its stop paths, fire-and-forget; FIFO order guarantees the marker is consumed last. The consumer ends NATURALLY on that marker (there is NO drain deadline/grace since #75 D8 - every pass self-terminates via the escalating LLM budget #73), or on a GRACEFUL stop that lets the in-flight chunk finish and preserves the rest for a resume (#75 D7). A caller without a chunk (the legacy batch path, the pod seam) keeps reading the settled surface through `run_analyser_chunked`, the batch adapter that builds one pseudo-job `L0Chunk` and hands it to the same `analyse_chunked`.
Mode requires `streaming_analysis` on; given that, `queued` is the DEFAULT (#9 - the mechanism-typist's ~126s/chunk cost put an inline pass on recon's critical path), and `inline` is the explicit rollback path for a caller that sets `async_analysis_consumer=False` - it runs the SAME chunk pass on the caller's task, identical semantics, different executor.

**Analysis run** (`analysis/lifecycle.py` + `analysis_runs` table, #75): analysis is its OWN run, decoupled from the recon run. The dispatcher (`POST /recon` combined or `with_analysis=false` recon-only; `POST /analysis` analysis-only/resume; `.../stop` for each) starts recon and analysis as independent tasks over the shared per-run FIFO. The recon run reaches `complete` the instant its jobs finish - it NEVER waits on analysis (D3). The analysis run carries its own status: `draining -> drained` (marker consumed + a pass entered a dispatch) `| withheld` (marker consumed, vacuous) `| stopped` (graceful stop, queue non-empty, resumable) `| interrupted` (process died mid-drain; the startup reconcile `pg.reconcile_orphaned_analysis_runs` writes this, D10). `analysis_runs` uses a surrogate `analysis_run_id` PK with `run_id` a NON-unique indexed correlation column, so a relaunch over the same recon run never collides (D5); `get_analysis_run` reads the latest attempt. Full ADRs: `docs/design/control-plane-decoupling-decisions.md`. Cross-process-restart resumption of the queue is deferred to #88.
_Guarantee_: at-least-once OBSERVATION of surface - a completion obligation on the run, NOT a transport property, and nothing is claimed about what the analyser concluded.

**Supervisor terminal flush** (#211):
The supervisor stamps the terminal status only AFTER archiving ONLY this run's proposer threads through the SHARED run-scoped chokepoint `flush_run_scoped("analysis", run_id)` (`app/llm/checkpoints.py`) - the strict flush -> assert -> teardown dependency at the run surface, never an inline flush block. The chokepoint returns the typed `FlushResult` (`committed/archived/dropped/dropped_thread_ids/cause`, closed cause vocabulary on the type), logs a drop loudly with the thread ids, and never raises.

**analysis.supervisor_enabled (coexistence flag, RETIRED)**:
The orthogonal flag that used to select legacy-pod vs the supervisor at the one analyser entry (`run_analyser`).
RETIRED (#48 section 11 step 6, ratified 2026-07-30): the legacy two-pass pod it selected away from is deleted, so the flag branch is gone - `run_analyser` always drives the chunk-fed supervised path (`analyse_chunked`, the `assigner -> mechanism_typist` schedule).
A project settings blob may still carry the key from before this change; it is simply no longer read.

## Chunk feeding (increment 1; the delivery gate was REMOVED by #48)

The chunk-builder (`analysis/chunking.py`, `#13`/`#14`, increment 1) streams a recon job's L0 delta to the proposers.
A pure function whose reads are injected.

**Chunk**:
The slim immutable Value Object carrying an immutable per-job L0 DELTA - the pure-function input a proposer reasons over.
It carries only the L0 delta; all L1 context is re-derived LIVE at the proposer, never frozen on the chunk (the live-graph invariant).
_Avoid_: batch (a chunk closes on the soft target, below), payload.

**Role admission set** (`ROLE_ADMITS` / `admit_for_role`, #34 D2/D7 - the lever #15 called asset-type-driven agent scoping):
Every asset type a recon job produces is STREAMED unless a stream-level gate withholds it (noise Endpoints; the connectivity types `Domain`/`IP`/`Port`/`Service`); each proposer role then narrows the stream to the types it can meaningfully consume.
`assigner` admits `Endpoint` alone; `mechanism_typist` holds the `ADMIT_ALL` sentinel.
The sentinel is load-bearing, not shorthand: with two allow-sets an asset type no role names would be admitted by nobody and silently dropped, losing the fork-H guarantee, so the generalist role always catches a new recon tool's output.
A role admitting nothing from a chunk yields an empty batch, which is a valid outcome rather than an error.
This is a SEPARATE, later-stage mechanism from the httpx-profile delivery gate below (verified NOT to be affected by that gate's removal).

**Concern (concern tag)** - RETIRED 2026-07-27 (#34 D8).
The two-way `service` / `data` partition fixed "which asset types matter" once and globally, when the real constraint is per-agent; the role admission set replaced it, and `Chunk.concern` / `CONCERN_ROLES` are gone.

**Chunk-builder**:
`chunks_for_job` - streams a job's `AssetDelta` list into an ordered sequence of topology-cohesive chunks, in three stream-level transforms: FILTER, COLLAPSE, GROUP.
The FILTER gates (`is_noise_endpoint`, `is_connectivity_asset`) drop what no L1 judgment can use: the never-surface static families (stylesheets, fonts, sourcemaps), the script bundles (`.js`, `.mjs`) and `wasm` (case-insensitive, query/fragment stripped) and whole-segment `assets/`/`static/` paths; images/media drop only under a presentational segment (recon's D15 recall bias - `/uploads/x.png` stays), and non-Endpoint assets found on those paths stay in the stream. The extension families are single-sourced from recon's `noise_filter` so the two classifiers never drift (2026-10-16). The connectivity types (`Domain`, `IP`, `Port`, `Service`) are how the target is REACHED, not surface an agent acts on: they stay in L0 (the topology's join keys) and never enter a chunk (2026-10-15, arm H: the assigner yielded no judgment on them while the typist typed mechanism noise off them).
The COLLAPSE keeps the FIRST occurrence of each `(type, identity)`; recon re-emits its BaseURL, response Headers and Technologies once per crawled transaction, and this is where that per-transaction flood ends (2026-10-15, T3 diagnosis: a katana chunk carried 100 paragraphs over 10 unique identities, ~144k chars).
The GROUP turns the deduped stream into topology FAMILIES: a `host-meta` family per BaseURL (the BaseURL with its Headers, Technologies, Certificates and host-level Secrets) and one `endpoints` family per `(baseurl, content-class bucket)`, the Endpoints with their Parameters and endpoint-anchored Secrets. Endpoint BUCKETS read the recorded `content_type` prop: `code` / `visual` / `html` / `data` / `other`. Anchorless assets (e.g. a Subdomain) keep their own singleton family and still stream (the fork-H guarantee).

**Chunk target (soft)**:
`CHUNK_TARGET_ASSETS` is a target, NOT a cap: families are ATOMIC and are added whole, so a chunk closes once the added families cross the target while a single family larger than it goes whole.
`batch_index` / `batch_total` still order the chunks and the tail is never dropped.
A chunk is therefore a graph neighbourhood (a host's metadata, or an endpoint bucket with its parameters), never an array slice.

**httpx-profile delivery gate** - REMOVED, 2026-07-30 (#48, not merely retired as an instance of "Gate"):
Formerly: the `#13` fork-G rule (reuse-first on D16) that admitted a Parameter only when its BaseURL carried an httpx `profile`, withholding an un-profiled one at delivery and delivering it FLAGGED at the phase-barrier (`Chunk.flagged`, the AMV-14 fail-open backstop).
`#34 D1` already dropped the identical gate for Endpoint (withholding an unprofiled Endpoint made a never-profiled target produce an ownerless attack surface indistinguishable from one with nothing to own); dropping the Parameter half too EMPTIED the gate's `_GATED_TYPES`, making the whole apparatus (`chunking._gate`/`_GATED_TYPES`/`profiled_origins`/the `barrier` parameter/`Chunk.flagged`) permanently unreachable, so it was removed rather than left to rot.
Profile classification is now absent from every proposer's context entirely; the data-modeller's candidate-owning-Service join is its sole interpretive signal for a Parameter's origin.

## Provisional and designed-not-built terms

**Fault-hypothesis**:
A defeasible, falsifiable claim that "unit U, at locus L, could exhibit fault-class F, because property P is assumed there and P may not hold" - the top rung of the epistemic ladder.
It is a **phase-3 testing primitive**, not graph structure: it lives in the reasoning of a testing technique for the duration of a test and is NEVER a node or edge in the L0/L1 graph.
No seed instance is persisted now (the `CONSUMES` trust assumption was removed with the data plane); the general primitive belongs to the deferred phase 3 (Stage-3, `NM-8`).
_Status_: **designed-not-built and name-not-ratified** - the operator has ruled out the earlier `:L1FaultHypothesis` node / `POSITS_FAULT_AT` edge framing (`domain-model.md` §2.6/§8).
_Not to be confused with_: a vulnerability (a *confirmed* fault); an Observation (Recon, a low inference).

**Testing technique**:
A phase-3 procedure that embodies a fault-hypothesis and is enacted as one or more probes against the persisted L0/L1 substrate.
_Status_: designed-not-built (phase 3 / Stage-3, `NM-8`).

**Probe**:
A single phase-3 test of a fault-hypothesis against the substrate; on success it discovers a vulnerability.
Related to the already-built interface-B backward-recon request (`L1D-26`), which is the mechanism a probe would ride.
_Status_: the interface-B request is built; the phase-3 hypothesis-testing use of it is designed-not-built.

**Vulnerability**:
A confirmed fault - the output of a probe that succeeds in phase 3.
_Status_: designed-not-built (phase 3, `NM-8`).
_Not to be confused with_: a fault-hypothesis (an *unconfirmed* claim); an Observation (a low inference, not a confirmed fault).

**SystemAspect**:
A reified shared facet that would make the inverse "which services manifest this facet" traversal one hop.
_Status_: designed-not-built; the MVP fence asserts no `:SystemAspect` node exists (`L1D-16`, `NM-3`).

**Journey**:
A withdrawn grouping-of-services concept.
(Resolved: a DONE FR area still in the catalogue, but withdrawn from the codebase on 2026-07-22 because the LLM coined single-member journeys that restate a service; `CurationBatch.journeys` and its stage are removed.)
_Status_: withdrawn - an unbuilt, deferred extension, not a live primitive.

**Context-memory scaffold**:
Cross-phase operational-failure memory (`recon_signals`), grounded coverage verdicts, and finding-triggered extension - all specified, none built.
_Status_: designed-not-built (`recon-pipeline-design.md` §9).
