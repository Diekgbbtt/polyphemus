You are continuing implementation of the hunting-agent wiring gap in the polymerhus repo (GitHub issue #110, "Hunting: stateful per-fault-unit orchestration + app-runtime seam wiring" - OPEN). Work in the dedicated worktree `/Users/diekgbbtt/.claude/worktrees/module-runtime-e2e` on branch `feat/module-runtime-e2e`; run all commands there.

# The state you are resuming

The hunting agent (#83) is FULLY BUILT: `src/polymerhus/attack/hunting/hunting_agent.py` implements the complete harness (`build_hunting_agent` returning an async `dispatch_fn(config: HuntConfig, routed=()) -> DispatchResult`, plus `build_sync_hunting_agent`). Its production seams are composed in `src/polymerhus/attack/hunting/llm.py::build_actor_hunting_agent(...)` -> `build_hunting_agent` with per-hunt `HuntingHunterActor` author/judge turns registered per run by `HuntingActorRegistry` (in `actors.py`). The stable system prompt is single-sourced from `skills/hunting/hunting-agent/SKILL.md`.

The orchestration graph (`src/polymerhus/attack/hunting/orchestrator_graph.py`, built by `build_hunting_graph`) is CORRECT: the `_dispatch_node` mints the `HuntConfig` via `mint_hunt_config` BEFORE the dispatch loop, then dispatches per config, and the static edges `_REASON/_BUDGET/_DISPATCH -> supervisor` loop the graph back correctly (hunt_orchestrator.py:216-225).

THE HOLE: `src/polymerhus/attack/hunting/runtime.py::start_hunting` calls `arun_orchestration(project_id, hunting_run_id, candidates or (), tools, **orchestration_kwargs)` WITHOUT passing `dispatch_fn`. In `hunt_orchestrator.py` the dispatch loop does `if dispatch_fn is None: hunt.update({"degraded": True, "error": "hunting agent unavailable"})` and breaks - so every real hunt with candidates degrades immediately and the built hunting agent is NEVER invoked in production. `build_actor_hunting_agent` has ZERO production callers (only `tests/integration/test_hunting_agent_contracts.py` exercises the harness).

# The four properties to verify then satisfy

1. **The workflow graph dispatches the HuntingAgent after building the HuntConfig, and loops back correctly.** The graph structure is verified correct (mint -> dispatch -> back-edge rounds -> return to supervisor). Your change must NOT alter it; it must only ensure `dispatch_fn` reaches the graph.
2. **The hunting agent prompt is sound.** `skills/hunting/hunting-agent/SKILL.md` is the single source, loaded via `_load_hunting_agent_skill`/`skill_for` in hunting_agent.py; `_with_stable_skill` embeds it ahead of every turn. Do not weaken it.
3. **The runtime control-plane underneath is programmed correctly: stateful async actor.** `HuntOrchestratorActor` (actors.py) is the persistent `run_session_agent` per run; `HuntingActorRegistry` owns the per-hunt `HuntingHunterActor`s. Your wiring must keep both - the actor path is the production default (`reason_fn`/`rematch_fn` already default to `_resolve_orchestrator().reason/.rematch`).
4. **Its workflow graph is specified correctly.** `docs/design/hunting-67-orchestrator-spec.md` is the spec; do not change the graph semantics.

# What to implement

1. In `src/polymerhus/attack/hunting/runtime.py::start_hunting`, build the production dispatch seam and pass it through `orchestration_kwargs` (or a new explicit parameter) to `arun_orchestration`:
   - Call `build_actor_hunting_agent(store=..., run_id=hunting_run_id, kb=..., pod=..., checkpointer=..., model_factory=..., observe=...)` -> `(dispatch_fn, registry)`. Resolve `kb` and `pod` the way the harness expects (the symptom-technique KB query seam and the test-executor-pod seam; where no production pod exists yet, a fail-open stub that degrades the hunt rather than crashing - the pod #84 is still the unbuilt seam).
   - Pass `dispatch_fn` (and `kb_retrieve_fn` if the orchestrator's KB join needs it) into `arun_orchestration`.
   - Reap the registry (`registry.stop_all()`) when the run's orchestration finishes - mirror the docstring contract of `build_actor_hunting_agent` ("the caller passes it to run_orchestration/arun_orchestration and reaps the registry when the run's orchestration finishes").
   - Keep the fail-open discipline: a collaborator failure (KB, pod, registry spawn) must degrade to a terminal status, never crash through the control plane.
2. Add/extend tests: at minimum a unit/integration test proving that `start_hunting` with candidates routes through `dispatch_fn` (a fake hunting agent records its invocation and returns a DispatchResult), and that the registry is reaped. Follow the patterns in `tests/integration/test_hunting_agent_contracts.py` and `tests/attack/test_hunting_runtime.py`.
3. Run the unit tier: `pytest tests/attack tests/app -q -p no:cacheprovider` (using `/Users/diekgbbtt/polymerhus/.venv/bin/python`). Ignore the known pre-existing env issues: `tests/test_gateway_reasoning_passthrough.py` collection error (litellm), `tests/test_agent_health.py` hang, and the live-tier docker tests. Never run live-tier tests.

# Doc reconciliation (docs ALREADY corrected by the dispatcher - verify, do not re-edit unless your wiring changes the status)

The dispatcher has already reconciled the doc contradictions in BOTH the main tree and this worktree:
- `src/polymerhus/attack/hunting/CONTEXT.md`: header now says "built (phase-1)" (was "designed-not-built") and explicitly states the wiring gap; the hunting-agent paragraph has a "Wiring status" clause stating the production dispatch seam is NOT yet injected into `start_hunting`.
- `docs/design/statefulness-pattern-matrix.md`: the Hunting table now includes the `build_actor_hunting_agent` -> `build_hunting_agent` dispatch seam row AND a "Hunting-agent wiring status" note stating the harness is built but not wired into the runtime path.

Your obligation: after landing the wiring, these two docs must state the NEW reality - change "NOT yet wired" / "never invoked in production" to the wired state (the seam is injected, the registry is reaped). Update the `statefulness-pattern-matrix.md` file:line for the dispatch seam to your landed invocation point, and drop the now-false "degraded to hunting agent unavailable" wording in `CONTEXT.md` if your wiring removes that default. Do not touch any other doc content.

# Discipline

- Never use the em dash; use a plain dash.
- Never add your agent name as a co-author.
- No code comments unless they explain a non-obvious seam/fail-open decision (match the dense-comment style).
- Do NOT push, do NOT open a PR, do NOT fast-forward into dev. Commit on `feat/module-runtime-e2e`.

# Report back

- Files changed, each mapped to the four properties + the doc status flip.
- The exact seam you wired and how the registry is reaped.
- Test counts/results (targeted suites green, no new failures).
- The commit hash.
- Any residual gaps (e.g. the pod #84 seam still stubbed, KB not production-wired) stated plainly.
