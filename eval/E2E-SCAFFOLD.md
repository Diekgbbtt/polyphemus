# E2E-SCAFFOLD.md - the pre-e2e gate for the first live EvalSetup (#276)

This is the operator-facing scaffold for the first live end-to-end run of
`eval/setups/first.yaml` (one `PolyphemusInstance`, one WebExploitBench target:
`comfyui`).
It is the gate the operator assesses before the live execution phase: run it or reject it.
It names, for every live step, the exact command, the bootstrap data only the operator can supply, the observable outcome that counts as success, and the failure-reporting path.
Nothing here is executed by the dry-run tier; the live run is deferred to the final e2e phase.

The setup under test is committed and already dry-run-clean:

```
PYTHONPATH=eval python3 -m orchestrator plan eval/setups/first.yaml --dry-run
PYTHONPATH=eval python3 -m orchestrator trial eval/setups/first.yaml eval-server-1 comfyui-1 --dry-run
```

Observed plan summary (from the committed setup, no execution):

- instance `eval-server-1` (`ph-dd131acc`): worktree add -> env preflight -> compose render -> `up -d`
- target `eval-server-1/comfyui-1` (`webexploitbench/comfyui`, `targetctl`, local): platform bank `~/WebExploitBench` -> `targetctl build comfyui` -> `targetctl up comfyui` -> front conf `eval-target-t-1fc05262.target.conf` in the shared `ph-eval-front` container -> bounded readiness probe -> Docker host gateway -> kali alias
- trial: create project -> settings (`target_seed=t-1fc05262.target`, operator KB) -> deterministic L1 scaffold -> recon entry + launch -> hunting entry + launch (cap 10)

## 1. Identities and paths this run uses

| Thing | Value | Where it comes from |
|---|---|---|
| Instance | `eval-server-1` | `first.yaml` |
| Target | `comfyui-1` (`webexploitbench/comfyui`) | `first.yaml` (`target_key`) |
| Synthetic Host (the seed) | `t-1fc05262.target` | derived: `sha1("eval-server-1/comfyui-1")[:8]`; written to the front `server_name` and aliased in kali |
| Front URL | `http://t-1fc05262.target/` | the shared `ph-eval-front` container on :80 (D45) |
| Instance worktree | `<EVAL_INSTANCES_ROOT>/eval-server-1` | `--instances-root` (default `eval/instances`) |
| Instance `.env` | `<instance worktree>/.env` | manually managed; see the checklist |
| Data root | `<instance worktree>/data` = `$EVAL_DATA_ROOT` | the compose `./data` bind; passed explicitly as `--data-root`/`EVAL_DATA_ROOT` (see B12). `store materialize` derives the same path from `--instances-root` + the instance id, but the trial/assess/diagnose verbs default to `<repo>/data`, so it must be passed explicitly. |
| Artifact store | `/srv/eval-artifacts` | `first.yaml` |
| Trial dir | `eval/runs/comfyui-1/<trial_id>/` | `--runs-root` (default `eval/runs`) |
| Store trial tree | `/srv/eval-artifacts/comfyui-1/eval-server-1/<trial_id>/` | `target_run_id` defaults to the instance id |
| Ground truth | `<EVAL_WEB_DIR>/comfyui/challenge.json` | `EVAL_WEB_DIR` (default `~/WebExploitBench`) |

The instance runs from a worktree DETACHED at the read-only `eval` branch.
The canonical checkout `EVAL_REPO` is the eval server's `dev` checkout (the delivery plane owns it); the instance worktree is added from it.

## 2. Operator bootstrap data (the checklist)

Only the operator can supply these.
A run attempted with one missing fails loud; none is silently defaulted.

