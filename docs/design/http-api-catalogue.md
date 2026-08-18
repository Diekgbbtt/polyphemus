# The polymerhus HTTP API - endpoint catalogue

Single source of truth for the agent's HTTP surface. Everything a client can call lives here; a route that is not in this catalogue is either a mistake or must be added to it in the same change that introduces it.

**Serving:** `app/main.py` builds the FastAPI app, mounts the project-management router (`project_management/api.py`), and defines `/health` directly. The agent listens on port 8080 (published to the host as `localhost:8080`).

## Route index

| Method | Path | Auth | Body | Success | Errors | Handler |
|---|---|---|---|---|---|---|
| `POST` | `/projects` | none | `{name: str}` | 200 `{project_id}` | - | `create_project` |
| `GET` | `/projects` | none | - | 200 `{projects: [...]}` | - | `list_projects` |
| `GET` | `/projects/{project_id}/graph` | none | - | 200 graph payload | 404 unknown project | `project_graph` |
| `GET` | `/runs` | none | - | 200 `{runs}` (status=running only) | 400 `status != running` | `list_runs` |
| `PUT` | `/projects/{project_id}/settings` | none | `{recon: {target_seed, auth_context, feature toggles...}}` | 200 settings | 404 unknown project | `update_settings` |
| `POST` | `/projects/{project_id}/recon` | none | `ReconLaunch {jobs?, settings?, with_analysis=true}` | 200 `{run_id}` | 404 unknown project; 400 invalid jobs / targetless | `launch_recon` |
| `POST` | `/projects/{project_id}/recon/{run_id}/stop` | none | - | 200 `{run_id, stopping}` | 503 runtime inactive; 404 unknown run | `stop_recon` |
| `GET` | `/projects/{project_id}/recon/{run_id}` | none | - | 200 run status | 404 unknown run | `get_recon_status` |
| `POST` | `/projects/{project_id}/analysis` | none | `AnalysisLaunch {run_id}` | 200 analysis dispatch | 503 runtime inactive | `launch_analysis` |
| `POST` | `/projects/{project_id}/analysis/{run_id}/stop` | none | - | 200 graceful-stop ack | 503 runtime inactive | `stop_analysis_run` |
| `GET` | `/projects/{project_id}/analysis/{run_id}` | none | - | 200 analysis-run status | 404 unknown run | `get_analysis_status` |
| `POST` | `/projects/{project_id}/bootstrap` | none | `{operator_kb?}` | 200 skeleton counts | 503 fail-closed block | `bootstrap_project` |
| `POST` | `/projects/{project_id}/hunting` | none | `HuntingLaunch {candidates?}` | 201 `{hunting_run_id}` | 404 unknown project; 503 control plane not landed | `launch_hunting` |
| `POST` | `/projects/{project_id}/hunting/{hunting_run_id}/stop` | none | - | 200 `{hunting_run_id, stopping}` | 404 unknown run | `stop_hunting_run` |
| `GET` | `/projects/{project_id}/hunting/{hunting_run_id}` | none | - | 200 `{status}` | 404 unknown run | `get_hunting_status` |
| `GET` | `/health` | none | - | 200 `{postgres, neo4j, kali_mcp}` checks | - | `health` (in `main.py`) |

## Module-lifecycle surface (#118/#121)

The runtime manager owns the lifecycle verbs (`pause` / `resume` / `drain`) as in-process verbs in `app/runtime.py`. The HTTP surface exposes them per module so an operator can drive the runtime plane over the wire:

| Method | Path | Body | Success | Errors |
|---|---|---|---|---|
| `POST` | `/projects/{project_id}/modules/{module}/pause` | - | 200 `{module, state}` | 404 unknown module; 503 runtime inactive |
| `POST` | `/projects/{project_id}/modules/{module}/resume` | - | 200 `{module, state}` | 404 unknown module; 503 runtime inactive |
| `POST` | `/projects/{project_id}/modules/{module}/drain` | - | 200 `{module, state}` | 404 unknown module; 503 runtime inactive |

`module` is one of `recon` / `analysis` / `hunting`. Pause of a stopped module and resume of a non-paused module are safe no-ops that still report the current state (the runtime verb's own semantics). Drain settles the module to `stopped` (archive via flush hook) and is the only lifecycle verb that changes run state durably.

## Seam notes

- Every handler is a thin HTTP adapter over the `repository` use-case layer (project-management) or the runtime manager (`app/runtime.py`); domain errors map to status codes (`ProjectNotFound`/`RunNotFound` -> 404, `ValueError` -> 400, no active runtime -> 503).
- The lifecycle handlers route through `runtime.pause/resume/drain` and must never touch the worker loop directly (the two sanctioned verbs only).
- This catalogue is the reference the module-runtime e2e tier asserts against (module-runtime-assertions.md C16/C17 and the pause/resume/drain walkthroughs).
