# 406 - Carry the impact in the hunter payload

**What to build:** Carry the impact and the end-impact statement in the hunter payload. Do not carry the computed risk or the dispatch priority: the hunter does not reason over the priority, and the impact is context, not a primary reasoning citizen.

**Blocked by:** 405

**Status:** ready-for-agent

**Seams:** attack/hunting/hunter_payload.py, attack/hunting/hunting_agent.py

## Context

The hunter's symptoms are more technical and scoped to a narrow part of the surface. The impact tells the hunter the intended end effect, but the hunter remains free to find a sharper path. The payload already carries the loop record, the classes, the likelihood, and the vulnerability rationale; the impact joins that context.

## Acceptance criteria

- [ ] The payload carries the impact metrics and the end-impact statement.
- [ ] The payload does not carry the computed risk or a priority field.
- [ ] The first human message can render the impact without narrowing the vector.
- [ ] A payload for a model without impact renders an explicit absence, never a fabricated value.
- [ ] The payload tests cover the present, absent, and degraded cases.

## Verification

- Run the hunter payload tests.
- Run the hunter first-human tests.
