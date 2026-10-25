# 413 - Add the class binding guard and the non-blocking finding

**What to build:** Require a suite class parent or leaf on every loop. Remove suite_gap. Forbid technique families as the class. Add the non-blocking completion finding for an empty class, a technique family, and a name outside the suite.

**Blocked by:** 412

**Status:** done

**Seams:** attack/hunting/prompts/threat-modeller.md, attack/hunting/threat_model.py, attack/hunting/threat_modeller_tools.py

## Context

The guard is a signal, not a symbolic rejection. A novel class binds its nearest parent and keeps the novel name in canonical_class. Technique families such as defence-bypass and proxy-techniques stay in the characterisation prose. The suite index is read from the skill tree; the validator does not invent a class list.

## Acceptance criteria

- [x] Every loop carries a suite class parent or leaf.
- [x] suite_gap is removed from the schema, the prompt, and the loop.
- [x] The prompt states the class-binding rule verbatim.
- [x] The prompt states that technique families are not classes.
- [x] The completion checker records a non-blocking finding for an empty class.
- [x] The completion checker records a non-blocking finding for a technique family.
- [x] The completion checker records a non-blocking finding for a name outside the suite.
- [x] The finding never rejects the write.
- [x] A novel class binds its nearest parent and keeps its canonical name.
- [x] The tests cover all four cases.

## Verification

- Run the threat-model store tests.
- Run the prompt tests.
