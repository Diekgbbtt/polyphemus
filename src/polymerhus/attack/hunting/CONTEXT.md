# Context: Hunting (vuln-testing) - designed-not-built

*Status: **designed-not-built**. Terse glossary seed; the reasoned design is `docs/design/hunting-system-design.md`, and the open decisions are the wayfinder map [#54](https://github.com/Diekgbbtt/polyphemus/issues/54). Terms marked provisional are not yet ratified.*

Hunting configures and dispatches; a test-executor pod executes. Only the former is in scope.

## The agent hierarchy

- **hunt-orchestrator** (planner) - selects candidates, configures, dispatches, holds memory + budget.
- **hunting agent** (N = 1 in phase 1; per-symptom in phase 2) - a typed agent with a parametrised prompt template over a declarative `HuntConfig`; writes rich `TestImplementationSpec`s.
- **test-executor pod** - a small cooperative agent team that executes a spec against the live target and returns `{verdict, evidence}`. **Stub only** in this effort (typed handoff + one trivial real run); cooperative-team internals are out of scope.

## Provisional terms

- **HuntCandidate** (provisional) - a `(service/system, fault-class)` pair, identity-bound to the L1 unit; the phase-2 requirement-fault-at-a-locus. The *unit of selection/knowledge*.
- **Hunt** (provisional) - a configured + dispatched hunting agent, minted per symptom; the *unit of work*. One candidate fans out into N hunts.
- **Fault-class grammar** (provisional) - fault-classes authored as `fault -> symptom(s) -> probing-technique(s) -> applies-if(predicate)`, the phase-2 three-kind grammar (`DD-13`), even though phase 1 consumes only the flat projection.
- **HuntConfig** (provisional) - the declarative config the hunting agent consumes: five identity-bound handles (wide surface context, fault KB, target caveats, prior-hunt insights, fault-targeting tools).
- **FaultSource** (provisional) - the swappable selection interface `f(L1 model) -> {(unit, fault, symptom, applies-witnesses)}`; phase-1 body = necessary-only prefilter + LLM validation, phase-2 body = anatomy abduction.
- **TestImplementationSpec** (provisional) - the hunting agent's output: the concrete test procedure covering the low-level techniques; the executor-pod input.
- **Hunt store** (provisional) - a separate store (**not** neo4j) holding candidates, configs, hunts, results, and the hunt-orchestrator memory; references L1 by identity, never mints L0/L1 nodes.
- **Revival key** (provisional) - `(unit_identity, fault_class, symptom, failed-precondition?)`; persists prior-hunt insight and drives change-driven re-test (`DD-26`).

## Reused seams (already built)

- Interface Agreement B / backward-recon - `recon/control/targeted.py` (`AnalyserReconRequest`, `request_targeted_recon`); the typed information-need -> job back-edge, extended with a hunting `origin`.
- Pod template + `{verdict, ...}` single export - `recon/domain/pod.py`.
- Job registry pattern (for the tool registry) - `recon/control/jobs.py::JobSpec`.
- Index-card projection (the surface-context budget rule) - `analysis/index_card.py`.
