# Pod triager staged decision tree and first-call occupancy claim

## Scope

This report answers two questions.

First, whether the triager's system prompt and fed context are large enough to explain its token tax, and whether the 20 symptom-confirmed pods should have short-circuited to the confirmed-symptom decision at about 10k tokens.

Second, how the triager should be staged so the confirmed path stays cheap while the skill that was fed to the runner remains available for bounded variant mining.

The evidence is the `CONTEXT-OCCUPANCY-ANALYSIS.md` component table for the pod triager, the trial `spend_by_agent.pod_triager`, the 24 triager Langfuse sessions, and the pod store variants.
The measured trial is `white-jotter-1-20261022T030303-1618c524`.
The measured code is `5789ad3f`.
The design authority is `docs/design/hunting-67-test-executor-pod-spec.md` section 8.6.

## The claim

The hypothesis is:

> The triager's system prompt and fed context are significantly large and hinder execution with a high token tax, so the 20 symptom-confirmed pods should reach the confirmed-symptom node and the `PodExport` at about 10k tokens.

The claim is **confirmed in aggregate and falsified in attribution**.

The fixed context and the fed data are large.
The first call is 11,712 tokens.
The fixed system plus tool descriptions are 7,901 tokens, 67.5% of the first call.
The fed human context is 3,613 tokens, 30.8%.
The 20 symptom-confirmed sessions do not short-circuit; they run 2-6 calls and cost about 52k capped tokens per success.
The 10k target is feasible for the confirmed path, and the main saving is the one-call confirmed node, not the system prompt alone.

The system prompt alone is **not** the main cause.
The system prompt is 2,959 tokens, 25.3% of the first call and 12.8% of the session.
The tool descriptions are 4,942 tokens, 42.2% of the first call and 21.9% of the session.
The human feed is 3,613 tokens, 30.8% of the first call and 16.7% of the session.
The tool responses are 13,333 tokens, 47.1% of the session.
The 2-6 calls, the tool descriptions, and the tool responses drive the lifecycle.
The system prompt is a minority of both the first call and the session.

## Occupancy evidence

The pod-triager table from the occupancy analysis:

| Component | Session tokens | Session share | First-call tokens | First-call share | Class |
|---|---:|---:|---:|---:|---|
| system | 3,614 | 12.8% | 2,959 | 25.3% | N/C |
| human input | 4,730 | 16.7% | 3,613 | 30.8% | N |
| tool descriptions | 6,189 | 21.9% | 4,942 | 42.2% | C |
| tool responses | 13,333 | 47.1% | 0 | 0% | P |
| assistant output | 428 | 1.5% | 0 | 0% | N |
| total | 28,293 | 100% | 11,712 | 100% | |

The fixed first-call tax is the system plus the tool descriptions: 2,959 + 4,942 = 7,901 tokens, or 67.5% of the first call.
The fed human context is 3,613 tokens, or 30.8%.
The first call is 11,712 tokens.

The session mean is 28,293 tokens.
The first call is 41.4% of the session mean, so the first-call context is not the whole story.
The session growth is the 2-6 calls plus the tool responses.
The tool responses are 13,333 tokens, 47.1% of the session.
The largest single response is the 89,087-char KB answer in one session.
The tool descriptions are 6,189 tokens per session, 21.9%.

The 20 symptom-confirmed sessions account for about 1.42M total triager tokens and about 1.04M capped.
The average is about 71k total and about 52k capped per confirmed pod.
The calls range from 2 to 6 per confirmed session.
The confirmed pods do not reach a one-call 10k path today.

## What the claim confirms

The aggregate tax is real.

- The first call is 11.7k.
- The fixed context is 67.5% of it.
- The fed data is 30.8% of it.
- The 20 confirmations run 2-6 calls and cost about 52k capped each.
- The 10k target is about 15% below the current first call, so it is reachable with a trimmed fixed context.
- The tool descriptions are the largest fixed component and the clearest compression target.

