# RUN NOTE: v2 analysis-unit enrichment - live eval run

## The run

- Trial project: `6c357d47-2b7e-401e-9521-d268f2902365` (eval-comfyui-1), recon run `f3080a97-dce3-493e-92e5-21522a1c22df`.
- Analysis run: `f3080a97-dce3-493e-92e5-21522a1c22df:d8be3a2e`, status `draining` (the service_sourced pass runs, per-Service).
- Hunting run: `c1dd0163-5e7a-4ce0-97ff-a628ee44a096` (started 22:52:42, running - the default-ON chain).
- Deployed code: instance worktree `/opt/polymerhus-dev/eval/instances/eval-server-1` on branch `ph-unitv2`, HEAD `55054aae` + the working-tree patch `/tmp/unitv2.patch` (applied). `EVAL_SHA=55054aae7feff362668da6af5a8774c4716080f9`.
- Settings: `recon.analysis_mode=service_sourced`, `recon.streaming_analysis=true`, `recon.hunt_after_analysis` absent (now default-ON).
- Langfuse keys applied to the instance `.env` (verified equal to the main-worktree keys).
- Launch: `/root/unitv2-trial.sh` (nohup), log `/root/unitv2-trial.log`, runs root `eval/runs-unitv2`.

## Confirmed working

- 24 bootstrapped L1 Services (incl. `comfyui-update`); the assigner logged `chunk=comfyui-update admitted=290 proposed=25 kept=0 out_of_inventory=25` - the per-Service pass runs with the whole surface as its candidate set and the `existing_slugs={slug}` filter (the designed v2 behaviour). This resolves the earlier doubt: `comfyui-update` IS an L1 Service slug, so the log line is the v2 per-Service assigner, not the streamed path.

## Follow-ups the run surfaced

- The per-Service assign filter drops proposals that name ANOTHER owner (`out_of_inventory=25` for `comfyui-update`). If the eval shows this starves ownership, consider widening the assigner's validation set to the full inventory while still feeding ONE Service (it would then be "ground on each Service" without the hard write filter). Measure first.
- LangGraph prints a WARNING on the agent: `Blocked deserialization of polymerhus.analysis.reasoning_workflow.AnalysisTurn - not in allowed_msgpack_modules`. It degrades a resumed thread's stored `AnalysisTurn`. Add the module to `allowed_msgpack_modules` (or `LANGGRAPH_STRICT_MSGPACK=false`) as a follow-up.

## Measurement (when the analysis drains)

Stop condition: the `assigner`/`service_slice` logs stop advancing for all 24 Services, and `analysis_runs.status` transitions to `drained` (or the trial log prints the analysis phase terminal).

```bash
P=6c357d47-2b7e-401e-9521-d268f2902365
# write the Cypher to a file and run via cypher-shell in ph-dd131acc-neo4j-1 (see the transcript)
# C1 endpoint_placement: endpoints aggregated / total
# C2 orphan_services, system_attachment_coverage, system_anchoring_coverage, orphan_systems
# C3 service_recall/precision, dataitem_recall, gt_service_system_exposure
# C4 cached_share, worst-proposer cache, input_uncached, generated_output, capped
curl -s "http://127.0.0.1:8080/projects/$P/usage"
```

Then per `/measure-experiment-results`, append a new comparison section to the cross-version evals document comparing this run against the best latest version (v1 streamed `e2b53777` and v1 batched `79f96b81`), and update the per-target registry.

## v2-run defect fixes (2026-10-12)

Three defects were diagnosed from this run and fixed.

1. **The token cap did not stop the run (project-scoped stop).**
   The trial stopped only the run its poll had launched, so the co-launched analysis kept draining and its drain chained a fresh hunting run (160,727,360 capped against a 4,000,000 budget).
   Fix: a new `POST /projects/{id}/execution/stop` stops EVERY live run of the project in one call (analysis first, then recon, then hunting), and the trial monitor calls it via `api.stop_project` (no per-run-kind or per-mode branch).
   ADR: `docs/design/project-execution-stop-adr.md`.

2. **Checkpoint serde blocked `AnalysisTurn`.**
   Under `LANGGRAPH_STRICT_MSGPACK=true` the analysis reasoning state's `AnalysisTurn` was blocked at load.
   Fix: `app/llm/checkpoints.py::checkpoint_serde()` allow-lists `("polymerhus.analysis.reasoning_workflow", "AnalysisTurn")` at the ONE serde construction point (facade, bounded savers, version saver, pooled PG target); strict mode stays ON.
   ADR: `docs/design/checkpoint-serde-allowlist-adr.md`.

3. **The model was never switched.**
   Only the Langfuse keys were applied to the instance `.env`; every `LLM_<ROLE>` kept the code default `opencode-go:deepseek-v4.1-flash`.
   Fix: the instance `.env` `LLM_<ROLE>` lines are now `opencode-go:muse-spark-1.3-contributor` (no capability override needed); the agent container was recreated and is healthy.

Deployment: the fixed `src/` is in the instance worktree (bind-mounted); the fixed `eval/orchestrator/{trial,api}.py` are in both the instance worktree and the `/opt/polymerhus-dev` checkout, because the trial runs from the latter (`PYTHONPATH=eval`).
Pre-existing test fix: `tests/eval/test_orchestrator_cli.py::test_trial_executes_through_the_injected_api_and_runner` hung (infinite analysis poll) because `_trial_routes()` lacked a route whose status is in the analysis terminal vocabulary; it was hanging at the committed HEAD too.
