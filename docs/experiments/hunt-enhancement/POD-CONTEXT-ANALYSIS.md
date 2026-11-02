# Pod runner and triager context analysis

## Scope

This report covers the `pod_runner` and `pod_triager` roles on the white-jotter trial.
It uses the session-unweighted occupancy analysis and the formal duplication analysis.
It measures the bound tool descriptions with the same method used on the hunter.
It separates first-call cold input from warm-session occupancy.
It does not claim a behavioural quality result, because no new trial ran.

## Measured baseline

### Runner

| Component | Value |
|---|---:|
| First input | 8,810 tokens |
| First input characters | 37,361 |
| Cache read | 0 |
| System | 9,446 chars |
| Tool surface | 20,770 chars |
| First human | 6,574 chars |
| Session calls | 709 |
| Mean input | 34,979 tokens |
| Session cache share | 93.3% |
| Total input | 26.12M tokens |

### Triager

| Component | Value |
|---|---:|
| First input | 11,712 tokens |
| First input characters | 46,410 |
| Cache read | 0 |
| System | 11,724 chars |
| Tool surface | 19,580 chars |
| First human | 14,318 chars |
| Session calls | 79 |
| Mean input | 28,293 tokens |
| Session cache share | 66.3% |
| Total input | 2.53M tokens |

Both first calls are cold.
The static prefix has no cache read on the first call.
The runner session is warm after the first call.
The triager session is much less cached because its input is dominated by the observed evidence and the 89,087-char KB answer.

## Engineering faults

| Fault | Evidence | Class | Status |
|---|---|---|---|
| Spec paragraph is a partial D4 projection | prompt vs `TestImplementationSpec` | P | `skills` named; rest still prose |
| Runner tool list omitted `auth_store` | prompt vs bound surface | P | Fixed |
| Triager tool list omitted `graph_view` and `auth_store` | prompt vs bound surface | P | Fixed |
| Triager bound the full auth write contract | 6,364-char full contract on a read-only critic | P/E | Fixed to read-only |
| Conciseness directive copied into prompts and tool descriptions | 328 exact chars | E | Single-sourced and shortened |
| Memory guidance stated in the prompt, the note contract, and the context builder | three statements | S | Open |
| Variant table hand-copied from `VARIANT_BASES` | 10-row prompt table | S | Verified, not generated |
| Terminal vocabulary hand-copied from the validator | 5 reasons | S | Verified, not generated |
| Skill index and direct references | 1,081-char index in the trace | P | Current direct-reference line stays |

The largest fixed tax is the tool surface.
The largest semantic risk is the triager's variant and terminal tables.
They match the code today, but they are independently edited.
The runner's spec paragraph is also a projection, not the model.
The `skills` field is now named, but the full D4 field list is still not generated.

The triager carried the largest bound tool in the wrong mode.
`auth_store` was writable on a critic that never writes the store.
The binding is now read-only, which also removes the write arguments from the schema.

## Applied changes

| Change | Runner before | Runner after | Triager before | Triager after |
|---|---:|---:|---:|---:|
| Tool-description characters | 12,979 | 5,101 | 12,715 | 4,837 |
| Tool-description delta | -7,878 (-60.7%) | | -7,878 (-62.0%) | |
| System-prompt characters | 9,446 | 8,124 | 11,724 | 10,764 |
| System-prompt delta | -1,322 (-14.0%) | | -960 (-8.2%) | |
| Named bound tools | 7 | 8 | 4 | 6 |
| Auth-store mode | full | read-only | full | read-only |

The tool-description metric is the sum of `len(tool.description)` over the bound surface.
It includes the shared conciseness directive where the tool appends it.
It is not the audit's request-schema character count.

The runner and triager cuts are not pod-only edits.
Each role has the same 3,229 chars of shared description text and the same 4,649-char full-to-read-only auth-store mode.
The pod `exec` description did not change.
The pod note change is the shared conciseness directive.
The exact per-role decomposition is in `docs/design/hunting-context-dedup-impact-map.md`.

## Cache effect

The first calls are cold, so the fixed cut lands directly on uncached input.
The estimate uses about 4.24 chars per token for the runner and 3.96 for the triager.

| Case | Input | Cache read | Uncached | Miss share |
|---|---:|---:|---:|---:|
| Runner before, first call | 8,810 | 0 | 8,810 | 100% |
| Runner after, first call | 6,621 | 0 | 6,621 | 100% |
| Triager before, first call | 11,712 | 0 | 11,712 | 100% |
| Triager after, first call | 9,482 | 0 | 9,482 | 100% |

The runner first call loses about 2,189 uncached tokens, a 24.8% reduction.
The triager first call loses about 2,230 uncached tokens, a 19.0% reduction.
The miss share stays at 100% because both calls are cold.

The warm-session effect is different.
The removed fixed text is part of the cached prefix.
The uncached runtime evidence is unchanged.

| Case | Mean input | Cached | Uncached | Cache share |
|---|---:|---:|---:|---:|
| Runner before | 34,979 | 32,635 | 2,344 | 93.3% |
| Runner after | 32,790 | 30,446 | 2,344 | 92.9% |
| Triager before | 28,293 | 18,758 | 9,535 | 66.3% |
| Triager after | 26,063 | 16,528 | 9,535 | 63.4% |

The warm miss share rises slightly for the runner and more for the triager.
The absolute uncached tokens are unchanged.
This is the same cached-text arithmetic as the modeller.
The fixed cut lowers occupancy, not the progressive miss ratio.

## What would reduce the progressive miss ratio

The runner's and triager's miss tokens are the runtime evidence.
The largest triager payload is the 89,087-char KB answer.
The runner carries the 74,649-char replay result and the 20,898-char skill body.
Bounding those payloads at the source reduces both uncached input and cached carry.
Removing only the static prompt text lowers the window but can raise the miss share.

## Remaining work

- Generate the runner's spec paragraph from `TestImplementationSpec`.
- Generate the variant table from `VARIANT_BASES` and `PROCEDURE_GAP_FIELD`.
- Generate the terminal vocabulary from the decision validator.
- Single-source the memory key-list and reading guidance.
- Bound the KB answer, replay result, and skill body payloads at the source.
- Validate the behaviour on a later authorized trial.