| # | Item | Needed by | Notes |
|---|---|---|---|
| B1 | Eval-server access and the canonical checkout path (`EVAL_REPO`, e.g. `/opt/polymerhus-dev`) with the `eval` branch present | instance up | `git worktree add` runs against it |
| B2 | The instance `.env` at `<EVAL_INSTANCES_ROOT>/eval-server-1/.env` | instance up | The preflight fills missing keys from `.env.example` but never creates the file (exit 2 if absent). It must exist before `up`. Required keys: `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`, `POSTGRES_DSN`, `KALI_MCP_URL`, the nine `LLM_<ROLE>` model keys, and `LLM_CAPABILITY_OVERRIDES` (the A6 correction for the relay; the preflight fills it from `.env.example` if the operator omits it and fails loud if it is wrong - its absence silently degrades the compaction summariser, F12). Provider `API_KEY_<PROVIDER>` for every provider those roles select, plus `LANGFUSE_*` for traces. |
| B3 | The eval host runs Docker with amd64 binfmt emulation registered (`docker run --privileged tonistiigi/binfmt --install amd64`; D46) | target built/run | WebExploitBench base images are amd64-only; the host is aarch64, so the targets run emulated |
| B4 | The local WebExploitBench checkout `~/WebExploitBench` (or `EVAL_WEB_DIR`) with the `comfyui` target built (targetctl clones if missing) | target routed | `targetctl build/up comfyui` runs locally; the front is the shared `ph-eval-front` container (no ssh, no host nginx) |
| B5 | The same local checkout serves ground truth (`EVAL_WEB_DIR`, default `~/WebExploitBench`; D45) | assessment, diagnosis | `gt.py` reads `<EVAL_WEB_DIR>/comfyui/challenge.json`; the KB is committed at `eval/data/webexploitbench/comfyui/operator_kb.md` |
| B6 | LLM provider credits/keys for the roles in B2 | trial | Recon/analysis/hunting spend them |
| B7 | `EVAL_SHA` and `EVAL_STACK_FINGERPRINT` | trial, store | The `eval` branch commit and the daemon's stack fingerprint of the running (post-advance) tree. Read the SHA with `git -C "$EVAL_REPO" rev-parse eval`; read the fingerprint from the advance daemon heartbeat's `decision.fingerprints.dev` - the post-advance/running side, which pairs with the now-current SHA. Do NOT use `decision.fingerprints.eval`: that is the pre-advance fingerprint and would pair the new SHA with a stale stack. Both are mandatory: `store materialize` refuses `identity_missing`, and every verdict and diagnosis row must carry them. |
| B8 | `EVAL_ASSESS_COMMAND` and `EVAL_DIAGNOSE_COMMAND` | assessment, diagnosis | Shell lines with the documented placeholders (OPERATOR.md 2.9/2.10); no command means `assessment_no_command` / `diagnosis_no_command` escalation |
| B9 | `EVAL_GITHUB_TOKEN` | diagnosis | The read-only `issue-search` bank; absent means the diagnoser writes a `proposed_issue` |
| B10 | `EVAL_ALIGNMENT_STATE` with no unresolved hold | trial | `up`/`trial` refuse while a hold exists; resolve with `alignment resolve` |
| B11 | The store root `/srv/eval-artifacts` writable on the eval server | store sync/materialize | The harness creates the tree; its parent must exist and be writable |
| B12 | The instance data root `EVAL_DATA_ROOT` = `$EVAL_INSTANCES_ROOT/eval-server-1/data` | trial, assess, diagnose, close-verify, store | Export it in section 3 and pass `--data-root "$EVAL_DATA_ROOT"` on every step. The trial/assess/diagnose verbs default to `<repo>/data` while `store materialize` derives `<instances-root>/<instance>/data`; an unset root splits the pipeline across two trees (`chain_unresolved` at materialize, or unattributable paths). |

Create the instance worktree and `.env` before the first `up` (the worktree add is idempotent, so `up` will skip it):

```
mkdir -p "$EVAL_INSTANCES_ROOT"
git -C "$EVAL_REPO" worktree add --detach "$EVAL_INSTANCES_ROOT/eval-server-1" eval
cp <operator-env> "$EVAL_INSTANCES_ROOT/eval-server-1/.env"
PYTHONPATH=eval python3 eval/env_preflight.py "$EVAL_INSTANCES_ROOT/eval-server-1/.env"
```

The preflight exits 0 clean, 1 when a required overlay key is still unset/empty (fix it), or 2 when a file is missing (the `.env` was not placed).

## 3. The live cycle, step by step

Set the common environment once (from the repo root):

```
export PYTHONPATH=eval
export EVAL_REPO=<canonical checkout>
export EVAL_INSTANCES_ROOT=eval/instances
export EVAL_DATA_ROOT="$EVAL_INSTANCES_ROOT/eval-server-1/data"
export EVAL_BRANCH=eval
export EVAL_WEB_DIR=~/WebExploitBench
export EVAL_TARGET_PLATFORM=linux/amd64
export PH_API=http://localhost:8080
export EVAL_SHA=$(git -C "$EVAL_REPO" rev-parse eval)
export EVAL_STACK_FINGERPRINT=<daemon heartbeat decision.fingerprints.dev>
export EVAL_ASSESS_COMMAND="opencode run --agent eval-assessor --dir $EVAL_REPO \"Follow {prompt}. trial_record={trial_record}; ground_truth={ground_truth}; data_root={data_root}; destination={destination}; trace_id={trace_id}. Write only {destination}.\""
export EVAL_DIAGNOSE_COMMAND="opencode run --agent eval-diagnoser --dir $EVAL_REPO \"Follow {prompt}. trial_record={trial_record}; verdicts={verdicts}; ground_truth={ground_truth}; data_root={data_root}; vulns={vulns}; destination={destination}; trace_id={trace_id}. Write only {destination}.\""
export EVAL_ALIGN_COMMAND="opencode run --agent eval-aligner --dir $EVAL_REPO \"Follow {prompt}. input={input}; destination={destination}. Write only {destination}.\""
export EVAL_SURFER_COMMAND="opencode run --agent eval-surfer --dir $EVAL_REPO \"Follow {prompt}. input={input}; destination={destination}. Write only {destination}.\""
```

