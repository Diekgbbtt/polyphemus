# Pod triager minimisation: token and quality feasibility

> **Staged update 2026-10-23:** the pure-removal scenario below is the lower bound.
> The recommended staged design is in `POD-TRIAGER-STAGED-FIRST-CALL-CLAIM.md`.
> The staged design keeps the 4 variants and the 20 symptom-confirmed pods at about 280k capped, with the 19 first-shot pods at about 10k each.

## Scope

This report assesses a change requirement for the `pod_triager` in the test-executor pod.
The measured trial is the successful 7M white-jotter trial `white-jotter-1-20261022T030303-1618c524`.
The measured code is `5789ad3f`.
The current code base is `1ef3e548` on `fix/context-lifecycle-followup`, which already carries the pod compaction wiring and typed-procedure dedup.
The design authority is `docs/design/hunting-67-test-executor-pod-spec.md` section 8.6 and `docs/design/hunting-84-pod-memory-system-spec.md`.
The role prompt is `src/polymerhus/attack/hunting/prompts/pod-triager.md`.
The code surfaces are `pod/agents.py`, `pod/graph.py`, `pod/edge.py`, `pod/context.py`, `pod/pod.py`, and `pod/types.py`.

The proposed change is to reduce the triager to three jobs:

1. assess a runner functional failure;
2. assess a spec test-procedure divergence;
3. otherwise, when the run is clean, move to the deterministic `PodExport` write.

The change removes the assessment of new test-spec variants: the procedure-gap mining, the `failure-mode` fallback, the `variant_spec`, and the variant branch.
This report prices that change against the measured trial and assesses its technical feasibility.

## Bottom line

The change is technically feasible and strongly token-positive.
It is not quality-neutral on the measured evidence.
The triager did mint variants: 4 exported variants plus 1 in-flight variant.
Those variants produced 1 symptom-confirmed pod, 2 deeper negative pods, and 1 in-flight pod.
The one symptom-confirmed pod is off-spec: the original per-address-throttle symptom was falsified, and the minted v2 confirmed a different authority-selection symptom.

The triager's measured cost is:

| Metric | Value |
|---|---:|
| Calls | 79 |
| Sessions | 24 |
| Cached input | 1,674,880 |
| Uncached input | 850,278 |
| Reasoning output | 151,997 |
| Visible output | 37,912 |
| Generated output | 189,909 |
| Total tokens | 2,715,067 |
| Capped tokens | 1,040,187 |

The user's "1M uncached plus 200k output" is close but not exact.
The uncached input is 850,278.
The generated output is 189,909.
The 1,040,187 figure is the capped total, which is uncached input plus generated output.
The remaining 1.67M is cached input.

The minimised triager should cost about 192k capped tokens, which is 24 one-call assessments at about 8k tokens each.
The savings are about 848k capped tokens and about 2.52M total tokens.
That is 81.5% of the triager's capped cost and 11.2% of the 7.55M trial cap.
The per-export cost falls from 45.2k capped to 8k capped.
The product/tokens ratio rises from 22 exports per 1M capped tokens to about 120, a 5.4x improvement.

The 23 pod exports stay the same if the one-call assessment preserves the current clean and terminal behaviour.
The 20 symptom-confirmed pods become 19: the off-spec `forwarded-address-counter` success is lost.
The no-symptom count rises from 3 to 4.
The 4 exported variants and the 1 in-flight variant disappear.
The one off-spec symptom confirmation disappears.
The two deeper negatives disappear.
The one in-flight pod remains unresolved.

The recommendation is to proceed with the minimisation, but not as a blanket removal.
Keep a bounded variant path through the hunter's spec or a separate low-cost variant miner.
The measured variant product is small but real: one real authority bug, two stronger negatives, and one in-flight test.
The 848k capped saving is large enough to fund about 7 hunter loops, about 10 pod runs, or about 104 modeller calls at the observed role costs.

## Premise check

The premise that no variants are ever minted is false.

The pod store has 23 exported pod results and 4 no-export pods.
The 23 exports contain 4 variant records:

