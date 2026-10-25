# 420 - Update the design specs, CONTEXT, and the ADR

**What to build:** Update the design specs listed in the impact map, the hunting CONTEXT.md, and the ADR. Record the final scoring algorithm, the well-formedness loop, the failure-mode removal, the class guard, and the measured evidence.

**Blocked by:** 419

**Status:** ready-for-agent

**Seams:** docs/design, attack/hunting/CONTEXT.md

## Context

The docs must describe the code as it is, not the plan. The workbench decisions that the operator superseded are marked superseded, not deleted. The historical experiment reports stay as they are.

## Acceptance criteria

- [ ] Every design spec in the impact map is updated or marked superseded.
- [ ] CONTEXT.md carries the new terms and no removed term.
- [ ] The ADR records the final decisions and the evidence.
- [ ] No doc describes failure modes as a current artifact.
- [ ] The docs match the code and the tests.

## Verification

- Cross-read the docs against the code and the tests.
- Run the full verification phase.
