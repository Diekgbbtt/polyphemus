---
name: js-evidence-triage
description: >-
  Turn verified generated or recovered JavaScript evidence into a bounded, resumable question-and-span shortlist using controlled literal search and reads through Exec.
metadata:
  version: '1.2'
---

Use this skill in two distinct modes.

## Early guidance

1. Load `reference js-evidence-triage commands` and
   `reference js-evidence-triage priorities` after `context` and `notes`, before
   inventory selection or acquisition. Run one bounded initial `triage-list`
   to resume existing spans and cursors.
2. Use notes, the shortlist and subsequent inventory/scan/structure evidence
   to form candidate questions. Guidance and this initial list are planning,
   not code analysis. They consume attempts but do not search code, read code
   or start the runtime's triage-analysis phase. Return to
   `js-inventory-intake` after recording provisional priorities and gaps.

## Actual analysis

3. Start analysis only when authorized readable code is available. Any
   `search-code`, `read-code`, `triage-select` or `triage-update` call is
   analysis work and consumes the protected phase. A scan, map or structure
   gap does not erase an acquired, integrity-verified file.
4. Express each candidate as a question linked to a clue:
   `trigger/input → transformation → request/state/sink → effect`; name the
   inventory, scan, recovered-source or structure evidence that suggested it
   and the decision the answer could support.
5. Group questions by mechanism and dataflow, not by wording, function name or
   file. Firebase configuration, API-key persistence and auth request-header
   construction belong to one group when the inspected data connects them.
   Different labels or files alone do not make leads independent.
6. Compare currently supported groups before acting. Choose the highest-value
   available group and inspect its smallest useful span. One scope is valid
   when it is the only well-supported scope; record why alternatives were
   deferred. Do not manufacture variety to satisfy a count.
7. Before another pass over the same group, write a note stating:
   the new information needed, how it could change a decision, and why it
   outranks the other available groups. Without that justification, switch to
   an independent group or close with pending coverage.
8. For a concrete question, use
   `search-code <lead_id> --text <literal> --limit 5`. The literal is exact,
   case-sensitive and short, never a sentence. A match is a locator, not
   behaviour; paginate only when the next page can answer the question.
9. Select one focus with `triage-select --item/--source/--match`,
   `--question` and `--priority high|normal|low`. Before reading that question,
   load `js-behavior-reconstruction` and its commands reference so the output
   contract is known while gathering evidence; these are analysis-phase calls,
   not additional pre-analysis guidance. Read it with
   `read-code --match|--source|--item [--bytes N]`. A redaction marker is a
   visibility gap, never permission to infer the hidden value.
10. After a delivered read, use
    `triage-update <span_id> --state inspected --read-id <read_id>`.
    `deferred` requires a reason and `unresolved` requires the missing
    evidence/context. Never mark inspected from a match, prepared response,
    failed confirmation or unrelated partial window.
11. Follow concrete identifiers, request construction, state transitions and
    callers only as needed. Use one supported `acquire-reference` only when the
    selected question needs an explicit child absent from available code; do
    not acquire children routinely or expand recursively.
12. For a question with useful supported reads, follow the already-loaded
    `js-behavior-reconstruction`, trace only the additional code needed, and
    save one compact partial `behavior-save` record before protected closure.
    Prefer a saved coherent partial answer before opening or deepening another
    question. Missing evidence is a gap, never a reason to invent a step.
    Return to `triage-list` for the next priority. A valid record cites only
    delivered reads and remains reconstructed, not runtime-observed.
13. Finish with `triage-list`, retaining discovered/inspected/deferred/
    unresolved states, cursors and unvisited coverage. Account for selected
    spans or leave them explicitly pending. Do not publish final YAML. Keep
    free-form notes below 1500 characters and record IDs, questions, decisions,
    priorities and gaps rather than source text.