| Pod | Variants | Basis | Result | Clean |
|---|---:|---|---|---|
| `forwarded-address-counter_per-address-throttle` | v0, v1, v2 | `bypass-technique`, `advanced-technique` | symptom-confirmed | True |
| `account-state-disclosure_disabled-verdict` | v0, v1 | `advanced-technique` | no-symptom-evidence | False |
| `forwarded-address-record_audit-address-echo` | v0, v1 | `advanced-technique` | no-symptom-evidence | False |
| `filter-tier-verdict-gap_permission-denial-envelope` | v0, v1 | `advanced-technique` | no export, in flight | not reached |

The `filter-tier` pod is the 4th no-export pod and carries a minted v1 at the stop.
That makes 5 minted variants in total, 4 exported and 1 in flight.
The variants are not zero.
The variant rate is 4 pods with variants out of 27 pod directories, or about 15%.

The successful variant pod is also the strongest quality caveat.
`forwarded-address-counter_per-address-throttle` began with a per-address rate-limit symptom.
The v0 probes falsified that symptom.
The v1 `bypass-technique` variant changed the spec to a path-override symptom and falsified that too.
The v2 `advanced-technique` variant changed the spec again, to an authority-field upstream-selection symptom, and confirmed it.
The confirmed symptom is a different vulnerability from the original spec.
The pod export records `symptom-confirmed`, but the confirmation belongs to the v2 derived spec, not the per-address-throttle spec that the pod directory names.

That is an off-spec success.
It is a real finding, but it is not the original spec's finding.
The parent and the hunter must not treat it as the original symptom's confirmation without the variant provenance.

The two no-symptom pods with variants are different.
`account-state-disclosure_disabled-verdict` v0 already refuted the symptom as probed.
The v1 `advanced-technique` variant ran the full roster sweep, case and whitespace forms, timing, and alternate sign-in handlers.
It refuted the symptom at full coverage.
`forwarded-address-record_audit-address-echo` v0 proved the relay fact and the record-layer negatives.
The v1 `advanced-technique` variant searched the origin object graph and closed the out-of-band consumer space.
Both variants deepen the negative evidence.
Both are still `clean=False`, so the pods remain honest no-symptom results rather than clean absences.

The `filter-tier` v1 is in flight.
Its v0 falsified the original CORS-tier symptom, and the v1 is an alternate-spelling advanced variant.
The run stopped before the v1 produced a terminal export.
Its product is unknown.

## Design intent

The pod is an actor-critic pair.

The Runner is the actor.
It runs a ReAct loop over one `stateful_turn` per stretch.
It authors probes, executes them, reads the observations, and writes one consolidated experiment-summary note at exhaustion.

The Triager is the critic.
The design says it reads the note and the filtered experiment log, then emits a binary verdict or mines a third-party variant.
The two terminal outputs are `successful` or `unsuccessful`.
The six terminal reasons are `symptom-confirmed`, `space-exhausted`, `technical-infeasibility`, `specific-defence-prevention`, `no-symptom-evidence`, and `budget-timeout`.
The `clean` flag separates clean completed observations from blocked, unreachable, or mid-flight observations.

The variant function is specified in section 8.6.
The triager reads the typed seven-field `SkillProcedure` from `spec.provenance["skill_procedure"]`.
It compares that procedure with the executed procedure from the D6 trail.
It tests the execution triggers first: `runner-failure` and `runner-divergence`.
It then tests the seven procedure-gap bases in order: `recon-action`, `bypass-technique`, `technology-grounding`, `pro-tips`, `advanced-technique`, `preliminary-chaining`, and `interpretation-pitfall`.
If every populated gap class is covered, it may use the `failure-mode` fallback.
A duplicate basis and detail is refused.
The derived spec is recorded as a `VariantSpec` with the basis in `declined_attribute`.
The pod memory keeps `variants/<variant-ref>.yaml` and `experiment-log/<order>.yaml`.

The `PodExport` is not written by the triager.
The deterministic terminal node `_export` writes it.
The export body is the D5 verdict plus the D6 evidence: `variant_specs`, `raw_observations`, `interpretations`, `terminal_reason`, `clean`, and `init_validation`.
The pure-log invariant says no tool writes the export.
The export is written by the graph.

The triager's intended product is therefore two things:
a terminal verdict with a clean flag, and, when the evidence warrants it, a new falsifiable variant.
The change requirement removes the second product.

## What the triager actually did

