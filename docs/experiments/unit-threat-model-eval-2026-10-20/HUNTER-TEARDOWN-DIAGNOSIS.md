# Hunter Teardown Diagnosis - 2026-10-21

## Question

The operator asked whether the previous trials had several hunter degradations or teardowns.
The operator also asked for the most upstream root cause of each and the observable cascade.
The purpose is to decide whether to proceed to white-jotter or fix the root causes first.

## Short Answer

There were **three provider-failure interruptions** in the hunting runs:
- One older run on 2026-10-14.
- The comfyui canary 4 on 2026-10-21 at 00:27:30.
- The comfyui retest first attempt on 2026-10-21 around 12:39.

There was **one deliberate budget project stop** in the retest second attempt at 14:18:47.
That stop is not a provider teardown, and the 16 hypothesised drafts are its expected partial state.

There were **two terminal pod failures**, and both are the same F-009 `reasoning_content` 400.
Both exports report `verdict: unsuccessful`, `terminal_reason: technical-infeasibility`, `iterations: 0`.
The two pods are `active-type-denylist-omission_userdata-blob-serve` and `type-selects-privileged-area_temp-read`.
The retest's 0 pod confirmations therefore cannot be attributed to the domain probes.
The pod runner never reached iteration 1.

There was **one malformed hunter spec write**, F-025, with two parse failures.
It produced no spec, but it did not stop the run.

There was **one terminal-set omission**, F-020 canary.
It was a model omission before the provider pause, not a controller teardown.
The terminal-write guard now rejects that omission.

## Evidence

### Run history

The `hunting_runs` table has 24 rows:
- 20 `stopped` runs, most of them operator or trial stops.
- 2 `completed` or `complete` runs.
- 1 `failed` run.
- 1 older `interrupted` run with provider 429 and `quota_exhausted=true`.

The older interrupted run is `9637a7bd-2aa8-470f-bb1c-50f4939818dd` on 2026-10-14.
The canary and the retest first attempt cleared their `interrupted` stats when the operator resumed them.
The trial records and the pre-resume backup preserve the evidence.

### Canary 4

- The trial record is `comfyui-1-20261021T002730-1fc05262`.
- The trial terminal is `failed`.
- The hunting phase is `interrupted`.
- The hunting failure is `provider unavailable (no status)`.
- The hunting run is `8e94cafc-4c77-41f7-856c-72f399fb4265`.
- The run later completed at 01:05 after the operator resumed it.
- The canary's F-017 pod spec was consumed with no pod dispatch.
- The canary's F-020 `/view` draft was written at 00:10:24.
- The terminal write at 00:27:02 omitted that draft.
- The provider pause was 28 seconds later, at 00:27:30.
- The omission therefore happened **before** the teardown.

### Retest first attempt

- The pre-resume backup is `_backup/utm-comfyui-provider429-20261021T135905Z/run-stats-before-resume.json`.
- The stats carry `interrupted=true`.
- The stats carry `provider_status=429`.
- The stats carry `quota_exhausted=true`.
- The stats carry `interrupt_reason=provider unavailable (status=429, quota_exhausted=true)`.
- The retest trial note says: first attempt interrupted on provider 429; new key applied; same run resumed.
- Thirteen loop files had already moved from `produced/` to `consumed/`.
- The thirteen loop files were restored from a backup before the resume.
- The automated resume did not restore them.

### Retest second attempt

- The trial terminal is `stopped`.
- The spent capped tokens are `3,355,148` against the `3,000,000` budget.
- The overshoot is `355,148`.
- The trial note says: the 3M watchdog stopped the project.
- The project-level stop is the eval design for a budget or deadline.
- The run had 16 hypothesised specs and 3 pod directories without a terminal export.
- The 16 drafts are the partial state of a deliberate stop, not a provider teardown.

### Pod exports

Both terminal exports are F-009:
- `active-type-denylist-omission_userdata-blob-serve`.
- `type-selects-privileged-area_temp-read`.
- Both have `iterations: 0`.
- Both have `clean: false`.
- Both have `terminal_reason: technical-infeasibility`.
- Both have the same upstream 400: `The reasoning_content in the thinking mode must be passed back to the API`.
- The pod log records `pod run degraded to unsuccessful` at 14:16:47.

The five pod runs measured are:
- Two with a terminal export.
- Three with no terminal export.
- Zero confirmed.

### F-025

- Two `hunts_store` tool-call parse failures occurred at 14:04:18.
- The captured payload is 13,338 characters.
- The payload is complete at the end.
- The first spec leaves a nested object open at the first spec boundary.
- The error position 3,685 is the second spec, not a truncation point.
- The loop produced no spec.
- The run continued.

## Cascades

### C-1 - Canary provider-failure teardown

1. The provider returned an unavailable or throttled response during the hunting phase.
2. A dispatched hunter or pod raised `ProviderUnavailableError`.
3. The surfer recorded `state.provider_failure` and stopped dispatching.
4. `start_hunting` caught the typed error.
5. `stop_hunting_for_provider_failure` cancelled **every** component session of the run.
6. The cancelled sessions included the modeller, every hunter, every pod, and the surfer.
7. The run stamped `interrupted`.
8. The trial client saw the non-terminal phase and terminated the trial `failed`.
9. The F-017 pod spec had already moved to `consumed/`; it had no pod.
10. The operator resumed the run; it completed later.
11. The F-020 `/view` draft was already omitted before this cascade.

### C-2 - Retest first-attempt provider teardown

