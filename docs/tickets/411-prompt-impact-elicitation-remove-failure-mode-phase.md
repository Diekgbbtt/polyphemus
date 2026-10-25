# 411 - Rewrite impact elicitation and remove the failure-mode phase

**What to build:** Rewrite the completion phase around the end impact: the three metrics, the attacker capabilities gained, the target application state, and the literal damage to the application or its users. Remove the failure-mode deduction and the encoding floor. Replace the drop rule with the two-clause loose drop.

**Blocked by:** 410

**Status:** done

**Seams:** attack/hunting/prompts/threat-modeller.md, attack/hunting/threat_modeller.py

## Context

The impact questions are: if exploited, could the issue enable privileged actions, cross-tenant compromise, sensitive-data exposure, persistent integrity loss, or major availability degradation? What capability does the attacker gain? What state does the application enter? What is the literal end damage? The drop rule: drop only when the data is not attacker-influenced or the trust agreement is misspecified. Unobserved assumptions survive. A missing observation or a failed probe is not a drop reason. The hunter and the pod own technical feasibility and effective attempt.

## Acceptance criteria

- [x] The prompt carries the three metric definitions and the ordinal impact weight.
- [x] The prompt requires the attacker-capability, target-state, and literal-damage reasoning.
- [x] The prompt carries the impact questions.
- [x] The prompt removes the failure-mode deduction.
- [x] The prompt removes the encoding floor.
- [x] The prompt carries the two-clause drop rule.
- [x] The prompt states that unobserved assumptions survive.
- [x] The prompt states that the hunter and the pod own feasibility and effective attempt.
- [x] The risk-scoring text matches the combined formula and the ranking.
- [x] The prompt tests assert the clauses and the removals.

## Verification

- Run the prompt tests.
- Adversarial review for concision and cohesion.
