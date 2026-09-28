"""The eval orchestrator: EvalSetup, instances, targets, routing, and the gate.

`python -m orchestrator plan|up|down|status <setup.yaml>` drives one
`EvalSetup` (D1/D4). The package is a pure symbolic layer: every external
effect (ssh, docker, compose, git worktree, the env preflight) is a `Command`
run by an injected `CommandRunner` (`orchestrator.commands`), and `plan()`
builds the whole command list without a runner. Importing this package performs
no I/O (CODING_STANDARD section 6).
"""
