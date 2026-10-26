# Hunting pod batch size and threat promotion - spec

*Status: ready for implementation (2026-10-26).*
*Extends the owning pipeline-sync spec and ADR: `docs/design/hunting-pipeline-sync-spec.md` and `docs/design/hunting-pipeline-sync-adr.md`.*
*Amends the threat artifact dispatch contract: `docs/design/hunting-67-threat-model-artifact-spec.md` sections 8.3 and 8.4.*
*Sourced from the iteration B evidence in `docs/experiments/hunt-enhancement/iteration-b-white-jotter-2026-10-25/`.*

## Problem Statement

The `batched` pipeline dispatches the unit's whole hunter set concurrently.
It then dispatches one hunt's pod set at a time in threat-rank order.
The fixed one-hunt pod batch cannot be widened for a target that tolerates more concurrent pods.
The operator cannot tune the pod burst without a code change.

Separately, every produced non-zero-risk threat reaches a hunter.
The threat modeller cannot prioritise by downstream risk because it does not see the dispatch policy.
Iteration B showed the cost: 26 threats over 3 modelled units, many low-yield, and 93% of the capped budget spent in the first two units.
The operator wants a per-threat risk floor.
Only threats at or above the floor should be promoted to a hunter.
The rest must stay in `produced/` as evidence.

## Solution

Add two frozen, project-level hunting settings.

- `pod_batch_size`: the number of hunts whose pod sets dispatch together in `batched`. Default 1.
- `promotion_risk_threshold`: the minimum per-threat combined risk that is promoted to a hunter. Default `null`, which means no filter.

The pod batch keeps the existing phase barrier.
Every hunter of the unit must be terminal first.
The unit's hunts are then processed in fixed blocks of `pod_batch_size` in threat-rank order.
Every spec of every hunt in the block dispatches concurrently.
The next block starts only when every consumed spec in the current block has a terminal export.

The promotion filter runs in the mover's produced-inbox read.
A produced threat whose combined `risk` is below the threshold is not an item.
It stays in `produced/` as evidence.
It is excluded from the hunter completion set, the dispatch work, and the run quiesce.
The unit model is consumed once its promoted threats are done.
The below-threshold files remain in `produced/`.
The threat modeller is not aware of the threshold.

## User Stories

1. As an operator, I want to set the number of hunts whose pod sets dispatch together, so that I can tune the pod burst for a target without a code change.
2. As an operator, I want a default of one hunt per pod batch, so that an unconfigured project keeps the current behaviour.
3. As an operator, I want the batch size to apply only to `batched`, so that `serial` stays strictly sequential.
4. As an operator, I want the pod batch to be fixed blocks in threat-rank order, so that the dispatch order is deterministic and re-derivable on resume.
5. As an operator, I want a batch to advance only when every consumed spec in it has a terminal export, so that a partial batch never loses coverage.
6. As an operator, I want a done hunt inside a batch to contribute no work but not slide the next hunt into the batch, so that the block boundary is stable.
7. As an operator, I want a blocked hunt to hold its batch, so that a stale or malformed hunt is never silently skipped.
8. As an operator, I want a zero-spec hunt to count as done immediately, so that it never holds a batch.
9. As an operator, I want a batch size larger than the remaining hunts to clamp to the remaining hunts, so that an over-large value is harmless.
10. As an operator, I want to set a minimum per-threat risk for hunter promotion, so that low-yield threats do not consume hunter and pod budget.
11. As an operator, I want the promotion comparison to be inclusive, so that a threat at exactly the threshold is promoted.
12. As an operator, I want the promotion filter to apply in every sync mode, so that the policy is consistent and `parallel` does not silently ignore it.
13. As an operator, I want an unset promotion threshold to mean no filter, so that the historical behaviour is the default.
14. As an operator, I want below-threshold threats to stay in `produced/` as evidence, so that no research direction is destroyed.
15. As an operator, I want below-threshold threats to be excluded from the hunter completion set and quiesce, so that the run can complete.
16. As an operator, I want the unit model to move to `consumed/` once its promoted threats are done, so that the unit has a clean completion marker.
17. As an operator, I want the below-threshold files to remain after the model moves, so that the evidence is still inspectable.
18. As an operator, I want the promotion filter to run before the low-tier sequencing, so that a below-threshold high-tier threat cannot hold a promoted low-tier threat.
19. As an operator, I want the run record to carry both frozen values, so that a resume and an audit use the same policy.
20. As an operator, I want a resume to prefer the run record over the current project settings, so that a mid-run PUT cannot change a running or resumed run.
21. As an operator, I want a malformed stored value to fall back to the documented default with a warning, so that a typo cannot disable the pipeline.
22. As an operator, I want the hunting config REST surface to read and write both settings, so that the frontend and the eval harness can set them.
23. As an operator, I want an unknown field or an invalid value refused with nothing landing, so that a bad config cannot half-apply.
24. As a developer, I want the pure sync policy to take the batch size as an explicit input, so that the decision stays pure and testable.
25. As a developer, I want the promotion decision to be one pure predicate shared by the mover and the sync gate, so that dispatch and quiesce cannot disagree.
26. As a developer, I want the promotion filter in the mover's produced-inbox read, so that `run_work_remaining` and `run_delivery_tick` see the same items.
27. As a developer, I want the completion audit to ignore below-threshold produced threats, so that a demoted threat never blocks the run terminal.
28. As a developer, I want the dispatch-gap diagnostic to count only promoted threats, so that it reports a real gap.
29. As a developer, I want the model-consume primitive to treat below-threshold stems as non-pending, so that the model can move while the evidence stays.
30. As a developer, I want the existing seams reused, so that no new store, session, or ledger is introduced.
31. As a test author, I want to pin the batch block selection without a store, so that every boundary is covered by the pure tier.
32. As a test author, I want to pin the promotion lifecycle with a temp store, so that the produced and consumed state is real.
33. As a test author, I want a runtime test for the frozen values and the resume, so that a mid-run PUT is proven ineffective.
34. As a test author, I want an integration test with promoted and demoted threats, so that the hunter dispatch, the pod batch, and the model consume are proven end to end.
35. As an operator, I want the default configuration to reproduce the current behaviour, so that existing projects are unaffected.

