# polymerhus Coding Standard - the software-design principles

*The discipline we hold, and where the code already shows it.*

polymerhus is an autonomous web-application vulnerability-discovery system.
This document states the design principles that guide the implementation and grounds each one in a pattern the codebase already embodies, cited by `path:line` or by a named function or constant.
A principle with no worked example from this repo is weaker than one with a citation, so every principle below carries at least one.

This standard is the "how we build".
It cross-references, rather than restates, the three documents that own the other truths:

- `docs/design/domain-model.md` - the canonical ontology (the "what is true"): the reasoning every domain term derives from.
- `CONTEXT-MAP.md` plus `src/polymerhus/recon/CONTEXT.md`, `src/polymerhus/analysis/CONTEXT.md`, and `src/polymerhus/project_management/CONTEXT.md` - the bounded contexts and their per-context glossaries (the "what things mean").
- `loop-constraints.md` - the binding invariants enforced on every write (the "what must hold").
- `docs/design/testing-strategy.md` - the testing tiers and their boundaries (the "what is tested").

When this standard and any of those disagree, they win on their own subject and this document is corrected.

---

## 0. The paradigm: domain-driven design

Everything below unfolds from one commitment: the code is the model, and the model is the domain of vulnerability discovery.
This is not a CRUD business application, so DDD maps onto it honestly rather than by rote - some patterns fit exactly, a few do not fit at all, and this standard says which is which.

What fits, and is load-bearing here:

- **Ubiquitous language.** Every name in code is a domain term with a glossary entry.
  `Observation`, `AGGREGATES`, `Service`, `System`, `DataItem`, `stale pool`, `judgment envelope`, `provenance` are all defined in the CONTEXT files and used verbatim in the code.
- **Bounded contexts with an explicit map.** Two contexts, Recon (Layer 0, observed) and Analysis (Layer 1, judged), with a documented supplier/consumer relationship and an anti-corruption discipline at the seam (Section 2).
- **Entities vs value objects.** L1 units are entities with stable intrinsic identity (a `Service` survives all its attribute changes); deltas, envelopes, and references are value objects, defined wholly by their attributes and replaced rather than mutated (Section 8).
- **Aggregates and consistency boundaries.** Each store has exactly one write authority that enforces its invariants (Section 5, the sole-writer).

What maps only partially, stated so no one forces it:

- **Domain events** exist conceptually (a probe result defeases a hypothesis, the reflection loop of `domain-model.md` §2.6) but are not implemented as an event bus; the pipeline is a phase DAG, not an event-sourced system.
  Do not introduce `*Event` types speculatively.
- **Repositories/factories** appear as injected `read_fn`/`merge_fn` seams and `proposals_to_deltas` factories, not as a formal repository layer.

The Core Domain - where the system's value lives and where the deepest modeling belongs - is Layer 1 inference: reconstructing what a target *is* from what tools observed, and (ahead of the code) the `FaultHypothesis`.
Layer 0 recon is a rich supporting subdomain; persistence, MCP execution, and LLM-client plumbing are generic and kept thin.
Invest modeling effort accordingly.

---

## 1. Separation of concerns under a continuously-reviewed responsibility model

**Principle.** Every responsibility lives in exactly one place, and the assignment of responsibilities is revisited and re-homed as understanding improves.
A responsibility model is never "done"; it is corrected when the domain teaches us it was wrong.

**DDD rationale.** A bounded context and an aggregate are only coherent if each concept has one home.
When the model learns that a concept was mis-homed - a category error - the correction is a first-class modeling act, not a refactor of convenience.

**Grounded example - a live correction.**
The mechanism-classification principle (`domain-model.md` §2.3, `CONTEXT` glossary "Mechanism-as-System") is a responsibility model being *fixed in flight*.
The operator twice corrected the placement of mechanism attributes: a `rendering_model`, a `navigation_model`, an `api_paradigm`, an `auth_methods` set is a property of the *mechanism-System*, never of the *target-Service* that uses it - storing it on a Service is a category error that both hides the fault's transferability and duplicates state (`l1-domain-model-catalogue.md` §1).
The correction is now enforced in code as an explicit re-homing authority: `curation._REHOME_RULES` (`src/polymerhus/analysis/curation.py:107-113`) maps each mis-placed Service prop to the `EXPOSED_VIA` / `AUTHENTICATED_BY` edge and System that should carry it, and `_navigation_target` deliberately deletes the old `SPA -> CSR` inference (`src/polymerhus/analysis/curation.py:71-72`, `FR-MODELFIX`) because `navigation_model` and `rendering_model` are ontologically independent (`L1D-31a`).

