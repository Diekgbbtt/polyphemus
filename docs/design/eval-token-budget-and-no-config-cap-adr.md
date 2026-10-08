# ADR: eval budgets count generated tokens; the hunt-config cap is removed

## Status
Accepted (2026-10-05).
**Decision 2 (the budget axis) is SUPERSEDED** by `eval-budget-axis-adr.md`
(#347, 2026-10-08): the budget now counts `capped_tokens` (generated output plus
uncached input), not generated output alone. The hunt-config-cap removal
(decision 1) and the setup structure stand.

## Context
- The jetlinks-1 trial was hard-stopped at its 10-config hunt cap while still
  inside tier 0 (broken access control): all 10 consumed configs were
  CWE-266/CWE-1220 hypotheses on the auth/identity Systems, and the
  validation-tier classes the ground truth lived in (CWE-78/94/918/22) were
  never scheduled. The cap turned a coverage-ordering issue into a total miss,
  and a consumed-config COUNT is not a failure signal.
- The trial-wide token budget counted `capped_tokens` (generated output plus
  uncached input, i.e. `total_tokens - cached`), so re-read context counted
  against the budget.

## Decision
1. The hunt-config cap is REMOVED: `TargetRun.hunt_config_budget`, the trial's
   `_poll_hunting` cap, the record's `cap` / `stop_count` / `final_count` /
   `overshoot` / `cap_baseline`, and the setup field are gone. A trial now
   settles on the run's own quiesce, the token budget, or the trial deadline.
2. The token budget counts `generated_tokens` (reasoning + visible output) via
   `api.usage_generated`, never input (cached or not).
3. The next eval (`eval/setups/webexploitbench-5.yaml`) features the 5 bundled
   targets, each with `token_budget: 15000000`.
4. (2026-10-08, amendment) The all-targets run lowers the cap to
   `token_budget: 4000000` per target
   (`eval/setups/webexploitbench-all-pulled.yaml`, all 15 targets, images
   pre-pulled from the dataset registry). 15M was calibrated for one
   well-covered target; 4M bounds the total spend of a 15-target serial run
   while still letting a single trial reach the hunting quiesce.

## Consequences
- Hunting runs to its natural quiesce; coverage is bounded by the run's own
  schedule and the token budget, not by an arbitrary config count.
- The budget is a pure output-spend bound; input volume (including re-reads)
  can never trip it.

## References
- jetlinks-1 trial `jetlinks-1-20261004T234556-9f4acf85`; #321.
