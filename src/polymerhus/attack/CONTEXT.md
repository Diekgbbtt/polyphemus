# Context: Attack (Layer-2 adversarial reasoning)

*Status: **partially built**. The hunting submodule is built (phase-1: candidate selection, the hunt-orchestrator graph engine, the hunting agent, the hunt store, the `hunting_runs` control plane - `#82`, `#110`, `#123`); the exploit submodule remains a designed-not-built linchpin. The package started as a filesystem linchpin (`CODING_STANDARD.md` §12); the design lives in `docs/design/hunting-system-design.md` and the wayfinder map [Hunting (vuln-testing) submodule - design map](https://github.com/Diekgbbtt/polyphemus/issues/54).*

The **attack** context is a core module, peer to Recon (Layer 0, observed) and Analysis (Layer 1, judged), and a new **phase** after them.
Its inputs are the modelled **L1** service/system abstraction and the collected **L0** attack surface.
It reasons *over* that persisted substrate; it does not write into the L0/L1 graph (the fault-hypothesis is a phase-3 primitive, never a graph node - `domain-model.md` §2.6).

It splits into two deep submodules:

- **[hunting](./hunting/CONTEXT.md)** (aka *vuln-testing*) - the built submodule: selects `(service/system, fault-class)` candidates, configures and dispatches hunting agents, which emit concrete test-implementation specs executed by a stub test-executor pod. This is phase-1 **Stage-3 test design** of `docs/design/evolution-paradigm.md`.
- **[exploit](./exploit/CONTEXT.md)** - designed-not-built linchpin only: capability -> impact chaining. Out of scope for the current effort.

## Where the design lives

- `docs/design/hunting-system-design.md` - the hunting submodule abstract-overview spec (phase-1 of the map).
- `docs/design/evolution-paradigm.md` - the phase-1 -> phase-2 evolution contract this module must remain recyclable toward.
- `docs/design/threat-modeling-system-design.md` - the phase-2 target (recursive attack-chain DAG, anatomy abduction, verification pods).