## Implementation Decisions

### Configuration contract

- `pod_batch_size` is an integer at least 1.
- Its default is 1.
- `promotion_risk_threshold` is an integer at least 0, or `null`.
- Its default is `null`.
- Both live in `settings.hunting`.
- `GET /projects/{project_id}/hunting/config` returns both beside `pipeline_sync` and `risk_threshold`.
- `PUT /projects/{project_id}/hunting/config` accepts a partial body with `extra="forbid"`.
- An explicit `null` clears the effective value: `pod_batch_size: null` reads back 1, and `promotion_risk_threshold: null` reads back `null`. The stored key may remain present as a JSON null (the same convention as `risk_threshold`).
- A malformed stored value reads back the default with a warning.
- On resume, a malformed run-record value warns and falls through to the project setting; a malformed project setting warns and falls back to the default.
- On resume, the run record wins over the project setting.
- Both values freeze at run start.
- Both values are stamped on every run-record write beside `pipeline_sync`.
- There is no environment fallback.
- These are project-level pipeline settings, not model settings.

### Pod batch policy

- The batch size applies to `batched` only.
- `serial` ignores it and stays one hunter and one pod at a time.
- `parallel` has no gate and ignores it.
- The hunter phase is unchanged: every threat of the unit dispatches concurrently after the modeller pass settles.
- The pod phase starts only when every hunt of the unit is terminal.
- The unit's hunts are rank-ordered by `hunt_rank`.
- The first not-done hunt determines the block start: `start = (index // pod_batch_size) * pod_batch_size`.
- The block is `hunts[start:start + pod_batch_size]`.
- Every non-terminal spec of every hunt in the block is admitted.
- The block advances when every hunt in the block is done.
- A hunt is done when it has no pending threat file, is not mid-graph, has no live pod, is not blocked, has a terminal marker for this run, has no pending spec, and every consumed spec has a durable export.
- A done hunt in the block contributes no work and does not slide the next hunt into the block.
- A blocked hunt holds the block.
- A zero-spec hunt is done immediately.
- A batch size larger than the remaining hunts clamps to the remaining hunts.
- The default of 1 reproduces the current per-hunt cursor behaviour.

### Promotion policy

- One pure predicate decides promotion.
- The full hunt list includes only promoted, dispatchable, observable hunts. A zero-risk threat has no threat file (S2 8.3); a refused threat has no observable artifact. Neither can hold the pod phase.
- A hunt is observable when it has a produced or consumed threat item, a spec folder, a live graph or pod, a blocked marker, or a current-run terminal marker.
- A produced threat is promoted when its computed combined `risk` is at least the threshold.
- A threshold of `null` or 0 promotes every valid threat.
- A combined risk of 0 is already refused by the threat validity predicate.
- A threat whose combined risk is unreadable is a refusal, never a demotion. The completion audit sees it while the unit model is produced; a refused file that remains after the model moves is left as evidence, the same pre-existing fail-open as any refused threat file.
- The mover's produced-inbox read applies the predicate.
- A demoted threat is not an item.
- The demoted threat id is carried as non-pending for the unit's model consume.
- A unit with at least one promoted threat stays produced until the promoted threats are consumed.
- A unit with no promoted threat after the last consumed promoted threat is consumed on the next tick.
- Its demoted files stay in `produced/`.
- Recovered consumed threats are never filtered. They were admitted under the frozen threshold.
- The filter runs before the low-tier sequencing.
- `run_work_remaining` and `run_delivery_tick` pass the same threshold to the same read.
- The completion audit ignores demoted produced threats and the demoted hunt's leftover spec folder, including after the unit model moves to `consumed/`.
- The gate's lifecycle read uses the same demoted-hunt resolution, so a leftover spec folder cannot hold the pod phase after the model moves.
- The mover's spec inbox drops a spec whose hunt is demoted; the gate excludes that hunt from the pod block. A demoted hunt's leftover spec is evidence, not work.
- The dispatch-gap diagnostic counts only promoted produced threats.
- The unit risk budget and the unit queue order are unchanged. They still use every stored threat.
- The threat modeller is not aware of the threshold.

