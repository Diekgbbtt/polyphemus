# Experiment Results: boundary-abduction reasoning for the unit threat modeller (`t1-tbsg`)

*Report filed 2026-10-18, following the `measure-experiment-results` template (`/Users/diekgbbtt/.config/opencode/skills/measure-experiment-results/references/TEMPLATE.md`), adapted honestly for a single-unit retrospective-control comparison: no p-values, no confidence intervals, n=1 per arm. Every result below is descriptive. The assessment was pre-registered in `unit-threat-model-abduction-trial/assessment-plan.md` BEFORE the treatment run existed; the critical-thinking discipline was applied throughout (pre-listed falsifiers, blind assessment, counter-arguments on every comparative claim).*

## Summary

| Attribute | Value |
|-----------|-------|
| **Experiment ID** | `t1-tbsg-service-model-download` |
| **Status** | Completed (both arms; treatment 2026-10-18) |
| **Duration** | Control 2026-10-15; treatment 2026-10-18 |
| **Traffic allocation** | 1 unit per arm; no randomisation |
| **Total sample size** | n=1 per arm (single unit, single run each) |
| **Owner** | design session, operator-ordered (workbench R8-4) |
| **Design doc** | `unit-threat-model-abduction-trial/assessment-plan.md` (pre-registered) |
| **Arms** | Control: the 2026-10-15 T1 model (inductive method, session `ses_ebe86bcf1ffe...`). Treatment: the boundary-abduction model (run book `unit-threat-model-abduction-trial/input.md`, session `ses_eb0dce368ffe...`) |

## Hypothesis recap

- **H1**: the boundary-abduction discipline improves the quality of the trust boundaries and the trust assumptions (exhaustiveness, sophistication, well-formedness, depth precision) at an acceptable token cost, against the inductive baseline, on this unit.
- **H0**: no material quality difference; any cost increase is unjustified.
- **Pre-registered falsifiers**: (1) loss of a GT anchor; (2) baseline-region retention < 90%; (3) lower sophisticated-assumption share or depth scores; (4) more duplicates/overlaps/orphans; (5) generated-token inflation > 2x with no quality gain.
- **Pre-registered decision rules**: ADOPT if all anchors covered, retention >= 90%, quality equal-or-better, token ratio <= 2.0x. REJECT if any anchor lost, or retention < 80%, or well-formedness roughly doubles, or token ratio > 3.0x without gain. ITERATE in between. INCONCLUSIVE only on mechanical run failure.

## Results

### Primary: exhaustiveness

**GT anchors** (definitions in the pre-registration; both verified live on the redeployed target 2026-10-18):

| Anchor | Control | Treatment | Verification evidence |
|---|---|---|---|
| **GT-A** (`.safetensors` + arbitrary URL install; `queue/start` fetches: SSRF comfyui-006) | **Covered** - loop-1 `high`, oracle-proven (P09/P13/P28/P57-P58) | **Not covered** - V-D1/FM-D1 dropped as `feasible: false` | Live re-verification 2026-10-18: `POST install_model` with `filename: review-check.safetensors`, `url: http://ssrf-listener:8000/review-verify-1` returned **200**; `GET queue/start` returned 200; the listener recorded the fetch (`GET /review-verify-1`, remote 172.18.0.3). The treatment's drop evidence ("url must equal a catalog value (403), no listener hits") rests on probes that never combined a `.safetensors` filename with an arbitrary URL (their P17/P18/P21 forced shapes returned 400 on other fields). **The drop is factually invalid.** |
| **GT-B** (arbitrary channel URL persisted via `?value=`: comfyui-005 carrier) | **Not covered** - FM16 dropped (invalid; trial report section 2.3) | **Not covered** - V-D4/FM-D4 dropped as `feasible: false` | Live re-verification 2026-10-18: `?value=http://127.0.0.1:9/review-verify` returned 200 and read-back showed `selected: custom` (restored). The treatment probed only the malformed `name::url` form (`tmprobe::http://...`), never a raw `http(s)` value. **The drop is factually invalid.** |

