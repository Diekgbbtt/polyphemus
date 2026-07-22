# Analysis

Layer-1 interpretive abstraction.
This context reconstructs, from the observed L0 attack surface, a judged model of what the target *is* - its business targets (Service), its shared mechanisms (System), and its logical data (DataItem) - and anchors every judgment back onto the L0 evidence that licenses it.
Nothing here is witnessed; every node is an analyst-role LLM's proposal that the L1 sole-writer turns into a fact.
This context is not yet a physically independent module (it lives under `agent/recon/analysis/`) but is scheduled to be refactored into one.

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
A designed-not-built checker that would vet proposals *before* they are written (a confidence gate, a noise classifier, an identity-reuse check), moving the maker/checker discipline upstream from repair to prevention.
_Status_: designed-not-built (`AMV-16`); the natural home for the orphaned confidence and absence policies.

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
