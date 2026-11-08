# 421 - SkillEvolution experiment switch

**What to build:** One environment switch that disables the whole skill-evolution system for an experiment arm: the project evolver controller, the `meta/meta-write-skill` binding, the `record_skill_lesson` tool, and the lesson line in the pod prompts.

**Blocked by:** none

**Status:** done

**Seams:** `app/llm/skills.py`, `app/llm/evolver.py`, `attack/hunting/pod/prompts.py`, `project_management/api.py`

## Context

Iteration B needs the skill-evolution system fully off so the run spends no tokens on lesson writes, meta-skill reads, or evolver passes. The default must stay on, so production behavior is unchanged.

## Acceptance criteria

- [x] `SKILL_EVOLUTION_ENABLED=0` starts no project evolver controller.
- [x] The forced evolve endpoint refuses with 503 and leaves no running pass record.
- [x] The `meta/meta-write-skill` binding is empty when disabled.
- [x] `build_skill_tools` omits `record_skill_lesson` when disabled.
- [x] The pod runner and triager prompts do not name `record_skill_lesson` when disabled.
- [x] The default and every other value keep the current behavior.
- [x] Unit and API tests pin both the on and off states.

## Verification

- `tests/app/test_skill_evolution_toggle.py`
- `tests/project_management/test_skill_evolve_api.py`
- `tests/app` and `tests/recon` full suites
- `tests/attack` full suite
