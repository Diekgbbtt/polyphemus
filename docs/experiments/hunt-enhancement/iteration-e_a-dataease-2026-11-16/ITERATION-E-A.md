# Iteration E_a - dataease on glm-5.3-flash

*Status: prepared 2026-11-16. Run state and results are filled progressively.*

## What this iteration changes

The branch `iter-e_a-dataease-authn-pod-context` is `feat/iter-e-glm53-hunt-only`
rebased onto `dev` and extended with the work of `fix/iter-e-failure-modes`.
It carries three changes under test:

- **Auth-store secrets-redaction retirement.** The read-only auth binding
  returns the real session material - passwords, token values, snapshot
  headers, cookies, and params - exactly as stored. The `REDACTED` marker and
  its projection are gone. This is the 2026-11-13 ablation; the authn skill
  still cites names only.
- **Pod terminal-record single ownership and graceful degradation.** The
  finalizer owns the one canonical `<spec_id>/<run_id>.yaml` export; the
  retired parent-keyed durable note is not resurrected. The monotonicity ladder
  keeps a latched domain verdict, lets a domain verdict replace a latched
  harness terminal, and never lets a harness terminal replace a domain verdict.
  A runner kill routes to the triager for a final pass; a no-evaluation
  outcome stays the honest harness terminal.
- **Lifecycle v2 pod triager context.** One immutable system prompt, one
  constant request-only tool surface, one append-only per-pod thread. The
  bound-skill listing rides the first human packet; the ASSESS and DECIDE
  verbatims are added progressively to the human messages. The cached prefix
  from position 0 survives every turn and lap.

The merge takes `dev` as authoritative for the pod terminal record and keeps
the failure-mode branch's auth ablation, analysis proposer contracts, recon
media/cookie filters, steel crawl fail-safes, symbolic spec provenance, and
measurement harness.

## Question

Does the same full dataease pipeline produce a better discovery and pod
outcome when the auth store returns its real session material, the pod
terminal record has one owner, and the triager keeps a stable cached prefix?

The evaluation is both qualitative and quantitative.
The standard workbench metrics are the record; the pod cache and terminal
quality are the specific measurements.

## Hypothesis

- The auth-store ablation lets the analysis and pod agents replay and mount
  the recorded dataease `X-DE-TOKEN` session exactly, instead of reasoning
  around a redaction marker.
- The one-owner terminal record removes the duplicate-export and
  graceful-degradation inconsistencies seen in the prior siyucms trials.
- The lifecycle v2 triager raises the pod triager's prefix hit ratio and
  lowers its cold-call share without weakening its domain verdicts.

## Design

| Item | Value |
|---|---|
| Arm | single arm, full pipeline |
| Instance | `eval-server-2` |
| Target | `webexploitbench/dataease` as `dataease-web` (DataEase 2.10.0) |
| Start phase | `recon` (fresh project) |
| Data dependencies | `/root/eval-dd/data/dataease` (auth, authn skill, operator KB, L1 surface) |
| Ground truth | `/root/WebExploitBench/dataease` |
| Recon jobs | `httpx, httpx_reprofile, katana, jsluice, arjun, steel_crawl` |
| Code identity | the branch at the run commit, recorded in `trial.yaml` |
| Bring-up | one `orchestrator up`; the trial runs with `--skip-up` |
| Model | `opencode-go/glm-5.3-flash` for every `LLM_*` role |
| Thinking effort | the committed role defaults (no C.a `max` patch) |
| Steel crawl deadline | `STEEL_CRAWL_MAX_DURATION_S=7200` |
| Pod watchdog | `HUNT_POD_SESSION_TIMEOUT_S=5400` |
| Skill evolution | `SKILL_EVOLUTION_ENABLED=0` |
| Token budget | 7,000,000 capped |
| Risk budget | 360 (cumulative CVSS 4.0 `risk_threshold`) |
| Trial clock | 24 hours; the token cap is the real bound |

## Frozen policy

```text
pipeline_sync            batched
pod_batch_size           2
promotion_risk_threshold 2.5
risk_threshold           360
token_budget             7000000
```