### Ownership

- The policy lives in `pipeline_sync.py`.
  It owns the block selection, the promotion predicate, the setting resolvers, and the gate fields.
- The inbox filtering and the model-consume plumbing live in `mover.py`.
- `surfer.py` passes the frozen threshold and the gate. It owns no promotion logic.
- `runtime.py` reads the settings, resolves the frozen values, stamps the record, and wires the gate and the run state.
- `project_management/repository.py` and `project_management/api.py` expose the config.
- `threat_model_store.py` accepts non-pending stems on the model consume.

### Failure handling

- A malformed stored value falls back to the default with a warning.
- A failed settings read fails open to the defaults.
- A demoted threat is never an error and is never logged as a refusal.
- A blocked or stale hunt still holds its batch, unless the hunt is demoted: a demoted hunt's leftover spec is evidence, not work, and is dropped from the mover's spec inbox.
- A missing durable export still holds the batch.

### Observability

- The run record carries `pod_batch_size` and `promotion_risk_threshold`.
- The batch block is derivable from the model, the run record, and the exported specs.
- No new session, store, or ledger is introduced.

## Testing Decisions

- The pure tier tests `decide` and `batch_state` with `pod_batch_size` 1, 2, and larger than the hunt set.
  It pins block selection, non-sliding, blocked, zero-spec, and default behaviour.
- The gate tier tests `RunSyncGate` with a fake threat store.
  It pins the batch fact reads and the demoted-hunt filtering.
- The mover tier tests `read_produced_inbox` and `run_delivery_tick` with a temp `ThreatModelStore`.
  It pins the demoted item omission, the model consume, and the below-threshold files.
- The surfer tier tests `run_work_remaining` and `is_run_quiesced` with the threshold.
  It pins the all-demoted false and the promoted true.
- The lifecycle tier tests `hunting_artifacts_terminal` with a demoted produced threat.
  It pins the audit pass.
- The runtime tier tests the run record and the resume.
  It pins the frozen values and the mid-run PUT.
- The API tier tests GET and PUT defaults, validation, and partial merge.
- The integration tier runs one model with promoted and demoted threats through the mover and the gate.
  It pins the hunter dispatch, the pod batch, the model consume, and the run terminal.
- Existing prior art: `tests/attack/test_hunting_pipeline_sync.py`, `tests/attack/test_hunting_pipeline_sync_gate.py`, `tests/attack/test_hunting_mover_sync_filter.py`, `tests/attack/test_hunting_pipeline_sync_lifecycle.py`, `tests/attack/test_hunting_run_lifecycle.py`, `tests/attack/test_threat_model_store.py`, and `tests/project_management/test_hunting_config_api.py`.
- Tests assert external behaviour only: the admitted message ids, the produced and consumed files, the run record, and the REST body.
- No new seam is introduced.
- The highest existing seam is preferred: the pure `decide` for the batch, the mover inbox for the promotion, and the REST config for the settings.

## Out of Scope

- A per-target pod concurrency cap. Ticket 433 rejected it.
- A batch-scoped watchdog. Ticket 434 rejected it.
- A change to the risk halt or the unit queue order.
- A change to the threat modeller prompt or schema.
- A new store family for demoted threats.
- A durable sync ledger.
- A change to the verdict processing.
- A migration of old runs. An old run without the keys reads the defaults or the settings on resume.

## Further Notes

- The pod batch size is a ceiling, not a reservation. The shared dispatch gate width still bounds admission.
- A large batch on a slow target can saturate the target. The operator sets it per project. The default is 1.
- The promotion threshold is per threat.
  A unit whose total risk is high because of many demoted threats still queues early.
  That is the consequence of keeping the modeller unaware.
- The promotion threshold does not reduce the unit risk budget.
  A run can halt on threats that would not be promoted.
  This is intentional: the halt is a modelling budget, the promotion is a dispatch policy.
- The default configuration reproduces the current behaviour.
- The alternative of filtering inside the threat modeller was rejected because it would make the modeller aware of a dispatch policy.
- The alternative of moving demoted threats to a separate family was rejected because it would destroy the "left in produced as-is" evidence contract.
- The alternative of a sliding window was rejected because it would make the batch boundary depend on completion timing instead of the frozen rank order.
