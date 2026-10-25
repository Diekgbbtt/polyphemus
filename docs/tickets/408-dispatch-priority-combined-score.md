# 408 - Move the dispatch priority to the combined score

**What to build:** Move the dispatch priority, the low-loop gating, and the live-loop map to the combined risk bucket. The loop rank stays the dispatch order, but the rank is now the risk rank.

**Blocked by:** 407

**Status:** ready-for-agent

**Seams:** attack/hunting/pipeline_sync.py, attack/hunting/mover.py, attack/hunting/surfer.py

## Context

The buckets are critical >= 12, high 8..11, medium 4..7, low 1..3, none 0. A low-bucket loop waits while a higher-bucket loop is produced or a higher-bucket hunter is live. The mover reads the loop file, not the model, for the dispatch decision. The pipeline sync risk helper must use the same combined weight.

## Acceptance criteria

- [ ] The loop file carries the risk bucket.
- [ ] The mover's sequencing gates the low bucket behind higher buckets.
- [ ] The live-loop map carries the bucket, not the likelihood string.
- [ ] The pipeline sync risk helper uses the combined loop risk.
- [ ] The hunt rank remains the loop rank and the rank is the risk rank.
- [ ] A malformed or missing risk contributes zero and never crashes the queue.

## Verification

- Run the mover tests.
- Run the pipeline-sync tests.
- Run the surfer wiring tests.
