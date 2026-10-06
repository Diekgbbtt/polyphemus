# ADR: #324 - the WSTG compact-document budget is content-bounded, not path-bounded

*Status: implemented in this change. Profile: B (root cause not confirmed by the ticket), reproduced and diagnosed before the fix. No new spec; this amends the WSTG compaction design in `docs/design/lightrag/preprocessing_pipeline.md`.*

## Context

`tests/lightrag/test_preprocess.py::test_wstg_profile_compacts_architecture_mapping_scenario` failed on `dev` with `assert 8029 < 8000`.

The ticket framed the choice as "did the compaction rule regress, or is the threshold stale", and forbade a bare bump of the bound.

The compact INFO-10 document is a fixed card: `_render_wstg_info_10_compact_document` (`lightrag/preprocess.py:2139`) hardcodes its body and ignores the source fragments.
Its only variable input is the scenario anchor block, `_render_wstg_anchor_block` (`lightrag/preprocess.py:1083`), which rendered `- Source file: {source_file.as_posix()}`.

The evidence:

- The rendered length tracked the absolute source path length 1:1.
  A 54-character path produced 7914 chars; a 187-character path produced 8047 chars.
- The test writes its source under pytest `tmp_path`, which is absolute.
  Re-running the same test reported 8028 and then 8029 chars, because the `pytest-N` temp directory name changed length between runs.
- The committed production card `lightrag/data/lightrag/rag_storage/kv_store_full_docs.json` (WSTG-INFO-10) was 7998 chars - only 2 under the bound - because production passes a repo-relative path.

So neither the rule's content nor the threshold was wrong in isolation.
The rule embedded an unbounded, environment-specific value (the filesystem path) into a size-budgeted artifact, so the measured size was a function of the environment, not the document.
The threshold was therefore not a stable contract at all.

## Decision

1. **Fix the rule: the anchor embeds the portable source file name, not a filesystem path.**
   `_render_wstg_anchor_block` renders `- Source file: {source_file.name}`.
   The reconstructed document is now a deterministic function of the scenario id, title, and file name.
   Directory context is redundant: the anchor already renders `WSTG category: {name} ({code})`.
   The manifest keeps the full `source_path` as metadata, so traceability is unchanged.

2. **Single-source the compact budget.**
   `WSTG_COMPACT_DOCUMENT_MAX_CHARS = 8000` (`lightrag/preprocess.py`) is the one definition of the compact-card char budget.
   `_WSTG_COMPACT_DOCUMENT_RENDERERS` is the one definition of the compact scenario set, used both for render dispatch and for QA.

3. **Enforce the budget at the QA seam.**
   `_add_wstg_document_qa_issues` raises the error `compact_document_over_budget` for a compact card over budget, so `--qa-only --fail-on-qa-issues` blocks the regression before indexing tokens.

The three test bounds `< 8000`, `< 8500`, and `< 7500` become `<= WSTG_COMPACT_DOCUMENT_MAX_CHARS`.

## Why the bound is 8000, and why it is not a bump

The bound is not chosen to fit the number; it is the strictest existing bound, retained and applied uniformly.
After the fix the compact cards measure: WSTG-INFO-10 ~7.9k, WSTG-APIT-01 ~6.6k, WSTG-APIT-02 ~5.9k characters.
8000 is the largest intrinsic card plus headroom for a bounded source file name, so it is the correct single compact budget.
The bug was never that 8000 was too small; it was that 8000 was being measured against a machine path.

The compact budget (8000) is distinct from the corpus extraction-timeout budget (`max_document_chars`, default 60000, `lightrag/preprocess.py:3478`).
The compact budget is the stricter "card" contract for the bespoke scenarios; the corpus budget is the general large-document warning.

## Consequences

- The test is deterministic and environment-independent, as the ticket believed it already was.
- No rendered methodology document embeds a filesystem path, so the corpus cannot leak the checkout or temp layout.
- The committed `rag_storage` snapshot carries the old relative-path line until the next ingestion refresh; it is a periodically-refreshed snapshot, not asserted against the renderer, so this is a known and bounded drift.
- A future regression of the compact contract fails static QA instead of failing a size-sensitive unit test.

## Tests

- `test_wstg_compact_document_is_independent_of_source_path` - the same content at two path depths renders byte-identical cards, no `tmp_path` leaks in, and the card is within budget. This test failed before the fix (the two cards differed only by the embedded path).
- `test_wstg_compact_document_over_budget_is_flagged_by_qa` - a compact card over a shrunk budget yields `qa_result.passed is False` with `compact_document_over_budget`.
- `test_wstg_profile_compacts_architecture_mapping_scenario` and `test_wstg_profile_compacts_api_recon_and_bola_scenarios` now assert against `WSTG_COMPACT_DOCUMENT_MAX_CHARS`.
