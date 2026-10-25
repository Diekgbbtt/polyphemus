# 403 - Record the baseline measurement

**What to build:** Record the baseline census of the eval-server-1 run: 17 unit models, 113 loops, the low-yield share, the impact families, the boundary shapes, the likelihood and impact distribution, the class-integrity gaps, the token economics, and the per-loop classification. Add the read-only survey script so the census is reproducible.

**Blocked by:** None - can start immediately

**Status:** done

**Seams:** docs/experiments/modeller-impact-quality

## Context

Committed at 9eb66a0a. The baseline is 70/113 low (61.9%), 25/113 severe (22.1%), 18/113 conditional (15.9%), 45/113 suite gaps (39.8%), 5 technique-family classes, 2 non-suite names, a 39.8% green-class share, and a 31.1% modeller share of the 7M cap with 10/113 loops dispatched.

## Acceptance criteria

- [ ] The report uses the measurement template and states that it is a census, not an A/B.
- [ ] The per-loop classification CSV is committed.
- [ ] The survey script reproduces the aggregate counts.
- [ ] The report records the caveats and the open questions.

## Verification

- Run the survey script against the instance and compare the aggregates.
