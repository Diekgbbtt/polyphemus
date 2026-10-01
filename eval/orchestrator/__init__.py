"""The eval orchestrator: EvalSetup, instances, targets, routing, and the gate.

`python -m orchestrator plan|up|down|status <setup.yaml>` drives one
`EvalSetup` (D1/D4); `python -m orchestrator trial <setup.yaml> <instance>
<target>` drives one `TargetRun` from its phase entry to terminal through the
trial engine (`orchestrator.trial`, #270): phase-entry predicates over
persisted state, setup-outcome chaining, launch/poll within a budget, and the
hunting cap. `assess`/`close-verify` (#271) dispatch the background assessment
subagent and run the eval-close presence/schema verification with
re-dispatch and a bounded micro-diagnosis; `diagnose` (#272) dispatches the
diagnoser subagent and `issue-search` exposes the read-only issue bank;
`store render-sync`/`store materialize` (#273) render the one-way artifact
sync and assemble the self-contained per-trial tree. `monitor` (#289) is the
tick-based post-execution control plane (`orchestrator.monitor`): one sweep
verifies every trial's execution state and advances the workflow one node - a
successful execution dispatches the assessment, a present `verdicts.yaml`
dispatches the diagnoser, and a present, paired `diagnoses.yaml` completes the
trial. `align` (#274) asserts the
advance delta the daemon emitted, decides the alignment action through an agent
turn (`orchestrator.alignment`), executes it, or escalates and writes a hold
that blocks `up`/`trial` until `alignment resolve` records the operator's
decision. `surfer` (#275) is the background supervisor (`orchestrator.surfer`):
it asserts the environment state (app-state plus the persisted cap/failed-run
evidence plus a failure-signal classifier), prompts the orchestrator, and
resolves exactly one bounded lifecycle decision - terminate, destroy, or a
configuration/data-layer fix that restarts and resumes - escalating anything
else into the same hold mechanism. The package is a pure symbolic layer: every
external effect (ssh, docker, compose, git worktree, the env preflight, the REST
calls, the assessment/diagnoser/alignment/surfer subagents) is a
`Command`/`ApiCall` run by an injected runner, and `plan()` builds the whole
effect list without a runner. Importing this package performs no I/O
(CODING_STANDARD section 6).
"""