The 24 triager sessions cover all 23 exports plus the in-flight `filter-tier` pod.
There are 79 model calls, or about 3.3 calls per session.
The calls range from 2 to 7 per session.
The triager is therefore not a symbolic no-op in this trial.
It ran on every pod, including the 20 symptom-confirmed pods.

The measured per-session totals show the cost distribution:

| Pod | Calls | Total | Uncached | Cached | Generated |
|---|---:|---:|---:|---:|---:|
| `forwarded-address-record_audit-address-echo` | 6 | 348,373 | 69,488 | 262,400 | 16,485 |
| `forwarded-address-counter_per-address-throttle` | 7 | 323,351 | 61,632 | 234,752 | 26,967 |
| `forwarded-address-gate_address-gated-decision` | 5 | 250,203 | 56,441 | 182,912 | 10,850 |
| `account-state-disclosure_disabled-verdict` | 6 | 193,631 | 34,919 | 143,104 | 15,608 |
| `filter-tier-verdict-gap_permission-denial-envelope` | 4 | 179,229 | 39,361 | 118,400 | 21,468 |

The remaining 19 exported sessions cost between 33,569 and 159,660 total tokens each.
The 20 symptom-confirmed pods account for about 1.42M total triager tokens.
The 4 variant pods account for about 1.04M total triager tokens.
The 1 no-symptom v0 pod accounts for about 250k total triager tokens.
The three no-symptom pods account for about 791k total triager tokens.

The triager's tool surface explains the large KB read in the context audit.
It has `note`, `query_lightrag`, `graph_view`, `load_skill`, and `record_skill_lesson`.
It reads the Runner's note, the filtered experiment log, the current spec, the typed skill procedure, the variants already tried, the probe commands, the raw observations, the interpretations, and the memory guidance.
The largest single payload in the measured context audit was an 89,087-char KB answer in a triager session, about 22.3k tokens.
The triager's highest input was 76,557 tokens.

The triager is therefore paying for a critic with KB and skill research capability, a variant-mining algorithm, and a multi-turn session.
The measured variant output is 5 variants, one off-spec success, two deeper negatives, and one in-flight pod.

## Product/tokens ratio

The current ratios are:

| Product | Count | Capped tokens | Capped tokens per product |
|---|---:|---:|---:|
| Exports | 23 | 1,040,187 | 45,225 |
| Symptom-confirmed pods | 20 | 1,040,187 | 52,009 |
| Variants minted | 5 | 1,040,187 | 208,037 |
| Exported variants | 4 | 1,040,187 | 260,047 |
| Off-spec symptom success | 1 | 1,040,187 | 1,040,187 |
| Deeper negative pods | 2 | 1,040,187 | 520,094 |
| In-flight variant pod | 1 | 1,040,187 | 1,040,187 |

The 20 symptom-confirmed pods are the triager's main product in count.
Most are not caused by the triager.
The Runner's probes produce the observation.
The Triager's verdict and clean flag are necessary for the export, but the one-call replacement can preserve them.
The variant-specific product is the 4 exported variants plus the 1 in-flight variant.
That product costs the triager's full 1.04M capped in the current design because the variant context is part of the same session.
The marginal product per 1M capped is 4 exported variants and 1 off-spec success.
The two deeper negatives are valuable but not symptom discoveries.

The per-session product is also weak:
the highest-cost session, `forwarded-address-record_audit-address-echo`, produced a no-symptom result with a deeper negative, and cost 348k total.
The second-highest, `forwarded-address-counter`, produced the off-spec success and cost 323k total.
The no-symptom v0 `forwarded-address-gate` cost 250k total and produced no variant.
The 20 symptom-confirmed sessions cost 1.42M total for confirmations that the Runner observed.

The current design is therefore under-optimised in the user's sense.
The triager is expensive relative to the marginal decision it adds.
The variant capability is not zero, but it is a small, mixed product.

## Proposed minimised role

> **Staged update 2026-10-23:** this section is the pure-removal lower bound.
> The recommended staged design is in `POD-TRIAGER-STAGED-FIRST-CALL-CLAIM.md`.
> The first stage runs the failure and confirmed-symptom check on a compact context.
> The bounded-variant stage receives the same skill that was fed to the runner, in the same concrete prompt rendering as the spec.
> The staged design keeps the 20 symptom-confirmed pods and the 4 variants at about 280k capped tokens.