The design implication is also confirmed.
The triager does not need the full variant-mining context to confirm a symptom.
The confirmed path can be a small one-call assessment.
The first call can carry the spec's verification symptoms, the latest observation, and the Runner's note.
The skill, the KB, the graph view, and the variants are not needed for that check.

## What the claim falsifies

The system prompt is not the main culprit.

- The system prompt is 2,959 tokens, 25.3% of the first call and 12.8% of the session.
- The tool descriptions are 4,942 tokens, 42.2% of the first call and 21.9% of the session.
- The human feed is 3,613 tokens, 30.8% of the first call.
- The tool responses are 13,333 tokens, 47.1% of the session.

The 10k figure is the whole first call, not the system prompt.
The system prompt alone is about 3k.
The main lifecycle tax is the 2-6 calls and the tool responses, plus the fixed tool-description block.
The system prompt trim is secondary.
The tool-description trim is the largest fixed lever.
The stage split is the largest call-count lever.

The 20 first-shot count is also slightly overstated.
Nineteen symptom confirmations are v0 first-shot.
The twentieth, `forwarded-address-counter_per-address-throttle`, is the off-spec v2 confirmation after the per-address v0 and the path-override v1 were falsified.
The measured 20 includes that off-spec success.
The first-shot count is 19.

## Staged decision tree

The triager should walk the tree in this order.

1. **Failure assessment.**
   If `runner_failed`, keep the current runner-failure behavior.
   The pod records the failure evidence and terminates honestly.

2. **Symptom confirmation.**
   If the run completed successfully, check the spec's verification symptoms against the observation.
   If the symptom is confirmed, write the verdict `successful`, `terminal_reason=symptom-confirmed`, `clean` as appropriate, and the deterministic `PodExport`.
   This is the 19 first-shot path.
   The target is about 10k tokens.

3. **Divergence assessment.**
   If the symptom is not confirmed, compare the executed procedure with the spec's procedure.
   The procedure is the same skill that was fed to the Runner, in the same concrete prompt rendering as the spec.
   If `runner_diverged`, go down the divergence restart path.
   The pod records the divergence evidence and terminates or restarts as the current design prescribes.

4. **Bounded variant mining.**
   If the run is inconclusive, not failed, and not diverged, and a populated procedure gap exists, load the skill and mint at most one variant.
   The skill is the same skill that was fed to the Runner, in the same concrete prompt rendering as the spec.
   The typed `SkillProcedure` is the procedure-diff material.
   The KB is loaded on demand, not as a fixed block.
   The variant must cover one populated procedure gap.
   The variant must not change the symptom identity unless it records the new symptom as a derived spec.
   The off-spec guard applies.

5. **Verdict and terminal.**
   If no procedure attribute can be bent, terminate with the appropriate verdict and terminal reason.
   The deterministic `PodExport` is written.

The first stage has no KB, no full skill, no graph view, no variants, and no procedure-gap mining context.
The later stages have the skill and the procedure.
The 19 first-shot pods never reach the later stages.
The ambiguous pods do.

## Token effect

The current measured cost is 2,530,000 input tokens and 1,040,187 capped tokens across 24 sessions and 79 calls.
The 20 symptom-confirmed sessions are about 1.42M total and 1.04M capped.
The 4 variant pods are about 1.04M total.
The 3 no-symptom pods are about 0.79M total.
The 1 in-flight pod is about 0.18M total.

The staged estimate is:

| Path | Pods | Per pod | Subtotal |
|---|---:|---:|---:|
| First-shot confirmed | 19 | 10k | 190k |
| Off-spec confirmed via variant | 1 | 20k | 20k |
| No-symptom with variant | 2 | 20k | 40k |
| No-symptom v0 | 1 | 10k | 10k |
| In-flight variant | 1 | 20k | 20k |
| Total | 24 | | 280k |

The staged total is about 280k tokens, all treated as capped for the estimate.
That is a saving of about 2.25M input and about 760k capped.
The capped reduction is about 73%.
The total reduction is about 89.7%.
The per-export capped cost falls from 45.2k to about 12.2k.
The product/tokens ratio rises from 22 exports per 1M capped to about 82, a 3.7x improvement.
The 20 symptom-confirmed pods are retained.
The 4 variants are retained.
The 2 deeper negatives are retained.
The 1 in-flight variant is retained.
The off-spec guard is added.