**Baseline-region retention** (session-side mapping, generous region reading; the blind assessor's independent mapping is reconciled below):

| # | Baseline region | Treatment coverage | Treatment record | Note |
|---|---|---|---|---|
| A1 | `.safetensors` extension shortcut decides scrutiny | **Lost** | - | GT-A-critical; no assumption or record; the shortcut branch was never discovered |
| A2 | No destination filtering on the outbound fetch | **Lost** | dropped V-D1/FM-D1 | GT-A-critical; invalid drop (verified) |
| A3 | Scheme-filter narrowness (`file://` variants) | **Lost** | - | no scheme-level reasoning |
| A4 | URL set membership vs record binding | Full | A-1 | treatment found the same region sharply (loop-1) |
| A5 | `save_path` trusted from the dropdown | Full | A-8 | |
| A6 | JSON well-formedness assumed | Full | A-9 | |
| A7 | `ui_id` type/identity trusted | Full (reframed) | A-2 | control: type/worker halt; treatment: unbound correlation key/spoofing - same object, different emphasis |
| A8 | Counters as execution truth | **Lost** | - | reset/counter retention was probed but not recorded as a region |
| A9 | GET semantics on state changes | Full | A-3 | merged with the missing-privilege region |
| A10 | Channel content trusted as authentic | Partial | A-6 + A-7 | mechanism covered as DOM injection; channel-source integrity itself absent |
| A11 | Path building by concatenation | Full | A-8 | merged with A5 |
| A12 | Check-to-use gap gate-to-queue | Partial | A-1 mechanism; T-7/T-8 blocked | the temporal/mutation framing is absent |
| A13 | Duplicate `ui_id` bookkeeping | Partial | A-2 | identifier non-binding covered; reconciliation not explicit |
| A14 | Concurrency guards on queue mutation | Partial | A-4, A-5 | control semantics covered; explicit concurrent-write claim absent |
| A15 | No authentication anywhere | Full | A-3 | |

- Full retention: 7/15 = **46.7%**. Including partials: 11/15 = **73.3%**. Both readings are below the pre-registered 80% reject threshold.
- The assessor's independent blind mapping is stricter: 5 exact / 5 partial / 5 none (33.3% exact; 66.7% including partials). The differences concentrate on A7 (`ui_id` type/worker-halt vs identifier spoofing, judged distinct) and A6 (exception handling vs validation oracle). Under either mapping the retention thresholds are missed; the decision is unaffected.
- Treatment-only regions (no ground truth; plausibility noted, not scored as gains): DOM-injection assumption made explicit (A-7), install-integrity assumption (A-6), queue-ownership assumption (A-4), reset/pending-state discrimination (A-5). The control carried the DOM-XSS direction only as a dropped failure mode (FM16), not as an assumption.

**Exhaustiveness verdict**: GT-A lost, GT-B lost (control also lost GT-B), retention below thresholds. Per the pre-registered rules this alone triggers **REJECT**.

### Sophistication and depth precision (blind assessment)

Judge: cross-family assessor (`opencode-go/gpt-6-luna#max`), blinded corpora (`model-a.md` = control, `model-b.md` = treatment; the assignment was never disclosed), session `ses_eb0c8b270ffe...`.

| Measure | Control (Model A) | Treatment (Model B) | Direction |
|---|---|---|---|
| Sophistication tiers | T2 7 / T1 6 / T0 2 (of 15) | T2 5 / T1 3 / T0 1 (of 9) | Mixed: treatment has the higher T2 share (55.6% vs 46.7%), the control the larger absolute T2 count. Tier judgement is subjective; confidence medium. |
| Mean depth (0-3) | 3.0 (all 15) | 3.0 (all 9) | Tie. The metric saturated: both models attach a mechanism, an attribute, and a failure to every assumption, so the criterion did not discriminate at this granularity. Recorded as a measurement limitation, not a win or a loss. |
| Assumption-to-loop closure | 2 fully orphaned (A4/F4, A13/F13); 2 more reach a vulnerability without a loop (A10/F10, A11/F11); 4 of 16 vulnerabilities unlooped (VUL13-VUL16) | Complete: every surviving assumption reaches a vulnerability and a loop (verified session-side via the fault ids embedded in the prose) | **Treatment better** (assessor confidence high). Counter-argument: part of the control's gap is an attribution defect (VUL6 cross-entry substitution exists but is linked to F12, leaving F4 orphaned) rather than a missing finding. |

The assessor's incidental notes about undefined state names and undefined probe ids are corpus-rendering artifacts (the renderer omits the states section and the probe logs; both models define their states - control 7, treatment 6 - and the probe ids resolve in the trial artifacts). They are excluded from scoring.

### Well-formedness

| Check | Control | Treatment |
|---|---|---|
| Machine-parseable YAML | yes | yes |
| Near-duplicate assumption pairs (Jaccard >= 0.55 on normalised tokens) | 0 | 0 |
| Overlapping assumption pairs (blind assessor) | 1 substantive (A4/A12: record binding vs check-use gap, not distinguished by any shown post-gate mutation) | 0 substantive (A-3/A-4, A-2/A-7, A-1/A-8 judged distinct mechanisms) |
| Structural fault references | 0 broken (all `F#` resolve) | **9 of 9 structural breaks**: `induced_fault` holds a prose sentence, not a fault id; the association is recoverable only from the id embedded in the prose (verified session-side) |
| Assumption-to-loop closure | 2 orphans (A4/F4, A13/F13); 2 vulnerabilities without loops (VUL13-VUL16 region) | complete (all 9 assumptions -> vulnerability -> loop) |
| Factually false boundary statements | none found beyond the invalid drop | IA-5 states channel mutation "accepts only predefined channel names" - contradicted by the verified raw-URL persistence |
| Weak fault attributions | VUL6 attributed to F12 although A4/F4 describes the failure | V-D4 attributed to F-3 (privilege layer) although the channel-value write is the object |

Assessor observations discounted as corpus artifacts: undefined state names (the renderer omits the states section; both models define them) and undefined probe ids (the probe logs exist in the trial artifacts).

### Token tax and cost

| Metric | Control | Treatment | Delta |
|---|---|---|---|
| Input tokens (non-cached) | 264,654 | 124,860 | -52.8% |
| Output tokens | 39,268 | 42,671 | +8.7% |
| Reasoning tokens | 118,440 | 49,257 | -58.4% |
| **Generated tokens (output + reasoning)** | **157,708** | **91,928** | **-41.7%** |
| Cache-read tokens | 8,535,296 | 5,663,232 | -33.7% |
| Cost | 0 (free tier) | $0.091 (paid tier) | provider-tier difference |
| Model document size | 47,343 B | 61,847 B | +30.6% |
| Trace / notes | 11,179 B / 4,473 B | 11,148 B / 5,840 B | notes +30% |
| Wallclock | 1,228 s | 914 s | -25.6% |
| Probes (limit 60) | 58 | 59 | equal |

- Token tax is favourable on generated tokens (-41.7%), mostly from reduced reasoning.
- Caveat: the arms ran on different provider tiers of the same model family (free vs paid); part of the reasoning-token gap may be provider-side behaviour, not the method. Flagged, not resolved.

### Process and guardrails

| Guardrail | Control | Treatment | Status |
|---|---|---|---|
| Probe budget respected | 58/60 | 59/60 | pass both |
| Gate cadence (write per state during the run) | failed (all probes batched before gate 1; R2-17) | failed (all 59 probes in state 1) | the recurring cadence defect repeated |
| Drops recorded in place with reasons | yes | yes | pass both |
| Invalid drops (probe-based "infeasibility" that the live target contradicts) | 1 (FM16, channel) | 2 (V-D1 GT-A; V-D4 GT-B) | **degraded** |
| Evidence discipline (rungs + evidences per record) | consistent | consistent | pass both |
| Blocked probes recorded with reasons | yes | yes (9 evidence gaps) | pass both |
| Suite mapping | all kept classes mapped | all kept classes mapped | pass both |

## Segment analysis (adapted)

- **By trust branch**: the treatment's transition-side records are the richest part of its model (all 8 transitions carry `establishes`/`requires`; the guard-versus-invariant split produced real state insights such as the global unowned queue). Both GT failures sit on the **interface-side source/destination** branches (the fetch url; the channel selection), where the treatment's hypothesis set closed early and its falsification probes covered neighbouring shapes only.
- **By criterion direction** (control vs treatment): exhaustiveness = control better (GT-A outright; retention under both mappings); sophistication = mixed (treatment higher T2 share, control more absolute T2 count); depth = tie (metric saturated); well-formedness = mixed (treatment better assumption-to-loop closure; control fewer structural defects and one substantive overlap); token tax = treatment better. On the pre-registered primary (exhaustiveness anchors) the control wins outright.
- **By run**: the two arms share the same defect class (invalid drops of unprobed carrier shapes); the control's defect was the cross-unit channel direction, the treatment repeated it and added the same class on its own GT direction.

## Learnings

1. **The boundary-abduction discipline did not prevent, and here worsened, the recurring drop-error class.** Across all runs to date (prototype x2, T1, T2, T1-TBSG), the most repeated defect is a carrier direction dropped as "infeasible" on the strength of probes that never exercised the actual discriminating shape. The treatment dropped its own ground-truth carrier (GT-A), which no run had done before.
2. **A plausible mechanism (hypothesis, not proven): closure pressure.** The abduction produced a closed, tidy record set - 9 assumptions, every boundary answered, closure check green - while the branch that mattered (extension-decides-scrutiny; raw-URL channel value) was never generated. Structured record-completeness may substitute for adversarial branch generation unless a discipline forces hypothesis-space extension beyond the records.
3. **Structured records do not fix fact quality.** The treatment's boundary statements include a verified falsehood (IA-5), and its drop rationales assert "url must equal a catalog value", contradicted by the live target. The added structure made the reasoning traceable but did not make it true.
4. **Referential integrity regressed.** All 9 treatment assumptions leave `induced_fault` as prose; the specified fault-id link is absent. The extra structure added a new failure surface.
5. **Token economics moved favourably** (-41.7% generated tokens), so cost is not the blocker; the quality anchors are.
6. **What went right in the treatment**: the recombination finding (loop-1) is sharp and matches the control's equivalent region; the DOM-injection and install-integrity assumptions promote regions the control only carried implicitly; the transition records are dense and traceable; evidence, rungs, drops-in-place and blocked-probe records hold.
7. **The treatment's one clean structural win: assumption-to-loop closure.** Every treatment assumption resolves to a vulnerability and a loop; the control left two assumptions fully orphaned and four of its sixteen vulnerabilities unlooped. This discipline is cheap to adopt independently of the abduction model.

## Recommendation

### Decision: **KILL** (do not adopt the boundary-abduction variant as the working reasoning model)

**Rationale, per the pre-registered rules:** GT-A was lost outright on a live-verified reachable vulnerability (the unit's own ground-truth carrier); retention is 46.7-73.3%, below both thresholds; well-formedness regressed (broken references, a false statement). The favourable token tax does not compensate.

**Honest limits of this decision:**

- n=1 per arm, single unit, one run each; run stochasticity and probe-design luck are real confounds. This experiment does not prove the method is universally worse; it proves that *this implementation of it, on this unit, failed its primary anchors while the control passed*.
- The treatment prompt was authored by the same session that advocated the model; mitigations (pre-registration, blind assessor, live verification) reduce but do not remove this bias.

**What to preserve regardless:**

- The **assumption-to-loop closure check**: every kept assumption must reach at least one vulnerability and one loop before the completion gate; orphans are resolved or explicitly waived with a reason. Independently evidenced by the control's A4/A13 orphans.
- The **drop-decision discipline**: promote the retention-first semantics (R3-9) into every prompt, and require a drop to name the infeasibility proof and the exact discriminating probe shape that would have falsified it. This is the single highest-value fix indicated by four runs, independent of the abduction question.
- The stale trial run books' drop rule (which both arms carried) should be updated before any future comparative run.
- The `establishes` versus `requires` vocabulary and the boundary-record shape as an **optional annotation** to the existing notes material - informative for traceability, but only if a future run shows it does not dilute adversarial probing.

**Operator decision (2026-10-18):** the KILL is accepted. The exploration of the abduction improvement stays open as ticket `#371`, because this experiment evaluated a low-quality prototype (single unit, single run, subagent-mocked); the verdict bounds this implementation, not the approach. The two orthogonal disciplines (drop-decision, assumption-to-loop closure) are adopted (Q43(a)).

## Next steps

| Action | Owner | Status |
|---|---|---|
| Record the verdict, per pre-registered rules | session | this report |
| Decide: accept the KILL, or run one amended second run | operator | **decided 2026-10-18: KILL accepted; TBSG exploration continues as ticket `#371`** |
| Adopt the drop-decision discipline and the assumption-to-loop closure check | change spec (modeller prompt material) | **decided 2026-10-18 (Q43(a))** |
| Update the trial run-book drop rule to R3-9 semantics before any future run | design workstream | pending (rides the change spec) |
| Keep the study artifacts frozen for re-analysis | session | done (`unit-threat-model-abduction-trial/`) |

## Appendix

### Raw data

- Control model: `unit-threat-model-prototype/trials/t1-service-model-download/output/` (model, trace, notes, metrics, probes, gates).
- Treatment model: `unit-threat-model-abduction-trial/output/` (same set).
- Pre-registration: `unit-threat-model-abduction-trial/assessment-plan.md`.
- Blind corpora: `unit-threat-model-abduction-trial/comparison/blind/` (model-a = control, model-b = treatment; assignment was not disclosed to the assessor).
- Inventories and tooling: `unit-threat-model-abduction-trial/comparison/` (`analyse.py`, `baseline-inventory.json`, `treatment-inventory.json`).
- Session token data: opencode session store, sessions `ses_ebe86bcf1ffe...` (control) and `ses_eb0dce368ffe...` (treatment).

### Statistical methodology

None applicable: single unit, single run per arm, no randomisation, no repetition; the design is a retrospective-control case comparison. All comparative statements are descriptive counts and rubric scores. The sophistication/depth scores come from one blinded cross-family assessor; reconciliation with the session-side reading is stated where they diverge.

### Known issues and deviations

- Target parity: the treatment ran on a redeployed instance of the same image (`pentestbench-comfyui:v0.3.76-isolated`, build 2026-10-02), fresh seed, at a new port; same behaviour verified.
- Model parity: same model family, different provider tiers (free vs paid).
- Deviations from pre-registration: none in the protocol; the assessor model was chosen cross-family (not pre-specified) to reduce same-family bias - an implementation choice, recorded here.
- The assessor corpus strips treatment-only fields (`boundary_ref`, `dimension`, `propagation`) by design; their quality is covered in the supplementary non-blind review in this report (structure traceable, but the referential defect above).
- Blind-corpus scope: the renderer omits the dynamic-state definitions and the probe logs; two incidental assessor observations (undefined state names, undefined probe ids) are artifacts of that scope and were excluded from scoring; both models define their states and the probe ids resolve in the trial artifacts.
