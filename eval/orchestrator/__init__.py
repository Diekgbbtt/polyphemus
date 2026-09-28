"""The eval orchestrator: EvalSetup, instances, targets, routing, and the gate.

`python -m orchestrator plan|up|down|status <setup.yaml>` drives one
`EvalSetup` (D1/D4); `python -m orchestrator trial <setup.yaml> <instance>
<target>` drives one `TargetRun` from its phase entry to terminal through the
trial engine (`orchestrator.trial`, #270): phase-entry predicates over
persisted state, setup-outcome chaining, launch/poll within a budget, and the
hunting cap. The package is a pure symbolic layer: every external effect (ssh,
docker, compose, git worktree, the env preflight, the REST calls) is a
`Command`/`ApiCall` run by an injected runner, and `plan()` builds the whole
effect list without a runner. Importing this package performs no I/O
(CODING_STANDARD section 6).
"""
