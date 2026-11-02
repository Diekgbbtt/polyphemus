# Impact assessment system - adversarial review

*Status: completed 2026-10-26.*
*Branch: `impact-assessment-tdd`, base `a15f5ec3`, review fix `fcb8c0c8`.*
*Scope: tickets 436-441, the spec, the tests, and the native framework patterns.*

## Review method

Two reviewers ran independently:
- the spec reviewer checked every acceptance criterion in tickets 436-441 against the code and the persisted artifacts;
- the code reviewer checked the Standards and Spec axes, the native pydantic/FastAPI/LangGraph patterns, the fail-open paths, the atomic writes, the coded rejections, and the test quality.

The reviewers did not fix anything.
The findings below are the reviewers' findings.
The fix column names the change made after the review.

## High findings

| ID | Finding | Fix |
|---|---|---|
| S1 | The modeller turn prompt reported a defaulted section as written. At the `PRIOR_ART` turn it said `prior_art` was in `sections written`, although the section had never been authored. The branch's `_section_holds` helper existed in the tool layer and was not reused in `llm.py`. | `llm.py` now uses `_section_holds`. A regression test pins the `PRIOR_ART` turn. |
| P1 | The store refused every v2 document, while the spec says a v2 model remains readable and consumable under its stored `validation.valid`. The measurement could read v2 raw, but the store and the intake could not. | `read_model` and `read_completed_units` read a legacy v2 document. The mover and the prior-art query stay on the current schema, so a v2 threat file is never dispatched into the v3 hunter contract. A regression test pins the boundary. |

## Medium findings

| ID | Finding | Fix |
|---|---|---|
| P3 | An extra completion invariant, `capability_path ⊆ precursor_refs`, was not in the spec. A path may chain a capability yielded by another vulnerability. | The invariant is removed. A test asserts that a cross-vulnerability path is valid. |
| S2 | The forward-jump test was rewritten into a ladder that writes every gate on the first turn, so the cold jump (six silent turns, then a jump) was no longer covered. The abort default rose from 5 to 7 without a test. | A cold-jump test now drives six silent turns and the seventh-turn jump. It pins the default behaviour. |
| P2 | Six live amendment sentences still described the retired typed-filter query (`unit_id`, `kind`, `web_vulnerability_class`, `disposition`, `text`). | The amendment bullet now describes the required `kind` plus the non-empty `{path, regex, flags}` filters. Nine documents were updated. |

## Low findings and dispositions

| ID | Finding | Disposition |
|---|---|---|
| S3 | The hunter-payload docstring said the key set was exactly the listed keys; `impact` was missing. | Fixed. |
| S4 | The store error docstring said "five workflow gates"; there are seven. | Fixed. |
| S5 | The REST read/update docstrings did not mention the scope field. | Fixed. |
| S6 | The tool and the store both validated the query's kind and filters. | The duplicate empty-filter check is removed; the store owns the path/regex validation. The `kind` conversion stays in the tool. |
| S7 | The tool reimplemented the base `_run` and dropped the base's args-schema guard. | The base now owns a `_dispatch_other` hook; the tool uses it for `query`. |
| S8 | The measure prompt documented `schema: mixed` and a `notes` member the script did not emit. | The script now emits `mixed` with a `legacy_v2` sub-block; the prompt carries `legacy_v2`. `notes` is the subagent's own output. |
| S9 | `is_broad_class` was reused as an "is bound" predicate. | `is_bound_class` is added and tested. |
| P5 | The grounding rendered the impact as inline labels, not the spec's `##` headings. | The spec now says "labelled lines", matching the code. |
| P6 | The spec declared a `ThreatQuery` model that was never built. | The spec now documents the tool args and the `PriorArtQuery` record. |
| P7 | A mixed v2/v3 store silently dropped the v2 rows. | The metric emits `schema: mixed` and a `legacy_v2` block. A test pins it. |
| P8 | A dict-valued filter path echoed the whole record in `matched`. | The matched value is truncated at 500 characters. |
| P9 | An abandoned copy double-counted the impact rows. | The impact metric excludes abandoned copies. A test pins it. |
| P10 | Several write-schema fields are optional where the spec's typed model requires them. | Deliberate lenient-write pattern; the completion check reports the missing fields. Empty ids are excluded from the reference sets. |

## Residual risks

1. The precursor abstraction is prompt-bound. No deterministic check rejects a `procedure` that names a request, a payload, or a tool. The spec accepts this: the hunter payload audit and the measurement review judge it.
2. The query regex is not time-bounded. A catastrophic-backtracking pattern can stall a modeller turn. The pattern is capped at 200 characters; a time bound is a follow-up.
3. An empty regex is accepted and matches every record, bounded by the 50-record limit.
4. The 7-turn abort bound is a product-visible default. It is the minimum that preserves the documented cold jump. A test now pins the behaviour.
5. A v2 gate write is still refused. A resumed v2 project must use a fresh project. The read path is compatible; the write path is not migrated.
6. The damage semantic and the CIA-after-assessment consistency are judged by the model, the measurement review, and the assessment. They are not deterministic.
7. The query cost grows with the number of units; each query walks the project's model directories.

## Verification

- `tests/attack tests/eval tests/project_management`: 2244 passed, 6 skipped.
- The focused suites for 436-441 pass.
- `compileall` is clean.
- `git diff --check` is clean.
- No em dash and no co-author trailer in the change.

## Verdict

The two high findings and the two medium findings are fixed.
The remaining findings are low, documented, or deliberate.
The system matches the impact-assessment spec for tickets 436-441.
The branch is not pushed or merged.
