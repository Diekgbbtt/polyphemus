# Context Map

polymerhus is an autonomous web-application vulnerability-discovery system.
Its domain vocabulary splits along one hinge: the boundary between what the tooling **observes** about a target's attack surface (Layer 0) and what an analyst-role LLM **judges** that surface to mean (Layer 1); a third layer **reasons adversarially** over that persisted substrate (Layer 2).
The per-context glossaries below are terse lookups derived from the canonical ontology in `docs/design/domain-model.md`; the ontology is the reasoning, each `CONTEXT.md` is the index.

Recon, Analysis and Project-management are physical modules under `src/polymerhus/`. Attack (Layer 2) is a fourth core context whose package exists under `src/polymerhus/attack/`, with the hunting submodule built (phase-1) and the exploit submodule a designed-not-built filesystem linchpin (`CODING_STANDARD.md` §12).

- [Recon](./src/polymerhus/recon/CONTEXT.md) - Layer-0 descriptive attack-surface discovery: the observed node types, the adversarial Observation, and the pipeline that produces them (Run, Job, Phase, Pod, the L0 curator, the triager, the configurator).
  Internally layered into a **control** sub-package (the orchestration: pipeline, jobs, job_agent, orchestrator_agent, auth, batching, async_bridge, scope, steering, targeted) over a **domain** sub-package (the model and the L0 sole-writer: curator, types, findings, pod, graph_read, selectors, noise_filter, skills, parsers), plus `crawl/`.
- [Analysis](./src/polymerhus/analysis/CONTEXT.md) - Layer-1 interpretive abstraction: the reconstructed Service / System / DataItem model, the typed cross-layer and intra-L1 edges, the L1 sole-writer, and the reasoning vocabulary (provenance, confidence, the judgment envelope, the escalating epistemic ladder).
  It also owns the **agent-configuration eval** (`evaluation.py`): because its agents are non-deterministic LLM proposers, judging one configuration against another is a comparative, repeated-run measurement rather than a pass/fail assertion, and that measurement is part of the context's own vocabulary.
- [Attack](./src/polymerhus/attack/CONTEXT.md) - Layer-2 adversarial reasoning: a core module and a new **phase** after recon and analysis, whose hunting submodule is **built (phase-1)**. It reads the modelled L1 abstraction and the collected L0 surface as a published substrate and reasons *over* them; it never writes into the L0/L1 graph (the fault-hypothesis is a phase-3 primitive, never a graph node). It splits into two deep submodules - **[hunting](./src/polymerhus/attack/hunting/CONTEXT.md)** (aka *vuln-testing*: selects `(service/system, fault-class)` candidates, configures and dispatches hunting agents that emit test-implementation specs run by a stub test-executor pod) and **[exploit](./src/polymerhus/attack/exploit/CONTEXT.md)** (capability -> impact chaining, linchpin only, designed-not-built, out of scope for the current effort).
- [Project-management](./src/polymerhus/project_management/CONTEXT.md) - the operator-intent surface: the Project / settings / run-request lifecycle. It LAUNCHES recon (a lazy call, never an eager import) and reads/writes Project and settings state through the shared Postgres gateway; it never sits under recon.

## Relationships

- **Recon -> Analysis (supplier / consumer, the L0/L1 hinge)**: Recon is the upstream supplier; it writes the L0 attack-surface graph and never reads Layer 1.
  Analysis is the downstream consumer; it treats the L0 graph as a published, read-only substrate and anchors every judgment back onto it.
  The crossing is carried by three cross-layer edges - `AGGREGATES`, `SURFACES_AT`, `EVIDENCED_BY` - which point from an L1 (judged) node down onto an L0 (observed) node and are `MATCH`ed, never `MERGE`d, so the interpretive writer can never mint a descriptive node.
  `AGGREGATES` is the load-bearing hinge: it carries a Service's assignment judgment ("I judge element e belongs to service S, this confident, on this evidence") from the observed store into the judged store.
