# 409 - Render the combined risk on the status surfaces

**What to build:** Render the combined risk total, the impact breakdown, the risk breakdown, and the threshold on the status and run-record surfaces. Keep the likelihood breakdown visible for audit.

**Blocked by:** 408

**Status:** ready-for-agent

**Seams:** attack/hunting/hunting_status.py, attack/hunting/runtime.py

## Context

The operator reads the run record to compare the A/B arms. The status must show why a unit crossed the threshold and which loops contributed the risk. The display uses the recorded weights, never a recomputation with different constants.

## Acceptance criteria

- [ ] The status renders the combined total, the impact breakdown, and the risk breakdown.
- [ ] The likelihood breakdown remains visible.
- [ ] The threshold and its basis are rendered.
- [ ] A legacy run without the impact fields renders an explicit absence.
- [ ] The display tests cover the new and legacy records.

## Verification

- Run the status tests.