The minimised triager should be a one-call structured assessment with a compact context.

It should receive:

- the current spec projection: target identity, verification symptoms, assumptions, and the typed `SkillProcedure` only for the divergence check;
- the Runner's consolidated experiment note;
- the latest raw observation and the executed probe commands;
- the clean and blocked/unreachable evidence needed for the `clean` flag;
- the terminal-reason vocabulary.

The first-stage triage should not receive:

- the full experiment log;
- the variants already tried;
- the KB answer bundle;
- the full skill bodies;
- the graph view;
- the procedure-gap mining instructions;
- the variant-minting schema.

The bounded-variant stage receives the same skill that was fed to the runner, in the same concrete prompt rendering as the spec.
It also receives the typed `SkillProcedure`, the variants already tried, and the KB on demand.
It mints at most one variant, only when the runner is inconclusive and a populated procedure gap exists.
The off-spec guard applies: a variant that changes the symptom must be recorded as a derived spec, not as the original spec's confirmation.

It should return a compact `TriagerAssessment`:

- `runner_failed`: the Runner's execution failed;
- `runner_diverged`: the execution diverged from the spec's procedure;
- `verdict`: `successful` or `unsuccessful`;
- `terminal_reason`: one of the six values;
- `clean`: the clean-completion flag;
- `note`: the interpretation note.

The first-stage assessment should route directly to the deterministic `_export` node when the symptom is confirmed or the runner failed.
The bounded-variant stage keeps a gated `mint_variant` node with a one-variant cap.
The pure-removal lower bound removes the `mint_variant` node, the `decide_router` variant branch, the `variant_basis` resolver, and the `variant_specs` growth.
The staged design keeps the gated branch.
The pod store keeps `variants/v0.yaml` and `experiment-log/0.yaml`; the export keeps the same IA-4 shape.
The `variant_specs` list becomes the initial v0 only, or empty if the parent tolerates it.
The `iterations` count becomes 1.
The `PodExport` remains deterministic and unchanged in shape.

The `PodExport` write is already deterministic.
The user's "if clean move on to write of the PodExport" does not require the triager to write the file.
The deterministic terminal node should keep the write.

The change is a design amendment, not a small prompt edit.
Section 8.6 and its variant contracts C9/C10 would be retired.
The pod memory variant record shape would remain for compatibility, but the variant production would stop.
The parent's binary verdict derivation is unchanged because the six terminal reasons, the clean flag, and the export shape are unchanged.

## Token quantification

The current triager costs 2,715,067 total and 1,040,187 capped.
The measured caps are the client ledger from the trial record.

The minimised estimate assumes 24 one-call assessments at about 8k tokens each:

- about 5k cached or stable context;
- about 2k uncached spec, note, and observation;
- about 1k output and reasoning.

That is about 192k total and 192k capped for the full trial.
The estimate is conservative relative to the measured 8k-10k first-call context of the pod roles.
A 10k per-call variant would be about 240k, still a 77% reduction.

| Metric | Current | Minimised | Change |
|---|---:|---:|---:|
| Calls | 79 | 24 | -55 |
| Total tokens | 2,715,067 | 192,000 | -2,523,067, -92.9% |
| Capped tokens | 1,040,187 | 192,000 | -848,187, -81.5% |
| Cached input | 1,674,880 | 0 in the estimate | -1,674,880 |
| Uncached input | 850,278 | 120,000 | -730,278 |
| Generated output | 189,909 | 24,000 | -165,909 |
| Capped per export | 45,225 | 8,348 | -36,877, -81.5% |
| Capped per success | 52,009 | 10,105 | -41,904, -80.6% |
| Capped per variant | 260,047 | 0 | -260,047 |
| Capped per off-spec success | 1,040,187 | 0 | lost product |
| Capped per deeper negative | 520,094 | 0 | lost product |

The per-export ratio improves from 22.1 exports per 1M capped to about 120 exports per 1M capped.
The total-token ratio improves from 8.5 exports per 1M total to about 120 exports per 1M total.
The improvement is about 5.4x on capped tokens and about 14x on total tokens.

The saved 848k capped tokens are 11.2% of the 7.55M trial cap.
At the observed role costs, that is about:

