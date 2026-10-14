# Remove the eval version-advance jumper from the codebase

Status: accepted (amended 2026-10-14 - the stack-identity library is retained; see "Amendment")
Date: 2026-10-12
Supersedes: the advance daemon (D34/D42), the orchestrator alignment step (#274), and the operator rewind (D38) as they stood in `docs/design/eval-environment-version-pinning-adr.md` and `docs/design/eval-multi-instance-decisions.md`.

## Context

The eval version advance was a client-plus-daemon system.
A server-side `eval-advance.service` ran `python -m advance.daemon` and fast-forwarded every instance worktree to `dev` when all instances were idle, computed a stack manifest and fingerprint, and emitted a decision input in a heartbeat file.
Client code in this repo followed the jump: the `advance` package (`daemon`, `decision`, `manifest`, `fingerprint`, `images`), the `orchestrator.alignment` step (which read the heartbeat, decided restart/recreate/migrate actions, and wrote a hold), and the `orchestrator align` CLI verb.

The operator has taken full ownership of the eval instance and its version jump for the current work.
The jump is now performed by the external operator, out of band, and no client code needs to observe or drive it.
Keeping the machinery in the repo adds a second, competing owner of the jump and a large client surface that no longer serves a purpose.

## Decision

Remove the version-advance jumper and its client code from this codebase and from the eval server.
Keep only the two capabilities other eval components genuinely depend on.

1. Delete the jump machinery from `eval/advance/`: `daemon.py`, `decision.py`, `systemd/`, and the daemon-only imports.
   RETAIN `manifest.py`, `fingerprint.py`, and `images.py` (with a slimmed `__init__.py`) as the shared stack-identity library - amended 2026-10-14, see "Amendment".
2. Delete the alignment decision machinery from `orchestrator/alignment.py`: the `AlignmentDecider` seam, `SubagentAlignmentDecider`, `ImpactEntry`/`DecisionAction`/`AlignmentDecision`/`AlignmentRequest`, `plan_dispatch`/`load_decision`, `run`/`_execute`/`_plan_commands`/`_impacted_components`, `AlignmentEnvironment`/`environment_context`, `AlignmentOutcome`/`ActionResult`/`action_key`, `COMPONENTS_BY_ARTIFACT_CLASS`, and the `default_containers`/`COMPONENTS` import.
3. Delete the `align` CLI verb and its heartbeat/decision-file plumbing, and the `AlignmentDeclarations`/`DeclaredMigration`/`DeclaredRebuild` setup config.
4. Keep the durable recovery state in `orchestrator/alignment.py`: the `Hold` marker, the `AlignmentState` atomic state file (holds plus applied keys), the surfer handled-key namespace, and the `alignment resolve` verb. The surfer loop and `up`/`trial`'s `require_no_holds()` use these, and none of that is jump logic.
5. Relocate the idle proxy to `orchestrator/app_state.py` (from `advance/app_state.py`), with its subprocess seam `orchestrator/effects.py`. The surfer reads `GET /app-state` to assert idleness; this is a surfer input, not a jump input.
6. On the eval server, stop and disable `eval-advance.service` and `eval-instance-watch.service` and move their units and `/etc/polymerhus/eval-advance.env` aside.

## Why the shared pieces stay

The surfer uses `alignment.AlignmentState`/`Hold` and the idle proxy; both outlive the jump.
`alignment.AlignmentState` reuses one atomic state file for the surfer's handled-trigger keys and for applied-action keys, so it cannot be dropped without a new state file and a surfer rewrite; the state and its hold semantics are recovery state, not version-jump state.
The idle proxy reads the instance API's own running-state surface; it was named for the daemon only because the daemon was its first consumer.

## Consequences

- The `eval` branch's fast-forward and the jump decision move to the operator and out of this codebase.
  The stack manifest/fingerprint STAY in this codebase as the shared stack-identity library (`eval/advance/{manifest,fingerprint,images}.py`), which the operator drivers use to compute the `stack_fingerprint` the trial record carries; the daemon alone moved. (Amended 2026-10-14: the removal had also deleted this library, silently breaking the drivers.)
- `EvalSetup.alignment` declarations are gone; no setup YAML declared any (all three live setups comment the field out).
- The C5-C14 advance/alignment assertions and the E6/E9 advance end-to-end scenarios in `eval/ASSERTIONS.md` are removed; the C14 hold assertion is retained as a recovery-state assertion.
- A stale hold still blocks `up`/`trial` and is cleared with `alignment resolve`; nothing reverts a jump (the `Rewind`/last-known-good concept goes with the daemon).
- Historical design records that describe the daemon (`docs/design/eval-environment-version-pinning-adr.md`, `docs/design/eval-multi-instance-decisions.md`, `docs/design/llm-gateway-100-decisions.md`, and others) are left as history; this ADR supersedes their daemon and alignment decisions.

## Amendment (2026-10-14): retain the stack-identity library

The original removal (decision 1) also deleted `manifest.py`, `fingerprint.py`, and `images.py`.
Those three are not jump logic: they compute the running stack's identity, and the operator's eval drivers depend on them directly.
The drivers `streamed-trial-fix.sh`, `ss-trial.sh`, and `drive-run2.sh` compute `EVAL_STACK_FINGERPRINT` with `from advance import fingerprint, images, manifest` and redirect stderr.
With the modules gone the import raised, the variable went empty, and every trial record stamped a blank `stack_fingerprint`; the verdict and diagnosis rows that copy it were then refused on write.
The collateral break was silent because the drivers swallow the traceback.

The library is restored under `eval/advance/` with its public surface unchanged - `manifest.build_manifest`, `images.collect_image_digests`, `images.default_containers`, `fingerprint.fingerprint` - and `manifest`/`images` now import the shared subprocess seam from its relocated home, `orchestrator.effects`.
The daemon, the decision input, the systemd units, and the alignment machinery stay removed.
The unit tests for the three modules are restored beside them, plus `tests/eval/test_stack_identity_driver_contract.py`, which pins the exact driver import path.
