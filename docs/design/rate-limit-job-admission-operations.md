# LLM Rate-Aware Recon Configuration — Operations

Status: built for the LLM Configurator design. Authority:
`docs/superpowers/specs/2026-09-28-llm-rate-aware-recon-configurator-design.md`.

This is the operator view of the current recon path: what happens
automatically, what the LLM owns, what the controller still owns, and what the
persisted evidence means.

## 1. The automatic flow

Every recon run follows this trajectory without an operator pause:

```text
run start
  -> Auth Gateway turn
  -> GatewayVerdict
  -> direct Vegeta mapping from the pipeline
  -> RateProfile
  -> recon_runs.stats["rate_limit"]
  -> data/<project_id>/rate-limit/<target_key>.yaml
  -> per phase:
       prepare canonical jobs and inputs
       offer phase inputs to the Configurator
       Configurator reads rate_limit_posture
       ConfiguratorDecision
       technical validation / atomic materialization
       pods execute configured commands
       parser -> Triager -> Curator
  -> run complete
```

There are two model-facing decision points:

1. the Auth Gateway, which closes with `GatewayVerdict`;
2. the phase Configurator, which closes with `ConfiguratorDecision`.

There is no controller-owned admission decision and no runtime TrafficPolicy
forwarded to recon pods.

## 2. Ownership

### Controller-owned

- Vegeta invocation and its hard safety budget;
- `RateProfile` construction and classification;
- `safe_rate_per_s`, measured thresholds, burst and evidence references;
- persistence of `stats["rate_limit"]`;
- the per-target advisory YAML;
- technical validation of Configurator references and command shape.

### LLM-owned

- which offered jobs become pods in the phase;
- which offered input each pod uses;
- command parameters such as rate, threads, concurrency, delay and depth;
- `pods=[]` when the phase has no safe or useful work;
- the rationale explaining the aggregate plan.

### Explicitly not guaranteed

The runtime does not compare the model's rate, thread, concurrency, delay or
duration choices with the measured posture. The design is **prompt-guided**:
the system prompt requires prudent choices, but there is no hidden numeric
checker or controller-side correction.

## 3. Rate profile and posture file

`stats["rate_limit"]` is the immutable per-run record:

```text
rate-profile/v2
```

It contains the measured bounds, scope, behavioural hypothesis, confidence,
bypass evidence, the operator budget and its consumption, the advisory
`traffic_policy`, and relative artifact references with SHA-256 hashes.

The project's current posture is:

```text
data/<project_id>/rate-limit/<target_key>.yaml
```

with:

```yaml
version: rate-limit-posture/v1
source_run_id: <run that produced the measurement>
advisory: true
profile: <rate-profile/v2>
```

Rules:

- only the controller writes the YAML;
- Postgres is written before the YAML;
- a failed YAML write fails the run before any phase;
- an older measurement never overwrites a newer one;
- a missing file means "not measured";
- a corrupt or invalid file is `unreadable`, never a missing posture.

## 4. Configurator decision

The Configurator is one stateful role:

```text
ConfiguratorSession(run_id)
thread = run:<run_id>:configurator
```

The phase is a new turn on the same session, never part of the identity.

Its tool surface is exactly:

```text
load_skill
rate_limit_posture
```

It returns:

```python
ConfiguratorDecision(
    phase=...,
    target_key=...,
    posture_status=...,
    pods=[ReconPodProposal(...)],
    rationale="...",
)
```

Each proposal selects one offered `(job_name, input_id)` and one command:

- non-empty string for a shell job;
- `None` for an agentic job such as `steel_crawl`.

The runtime rejects the entire decision atomically if phase, target, job,
input, duplicate id or command shape is invalid.

## 5. Where to inspect the outcome

`GET /projects/{project_id}/recon/{run_id}` returns `stats`.

Important keys:

* **`rate_limit`** — what was measured and persisted for this run;
* **`traffic_admission`** — no longer written by the recon path.

