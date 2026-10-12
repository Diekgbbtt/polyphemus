# ADR: the Assigner degrades to `no_surface` instead of escalating to the firehose

Status: accepted (2026-10-12).

## Context

The comfyui analysis-only run stalled on one Service and proposed zero
aggregates for another.
The assigner is L1-unit-first: given one Service and its `contract`, it
DISCOVERS its own surface through `graph_view` and the HTTP-history pair.
When `graph_view` found nothing for a Manager Service, the prompt told the model
to "HARVEST AGGRESSIVELY ... query BROADLY ... query BROADLY and AGGRESSIVELY",
so it fell back to `search_http_history`.
Each call returned about 250 KB (full URLs, max 3,546 chars), the context blew
to 422k-681k tokens, and the run stalled.

The root of the blowout is the missing surface (W-c): no query could find an
endpoint the crawl never captured.
The assigner's failure was that it had no way to CONCLUDE "the surface is
absent" - its only move on finding nothing was to search wider.

## Decision

The Assigner's workflow gains an ABSENT-SURFACE degradation branch, and the
harvest is bounded.

1. **The harvest is surgical, not aggressive**
   (`analysis/prompts/assigner-batched-l1unit-first.md`).
   `graph_view` is queried narrowly, one bounded probe per contract-derived
   candidate.
   `search_http_history` is called ONLY with a url-path filter derived from the
   contract; a call with no path filter returns the firehose, not the Service's
   surface, and is refused by the discipline.
   A candidate that finds nothing is a valid miss; the model must NOT widen a
   search that found nothing.

2. **The chain HALTS before `candidate_owners` when nothing survives**
   (`analysis/assigner.py`).
   `_halt_without_surface` is the `halt_when` predicate: after `falsify_harvest`,
   if no harvested Endpoint survived (verdict `survive`), the chain stops, so
   `candidate_owners`/`assign` never run on an empty premise.
   This covers both "the harvest found nothing" and "everything was falsified
   away".

3. **The outcome is observable.**
   `AssignmentOutcome.no_surface` records the degradation as a FINDING (the
   Service's surface is not mapped), distinct from a failed search, and the
   assigner logs one line naming it.

The named failure mode in the eval vocabulary is `surface_gap`
(`src/polymerhus/eval`/`eval/CONTEXT.md`), of which this is the analysis-layer
expression.

## Consequences

- An absent surface costs a bounded harvest plus two turns, never a full-context
  firehose and a stall.
- A degraded Service is no longer indistinguishable from a model that found
  nothing: `no_surface` is explicit.
- The chain's turn count now depends on the harvest: when nothing survives, two
  sub-problems run (`harvest_surface`, `falsify_harvest`), not six.
  Tests that stub the invoke seam must return a per-sub-problem turn (as a real
  model does), not one turn for every step.
- This does NOT recover the missing surface; it makes the assigner honest about
  its absence. Recovering the surface is #353 (client-side routes behind a UI
  tab).