**Standard.**
When you find a prop, an edge, or a function on the wrong unit, do not widen the reader to tolerate it - re-home it, and add the rule to the reconciliation authority so the correction is mechanical and idempotent.
Naming difficulty is a design signal: if a concept resists a clean home, the model is probably wrong (DDD skill, ubiquitous-language).

---

## 2. Bounded contexts, the L0/L1 hinge, and the anti-corruption boundary

**Principle.** Recon (Layer 0) and Analysis (Layer 1) are separate bounded contexts with separate models, joined by a narrow, one-directional, documented seam.
Recon never reads Layer 1; Analysis treats Layer 0 as a published, read-only substrate.

**DDD rationale.** The two contexts speak two epistemic languages: an L0 claim is descriptive ("a tool witnessed this"), an L1 claim is interpretive ("an analyst-role LLM judged this").
The same word means different things across the boundary - `Service` is a network service on a port in Recon and a business target in Analysis (`CONTEXT.md` both glossaries) - and that is fine precisely because the boundary is explicit.

**Grounded example - the anti-corruption layer.**
The three cross-layer edges `AGGREGATES` / `SURFACES_AT` / `EVIDENCED_BY` are the only crossing, and they always `MATCH` the L0 node and never `MERGE` it (`src/polymerhus/analysis/l1_curator.py:315-322`, `build_aggregates_cypher` at `src/polymerhus/analysis/l1_curator.py:351`).
This is the ACL: the interpretive writer can never mint a descriptive node, so an L1 judgment can anchor onto L0 evidence but can never corrupt the observed store.
The two contexts share no identity keys (`L1D-2`), so either can be re-derived without churning the other.

**Standard.**
A new judgment anchors onto L0 by `MATCH`; it never creates an L0 node.
Cross-context terms get their full definition in the owning context and at most a one-line pointer in the other (`CONTEXT-MAP.md`).

