---
name: js-behavior-reconstruction
description: >-
  Reconstruct one selected client-side behaviour from delivered reads and persist a concise evidence-linked record in run notes.
metadata:
  version: '1.1'
---

Load this skill after selecting one shortlist question and before reading or
deeply tracing it, so its output contract guides evidence collection. Work
inside the shared analysis budget and return to triage after each saved record
or explicit gap.

1. Read `reference js-behavior-reconstruction commands` and
   `reference js-behavior-reconstruction methodology`. Resume
   `behavior-list --limit 5` when notes are already underway. An initial
   behaviour list is planning and does not by itself start analysis.
2. Start from the selected `span_id` and question from `triage-list`. Follow
   its trigger/input, value origins and transformations, request/state/sink,
   response/error handling and client effects. Use bounded `read-code` and
   exact `search-code` only when the next read can resolve the question. Any
   search/read/selection/save is analysis work.
3. A factual step must cite one or more actually delivered `read_id` values.
   Copy the exact returned ID; do not shorten, reconstruct or pad it. A source,
   span or search ID is not a read receipt. Cite only evidence you received.
   A valid read ID proves delivery, not the
   truth of a statement; neighbouring or cross-file reads are allowed when
   relevant, with their source/hash/range provenance retained by the receipt.
4. Keep distinct conditional, asynchronous and error paths separate. Do not
   collapse an HTTP response, later socket event and local effect into one
   unconditional sequence unless reads establish that ordering.
5. Save one compact partial record as soon as the question has useful supported
   evidence, before opening or deepening another question. If the evidence is
   insufficient, record the specific missing link rather than inventing a step.
   Submit only:
   `question_ref`, `steps`, `assumptions` and `gaps`. Do not repeat question
   text or source code. Keep supported assumptions evidence-linked and leave
   unknown runtime/server conditions explicitly `unverified`.
   The record allows 4,096 canonical JSON bytes including keys and repeated IDs.
   Preserve decisive conditions, error handling and asynchronous ordering; remove
   duplicate prose and metadata instead of compressing them into false certainty.
6. `steps` use only trigger, input, transform, call, request, sink, response,
   error or effect. Every step has concise text and nonempty delivered read
   IDs. An empty explanation is not a reconstruction.
7. Use `behavior-save --record '<JSON>'`. A same-question retry with identical
   content is idempotent; changed content appends a new revision. A failed or
   unacknowledged save is not persisted success and may be retried once the
   outcome is checked. The command automatically retains complete files behind
   cited delivered reads; nominate an extra dependency only when an authorized
   item/source/match is indispensable and include a short rationale.
   Explicit size errors include actual/max byte counts. Read errors identify
   the submitted field positions; correct them from delivered reads rather than
   repeatedly shortening unrelated prose. After uncertain delivery use
   `behavior-list` before retrying. Retried commands consume the same budget.
8. Treat output as `reconstructed`, never runtime-observed. Do not assert
   server-side authorization/validation, cookie security flags or JWT forgery
   from client code. Name unread callees, unresolved values, redaction
   visibility, runtime uncertainty and missing server evidence in `gaps`.
9. A saved record and evidence retention are separate outcomes. Treat only
   `retention.status=complete` as verified archive availability; report pending,
   partial or gap outcomes without claiming the bytes were retained. Do not
   issue manual archive-transfer commands.
10. After a saved record, return to `triage-list`/the next priority decision.
    Do not exhaust the entire shortlist before considering a save.
    `behavior-list` shows current revisions and retention status; it is not final
    YAML publication.
11. Do not write graph data or final YAML, execute target code, probe the
    browser/endpoint or expand scope. Stop with a saved partial record plus
    gaps, or a named reason reconstruction could not proceed.
