# Analysis

Layer-1 interpretive abstraction.
This context reconstructs, from the observed L0 attack surface, a judged model of what the target *is* - its business targets (Service), its shared mechanisms (System), and its logical data (DataItem) - and anchors every judgment back onto the L0 evidence that licenses it.
Nothing here is witnessed; every node is an analyst-role LLM's proposal that the L1 sole-writer turns into a fact.
This context is a physically independent module at `src/polymerhus/analysis/` (extracted from under `recon/` in the 2026-07 `src/` restructure). Its only structural tie to recon is the published L0 vocabulary in `recon.domain.types` - the anti-corruption seam.

Vocabulary derived from `docs/design/domain-model.md` (esp. §2.2-2.6, §4, §6); see also `docs/design/l1-domain-model-catalogue.md`.

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
The three are `AGGREGATES`, `SURFACES_AT`, `EVIDENCED_BY`.

**AGGREGATES**:
The assignment edge from an L1 `Service` to an L0 node, carrying the full judgment envelope: "I judge element e belongs to service S, this confident, on this evidence".
It is the load-bearing L0/L1 hinge and the only cross-layer edge that carries a graded judgment.
_Avoid_: contains, owns, has (membership is N:M and non-possessive).

**SURFACES_AT**:
The cross-layer edge from an L1 `DataItem` to the L0 Parameter / Header / field where that logical item appears on the observed surface; carries provenance and timestamps only.

**EVIDENCED_BY**:
The cross-layer edge from an L1 `System` to the L0 node that fingerprints it (a `Server:` header, a cookie); carries provenance and timestamps only.

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
The single System `kind` for the web-presentation channel, carrying `rendering_model` (CSR/SSR/...) and `navigation_model` (SPA/MPA/Hybrid) as two ontologically independent props.
(Resolved: replaced the deleted `RENDERED_BY` edge and the `RenderingSystem_*` kinds; a Service reaches it via `EXPOSED_VIA`, exactly as it reaches a REST or GraphQL API.)

**kind**:
A System's intrinsic identity attribute, validated against the fixed `SYSTEM_KINDS` constant.
(Resolved: the `SystemKind` catalogue *node* of the older spec no longer exists; kind is an attribute, not a node.)
_Avoid_: type, category, SystemKind (the node).

**DataItem**:
A logical data record (a session token, an order, a `sales_figure`) as a first-class L1 node, keyed on a semantic `item_key`, with identity independent of the many L0 sites it surfaces at.
It is the Tier-1 trust locus and the noise filter for concretisation.
_Avoid_: field, parameter, value.

**Trust boundary**:
Where trust changes hands; not a node but an edge - a `CONSUMES` edge from a service to a data item it did not produce.
The impactful faults live on these boundaries and in shared mechanisms, not inside a single target.

**Trust assumption**:
The falsifiable predicate a consuming service holds about data it did not produce (e.g. "this field was authorised for this user"), carried on a `CONSUMES` edge.
Representable only when it hangs on a derived flow `A -CONSUMES-> D <-PRODUCES- B`, so assertion-without-a-dataflow is structurally unrepresentable.
It is the one *persisted* seed instance of the general phase-3 fault-hypothesis, read as input by a testing technique.

## Intra-L1 edges

**EXPOSED_VIA**:
The edge from a Service to the System that presents it (WebPresentation, a REST or GraphQL API).

**CONSUMES / PRODUCES**:
The data-flow edges between a Service and a DataItem; a `CONSUMES` on data the service did not `PRODUCES` is a trust boundary.

**AUTHENTICATED_BY / AUTHORIZED_BY**:
System edges binding a Service to its authentication and authorization mechanisms (kept distinct: who you are versus what you may do).

**DATA_RELATIONSHIP edge**:
The edge between two DataItems whose type *is* the uppercased kind from a fixed six-value allowlist (`DERIVED_FROM`, `REFLECTED_IN`, `EQUALS_HASH_OF`, `COPY_OF`, `CONCATENATION_OF`, `SUBSET_OF`).
(Resolved: the `DataRelationshipKind` catalogue node of the older spec no longer exists; the kind is the edge type itself.)