- 7 hunter loops, at about 127k capped per loop;
- 10 pod runs, at about 82k capped per pod;
- 104 modeller calls, at about 8.1k capped per call.

Those are approximate reallocation units, not a promise of additional coverage.
The cap is shared, and the next trial's schedule decides what the saved tokens buy.

## Quality effect

The minimised role keeps the 19 v0 symptom-confirmed pods.
The off-spec `forwarded-address-counter` success is lost.
The Runner's observations and the deterministic export remain.
The clean flag and the six terminal reasons remain.
The functional-failure and divergence assessment remains, although it was not exercised in the measured exports as a variant basis.
The `runner-failure` and `runner-divergence` triggers were not the basis of the 4 measured variants; the bases were `bypass-technique` and `advanced-technique`.
The minimised triager can still classify a failed or diverged execution and terminate honestly.

The minimised role loses 4 exported variants and 1 in-flight variant:

- the `forwarded-address-counter` off-spec symptom confirmation;
- the `account-state-disclosure` deeper negative;
- the `forwarded-address-record` deeper negative;
- the `filter-tier` in-flight alternate-spelling variant.

The `forwarded-address-counter` loss is the strongest quality cost.
The pod becomes a fourth no-symptom result, so the no-symptom count rises from 3 to 4.
The v2 confirmed a real authority-selection defect.
The original per-address-throttle spec was falsified, so the v2 was a genuine new finding.
It is off-spec relative to the pod directory and the original spec.
The correct treatment is a hunter re-spec for the authority symptom, not a silent success on the per-address spec.

The two no-symptom variants deepen the negative evidence.
The v0 results already refuted the symptoms as probed.
The v1 advanced variants close the remaining procedure space.
The minimised triager would stop at the shorter v0 negative.
That is a real but modest quality loss, and the hunter can write the advanced technique into the next spec.

The in-flight `filter-tier` variant has no terminal product.
Its loss is unknown.

The net quality effect is therefore neutral to slightly negative in the measured trial.
The token effect is strongly positive.
The product/tokens ratio improves because the removed product is small and one of its items is off-spec.

## Technical feasibility

The change is feasible.

The code changes are localised:

- `pod/agents.py`: replace `TriagerDecision` with the compact `TriagerAssessment`; remove the variant fields; keep the structured output.
- `pod/graph.py`: route the triager directly to the deterministic `_export`; remove or gate the `decide_router` variant branch and the `mint_variant` node; keep the six terminal reasons and the clean flag.
- `pod/context.py`: replace `compose_triager_delta` and `triager_context` with the compact spec, note, and observation context.
- `pod/agents.py`: reduce `triager_react_tools` to the note read and the spec/observation context; remove the KB, the graph view, the skill load, and the record-skill-lesson tool from the minimised path.
- `prompts/pod-triager.md`: rewrite the role to the three checks.
- `pod/types.py`: keep `VariantSpec` and `PodExport` for the store and export shape; the triager no longer creates variants.
- `pod/edge.py` and `pod/variant_basis.py`: the mining algorithm becomes dead or gated; the deterministic basis helpers can be removed from the minimum path.
- The tests: the variant mining tests, C9/C10, the `mint_variant` graph tests, and the triager decision tests change; the export tests, the clean tests, the six-reason tests, the C2 binary terminal tests, and the note tests stay.
- The design spec: amend section 8.6 and the variant acceptance criteria; record the new contract as a design decision, not an unstated removal.

The estimated implementation effort is about 1 to 2 engineering days for the code and tests, plus the design amendment and one measurement trial.
The main uncertainty is not the code.
It is the quality policy for the removed variant product.

The risk is the off-spec success and the deeper negatives.
The mitigation is a bounded variant path:

- let the hunter's `TestImplementationSpec` carry the advanced techniques and alternative procedure from the start;
- or keep a separate low-cost variant miner that is called only when the runner's observation is inconclusive and the spec's procedure has a populated uncovered gap;
- cap it at one variant per pod;
- forbid symptom-changing variants unless the spec's provenance records the new symptom as a derived spec;
- require the variant to keep the parent symptom identity or mark the parent spec as superseded;
- measure the variant rate and the off-spec rate in the next trial.

The triager should not keep the full variant context in the confirmed-symptom stage.
The bounded-variant stage does keep the skill, the typed procedure, the variants already tried, and the KB on demand.
The bounded variant path stays inside the triager but is gated to the ambiguous pods.

