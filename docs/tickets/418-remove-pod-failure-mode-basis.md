# 418 - Remove the pod failure-mode variant basis

**What to build:** Remove the failure-mode variant basis and the failure_mode_plausible field. When no procedure gap remains, no variant basis is derivable. Remove the triager's step 5, the table row, and the field description.

**Blocked by:** 417

**Status:** done

**Seams:** attack/hunting/pod/variant_basis.py, attack/hunting/pod/agents.py, attack/hunting/pod/graph.py, attack/hunting/pod/context.py, attack/hunting/prompts/pod-triager.md

## Context

The pod keeps the other eleven bases: the nine procedure gaps and the two execution triggers. A pod that cannot derive a basis terminates honestly instead of minting a failure-mode variant.

## Acceptance criteria

- [x] The FAILURE_MODE literal is gone.
- [x] VARIANT_BASES has eleven entries.
- [x] mint_variant_basis has no failure_mode_plausible parameter and returns None when no gap remains.
- [x] The TriagerDecision schema has no failure_mode_plausible field.
- [x] The pod triager prompt has no step 5, table row, or field description.
- [x] The pod context no longer mentions the failure-mode fallback.
- [x] The tests are updated and the pod suite passes.

## Verification

- Run the pod variant-basis tests.
- Run the pod prompt tests.