`EVAL_STACK_FINGERPRINT` is always the fingerprint of the running (post-advance) tree, so it matches the current `EVAL_SHA`.
It comes from the daemon heartbeat (`decision.fingerprints.dev`, never `.eval`) only when an advance was recorded.
For the very first run (no advance yet), compute it once the instance stack is up (step 1), over the current `eval` SHA and the running image digests:

```
PYTHONPATH=eval python3 -c "
from pathlib import Path
from advance import fingerprint, images, manifest
repo, sha, project = Path('$EVAL_REPO'), '$EVAL_SHA', 'ph-dd131acc'
m = manifest.build_manifest(repo, sha, images.collect_image_digests(images.default_containers(project)))
print(fingerprint.fingerprint(m))
"
```

`ph-dd131acc` is the instance's compose project (`ph-<short hash>` of `eval-server-1`); a future fingerprint CLI would fold this one-liner away.

### Step 0 - plan gate (already green, re-run to confirm)

```
PYTHONPATH=eval python3 -m orchestrator plan eval/setups/first.yaml --dry-run
```

Expected: the full instance + target command plan, nothing executed.
Failure: `orchestrator: error: <SetupError>` on stderr, exit 1 (a malformed or unknown setup field names itself).

### Step 1 - instance up and target routed

```
PYTHONPATH=eval python3 -m orchestrator up eval/setups/first.yaml
PYTHONPATH=eval python3 -m orchestrator status eval/setups/first.yaml
```

Needs: B1, B2, B3, B4.
Expected: the work-item gate passes (only required items are gated; `auth-bootstrap` is `required: false` for comfyui); per instance `instance eval-server-1: up`; per target `target t-1fc05262.target: http://t-1fc05262.target/ -> http://127.0.0.1:<port>`; `status` shows `kali aliases: t-1fc05262.target -> <gateway-ip>`.
Failure paths: `WorkItemGateError` names the incomplete item; `InstanceError` on the worktree/preflight/render/compose (`env_preflight: error:` names a missing `.env`); `TargetctlError`/`TargetNotReadyError` on build/up/front/readiness; `RoutingError` refuses a non-numeric alias address.
Every failure prints `orchestrator: error: ...` and exits 1.

### Step 2 - trial (recon -> hunting)

```
PYTHONPATH=eval python3 -m orchestrator trial eval/setups/first.yaml eval-server-1 comfyui-1 \
  --eval-sha "$EVAL_SHA" --stack-fingerprint "$EVAL_STACK_FINGERPRINT" \
  --data-root "$EVAL_DATA_ROOT"
```

Needs: B5, B6, B7, B10.
Expected: `trial <trial_id>: complete (project <id>)`, phases `recon` and `hunting` with statuses; `eval/runs/comfyui-1/<trial_id>/trial.yaml` carries `eval_sha` and `stack_fingerprint` and `target_run_id: eval-server-1`.
The trial stamps the derived seed `t-1fc05262.target` into the settings PUT, so routing and scope agree.
Failure paths: a phase `blocked` (predicate unmet), `failed` (a failed run or a `complete` run with no job rows), or `timeout`; the record and stdout report it.
The trial verb exits 1 on a `failed` or `timeout` terminal and 0 on `complete`, `blocked`, or `stopped`: the failure is a recorded trial event, and the surfer loop (`surfer --once`) is what asserts and recovers it.
Never read a failed recon run as an empty finding.

### Step 3 - assessment

```
PYTHONPATH=eval python3 -m orchestrator assess eval/setups/first.yaml --trial eval/runs/comfyui-1/<trial_id> \
  --data-root "$EVAL_DATA_ROOT"
```

Needs: B5, B6, B8.
Expected: the background subagent writes `verdicts.yaml` into the trial dir; every row carries the trial record's `eval_sha` and `stack_fingerprint`; `trial.yaml` gets `assessment.status: dispatched`.
Failure path: `close-verify` re-dispatches a missing/invalid verdicts file twice, then records `assessment.failure` (`assessment_no_command`, `dispatcher_process`, `empty_file`, `schema_invalid`) and escalates; a verdict whose identity does not match the record is refused (`VerdictError`).

### Step 4 - diagnosis

