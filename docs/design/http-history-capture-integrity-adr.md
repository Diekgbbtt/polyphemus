# ADR: the HTTP-history capture gate drops scanner traffic, not the response

Status: accepted (2026-10-12).

## Context

The comfyui analysis-only run stalled on one Service and proposed zero
aggregates for another.
The root cause was a context blowout: the assigner fell back to
`search_http_history` when `graph_view` found nothing, and each call returned
about 250 KB.
The store held 110,809 URLs, maximum 3,546 chars, 13,011 over 1 KB, 36.8 MB
total.
The giant URLs were parameter-mining artifacts (`/api/features?slq=111252&...`)
and path-fuzzing artifacts (`/api/AAAA...`), not the navigational surface.
The store also contained the recon toolchain's own update traffic
(`api.pdtm.sh`), attributed to the project because the tool ran inside the
lease.

Two candidate fixes were weighed:

1. Bound the `search_http_history` response (truncate the URL, cap the bytes).
2. Stop the scanner traffic entering the store at all.

Option 1 trades away row precision, and it treats the symptom: a store full of
scanner noise still misleads every reader, not only the one that overflowed.

## Decision

The gate is at CAPTURE, not at the response, and it is a deterministic
content-shape predicate over the request.

1. **Fuzzing gate** (`kali/http_history/normalize.py::is_fuzzing_request`).
   A request is dropped when its query-parameter count exceeds
   `KALI_HTTP_FUZZ_MAX_QUERY_PARAMS` (default 30) or a single path segment
   exceeds `KALI_HTTP_FUZZ_MAX_PATH_SEGMENT` (default 80).
   A non-positive bound disables that half.
   The addon bumps `excluded_fuzzing` in `proxy_status()`, exactly as
   `excluded_websocket` does.

2. **Toolchain-host gate** (`normalize.py::is_excluded_host`).
   A request whose host is one of the recon toolchain's own hosts is dropped.
   The hosts are the suffix list `KALI_HTTP_EXCLUDE_HOSTS` (default `pdtm.sh`).
   The addon bumps `excluded_tooling`.

3. **Scope is enforced at BOTH ends.**
   Capture: an uncorrelated flow lands in the reserved `unscoped` store, which
   project-scoped queries refuse; the toolchain-host gate removes the traffic
   that would otherwise correlate through a lease.
   Query: `HttpHistoryService._guard_project` refuses an empty `project_id` and
   the reserved `unscoped` project, and the store is per-project, so one
   project can never read another's artifacts (tests
   `test_search_rejects_the_reserved_unscoped_project`,
   `test_cross_project_get_is_not_found`).

The proxy is at the network interface, so it cannot see which local process
produced a flow; a source-tool denylist is infeasible there.
A content-shape predicate is therefore the only reliable capture-side gate, and
it is the one taken.

## Consequences

- The store holds only in-scope navigational traffic, so a reader's context is
  bounded by the real surface, not by scanner noise.
- The predicate is conservative: an ordinary route with a handful of
  parameters, or a normal path, is never dropped.
- The thresholds are configurable, so a target with legitimately wide query
  strings can raise them.
- This does NOT recover surface the crawl never reached (the ComfyUI-Manager
  API); that is a separate question (see
  `docs/design/surface-integrity-degradation-plan.md` W-c).
- Flows already in a live store are not rewritten; the store is re-derivable and
  the eval re-runs the crawl.