1. The provider returned 429 with the quota flag.
2. The same #331 handler cancelled every session of the run.
3. Thirteen loop files had already moved to `consumed/`.
4. The hunters were torn down before their terminal spec sets.
5. The run stamped `interrupted` and `quota_exhausted=true`.
6. The trial client terminated `failed`.
7. The automated resume could not re-dispatch the consumed loops.
8. The operator restored thirteen loop files from a backup and cleared the quota flag.
9. The run resumed and produced 39 specs from thirteen hunters.
10. The same run was then stopped at the 3M cap.

### C-3 - Retest second-attempt budget stop

1. The trial monitor read the capped spend and crossed the 3M budget.
2. The monitor called `POST /projects/{id}/execution/stop`.
3. The project stop cancelled every live run.
4. The hunting run stopped with 16 hypotheses in `produced/`.
5. Three pod directories had no terminal export.
6. Two pods had already failed for F-009.
7. The run terminal is `stopped`, not `complete`.
8. This is the designed budget behavior; it is not the provider teardown.

### C-4 - F-009 pod degradation

1. The provider response omitted `reasoning_content` or the app failed to parse it.
2. The next outbound request omitted the field for an assistant tool-call message.
3. The provider returned 400: the field must be passed back.
4. The pod runner caught the 400 as a generic failure.
5. The pod exported `verdict: unsuccessful` with `iterations: 0`.
6. No domain probe ran.
7. The run did not stop; the pod result is a false negative.
8. The same 400 appears in both terminal exports.

### C-5 - F-025 malformed spec write

1. The hunter wrote a batch of several specs in one `hunts_store` call.
2. The model-authored payload had a nested object left open.
3. LiteLLM rejected the whole call before the typed contract saw it.
4. The hunter retried and failed again.
5. The loop produced no spec.
6. The run continued; the loop was cut by the cap.
7. No controller teardown occurred.

### C-6 - F-020 terminal omission

1. The hunter wrote the `/view` SVG draft as `hypothesised`.
2. The hunter wrote a terminal set that omitted the draft.
3. The old code persisted the terminal set as authored.
4. The pod dispatch gate accepted only `ratified` specs.
5. The draft never reached a pod.
6. The provider pause happened after the terminal write.
7. The current guard rejects the omission.
8. This is a model omission, not a teardown.

## Most Upstream Root Causes

### R-1 - F-009 is the most upstream cause of the two failed pods

The two terminal pod exports failed at iteration 0 with the same reasoning 400.
The pod cannot produce a domain verdict when the model call fails before the first probe.
The fix is the local empty-reasoning fallback in the outbound replay.
The direct provider probe accepted an empty `reasoning_content`.
This is the highest-value local fix for the retest quality.

### R-2 - F-022 is the most upstream durability defect in the provider teardowns

The hunting dispatcher moves a loop from `produced/` to `consumed/` before the hunter has a terminal outcome.
A run-wide stop therefore leaves the loop in a consumed state with no completion marker.
The resume path does not re-dispatch it.
The operator restored the 13 loops manually.
The stop-only handler is the trigger; the destructive move is the defect that makes the trigger lossy.
The minimal robust fix is an at-least-once loop dispatch or lease:
- Keep the loop in `produced/` until the hunter writes a terminal set, or
- Record a completion marker and re-dispatch unconsumed leases on resume.

### R-3 - The #331 stop-only handler is the amplifier

A provider failure in one hunter or pod cancels every component session of the run.
This includes hunters that had no provider failure.
The handler was a deliberate design choice to avoid a live surfer dispatching after a pause.
It converts a local infrastructure failure into a run-wide teardown.
A narrower policy would hold or stop only the affected session and requeue its loop.
That policy needs an ADR revision and is larger than the F-022 durability fix.

### R-4 - The budget stop is deliberate, not a teardown bug

The 3M project stop is the eval's budget control.
The 16 drafts are the expected partial state of a stopped run.
They are not a terminal-set omission and not a provider failure.
A graceful stop could record them as dropped or leave them for a resume.
That is a finalization improvement, not the root cause of the lost hunters.

### R-5 - F-025 and F-020 are independent model or tool contract defects

F-025 is a malformed batch write.
F-020 is a terminal-set omission.
Neither is a controller teardown.
F-020 is guarded.
F-025 needs the one-spec typed write contract.

## Decision Inputs

### What is proven

- The two terminal pod exports are F-009, not domain evidence.
- The retest lost 13 loops to a destructive dispatch move on a provider stop.
- The canary trial failed on a provider pause and lost one consumed pod spec.
- The #331 handler cancels the whole run, including unaffected hunters.
- The 16 drafts are a budget-stop partial state, not a terminal omission.

### What is not proven

- That the canary's provider failure had a specific status; the trial record says `no status`.
- That the two pod 400s are the only F-009 cases; the log has 28 400s and two exports.
- That the 13-loop loss is the only resume defect; F-023 and F-017 show related defects.
- That the 3M stop drained every hunter before the project terminal; the artifacts show partial work.

### Recommendation

- Fix F-009, F-010, F-012, F-014, F-018, and F-025 as planned.
- Do not reinterpret F-020 as a status-model bug; the draft processing issue is a stop and durability problem.
- Before white-jotter, fix the at-least-once loop dispatch (F-022) or narrow the #331 stop policy, or both.
- The at-least-once loop dispatch is the smaller root-cause fix and protects every future stop.
- The #331 change is the structural fix that matches the operator's "do not stop hunters" rule, but it needs an ADR revision.
- White-jotter can proceed only after the selected teardown fix is proven by tests and a targeted run.
