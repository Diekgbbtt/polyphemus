# Threat modeller context analysis

## Scope

This report covers the `hunting_threat_modeller` role on the white-jotter trial.
It uses the session-unweighted occupancy analysis and the formal duplication analysis.
It measures the current tool descriptions with the same method used on the hunter.
It separates cached occupancy from uncached runtime input.
It does not claim a behavioural quality result, because no new trial ran.

## Measured baseline

| Component | Value |
|---|---:|
| First input | 17,076 tokens |
| First input characters | 65,799 |
| Cache read | 14,336 tokens |
| Uncached input | 2,740 tokens |
| First-call cache share | 84.0% |
| System | 23,297 chars |
| Tool surface | 36,820 chars |
| First human | 5,015 chars |
| Session calls | 163 |
| Mean input | 215,777 tokens |
| Session cache share | 96.1% |
| Total input | 35.17M tokens |

The first call is warm on the static system and tool prefix.
The 2,740 uncached tokens are the first human turn plus framing.
The 163-call session is dominated by tool responses, not by the fixed prompt.
Tool responses are 72.9% of the session input.
The fixed system and tool descriptions are 18.7% of the session input.

## Engineering faults

| Fault | Evidence | Class | Status |
|---|---|---|---|
| Five-state and gate table authored in prose and code | prompt, `GATE_SECTIONS`, `ModelSections`, `hunts_store` description, store validator | S | Open |
| Reference-field table is a partial human copy | prompt table vs `ModelSections` references | S | Verified, not generated |
| `hunts_store` has a 1,210-char description beside a 14,903-char schema | tool surface | P | Description shortened |
| Tool list omitted `record_skill_lesson` | prompt vs bound surface | P | Fixed |
| Target-front 5xx paragraph copied verbatim from the hunter | 715 exact chars | E | Replaced with a pointer |
| Completion and drop rules authored in prose and validator | prompt vs store checker | S | Open |
| Skill index and direct references | 107-char index in the trace | P | Current direct-reference line stays |

The strongest structural fault is the state and section table.
The same five states and six sections are named in the prompt, the tool description, `GATE_SECTIONS`, `ModelSections`, and the store validator.
The prompt is a readable projection, but it is edited independently.
A change to a gate or section can leave the prompt stale.
The reference-field table has the same risk.
It is complete today, but nothing prevents it from drifting.

The strongest exact fault was the 5xx paragraph.
It was byte-identical to the hunter paragraph and paid twice.
The prompt now names the shared rule and keeps only the 502, 503, 504, and 404 semantics.

The tool list was a hidden-capability bug.
`record_skill_lesson` is bound but was not named.
The prompt now names it and marks `auth_store` as read-only.

## Applied changes

| Change | Before | After | Delta |
|---|---:|---:|---:|
| Tool-description characters | 18,594 | 6,850 | -11,744 (-63.2%) |
| System-prompt characters | 23,297 | 22,887 | -410 (-1.8%) |
| Auth-store binding | full write contract | read-only contract | -4,649 chars |
| Tool names | 9 named | 10 named | +1 |
| 5xx rule | 715-char copy | shared pointer | -about 500 chars |

The tool-description metric is the sum of `len(tool.description)` over the bound surface.
It includes the shared conciseness directive where the tool appends it.
It is not the audit's request-schema character count.

The 11,744-char modeller cut is not a modeller-only edit.
It decomposes into 7,095 chars of shared description text and 4,649 chars from the full-to-read-only auth-store mode.
The shared text is the same constant set that the hunter, runner, and triager bind.
The modeller-specific `hunts_store` description did not change.
The modeller `notes` change is the shared conciseness directive.
The exact per-role decomposition is in `docs/design/hunting-context-dedup-impact-map.md`.

## Cache effect

The first call has 14,336 cached tokens and 2,740 uncached tokens.
The cut removes about 3,158 cached tokens: 3,051 from tool descriptions and 107 from the system prompt.
The first human remains 5,015 chars and remains uncached.

| Case | Input | Cache read | Uncached | Miss share |
|---|---:|---:|---:|---:|
| Before, warm first call | 17,076 | 14,336 | 2,740 | 16.0% |
| After, warm first call | 13,918 | 11,178 | 2,740 | 19.7% |
| Before, cold first call | 17,076 | 0 | 17,076 | 100% |
| After, cold first call | 13,918 | 0 | 13,918 | 100% |

The warm-cache miss share rises.
The absolute uncached tokens are unchanged.
This is the expected result when only cached fixed text is removed.
The denominator shrinks and the numerator stays.

The cold-cache first call drops 3,158 uncached tokens, an 18.5% reduction.
That is the case where the removable text has not yet been cached.

At the lifecycle level, the 163 calls lose about 514,754 input tokens, or 1.5% of 35.17M.
The uncached tokens are unchanged in the warm regime.
The miss share moves from about 3.9% to about 4.1%.
The progressive miss ratio is therefore not reduced by this cut.
The runtime payloads drive the progressive miss ratio.

## What would reduce the progressive miss ratio

The first human turn is 2,740 uncached tokens on the first call.
The large tool responses are the lifecycle miss drivers:

- the 74,649-char HTTP-history page, carried for 154 turns;
- the 22,302-char auth store, carried for about 154 turns;
- the 8,567-char skill listing, carried for about 154 turns.

Bounding those payloads at the source reduces uncached input and cached carry together.
Removing only cached prompt text reduces occupancy but can raise the miss share.
The report should not present cached-text removal as a miss-ratio win.

## Remaining work

- Generate the state, gate, and reference tables from `ModelState`, `GATE_SECTIONS`, and `ModelSections`.
- Generate the completion and drop table from the store checker.
- Bound the HTTP-history, auth-store, and skill-listing payloads at the source.
- Validate the behaviour on a later authorized trial.