**Realised (2026-07).**
Analysis is now a physically independent module at `src/polymerhus/analysis/`, extracted from under `recon/` in the `src/` restructure (`docs/design/module-restructure.md`), and Project-management is minted as `src/polymerhus/project_management/`.
Recon itself is now internally layered - a `control` sub-package (orchestration) over a `domain` sub-package (the model and sole-writer). Run/Job/Pod stay recon vocabulary (ruled elements of the recon pipeline); project-management owns the operator's intent over runs, not their execution.
neo4j/postgres/mcp/llm-client remain shared helper infrastructure, never their own context (`CONTEXT-MAP.md`, "Helper modules"); their vocabulary is still threaded through the pipeline and both curators.
The one exception is the **session seam** under the llm-client helper (`app/llm/session.py`, `session_address.py`, `checkpoints.py`, `actor.py`, `#94`): its typed `SessionAddress` value objects (`AnalysisSession`/`PodSession`/`HuntSession`) ARE domain concepts - a stateful agent's collision-free instance identity - reasoned in `domain-model.md` §3.7, so this one helper carries real domain content while still not becoming a bounded context of its own.
Respect the one-directional dependency arrows (`project_management -> recon -> app`, `analysis -> recon.domain.types` as the ACL) in new code; the session seam keeps them intact - each module owns HOW its own address is discriminated (recon's `pod.py::pod_session` resolves the pod token), so `app/llm` never imports a domain module.

---

## 3. Controller logic separated from data-management logic

**Principle.** Pure logic and impure orchestration live in different functions.
The functions that *build* what to write are pure and touch no driver; the functions that *decide when and whether* to write, inject context, dispatch, and handle failure are the impure orchestrators.

**DDD rationale.** This is the entity/value-object and repository split made concrete: the model computes a value (a parameterised write), and a thin orchestrator applies it to the store.
Business logic never mixes with persistence, so the model stays testable in memory.

**Grounded example.**
In both curators the split is explicit and documented at the top of the module.
`build_asset_cypher` / `build_observation_cypher` (`src/polymerhus/recon/domain/curator.py:119, 151`) are pure - "they never touch a driver" (`src/polymerhus/recon/domain/curator.py:5-8`) - and `curate` (`src/polymerhus/recon/domain/curator.py:226`) is "the impure orchestrator: it injects `project_id`, calls `merge_fn` per item, and skips+logs single-item failures".
The Layer-1 mirror is `build_service_cypher` / `build_system_cypher` / `build_aggregates_cypher` (pure) versus `l1_curate` / `enrich` / `reconcile` (impure), stated verbatim at `src/polymerhus/analysis/l1_curator.py:5-9`.
Even the D8 re-anchor repair keeps this discipline: `broaden_anchor` (`src/polymerhus/recon/domain/curator.py:72`) derives a broadened anchor "by identity key ONLY - no graph/driver access, so this stays pure and unit-testable".

**Standard.**
A `build_*` function is pure: input value in, `(cypher, params)` out, `ValueError` on a shape it refuses.
Never let it read or write.
The orchestrator owns `project_id` injection, dispatch through the injected `merge_fn`, and the fail-open loop.

---

## 4. The sole-writer discipline - one authority makes a claim true

**Principle.** Each store has exactly one module authorised to write it.
That module is the boundary between "proposed" and "true in the graph".

**DDD rationale.** This is the aggregate-root consistency boundary: the one place that enforces identity, stamps provenance, and validates every label and edge against a fixed allowlist.
Without it, "true in the graph" stops being a well-defined predicate (`domain-model.md` §7.1).

**Grounded example.**
L0 writes go only through `src/polymerhus/recon/domain/curator.py`; L1 writes go only through `src/polymerhus/analysis/l1_curator.py` (`loop-constraints.md`, "Sole-writer & denylist paths").
The writer validates labels against `ALLOWED_LABELS` (`src/polymerhus/recon/domain/curator.py:27-31`) and `L1_ALLOWED_LABELS` (`src/polymerhus/analysis/l1_curator.py:69`), and it is where the maker/checker discipline lives at the data boundary: the proposer is the maker, the writer is the mechanical checker of shape and identity.
The proposer is *structurally forbidden* from setting reserved fields - `_clean_props` strips any attempt to set identity or provenance keys from LLM-originated props (`src/polymerhus/analysis/l1_curator.py:139-142, 174-181`), and the proposal models deliberately omit provenance (`src/polymerhus/analysis/analyser_types.py:37-63`), which `proposals_to_deltas` injects at the curate boundary (`src/polymerhus/analysis/analyser_types.py:133-161`).
Even destructive reconciliation (`merge`/`delete`/`relabel`) is admitted only inside `l1_curator` and only over `:L1*` labels (`src/polymerhus/analysis/l1_curator.py:75`, `reconcile` at `src/polymerhus/analysis/l1_curator.py:878-895`), so a repair op can never touch an L0 node.

**Standard.**
Never emit `:L1*` (or L0) MERGE Cypher from anywhere but its sole-writer; if a change seems to need it, escalate (`loop-constraints.md`).
A relationship type or label interpolated into Cypher (Neo4j cannot parameterise it) must pass both `_SAFE_IDENT` (`src/polymerhus/analysis/l1_curator.py:328`) and a fixed allowlist - the two together are the injection boundary.

---

## 5. Slim, typed interface agreements that cover all delivery semantics

**Principle.** Contracts between components are small typed models, and every success and failure path is handled explicitly - no path is left to chance.

**DDD rationale.** A published language between contexts must be minimal and total.
Slim so it is easy to honour; total so a caller never meets an unhandled outcome.

**Grounded examples - the contracts.**
The interface agreements are deliberately narrow typed shapes in `src/polymerhus/recon/domain/types.py` and `src/polymerhus/analysis/analyser_types.py`:

- The parser contract: `stdout -> list[AssetDelta]`, i.e. `Callable[[str], list[AssetDelta]]` (`src/polymerhus/recon/domain/parsers/__init__.py:17`).
- The curate contract: `curate(assets, observations, project_id, *, merge_fn=...)` returning `(assets_merged, observations_merged)` (`src/polymerhus/recon/domain/curator.py:226-234`), mirrored by `l1_curate` returning `(services_merged, systems_merged)` (`src/polymerhus/analysis/l1_curator.py:264`).
- Interface agreement A (assignment): `AGGREGATES` carrying the full judgment envelope `{confidence, status, evidence_refs, provenance, ts}` (`src/polymerhus/analysis/l1_curator.py:32-39`, `L1D-25`).
- Interface agreement B (targeted recon / probe): a backward-recon request routed to the requesting agent (`domain-model.md` §2.6, `L1D-26`).
- The analyser's pure contract: `f(L0-slice + observations) -> L1-deltas` (`src/polymerhus/analysis/analyser_types.py:11-13`), whose proposals omit provenance and identity by design.

**Grounded example - all delivery semantics handled.**
The recon pipeline is the exemplar of total delivery semantics, layered as three fail-open rings that always terminate:

- Per item: one bad delta is skipped and logged, never aborting the batch (`curate`, `src/polymerhus/recon/domain/curator.py:264-292`; `_write_each`, `src/polymerhus/analysis/l1_curator.py:608-624`).
- Per pod: one pod's exception degrades to a `verdict="failed"` export, never aborting its siblings (`pod_runner_node`, `src/polymerhus/recon/control/job_agent.py:270-277`).
- Per job and per run: a job whose pods all fail is marked `degraded` and the run always reaches a terminal `set_run_status(run_id, "complete")` (`src/polymerhus/recon/control/pipeline.py:9-11, 369-384, 474`).

The gate node makes the empty-but-clean semantic explicit: `returncode == 0` is success even with empty stdout, only a non-zero exit is a failure (`src/polymerhus/recon/domain/pod.py:223-236`).
The exec-artifact reader makes the *absence* of evidence a failure, never an assumed success ("No structured result: treat as FAILURE, never assume success", `src/polymerhus/recon/domain/pod.py:357-363`).

**Standard.**
An interface is a typed model with a documented success shape and a documented failure shape.
Handle every branch: exit code, empty result, missing collaborator, malformed proposal.
A "nothing to add" result is a valid, well-typed value (every proposal list defaults empty, `src/polymerhus/analysis/analyser_types.py:116-130`), not an error.

**Honest debt.**
Fail-open *silently drops*: a dropped judgment and a never-made judgment are indistinguishable downstream (`domain-model.md` §7.4).
This is an accepted operational trade, not an ontological defect, because absence is deliberately outside the model (`domain-model.md` §3.5); the concern lives in the operational quality gates (`AMV-14`), not in the interface contract.

---

## 6. Dependency injection for testability

**Principle.** Every side-effecting collaborator is a constructor or call parameter with a real default, so a test can inject a fake and the unit tier never touches a live database, LLM, or Kali host.

**DDD rationale.** The domain model must be exercisable in memory.
Injection is how the repository/gateway seam stays out of the model.

**Grounded example.**
The seams are pervasive and uniform: `build_pod_graph(*, exec_fn, curate_fn, triage_fn)` (`src/polymerhus/recon/domain/pod.py:189`), `build_job_agent(*, pod_invoke, preprocess_fn)` (`src/polymerhus/recon/control/job_agent.py:235`), `run_pipeline(..., run_job=None, load_settings=None, registry=None, read_assets=None, ...)` (`src/polymerhus/recon/control/pipeline.py:196-208`), and `merge_fn`/`read_fn` on every curator and reader.
Real collaborators resolve their clients *lazily on first call*, never at import - "Importing this module must never perform network I/O" (`src/polymerhus/recon/domain/pod.py:8-12`), and `curate` resolves `neo4j_client.merge` inside the function body (`src/polymerhus/recon/domain/curator.py:248-250`).

**Standard.**
A module that talks to Neo4j, an LLM, or the execution substrate exposes that collaborator as an injectable parameter with a lazily-resolved production default.
Importing a module performs no I/O and requires no env var.
This is the enforcement surface of the unit-tier boundary (Section 10).

---

## 7. Extension points that are easy to work on

**Principle.** Adding a parser, a System kind, a data-relationship edge type, an anatomy skill, or a steering tool is a bounded, low-friction edit - one data addition or one registry entry, never a schema migration or a cross-cutting change.

**DDD rationale.** The model grows by extending a controlled vocabulary, not by re-opening the aggregate.
An extension point is where the ubiquitous language admits a new term cheaply.

**Grounded examples.**

- **A parser**: add one entry to the `PARSERS` registry (`src/polymerhus/recon/domain/parsers/__init__.py:17-38`); `get_parser(tool)` and the whole pod path pick it up. The signature-aware dispatch means a findings-parser that wants `target_url` is handled without touching the caller (`src/polymerhus/recon/domain/pod.py:55-63`).
- **A System kind**: add one `(kind, description)` tuple to `SYSTEM_KINDS` (`src/polymerhus/analysis/l1_curator.py:83-97`) - "Extending it is a one-line data edit here - never a schema migration". The same constant validates a proposal, drives the sweep prompt, and renders into the analyser's `vocabulary_prompt` (`src/polymerhus/analysis/l1_curator.py:152-171`), so it never drifts.
- **A data-relationship edge type**: add one tuple to `DATA_RELATIONSHIP_KINDS` (`src/polymerhus/analysis/l1_curator.py:105-112`); the kind *is* the uppercased edge type, single-sourced into `_DATA_REL_EDGE_TYPES` (`src/polymerhus/analysis/l1_curator.py:116`).
- **A findings tool**: add one entry to `_FINDINGS_MODULES` (`src/polymerhus/recon/domain/pod.py:39-42`).

**Standard.**
When you add a term to a controlled vocabulary, add it to the *single source of truth* constant so validation, the LLM prompt, and any sweep all update together.
If adding a kind requires editing more than one place, the vocabulary is not yet single-sourced - fix that first.

---

## 8. Reuse as much as possible

**Principle.** One behaviour has one implementation; a second caller reuses it rather than copying it.

**DDD rationale.** Duplication of domain logic is duplication of the model, and the two copies drift into contradiction.

**Grounded examples.**

- The `httpx_reprofile` job reuses `parse_httpx` verbatim - "Reuse, not duplication" (`src/polymerhus/recon/domain/parsers/__init__.py:19-21`).
- `_write_each` (`src/polymerhus/analysis/l1_curator.py:608-624`) is the one fail-open write loop reused by every enrichment builder (`src/polymerhus/analysis/l1_curator.py:643-647`).
- `_identity_clause` builds the deterministic sorted-key MERGE fragment reused across both curators (`src/polymerhus/recon/domain/curator.py:111`, `src/polymerhus/analysis/l1_curator.py:188`).
- `vocabulary_prompt` (`src/polymerhus/analysis/l1_curator.py:152`) renders the same allowlist constants the builders validate against, so the LLM is told exactly the values the writer will accept.
- The scope filter runs once at the curator chokepoint so "one rule here covers ALL tools" (`src/polymerhus/recon/domain/curator.py:254-255`, `_promote_seed_domain` at `src/polymerhus/recon/domain/curator.py:207-223`).

**Standard.**
Before writing a loop, a clause builder, or a prompt fragment, look for the existing one.
A single chokepoint that every caller funnels through (the curator, `_write_each`, `fill_template`) is the reuse pattern to prefer over a per-caller special case.

---

## 9. Idempotency and provenance-on-write

**Principle.** Every write is an idempotent `MERGE` on a stable intrinsic identity key, and every node and edge records who or what produced it, stamped by the writer and never by the proposer.

**DDD rationale.** Identity is the definition of an entity - two things are the same iff their intrinsic key matches - and re-derivation must converge rather than duplicate.
Provenance is what lets "an LLM said so" and "a tool measured it" be different kinds of fact in one graph (`domain-model.md` §3.1).

**Grounded example.**
`identity ⊥ membership` (`L1D-11`): a unit is keyed on what it *is* (business function, mechanism kind), never on what it *contains* (`src/polymerhus/analysis/l1_curator.py:15-19`).
A Service is keyed on `(project_id, business_function_slug)`; a System on `(project_id, kind, discriminator)` with the non-null `__singleton__` sentinel so a null discriminator cannot silently duplicate a singleton (`L1D-9`).
Provenance (`prov_job`/`prov_model`/`prov_prompt_id`) and `first_seen`/`last_seen` are stamped on every write, `ON CREATE` for first-seen and refreshed on every touch (`src/polymerhus/analysis/l1_curator.py:184-185, 220-226`), which is what lets the stores be re-derived rather than migrated.

**Standard.**
Every `MERGE` keys on identity, never on the member set.
`discriminator` defaults to the literal `"__singleton__"`, never null.
The writer stamps provenance; if a proposal tries to set a reserved key it is stripped (`_RESERVED_PROPS`, `src/polymerhus/analysis/l1_curator.py:139-142`).
These are binding invariants - see `loop-constraints.md`, "Invariants that must hold on every write (FR-NFR)".

**Honest debt.**
Idempotent identity holds only within a `project_id`; cross-run canonical identity is an open primitive (two identical runs shared only 41% of service identities, `AMV-12/AMV-13`, `domain-model.md` §3.4).
Do not assume a slug is stable across runs of the same target.

---

## 10. The testing boundary - the unit tier must not touch a database

**Principle.** The unit tier mocks Neo4j, and this is enforced at runtime, not by convention.
A test that genuinely needs a live database goes in `tests/integration/` or `tests/e2e/`, never in the unit tree behind a skip gate.

**DDD rationale.** The point of the pure-builder / injectable-collaborator design (Sections 3, 6) is that the model is exercisable in memory; the test boundary is where that design pays off.

**Grounded example.**
`tests/conftest.py` raises on any live Neo4j access from an unmarked test, including via the raw `_driver` attribute - the driver guard is load-bearing because `pipeline.read_steering_signals` reaches past the helpers with `neo4j_client._driver` (`testing-strategy.md` §2).
Every module supports injecting a fake `read_fn`/`merge_fn`/`exec_fn`, which is exactly why the unit tier can stay the largest (~890 tests) and laptop-runnable.

**Standard.**
If a unit test seems to need a database, the test is misplaced or the injectable seam is missing - fix one of those, never reach for the live driver.
A SKIP is a silent failure with good manners: when a gated test skips, verify the gate before believing it (`loop-constraints.md`; a broken gate once hid a whole tier and a permanently-dead test).
Never disable, skip, or weaken a test to go green.
Full tiers and run procedure: `docs/design/testing-strategy.md`.

---

## 11. Maker / checker

**Principle.** The agent (or developer) that writes a change never marks its own work done; a separate checker reproduces the evidence and approves.
The discipline appears twice: at the data boundary and at the development-loop boundary.

**DDD rationale.** A claim means nothing until an independent authority has validated it - the same reason the sole-writer is the mechanical checker of every proposal (Section 4).

**Grounded example.**
At the data boundary: the proposer is the maker, the sole-writer is the mechanical checker of shape, identity, and vocabulary; and the designed-not-built `auditor` (`AMV-16`, `CONTEXT.md` Analysis) would move that checker upstream to vet proposals *before* they are written.
At the loop boundary: the implementer sub-agent writes, a separate `loop-verifier` runs the assertions and approves, and "the implementer may NEVER mark its own work done" (`loop-constraints.md`, "Code & loop discipline").

**Standard.**
Report and plan first, then implement one bounded area, then have a separate checker verify.
Debug with reproduce -> minimal root cause -> smallest diff -> rerun; one problem per fix, no drive-by refactors.
Integration follows `docs/agents/issue-tracker.md`: a verifier approval authorises opening the PR; merging to `main` is a human action.

---

## 12. Designed-not-built is named, never faked

**Principle.** Where the ontology leads the code, the gap is stated explicitly at the seam - a reserved-but-dormant registration, a designed node that the MVP fence asserts does not exist - and never papered over as if it were live.

**DDD rationale.** An honest model names its holes; false closure is worse than an open question (`domain-model.md` §8).

**Grounded example.**
`configurator`/`job_orchestrator` are registered but dormant proposer seams (`src/polymerhus/app/llm/providers.py:14`, `CONTEXT.md` Recon); `asset_context` is threaded end-to-end but is always the empty string (`CONTEXT.md` Recon, line 109-111); the `FaultHypothesis` node and its `POSITS_FAULT_AT` edge are modelled in the ontology but designed-not-built and name-not-ratified (`CONTEXT.md` Analysis, `NM-8`); `SystemAspect` is designed but the MVP fence asserts no such node exists (`L1D-16`, `NM-3`).

**Standard.**
When you scaffold ahead of a capability, mark the seam `designed-not-built` in code and in the relevant CONTEXT/STATE record, and make the dormant path inert (an empty string, a no-op default), never a silent half-implementation.
A no-op checker that rots undetected is a real hazard the model has already suffered (the broken curation stage, `domain-model.md` §5).

---

## Appendix - the enforcement surfaces

This standard is prescriptive; these documents are where the rules are checked or made true.

| Concern | Owning document |
|---|---|
| Binding write invariants (idempotent MERGE, `identity ⊥ membership`, provenance, fail-open, traversal-then-fetch, sole-writer) | `loop-constraints.md` |
| Testing tiers and the DB boundary | `docs/design/testing-strategy.md` |
| The reasoned ontology every term derives from | `docs/design/domain-model.md` |
| Bounded contexts and per-context glossaries | `CONTEXT-MAP.md`, `src/polymerhus/recon/CONTEXT.md`, `src/polymerhus/analysis/CONTEXT.md`, `src/polymerhus/project_management/CONTEXT.md` |
| Layer-0 pipeline architecture | `docs/design/recon-pipeline-design.md` |
| Layer-1 model catalogue | `docs/design/l1-domain-model-catalogue.md` |
| Development-workflow ledger (what was built, learned, deferred) | `STATE.md` |
