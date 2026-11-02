# 430 - Ratify the green set, record the boundary shape, and enforce distinct discrimination axes

**What to build:** Close the three open questions the experiment exposed: what counts as green, what the sharp-boundary field is, and how the spec-set gate enforces distinct primary axes.

**Blocked by:** none

**Status:** open

**Seams:** `attack/hunting/threat_model.py`, `attack/hunting/threat_modeller.py`, `attack/hunting/prompts/threat-modeller.md`, `attack/hunting/hunter_tools.py`, `eval/measure_utm.py`, `eval/prompts/measure.md`, `docs/design/threat-model-impact-elicitation-adr.md`

## Context

Iteration B produced 10 green threats of 26 (38.5%).
The arm A green figure is not reproducible from its artifacts.
The sharp-boundary share is not measurable because the threat schema has no boundary-shape field.
The hunter produced 21 substantial spec sets and 1 well-formed set; 20 sets vary one primary axis.

## Acceptance criteria

- [ ] The ADR records the ratified high-yield class set, with the suite parent for every member.
- [ ] The threat schema records the trust-boundary shape and the measurement reads it.
- [ ] A substantial spec set with a repeated primary axis is refused at the spec-set gate, with a coded teaching rejection.
- [ ] The hunter prompt tells the hunter to choose distinct primary axes, not variants inside one axis.
- [ ] The measure script reports the green share and the well-formed share with the ratified set.
- [ ] A regression test builds a 3-spec set with one primary axis and asserts the refusal.
- [ ] The next white-jotter run reports the class-binding rate, the green share, the sharp-boundary share, and the well-formed share.

## Verification

- `tests/attack/test_threat_model.py`
- `tests/attack/test_hunter_tools.py`
- `tests/eval/test_measure_utm.py`
- A white-jotter run.