The per-job rows carry `stats.commands`, with authenticated values redacted.
The commands show the model-selected parameters executed by the pods.

The YAML posture is the project-level current view of the same measured profile.

## 6. Failure semantics

| Event | Behaviour |
|---|---|
| Auth Gateway degraded | existing auth fail-open/anonymous semantics |
| Target browser-only | conservative inconclusive profile; zero Vegeta experiments |
| Vegeta mapping fails | conservative profile, visible to the Configurator |
| YAML write fails | run `failed` before phases |
| YAML missing | prompt requires conservative fallback |
| YAML unreadable | prompt requires omitting target-facing pods |
| LLM decision missing/invalid | run `failed` before that phase's pods |
| Unknown job/input/reference | entire decision rejected atomically |
| `pods=[]` | valid; no pods in that phase |
| Exec tool fails | existing pod retry/degradation semantics |

## 7. Wire versions and rollback

- `RateProfile` and `TrafficPolicy` are v2 contracts;
- a v1 persisted profile is read only through `upgrade_rate_profile_v1`;
- Kali still advertises the generic governor versions, but the recon path no
  longer arms a TrafficPolicy on pod exec;
- rollback is additive because `rate_limit` already lives inside JSONB stats.

## 8. Deterministic E2E targets

The functional E2E uses the five local posture services:

| Service | Posture |
|---|---|
| `rate-matrix-no-limiter` | no limiter |
| `rate-matrix-high-limit` | compatible limiter |
| `rate-matrix-low-limit` | low limiter, no bypass |
| `rate-matrix-false-bypass` | low limiter with an unconfirmed bypass shape |
| `rate-matrix-burst-inconclusive` | ambiguous/bursty behaviour |

The E2E provider is deterministic and is not production logic. It calls the
real `rate_limit_posture` tool and emits a real `ConfiguratorDecision`.

Run:

```sh
sh scripts/issue_238_e2e_stack.sh config
sh scripts/issue_238_e2e_stack.sh build
sh scripts/issue_238_e2e_stack.sh gate-twice artifacts/issue-238-llm-configurator
sh scripts/issue_238_e2e_stack.sh down
```

The twice-run gate proves:

```text
auth -> Vegeta -> stats/YAML -> Configurator -> selected pod commands -> Triager
```

and that the second run does not reuse the first run's project, session or
outputs.

## 9. Pull-request verification gate

Run the following from the root of the dedicated worktree. Unit and contract
tests must have zero failures; skipped tests retain their normal environment
gates. This scoped tier is intentional: bare `pytest` also collects unrelated
live E2E suites and optional gateway components that require their own stacks
and dependency sets.

```sh
.venv/bin/python -m pytest tests/app/test_launch_task_lifetime.py -q -p no:cacheprovider
.venv/bin/python -m pytest tests/app tests/recon tests/attack -q -p no:cacheprovider
sh scripts/issue_238_e2e_stack.sh config
sh scripts/issue_238_e2e_stack.sh build
sh scripts/issue_238_e2e_stack.sh gate-twice artifacts/issue-238-llm-configurator
sh scripts/issue_238_e2e_stack.sh down
git diff --check
git status --short
```

`gate-twice` owns its isolated Compose lifecycle and resets Postgres, target
counters and the deterministic provider between run A and run B. Always run
`down` even after a failed gate.

The curated files under `artifacts/issue-238-llm-configurator/` are the small
review snapshot for the pull request. Do not stage concurrency probes or dated
local QA reruns; `.gitignore` excludes both categories.

Before requesting review, the authoritative spec, implementation plan,
operations guide and QA record must all be tracked, and the branch must contain
no unrelated changes.

## 10. What not to do

- Do not raise traffic by disabling a governor: the recon path does not arm one.
- Do not edit the YAML to "fix" a run: it is advisory and read-only for agents.
- Do not expect `stats["traffic_admission"]`: it is retired from this path.
- Do not infer a numeric guarantee from the Configurator prompt; compliance is
  model behaviour, not a runtime invariant.
