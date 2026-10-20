---
artifact: experiment-results
version: "1.0"
created: 2026-10-19
status: completed-with-one-trial-ended-early
---

# Experiment Results: Arm L - the #384/#385 fixes and the analysis thinking baseline (high vs max)

## Summary

| Attribute | Value |
|-----------|-------|
| **Experiment ID** | `arm-l` |
| **Experiment Name** | Arm L: deployment-neutral auth (#384), structured-channel recovery (#385), and the assigner/typist thinking baseline (as-is vs max) |
| **Status** | Trial 1 completed; trial 2 ended early (a harness read-timeout cut the hunting arm after the analysis had drained) |
| **Duration** | 2026-10-19 08:41Z to 2026-10-19 11:55Z (3 h 14 m) |
| **Traffic Allocation** | Not applicable: two sequential full-pipeline trials, one target each, one trial per arm |
| **Total Sample Size** | 1 target (`white-jotter`) x 2 arms; n=1 per arm |
| **Owner** | implementation session (arm L) |
| **Design Doc** | `docs/design/plans/2026-10-19-arm-l-384-385-and-thinking-trials.md` |

The stack for both trials is the same commit: `eval_sha` `7c7b5d1fedab1c9183a384216271b0c971158418`, `stack_fingerprint` `148279b469e731a46c572381531d7fd0ce6055adb32c1678739503d2f4e45044`.
The only changed variable between the two trials is the declared thinking baseline of `assigner` and `mechanism_typist`: `medium` (negotiated to the wire `reasoning_effort=high`) in trial 1, `max` (wire `max`, exact match) in trial 2.
The change was applied in place on the instance checkout, its live remount asserted inside the agent container before the trial, and stashed after the trial.

## Hypothesis Recap

**Original hypothesis, H1 (the fixes):**

> The arm K failure had two independent roots, both fixed in this iteration.
> (a) A data-dependency auth artifact carried the bootstrap deployment address instead of the project's run-stable origin, so the auth gateway replayed a dead host:port, thrashed, and ran recon unauthenticated (#384).
> (b) A structured turn whose answer arrived as message text was misread as a blackloop and its schema-valid payload was silently dropped, taking the whole typed-edge layer with it (#385).
> We believed that removing deployment origins from the data plane and resolving them from `settings.recon.target_seed` at the auth seam, plus a bounded structured-channel recovery, would restore both the authenticated recon surface and the typed-edge layer, lifting GT unit well-formedness from arm K's 0.381 toward or past arm J formal's 0.660.

**Original hypothesis, H2 (the thinking baseline):**

> Raising the declared thinking of `assigner` and `mechanism_typist` from the as-is baseline (wire `high`) to the model's maximum (wire `max`) would improve the analysis further, by giving the ownership and mechanism judgments more reasoning per turn.

**Success criteria:**

- Primary metric: GT unit well-formedness target score above arm K's 0.381 and at least at arm J formal's 0.660.
- The typed-edge family M4 at arm J formal's level (arm K: 1/17; arm J formal: 12/17).
- The auth gateway produces a verdict and authenticates the run, with no orchestrator thrash.
- H2 judged directionally (one trial per arm; the instrument is deterministic, so significance testing does not apply).

## Results

### Primary Metric: GT unit well-formedness (7 white-jotter specs)

The instrument is `tools/measure_gt_wellformedness.py` over the local-only 13-spec corpus, 7 white-jotter specs.
Both graphs were measured with the same corpus, the same instrument and the same query set.
M1 is the alias bridge, M2 the endpoint/parameter placement, M3 the Service field shape, M4 the typed-edge shape.

| Variant | Target score | M1 | M2 | M3 | M4 | Analysis passes / L0 assets |
|---------|-------------:|---:|---:|---:|---:|---:|
| Arm J formal | 0.6603 | 7/7 | 5/16 (31.2%) | 19/20 (95.0%) | 12/17 (70.6%) | n/a |
| Arm K | 0.3810 | 7/7 | 4/16 (25.0%) | 13/20 (65.0%) | 1/17 (5.9%) | n/a |
| **Arm L, trial 1 (`high`)** | **0.6968** | 7/7 | 7/16 (43.8%) | 17/20 (85.0%) | 12/17 (70.6%) | 9 / 681 |
| **Arm L, trial 2 (`max`)** | **0.7159** | 7/7 | 7/16 (43.8%) | 19/20 (95.0%) | 12/17 (70.6%) | 9 / 681 |

**Observed difference, high -> max:** +0.0191 target points (+2.7% relative).
The whole difference is one spec's M3 fields (`white-jotter-002`, 0.589 -> 0.722); every other spec is identical.

**Statistical significance:** not applicable.
There is one trial per arm, and the GT unit criterion is a deterministic per-requirement share, not a sampled estimate.
The comparison is descriptive; a per-requirement share of 1/20 moves the target score by about 0.007, so the `high` vs `max` delta is within a few requirement ticks.
It is directional evidence, not a measured effect size.

**Interpretation:**

H1 is confirmed.
The two fixes lift the target score to 0.697 (as-is thinking) and 0.716 (max), above both prior arms (arm K 0.381, arm J formal 0.660).
The recovery is exactly where the diagnosis predicted: M4 typed edges go from arm K's 1/17 to 12/17, the arm J formal level, and M2 placement improves from 25.0% to 43.8%.
H2 gets a small, one-spec directional gain; it does not transform the analysis.

### Secondary Metrics

| Metric | L `high` | L `max` | Difference | Significant? |
|--------|---------:|--------:|-----------:|--------------|
| C1 `endpoint_placement` | 71/114 = 62.3% | 29/114 = 25.4% | -36.9 pts | Not testable (n=1) |
| C1 `orphan_services` | 3 of 12 | 3 of 12 | 0 | No |
| C2 `system_anchoring` | 14/15 = 93.3% | 14/15 = 93.3% | 0 | No |
| C2 `orphan_systems` | 1 | 1 | 0 | No |
| C3 `evidenced_by_edges` | 95 | 98 | +3 | No |
| C3 systems with witnesses | 14 | 7 | -7 | Not testable |
| C5 `l1_l0_grounded` | 23/27 = 85.2% | 16/27 = 59.3% | -25.9 pts | Not testable |
| C5 L1->L1 typed edges | 44 | 37 | -7 | No |
| C5 L1 nodes | 27 | 27 | 0 | No |

Per-role analysis usage (capped tokens / calls / reasoning tokens):

| Role | L `high` | L `max` | Difference |
|------|---------:|--------:|-----------:|
| `assigner` | 100,258 / 15 / 32,992 | 77,970 / 16 / 18,723 | -22,288 capped |
| `mechanism_typist` | 671,815 / 78 / 88,496 | 457,596 / 97 / 87,023 | -214,219 capped |
| `triager` | 112,449 / 17 / 12,497 | 82,029 / 17 / 12,845 | -30,420 capped |
| Analysis total | 884,522 / 110 | 617,595 / 130 | -266,927 capped |

Whole-project C4 (usage pull after the run; both trials' late calls included):

| Metric | L `high` | L `max` |
|--------|---------:|--------:|
| `cached_share_total` | 92.4% | 92.6% |
| `input_uncached` | 2,874,483 | 3,135,769 |
| `output_tokens` | 1,164,407 | 1,034,783 |
| `capped_tokens` | 4,038,890 (+38,890) | 4,170,552 (+170,552) |
| `calls` | 1,053 | 982 |

### Guardrail Metrics

| Metric | L `high` | L `max` | Threshold | Status |
|--------|---------:|--------:|-----------|--------|
| Auth gateway verdict + authenticated run | verdict produced; registration replay minted `wjbootstrap4821`; store stays path-only | same | must authenticate | Pass |
| Orchestrator resistance to thrash | 15 calls / 25,304 capped | 11 calls / 18,914 capped | no runaway loop | Pass (arm K: 852,003-token thread, no verdict) |
| Structured payload loss | 0 dropped (typist/assigner 0 drift; triager 2 recoveries accepted) | 0 dropped (typist/assigner 0 drift; triager 3 recoveries accepted) | no silent loss | Pass |
| Analysis drains | drained 09:10:57, `analysis_drained=true` | drained 10:51:40, `analysis_drained=true` | must drain | Pass |
| Deployment origin in the placed auth store | none (`login_url: /api/login`, no `domain`) | none | none | Pass |
| Trial record complete | yes | **no (harness read-timeout)** | yes | **Fail (trial 2)** |

## Segment Analysis

### By GT spec bundle (`high` -> `max`)

| Spec | L `high` | L `max` | Difference |
|------|---------:|--------:|-----------:|
| white-jotter-001 | 0.800 | 0.800 | 0 |
| white-jotter-002 | 0.589 | 0.722 | +0.133 |
| white-jotter-003 | 1.000 | 1.000 | 0 |
| white-jotter-004 | 0.767 | 0.767 | 0 |
| white-jotter-005 | 0.833 | 0.833 | 0 |
| white-jotter-006 | 0.333 | 0.333 | 0 |
| white-jotter-007 | 0.556 | 0.556 | 0 |

### By per-service typed edges

Both trials place typed edges on 10 of 12 Services (`operations-telemetry` and `password-recovery` stay empty in both).
The composition shifts by arm: trial 1 carries `FRONTED_BY` (10) and `SHAPES_DATA_OF` (8); trial 2 replaces much of that with `ROUTED_BY` (9) and drops `SHAPES_DATA_OF` to 1.
The max run is additionally more selective in endpoint aggregation: 29 of 114 endpoints placed versus 71 of 114, with the same Services and the same GT-required endpoints matched (M2 7/16 in both).

### Segment insights

The entire H2 gain sits in one spec's Service-field shape (`white-jotter-002`), while the same arm loses 37 points of endpoint placement and half the witnessed Systems.
Max thinking therefore made the assigner and typist more selective, not uniformly better.
That is a real behavioral shift, not a workload artifact: both analyses ran 9 passes over the same 681 L0 assets with 12 dispatches entered.

## Visualization

Not applicable: no time-series or funnel chart is meaningful for two single-trial deterministic scores.
The per-spec table above is the finest-grained view.

## Learnings

### What We Learned

1. **#384 is fixed and live-verified.**
   The placed auth store now carries paths only (`login_url: /api/login`, no `domain`); every read resolves the project's canonical origin (`http://t-1618c524.target` this run).
   The gateway produced a verdict, replayed the sign-up procedure, and minted `wjbootstrap4821-first_authn_bootstrap` in the store.
   The orchestrator used 15 calls / 25,304 capped tokens (trial 1) and 11 calls / 18,914 (trial 2), against arm K's runaway 852,003-token thread with no verdict.

2. **#385 is fixed and live-verified.**
   M4 typed edges recovered from arm K's 1/17 to 12/17 (the arm J formal level), and M2 placement rose from 25.0% to 43.8%.
   The typist and assigner produced zero text-channel drift after the prompt line naming `L1DeltaBatch`.
   The structured-channel recovery nonetheless fired five times in production, always on the recon triager (2 in trial 1, 3 in trial 2), and preserved every payload: the seam converted the failure mode from silent data loss to a loud, bounded, data-preserving recovery.

3. **The triager still answers in text.**
   The recovery path is doing the work the prompt line should prevent: the recon triager's prompt does not name its tool, so it drifts every few turns.
   Nothing is lost, but the recovery turn costs a call per drift.

4. **Max thinking buys little well-formedness and changes the analysis materially.**
   The target score moves +0.019 (one spec's fields), while endpoint placement drops 62.3% -> 25.4% and witnessed Systems 14 -> 7.
   The analysis is also cheaper in capped tokens under max (617,595 vs 884,522), with more calls (130 vs 110).
   With one trial per arm this is directional only.

5. **The trial-1 hunting misses are budget-schedule misses, not analysis misses.**
   All four missed GT vulnerabilities (003 XSS, 004 Log4j/JNDI, 005 SQLi, 006 path traversal) are diagnosed `cap_hit`: the 4M budget is consumed inside the Tier-0 access-control schedule (14 faults) before any Tier-1 validation fault is scheduled.
   The analysis had already made the loci available (the article write/read endpoints, `/api/search` with `keywords`, the media static-file contract).

6. **The checkpoint serde allow-list was empty and every persisted structured envelope loaded back as a plain dict.**
   The trials logged the block for seven types: `L1DeltaBatch`, `GatewayVerdict`, `_ObservationBatch`, `TriagerDecision`, `GateDecision`, `NoteDecision`, `RatifyDecision`.
   Fixed post-trial in `7cfcdaf5` with round-trip tests for the whole family.

7. **The harness can lose a long trial to one slow poll.**
   Trial 2's hunting arm was cut at 87 minutes by a `urllib` read timeout (30 s) on a status poll, not by a product failure; the analysis had already drained.
   The abort also skipped the trial record, so trial 2 has no verdicts or assessment.

### Surprising Findings

- Higher thinking effort lowered endpoint aggregation by 37 points while leaving the GT-required endpoints matched. The assigner under `max` is more selective in what it claims, not more complete.
- `max` consumed fewer capped tokens than `high` on the same 9-pass/681-asset workload. More calls, less cached-context cost per call; the economics need a dedicated study before being trusted.
- The structured-channel recovery was exercised more by a role nobody prompt-fixed (the triager) than by the failing role it was built for (the typist), which no longer drifts.

### What We Still Don't Know

- Whether the placement drop under `max` is robust or a single-trial excursion.
- Whether the H2 gain holds on a second target or a re-run.
- Whether the hunting recall at 4M improves materially once the Tier-0/Tier-1 schedule is budget-aware.
- How much of the trial-1 hunting result (3/7) is attributable to the authenticated surface versus the richer typed-edge layer.

## Recommendation

### Decision: Iterate

**Rationale:**

The fixes are confirmed and should stay.
The thinking comparison does not justify switching the analysis roles to `max`: the well-formedness gain is one spec's fields, while the placement and witness coverage regress substantially and the economics are unexplained.
The next iteration's leverage is elsewhere: the hunting budget schedule (four of seven GT vulnerabilities were never scheduled) and the triager's prompt line.

### If Iterating

- **What to change:**
  - Add the `L1DeltaBatch`-style tool-naming line to the recon triager's prompt (the recovery path proves the payload exists; the prompt should prevent the drift).
  - Harden the eval poll client: retry a read timeout on status polls with a bounded backoff, so a busy app cannot abort a trial.
  - Make the hunting schedule budget-aware (reserve or interleave Tier-1 faults), or raise the white-jotter budget; trial 1 spent the whole 4M inside two Tier-0 classes.
  - Promote the checkpoint serde allow-list fix (already on `dev`) and re-align the instance before the next run.
- **Next experiment:** white-jotter, as-is thinking, with the triager prompt line and the budget-aware schedule; then a second target for the well-formedness generalisation.
- **Timeline:** after the harness retry and the schedule fix land.

## Next Steps

| Action | Owner | Due Date |
|--------|-------|----------|
| Comment #384/#385 with the live verification and close them | implementation session | 2026-10-19 |
| Add the tool-naming line to the recon triager prompt | next iteration | - |
| Add a bounded retry to the eval status-poll client | next iteration | - |
| Budget-aware hunting schedule (Tier-0/Tier-1 interleave or reserve) | next iteration | - |
| Re-run the `max` arm end-to-end if hunting comparability is required | operator decision | - |

Follow-up documents: `docs/experiments/2026-10-19-arm-l-recommendations-1-2-overview.md` (failure modes, root causes and fixes for the two accepted recommendations) and `docs/experiments/2026-10-19-arm-l-high-vs-max-analysis-comparison.md` (the analysis-only comparison and the analysis-owned residual experiments).

## Appendix

### Raw Data

- Trial 1 record: `eval/runs-arml/white-jotter-1/white-jotter-1-20261019T100825-1618c524/trial.yaml` (eval host), project `7a8bdcce-3b81-4113-adad-c3a0876925a7`.
- Trial 1 verdicts + diagnoses: same directory (`verdicts.yaml`, `diagnoses.yaml`).
- Trial 2 graph: project `da6340e5-5f17-4117-9515-edaad54c6ddc`; analysis run `bdaa0acb-5568-46de-a18c-88eddcdde65c` (drained 10:51:40, 9 passes, 681 L0 assets). No trial record (harness abort).
- GT measurement JSON: `/tmp/arml-wj-high-gt.json`, `/tmp/arml-wj-max-gt.json` (implementation host); the instrument is `tools/measure_gt_wellformedness.py`.
- Usage pulls: `GET /projects/{project_id}/usage` on the instance.
- Artifact store: `white-jotter-1/arml-wj-high/...` (trial 1 materialized; trial 2 has no record to materialize).
- Stack: `eval_sha` `7c7b5d1f`, `stack_fingerprint` `148279b4...`.

### Statistical Methodology

- No sampling and no randomisation: each arm is one deterministic full-pipeline trial on one target.
- The GT unit criterion is a per-requirement share over fixed specs; the target score is the mean of the seven spec scores. Differences are reported in points, never as significance.
- Segment analysis is per GT spec and per role; no multiple-comparison correction is meaningful at n=1.
- The M4 comparison against arm J/K reuses the same corpus and instrument on their still-present graphs (`f16de150-...`, `35189233-...`), executed in this measurement session.

### Known Issues

- **Trial 2 ended early.** A harness `urllib` read timeout (30 s) on a status poll aborted the trial at 87 minutes; the hunting arm was cut mid-run and no trial record, verdicts or assessment exist. The analysis had drained before the abort, so the primary criterion is valid; hunting is not comparable.
- **Trial 2's C4 and analysis-usage cells** come from the usage API at measurement time, not a trial record; the analysis-role split is exact, but the analysis/hunting boundary is inferred from the phase timestamps.
- **The serde allow-list fix is not in the trial stack.** Both trials ran `7c7b5d1f` with the empty allow-list; the blocked loads affect checkpoint state fidelity on resume, not the analysis outputs. The fix is `7cfcdaf5`.
- **The arm J formal and arm K comparison points** were re-measured now with the same instrument and corpus, not copied from the earlier documents; the values match the recorded ones (0.6603 and 0.3810).
- **The triager recoveries** are counted from the app log (`stateful_turn triager structured-channel`), five occurrences across the two trials.

---

*Results documented on 2026-10-19.*
