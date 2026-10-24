# Ticket 401: hunting spec lifecycle

- **Tracker:** https://github.com/Diekgbbtt/polyphemus/issues/401
- **Severity:** high (run wedge and false completion).
- **Area:** `src/polymerhus/attack/hunting/`.
- **Status:** open, `enhancement`, `needs-triage`.

## Summary

The gate-side lifecycle is hardened. The remaining work is the upstream spec
lifecycle: write-time validation, a structured loop over `hypothesised` drafts,
the produced-to-consumed ownership decision, and a named run-record
blocked/degraded state.

## Implemented on the current branch

- The serial gate distinguishes pending produced `ratified` specs, consumed
  `ratified` completion specs, and produced `dropped` specs.
- A hunt is done only with the run-scoped `terminal.yaml` marker, no pending
  produced `ratified` spec, and a terminal state for every consumed spec.
- The hunter's symbolic COMPLETE hook calls
  `HunterMemoryStore.settle_hypothesised()`: leftover `hypothesised` specs are
  declassed to `dropped` with `declassified: hunter-complete`, then the terminal
  marker is written.
- `is_run_quiesced()` calls `hunting_artifacts_terminal()`: any current-run
  stale, malformed, pending, or export-less artifact blocks completion. The
  surfer cannot quiesce `complete` just because it has no dispatchable item.
- The `surfer-dispatch-degraded` path persists its degraded envelope as a
  durable `PodExport`.
- The gate scans actual files, so a late `hypothesised` write behind an older
  marker is blocked.

## Historical evidence

Scan of 1,514 historical spec files (963 hunter specs, 551 pod variants) under
`/opt/polymerhus-dev/eval/instances/data/eval-server-1`:

- YAML syntax and duplicate-key parse errors: **0**.
- Current D4 shape: **150** (9.9%).
- Unknown D4 fields: **1,358** (89.7%).
- Retired D4 fields `testing_pattern` / `payload_vector_space` /
  `interpretation_guidance`: **1,271** (83.9%).
- Legacy hypothesis/mechanism shape (`hypothesis`, `conflicts`, `mechanism`,
  `supports`, `test`, `fault_class`, `rank`): **465** (30.7%).
- Missing verification symptoms: **48** (3.2%).
- Empty verification symptoms: **51** (3.4%).
- Missing target identity: **3** (0.2%).
- Current live project `0c8cb6e6-7e91-4a01-880e-408896c0ce4a`: 14/14
  canonical.

The historical failures are schema-level, not YAML-level. The old D4
`extra="forbid"` rejects the retired fields at INIT; the live schema is clean.

## Remaining gaps

1. **Write-time validation.** Reject a body that fails the current contract
   before it lands. Add a coded rejection at the `hunts_store.write` seam and a
   repair path for an existing corrupt file.
2. **Structured hypothesised loop.** No free-form re-prompt is in scope. The
   hunter should present each produced `hypothesised` spec sequentially for an
   explicit promote/drop decision before graph COMPLETE. If the tracker reaches
   COMPLETE with an undecided spec, the settle hook declasses it to `dropped`.
3. **Consumed transition ownership.** Decide whether the hunter controller
   moves `ratified` specs to consumed before COMPLETE, or whether the mover's
   admission move remains the contract. The ADR says admission; the operator
   wording says "dispatchable = consumed". The gate uses produced `ratified` as
   pending admission and consumed `ratified` as the completion set.
4. **Run-record health.** Expose the `hunting_artifacts_terminal()`
   blocked/degraded reason on the run record. The gate and audit hold
   completion, but the operator needs a named state.

## Acceptance criteria

- `hunts_store.write` rejects a malformed body with a coded error before any
  file lands.
- A completed hunt with a strained `hypothesised` set is impossible: each
  draft is promoted or dropped by the structured loop; the COMPLETE settle hook
  declasses any remaining draft.
- The serial cursor uses consumed `ratified` specs as its completion set,
  produced `ratified` specs as pending admission, and produced `dropped` specs
  as terminal.
- `is_run_quiesced()` never returns true while a current-run malformed, stale,
  pending, or export-less artifact exists.
- A named blocked/degraded reason is visible on the run record when the audit
  holds completion.
- Tests cover malformed write rejection, structured draft decisions,
  consumed-vs-produced cursor, dropped exclusion, terminal-marker requirement,
  declass-at-COMPLETE, and quiesce fail-safe.

## Code map

- `src/polymerhus/attack/hunting/hunter_memory.py` - `write_specs`,
  `finalize_specs`, `settle_hypothesised`, `consume_spec`,
  `read_terminal_set`.
- `src/polymerhus/attack/hunting/hunter_tools.py` - `hunts_store` write/finalize
  seam.
- `src/polymerhus/attack/hunting/pipeline_sync.py` - `RunSyncGate`, `SyncFacts`,
  `hunting_artifacts_terminal`.
- `src/polymerhus/attack/hunting/surfer.py` - hunter COMPLETE settle hook, pod
  degraded export, `is_run_quiesced`.
- `src/polymerhus/attack/hunting/pod/pod_memory.py` - `read_pod_export`,
  `write_pod_export`.
- `src/polymerhus/attack/hunting/mover.py` - produced/consumed recovery and
  `consume_spec`.
