# Threat-model impact elicitation and failure-mode removal - ADR

*Status: decided 2026-10-25, built 2026-10-25. Impact map: `docs/design/threat-model-impact-elicitation-impact-map.md`. Plan: `docs/experiments/modeller-impact-quality/PLAN.md`. Baseline: `docs/experiments/modeller-impact-quality/BASELINE.md`.*
*Supersedes: the likelihood-only risk scoring in `unit-threat-model-workbench.md` Q33 and R3-1, and the failure-mode artifact in `hunting-67-threat-model-artifact-spec.md`.*
*Decision owner: operator. Grilled and settled 2026-10-25.*
**Vocabulary note (2026-10-25).** The ranked artifact was called a **loop** in the earlier baseline and design text. The module, the store, and the current documentation now call it a **threat**. A historical "loop" in the baseline means the same artifact.

## Problem

The eval-server-1 baseline measured 113 threats over 17 unit models.
70 threats (61.9%) were low-yield: contract integrity, information disclosure, enumeration, or rate limiting.
Only 25 (22.1%) carried a severe end impact.
Only 32 (28.3%) had an attacker-artifact-to-security-decision boundary.
The green-threat share was 45 of 113 (39.8%).
The likelihood-only ranking put 18 of the 25 severe threats below `high`.
The failure-mode check never discriminated: 113 failure modes, 78 feasible, 33 conditionally feasible, 2 infeasible, 0 vulnerabilities dropped.
The modeller consumed 31.1% of the 7M capped budget, and 10 of 113 threats reached the hunter.

The defect is not the interface agreements, the control flows, or the data flows.
Those are strong.
The defect starts at the trust assumptions and the faults, and it propagates downstream.
The trust model describes what each component promises, but it does not consistently name the attacker-controlled field, the security-sensitive variable it reaches, the adversarial capability gained, and the literal end damage.
The failure-mode check then spends context on a feasibility judgement that never changed a decision, and the likelihood-only score lets an observable contract divergence outrank a severe but conditional exploit.

## Decision

### 1. Impact is first-class and scored with VC, VI, VA

Every threat carries an impact record with `VC`, `VI`, and `VA`, each `none`, `low`, `medium`, or `high`, plus a literal end-impact statement.
The impact is on the application and its users.
There is no separate subsequent-system metric.
The operator wants the modeller to reason in adversarial capabilities and vulnerability chains, not in single-system failure.

The metric weights are `none = 0.00`, `low = 0.22`, `medium = 0.35`, `high = 0.56`.
The impact sub-score is `1 - (1 - VC)(1 - VI)(1 - VA)`.
The ordinal impact weight is `0` at zero, `1` at `(0, 0.25]`, `2` at `(0.25, 0.50]`, `3` at `(0.50, 0.75]`, `4` above `0.75`.
The threat risk is `likelihood_weight * impact_weight`.
The store computes the sub-score, the weight, the threat risk, the unit profile, and the run total.
The modeller never authors a score.

The ranking is risk descending, then impact descending, then likelihood descending, then the modeller's write order.
The dispatch buckets are critical `>= 12`, high `8..11`, medium `4..7`, low `1..3`, none `0`.
The provisional default threshold is `360`.
The A/B sets the threshold per arm, and both arms use the same value.

### 2. Failure modes are removed from the hunting module

The `failure_modes` artifact, the `Threat.failure_mode_refs` link, the prompt phase, the pod `failure-mode` variant basis, and every reader and writer of the artifact are removed.
The hunter loses every failure-mode reference; it keeps its existing reasoning axes: vulnerability variants, manifestation, testing technique, framework or protocol misconfiguration, and payload vector class.

The rationale is measured, not theoretical.
The check produced 113 failure modes and 0 drops.
It consumed modeller context and produced no discriminating decision.
The technical feasibility and the effective attempt belong to the hunter and the test-executor pod, which hold the live target, the procedure, and the observation.

The modeller still judges exploitability through the likelihood score, because the likelihood names the adversarial capabilities the attack needs.
It does not judge whether the mechanics are present, does not drop for a missing observation, and does not drop for a failed probe.
Unobserved assumptions survive.
A drop requires one of two findings: the data is not attacker-influenced, or the trust agreement is misspecified.
The encoding-floor instruction is removed.

### 3. The trust procedure uses four axes

Branch A of the modeller prompt uses four characterization axes, each with equal structural weight:

- `identity`: privilege context, provenance, authority, delegation, and the binding of the claimed principal to the caller, session, resource, and function.
- `spatial`: every attribute that extends the artifact in breadth or depth, its origin and lifecycle, the objects and resource domains it selects or reaches, and its representation changes through decoding, normalization, canonicalization, concatenation, and propagation.
- `temporal`: state and time over application-state transitions, concurrency assumptions, replay, freshness, partial states, stale caches, fail-open fallbacks, and silent activation such as TOCTOU and DNS rebinding.
- `controls_semantics`: the precise invariant checks on untrusted attributes and impacted state, their placement across stages, their effective representation downstream, and the gap between syntactic validity and semantic safety.

`temporal` may be shorter when the unit has few state transitions.
It is not padded.
The framework lives only in the prompt.
The chain of thought compiles into the trust agreement and the assumption, as it does today.

### 4. The trust stretch is a well-formedness phase

The linear `trust_model -> assumptions -> vulnerabilities` stretch becomes a phase.
After the vulnerabilities write, the modeller runs a well-formedness check:

