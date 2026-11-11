# Iteration E - hunting-only repetition on glm-5.3

## Objective

Repeat the completed iteration-E siyucms eval with one model change:
`opencode-go/glm-5.3` for every LLM role.
Keep the built L0/L1 graph exactly as the rerun left it, drop every hunting
artifact and tracked hunt session, add the reusable threat-model scope fence,
and execute only the hunting module.

The design question is narrow.
Does the same target, the same L0/L1, and the same hunting policy produce a
different hunt when the model is GLM-5.3 and the artificial-defect classes are
fenced out?

## Decisions

| Item | Decision |
|---|---|
| Model | `opencode-go/glm-5.3` for every `LLM_*` role |
| Budget | 7,000,000 capped tokens, the same as the prior run |
| Project | A fresh project id; the source project is never mutated |
| L0/L1 | Copied from the source project's Neo4j graph |
| Hunting artifacts | Not copied: no `hunting/` dir, no `hunting_runs`, no checkpoint thread |
| Auth | Freshly minted admin and member sessions under the new project refs |
| HTTP history | Copied and re-scoped to the new project id |
| Scope fence | The iteration-D verbatim, in `settings.hunting.threat_model_scope` |
| Execution | `orchestrator trial --existing-project-id`, `start_phase: hunting` |

## Model identity

The catalog id is `opencode-go/glm-5.3` (hyphen, not `glm5.3`).
The gateway capability record is `models.dev/opencode-go/glm-5.3`:

| Field | Value |
|---|---|
| `supports_tool_calling` | true |
| `supports_structured_output` | true |
| `reasoning_control` | `effort` |
| `reasoning_efforts` | `low`, `high`, `max` |
| context limit | 1,000,000 |
| output limit | 131,072 |

The A1 resolution is therefore:

- no tools bound -> `json_schema` with `strict=False`;
- tools bound -> `function_calling`;
- `xhigh` (the hunting design roles) -> `max` by nearest-at-least-as-much;
- `high` (the pod roles) -> `high` exactly.

## Live capability preflight

`eval/preflight_llm_capability.py` is the go/no-go gate.
It runs inside the agent image against the live gateway and asserts the real
generation methods, not just the profile:

1. the capability record resolves with a provenance tag and both capabilities;
2. `negotiate_method` returns `json_schema` for no tools and
   `function_calling` for tools;
3. `negotiate_thinking` maps every requested level to an offered form;
4. the production one-shot seam (`invoke_role`) returns a valid `json_schema`
   answer;
5. the one-shot `function_calling` rung returns a valid answer;
6. a live tool loop returns a real `probe_tool` call;
7. a live call per thinking level returns non-empty content.

The first manual run passed all seven checks.
The driver reruns the script and saves the JSON report at
`<runs-root>/preflight.json`; a failure stops the run before any project is
created.

## Duplication

`duplicate_project.py` creates the fresh project and copies only hunting
inputs:

- the L0/L1 graph, with `project_id` replaced on every node and every
  relationship; copied `Observation` nodes get fresh ids because
  `observation_unique` is global;
- `settings.recon` (`operator_kb`, `target_seed`, `application_overview`,
  `streaming_analysis`) and `settings.hunting`;
- the HTTP-history SQLite store and its body blobs, with `flows.project_id`
  rewritten so the search tool sees the evidence;
- the operator auth records, with a newly minted `PHPSESSID` written to both
  `tokens` and `snapshot`, and a new `browser_context.ref` per account;
- the project `authn` skill bundle.

It deliberately does not copy:

- `hunting/` (threat models, hunter specs, pod exports, notes);
- `usage/` (the new trial starts its budget at zero);
- `hunting_runs` or any checkpoints (the new project has no run id, so no
  tracked hunt session);
- the old recon/analysis run rows.

The script asserts the new project has no `hunting/` directory and no
`hunting_runs` row before it returns.

## Scope fence

The verbatim is `scope-fence.txt`, copied unchanged from
`docs/experiments/hunt-enhancement/iteration-d-white-jotter-2026-10-27/ITERATION-D.md`.
The mechanism is the existing `Project.threat_model_scope`:
`PUT /projects/{id}/hunting/config` writes it, the hunting runtime reads it
once at run start, and the threat-modeller turn appends it verbatim under
`## Project scope (verbatim)`.

The fence excludes:

1. rate limiting and every volumetric defence;
2. the plain-text (non-TLS) nature of a channel and any secret it exposes;
3. vulnerabilities that need a preliminary step outside the target's own
   attack surface for client-side code control.

A direction that depends on one is out of scope.
It must not become an assumption, vulnerability, impact row, or threat.
It may be recorded as an evidence note on an interface agreement.

## Run

The driver is `drive_hunt_only.sh`.
It performs the whole sequence:

1. rewrite every `LLM_*` role in the instance `.env` to
   `opencode-go:glm-5.3`;
2. recreate only the agent service so the container sees the env;
3. run the live preflight;
4. duplicate the completed project;
5. run the seeded hunting trial;
6. run the eval monitor, close-verify, store materialization, and measurement.

The trial enters at hunting.
No recon, analysis, or L1 placement runs.
The source project id is `fb865e52-719d-4637-ae7f-e6856f571166`.
The driver writes a fresh project named `eval-siyucms-web-glm53-hunt`.

## Expected artifacts

- `<runs-root>/preflight.json`
- `<runs-root>/driver.log`
- `<runs-root>/siyucms-web/<trial-id>/trial.yaml`
- `verdicts.yaml`, `diagnoses.yaml`, `impact_review.yaml`,
  `measurements.yaml`, `measurements.md`

The hunting-only budget remains the prior 7,000,000 capped tokens.
The prior run stopped on that budget with 14 of 17 threat files never
dispatched, so budget starvation remains a possible outcome and is measured,
not hidden.

## System design references

- `docs/design/capability-adaptive-client-99-spec.md` - the A1 method rungs,
  A2 probe, A5 thinking adaptation, and the E2E tier this preflight implements.
- `docs/design/hunting-67-hunting-agent-spec.md` - the project scope is
  applied at the assumptions layer and appended verbatim.
- `docs/design/impact-assessment-system-spec.md` - the
  `Project.threat_model_scope` field and the REST surface.
- `docs/experiments/hunt-enhancement/iteration-e-siyucms-2026-11-08/ITERATION-E.md`
  - the source run and its measured failure modes.

## Results

Filled in after the run.
