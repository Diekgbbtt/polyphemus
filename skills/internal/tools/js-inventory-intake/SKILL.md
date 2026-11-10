---
name: js-inventory-intake
description: >-
  Interpret the crawler JavaScript inventory and select a bounded acquisition batch when starting or resuming a JS context.
metadata:
  version: '1.1'
---

Read `reference js-inventory-intake commands` through the supplied Exec CLI prefix for exact recipes.

1. Read `context`, then `notes` before selecting work. Check project/run, authorised domains and the explicit auth context against the supplied binding. Missing context is a gap; never guess anonymous. Notes from previous invocations carry selected/pending IDs, reasons and the remaining cursor.
2. Immediately after context/notes, load `js-evidence-triage`, its
   `commands` and `priorities` references, and make one bounded
   `triage-list` call. This early guidance resumes the existing shortlist and
   prepares evidence-seeking questions. It is planning, not code analysis:
   it consumes attempts but does not start the protected triage phase. Return
   to this inventory procedure; do not search or read code yet.
3. Read `inventory --limit 5`; continue with `--cursor <next_cursor>` within
   the runner budget. Report `coverage_gap`, failed/partial/unknown pods,
   missing inventory and any remaining page cursor. Do not report completion
   while pages remain, or treat a failed reference as an empty successful
   inventory.
4. Rank a bounded batch no larger than the supplied batch limit. The maximum
   is not a quota: select fewer when coverage, priority or budget justifies
   it. Prefer browser-requested application leads, then crawler-discovered
   leads and useful path probes; status/MIME and inventory evidence help rank.
   Vendor/runtime names lower priority but never exclude a lead by themselves.
   Browser-requested means requested during the crawl, not successfully
   executed. Katana discovery and ffuf probes do not prove browser use. Names
   alone cannot establish imports or relationships.
5. Before acquisition, record selected IDs, priorities, reasons, deferred
   IDs/reasons, coverage gaps and next cursor in `note --text '...'`. When the
   available evidence supports a question, pair it with a mechanism and the
   inventory/structure/scan clue it came from. Do not invent questions to fill
   a quota. Keep identical URLs in different auth contexts separate. Never
   write URLs with private values, credentials, source or browser cookies into
   notes. Budget unused pages as uncovered, not empty.
6. Load `js-code-acquisition` for this selection. That handoff continues
   through acquisition, scanning, source recovery and bundle structure; this
   skill owns selection only and does not end the run. Leave enough attempts
   for the selected leads, actual triage and a final resumption note. If
   access or budgets block work, stop with the pending IDs/cursor and named
   gap.

Do not perform acquisition or scan inside this skill. Broad crawling, code inspection, source-body reading and behavioural publication remain outside the complete micro-workflow.
