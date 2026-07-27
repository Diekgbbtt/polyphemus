# Context Map

polymerhus is an autonomous web-application vulnerability-discovery system.
Its domain vocabulary splits along one hinge: the boundary between what the tooling **observes** about a target's attack surface (Layer 0) and what an analyst-role LLM **judges** that surface to mean (Layer 1).
The per-context glossaries below are terse lookups derived from the canonical ontology in `docs/design/domain-model.md`; the ontology is the reasoning, each `CONTEXT.md` is the index.

All three contexts are now physical modules under `src/polymerhus/`.

- [Recon](./src/polymerhus/recon/CONTEXT.md) - Layer-0 descriptive attack-surface discovery: the observed node types, the adversarial Observation, and the pipeline that produces them (Run, Job, Phase, Pod, the L0 curator, the triager, the configurator).
  Internally layered into a **control** sub-package (the orchestration: pipeline, jobs, job_agent, orchestrator_agent, auth, batching, async_bridge, scope, steering, targeted) over a **domain** sub-package (the model and the L0 sole-writer: curator, types, findings, pod, graph_read, selectors, noise_filter, skills, parsers), plus `crawl/`.
- [Analysis](./src/polymerhus/analysis/CONTEXT.md) - Layer-1 interpretive abstraction: the reconstructed Service / System / DataItem model, the typed cross-layer and intra-L1 edges, the L1 sole-writer, and the reasoning vocabulary (provenance, confidence, the judgment envelope, the escalating epistemic ladder).
  It also owns the **agent-configuration eval** (`evaluation.py`): because its agents are non-deterministic LLM proposers, judging one configuration against another is a comparative, repeated-run measurement rather than a pass/fail assertion, and that measurement is part of the context's own vocabulary.
- [Project-management](./src/polymerhus/project_management/CONTEXT.md) - the operator-intent surface: the Project / settings / run-request lifecycle. It LAUNCHES recon (a lazy call, never an eager import) and reads/writes Project and settings state through the shared Postgres gateway; it never sits under recon.

## Relationships

- **Recon -> Analysis (supplier / consumer, the L0/L1 hinge)**: Recon is the upstream supplier; it writes the L0 attack-surface graph and never reads Layer 1.
  Analysis is the downstream consumer; it treats the L0 graph as a published, read-only substrate and anchors every judgment back onto it.
  The crossing is carried by three cross-layer edges - `AGGREGATES`, `SURFACES_AT`, `EVIDENCED_BY` - which point from an L1 (judged) node down onto an L0 (observed) node and are `MATCH`ed, never `MERGE`d, so the interpretive writer can never mint a descriptive node.
  `AGGREGATES` is the load-bearing hinge: it carries a Service's assignment judgment ("I judge element e belongs to service S, this confident, on this evidence") from the observed store into the judged store.
- **Shared but context-owned**: cross-context terms get their full entry in the owning context and at most a one-line pointer in the other.
  `Observation`, `Project`, `Domain`/`Endpoint`/`Parameter` and the rest of the L0 node set, and the sole-writer principle are owned by Recon; the epistemic-reasoning cluster (provenance, confidence, evidence, identity, staleness, defeasibility) is owned by Analysis even where the L0 curator also stamps provenance and merges on identity.

## Context boundaries realised (2026-07)

The three contexts above are now physically separate packages under `src/polymerhus/` (the `src/` restructure, `docs/design/module-restructure.md`).
Two boundaries that this map long anticipated have landed:

- **Analysis** was extracted from under `recon/analysis/` to its own top-level module; its only structural tie to recon is the published L0 vocabulary in `recon.domain.types` (the anti-corruption seam).
- **Project-management** was minted from the operator surface that had been scattered across the API layer and the Postgres gateway. Run/Job/Phase remain recon vocabulary (they are elements of the recon pipeline, per the operator's ruling); project-management owns the operator's INTENT over runs (create project, configure settings, request a run, poll status), not the pipeline that executes them.

## Helper modules (shared infrastructure, never their own context)

**neo4j**, **postgres**, **mcp**, and **llm-client** are NOT bounded contexts and will not become independent modules.
Following the domain-driven paradigm, they are shared/helper infrastructure - the technical supporting layer (a shared kernel) - inherently coupled to the domain modules that consume them.
They carry no independent ubiquitous language of their own; the meaning of what they persist, execute, or invoke belongs to the Recon and Analysis (and future Project-management) contexts that use them.
They therefore never get a `CONTEXT.md`, and no glossary should be minted for them (operator's explicit ruling).

## Where the architecture and workflow live

This map and the two `CONTEXT.md` files are pure glossary.
Architecture and development-workflow detail are linked, never duplicated:

- `docs/design/domain-model.md` - the canonical reasoned ontology every term here is derived from.
- `docs/design/recon-pipeline-design.md` - the Layer-0 recon pipeline architecture.
- `docs/design/l1-domain-model-catalogue.md` - the Layer-1 model catalogue (supersedes parts of `service-system-model-design_1.md`).
- `STATE.md` - the development-workflow ledger: what was built, what each loop learned, what is deferred.
- `docs/agents/` - the agent operating docs (domain, issue-tracker, triage-labels).