```
PYTHONPATH=eval python3 -m orchestrator diagnose eval/setups/first.yaml --trial eval/runs/comfyui-1/<trial_id> \
  --data-root "$EVAL_DATA_ROOT"
```

Needs: B5, B6, B8, B9.
Expected: `diagnoses.yaml` with exactly one entry per `missed`/`partial` verdict; every row carries the trial record's `eval_sha` and `stack_fingerprint`, exactly like a verdict row; `trial.yaml` gets `diagnosis.status` and the counts (`entries_written`, `issues_matched`, `issues_proposed`).
Failure path: no `verdicts.yaml` refuses loudly; no diagnoser command escalates `diagnosis_no_command`; a missing/unpaired entry is caught by `close-verify`; a diagnosis row whose identity is missing or does not match the record is refused (`DiagnosisError`).

### Step 5 - close verification

```
PYTHONPATH=eval python3 -m orchestrator close-verify eval/setups/first.yaml \
  --data-root "$EVAL_DATA_ROOT"
```

Expected: exit 0 with `comfyui-1/<trial_id>: present` and `diagnosis present` (or `not_required` when every verdict was `identified`).
Failure path: exit 1, with one `close-verify: ...` line per escalated trial on stderr naming the failure.

### Step 6 - artifact store

```
PYTHONPATH=eval python3 -m orchestrator store render-sync eval/setups/first.yaml
PYTHONPATH=eval python3 -m orchestrator store materialize eval/setups/first.yaml --trial eval/runs/comfyui-1/<trial_id> \
  --data-root "$EVAL_DATA_ROOT"
```

Needs: B7.
Expected: `<store>/_sync/eval-store-eval-server-1.{conf,service}` (one-way lsyncd, `delete = false`); the authoritative tree `/srv/eval-artifacts/comfyui-1/eval-server-1/<trial_id>/` holding `verdicts.yaml`, `diagnoses.yaml` (when required), `run-manifest.yaml` (with `eval_sha`/`stack_fingerprint`), and the copied evidence chain at data-root-relative paths.
Failure paths (named `StoreError` codes): `identity_missing` (no SHA/fingerprint on the record), `verdicts_missing`, `diagnoses_missing` (a missed/partial verdict with no paired file), `chain_unresolved`, `sync_layout` (store/data-root overlap), `record_missing`/`record_invalid`.
Materialize is idempotent: a re-run replaces each copy atomically from the source and never writes back into the data root.

### Step 7 - version records (attribution)

Every produced record must carry the version identity. Verify:

```
grep -E "eval_sha|stack_fingerprint" eval/runs/comfyui-1/<trial_id>/trial.yaml
grep -E "eval_sha|stack_fingerprint" eval/runs/comfyui-1/<trial_id>/verdicts.yaml
grep -E "eval_sha|stack_fingerprint" eval/runs/comfyui-1/<trial_id>/diagnoses.yaml
grep -E "eval_sha|stack_fingerprint" /srv/eval-artifacts/comfyui-1/eval-server-1/<trial_id>/run-manifest.yaml
```

Expected: the same `EVAL_SHA` and `EVAL_STACK_FINGERPRINT` in all four.
The verdict and diagnosis schemas refuse a row whose identity is missing or does not match the record, and `store materialize` refuses a record with no identity, so an unattributed artifact cannot land in the store.

## 4. Failure reporting, never silent patching

- The orchestrator's verbs surface every failure on stderr as `orchestrator: error: <named cause>` and exit non-zero, except `trial`, which records a non-`complete` terminal in `trial.yaml` and stdout and exits 1 only for `failed`/`timeout` (0 for `blocked`/`stopped`) for the surfer loop to recover.
- Configuration-layer repairs only: the trial's `chain` retries once after an `env`/`stack` repair; the surfer loop may apply `env` or `replace_artifacts` and resume.
- An unalignable version jump or an unbound surfer action writes a hold (same mechanism) and blocks `up`/`trial` until an operator resolves it.
- The artifact store fails loud with a named code rather than copying a partial tree.
- A proposed issue is written into `diagnoses.yaml`; the diagnoser never files.

## 5. Operator gate: accept or reject

Accept the scaffold for execution when:

- every bootstrap item B1-B12 is answered by name (no doubles, no placeholders);
- `plan ... --dry-run` and `trial ... --dry-run` match section 1 and section 3;
- the target is deployed on the eval host (emulated amd64) and answers on `http://t-1fc05262.target/` from the instance kali before recon launches.

Reject (and report the gap) when:

- any bootstrap item is unanswered: carry the walkthrough as blocked, never substitute a double;
- the dry-run plan no longer covers a step in section 3;
- a live step exposes a missing capability that needs a design decision (pipeline termination condition: report NEEDS_CONTEXT).
