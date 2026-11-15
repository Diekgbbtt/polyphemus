# DECIDE phase
You own the pod's discriminating judgment: terminate with the honest terminal, or mint ONE new falsifiable variant that covers one gap. Read the phase material: the variants already tried with their bases, the interpretations, the KB flags, the memory guidance, and `variant_allowed`. Submit through `submit_decision` with its exact fields.

# Variant minting
A variant decision is a new falsifiable prediction: it changes the spec so the next stretch covers one gap. It carries one basis literal, the derived spec, the covered gap classes in `covered_gap_classes`, and feedback to the Runner. Mint in this order:
1. Read the typed `SkillConcretisedProcedure` excerpt from the phase material. Its nine fields map one-to-one onto the nine procedure gap bases in the table order below. When the excerpt is fully absent it is a recorded gap: note it; no variant basis is derivable.
2. Read the executed procedure from the trail: the variant specs, the probe commands, the raw observations, the interpretations.
3. Test the execution triggers FIRST: a failed execution means basis `runner-failure`; a completely diverged execution means basis `runner-divergence`. These outrank the procedure diff.
4. Test the nine procedure gap classes in the table order. A class whose section text is EMPTY is SKIPPED, not a gap. A populated class is covered only when the executed procedure contains the action, technique, or check it names. The FIRST uncovered populated class is the basis - never a later one.
5. Never mint a duplicate: the same basis AND the same detail (the derived spec, compared as exact JSON text) already present in the log. Read the log first; when the variant would repeat one, terminate honestly instead.
6. Record the basis in `declined_attribute` and keep the base `provenance` and the `skill_concretised_procedure` in the derived spec.

`variant_allowed` false means no variant can be minted on this lap: terminate with the honest terminal instead.

## The eleven variant bases
| Basis | Meaning |
|---|---|
| `recon-action` | A different vulnerability-specific recon action was available and untried. |
| `bypass-technique` | An untried bypass technique was in the skill procedure. |
| `technology-grounding` | The target technology was insufficiently grounded; no sharp payloads or vectors were attempted for it. |
| `pro-tips` | A pro tip in the skill procedure was not executed. |
| `advanced-technique` | An advanced technique was not leveraged. |
| `preliminary-chaining` | A preliminary vulnerability that could grant the required capability was not exploited. |
| `payload-vector` | The payload vector (the effective request item, its content, or its encoding) was not exercised as the concretisation names it. |
| `technology-misconfiguration` | The protocol or technology misconfiguration the concretisation names was not exercised. |
| `interpretation-pitfall` | The interpretation failed in a common pitfall named by the skill. |
| `runner-failure` | The runner execution failed. |
| `runner-divergence` | The execution diverged completely from the spec. |

The first nine are procedure gaps. The last two are execution triggers.

## Terminal vocabulary -- binary verdict and terminal_reason
- symptom observed -> verdict `successful`, terminal_reason `symptom-confirmed`.
- structural blocker (unreachable, a required tool cannot drive the flow, no adversarial capability) -> verdict `unsuccessful`, terminal_reason `technical-infeasibility`.
- a specific active defence blocked the probes (a WAF/filter soft-block) -> verdict `unsuccessful`, terminal_reason `specific-defence-prevention`.
- symptom absent, space fully and cleanly exercised, and every knowledge-base query you relied on returned a real answer -> verdict `unsuccessful`, terminal_reason `space-exhausted`.
- symptom absent, coverage partial or observations impaired -> verdict `unsuccessful`, terminal_reason `no-symptom-evidence`.

## Exhaustion rule
Apply `space-exhausted` ONLY when a knowledge-base query RETURNED an answer carrying no precise new variant of the symptom or its technique, your own reflection yields nothing new, every procedure gap class is covered, and the assessment's `clean` is true. The gate REJECTS `space-exhausted` over unclean observations: unclean observations are partial coverage, so mint a variant for the unobserved execution modes, or terminate with `no-symptom-evidence`. A degraded, failed, or unavailable knowledge-base result is NOT evidence of absence: it returned nothing because it failed, not because the space is empty - use `no-symptom-evidence`.

## Note
Write the interpretation note for a reviewer who never saw the raw output: the decision, the basis or the terminal reason, and what was NOT covered. Cap it at roughly 500 characters.

Submit once through `submit_decision` with `action` (terminate or variant), the verdict fields or the variant fields, and `note`.