## The reasoning vocabulary

**Judgment envelope**:
The `{confidence, status, evidence_refs, provenance, ts}` bundle carried on the `AGGREGATES` assignment edge from day one, even though the MVP only ever writes `status="committed"`.
Reserved for `AGGREGATES` alone because assignment is a graded judgment, while data-surfacing and mechanism-fingerprinting are near-mechanical bindings (the deliberate envelope asymmetry).

**Provenance**:
Who or what made a claim: `prov_job` / `prov_model` / `prov_prompt_id`, stamped by the sole-writer and structurally forbidden to the proposer.
The concept that lets "an LLM said so" and "a tool measured it" be different kinds of fact in one graph.
(Also stamped by the L0 curator in Recon; defined here as it is core to weighing L1 judgments.)
_Avoid_: metadata, source tag.

**Confidence**:
The strength of a judgment, carried in the envelope; orthogonal to provenance (who asserted) - both are needed to weigh a claim.
The policy that would act on it (a withholding threshold) is unset.
_Status_: recorded but not yet acted on.

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
The proposer role that reconstructs the L1 Service/System model, run in two passes - an assignment pass and a dedicated data-modelling pass - split because one combined call systematically starved data modelling.
_Avoid_: analyst, modeller.

**l1_curator (L1 sole-writer)**:
The single module authorised to write the L1 store: enforces identity, stamps provenance, validates every label and edge type against a fixed allowlist, and never `MERGE`s an L0 node.
The L1 counterpart of the Recon `curator`.

