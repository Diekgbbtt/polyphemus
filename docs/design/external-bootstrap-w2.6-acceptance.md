# External bootstrap e2e regeneration - run w2.6 acceptance record

This is the durable record of the external bootstrap's first full end-to-end regeneration on the eval server.
The run id is `w2.6`; its live state and logs are under `.bootstrap-runs/w2.6/` (gitignored), and its resolved configuration is `.bootstrap-runs/w2.6/config.resolved.yaml`.
The procedure it proves is `tools/bootstrap/run_external_bootstrap.py` against the planned workflow in `docs/design/external-bootstrap-architecture.md`.
The spec of the module is GitHub issue Diekgbbtt/polyphemus#358.

## What ran

One serial pass over all eight pre-pulled eval-server targets: dataease, comfyui, geoserver, jetlinks, phpbb, prestashop, siyucms, white-jotter.
For each target, from scratch: archive the pre-existing KB and staging bundle, deploy, wait for readiness from raw signals, drive one worker session through the authn phase, gate it with the validator in auth-only mode, drive the authenticated L1 crawl, gate it in full mode, tear down, and verify zero containers.
Every phase completed green: `done 8/8`, no failed targets, and each teardown verified.

Timeline: the pass ran from 2026-10-17 14:26 to 22:38 CEST, in several resumes, because the live run surfaced five module defects that were fixed as they appeared (see "Fixes the e2e surfaced").
Three targets (dataease, comfyui, geoserver) completed through their phases' bounded timeout-recovery path; the other five completed on their first dispatch turns.

## Shape gate (hard)

`PYTHONPATH=src python3 tools/bootstrap/validate_data_dependencies.py --staging eval/data-dependencies --all eval/data/webexploitbench` prints `8/8 target(s) valid`.
Nothing was assessed that the gate did not pass.

## Deterministic assessment (`assess.py`)

Committed view (the tracked artifacts; the auth bundle is not in this view, so D1 is 0 by design):

| criterion | mean | min |
|---|---|---|
| A1 overview.structure | 4.0 | 4 |
| A2 overview.journeys | 4.0 | 4 |
| A3 overview.budget | 3.0 | 3 |
| A4 overview.grounding | 4.0 | 4 |
| B1 kb.scaffold | 4.0 | 4 |
| B2 kb.contracts | 4.0 | 4 |
| B3 kb.systems | 4.0 | 4 |
| B4 kb.roles | 3.75 | 3 |
| C1 surface.schema | 4.0 | 4 |
| C2 surface.edges | 3.75 | 2 |
| C3 surface.parity | 4.0 | 4 |
| E1 notes.presence | 4.0 | 4 |
| E2 integrity.no_leak | 4.0 | 4 |
| overall | 3.6 | 3.5 |

Staging view (with `--staging eval/data-dependencies` and the sealed ground-truth directory names for the leak scan): D1 auth.structure 3.38 mean, overall 3.85 mean, no failing criterion anywhere.
Baseline deltas (committed view, versus `baseline-pre-regeneration.json`): comfyui +0.64, dataease +0.64, geoserver +0.5, jetlinks +0.64, phpbb +0.71, prestashop +0.71, siyucms +0.93, white-jotter +0.71.
The only sub-3 deterministic cell in either view is geoserver's `C2 surface.edges` at 2 (orphan_frac 0.24), recorded below as a follow-up.

## Semantic assessment (one independent assessor per target)

Each target's `assessment.yaml` was written by a fresh `eval-assessor` subagent following `llm_judge_prompt.md`, read-only, never touching ground truth.
Merged scales: L1 3.12, L2 3.62, L3 3.0, L4 3.0, L5 3.25 mean; overall 3.68 mean (3.53-3.74 per target).
Every L criterion is >= 3 for every target.

The assessors' top findings, kept as follow-ups:

- comfyui: the `/manager/queue/*` family is cross-claimed by `extension-management` and `model-installation`; it needs one declared owner and per-action routing.
- dataease: the exposure model is internally inconsistent - `typography` and `geographic-map` are declared public while their own contracts and the surface map show authenticated admin operations, and they carry no `AUTHENTICATED_BY` edge.
- geoserver: the surface omits the outbound-fetch and backing-datastore mechanisms (the only `IntegrationSystem` is CORS-only, and no datastore node exists although feature access and catalog management run against PostGIS).
- jetlinks: the live `/scene/**` module is cited as evidence twice yet appears in neither the endpoint-family table nor the KB.
- phpbb: the 27 `WebPresentation` System units are one boilerplate sentence each without the `pages`/`rendering_model`/`navigation_model` props the kind definition requires.
- prestashop: the KB models server-side fetch but drops the client-side upload and module-package-installation surface the crawl observed.
- siyucms: the member/identity contracts are not disjoint (`member-centre` vs `password-recovery`, `member-account-api` vs the front-office member services).
- white-jotter: the auth bundle stages only `sysAdmin` plus a roleless account while the KB names four roles, so the `contentManager` tier is unexplorable; secondary, journey 2 claims a self-registered reader lands with a loaded navigation tree, contradicting the observed empty list.

## Acceptance (RUBRIC.md section 5)

1. The shape validator passes every target: **pass** (8/8).
2. A2 and A4 are >= 3 for every target: **pass** (both 4 for every target).
3. No target's E2 regresses to 0: **pass** (4.0 everywhere).
4. Every target's `overall` is >= its baseline: **pass** (+0.5 to +0.93).
5. L criteria are >= 3 for every target, or the gaps are recorded: **pass** (all >= 3; the findings above are recorded).

The regenerated set is accepted.

## Fixes the e2e surfaced (all committed)

1. `588e9118` - a resumed run must re-align an adopted session's agent and model: a session persists the lane it was created with.
2. `f6622243` - the service's session create is idempotent (a duplicate id returns the existing session with rc=0), so the alignment must run on the create response too; otherwise a resume silently kept dispatching on the stale lane and 403ed on the free tier.
3. `f8182add` - the turn boundary is the transcript head id, never a page count: the message endpoint serves a newest-first window, so a count either sliced outside the page (a finished turn waited a full hour) or credited a previous turn's idle as the new turn's terminal.
4. `28a03be7` - transcript reads stay small and decode-lossy: the CLI truncates large streamed bodies (~256KiB, unstably), which killed the run once with a `UnicodeDecodeError`; the poll page is 20 messages and an unparseable head body is a failed read, never an empty session.
5. `5e13b784` - the non-5xx readiness rule is per-target overridable: prestashop's web SAPI hits the known emulation ICU defect, so its storefront root answers 500 permanently while the containers are up and the authenticated surface is workable; the accepted 5xx is recorded verbatim in the run state.

Two measurement fixes came from the assessment, not the run:

6. `d9000b5d` - the A4 grounding proxy counts the plural of its surface vocabulary, and the carriers now name that vocabulary explicitly.
