# Context Map

polymerhus is an autonomous web-application vulnerability-discovery system.
Its domain vocabulary splits along one hinge: the boundary between what the tooling **observes** about a target's attack surface (Layer 0) and what an analyst-role LLM **judges** that surface to mean (Layer 1).
The per-context glossaries below are terse lookups derived from the canonical ontology in `docs/design/domain-model.md`; the ontology is the reasoning, each `CONTEXT.md` is the index.

## Contexts

- [Recon](./agent/recon/CONTEXT.md) - Layer-0 descriptive attack-surface discovery: the observed node types, the adversarial Observation, and the pipeline that produces them (Run, Job, Phase, Pod, Project, the L0 curator, the triager, the configurator).
- [Analysis](./agent/recon/analysis/CONTEXT.md) - Layer-1 interpretive abstraction: the reconstructed Service / System / DataItem model, the typed cross-layer and intra-L1 edges, the L1 sole-writer, and the reasoning vocabulary (provenance, confidence, the judgment envelope, the escalating epistemic ladder).

## Relationships

- **Recon -> Analysis (supplier / consumer, the L0/L1 hinge)**: Recon is the upstream supplier; it writes the L0 attack-surface graph and never reads Layer 1.
  Analysis is the downstream consumer; it treats the L0 graph as a published, read-only substrate and anchors every judgment back onto it.
  The crossing is carried by three cross-layer edges - `AGGREGATES`, `SURFACES_AT`, `EVIDENCED_BY` - which point from an L1 (judged) node down onto an L0 (observed) node and are `MATCH`ed, never `MERGE`d, so the interpretive writer can never mint a descriptive node.
  `AGGREGATES` is the load-bearing hinge: it carries a Service's assignment judgment ("I judge element e belongs to service S, this confident, on this evidence") from the observed store into the judged store.
- **Shared but context-owned**: cross-context terms get their full entry in the owning context and at most a one-line pointer in the other.
  `Observation`, `Project`, `Domain`/`Endpoint`/`Parameter` and the rest of the L0 node set, and the sole-writer principle are owned by Recon; the epistemic-reasoning cluster (provenance, confidence, evidence, identity, staleness, defeasibility) is owned by Analysis even where the L0 curator also stamps provenance and merges on identity.

## Anticipated context (named, not yet minted)

**Project-management** is a genuine future bounded context with its own ubiquitous language: the Project/Run/settings/scope lifecycle and the operator's intent surface.
It currently lives inside Recon (Run, Job, Phase, Project are ruled elements of the recon pipeline), but the project-lifecycle vocabulary is a context of its own once the codebase is refactored to separate it (operator's explicit ruling).
No `CONTEXT.md` is minted for it yet; it is recorded here so the terms have a forward home.

`analysis` is not yet a physically independent module - it lives under `agent/recon/analysis/` - but is scheduled to be refactored into one.
Its `CONTEXT.md` is placed now as the anchor for that refactor.

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
