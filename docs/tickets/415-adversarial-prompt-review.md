# 415 - Adversarial prompt review and fixes

**What to build:** Run an adversarial review of the modeller prompt for concision, presence of the specified content, and cohesion with the surrounding prompt. Fix every finding and record the report.

**Blocked by:** 414

**Status:** ready-for-agent

**Seams:** attack/hunting/prompts/threat-modeller.md, docs/experiments/modeller-impact-quality

## Context

The review checks that the prompt does not repeat the tool contracts, does not restate the state gates, keeps the four axes balanced, keeps temporal honest, integrates the example without duplicating the framework, and leaves no failure-mode or encoding-floor residue.

## Acceptance criteria

- [ ] A review report records the findings per axis.
- [ ] Every finding is fixed or explicitly rejected with a reason.
- [ ] The prompt stays within the line budget.
- [ ] The prompt tests pass.
- [ ] The report is committed under docs/experiments/modeller-impact-quality/.

## Verification

- Run the prompt tests.
- Re-read the prompt end to end.