**Bootstrap**:
The pre-analysis step that seeds the operator KB so an analyser run starts from a framed target rather than the bare surface (the bootstrap-first e2e discipline).
The redesigned Bootstrapper (#26) elicits the skeleton in TWO calls - a free-text 5-step reasoning (architect-decompose -> expand -> hypothesis+KB-ground -> critical-withhold -> decide) then a structured shell extraction - taught by 2 divergent-domain few-shot exemplars, and is FAIL-CLOSED: on retry-exhaustion or a write failure it BLOCKS the analysis rather than degrading to an empty skeleton (an empty KB stays a valid linchpins-only proceed).

The Bootstrapper is a pre-analysis PHASE, not a supervised analyser proposer: it runs once, ahead of the analysis, and is triggered over the app API (`POST /projects/{id}/bootstrap`), which ingests the operator's knowledge and returns the skeleton counts - or a 503 carrying the fail-closed block.
Its system message is TWO layers: a stable base prompt in code (identity, pipeline position, the output-field contract - the WHAT) plus the operator-tunable reasoning discipline in `skills/analysis/bootstrapper/SKILL.md` (the five stages, service-contract craft, critical withholding - the HOW).
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
The checker that vets proposals *before* they are written (a confidence gate, a noise classifier, an identity-reuse check), moving the maker/checker discipline upstream from repair to prevention.
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
The driver opens an `AsyncPostgresStore` (`setup()`) alongside the `AsyncPostgresSaver`, and attaches the #18 Langfuse callbacks + a correct session id, flushing at run end.
2a wraps the LEGACY two-pass as one transitional `assigner` node (output-identical); the per-responsibility, chunk-fed decomposition is increment 2b.

## Proposer decomposition (increment 2b)

The `_two_pass_analyse` monolith dissolves into responsibility-scoped proposers, each consuming a `Chunk` narrowed by its own admission set and writing through the sole-writer. Built as standalone slices (flag OFF) then wired.

**Assigner**:
The sole owner of the `AGGREGATES` hinge (agent spec #8) - HIGH-PRECISION assignment of an Endpoint to its owning Service, A.1-only (no re-assignment, no retraction).
Emits a narrowed `L1DeltaBatch{aggregates}` (#34 D4: `services` left the output when minting was retired).
Its system message is TWO layers, the same split the Bootstrapper uses: the role verbatim in code (identity, the aggregates-only output contract, the reference shape - the WHAT, which must hold even with no skills mount) plus the operator-tunable ownership-judgment discipline in `skills/analysis/assigner/SKILL.md` (the no-owner null hypothesis, the differential over candidate owners, discriminating evidence, calibrated withholding - the HOW).
The shared analyser skill is NOT that layer and was never a fit: it addresses a generalist proposer and instructs the System and data modelling D4/D18 forbid this role (the #30 per-role retirement).
`ASSIGNER_PROMPT_CONFIG` selects the arrangement, defaulting to the pre-skill `baseline` until a comparative eval flips it.
_Avoid_: analyser (the whole-model term).

**Three "no edge is written" mechanisms** (named apart 2026-07-27, #34 - one word for all three hid a decision never taken behind a decision taken and declined):
- **Gate** (input side): the element never reaches the agent, so no judgment is formed. The per-role admission set, and the profile gate on the data path.
- **Narrow** (output side, structural): the agent may not emit a class of delta at all, whatever the model returned.
- **Withhold** (output side, epistemic): the agent looked, judged, and declined below the bar.

**TechnicalSystem / mechanism-typist**:
The sole owner of mechanism TYPING (agent spec #9) - it defines/extends the cross-cutting `System`s the streamed surface evidences and links them to Services as typed `Service->System` edges, never Service props. BREADTH-ONLY: it emits `L1DeltaBatch{systems, system_edges}`; all System DEEPENING (WebPresentation rendering/navigation, authz inverse-pyramid, backward-recon probes, the `AnatomyResult` triple) is Phase B (epic #39).
It runs a THREE-call chain over one `service` chunk delivered AFTER the Assigner: a hypothesis-driven free-text **reflection** (define which Systems the assets impact, verify soundly - overthink + critical-thinking + define/debug-hypothesis; exhaustion fails the step CLOSED), then structured **systems extraction**, then structured **services linking** (soft pass-through on later-step exhaustion).
_Avoid_: analyser (the whole-model term); anatomy (the Phase-B deepening path).

**System description (discriminative attribute)**:
The System-side counterpart of `service_contract`: a System's brief adversarially-oriented NL `description` prop is its DISCRIMINATIVE attribute - the mechanism-typist reads the currently-defined Systems WITH their descriptions (the additive `read_l1_inventory` `system_descriptions` map) to decide new-vs-extend, and on extend it COMPOUNDS the description (reads the existing one, emits the enriched superset), never emptied. Contrast the Assigner's never-re-emit `service_contract`: there the Bootstrapper is the better whole-architecture author, whereas the mechanism-typist is the SOLE incremental author of System descriptions, so compounding is correct, not clobbering.
_Status_: NL description is the sole carrier at breadth; a richer type-based System specification is Phase B (#40, the L1-System under-typing gap).

**Withholding gate**:
The Assigner's crux (AMV-14): a below-bar ownership judgment (confidence < the 0.75 bar) yields NO `AGGREGATES` entry - the L0 element stays in the stale pool.
The withholding is a SHAPING rule (absence IS the withholding; no "withheld" edge exists), lives in the Assigner seam not the shared sole-writer, and is the Assigner's SELF-check (maker); the Auditor is the separate check over survivors (checker).
The bar is an EMPIRICAL PLACEHOLDER (#34): an OUTPUT of the assertion suite that a run sweeps, not a reasoned input.

**Validation gate** (#34 D9):
An aggregate whose `service_slug` is not a live L1 identity is dropped BEFORE the confidence gate - an owner that does not exist is a reference to nothing, not a weak judgment to be scored, so a confident hallucination must not be scoreable.
The reach is retained as a **backlog description**: ONE short sentence naming the business function that may be missing, with the candidate slug embedded inline.
Carried, not transported (#34 D6): no envelope field carries it upward yet.

**Shared ownership** (#34 D3):
There is no single-owner invariant - several Services may aggregate the same L0 asset.
Each genuine owner is emitted with its own independent confidence, and the bar filters each edge separately.

**Service minting** (RETIRED from the Assigner 2026-07-27, #34 D4):
The Bootstrapper is the sole source of the Service population and of `service_contract`.
An Assigner sees one chunk of surface while the Bootstrapper read the whole architecture, so a chunk-local mint competes with a far better-informed source and is the measured origin of cross-run identity drift (AMV-12).
The Assigner's `existing_slugs` is therefore a VALIDATION set, never a mint discriminator.

**analysis.supervisor_enabled (coexistence flag)**:
The single orthogonal flag, read inside `run_analyser`, that selects legacy-pod (default OFF) vs the supervisor (ON) at the one analyser entry.
A two-way door: rollback is a flag flip; the legacy path stays byte-for-byte unchanged and is the runnable default until the acceptance gate is green.

## Chunk feeding + delivery gate (increment 1)

The chunk-builder (`analysis/chunking.py`, `#13`/`#14`, increment 1) streams a recon job's L0 delta to the proposers.
A pure function whose reads are injected.

**Chunk**:
The slim immutable Value Object carrying an immutable per-job L0 DELTA - the pure-function input a proposer reasons over.
It carries only the L0 delta; all L1 context is re-derived LIVE at the proposer, never frozen on the chunk (the live-graph invariant).
_Avoid_: batch (a batch is the overflow unit, below), payload.

**Role admission set** (`ROLE_ADMITS` / `admit_for_role`, #34 D2/D7 - the lever #15 called asset-type-driven agent scoping):
Every asset type a recon job produces is STREAMED; each proposer role then narrows the stream to the types it can meaningfully consume.
`assigner` admits `Endpoint` alone; `data_modeller` admits `Parameter` + `Header`; `mechanism_typist` holds the `ADMIT_ALL` sentinel.
The sentinel is load-bearing, not shorthand: with three allow-sets an asset type no role names would be admitted by nobody and silently dropped, losing the fork-H guarantee, so the generalist role always catches a new recon tool's output.
A role admitting nothing from a chunk yields an empty batch, which is a valid outcome rather than an error.

**Concern (concern tag)** - RETIRED 2026-07-27 (#34 D8).
The two-way `service` / `data` partition fixed "which asset types matter" once and globally, when the real constraint is per-agent; the role admission set replaced it, and `Chunk.concern` / `CONCERN_ROLES` are gone.

**Chunk-builder**:
`chunks_for_job` - streams a job's `AssetDelta` list into ONE ordered sequence, applying the profile gate and size-bounding by batch-overflow.

**Batch-overflow**:
The sizing lever: a stream longer than the per-chunk asset budget splits into ordered chunks (`batch_index` / `batch_total`), the tail never dropped - replacing the retired silent 400-cap truncation.

**httpx-profile delivery gate**:
The `#13` fork-G rule (reuse-first on D16): a Parameter is admitted only when its BaseURL carries an httpx `profile`; an un-profiled one is WITHHELD at delivery until phase-6 `httpx_reprofile` sets the profile, and delivered FLAGGED at the phase-barrier (the AMV-14 fail-open backstop - never silently dropped).
The profiled-origin set reuses `selectors.apply_selector`.
The gate covered Endpoint too (`#14`) until #34 D1 dropped it: withholding an unprofiled Endpoint made a never-profiled target produce an ownerless attack surface indistinguishable from one with nothing to own.

## Provisional and designed-not-built terms

**Fault-hypothesis**:
A defeasible, falsifiable claim that "unit U, at locus L, could exhibit fault-class F, because property P is assumed there and P may not hold" - the top rung of the epistemic ladder.
It is a **phase-3 testing primitive**, not graph structure: it lives in the reasoning of a testing technique for the duration of a test and is NEVER a node or edge in the L0/L1 graph.
The one *persisted* seed instance is the `CONSUMES` trust assumption, which a phase-3 technique reads as input; the general primitive belongs to the deferred phase 3 (Stage-3, `NM-8`).
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
