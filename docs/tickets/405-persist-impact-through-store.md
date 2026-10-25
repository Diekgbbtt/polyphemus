# 405 - Persist the impact through the store and the model sections

**What to build:** Add the impact to the vulnerability and the loop write schemas, the model sections, the store merge, and the loop files. Keep the failure-mode section optional during the expansion so the tree stays green. Add the impact completeness checks to the completion checker.

**Blocked by:** 404

**Status:** ready-for-agent

**Seams:** attack/hunting/threat_model.py, attack/hunting/threat_model_store.py

## Context

The loop file is the dispatch record. It must carry the impact and the computed loop risk so the mover can rank and gate without re-reading the model. The model document stays the source of truth and the store recomputes the profile at COMPLETED. A model written before this change must still parse and read as impact none.

## Acceptance criteria

- [ ] The vulnerability and the loop carry the impact in the write schema.
- [ ] The store round-trips the impact in the model document.
- [ ] The loop file carries the impact and the loop risk.
- [ ] The completion checker records a missing impact as a non-blocking finding.
- [ ] A model written before the impact model parses and contributes zero risk.
- [ ] The gate sections remain valid during the expansion.

## Verification

- Run the store round-trip tests.
- Run the loop-file tests.