## Recommendation

Proceed with the minimisation as the default.
The staged design is the recommended implementation; the pure-removal numbers in this section are the lower bound.
The measured triager cost is 1.04M capped for a product that is dominated by the 20 measured confirmations the Runner produced.
The one-call assessment preserves the 23 exports and the 19 v0 symptom-confirmed pods, the clean flag, and the six terminal reasons.
The off-spec `forwarded-address-counter` success is lost.
The measured saving is about 848k capped and about 2.52M total, with a 5.4x capped-token product ratio improvement.

Do not treat the variant removal as free.
The measured trial produced 4 exported variants and 1 in-flight variant.
One variant confirmed a real authority-selection defect off-spec.
Two variants deepened the negatives.
One is unresolved.
Preserve that value through the hunter spec or a bounded variant miner.

The practical sequence is:

1. Add a `POD_TRIAGER_VARIANT_MINING=0` default and keep the current branch behind the flag.
2. Implement the one-call `TriagerAssessment` and the compact context.
3. Keep the deterministic `PodExport` and the six terminal reasons unchanged.
4. Add the off-spec guard if any variant path remains: a variant that changes the symptom must be marked as a derived spec with a new parent symptom, not a success on the original spec.
5. Run the next trial on the same target and compare the 20 measured and 19 expected symptom-confirmed pods, the GT yield, the clean flags, the variant rate, the off-spec rate, and the triager tokens.
6. If the GT yield holds and the off-spec rate falls, retire the variant path.
   If the GT yield falls, restore the bounded variant miner rather than the full triager.

## Reproduction

The trial spend is in `trial.yaml` under `spend_by_agent.pod_triager`.
The measured values are cached 1,674,880, uncached 850,278, reasoning 151,997, visible 37,912, generated 189,909, total 2,715,067, capped 1,040,187, calls 79.

The per-session values are in the Langfuse `pod_triager` sessions under the run id `5c9590ff-9a83-4cea-9aff-be1bd51e2667`.
The trial store is under `hunting/test-executor-pod/`.
The variant records are the `variants/<ref>.yaml` files and the `evidence.variant_specs` in each `<run_id>.yaml` export.
The off-spec evidence is the `forwarded-address-counter_per-address-throttle` v0, v1, and v2 specs and their experiment logs.
The two negative variants are the `account-state-disclosure_disabled-verdict` v1 and the `forwarded-address-record_audit-address-echo` v1.
The in-flight variant is the `filter-tier-verdict-gap_permission-denial-envelope` v1.

The design references are:

- `docs/design/hunting-67-test-executor-pod-spec.md` sections 1.1, 1.3, 1.5, 1.7, 6.4, and 8.6;
- `docs/design/hunting-84-pod-memory-system-spec.md` sections 3, 6, 7, 13, and 14;
- `src/polymerhus/attack/hunting/prompts/pod-triager.md`;
- `src/polymerhus/attack/hunting/pod/agents.py`;
- `src/polymerhus/attack/hunting/pod/graph.py`;
- `src/polymerhus/attack/hunting/pod/context.py`.

## Limitations

The minimised token estimate is an estimate, not a measured run.
It assumes 24 one-call assessments at about 8k tokens.
The actual context may be higher if the divergence check needs the full typed procedure and the executed probe chain.
The 10k-per-call upper bound still gives a large saving.

The 4 exported variants are exact from the pod store.
The 5th in-flight variant is inferred from the `filter-tier` pod's `variants/v1.yaml` and its missing terminal export.
The in-flight variant has no terminal product.

The 20 symptom-confirmed pods are counted from the pod exports.
The triager's exact per-pod token attribution is from the Langfuse sessions.
The client ledger and Langfuse agree on the role total within rounding.

The off-spec classification is based on the v0, v1, and v2 verification symptoms in the stored specs.
The product is a real authority-selection finding, but it is not the original per-address-throttle symptom.
The parent's treatment of that export is a separate contract question.

The current code `1ef3e548` has the compaction wiring and the typed-procedure dedup, so the measured trial's triager context is slightly larger than the current code's base.
The relative savings of removing the variant context remain.
The absolute current cost should be re-measured on a fresh trial before the change is declared final.
