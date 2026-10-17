# External bootstrap - architecture

Status: W2.3 (2026-10-17), checkpoint decisions applied.
Spec: https://github.com/Diekgbbtt/polyphemus/issues/358.
Inputs: the dependency audit (`external-bootstrap-dependency-audit.md`) and the reverse-engineered workflow report.
Goal: one self-contained, target-environment-parametrizable module that regenerates the data dependencies (auth bundle + authn skill + L1 surface) for any set of WebExploitBench targets, driving opencode sessions as the workers.
Platform precedent: the eval monitor plugin already dispatches role agents as awaited native opencode child sessions (`.opencode/plugin/eval-monitor.ts`); this module does the same over the service API from Python.

Operator decisions applied (2026-10-17):

- No batch-critic phase: the two validator gates are the critical checkpoints and are trusted as sufficiently reliable.
- No final phase: the loop ends after the last target's verified teardown; there is no trailing `--all` pass and no report phase in the loop.
- Lifecycle must not be symbolic: the environment driver exposes accurate signals from reliable interfaces (the docker engine and targetctl's own output contract), and the orchestrator interprets those signals; `up`/`down` booleans alone are never evidence.
- Worker model default: `opencode/deepseek-v4.1-flash-free` variant `high` (parametrizable, per-target overrides allowed).

## 1. Shape in one view

```text
python3 tools/bootstrap/run_external_bootstrap.py run --config <run.yaml>

Orchestrator (runner/orchestrator.py)
  for each target, serial:
    observe(target)                      -> state; target up-and-ready? reuse : up + wait_ready
    dispatch(authn wrapper)  -> wait idle       [creator session]
    gate auth-only           -> red? re-dispatch the verbatim errors (bounded, then fail)
    dispatch(l1 wrapper)     -> wait idle       [same creator session]
    gate full                -> red? same bounded repair
    down(target)             -> observe: zero containers?; leftover containers are reported as evidence
```

## 2. Module layout

```text
tools/bootstrap/
├── run_external_bootstrap.py      # entry: thin argv -> runner.cli.main
├── runner/
│   ├── __init__.py
│   ├── cli.py                     # plan | run | resume | status
│   ├── config.py                  # run.yaml -> RunConfig
│   ├── harness.py                 # Harness protocol + OpenCodeApiHarness (opencode api subprocess)
│   ├── env.py                     # TargetEnv protocol + SshServerEnv / LocalEnv / AttachEnv
│   ├── wrappers.py                # pure wrapper builders (authn | l1)
│   ├── gates.py                   # validator invocation + OK/FAIL parsing
│   ├── state.py                   # RunState: atomic JSON, resume, session ids
│   └── orchestrator.py            # the loop: lifecycle policy, phases, gates, repair
├── prompts/                       # existing procedure carriers (authn, l1, critic-for-reference)
├── validate_data_dependencies.py  # existing phase gate (unchanged)
├── assessment/                    # existing graded measurement (W1.4, unchanged)
└── DATA-DEPENDENCIES.md           # existing contract
```

`.opencode/agent/data-dep-worker.md` (repo, project config): the worker agent definition (description + full-allow permissions), so worker sessions do not depend on the operator's personal agent list.

## 3. The seams (where tests cut)

Five seams, one of them a real integration seam:

1. `orchestrator.run_plan(cfg, harness, env, gates, state)` - THE high seam.
   Tests drive the whole loop with a scripted fake harness (canned turns, canned transcripts, injectable errors), a fake env (recording lifecycle commands and returning canned observations), a fake gate (scripted OK/FAIL), and a temp run dir; assert phase order, gate-before-advance, bounded repair, verified-teardown, failure policy, and resume-from-state.
2. `wrappers.*` - pure functions; snapshot tests assert substitution completeness, the exact validator command, the report budget, the "No secrets" clause, the sealed-path rule, and the Overview contract reminders.
3. `harness.OpenCodeApiHarness` - transcript parsing unit-tested on recorded JSON fixtures (idle/error/assistant shapes); plus ONE opt-in smoke test against the local service API (create a throwaway session, prompt a trivial reply, assert completion).
4. `env` drivers - unit tests with a fake command executor assert the exact commands issued (`wb up|ps|down`, `docker inspect`), URL rewriting via the platform's own parser, the project-name mirror, and the readiness interpretation; the live e2e run proves the driver for real.
5. `gates` - the real validator over W1 fixture targets; assert OK/FAIL parsing and mode selection.

Prior art: `tests/test_bootstrap_validator.py` (importlib-by-path over `tools/`), `tests/test_bootstrap_assessment.py` (temp-dir fixtures), `tests/eval/test_orchestrator_readiness.py` (fake CommandRunner over readiness probes).

## 4. Harness adapter (opencode service API)

- Create: `opencode api post /api/session` with `{id, title, agent: data-dep-worker, model: {providerID, id, variant}, location: {directory: <worktree>}, metadata: {run, target, phase}, permissions: [{action: "*", resource: "*", effect: "allow"}]}`; an existing id resumes (409 -> fetch).
- Prompt: `opencode api post /api/session/{id}/prompt` with `{text: <wrapper>}` (JSON body; no PTY truncation).
- Wait: poll `GET /api/session/{id}/message` until a new terminal `idle` message after the prompt (`outcome: succeeded|failed`); bounded turn timeout with `POST /api/session/{id}/interrupt`; `POST /api/experimental/session/{id}/wait` as an accelerator.
- Failure classes: provider `FreeTierError`/rate limit -> backoff and re-prompt; tool/permission stall -> interrupt and re-prompt with a sharper instruction; hard failure -> mark the target failed and continue per the failure policy.
- Deterministic session ids (`ses_bt_<run_short>_<target>_creator`) make resume and introspection trivial.

## 5. Environment drivers - signals, not guesses

One protocol, split into raw actuators and a raw observation; all interpretation lives in the orchestrator:

```text
TargetEnv
  up(target) -> CommandResult          # wb up | targetctl up | no-op (attach)
  down(target) -> CommandResult        # wb down | targetctl down | no-op
  observe(target) -> Observation       # READ-ONLY, accurate signals
Observation
  containers: [{name, service, state, health, exit_code}]   # docker engine facts
  url: str | None                      # targetctl's own accessible URL, host rewritten
  http_status: str | None              # raw status of the URL root ("" on no answer)
```

- Container facts come from the docker engine over the driver's transport: containers selected by the compose project label, then `docker inspect` JSON per container (`State.Status`, `State.Health.Status`, `State.ExitCode`, the compose service label). The project name mirrors targetctl's documented naming rule (`web_` + target lowercased with non-alphanumerics to `_`); a test pins the mirror against targetctl's own examples.
- URL discovery is `targetctl ps <target>` output parsed by the platform's own `parse_targetctl_url` (UI line preferred, port-bearing URL otherwise); the host is rewritten (`0.0.0.0` -> the configured host) only for the workers' base URL.
- Readiness interpretation reuses the platform's readiness rules (`ServiceHealth.ready` semantics: running + healthy, or running with no healthcheck, or exited 0; HTTP 5xx and no-answer are not ready) and is composite, like the platform's readiness plan: every container ready AND the URL answers a non-5xx status.
- Teardown verification is an observation: after `down`, `observe` must show zero containers of the project; leftovers are recorded as evidence and reported (not silently ignored).
- Drivers: `SshServerEnv` (default; ssh transport, `/root/wb` wrapper with its environment pins, never prune), `LocalEnv` (targetctl on the Mac with `DOCKER_DEFAULT_PLATFORM=linux/amd64` and bash 5), `AttachEnv` (lifecycle no-ops; the caller supplies the base URL).
- Path semantics per driver, carried to every wrapper as a fact: under `ssh`, the checkout (`<web_root>`, the sealed `vulnerability/` and `challenge.json`) lives on the remote host and is read over ssh, while the KB outputs (`<target_dir>`) are local to the worker's machine; under `local`, every path is local; under `attach`, checkout paths are informational only and outputs are local. The application is always at `<base_url>`.

## 6. State and resume

`RunState` is one JSON file per run (`<rundir>/state.json`), written atomically after every transition:

```text
run: {id, created, config_digest, targets[]}
target: {session_creator, base_url, phases: {authn, l1}, gates: {auth_only, full},
         lifecycle: {up_observations, teardown_observation},
         status: pending|active|done|failed, repair_attempts, notes[]}
```

`resume` re-reads the state, re-verifies live sessions by id, and continues at the first incomplete phase; `status` prints the table; per-turn logs live beside the state (prompt text, transcript tail, gate output).

## 7. Wrappers

Built from the versioned prompt files; the orchestrator only substitutes per-target facts (the wrapper pattern from the mined run, preserved):

```text
You are the <phase> producer for the WebExploitBench target `<target>`.
Read and execute end to end: <prompt file> + <contract>
Substitutions: <target>, <target_dir>, <web_root>, <worktree>, <staging>, <base_url>
Environment: <driver-specific lifecycle + crawl hints>; sealed paths: `<web_root>/<target>/vulnerability/`, `<web_root>/<target>/challenge.json` - never read.
Validate: <exact validator command> until OK.
Report (<30 lines): ... No secrets.
```

Contract reminders pinned in every creator wrapper: structured Overview (single-token stable `domain` equal to the target identity, never a host, IP, or port; >= 2 journeys with >= 3 steps; 250-word budget over the whole entity), contracts path-free and discriminating.

No phase of the loop reads the ground truth: the critic was its only reader, and the critic is out of the loop. The sealed trees stay untouched end to end.

## 8. Operational policy

- Serial targets by default (one target up on the shared server at a time).
- From scratch by construction: before a target's first dispatch, its pre-existing KB directory and staging bundle are moved aside under the run directory (`<rundir>/<target>/pre-existing/{kb,auth-bundle}`); the slots are the idempotence markers, so a resume never archives fresh artifacts. A stale artifact (in particular an old `research-notes.md` or a stale authn skill) can therefore neither mislead a worker nor survive a phase that fails to overwrite it.
- Gate repair: on a red gate the orchestrator re-dispatches the verbatim validator output into the creator session (bounded attempts, default 3); a persistently red target is marked failed and the run continues.
- Teardown after the target's phases pass, verified by observation; the status table and the summary show a target whose teardown could not be verified (leftover containers are evidence, never silently `done`).
- Server rules: `/root/wb` wrapper only, its environment pins untouched; `down` + `docker rm -f $(docker ps -aq)` between targets is allowed; `docker system prune -a` is forbidden.
- Failure policy: `on_target_failure: continue` (default) marks the target failed and reports at the end; the operator resumes it with `resume`.
- `--no-lifecycle` runs the phases and the gates with the environment's lifecycle actuators skipped (for a target whose lifecycle the operator already manages); observations and correctness gates are unaffected.
- Resume reads the run's own `config.resolved.yaml`, warns loudly on config drift (the state is the run's truth), probes every incomplete target's session live, and re-creates a missing session by its deterministic id at the target's next dispatch.
- Secrets: the wrappers carry paths, never values; logs never contain credential-file contents.

## 9. Resolved decisions (checkpoint 2026-10-17)

1. Seams as in section 3 - confirmed.
2. Worker model default `opencode-go/deepseek-v4.1-flash#high` - the entitled lane the operator's own sessions use; the free `opencode` tier answers interactive probes but rejects automated session dispatches intermittently with a 403 FreeTierError, so the module treats those as retryable but never relies on them.
3. Critic phase dropped; the two validator gates and the W1 assessment framework are the quality instruments - confirmed.
4. Final `--all` phase and the run-report phase removed from the loop - confirmed.
5. Lifecycle signal design as in section 5 - confirmed by the accurate-signal requirement.

Note for later readers: the validator deliberately does not enforce linchpin grounding or threat-model coverage (its own comment says so); those remain semantic judgements, now carried by the assessment framework's L criteria after the run, not by a loop phase.