## Model identity

The catalog id is `opencode-go/glm-5.3-flash`.
Every `LLM_*` role in the instance `.env` resolves to it.
The live capability preflight (`eval/preflight_llm_capability.py`) is the
go/no-go gate; a failure stops the run before any project is created.

Thinking efforts are the committed `providers.py` defaults:
`triager low`, `job_orchestrator medium`, `assigner medium`,
`mechanism_typist medium`, `skill_evolver high`, the two hunting design roles
`xhigh`, and the pod runner/triager `high`.
The C.a `max` patch that the earlier eval branches carried is not applied.

## Instance `.env` delta

The surgical update to `/opt/polymerhus-dev/eval/instances/eval-server-2/.env`:

- `API_KEY_OPENCODE_GO` - the newly credited key;
- `STEEL_CRAWL_MAX_DURATION_S=7200` - the raised crawl deadline;
- `HUNT_RISK_THRESHOLD=360` - the raised cumulative risk budget.

Every other instance value is retained: the models, the pod watchdog, the
skill-evolution switch, the gateway budgets, the database and host bindings.
The stale `INSTANCE_DATA_ROOT` value is not edited; the driver exports the
run's own data root so the compose substitution cannot mount the wrong one.

## Scope fence

The reusable iteration-D verbatim, `scope-fence.txt`, is written to
`settings.hunting.threat_model_scope` by `seed_dataease.py` after the project
exists and before the trial bootstraps.
The trial's hunting PUT is partial and deep-merged, so the scope survives the
policy freeze.

## Changes under test - the seams

- **Auth store:** `app/auth/tool.py` (`AUTH_STORE_READ_CONTRACT`, the retired
  `REDACTED` marker), `app/auth/seams.py`, the analysis read-only binding, the
  auth gateway, the authn skill, and the pod's read-only auth store.
- **Pod terminal record:** `pod/finalize.py` (the monotonicity ladder),
  `pod/pod_memory.py` (the one export and the experiment-summary update),
  `pod/graph.py` (the kill routing and the recovery turn), and the surfer.
- **Pod triager:** `pod/triage.py`, `pod/triage_state.py`,
  `pod/triage_graph.py`, `pod/gates.py`, `pod/context.py`, and
  `prompts/pod-triager-contract.md`.

## Run

The driver is `drive_dataease_iteration_e_a.sh`.
It performs the whole sequence:

1. assert the instance `.env` models, steel deadline, risk budget, watchdog,
   and default thinking efforts;
2. bring the stack and target up;
3. run the live capability preflight (the go/no-go gate);
4. seed the project and freeze the scope fence;
5. run the full `orchestrator trial` (recon -> analysis -> hunting);
6. run the eval monitor to convergence (assessment, then diagnosis);
7. close-verify, materialise the artifact store, and measure the trial.

The branch is checked out in the instance worktree; the stack bind-mounts that
root, so no image rebuild is required.
The agent is recreated once to load the updated `.env`.

## Expected artifacts

- `<runs-root>/preflight.json`
- `<runs-root>/driver.log`
- `<runs-root>/monitor.log`, `<runs-root>/monitor.jsonl`
- `<runs-root>/dataease-web/<trial-id>/trial.yaml`
- `verdicts.yaml`, `diagnoses.yaml`, `impact_review.yaml`,
  `measurements.yaml`, `measurements.md`

## Measurements

The standard workbench metrics are computed by `eval/measure_trial.sh` and the
`eval-measurer` role:

- GT verdict counts and identification rate;
- L0/L1 recall, impact rows, threat and precursor dispositions, chains, risk;
- capped tokens and the per-agent split;
- pod terminals, watchdog timeouts, and confirmed symptoms;
- workflow adherence.

The pod triager's cache prefix is read from the usage ledger:
`prefix_hit_ratio`, `marginal_hit_ratio`, and `first_call_share`.
The pod terminal and degradation counts are read from the exported trial
records.

## Results

Filled in after the run.