- For every vulnerability whose class will bound a threat, load the class skill.
- Read the title and overview, the Trust Assumptions section, and the closing summary.
- Name the assumptions the skill implies but the model lacks.
- Compile the missed assumptions into a local patch or a structural lack.
- A structural gap returns to the undermodelled part.

A structural gap is a trust boundary absent from the model, or the same axis missing across two or more vulnerabilities.
A local gap patches the affected assumption or vulnerability and re-checks.
The phase has no iteration bound; the run cap is the bound.

The phase is not a new `ModelState`.
The passive tracker observes `hunts_store` gate writes.
A lower-gate write after vulnerabilities is recorded as `lower_gate` and is the re-entry signal.
The exit is one `wellformedness` note followed by the `COMPLETED` write.
The note is the exit memory, never a per-iteration note.
It records the vulnerabilities checked, the skills loaded, the assumptions added, the absent Trust Assumptions sections, the structural finding, and the final action.

### 5. The class binding is strict, the enforcement is not

Every threat binds a suite class parent or leaf.
`suite_gap` is removed.
A novel class binds its nearest parent and keeps its novel name in `canonical_class`.
Technique families such as `defence-bypass`, `proxy-techniques`, and `two-principal-authz` are never the class.
They stay in the characterisation prose.

The completion checker records a non-blocking finding for an empty class, a technique family, and a name outside the suite.
It never rejects the write.
The finding is a signal that the modelling procedure went wrong, not a gate.

### 6. The success gate is the green-threat share

The gate is more than 90% green threats over all stored threats.
A green threat is a threat whose `web_vulnerability_class` is in the ratified high-yield set plus CSRF and clickjacking, rolled up to its class parent.
Low-yield threats stay stored.
Their risk is low or zero, so they do not enter the priority dispatch.

### 7. The next trial measures narrowing

A more specified trust boundary produces a sharper threat, but it can also narrow the threat to one variant before the hunter starts.
The depth exploration then has no meaningful set of distinct testing techniques left to discriminate.
The next trial measures this risk directly, without changing the pipeline behaviour yet.

Every threat carries two measurement attributes:

- **Breadth.** The bound `web_vulnerability_class` is a suite parent with at least one variant leaf (`broad`), a leaf (`narrow`), or absent from the suite index (`unknown`).
  The parent test is the strongest deterministic signal that the class can have multiple variants.
- **Downstream discrimination.** The spec set linked to the threat by `provenance.threat_id` is substantial when it has at least three specs, and well-formed when every spec carries a discriminator and the primary discrimination axes do not overlap.
  Two specs separated on the same primary axis are one dimension, not two.

The deterministic substrate is `eval/measure_utm.py` (`bound_class_is_parent`, `downstream.spec_count`, `primary_axes`, `axes_overlap`, `well_formed`, and the `narrowing` aggregate).
The measurement subagent judges the semantics and records `breadth`, `discrimination`, and the evidence.
A narrow threat with fewer than three specs or overlapping axes is the bias signal the trial must report, never smooth.

## Consequences

- The impact axis makes severe but conditional threats visible and prevents an observable contract divergence from outranking them.
- The failure-mode removal reduces the modeller's output and context, and it moves feasibility to the component that can test it.
- The four axes give the modeller a concrete, low-level elicitation procedure instead of an open-ended trust statement.
- The well-formedness phase adds class-skill loads and iteration turns. The cost is bounded by the run cap and measured in the A/B.
- The class guard removes the technique-as-class error and makes the hunter's skill binding honest.
- The green-threat gate is strict. A unit with no high-yield surface may produce few or no threats. That is the intended trade-off: the run cannot afford to hunt low-yield directions.
- Schema-1 documents are refused, not migrated: they carry the old `loops` key and ids. The A/B uses fresh schema-2 models.
- The threshold is provisional until the first re-model writes real metrics.
- The narrowing attributes are measurements, not gates: they tell the operator whether the sharper trust boundaries starve the hunter's discrimination space.

## Alternatives considered

- **Keep the likelihood-only score and add impact as a display field.** Rejected: the ranking would still demote severe conditional threats.
- **Keep failure modes and add impact beside them.** Rejected: the check produced zero drops, and the artifact duplicates the hunter's feasibility work.
- **Score subsequent-system confidentiality, integrity, and availability.** Rejected by the operator: it encourages single-system failure thinking instead of adversarial capability and chaining.
- **Add a new `ModelState` for well-formedness.** Rejected: the passive tracker already records the lower-gate re-entry, and a new state would add symbolic control that the operator does not want.
- **Enforce the class binding with a write rejection.** Rejected: the operator wants a signal, not a gate.
- **Drop low-yield threats.** Rejected: the operator wants the material retained and deprioritised by the score.

## Evidence

- Baseline report: `docs/experiments/modeller-impact-quality/BASELINE.md`.
- Baseline commit: `9eb66a0a`.
- Failure-mode census: 113 failure modes, 78 feasible, 33 conditionally feasible, 2 infeasible, 0 vulnerabilities dropped.
- Green-class baseline: 45 of 113 threats (39.8%).
- Low-yield baseline: 70 of 113 threats (61.9%).
- Severe baseline: 25 of 113 threats (22.1%).
- Severe below `high` likelihood: 18 of 25.
- Modeller spend: 2,179,055 capped tokens, 31.1% of the 7M cap.
- Dispatch coverage: 10 of 113 threats.