- **Analysis -> Attack (supplier / consumer, the L1/L2 hinge)**: Analysis is the upstream supplier of the judged model; Attack is the downstream consumer that treats both the L1 abstraction and the L0 surface as a published, read-only substrate.
  Attack reasons over that substrate into its own separate hunt store (**not** neo4j), referencing L1 units by identity and never minting L0/L1 nodes.
  It reuses the backward-recon back-edge (`recon/control/targeted.py`) to raise typed information-needs, extended with a hunting `origin`.
- **Shared but context-owned**: cross-context terms get their full entry in the owning context and at most a one-line pointer in the other.
  `Observation`, `Project`, `Domain`/`Endpoint`/`Parameter` and the rest of the L0 node set, and the sole-writer principle are owned by Recon; the epistemic-reasoning cluster (provenance, confidence, evidence, identity, staleness, defeasibility) is owned by Analysis even where the L0 curator also stamps provenance and merges on identity.

## Context boundaries realised (2026-07)

Recon, Analysis and Project-management are now physically separate packages under `src/polymerhus/` (the `src/` restructure, `docs/design/module-restructure.md`); Attack later joined them as a physical package, its hunting submodule built (phase-1) and its exploit submodule still a designed-not-built linchpin.
Two boundaries that this map long anticipated have landed:

- **Analysis** was extracted from under `recon/analysis/` to its own top-level module; its only structural tie to recon is the published L0 vocabulary in `recon.domain.types` (the anti-corruption seam).
- **Project-management** was minted from the operator surface that had been scattered across the API layer and the Postgres gateway. Run/Job/Phase remain recon vocabulary (they are elements of the recon pipeline, per the operator's ruling); project-management owns the operator's INTENT over runs (create project, configure settings, request a run, poll status), not the pipeline that executes them.

## Helper modules (shared infrastructure, never their own context)

**neo4j**, **postgres**, **mcp**, and **llm-client** are NOT bounded contexts and will not become independent modules.
Following the domain-driven paradigm, they are shared/helper infrastructure - the technical supporting layer (a shared kernel) - inherently coupled to the domain modules that consume them.
They carry no independent ubiquitous language of their own; the meaning of what they persist, execute, or invoke belongs to the Recon, Analysis, Project-management (and future Attack) contexts that use them.
They therefore never get a `CONTEXT.md`, and no glossary should be minted for them (operator's explicit ruling).
The **session seam** (the stateful-agent runtime: `app/llm/session.py`, `session_address.py`, `checkpoints.py`, `actor.py`, `#94`) is the one technical-support surface with real domain content - its typed `SessionAddress` value objects ARE domain concepts (a session's collision-free instance identity), owned per module (`AnalysisSession`/`PodSession`/`HuntSession`) and reasoned in `domain-model.md` §3.7 - so the seam gets ontology coverage without ever becoming a bounded context of its own.

## Where the architecture and workflow live

This map and the per-context `CONTEXT.md` files are pure glossary.
Architecture and development-workflow detail are linked, never duplicated:

- `docs/design/domain-model.md` - the canonical reasoned ontology every term here is derived from.
- `docs/design/llm-role-architecture-agent-prompt.md` - RATIFIED 2026-08-07 (#93/#94): the role record, the one_shot-vs-session turn-mode axis, the three-axis agent model, the collision-free session addressing, and the stateful migration ledger. The ontology home of the session concept is `domain-model.md` §3.7.
- `docs/design/recon-pipeline-design.md` - the Layer-0 recon pipeline architecture.
- `docs/design/l1-domain-model-catalogue.md` - the Layer-1 model catalogue (supersedes parts of `service-system-model-design_1.md`).
- `docs/design/hunting-system-design.md` - the Layer-2 hunting submodule abstract-overview spec (phase-1); open decisions live on the wayfinder map [#54](https://github.com/Diekgbbtt/polyphemus/issues/54).
- `docs/design/evolution-paradigm.md` - the phase-1 -> phase-2 evolution contract the attack module must stay recyclable toward; `docs/design/threat-modeling-system-design.md` - the phase-2 target.
- `STATE.md` - the development-workflow ledger: what was built, what each loop learned, what is deferred.
- `docs/agents/` - the agent operating docs (domain, issue-tracker, triage-labels).