The pure-removal floor is about 192k, with 19 confirmations and no variants.
The staged design costs about 88k more than that floor and keeps the four variants, the two negatives, and the in-flight test.
That is the quality premium of the bounded variant path.

## Technical feasibility

The staged design is feasible.

- The first stage is a small structured call with the spec symptoms, the observation, and the Runner's note.
- The schema is a compact `ConfirmedSymptomAssessment` with `runner_failed`, `confirmed`, `clean`, `terminal_reason`, and `note`.
- The graph routes the confirmed and failed cases to the existing terminal and `_export` nodes.
- The divergence stage reuses the typed `SkillProcedure` and the executed procedure.
- The bounded variant stage reuses the current `mint_variant` node, gated to one variant, with the skill and the KB on demand.
- The `variant_specs` list grows by at most one.
- The `PodExport` stays deterministic and keeps the IA-4 shape.
- The first stage's tool descriptions are small; the skill and KB descriptions are only in the later stages.
- The tests cover the first-shot confirm, the failed path, the divergence path, the one-variant cap, the off-spec guard, and the export.

The effort is about 1 to 2 engineering days plus the design amendment and one measurement trial.
The main risk is a first-stage false negative that sends a confirmed pod to the later stages.
The mitigation is the spec's verification symptoms plus the observation, with the later stages as the fallback.
The second risk is a false positive on a noisy observation.
The mitigation is the existing `clean` and evidence rules.

## Recommendation

Adopt the staged tree.

- First stage: failure and confirmed-symptom check, about 10k, 19 first-shot pods.
- Second stage: divergence check with the same skill and procedure, for the ambiguous pods.
- Third stage: bounded variant, at most one, with the skill, the KB on demand, and the off-spec guard.
- Fourth stage: verdict, terminal reason, and deterministic export.

This is not the pure-removal design.
It keeps the skill and the bounded variant path.
It keeps the 20 symptom-confirmed pods and the 4 variants.
It reduces the triager from about 1.04M capped to about 280k capped.
The 19 first-shot confirmations drop from about 52k capped each to about 10k each.

The earlier feasibility report's pure-removal numbers are the lower bound, not the recommended design.
The staged design is the recommended one because the measured variants include one real authority bug, two deeper negatives, and one in-flight test.

## Reproduction

The occupancy values are from `CONTEXT-OCCUPANCY-ANALYSIS.md` and its `audit_context_occupancy.py`.
The trial spend is `trial.yaml` under `spend_by_agent.pod_triager`: cached 1,674,880, uncached 850,278, reasoning 151,997, visible 37,912, generated 189,909, total 2,715,067, capped 1,040,187, calls 79.

The 24 triager sessions are the Langfuse `pod_triager` sessions under run `5c9590ff-9a83-4cea-9aff-be1bd51e2667`.
The 20 symptom-confirmed pods and the 4 variants are the pod exports under `hunting/test-executor-pod/`.
The 19 v0 first-shot confirmations are the exports whose `iterations` is 1 and whose `variant_specs` length is 1, excluding the v0-only no-symptom pod.
The off-spec confirmation is the `forwarded-address-counter_per-address-throttle` v2 authority-field variant.

## Limitations

The staged 280k is an estimate, not a measured run.
The 10k first-stage value is 15% below the measured first call of 11,712.
It assumes the first-stage tool descriptions and system are trimmed to about 5-6k combined, with the observation and note taking the rest.
The variant-stage 20k assumes the skill, the procedure, the KB on demand, and one minted variant.
The actual variant stage may be higher.
The 19 first-shot count treats the off-spec `forwarded-address-counter` as a variant-path confirmation.
The measured 20 is the trial's total, not the first-shot total.
The 4 variants and the 3 no-symptom pods are exact from the pod store.
The in-flight variant has no terminal product.
The staged design has not been implemented or measured.
