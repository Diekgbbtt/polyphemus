# 412 - Add the well-formedness pseudo-phase to the pass

**What to build:** Add the well-formedness turn to the modeller pass between vulnerabilities and completed. The turn loads the class skill for each loop, counterchecks the trust assumptions, and either patches a lower gate or exits. Add the wellformedness note kind, written once at the exit.

**Blocked by:** 411

**Status:** done

**Seams:** attack/hunting/threat_modeller.py, attack/hunting/threat_modeller_tools.py

## Context

The passive tracker observes hunts_store gate writes, not notes. A lower-gate write after vulnerabilities is already recorded as lower_gate and is the re-entry signal. The note is the exit memory: loops checked, skills loaded, assumptions added, structural gap, final action. The loop has no iteration bound. The model does not gain a new ModelState value.

## Acceptance criteria

- [x] The pass asks the well-formedness turn after vulnerabilities.
- [x] The pass re-asks the turn after a lower-gate write.
- [x] The pass exits on the wellformedness note plus the COMPLETED write.
- [x] The notes tool accepts the wellformedness kind.
- [x] The note is written once at the exit and not per iteration.
- [x] The note carries the loops checked, the skills loaded, the assumptions added, the structural gap, and the final action.
- [x] The model state enum is unchanged.
- [x] A missing note is a non-blocking completion finding.
- [x] The pass tests cover the clean exit and the re-entry path.

## Verification

- Run the modeller pass tests.
- Run the notes tool tests.
