# ADR: the fault-KB data and modules are retired with the selection path (#383)

*Status: DECIDED (T10, 2026-10-19). Closes workbench Q17(a)/R2-7 (the `fault_risk` tier ordering and the orchestrator-side materialisation are withdrawn) and Q39/R2-16 (the hunter-side materialisation is retired fully). Implements S1 9.1's "retire their runtime consumers and record the data-file disposition" and the impact map's data-file disposition row. No runtime consumer remains.*

## Context

The phase-1 fault knowledge base (`data/hunting/fault-kb.yaml`, 170 CWE entries curated offline by `tools/hunting/curate_fault_kb.py`) served two facets:

- the **matching facet**: each entry projected to `fault_source.FaultEntry` for `FaultSource.select`, which minted the hunt-orchestrator's candidate set and fed the `fault_risk` tier ordering; and
- the **materialisation facet**: the per-CWE rich content rendered into the hunter prompt and the gate prompt.

The unit threat model rewrite removed every producer of those facets:

- the run's unit set is the frozen INTAKE over the L1 inventory (`unit_intake`), not a fault selection (T3 #376);
- the modeller hypothesises faults from the trust model, never from an outside repository (tools ADR, R1-5 amendment); and
- the hunter is dispatched per loop with a loop payload, not per config, and the materialisation render retired with the loop-payload rework (T6 #379; Q39/R2-16).

At T10 the only live consumer of the catalogue was the app-boot existence check in `app/main.py`; the selection modules and their tests were dormant. The boot check verified a retired path's artifact at every process start.

## Decision

The fault-KB artifact and its runtime modules are **deleted**, not retained:

| Surface | Disposition |
|---|---|
| `data/hunting/fault-kb.yaml` | Deleted. Recoverable from git history before this change (T10, #383). |
| `attack/hunting/fault_kb.py` (catalogue loader, fold families, materialisation) | Deleted. |
| `attack/hunting/fault_source.py` (the deterministic selection entry) | Deleted. |
| `attack/hunting/fault_risk.py` (the tier-ordering policy) | Deleted; the ordering was withdrawn by Q17(a). |
| `symptom_kb.py` | Already removed by the lightrag merge; no remaining module. |
| The app-boot existence check (`app/main.py`) | Deleted; there is no provisioned hunting artifact to verify at boot. |
| `tools/hunting/curate_fault_kb.py`, `fold_family_view.py`, `migrate_hunting_data_root.py`, the OWASP seed mapping | Deleted with the artifact they produce or address. |
| `tools/hunting/authoring/`, `tools/hunting/portswigger-scrape/` | Retained as the historical curation inputs the #66 design record cites. They are not executable and have no runtime consumer. |
| `data/hunting/fault-kb.yaml` tests and the fault-source e2e walkthrough | Deleted with the modules. |

`predicate.py` (the typed applies-if grammar) and `unit_projection.py` remain: the projection feeds the modeller's grounding, and the grammar is a pure, generic contract with its own tests. Neither reads the catalogue.

The disposition is recorded in `src/polymerhus/attack/hunting/CONTEXT.md` beside the surviving fault-KB terms, and the old #66 design records stand as historical records.

## Consequences

- No boot process depends on a retired hunting artifact.
- The phase-1 fault selection, tier ordering, fold families, and materialisation cannot be revived by amending a data file; a future capability needs a new design and a new artifact (workbench R2-16 records the retirement as final).
- The raw curation inputs remain readable for the #66 history, but the artefact they generated is not in the tree.
