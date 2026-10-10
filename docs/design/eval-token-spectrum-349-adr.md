# ADR: the trial record carries the per-agent token spectrum

*Status: accepted (2026-10-09). Implements #349 (EV-35).*

## Context

The trial outcome artifact (`trial.yaml`, written by `eval/orchestrator/trial.py::Trial._finish`) captured the outcome and, since #346, the project's two-axis usage snapshot and the capped-token spend.
It did not carry the per-agent token split.
So the cached/uncached spectrum of a trial was recoverable only out-of-band from Langfuse or the litellm spend logs, as the 2026-10-08 token forensics had to do.

Two live concerns are both about that spectrum:

- the token-budget axis `capped_tokens = generated + uncached` (#347), and
- the cache-hostility defect (`mechanism_typist` / `job_orchestrator` cold bursts, EV-33 / #348).

Without the per-agent split in the record, a trial cannot explain why it spent what it spent, and a cache regression is invisible at the trial level.

The durable usage ledger already carries the split.
`app/llm/usage.py::UsageLedger.snapshot(project_id)["by_agent"]` returns, per agent, `context_tokens` (`cached` + `uncached`), `generated_tokens` (`reasoning` + `visible`), `total_tokens`, `capped_tokens`, and `calls` (#326), and the app exposes it read-only at `GET /projects/{id}/usage`.
The missing piece is that the eval harness did not project it into the record.

## Decision

The trial record gains a top-level, additive `token_spectrum` block: one flat typed entry per agent.

```
token_spectrum:
  <agent>:
    visible:        int   # generated output, non-reasoning
    reasoning:      int   # generated output, reasoning
    cached_input:   int   # context read from cache
    uncached_input: int   # fresh prefill input
    generated:      int   # reasoning + visible
    total:          int   # cached + uncached + generated
    capped:         int   # generated + uncached (the budget axis)
    calls:          int   # model calls attributed to the agent
```

### Source of truth: the durable ledger, decoded once at the terminal

The `token_spectrum` is decoded from the ledger's own `by_agent` surface with `eval/orchestrator/api.py::usage_spectrum` / `spectrum_by_agent`, from the SAME usage read the spend accounting already performed:

- a budget stop already read the surface (`Trial._check_spend`), and
- a non-stop terminal reads it once (`Trial._terminal_usage`, #346).

No new API call and no second read are added.
The only projection is `generated = reasoning + visible`, which sums the ledger's own output split; `cached_input` / `uncached_input` are the ledger's context split, and `total` / `capped` / `calls` are the ledger's scalars.
The spectrum is therefore never re-derived from traces or spend logs.

### Schema and fail-open

`SPECTRUM_FIELDS` in `api.py` fixes the eight-field order as the schema contract.
A malformed or absent agent entry reads as zeros (advisory), a bool is not an int, and a negative count reads as zero - the same discipline as `usage_total` / `usage_capped`.
When the usage surface is unreachable the terminal read fails open, the record still writes, and `token_spectrum` is `None` (never a fabricated zero entry).

## Impact map

Every artifact, schema, attribute, endpoint, consumer, doc, and test the change touches, with its reason and direction.

| # | Artifact | Kind | Reason | Direction |
|---|---|---|---|---|
| 1 | `eval/orchestrator/api.py` | decoder | Owns the wire decode: `usage_spectrum` / `spectrum_by_agent` project the ledger `by_agent` into the flat schema; `SPECTRUM_FIELDS` pins it. | additive |
| 2 | `eval/orchestrator/trial.py` `TrialRecord.token_spectrum` | schema | The new outcome attribute; `dict | None`, defaults None so older records load. | additive |
| 3 | `eval/orchestrator/trial.py` `Trial._finish` | writer | Projects the same `by_agent` the spend used into `token_spectrum`; no new read. | additive |
| 4 | `eval/orchestrator/trial.py` `_terminal_spend` / `_terminal_usage` | source seam | Unchanged shape; already returns the `by_agent` the spectrum is decoded from (a budget stop or the terminal snapshot). | unchanged |
| 5 | `eval/orchestrator/cli.py` `trial` command | consumer | Prints each agent's spectrum after the spend line, so the split is visible without leaving the terminal. | additive |
| 6 | `eval/prompts/assessment.md` | consumer doc | Names `token_spectrum` as part of the trial record the assessor reads, so a thin surface or a budget stop is explainable. | additive |
| 7 | `eval/CONTEXT.md` | vocabulary | New **Token spectrum** term; the trial-data-model glossary a reader uses. | additive |
| 8 | `docs/design/eval-bugs-map.md` EV-35 | register | Marks the failure fixed by #349 with the decode/schema/doc pointers. | status |
| 9 | `docs/design/eval-token-spectrum-349-adr.md` | decision | This record. | new |
| 10 | `tests/eval/test_orchestrator_api.py` | test | Pins the decoder: the ledger surface maps to the eight fields, the schema order, and fail-open/malformed/negative cases. | new |
| 11 | `tests/eval/test_orchestrator_trial.py` | test | Pins the record: a terminal snapshot and a budget stop both write the flat spectrum to `trial.yaml`; a failed usage read leaves it None. | new |
| 12 | `app/llm/usage.py`, `project_management/api.py`, `GET /projects/{id}/usage` | source | Unchanged: the durable ledger and its endpoint are the source of truth; the harness only decodes them. | unchanged |

## Consumers deliberately unchanged

- `eval/orchestrator/monitor.py`: the tick's pure decision reads the execution terminal and the node outputs, not the spend; no decision depends on the spectrum, so the monitor does not read it.
- `eval/orchestrator/surfer.py::spend_triggers`: the budget trigger reads `token_budget` / `spent_tokens`; the spectrum is diagnostic, not a trigger input.
- The app-side usage surface: unchanged - the eval projection must not fork the ledger's own representation.

## Consequences

- A trial's cached/uncached spectrum is readable from `trial.yaml` alone, per agent.
- The budget axis (#347) and a cache regression (#348 / EV-33) are explainable at the trial level.
- The record is backward compatible: `token_spectrum` defaults None, so a pre-#349 record still loads.
- No new API call and no new app-side surface: the decode rides the terminal usage read the spend already performs.

## Acceptance criteria

- (a) The trial record reports per-agent `visible`, `reasoning`, `cached_input`, `uncached_input`, plus `generated` / `total` / `capped` / `calls` - covered by the record test and the schema-order assertion.
- (b) The values come from the durable ledger, not a re-derivation - the decoder reads the `by_agent` the spend read; no trace or spend-log path exists.
- (c) A trial's cached/uncached spectrum is readable from the trial file alone - covered by the written-`trial.yaml` assertion.
- (d) Docs + ADR updated; a regression test pins the schema - `eval/CONTEXT.md`, the assessment prompt, the bugs map, this ADR, and the two test files.

## References

- #349 (this change), EV-35 in `docs/design/eval-bugs-map.md`.
- #326 (`docs/design/usage-ledger-durability-326-adr.md`), #346, #347 (`docs/design/eval-budget-axis-adr.md`), #348 (EV-33).
- `eval/orchestrator/api.py`, `eval/orchestrator/trial.py`, `app/llm/usage.py`, `src/polymerhus/project_management/api.py`.
